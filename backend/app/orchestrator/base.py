"""设备编排后端抽象。

两种实现：
- SimulatorBackend：无需 Docker，任意平台可跑（macOS 上直接演示主流程）。
- RedroidBackend：真实 Docker + Redroid，仅 Linux 宿主机。

上层（routers）只依赖此抽象，切换后端只改配置 CLOUD_DEVICE_BACKEND。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass

from ..models import Device


class DeviceUnreachable(RuntimeError):
    """设备控制通道不可用（容器停了 / adb 没连上 / 设备 offline）。

    存在的意义是**禁止静默降级**：这类故障过去被各处 `await self._adb(...)` 吞掉，
    表现为「预览有画面、批量报全部成功」，但设备其实早已失联（真实事故）。
    任何拿不到设备的场景都必须抛它，由路由层转成 503 并把设备标记为异常。
    """

    def __init__(self, device_id: int, serial: str = "", detail: str = "") -> None:
        self.device_id = device_id
        self.serial = serial
        self.detail = detail
        msg = f"设备 {device_id} 控制通道不可用"
        if serial:
            msg += f"（{serial}）"
        if detail:
            msg += f"：{detail}"
        super().__init__(msg)


class DeviceProvisionError(RuntimeError):
    """云手机**拉不起来**（建容器失败 / 起容器失败 / 开机没完成）。

    与 DeviceUnreachable 的区别：那是「已建好的设备失联」，这是「压根没建/起成功」。
    单独一类的原因是排障路径完全不同 —— 失联查 adb 与容器状态，拉不起来查宿主环境
    （镜像有没有拉、binder 有没有、/dev/dri 在不在、docker.sock 权限、内存够不够）。

    存在的意义同样是**禁止静默降级**：
      · redroid.start() 过去等 boot_completed 的循环耗尽后直接 return，调用方会把
        「Android 根本没起来」当成启动成功，设备标记 running，后续每个操作都失败；
      · services.create_device 过去 `except Exception: 标记 error` 把原因整个吞掉，
        甲方只看到「状态：异常」，没有任何下文。
    所以本异常强制携带三段信息：出错阶段、原因、可执行的处置建议。

    stage:    env | provision | start | boot   —— 卡在哪一步
              env 是宿主环境层面的问题（docker 连不上等），与具体设备无关
    reason:   人能读懂的原因（不是 Python 报文）
    hint:     照着做就能修的下一步（命令 / 检查项）
    evidence: 实测证据（容器状态、退出码、容器日志尾部、adb 报文），供进一步排查
    """

    def __init__(
        self,
        device_id: int,
        stage: str,
        reason: str,
        hint: str = "",
        evidence: str = "",
    ) -> None:
        self.device_id = device_id
        self.stage = stage
        self.reason = reason
        self.hint = hint
        self.evidence = evidence
        _stage_cn = {
            "env": "环境检查",
            "provision": "创建实例",
            "start": "启动容器",
            "boot": "等待开机",
        }
        what = _stage_cn.get(stage, stage)
        # device_id=0 表示故障与具体设备无关（宿主环境问题），别报成「设备 0」
        msg = f"设备 {device_id} {what}失败：{reason}" if device_id else f"{what}失败：{reason}"
        super().__init__(msg)

    def restamped(self, device_id: int) -> "DeviceProvisionError":
        """补上设备 ID 后返回新实例。

        docker 客户端不可用是在 property 里发现的，那里拿不到设备上下文（device_id=0）。
        由 create()/start() 补齐，好让界面能定位到具体是哪台设备的操作触发的。
        """
        if self.device_id:
            return self
        return DeviceProvisionError(device_id, self.stage, self.reason, self.hint, self.evidence)

    def as_dict(self) -> dict:
        """给路由层与落库用的结构化形式。"""
        return {
            "device_id": self.device_id,
            "stage": self.stage,
            "reason": self.reason,
            "hint": self.hint,
            "evidence": self.evidence,
        }


class DeviceCommandError(RuntimeError):
    """设备可达，但这条命令失败了（路径不存在、无权限、pm 报错等）。

    与 DeviceUnreachable 的区别：设备本身是活的。同样**不许静默返回空结果** ——
    过去 list_apps/list_logcat/list_files 失败都返回 []，前端会显示成
    「没有应用 / 没有日志 / 空目录」，把「读不到」伪装成「没有」。
    """

    def __init__(self, device_id: int, what: str, detail: str = "") -> None:
        self.device_id = device_id
        self.what = what
        self.detail = detail
        super().__init__(f"设备 {device_id} {what}失败" + (f"：{detail}" if detail else ""))


@dataclass
class Provisioned:
    """create() 的返回：后端引用 + adb 端口。"""
    backend_ref: str
    adb_port: int


class DeviceBackend(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    async def create(self, device: Device) -> Provisioned:
        """按设备的指纹/显示参数创建实例（不一定启动）。"""

    @abc.abstractmethod
    async def start(self, device: Device) -> None: ...

    @abc.abstractmethod
    async def stop(self, device: Device) -> None: ...

    @abc.abstractmethod
    async def destroy(self, device: Device) -> None: ...

    # --- 操控 ---
    @abc.abstractmethod
    async def open_url(self, device: Device, url: str) -> None: ...

    @abc.abstractmethod
    async def tap(self, device: Device, x: int, y: int) -> None: ...

    @abc.abstractmethod
    async def swipe(self, device: Device, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None: ...

    @abc.abstractmethod
    async def input_text(self, device: Device, text: str) -> None: ...

    @abc.abstractmethod
    async def key(self, device: Device, key: str) -> None: ...

    @abc.abstractmethod
    async def install(self, device: Device, apk_url: str) -> None: ...

    @abc.abstractmethod
    async def screenshot(self, device: Device) -> str:
        """返回一帧画面的 data URL。"""

    def last_action(self, device: Device) -> str:
        """最近一次操控的可读描述；默认空字符串。

        用途：让 tap / swipe / 输入文本 这类**画面上看不出变化**的操作也有可见确认。
        否则用户点了按钮、后端返回 200，但预览纹丝不动，体验上等同于「没反应」。
        """
        return ""

    # --- 已装应用（GM-003 设备详情聚合）---
    async def list_apps(self, device: Device) -> list[str]:
        """返回设备已安装应用的包名列表。

        默认实现返回空列表（具体后端可覆盖），确保未实现的后端不会报错。
        """
        return []

    # --- 设备日志（7.5.3 logcat）---
    async def list_logcat(self, device: Device, lines: int = 200) -> list[str]:
        """返回最近 N 行 logcat；默认空（具体后端覆盖）。"""
        return []

    # --- 分辨率/DPI 运行时切换（CP-007）---
    async def set_display(self, device: Device, width: int, height: int, dpi: int) -> None:
        """运行时切换分辨率/DPI；默认仅更新记录（具体后端覆盖以真正下发）。"""
        device.width, device.height, device.dpi = width, height, dpi

    # --- 应用管理（GM-101/102/103/106）---
    async def uninstall_app(self, device: Device, package: str) -> None:
        """卸载应用；默认空实现。"""

    async def launch_app(self, device: Device, package: str) -> None:
        """启动应用；默认空实现。"""

    async def stop_app(self, device: Device, package: str) -> None:
        """强停应用；默认空实现。"""

    async def clear_app(self, device: Device, package: str) -> None:
        """清除应用数据；默认空实现。"""

    # --- 文件互传（PC-104 / 7.2.4）---
    async def list_files(self, device: Device, path: str = "/sdcard/") -> list[dict]:
        """列目录：返回 [{name, is_dir}]；默认空。"""
        return []

    async def push_file(self, device: Device, local_path: str, remote_path: str) -> None:
        """上传本地文件到设备；默认空。"""

    async def pull_file(self, device: Device, remote_path: str, local_path: str) -> bool:
        """下载设备文件到本地；成功返回 True；默认 False。"""
        return False

    async def delete_file(self, device: Device, remote_path: str) -> None:
        """删除设备文件/目录；默认空。"""

    async def apply_skin(self, device: Device, theme: str, progress=None) -> None:
        """把皮肤主题真正落到设备（如装启动器/换壁纸并重启）；默认空（模拟后端无真机）。

        progress: 可选 async 回调 progress(phase: str)，用于向前端上报落地进度
        （phase 取值见 redroid 实现：launcher/grid/wallpaper/reboot/prefs）。
        注意：真机实现通常耗时（含重启），应由调用方作为后台任务运行。
        """


def get_backend() -> DeviceBackend:
    from ..config import settings

    if settings.device_backend == "redroid":
        from .redroid import RedroidBackend

        return RedroidBackend()
    from .simulator import SimulatorBackend

    return SimulatorBackend()
