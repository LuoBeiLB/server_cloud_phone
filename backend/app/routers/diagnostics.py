"""系统自检（/api/diagnostics）—— 一键 docker 部署的甲方自助排障入口。

存在的意义：甲方是 `docker compose up` 跑起来的，出问题时既不熟 docker 也进不了
宿主机。原先只有 `/api/health` 返回 `{"status":"ok"}`，「云手机拉不起来」「操作没反应」
这类问题只能靠人来现场翻日志。这里把所有已知前置条件逐项实测，每项给出：

    status(ok|warn|fail|unknown|skip) + 实测值 + 原因 + 可执行的处置

⚠️ 关于探测位置的诚实说明（很重要）：
本模块运行在**后端进程内**。若后端跑在容器里且未挂载宿主 /dev、未用 network_mode: host，
那么 /dev/binderfs、/dev/dri 这类宿主内核设施在容器内**本来就看不到** —— 此时结果是
`unknown` 而不是 `fail`，并会明确告诉用户「这里看不到不等于宿主没有，请在宿主机自行确认」。
把假阴性报成 fail 比不报更糟：会把人引到错误的方向去改内核。
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import Device, DeviceStatus

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"], dependencies=[Depends(get_current_user)])

# 严重程度排序，用于汇总 overall
_RANK = {"ok": 0, "skip": 0, "unknown": 1, "warn": 2, "fail": 3}

# 后端是否跑在容器里 —— 决定 /dev 探测失败该报 fail 还是 unknown
_IN_CONTAINER = os.path.exists("/.dockerenv")
_WHERE = "后端容器内" if _IN_CONTAINER else "宿主机"


def _check(
    key: str,
    name: str,
    status: str,
    value: str = "",
    reason: str = "",
    hint: str = "",
) -> dict:
    return {
        "key": key,
        "name": name,
        "status": status,
        "value": value,
        "reason": reason,
        "hint": hint,
    }


async def _run(*args: str, timeout: float = 5.0) -> tuple[int, str, str]:
    """跑一条命令，带超时。自检绝不能因为某条命令挂住而整体卡死或抛异常。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        return 127, "", f"命令不存在：{args[0]}"
    except Exception as e:  # noqa: BLE001
        return 126, "", f"无法执行 {args[0]}：{e.__class__.__name__}: {e}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        # 坑：进程可能已经自己退了，此时 kill() 抛 ProcessLookupError。
        # 自检端点因为「探测超时」而 500 是最糟的结果 —— 必须兜住。
        try:
            proc.kill()
            await proc.wait()
        except Exception:  # noqa: BLE001
            pass
        return 124, "", f"命令超时（>{timeout}s）：{' '.join(args)}"
    except Exception as e:  # noqa: BLE001
        return 126, "", f"读取 {args[0]} 输出失败：{e.__class__.__name__}: {e}"
    return (
        proc.returncode or 0,
        out.decode(errors="replace").strip(),
        err.decode(errors="replace").strip(),
    )


