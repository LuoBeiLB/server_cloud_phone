"""Redroid 后端：真实 Docker + Redroid + adb（仅 Linux 宿主机）。

对应计划 D1/D3（起容器）、D3/D5（一机一码注入 props）、D4（编排 API）、
D5（独立出口 IP/代理）、D11–D12（批量/同步操控走 adb/minitouch）。

依赖：
- docker（Python SDK）：容器生命周期。
- adb（命令行）：连接容器 5555、下发触控/输入/装 APK。
在 macOS/无 Docker 环境不会被导入（get_backend 按配置选择）。
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import time

from ..config import settings
from ..fingerprint import redroid_props
from ..models import Device
from .base import (
    DeviceBackend,
    DeviceCommandError,
    DeviceProvisionError,
    DeviceUnreachable,
    Provisioned,
)

# 主题壁纸（随后端一起分发到 app/skins/）
_SKIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skins")

_KEYCODES = {
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "menu": "KEYCODE_MENU",
    "recent": "KEYCODE_APP_SWITCH",  # 最近任务
    "power": "KEYCODE_POWER",
    "wake": "KEYCODE_WAKEUP",
    "enter": "KEYCODE_ENTER",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
}


async def _run(*args: str) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out, err


# 状态栏动作 -> `cmd statusbar` 子命令（AOSP 正规入口，比顶端下滑手势可靠）
_STATUSBAR_CMDS = {
    "notifications": "expand-notifications",  # 通知栏（iOS 语义：从左上角下滑）
    "quicksettings": "expand-settings",       # 快捷设置（iOS 语义：控制中心）
    "collapse": "collapse",                   # 收起
}

# adb 传输层错误特征（stderr 命中即认为设备不可达，而非命令本身失败）。
#
# 判据分两段，缺一不可：
#   1) 必须是 adb 客户端自己报的错（行首 "error:" / "adb:"）——用于把设备侧
#      shell 的错误排除掉，比如 `sh: xyz: not found` 不该被当成设备失联；
#   2) 且命中传输类关键词。
# 坑：真实报文是 `error: device 'localhost:5561' not found`，序列号夹在中间，
# 所以不能直接匹配 "device not found"（早期版本正是因此从未触发自愈重连）。
_ADB_ERR_PREFIX_RE = re.compile(rb"^\s*(error|adb):", re.I | re.M)
_TRANSPORT_KEYWORDS = (
    b"not found",
    b"no devices",
    b"offline",
    b"unauthorized",
    b"still connecting",
    b"connection refused",
    b"cannot connect to daemon",
    b"protocol fault",
    b"closed",
)

# _ensure_alive 的体检缓存时长（秒）。取帧最高 12fps，不能每帧体检
_ALIVE_TTL = 5.0

# 自愈重连后等待设备就绪的轮询次数与间隔（总上限约 2s，足够本地 TCP 握手）
_RECONNECT_POLLS = 8
_RECONNECT_INTERVAL = 0.25


def _is_transport_error(err: bytes) -> bool:
    low = (err or b"").lower()
    if not _ADB_ERR_PREFIX_RE.search(low):
        return False
    return any(k in low for k in _TRANSPORT_KEYWORDS)


# 宿主环境故障 -> 人能读懂的原因 + 可执行的处置。
#
# 甲方是「一键 docker」跑起来的，把 docker SDK 的 Python 报文直接抛到界面上等于没提示。
# 这里把已知故障翻成「哪里不对 + 敲哪条命令」。命中不了才退回原始报文。
def _explain_docker_error(e: Exception) -> tuple[str, str]:
    text = str(e)
    low = f"{e.__class__.__name__}: {text}".lower()

    if "imagenotfound" in low or "no such image" in low or "manifest unknown" in low:
        return (
            f"redroid 镜像 {settings.redroid_image} 未拉取",
            f"在宿主机执行 docker pull {settings.redroid_image}"
            "（国内网络先配镜像加速器，见部署手册 §3.2）",
        )
    if "permission denied" in low and "docker.sock" in low:
        return (
            "没有访问 /var/run/docker.sock 的权限",
            "后端跑在容器里：取消 compose 中 backend 段 volumes 对 docker.sock 的注释；"
            "后端跑在宿主机：sudo usermod -aG docker $USER 后重新登录",
        )
    if (
        "cannot connect to the docker daemon" in low
        or "dockerexception" in low
        or "filenotfounderror" in low
        and "sock" in low
    ):
        return (
            "连不上 Docker daemon",
            "确认宿主 docker 在跑（systemctl status docker），"
            "且后端已挂载 /var/run/docker.sock",
        )
    if "port is already allocated" in low or "address already in use" in low:
        return (
            "adb 端口已被占用",
            f"换 CLOUD_REDROID_BASE_ADB_PORT（当前基准 {settings.redroid_base_adb_port}），"
            "或 docker ps 找出占用该端口的残留容器后删除",
        )
    if "no space left on device" in low:
        return (
            "宿主磁盘已满",
            "清理磁盘或执行 docker system prune -a；每台实例的 /data 约需 2–6 GB",
        )
    if "conflict" in low and "already in use" in low:
        return ("同名容器已存在且无法自动清理", "手动删除残留容器：docker rm -f redroid_<设备ID>")
    if "invalid mount" in low or "no such file or directory" in low and "mount" in low:
        return (
            f"数据目录 {settings.redroid_data_dir} 不存在或不可挂载",
            f"在宿主机创建并授权：sudo mkdir -p {settings.redroid_data_dir} "
            f"&& sudo chmod 777 {settings.redroid_data_dir}",
        )
    return (text.strip() or e.__class__.__name__, "")


# 容器日志/状态里的特征 -> 开机失败的真正原因。
# 这几条都是 x86 宿主起 redroid 最常见的死法，且**都不是应用层能绕过的**。
def _explain_boot_failure(evidence: str) -> tuple[str, str]:
    low = evidence.lower()
    if "binder" in low:
        return (
            "宿主内核缺少 binder 模块，Android 无法启动",
            "sudo apt install -y linux-modules-extra-$(uname -r) && "
            'sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"；'
            "装了 extra 仍失败说明内核未编译 binder，必须换内核/发行版（见部署手册第 2 章）",
        )
    if "oom" in low or "out of memory" in low:
        return (
            "容器被 OOM 杀掉，宿主内存不足",
            "按 1.5 GiB/台 规划内存；减少同时启动的台数，或加内存（见部署手册 §1.3）",
        )
    if "/dev/dri" in low or "gralloc" in low or "no such device" in low:
        return (
            "图形设备不可用（无核显/显卡直通失败）",
            "确认 ls /dev/dri 有 renderD128；没有就把 CLOUD_REDROID_GPU_MODE 设为 guest "
            "走软件渲染（见部署手册 §1.1）",
        )
    if "exited" in low or "退出码" in evidence:
        return (
            "容器启动后立刻退出",
            "看容器日志定位：docker logs redroid_<设备ID>；"
            "最常见是 binder 缺失或 privileged 被限制（见部署手册第 2 章）",
        )
    return (
        "等待开机超时，Android 未上报 boot_completed",
        "首次冷启需 30–60s，数据盘是机械盘会更久甚至启动风暴——必须用 SSD/NVMe；"
        "用 docker logs redroid_<设备ID> 看卡在哪一步",
    )


async def _adb_server_up() -> None:
    """确保 adb server 已在跑（输出重定向 DEVNULL）。

    坑：adb 客户端发现 server 不在会自动 fork 一个常驻 server，子进程继承
    stdout/stderr 管道 → _run 的 communicate() 永远等不到 EOF 而挂死
    （表现为换肤后台任务卡在 queued）。先用 DEVNULL 显式起 server 即可规避。
    """
    proc = await asyncio.create_subprocess_exec(
        "adb", "start-server",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


class RedroidBackend(DeviceBackend):
    name = "redroid"

    def __init__(self) -> None:
        # 这里**不能**连 docker：services.py 在模块导入时就调用 get_backend()，
        # 若此处抛异常，整个后端进程起不来 —— 甲方看到的是 backend 容器崩溃重启，
        # 而不是界面上一句「Docker 不可用，请挂载 docker.sock」。
        # 改为首次真正用到时再连接并 ping，故障才能以可读的形式呈现给用户。
        self._docker = None
        self._alive_at: dict[int, float] = {}  # device_id -> 上次体检通过的时刻

    @property
    def docker(self):
        """惰性 docker 客户端。连不上时抛 DeviceProvisionError（带处置建议）。"""
        if self._docker is None:
            import docker  # 延迟导入，避免非 Linux 环境报错

            try:
                client = docker.from_env()
                client.ping()  # from_env() 不会真的建连，ping 才会
            except Exception as e:  # noqa: BLE001
                reason, hint = _explain_docker_error(e)
                # device_id=0：这里拿不到设备上下文，由 create()/start() 用
                # restamped() 补上。stage=env 表示这是宿主环境问题，不是某台设备的问题。
                raise DeviceProvisionError(
                    0,
                    "env",
                    f"Docker 不可用：{reason}",
                    hint,
                    f"{e.__class__.__name__}: {e}",
                ) from e
            self._docker = client
        return self._docker

    def _container_name(self, device: Device) -> str:
        return f"redroid_{device.id}"

    def _serial(self, device: Device) -> str:
        # container 模式：走 docker 网络内的容器名，后端无需 network_mode: host
        if settings.redroid_adb_mode == "container":
            return f"{self._container_name(device)}:5555"
        return f"localhost:{device.adb_port}"

    async def _container_diag(self, ref: str) -> str:
        """采集容器现状作为排障证据：状态 / 退出码 / OOM / 日志尾部。

        拉不起来时最有用的信息全在这里，必须随异常一起带给前端，
        否则甲方还得自己 ssh 上去 docker logs。
        """
        try:
            c = await asyncio.to_thread(self.docker.containers.get, ref)
            await asyncio.to_thread(c.reload)
        except Exception as e:  # noqa: BLE001
            return f"容器 {ref} 读不到（{e.__class__.__name__}），可能已被删除"

        parts: list[str] = []
        try:
            state = c.attrs.get("State", {}) or {}
            parts.append(f"容器状态={state.get('Status')}")
            if state.get("ExitCode"):
                parts.append(f"退出码={state['ExitCode']}")
            if state.get("Error"):
                parts.append(f"docker报错={state['Error']}")
            if state.get("OOMKilled"):
                parts.append("OOMKilled=true（被内存不足杀掉）")
        except Exception:  # noqa: BLE001
            parts.append("容器状态读取失败")
        try:
            logs = await asyncio.to_thread(c.logs, tail=15)
            tail = logs.decode(errors="replace").strip()
            if tail:
                parts.append(f"容器日志尾部：{tail}")
        except Exception:  # noqa: BLE001
            parts.append("容器日志读取失败")
        return " | ".join(parts)

    async def _container_alive(self, ref: str) -> bool:
        try:
            c = await asyncio.to_thread(self.docker.containers.get, ref)
            await asyncio.to_thread(c.reload)
            return c.attrs.get("State", {}).get("Running") is True
        except Exception:  # noqa: BLE001
            return False

    async def _adb(
        self, device: Device, *args: str, reconnect: bool = True
    ) -> tuple[int, bytes, bytes]:
        """执行一条 adb 命令。

        与「命令本身返回非 0」（如 pm 查不到包）不同，**传输层错误**（设备没连上 /
        offline / 容器没了）意味着这台设备根本控制不了 —— 此时先尝试自愈重连一次，
        仍不行就抛 DeviceUnreachable，**绝不返回让调用方误当成功**。

        背景：宿主休眠、adb server 重启、容器重建都会掉连接，过去这里静默返回，
        导致「预览有画面、批量报成功」而设备实际失联。
        """
        serial = self._serial(device)
        code, out, err = await _run("adb", "-s", serial, *args)
        if code == 0 or not _is_transport_error(err):
            return code, out, err

        if not reconnect:
            raise DeviceUnreachable(device.id, serial, err.decode(errors="replace").strip())

        # 自愈：显式起 server（防 fork 继承管道挂死）后重连再重试。
        # 注意 `adb connect` 是异步的 —— 它先返回 "connected"，TCP 握手与设备就绪
        # 还要几百毫秒。立刻重试会照样拿到 "device not found"，所以必须等就绪。
        await _adb_server_up()
        await _run("adb", "connect", serial)
        for _ in range(_RECONNECT_POLLS):
            st_code, st_out, _ = await _run("adb", "-s", serial, "get-state")
            if st_code == 0 and st_out.strip() == b"device":
                break
            await asyncio.sleep(_RECONNECT_INTERVAL)

        code, out, err = await _run("adb", "-s", serial, *args)
        if code == 0 or not _is_transport_error(err):
            self._alive_at.pop(device.id, None)  # 让下次 _ensure_alive 重新体检
            return code, out, err
        raise DeviceUnreachable(device.id, serial, err.decode(errors="replace").strip())

    async def _ensure_alive(self, device: Device) -> None:
        """确认控制通道真的活着（带 TTL 缓存，避免高频取帧把 adb 打爆）。

        截图会按 5–12fps 轮询，不能每帧都体检；但也不能不检 —— 主屏皮肤渲染那条
        路径根本不碰 adb，设备死了照样出图，正是它把故障藏了起来。
        """
        now = time.monotonic()
        if now - self._alive_at.get(device.id, 0.0) < _ALIVE_TTL:
            return
        code, out, err = await self._adb(device, "get-state")  # 失败会自愈/抛错
        if code != 0 or out.strip() != b"device":
            raise DeviceUnreachable(
                device.id, self._serial(device),
                (out + err).decode(errors="replace").strip() or "设备未就绪",
            )
        self._alive_at[device.id] = now

    async def create(self, device: Device) -> Provisioned:
        port = settings.redroid_base_adb_port + device.id
        props = redroid_props(device.fingerprint or {})
        env_proxy = (device.fingerprint or {}).get("network", {}).get("proxy")

        # 清理可能残留的同名容器，避免创建冲突。
        # 这里的失败要记下来：若清理没成功，下面 run 会因名字冲突失败，
        # 光看「Conflict」不知道是清理失败导致的。
        cleanup_note = ""
        try:
            old = await asyncio.to_thread(self.docker.containers.get, f"redroid_{device.id}")
            await asyncio.to_thread(old.remove, force=True)
        except Exception as e:  # noqa: BLE001
            name = e.__class__.__name__
            if "NotFound" not in name:  # 不存在是正常情况，不算问题
                cleanup_note = f"清理残留容器 redroid_{device.id} 失败（{name}: {e}）"

        try:
            container = await asyncio.to_thread(
                self.docker.containers.run,
                settings.redroid_image,
                command=[
                    f"androidboot.redroid_gpu_mode={settings.redroid_gpu_mode}",
                    f"androidboot.redroid_width={device.width}",
                    f"androidboot.redroid_height={device.height}",
                    f"androidboot.redroid_dpi={device.dpi}",
                    *props,
                ],
                name=self._container_name(device),
                detach=True,
                privileged=True,
                volumes={
                    f"{settings.redroid_data_dir}/inst{device.id}": {"bind": "/data", "mode": "rw"}
                },
                ports={"5555/tcp": port},
                # container 模式：把实例接入后端所在的 docker 网络，这样
                # `adb connect redroid_<id>:5555` 才能解析到容器名。
                network=settings.redroid_network or None,
                environment={"HTTP_PROXY": env_proxy, "HTTPS_PROXY": env_proxy} if env_proxy else None,
                restart_policy={"Name": "unless-stopped"},  # VM/Docker 重启后自动拉起，避免休眠丢运行态
            )
        except DeviceProvisionError as e:
            # docker 客户端本身不可用：原因与处置已齐备，只补设备 ID，别再套一层
            raise e.restamped(device.id) from e
        except Exception as e:  # noqa: BLE001
            reason, hint = _explain_docker_error(e)
            evidence = f"{e.__class__.__name__}: {e}"
            if cleanup_note:
                evidence = f"{cleanup_note} | {evidence}"
            raise DeviceProvisionError(device.id, "provision", reason, hint, evidence) from e

        return Provisioned(backend_ref=container.id, adb_port=port)

    async def start(self, device: Device) -> None:
        """启动容器并等 Android 真正开机完成。

        **失败必须抛异常。** 早期版本在等 boot_completed 的循环耗尽后直接 return，
        调用方（services.start_device / create_device）随即把设备标记成 running，
        于是「云手机根本没起来」被伪装成启动成功，后续每一次操作都失败，
        而界面上只显示「运行中」—— 甲方无从下手。
        """
        if device.backend_ref:
            try:
                c = await asyncio.to_thread(self.docker.containers.get, device.backend_ref)
                await asyncio.to_thread(c.start)
            except DeviceProvisionError as e:
                raise e.restamped(device.id) from e  # docker 客户端不可用，仅补设备 ID
            except Exception as e:  # noqa: BLE001
                reason, hint = _explain_docker_error(e)
                raise DeviceProvisionError(
                    device.id,
                    "start",
                    reason,
                    hint,
                    await self._container_diag(device.backend_ref),
                ) from e

        serial = self._serial(device)
        await _adb_server_up()  # 防 connect 自动 fork server 继承管道挂死 _run
        last_adb = ""
        for i in range(90):  # 最多 ~180s（首次冷启 30–60s，机械盘更久）
            # 容器中途退出就没必要再干等 —— binder 缺失、OOM、privileged 被限制
            # 都表现为「起来立刻退」，早退出早给准确原因。每 10s 查一次，别每轮都查。
            if device.backend_ref and i and i % 5 == 0:
                if not await self._container_alive(device.backend_ref):
                    evidence = await self._container_diag(device.backend_ref)
                    reason, hint = _explain_boot_failure(evidence)
                    raise DeviceProvisionError(device.id, "boot", reason, hint, evidence)

            _, cout, cerr = await _run("adb", "connect", serial)
            _, out, err = await _run(
                "adb", "-s", serial, "shell", "getprop", "sys.boot_completed"
            )
            if out.strip() == b"1":
                return
            last_adb = (
                f"adb connect: {(cout or cerr).decode(errors='replace').strip()}"
                f" | getprop: {(out or err).decode(errors='replace').strip() or '(空)'}"
            )
            await asyncio.sleep(2)

        # 循环耗尽 = 开机没完成。带上容器证据与 adb 最后一次报文，给出可执行处置。
        evidence = ""
        if device.backend_ref:
            evidence = await self._container_diag(device.backend_ref)
        evidence = f"{evidence} | 最后一次探测：{last_adb}" if evidence else last_adb
        reason, hint = _explain_boot_failure(evidence)
        raise DeviceProvisionError(device.id, "boot", reason, hint, evidence)

    async def stop(self, device: Device) -> None:
        if device.backend_ref:
            c = await asyncio.to_thread(self.docker.containers.get, device.backend_ref)
            await asyncio.to_thread(c.stop)

    async def destroy(self, device: Device) -> None:
        if device.backend_ref:
            try:
                c = await asyncio.to_thread(self.docker.containers.get, device.backend_ref)
                await asyncio.to_thread(c.remove, force=True)
            except Exception:  # noqa: BLE001  容器可能已不存在
                pass

    async def open_url(self, device: Device, url: str) -> None:
        # 先下发再写库：反过来的话 adb 失败仍会把 current_url 落库，
        # 列表显示「当前页面 = xxx」而设备上根本没打开（失联时的假象来源之一）
        await self._adb(device, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url)
        device.current_url = url

    async def tap(self, device: Device, x: int, y: int) -> None:
        await self._adb(device, "shell", "input", "tap", str(x), str(y))

    async def swipe(self, device: Device, x1, y1, x2, y2, duration_ms) -> None:
        await self._adb(device, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    async def input_text(self, device: Device, text: str) -> None:
        """向设备输入文本。优先使用 ADBKeyboard 广播（支持中英文），
        未安装时降级为 adb shell input text（仅支持 ASCII）。"""
        if await self._ensure_adbkeyboard(device):
            await self._adb(
                device, "shell", "am", "broadcast",
                "-a", "ADB_INPUT_TEXT", "--es", "msg", text,
            )
        else:
            await self._adb(device, "shell", "input", "text", text.replace(" ", "%s"))

    async def _ensure_adbkeyboard(self, device: Device) -> bool:
        """确保 ADBKeyboard 输入法已安装、启用、设为默认。返回 True 表示可用。

        关键修复（之前只 enable 没 set，所以即便 install 成功，IME 也不是默认，
        物理键盘字符仍然进不去）：现在每一步都打日志、装好后强制 ime set，
        并在「包在但 IME 不在默认」的场景里也直接 set。
        """
        import logging
        logger = logging.getLogger("redroid")

        # 1. 先看包是否已经装好
        code, out, _ = await self._adb(
            device, "shell", "pm", "list", "packages", "com.android.adbkeyboard"
        )
        if code != 0:
            logger.warning(
                "设备 %s 探测 ADBKeyboard 包失败（exit %d），降级为 adb input text",
                device.id, code,
            )
            return False
        if b"com.android.adbkeyboard" in out:
            # 包在 —— 但 IME 可能没切为默认；检查并切
            code2, cur, _ = await self._adb(
                device, "shell", "settings", "get", "secure", "default_input_method"
            )
            if code2 == 0 and cur.strip() == b"com.android.adbkeyboard/.AdbIME":
                return True
            logger.info(
                "设备 %s ADBKeyboard 已安装但当前默认 IME 不是它，切为默认", device.id,
            )
            await self._adb(
                device, "shell", "ime", "set", "com.android.adbkeyboard/.AdbIME"
            )
            return True

        # 2. 没装，从后端 skins 目录找 apk 推过去
        apk = os.path.join(_SKIN_DIR, "ADBKeyboard.apk")
        if not os.path.exists(apk):
            logger.warning(
                "缺少 ADBKeyboard.apk（%s），键盘输入将降级为仅支持 ASCII。"
                "放置 APK 到 app/skins/ADBKeyboard.apk 或执行 deploy/redroid/install-adbkeyboard.sh",
                apk,
            )
            return False

        logger.info("设备 %s ADBKeyboard 未安装，开始 push APK 安装", device.id)
        code, _, err = await self._adb(device, "install", "-r", apk)
        if code != 0:
            logger.warning(
                "设备 %s ADBKeyboard 安装失败：%s",
                device.id, err.decode(errors="replace").strip()[:200],
            )
            return False

        # 3. 装好之后 enable + set 默认（关键：之前漏了 set）
        await self._adb(
            device, "shell", "ime", "enable", "com.android.adbkeyboard/.AdbIME"
        )
        code_set, _, err_set = await self._adb(
            device, "shell", "ime", "set", "com.android.adbkeyboard/.AdbIME"
        )
        if code_set != 0:
            logger.warning(
                "设备 %s ADBKeyboard 切默认 IME 失败：%s（包已装但当前 IME 可能仍是别的，键盘输入可能仍失效）",
                device.id, err_set.decode(errors="replace").strip()[:200],
            )
        else:
            logger.info("设备 %s ADBKeyboard 安装并设为默认 IME 完成", device.id)
        return True

    async def key(self, device: Device, key: str) -> None:
        # 通知栏/控制中心：从屏幕顶端下滑手势在 adb input swipe 下并不可靠
        # （起点必须压在状态栏上，且手势导航开启后更易被吞），statusbar 命令是
        # AOSP 的正规入口，幂等且立即生效。
        if key in _STATUSBAR_CMDS:
            await self._adb(device, "shell", "cmd", "statusbar", _STATUSBAR_CMDS[key])
            return
        if key == "home":
            # KEYCODE_HOME 在部分 AOSP GSI 上不切桌面（桌面非默认 HOME 处理者），
            # 用 HOME intent 更可靠。
            await self._adb(
                device, "shell", "am", "start",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.HOME",
            )
            return
        code = _KEYCODES.get(key, key)
        await self._adb(device, "shell", "input", "keyevent", code)

    async def install(self, device: Device, apk_url: str) -> None:
        # 简化：容器内下载再安装；生产可先落地宿主再 adb install
        await self._adb(device, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", apk_url)

    async def install_from_local_file(self, device: Device, local_path: str) -> None:
    #"""把后端临时目录里的 APK 推送到设备并安装。"""
    # 1. 从文件路径取出文件名，拼出设备上的目标路径
        remote_path = "/sdcard/" + os.path.basename(local_path)
    # 2. 复用已有的 push_file 把文件推到设备（它内部调的是 adb push）
        await self.push_file(device, local_path, remote_path)
    # 3. 用 pm install 安装（-r 表示覆盖安装）
        await self._adb(device, "shell", "pm", "install", "-r", remote_path)
        
    async def list_apps(self, device: Device) -> list[str]:
        # 优先列第三方应用（-3），再补一份全量（去桌面/输入法等系统噪声后仍可见常用系统应用）
        packages: set[str] = set()
        failures: list[str] = []
        for extra in (("-3",), ()):
            code, out, err = await self._adb(device, "shell", "pm", "list", "packages", *extra)
            if code != 0 or not out:
                failures.append(err.decode(errors="replace").strip() or f"adb 退出码 {code}")
                continue
            for line in out.decode("utf-8", "ignore").splitlines():
                line = line.strip()
                if line.startswith("package:"):
                    name = line[len("package:"):].strip()
                    if name:
                        packages.add(name)
        # 两次 pm 都失败且一个包都没读到 = 读取失败，不是「这台设备没装应用」。
        # 空列表曾把失联设备伪装成「0 个应用」，必须如实报错。
        if not packages and failures:
            raise DeviceCommandError(device.id, "读取应用列表", failures[-1])
        return sorted(packages)[:200]

    async def list_logcat(self, device: Device, lines: int = 200) -> list[str]:
        code, out, err = await self._adb(device, "shell", "logcat", "-d", "-t", str(lines))
        # 命令失败要如实报错：返回空列表会被前端显示成「这台设备没有日志」，
        # 把「读不到」伪装成「没有」——与截图静默回退是同一类问题。
        if code != 0:
            raise DeviceCommandError(
                device.id, "读取日志",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        return out.decode("utf-8", "ignore").splitlines()[-lines:]

    async def set_display(self, device: Device, width: int, height: int, dpi: int) -> None:
        await self._adb(device, "shell", "wm", "size", f"{width}x{height}")
        await self._adb(device, "shell", "wm", "density", str(dpi))
        device.width, device.height, device.dpi = width, height, dpi

    async def uninstall_app(self, device: Device, package: str) -> None:
        await self._adb(device, "uninstall", package)

    async def launch_app(self, device: Device, package: str) -> None:
        await self._adb(device, "shell", "monkey", "-p", package, "-c",
                        "android.intent.category.LAUNCHER", "1")

    async def stop_app(self, device: Device, package: str) -> None:
        await self._adb(device, "shell", "am", "force-stop", package)

    async def clear_app(self, device: Device, package: str) -> None:
        await self._adb(device, "shell", "pm", "clear", package)

    async def list_files(self, device: Device, path: str = "/sdcard/") -> list[dict]:
        code, out, err = await self._adb(device, "shell", "ls", "-p", path)
        # 只有「命令成功但没输出」才是真的空目录；命令失败（路径不存在/无权限）
        # 必须报错，否则前端把「打不开」显示成「这个目录是空的」。
        if code != 0:
            raise DeviceCommandError(
                device.id, f"读取目录 {path}",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        if not out:
            return []
        items = []
        for n in out.decode("utf-8", "ignore").splitlines():
            n = n.strip().rstrip("\r")
            if not n:
                continue
            items.append({"name": n.rstrip("/"), "is_dir": n.endswith("/")})
        return items[:500]

    async def push_file(self, device: Device, local_path: str, remote_path: str) -> None:
        await self._adb(device, "push", local_path, remote_path)

    async def pull_file(self, device: Device, remote_path: str, local_path: str) -> bool:
        code, _, _ = await self._adb(device, "pull", remote_path, local_path)
        return code == 0

    async def delete_file(self, device: Device, remote_path: str) -> None:
        await self._adb(device, "shell", "rm", "-rf", remote_path)

    async def screenshot(self, device: Device) -> str:
        """真机取帧：**一律走 adb screencap，返回设备真实画面。**

        ⛔ 早期实现里有一条分支：设备没开网页时不碰 adb，直接用 render_frame 画一张
        主题皮肤图返回。初衷是「换肤即时可见」，实际后果是 —— 真机的预览被一张渲染图
        盖住，用户看到的根本不是设备屏幕。甲方的原话是「操作完全不是真机了，为啥都是
        图片」，指的就是这里。

        皮肤本来就是真落到设备上的（apply_skin 真装 Lawnchair、写壁纸、重启生效），
        真实画面自然会显示 iOS 桌面，不需要也不应该再伪造一张。换肤未完成时就该看到
        设备当前的真实样子，而不是一张「承诺中的」效果图。
        """
        # 先体检：失联设备必须明确报错，不能返回一张「看着正常」的画面
        await self._ensure_alive(device)

        code, out, err = await self._adb(device, "exec-out", "screencap", "-p")
        if code != 0 or not out:
            # 体检刚过却截不到图 —— 属真实异常，明确报错，不再回退成皮肤图糊弄
            raise DeviceUnreachable(
                device.id, self._serial(device),
                err.decode(errors="replace").strip() or "screencap 返回空数据",
            )
        return "data:image/png;base64," + base64.b64encode(out).decode("ascii")

    async def apply_skin(self, device: Device, theme: str, progress=None) -> None:
        """真机换肤：iOS 桌面（Lawnchair 4列/Dock/squircle）+ 主题壁纸 + 容器重启。

        deploy/ios-skin/apply-ios-skin.sh 已在真机验证过的流程的 API 移植：
          1) 装 Lawnchair（app/skins/lawnchair.apk，如未装）并 set-home-activity
          2) 重排 launcher.db：应用铺进 4 列网格 + Dock（重启后随开机加载）
          3) 主题壁纸 put_archive 写进 /data/system/users/0/wallpaper
          4) 整机重启 —— redroid 硬约束：`cmd wallpaper` 空实现、位图缓存在
             system_server，只有重启后 WallpaperManagerService 才从文件重读
          5) 开机后合并 Lawnchair 偏好（4列/Dock4/squircle 圆角）——必须在开机
             迁移之后写才留得住，且 key 均为 String 型（int 会崩启动器）
        耗时约 1–2 分钟（首次含装启动器），由调用方作为后台任务运行；
        progress(phase) 逐步上报：launcher/grid/wallpaper/reboot/prefs。
        """
        import io
        import tarfile

        async def _report(phase: str) -> None:
            if progress is not None:
                await progress(phase)

        # 壁纸选型：与 preview._svg_home 相同的 rid 公式（seed/name 求和取模），
        # 保证真机壁纸与预览渲染同款；分档文件缺失回退旧的单档壁纸
        rid = sum(ord(ch) for ch in ((device.fingerprint or {}).get("seed", "") or device.name)) % 3
        wp = os.path.join(_SKIN_DIR, f"wallpaper_{theme}_{rid}.png")
        if not os.path.exists(wp):
            wp = os.path.join(_SKIN_DIR, f"wallpaper_{theme}.png")
        if not os.path.exists(wp):
            return
        cref = device.backend_ref or f"redroid_{device.id}"
        container = await asyncio.to_thread(self.docker.containers.get, cref)
        serial = self._serial(device)
        # 后端/VM 重启后 adb server 是空的，必须先 connect，否则 -s serial 的
        # pm/dumpsys 全部静默失败 → _ensure_launcher 拿不到 pkg → 网格/偏好被跳过；
        # 且必须先显式起 server（否则 connect 自动 fork 的 server 会挂死 _run）。
        # 预检：确认 adb 真正可达（容器刚重启/批量场景下 connect 可能要几秒），
        # 15s 内不可达则明确失败 —— 宁可让前端显示「换肤失败」重试，也不要
        # 静默降级成只落壁纸（会表现为"换肤没效果"）。
        await _adb_server_up()
        reachable = False
        for _ in range(5):
            await _run("adb", "connect", serial)
            code, out, _ = await self._adb(device, "shell", "getprop", "sys.boot_completed")
            if code == 0 and out.strip() == b"1":
                reachable = True
                break
            await asyncio.sleep(3)
        if not reachable:
            raise TimeoutError(f"{serial} adb 不可达，换肤中止（设备未开机完成或 adb 连接异常）")

        # 1) iOS 风启动器（Lawnchair）就位并设为默认 HOME
        await _report("launcher")
        pkg = await self._ensure_launcher(device, container)

        # 2) iOS 网格/Dock：重排 launcher.db（失败不阻断壁纸流程）
        if pkg:
            await _report("grid")
            try:
                await self._populate_grid(device, container, pkg, theme)
            except Exception:  # noqa: BLE001
                pass

        # 3) 壁纸：打成 tar，put_archive 到 /data/system/users/0/（属主 1000:1000）
        await _report("wallpaper")
        with open(wp, "rb") as f:
            data = f.read()

        def _write_wallpaper() -> None:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                for member in ("wallpaper", "wallpaper_orig"):
                    ti = tarfile.TarInfo(member)
                    ti.size = len(data)
                    ti.mode = 0o600
                    ti.uid = ti.gid = 1000
                    tar.addfile(ti, io.BytesIO(data))
            container.put_archive("/data/system/users/0", buf.getvalue())

        await asyncio.to_thread(_write_wallpaper)

        # 4) 整机重启，开机时壁纸/网格一起加载；轮询开机完成 + 重连 adb（上限 ~120s）
        await _report("reboot")
        await asyncio.to_thread(container.restart)
        booted = False
        for _ in range(40):
            await asyncio.sleep(3)
            await _run("adb", "connect", serial)
            code, out, _ = await self._adb(device, "shell", "getprop", "sys.boot_completed")
            if code == 0 and out.strip() == b"1":
                booted = True
                break
        if not booted:
            raise TimeoutError(f"{cref} 重启后 120s 内未完成开机")

        # 5) 开机后合并 Lawnchair 偏好（squircle/4列/Dock），并回到主屏呈现
        if pkg:
            await _report("prefs")
            # iOS 手势导航条：三键导航 → 手势小白条（更贴 iOS home indicator）。
            # overlay 状态写在 /data/system/overlays.xml，重启保持，幂等可重复执行。
            await self._adb(
                device, "shell", "cmd", "overlay", "enable",
                "com.android.internal.systemui.navbar.gestural",
            )
            await self._merge_launcher_prefs(container, pkg)
            # 网格补写：新装设备开机加载可能仍按旧 4x4 网格删掉 cellY>=4 的行
            # （pref_numRows 要等上面 prefs 合并后才生效），此处按最终 prefs 再写一遍
            try:
                await self._populate_grid(device, container, pkg, theme)
            except Exception:  # noqa: BLE001
                pass
            await self._adb(
                device, "shell", "am", "start",
                "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
            )

    async def _ensure_launcher(self, device: Device, container) -> str | None:
        """确保 Lawnchair 已安装并为默认 HOME；返回包名（无法就位则返回 None）。"""
        _, out, _ = await self._adb(device, "shell", "pm", "list", "packages")
        pkg = None
        for line in out.decode(errors="replace").splitlines():
            if "lawnchair" in line:
                pkg = line.strip().removeprefix("package:")
                break
        if pkg is None:
            apk = os.path.join(_SKIN_DIR, "lawnchair.apk")
            if not os.path.exists(apk):
                import logging

                logging.getLogger("redroid").warning(
                    "缺少 %s，本次换肤仅落地壁纸（补齐：deploy/ios-skin/fetch-lawnchair.sh）", apk
                )
                return None
            code, _, _ = await self._adb(device, "install", "-r", apk)
            if code != 0:
                return None
            pkg = "ch.deletescape.lawnchair"
        # 预授权存储权限，避免首启弹「允许访问照片/媒体」对话框挡住桌面
        for perm in ("android.permission.READ_EXTERNAL_STORAGE", "android.permission.WRITE_EXTERNAL_STORAGE"):
            await self._adb(device, "shell", "pm", "grant", pkg, perm)
        # 解析 HOME activity → 设为默认桌面 → 先跑一次生成 launcher.db/偏好
        _, out, _ = await self._adb(
            device, "shell", "cmd", "package", "resolve-activity",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME", pkg,
        )
        act = None
        for tok in out.decode(errors="replace").split():
            if tok.startswith("name="):
                act = tok[5:].strip()
                break
        if act:
            await self._adb(device, "shell", "cmd", "package", "set-home-activity", f"{pkg}/{act}")
            await self._adb(
                device, "shell", "am", "start",
                "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
            )
            # 等 Lawnchair 首次运行建库（新装设备 launcher.db 要跑一次才有）
            db = f"/data/data/{pkg}/databases/launcher.db"
            for _ in range(5):
                rc = await asyncio.to_thread(container.exec_run, ["sh", "-c", f"test -f {db}"])
                if rc.exit_code == 0:
                    break
                await asyncio.sleep(2)
        return pkg

    async def _populate_grid(self, device: Device, container, pkg: str, theme: str = "ios") -> None:
        """把设计稿桌面（ios_layout，20 条目全 itemType=1 + 图标 BLOB）写进 launcher.db。

        deploy/ios-skin/populate-grid.py 的进程内移植：容器 get_archive 拉 db →
        本地 sqlite3 重写 favorites → put_archive 推回（容器内 sqlite3 会 abort，不能用）。
        图标资产（app/skins/icons/{theme}/）缺失时回退旧的「真实应用铺网格」逻辑。
        """
        import re
        import sqlite3
        import tarfile
        import tempfile
        import time as _time

        from .ios_layout import build_favorites

        # 应用清单（排除启动器自身）：设计稿路径用于 app 条目降级判断；旧路径用于铺网格
        _, out, _ = await self._adb(
            device, "shell", "cmd", "package", "query-activities", "--brief",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
        )
        comps = sorted(
            {
                m
                for m in re.findall(r"[a-zA-Z0-9_.]+/[a-zA-Z0-9_.]+", out.decode(errors="replace"))
                if not m.startswith(f"{pkg}/")
            }
        )
        if not comps:
            return

        # 设计稿桌面行（图标 BLOB 已验证像素级呈现且免疫图标形状开关）；资产缺失 → None 走旧网格
        design_rows: list[dict] | None = None
        if os.path.isdir(os.path.join(_SKIN_DIR, "icons", theme)):
            try:
                design_rows = build_favorites(set(comps), os.path.join(_SKIN_DIR, "icons"), theme)
            except FileNotFoundError:
                design_rows = None

        apps: list[tuple[str, str]] = []
        if not design_rows:  # 旧逻辑才需要逐个 dumpsys 取标题
            for comp in comps:
                _, dout, _ = await self._adb(device, "shell", "dumpsys", "package", comp)
                m = re.search(rb"label=(\S+)", dout)
                title = m.group(1).decode(errors="replace") if m else comp.split("/")[0].rsplit(".", 1)[-1]
                apps.append((title, comp))

        db_remote = f"/data/data/{pkg}/databases/launcher.db"

        def _pull_db() -> bytes:
            import io as _io

            stream, _stat = container.get_archive(db_remote)
            with tarfile.open(fileobj=_io.BytesIO(b"".join(stream))) as tar:
                f = tar.extractfile(tar.getmembers()[0])
                assert f is not None
                return f.read()

        raw = await asyncio.to_thread(_pull_db)
        # 改库前停启动器，避免其进程持有旧数据回写
        await asyncio.to_thread(container.exec_run, ["sh", "-c", f"am force-stop {pkg}"])

        def _rewrite(raw_db: bytes) -> bytes:
            cols, start_row, dock_slots = 4, 1, 4  # 4 列贴近 iOS；第 0 行留给 QSB
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp.write(raw_db)
                path = tmp.name
            try:
                conn = sqlite3.connect(path)
                cur = conn.cursor()
                cur.execute("DELETE FROM favorites")
                now = int(_time.time() * 1000)
                _id = 1

                def intent(comp: str) -> str:
                    p = comp.split("/")[0]
                    return (
                        "#Intent;action=android.intent.action.MAIN;"
                        "category=android.intent.category.LAUNCHER;launchFlags=0x10200000;"
                        f"package={p};component={comp};end"
                    )

                def ins(title: str, comp: str, cont: int, screen: int, cx: int, cy: int) -> None:
                    nonlocal _id
                    cur.execute(
                        "INSERT INTO favorites (_id,title,intent,container,screen,cellX,cellY,"
                        "spanX,spanY,itemType,appWidgetId,modified,restored,profileId,rank,options) "
                        "VALUES (?,?,?,?,?,?,?,1,1,0,-1,?,0,0,0,0)",
                        (_id, title, intent(comp), cont, screen, cx, cy, now),
                    )
                    _id += 1

                if design_rows:
                    # 设计稿桌面：全部 itemType=1 快捷方式 + 设计图标 BLOB（icon 列），
                    # 位置由 ios_layout 给定（主屏 cellY 1..4 共 4 行 + Dock screen 0..3）
                    for r in design_rows:
                        cur.execute(
                            "INSERT INTO favorites (_id,title,intent,container,screen,cellX,cellY,"
                            "spanX,spanY,itemType,appWidgetId,icon,modified,restored,profileId,rank,options) "
                            "VALUES (?,?,?,?,?,?,?,1,1,1,-1,?,?,0,0,0,0)",
                            (_id, r["title"], r["intent"], r["container"], r["screen"],
                             r["cellX"], r["cellY"], r["icon"], now),
                        )
                        _id += 1
                else:
                    for i, (title, comp) in enumerate(apps):
                        ins(title, comp, -100, 0, i % cols, start_row + i // cols)
                    for slot, (title, comp) in enumerate(apps[:dock_slots]):
                        ins(title, comp, -101, slot, 0, 0)
                if not cur.execute("SELECT 1 FROM workspaceScreens WHERE _id=0").fetchone():
                    cur.execute(
                        "INSERT INTO workspaceScreens (_id,screenRank,modified) VALUES (0,0,?)", (now,)
                    )
                conn.commit()
                conn.close()
                with open(path, "rb") as f:
                    return f.read()
            finally:
                os.unlink(path)

        new_db = await asyncio.to_thread(_rewrite, raw)

        def _push_db() -> None:
            import io as _io

            buf = _io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                ti = tarfile.TarInfo("launcher.db")
                ti.size = len(new_db)
                ti.mode = 0o660
                tar.addfile(ti, _io.BytesIO(new_db))
            container.put_archive(f"/data/data/{pkg}/databases", buf.getvalue())
            container.exec_run(
                [
                    "sh", "-c",
                    f"rm -f {db_remote}-journal; "
                    f"own=$(stat -c '%u:%g' /data/data/{pkg}/databases); "
                    f"chown $own {db_remote}; chmod 660 {db_remote}",
                ]
            )

        await asyncio.to_thread(_push_db)

    async def _merge_launcher_prefs(self, container, pkg: str) -> None:
        """开机后合并 Lawnchair 偏好：4 列/6 行/Dock4 + squircle 圆角蒙版
        + 设计稿观感（隐藏顶部日期 widget、Dock 浅色半透明）。

        坑（apply-ios-skin.sh 验证过）：整体覆盖 XML 会被 Lawnchair 开机迁移重置，
        必须在 </map> 前「插入」；网格类 key 都是 String 型，写 int 会崩启动器；
        追加的 boolean/float 行为真机探针验证有效的原样类型（float 写 boolean 会崩）。
        """
        squircle = "M50,0 C10,0 0,10 0,50 0,90 10,100 50,100 90,100 100,90 100,50 100,10 90,0 50,0 Z"
        prefs = f"/data/data/{pkg}/shared_prefs/{pkg}_preferences.xml"
        script = (
            f"am force-stop {pkg}\n"
            f"P='{prefs}'\n"
            "[ -f \"$P\" ] || printf \"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>"
            "\\n<map>\\n</map>\\n\" > \"$P\"\n"
            "sed -i '/name=\"pref_numRows\"/d;/name=\"pref_numCols\"/d;"
            "/name=\"pref_numHotseatIcons\"/d;/name=\"pref_override_icon_shape\"/d;"
            "/name=\"pref_showDateOrWeather\"/d;/name=\"pref_isHotseatTransparent\"/d;"
            "/name=\"pref_hotseatShouldUseExtractedColors\"/d;"
            "/name=\"pref_hotseatShouldUseCustomOpacity\"/d;"
            "/name=\"pref_hotseatShowArrow\"/d;"
            "/name=\"pref_hotseatCustomOpacity\"/d' \"$P\"\n"
            "sed -i \"s#</map>#    <string name=\\\"pref_numRows\\\">6</string>\\n"
            "    <string name=\\\"pref_numCols\\\">4</string>\\n"
            "    <string name=\\\"pref_numHotseatIcons\\\">4</string>\\n"
            f"    <string name=\\\"pref_override_icon_shape\\\">{squircle}</string>\\n"
            "    <boolean name=\\\"pref_showDateOrWeather\\\" value=\\\"false\\\" />\\n"
            "    <boolean name=\\\"pref_isHotseatTransparent\\\" value=\\\"true\\\" />\\n"
            "    <boolean name=\\\"pref_hotseatShouldUseExtractedColors\\\" value=\\\"false\\\" />\\n"
            "    <boolean name=\\\"pref_hotseatShouldUseCustomOpacity\\\" value=\\\"true\\\" />\\n"
            "    <boolean name=\\\"pref_hotseatShowArrow\\\" value=\\\"false\\\" />\\n"
            "    <float name=\\\"pref_hotseatCustomOpacity\\\" value=\\\"0.3\\\" />\\n</map>#\" \"$P\"\n"
            f"own=$(stat -c '%u:%g' /data/data/{pkg}/shared_prefs); chown $own \"$P\"; chmod 660 \"$P\"\n"
        )
        await asyncio.to_thread(container.exec_run, ["sh", "-c", script])