async def _adb_server_up() -> None:
    """先用 DEVNULL 显式起 adb server。

    坑（与 orchestrator/redroid.py 同一个）：adb 客户端发现 server 不在会自动 fork 一个
    常驻 server，子进程**继承调用方的 stdout/stderr 管道** → communicate() 永远等不到
    EOF → 探测挂住直到超时。所以必须先用 DEVNULL 把 server 拉起来。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "adb",
            "start-server",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=10)
    except Exception:  # noqa: BLE001
        pass  # 起不来的话下面 adb devices 自会报错，这里不必打断自检


# --------------------------------------------------------------------------
# 各项检查
# --------------------------------------------------------------------------


async def _check_database(db: AsyncSession) -> dict:
    driver = settings.database_url.split("://", 1)[0]
    try:
        t0 = time.monotonic()
        await db.execute(text("SELECT 1"))
        ms = (time.monotonic() - t0) * 1000
        n = (await db.execute(text("SELECT count(*) FROM devices"))).scalar()
        return _check(
            "database", "数据库连通", "ok", f"{driver}，往返 {ms:.0f}ms，devices 表 {n} 行"
        )
    except Exception as e:  # noqa: BLE001
        return _check(
            "database",
            "数据库连通",
            "fail",
            driver,
            f"{e.__class__.__name__}: {e}",
            "compose 部署：docker compose ps 看 postgres 是否 healthy；"
            "确认 CLOUD_DATABASE_URL 指向的主机名在同一网络内可解析",
        )


async def _check_redis() -> dict:
    """裸 RESP PING —— 不引入 redis 客户端依赖。

    当前 demo 后端并不强依赖 Redis，所以连不上只算 warn，不算 fail。
    """
    url = getattr(settings, "redis_url", "") or os.environ.get("CLOUD_REDIS_URL", "")
    if not url:
        return _check("redis", "Redis", "skip", "未配置", "", "当前版本后端不强依赖 Redis")
    u = urlparse(url)
    host, port = u.hostname or "127.0.0.1", u.port or 6379
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=3
        )
        writer.write(b"PING\r\n")
        await writer.drain()
        resp = await asyncio.wait_for(reader.read(16), timeout=3)
        writer.close()
        if resp.startswith(b"+PONG"):
            return _check("redis", "Redis", "ok", f"{host}:{port} PONG")
        return _check(
            "redis", "Redis", "warn", f"{host}:{port}", f"回应异常：{resp!r}", "确认该端口确实是 Redis"
        )
    except Exception as e:  # noqa: BLE001
        return _check(
            "redis",
            "Redis",
            "warn",
            f"{host}:{port}",
            f"{e.__class__.__name__}: {e}",
            "当前版本后端不强依赖 Redis，可暂不处理；如需启用请确认容器在跑且网络可达",
        )


def _probe_host_via_docker() -> dict | None:
    """借 docker.sock 起一个只读探针容器，去看**宿主**的内核事实。

    为什么必须这么做：后端跑在容器里时，binder / /dev/dri / SELinux 这些宿主内核设施
    在容器命名空间内看不见，只能报「无法判定」。结果是**每一次正常部署都永远显示
    「总体：无法判定」**，甲方看到灰色徽标以为有问题 —— 自检反而成了噪音源。

    注意一个我先前搞错的判据：`/proc/filesystems` 里没有 selinuxfs **不代表**内核不支持。
    Ubuntu 默认用 AppArmor，SELinux 编译进内核但未在启动时启用，selinuxfs 就不会注册；
    实测这种环境 redroid 照样正常启动。真正的判据是 `/boot/config-$(uname -r)` 里的
    CONFIG_SECURITY_SELINUX=y —— 那在容器里读不到，只能靠挂宿主根目录的探针容器。

    返回 None 表示探测不可用（无 docker / 非 redroid 模式），调用方退回「无法判定」。
    """
    if settings.device_backend != "redroid":
        return None
    try:
        import socket

        import docker  # noqa: PLC0415

        client = docker.from_env()
        client.ping()
        # 用后端自己的镜像做探针：一定在本地、一定有 sh，无需额外拉取
        me = client.containers.get(socket.gethostname())
        script = (
            'for p in /host/dev/binderfs/binder /host/dev/binder '
            '/host/dev/hwbinder /host/dev/dri/renderD128; do '
            '[ -e "$p" ] && echo "DEV $p"; done; '
            'grep -qw binder /host/proc/filesystems && echo "FS binderfs"; '
            'grep -qw selinuxfs /host/proc/filesystems && echo "FS selinuxfs"; '
            '[ -d /host/sys/fs/selinux ] && echo "DIR selinux"; '
            'grep -h "^CONFIG_SECURITY_SELINUX=y" /host/boot/config-$(uname -r) '
            '2>/dev/null && echo "CFG selinux"; '
            'echo "CGROUP $(stat -fc %T /host/sys/fs/cgroup 2>/dev/null)"; '
            'grep -c "^cgroup " /host/proc/self/mountinfo 2>/dev/null | '
            'sed "s/^/CGROUPV1 /"'
        )
        out = client.containers.run(
            me.image.id,
            command=["sh", "-c", script],
            remove=True,
            privileged=True,
            network_mode="none",
            volumes={"/": {"bind": "/host", "mode": "ro"}},
            stdout=True,
            stderr=False,
        )
        return {"raw": out.decode(errors="replace")}
    except Exception:  # noqa: BLE001
        return None  # 探针起不来就退回「无法判定」，绝不因此让自检失败


def _check_dev_node(host: dict | None, key: str, name: str, paths: list[str], fail_hint: str) -> dict:
    """探测内核设备节点。优先用宿主探针结果；拿不到且在容器内时报 unknown 而非 fail。"""
    if host:
        raw = host["raw"]
        hit = [p for p in paths if f"DEV /host{p}" in raw]
        if key == "binder" and "FS binderfs" in raw:
            hit.append("内核支持 binderfs")
        if hit:
            return _check(key, name, "ok", "宿主探针实测：" + "、".join(hit))
        # /dev/dri 缺失在软件渲染（guest）下是**预期**，不是故障 ——
        # 服务器 CPU 多数无核显，本来就该跑 guest；报成 fail 会让正常部署一直红着。
        if key == "dri" and settings.redroid_gpu_mode != "host":
            return _check(
                key, name, "ok",
                f"宿主无 /dev/dri，当前 CLOUD_REDROID_GPU_MODE={settings.redroid_gpu_mode}（软件渲染），符合预期",
                "", "要硬件渲染需宿主有核显/显卡且设 CLOUD_REDROID_GPU_MODE=host（部署手册 §1.1）",
            )
        return _check(key, name, "fail", f"宿主上不存在 {' / '.join(paths)}", "宿主缺少该内核设施", fail_hint)
    found = [p for p in paths if os.path.exists(p)]
    if found:
        return _check(key, name, "ok", f"{_WHERE}探测到 {', '.join(found)}")
    if _IN_CONTAINER:
        return _check(
            key,
            name,
            "unknown",
            f"{_WHERE}未探测到 {' / '.join(paths)}",
            "后端跑在容器里，宿主的内核设备在容器命名空间内本来就不可见，"
            "**据此不能判定宿主缺失**",
            f"请在宿主机上直接执行：ls -l {paths[0]}；确实没有再按以下处置："
            f"{fail_hint}",
        )
    return _check(key, name, "fail", f"未探测到 {' / '.join(paths)}", "宿主缺少该内核设施", fail_hint)


def _check_selinux(host: dict | None = None) -> dict:
    """Android init 必须 mount selinuxfs —— 内核没编译 SELinux 时 redroid 起不来。

    实测（2026-07-30，OrbStack aarch64 内核 7.0.11）：binder 三件套齐全、镜像也拉到了，
    但容器起来约 170ms 就被 SIGHUP 打死（退出码 129）、docker logs 全空。
    宿主 dmesg 里的第一条致命错误是：
        init: mount("selinuxfs", "/sys/fs/selinux", "selinuxfs", 0, NULL) failed
    这一条比 binder 更靠前，缺了它连日志都来不及输出，光看 docker logs 完全无从下手，
    所以必须单独探测并报出来。
    """
    if host:
        raw = host["raw"]
        if "CFG selinux" in raw or "DIR selinux" in raw or "FS selinuxfs" in raw:
            why = ("内核 CONFIG_SECURITY_SELINUX=y" if "CFG selinux" in raw
                   else "宿主已挂载 selinuxfs")
            return _check("selinux", "SELinux", "ok", f"宿主探针实测：{why}")
        return _check(
            "selinux", "SELinux", "fail", "宿主内核未编译 SELinux",
            "Android init 第一步就要 mount selinuxfs，失败会立刻被 SIGHUP 打死"
            "（容器退出码 129 且无任何日志），**应用层无法绕过**",
            "换用发行版官方内核（Ubuntu 22.04/24.04 均带 SELinux，即便默认用 AppArmor）",
        )
    if os.path.exists("/sys/fs/selinux"):
        return _check("selinux", "SELinux（selinuxfs）", "ok", f"{_WHERE}探测到 /sys/fs/selinux")
    has_fs = False
    try:
        with open("/proc/filesystems", encoding="utf-8") as f:
            has_fs = "selinuxfs" in f.read()
    except Exception:  # noqa: BLE001
        pass
    if has_fs:
        return _check(
            "selinux",
            "SELinux（selinuxfs）",
            "ok",
            "内核支持 selinuxfs（当前未挂载，Android init 会自行挂载）",
        )
    status = "unknown" if _IN_CONTAINER else "fail"
    return _check(
        "selinux",
        "SELinux（selinuxfs）",
        status,
        f"{_WHERE}未探测到 /sys/fs/selinux，且 /proc/filesystems 无 selinuxfs",
        "内核未编译 SELinux。Android init 第一步就要 mount selinuxfs，失败会立刻被 SIGHUP "
        "打死（容器退出码 129 且无任何日志），**应用层无法绕过**"
        + ("；容器内探测不到不完全等于宿主缺失，但 /proc/filesystems 是共享的，可信度高" if _IN_CONTAINER else ""),
        "换用发行版官方内核（Ubuntu 22.04/24.04 已编译 SELinux，即使默认用 AppArmor 也有 "
        "selinuxfs）。轻量虚拟化环境的裁剪内核（如 macOS 上的 OrbStack/Colima）通常没有，"
        "不能用于跑真机 —— 真机务必在 x86_64 Linux 宿主上部署，见部署手册第 2 章",
    )


def _check_cgroup(host: dict | None = None) -> dict:
    """Android 12 的 init 会尝试挂 cgroup v1 控制器；纯 v2 环境会报 Unknown subsys name。

    ⚠️ 容器内的 /proc/self/mountinfo 反映的是**容器自己的 cgroup 命名空间**，
    判断不了宿主的层级模式（实测过：宿主是纯 v2、dmesg 明确报了
    `cgroup: Unknown subsys name 'memory'`，而后端容器内看到的却是 v1 挂载）。
    所以在容器里只能报 unknown —— 与 binder/dri/selinux 同一条规矩：
    判断不了就不许报 ok，否则自检会给出误导性的绿灯。
    """
    if host:
        raw = host["raw"]
        m = re.search(r"CGROUP (\S+)", raw)
        v1 = re.search(r"CGROUPV1 (\d+)", raw)
        fstype = m.group(1) if m else "?"
        n_v1 = int(v1.group(1)) if v1 else 0
        if n_v1 > 0 or fstype != "cgroup2fs":
            return _check("cgroup", "cgroup 层级", "ok",
                          f"宿主探针实测：{fstype}，v1 挂载点 {n_v1} 个")
        return _check(
            "cgroup", "cgroup 层级", "warn", f"宿主为纯 cgroup v2（{fstype}）",
            "Android 12 的 init 会尝试挂 cgroup v1 的 memory 控制器，纯 v2 下会失败"
            "（宿主 dmesg 出现 `cgroup: Unknown subsys name 'memory'`）。"
            "实测多数情况下实例仍能启动，故只报注意",
            "如实例起不来，Ubuntu 可加内核参数 systemd.unified_cgroup_hierarchy=0 后重启",
        )
    hint = (
        "在宿主机执行 `stat -fc %T /sys/fs/cgroup`：cgroup2fs 表示纯 v2。"
        "Ubuntu 可加内核参数 systemd.unified_cgroup_hierarchy=0 后重启切回混合层级"
    )
    if _IN_CONTAINER:
        return _check(
            "cgroup",
            "cgroup 层级",
            "unknown",
            "后端在容器内，看到的是容器自己的 cgroup 命名空间",
            "无法据此判断宿主是纯 cgroup v2 还是 v1/v2 混合。Android 12 的 init 会尝试挂 "
            "cgroup v1 的 memory 控制器，纯 v2 环境下宿主 dmesg 会出现 "
            "`cgroup: Unknown subsys name 'memory'`",
            hint,
        )
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as f:
            mi = f.read()
        v2_only = " cgroup2 " in mi and " cgroup " not in mi
    except Exception as e:  # noqa: BLE001
        return _check("cgroup", "cgroup 层级", "unknown", "", f"读取失败：{e}")
    if v2_only:
        return _check(
            "cgroup",
            "cgroup 层级",
            "warn",
            "宿主仅挂载 cgroup v2（unified）",
            "Android 12 的 init 会尝试挂 cgroup v1 的 memory 控制器，纯 v2 环境下会失败。"
            "多数发行版同时提供 v1 混合层级，轻量虚拟化环境常只有 v2",
            hint,
        )
    return _check("cgroup", "cgroup 层级", "ok", "宿主存在 cgroup v1 层级，Android init 可正常挂载")


async def _check_adb() -> dict:
    code, out, err = await _run("adb", "version")
    if code != 0:
        return _check(
            "adb",
            "adb 可用性",
            "fail",
            "",
            err or f"退出码 {code}",
            "后端镜像已预装 adb；若在宿主机运行请 sudo apt install -y adb",
        )
    ver = out.splitlines()[0] if out else "未知版本"
    if settings.device_backend != "redroid":
        return _check("adb", "adb 可用性", "ok", f"{ver}（simulator 模式不使用）")
    await _adb_server_up()  # 必须先起 server，否则 adb devices 会挂住（见 _adb_server_up 注释）
    code, out, err = await _run("adb", "devices", timeout=10)
    lines = [l for l in out.splitlines()[1:] if l.strip()] if code == 0 else []
    if not lines:
        return _check(
            "adb",
            "adb 可用性",
            "warn",
            f"{ver}，当前已连设备 0 台",
            "adb 能跑，但没有任何设备连上",
            "若设备列表里没有运行中的真机，先建机；已有设备却连不上，"
            "多为实例未开机完成或 CLOUD_REDROID_NETWORK 与实际 docker 网络不一致"
            "（docker network ls 确认，默认 cloud_default）。"
            "注意本项目用 CLOUD_REDROID_ADB_MODE=container 经容器名连接，**不需要** network_mode: host",
        )
    return _check("adb", "adb 可用性", "ok", f"{ver}，已连 {len(lines)} 台：{'; '.join(lines)}")


async def _check_docker_and_image() -> list[dict]:
    """Docker daemon + redroid 镜像。仅 redroid 模式有意义。"""
    if settings.device_backend != "redroid":
        return [
            _check(
                "docker",
                "Docker daemon",
                "skip",
                "simulator 模式不需要",
                "",
                "切换真机后端需设 CLOUD_DEVICE_BACKEND=redroid 并挂载 docker.sock",
            )
        ]
    try:
        import docker  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return [
            _check(
                "docker",
                "Docker daemon",
                "fail",
                "",
                f"Docker SDK 未安装：{e}",
                "requirements.txt 里 docker 包带 platform_system=='Linux' 标记，"
                "非 Linux 镜像不会安装；真机后端必须在 Linux 上运行",
            )
        ]

    def _probe() -> tuple[dict, dict | None]:
        client = docker.from_env()
        client.ping()
        info = client.version()
        try:
            img = client.images.get(settings.redroid_image)
            return info, {"id": img.short_id, "tags": img.tags}
        except Exception:  # noqa: BLE001
            return info, None

    try:
        info, img = await asyncio.to_thread(_probe)
    except Exception as e:  # noqa: BLE001
        from ..orchestrator.redroid import _explain_docker_error

        reason, hint = _explain_docker_error(e)
        return [
            _check("docker", "Docker daemon", "fail", "", reason, hint),
            _check(
                "redroid_image",
                "redroid 镜像",
                "unknown",
                "",
                "Docker 不可用，无法查询镜像",
                f"修好 Docker 后确认：docker images | grep {settings.redroid_image}",
            ),
        ]

    checks = [
        _check(
            "docker",
            "Docker daemon",
            "ok",
            f"版本 {info.get('Version')}，API {info.get('ApiVersion')}",
        )
    ]
    if img:
        checks.append(
            _check("redroid_image", "redroid 镜像", "ok", f"{settings.redroid_image}（{img['id']}）")
        )
    else:
        checks.append(
            _check(
                "redroid_image",
                "redroid 镜像",
                "fail",
                f"{settings.redroid_image} 本地不存在",
                "镜像未拉取，建机时会直接失败",
                f"docker pull {settings.redroid_image}"
                "（国内网络先配镜像加速器，见部署手册 §3.2）",
            )
        )
    return checks


def _check_disk() -> dict:
    path = settings.redroid_data_dir if os.path.isdir(settings.redroid_data_dir) else "/"
    try:
        usage = shutil.disk_usage(path)
    except Exception as e:  # noqa: BLE001
        return _check("disk", "磁盘空间", "unknown", path, f"{e.__class__.__name__}: {e}")
    free_gb = usage.free / 1024**3
    total_gb = usage.total / 1024**3
    value = f"{path} 剩余 {free_gb:.1f} GB / 共 {total_gb:.1f} GB"
    # 每台实例 /data 约 2–6 GB，低于 20 GB 基本没法再建机
    if free_gb < 5:
        return _check(
            "disk", "磁盘空间", "fail", value, "磁盘即将耗尽，建机与容器写入都会失败",
            "清理磁盘或 docker system prune -a；每台实例的 /data 约需 2–6 GB",
        )
    if free_gb < 20:
        return _check(
            "disk", "磁盘空间", "warn", value, "按每台 2–6 GB 估算，最多只够再建几台",
            "扩容数据盘，或清理不用的实例与镜像",
        )
    return _check("disk", "磁盘空间", "ok", value)


def _check_memory() -> dict:
    """从 /proc/meminfo 读可用内存。容器内读到的通常是宿主的值。"""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            meminfo = {
                k.strip(): v.strip() for k, v in (l.split(":", 1) for l in f if ":" in l)
            }
        avail_gb = int(meminfo["MemAvailable"].split()[0]) / 1024**2
        total_gb = int(meminfo["MemTotal"].split()[0]) / 1024**2
    except Exception as e:  # noqa: BLE001
        return _check("memory", "内存", "unknown", "", f"读 /proc/meminfo 失败：{e}")
    # 生产按 1.5 GiB/台 规划
    can_host = int(avail_gb / 1.5)
    value = f"可用 {avail_gb:.1f} GB / 共 {total_gb:.1f} GB，按 1.5 GB/台 约可再起 {can_host} 台"
    if avail_gb < 2:
        return _check(
            "memory", "内存", "fail", value, "可用内存不足，新起的实例会被 OOM 杀掉",
            "停掉部分实例或加内存；单实例稳态约 606 MiB，规划按 1.5 GiB/台（见部署手册 §1.3）",
        )
    if can_host < 2:
        return _check(
            "memory", "内存", "warn", value, "余量只够再起 1 台",
            "按 1.5 GiB/台 规划内存，避免启动风暴（见部署手册 §1.3）",
        )
    return _check("memory", "内存", "ok", value)


async def _check_devices(db: AsyncSession) -> list[dict]:
    """设备侧一致性：库里标记异常的、以及「库说在跑但容器已经没了」的。"""
    from sqlalchemy import select

    devices = list((await db.execute(select(Device))).scalars().all())
    checks: list[dict] = []

    broken = [d for d in devices if d.last_error]
    if broken:
        detail = "；".join(f"#{d.id} {d.name}：{(d.last_error or '')[:160]}" for d in broken[:5])
        more = f"（另有 {len(broken) - 5} 台，详见设备列表）" if len(broken) > 5 else ""
        checks.append(
            _check(
                "devices_error",
                "设备失败记录",
                "fail" if len(broken) == len(devices) and devices else "warn",
                f"{len(broken)}/{len(devices)} 台有失败记录",
                detail + more,
                "每台的具体原因与处置已写在设备的 last_error 里，前端设备列表可直接查看",
            )
        )
    else:
        checks.append(
            _check("devices_error", "设备失败记录", "ok", f"{len(devices)} 台，无失败记录")
        )

    # 库中状态 vs 容器真实状态（仅 redroid 且 docker 可用时才有意义）
    running = [d for d in devices if d.status == DeviceStatus.running]
    if settings.device_backend != "redroid":
        checks.append(
            _check(
                "device_consistency",
                "状态一致性",
                "skip",
                f"simulator 模式，{len(running)} 台标记运行中",
                "",
                "simulator 没有真实容器，无需比对",
            )
        )
        return checks
    try:
        import docker  # noqa: PLC0415

        def _alive(refs: list[str]) -> dict[str, bool]:
            client = docker.from_env()
            client.ping()
            out = {}
            for ref in refs:
                try:
                    c = client.containers.get(ref)
                    c.reload()
                    out[ref] = c.attrs.get("State", {}).get("Running") is True
                except Exception:  # noqa: BLE001
                    out[ref] = False
            return out

        refs = [d.backend_ref for d in running if d.backend_ref]
        alive = await asyncio.to_thread(_alive, refs) if refs else {}
    except Exception as e:  # noqa: BLE001
        checks.append(
            _check(
                "device_consistency",
                "状态一致性",
                "unknown",
                f"{len(running)} 台标记运行中",
                f"无法查询容器状态：{e.__class__.__name__}",
                "先修好 Docker 项",
            )
        )
        return checks

    # 切换过设备后端的遗留数据：simulator 建的设备 backend_ref 形如 sim-<id>，
    # redroid 建的是 docker 容器 id。带着 sim- 引用去 docker inspect 必然 404
    # （报文形如 `No such container: sim-1`），这类设备在真机后端下**根本无效**，
    # 「停止再启动」救不回来 —— 必须删掉重建。早期版本把它和「容器被删」混为一谈，
    # 给出的处置是错的，实测在甲方现场造成了误导。
    stale_backend = [d for d in running if (d.backend_ref or "").startswith("sim-")]
    ghosts = [
        d
        for d in running
        if d not in stale_backend and not alive.get(d.backend_ref or "", False)
    ]
    if stale_backend:
        checks.append(
            _check(
                "device_backend_mismatch",
                "设备与后端不匹配",
                "fail",
                f"{len(stale_backend)}/{len(running)} 台是 simulator 模式下创建的",
                "、".join(f"#{d.id} {d.name}" for d in stale_backend[:8])
                + "（backend_ref 形如 sim-N，当前是真机后端，引用无效）",
                "这些是切换设备后端前的遗留数据，**停止/启动救不回来**：在设备列表里删掉它们，"
                "再用「批量建机」重新创建即可。常见来源是先在 simulator 模式下跑过冒烟测试。",
            )
        )
    if ghosts:
        checks.append(
            _check(
                "device_consistency",
                "状态一致性",
                "fail",
                f"{len(ghosts)}/{len(running)} 台库里标记运行中但容器已不在",
                "、".join(f"#{d.id} {d.name}" for d in ghosts[:8]),
                "容器没了但设备记录还在。先试「停止」再「启动」重建；"
                "若容器已被彻底删除（如 docker rm 过），删掉设备重新建机",
            )
        )
    else:
        checks.append(
            _check(
                "device_consistency", "状态一致性", "ok", f"{len(running)} 台运行中，容器状态一致"
            )
        )
    return checks


async def _check_functional(db: AsyncSession) -> list[dict]:
    """功能层探针（只读）。

    为什么需要：此前自检只查基础设施，全绿的同时「文件互传点进目录内容不变」
    「批量操作点了没反应」这类功能故障照样存在 —— 甲方看到「自检正常」反而更糊涂。
    这里挑几个**能自动判定对错**的功能点实测，专门盯「接口返回了但内容是错的」。
    """
    from sqlalchemy import select

    from .. import services

    checks: list[dict] = []
    device = (
        await db.execute(select(Device).where(Device.status == DeviceStatus.running).limit(1))
    ).scalars().first()
    if device is None:
        return [
            _check(
                "functional",
                "功能探针",
                "skip",
                "没有运行中的设备",
                "",
                "先建一台设备并启动，再回来自检可覆盖目录浏览与预览取帧",
            )
        ]

    # ① 目录浏览：不同目录必须返回不同内容。
    # 早期 simulator 的 list_files 直接忽略 path 参数，任何目录都返回同一份列表，
    # 表现为「点进子目录路径变了、内容纹丝不动」。这条检查专门守住它。
    try:
        root = await services.backend.list_files(device, "/sdcard/")
        sub = next((e["name"] for e in root if e.get("is_dir")), None)
        if sub is None:
            checks.append(
                _check("files", "目录浏览", "warn", "/sdcard/ 下没有子目录", "无法验证分层是否正确")
            )
        else:
            child = await services.backend.list_files(device, f"/sdcard/{sub}/")
            same = [e["name"] for e in root] == [e["name"] for e in child]
            if same:
                checks.append(
                    _check(
                        "files",
                        "目录浏览",
                        "fail",
                        f"/sdcard/ 与 /sdcard/{sub}/ 返回内容完全相同",
                        "后端 list_files 疑似忽略 path 参数。界面表现为：点进子目录后路径栏变了、"
                        "文件列表却纹丝不动，用户以为「点击没反应」",
                        "检查所用 device backend 的 list_files 是否按 path 分层返回",
                    )
                )
            else:
                checks.append(
                    _check(
                        "files",
                        "目录浏览",
                        "ok",
                        f"/sdcard/ {len(root)} 项，/sdcard/{sub}/ {len(child)} 项，分层正确",
                    )
                )
    except Exception as e:  # noqa: BLE001
        checks.append(
            _check(
                "files",
                "目录浏览",
                "warn",
                "",
                f"读取目录失败：{e}",
                "文件互传页会报同样的错；redroid 后端需设备 adb 可达",
            )
        )

    # ② 预览取帧：必须拿到可渲染的 data URL，而不是空串
    try:
        frame = await services.backend.screenshot(device)
        if not frame or not frame.startswith("data:image"):
            checks.append(
                _check(
                    "preview",
                    "预览取帧",
                    "fail",
                    f"返回值异常（前 40 字符：{str(frame)[:40]}）",
                    "预览帧不是 data URL，多画面预览与操控页都会显示占位图",
                    "检查后端 screenshot 实现；redroid 需 adb screencap 可用",
                )
            )
        else:
            checks.append(
                _check("preview", "预览取帧", "ok", f"设备 #{device.id} 取帧正常（{len(frame)} 字节）")
            )
    except Exception as e:  # noqa: BLE001
        checks.append(
            _check(
                "preview",
                "预览取帧",
                "fail",
                "",
                f"取帧失败：{e}",
                "多画面预览会一直显示「加载中…」占位图",
            )
        )

    return checks


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------


@router.get("")
async def diagnostics(db: AsyncSession = Depends(get_db)) -> dict:
    """逐项自检。任何一项都不会因异常中断整体结果。"""
    checks: list[dict] = [
        _check(
            "device_backend",
            "设备后端",
            "ok",
            f"{settings.device_backend}"
            + ("（模拟设备，不起真实容器）" if settings.device_backend == "simulator" else ""),
            "",
            "真机需 CLOUD_DEVICE_BACKEND=redroid，见部署手册第 5 章"
            if settings.device_backend == "simulator"
            else "",
        ),
        await _check_database(db),
        await _check_redis(),
    ]
    # 借 docker.sock 起只读探针容器看宿主内核事实；拿不到就退回「无法判定」
    host = await asyncio.to_thread(_probe_host_via_docker)
    checks += await _check_docker_and_image()

    if settings.device_backend == "redroid":
        checks.append(
            _check_dev_node(
                host,
                "binder",
                "内核 binder 模块",
                ["/dev/binderfs", "/dev/binder"],
                "sudo apt install -y linux-modules-extra-$(uname -r) && "
                'sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"；'
                "装了 extra 仍失败说明内核未编译 binder，必须换内核/发行版（部署手册第 2 章）",
            )
        )
        checks.append(
            _check_dev_node(
                host,
                "dri",
                "图形设备 /dev/dri",
                ["/dev/dri/renderD128", "/dev/dri"],
                "服务器 CPU 多数无核显（Xeon Scalable / EPYC 全系）。"
                "加装 Intel Arc A310/A380，或把 CLOUD_REDROID_GPU_MODE 设为 guest "
                "走软件渲染（部署手册 §1.1）",
            )
        )
        # 这两条比 binder 更靠前：缺 SELinux 时容器 170ms 就死且无任何日志
        checks.append(_check_selinux(host))
        checks.append(_check_cgroup(host))
    checks.append(await _check_adb())
    checks.append(_check_disk())
    checks.append(_check_memory())
    checks += await _check_devices(db)
    checks += await _check_functional(db)

    # overall 只由 warn/fail 决定。unknown 表示「这里测不到」而**不是「有问题」**，
    # 让它把总体拉成灰色会导致每次正常部署都显示「总体：无法判定」，
    # 与下面「所有检查项通过」的绿条自相矛盾（甲方现场就被这个误导过）。
    worst = max((_RANK.get(c["status"], 0) for c in checks), default=0)
    overall = "fail" if worst >= 3 else ("warn" if worst >= 2 else "ok")
    return {
        "overall": overall,
        "backend": settings.device_backend,
        "probed_from": _WHERE,
        "in_container": _IN_CONTAINER,
        "summary": {
            k: sum(1 for c in checks if c["status"] == k)
            for k in ("ok", "warn", "fail", "unknown", "skip")
        },
        "checks": checks,
    }
