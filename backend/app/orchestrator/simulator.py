"""模拟器后端：在没有 Docker/Redroid 的机器上跑通全部主流程。

它维护一份内存态（每台设备的当前页面、最近一次操作），并用 preview.render_frame
把状态渲染成 iOS 皮肤画面。所有操控/批量/脚本回放都会真实改变这份状态，
因此 Web 多画面预览、单机操控、批量同步、脚本回放在 demo 中都能被肉眼验证。
"""
from __future__ import annotations

import asyncio
import itertools

from ..models import Device
from ..preview import render_frame
from .base import DeviceBackend, DeviceCommandError, DeviceUnreachable, Provisioned

_port_seq = itertools.count(6001)

# 每台设备初始的虚拟文件系统。
# 键是目录（结尾带 /），值是该目录下的条目。**必须按 path 真实分层** ——
# 早期实现的 list_files 直接忽略 path 参数、任何目录都返回同一份列表，于是
# 点进子目录后路径栏变了、内容纹丝不动，用户看到的就是「点击没反应」。
def _initial_fs() -> dict[str, list[dict]]:
    return {
        "/sdcard/": [
            {"name": "Download", "is_dir": True},
            {"name": "Pictures", "is_dir": True},
            {"name": "DCIM", "is_dir": True},
            {"name": "demo.txt", "is_dir": False},
            {"name": "screenshot.png", "is_dir": False},
        ],
        "/sdcard/Download/": [
            {"name": "app-release.apk", "is_dir": False},
            {"name": "手册.pdf", "is_dir": False},
        ],
        "/sdcard/Pictures/": [
            {"name": "Screenshots", "is_dir": True},
            {"name": "wallpaper.jpg", "is_dir": False},
        ],
        "/sdcard/Pictures/Screenshots/": [
            {"name": "Screenshot_001.png", "is_dir": False},
        ],
        "/sdcard/DCIM/": [
            {"name": "Camera", "is_dir": True},
        ],
        "/sdcard/DCIM/Camera/": [],  # 故意留空：用于验证「空目录」与「读不到」的区别
    }


_DEFAULT_APPS = [
    "com.android.chrome",
    "com.android.launcher3",
    "com.android.settings",
    "com.android.vending",
    "com.android.webview",
    "org.chromium.webview_shell",
]

# 按键 -> 预览画面。render_frame 本就支持这些屏幕，此前一直没接上，
# 导致「同步 Home」「通知栏」「控制中心」点了之后画面完全不变。
_KEY_SCREEN = {
    "home": "home",
    "wake": "home",
    "power": "lock",
    "recent": "applibrary",
    "menu": "applibrary",
    "notifications": "today",
    "quicksettings": "control",
}


def _norm_dir(path: str) -> str:
    """规范成「以 / 结尾」的目录键。"""
    p = (path or "/sdcard/").strip() or "/sdcard/"
    if not p.startswith("/"):
        p = "/" + p
    return p if p.endswith("/") else p + "/"


def _split_remote(remote: str) -> tuple[str, str]:
    """把 /sdcard/Download/a.txt 拆成 ("/sdcard/Download/", "a.txt")。"""
    r = (remote or "").rstrip("/")
    idx = r.rfind("/")
    return (r[: idx + 1] or "/", r[idx + 1 :])


class SimulatorBackend(DeviceBackend):
    name = "simulator"

    # 进程内共享的运行态：device_id -> {
    #   "last_action": str,   最近一次操作（随截图返回，让每个操作都有可见确认）
    #   "screen": str,        当前屏幕，交给 render_frame
    #   "running": bool,      是否已启动（stop 后截图要能反映出来）
    #   "fs": dict,           虚拟文件系统
    #   "apps": list[str],    已装应用（install/uninstall 要真实生效）
    # }
    _runtime: dict[int, dict] = {}

    def _rt(self, device: Device) -> dict:
        rt = self._runtime.setdefault(device.id, {})
        rt.setdefault("last_action", "idle")
        rt.setdefault("screen", "auto")
        rt.setdefault("running", True)
        rt.setdefault("fs", _initial_fs())
        rt.setdefault("apps", list(_DEFAULT_APPS))
        return rt

    def _act(self, device: Device, action: str, screen: str | None = None) -> None:
        """记录一次操作。screen 非空则同时切换画面，使操作在预览里肉眼可见。"""
        rt = self._rt(device)
        rt["last_action"] = action
        if screen is not None:
            rt["screen"] = screen

    def last_action(self, device: Device) -> str:
        return self._runtime.get(device.id, {}).get("last_action", "idle")

    async def create(self, device: Device) -> Provisioned:
        await asyncio.sleep(0.02)  # 模拟拉起耗时
        port = next(_port_seq)
        return Provisioned(backend_ref=f"sim-{device.id}", adb_port=port)

    async def start(self, device: Device) -> None:
        rt = self._rt(device)
        rt["running"] = True
        self._act(device, "started", screen="home")

    async def stop(self, device: Device) -> None:
        # 不能整条 pop：虚拟文件系统与已装应用要在重启后保留，
        # 否则「停止→启动」会把用户上传的文件、卸载的应用全悄悄还原。
        rt = self._rt(device)
        rt["running"] = False
        self._act(device, "stopped", screen="lock")

    async def destroy(self, device: Device) -> None:
        self._runtime.pop(device.id, None)

    def _require_running(self, device: Device) -> None:
        """已停止的设备不接受操控。

        此前无论设备是停止还是运行，操控都「成功」返回，界面上看不出区别 ——
        这正是禁止静默降级要防的：把「没生效」伪装成「成功」。
        """
        if not self._rt(device)["running"]:
            raise DeviceUnreachable(device.id, f"sim-{device.id}", "设备已停止，请先启动后再操作")

    async def open_url(self, device: Device, url: str) -> None:
        self._require_running(device)
        device.current_url = url
        self._act(device, f"打开网页 {url}", screen="browser")

    async def tap(self, device: Device, x: int, y: int) -> None:
        self._require_running(device)
        self._act(device, f"点击 ({x},{y})")

    async def swipe(self, device: Device, x1, y1, x2, y2, duration_ms) -> None:
        self._require_running(device)
        # 上滑（y 变小）回主屏，下滑（y 变大）拉出 Spotlight —— 与 iOS 手势语义一致，
        # 这样「同步上滑/下滑」在预览里能看出变化，而不是只有一条日志。
        screen = "home" if y2 < y1 else "spotlight"
        self._act(device, f"滑动 ({x1},{y1})→({x2},{y2})", screen=screen)

    async def input_text(self, device: Device, text: str) -> None:
        self._require_running(device)
        self._act(device, f"输入文本「{text}」")

    async def key(self, device: Device, key: str) -> None:
        self._require_running(device)
        self._act(device, f"按键 {key}", screen=_KEY_SCREEN.get(key))

    async def install(self, device: Device, apk_url: str) -> None:
        self._require_running(device)
        rt = self._rt(device)
        # 从 URL 猜个包名，让「已装应用」列表真实发生变化
        stem = apk_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".apk") or "unknown"
        pkg = f"com.demo.{''.join(c for c in stem if c.isalnum()) or 'app'}".lower()
        if pkg not in rt["apps"]:
            rt["apps"].append(pkg)
        self._act(device, f"安装 {pkg}（来自 {apk_url}）")
    async def install_from_local_file(self, device: Device, local_path: str) -> None:

        print("=== SIMULATOR install_from_local_file 被调用了 ===")
        raise RuntimeError("模拟器后端不支持安装本地 APK，请在 redroid 环境中测试")

    async def screenshot(self, device: Device) -> str:
        rt = self._rt(device)
        if not rt["running"]:
            # 已停止就渲染锁屏，别让停掉的设备继续输出「像在正常运行」的画面
            return render_frame(
                device.name, None, device.fingerprint or {}, screen="lock",
                theme=getattr(device, "skin", "ios") or "ios",
            )
        return render_frame(
            device.name, device.current_url, device.fingerprint or {},
            screen=rt["screen"],
            theme=getattr(device, "skin", "ios") or "ios",
        )

    async def list_apps(self, device: Device) -> list[str]:
        # 返回**这台设备**的当前应用集合：install/uninstall 会真实改变它。
        # 早期实现返回恒定常量，导致卸载后应用还在列表里。
        return sorted(self._rt(device)["apps"])

    async def list_logcat(self, device: Device, lines: int = 200) -> list[str]:
        last = self._runtime.get(device.id, {}).get("last_action", "idle")
        return [
            f"07-17 10:00:0{i} I ActivityManager: [sim:{device.name}] tick {i} last={last}"
            for i in range(1, 9)
        ]

    async def set_display(self, device: Device, width: int, height: int, dpi: int) -> None:
        device.width, device.height, device.dpi = width, height, dpi
        self._runtime.setdefault(device.id, {})["last_action"] = f"display {width}x{height}@{dpi}"

    async def uninstall_app(self, device: Device, package: str) -> None:
        rt = self._rt(device)
        if package not in rt["apps"]:
            # 「卸载一个不存在的包」必须报错而不是假装成功
            raise DeviceCommandError(device.id, f"卸载 {package}", "该应用未安装")
        rt["apps"].remove(package)
        self._act(device, f"卸载 {package}")

    async def launch_app(self, device: Device, package: str) -> None:
        rt = self._rt(device)
        if package not in rt["apps"]:
            raise DeviceCommandError(device.id, f"启动 {package}", "该应用未安装")
        self._act(device, f"启动 {package}", screen="browser" if "chrome" in package else "home")

    async def stop_app(self, device: Device, package: str) -> None:
        self._act(device, f"强停 {package}", screen="home")

    async def clear_app(self, device: Device, package: str) -> None:
        self._act(device, f"清除数据 {package}")

    # ---------- 虚拟文件系统 ----------
    #
    # 按 path 真实分层。三条硬要求：
    #   1) 不同目录返回不同内容（否则点进子目录看起来「没反应」）
    #   2) 目录不存在必须报错，不能返回空列表 —— 「读不到」和「本来就是空的」
    #      必须能区分（/sdcard/DCIM/Camera/ 就是一个真的空目录，用来体现这个区别）
    #   3) 上传/删除要真实改变列表，否则操作完看不出效果

    async def list_files(self, device: Device, path: str = "/sdcard/") -> list[dict]:
        rt = self._rt(device)
        key = _norm_dir(path)
        if key not in rt["fs"]:
            raise DeviceCommandError(
                device.id, f"读取目录 {key}", "目录不存在（模拟后端仅提供 /sdcard 下的若干目录）"
            )
        return list(rt["fs"][key])

    async def push_file(self, device: Device, local_path: str, remote_path: str) -> None:
        rt = self._rt(device)
        d, name = _split_remote(remote_path)
        d = _norm_dir(d)
        if d not in rt["fs"]:
            raise DeviceCommandError(device.id, f"上传到 {d}", "目标目录不存在")
        if not name:
            raise DeviceCommandError(device.id, "上传", "远端路径缺少文件名")
        entries = rt["fs"][d]
        if not any(e["name"] == name for e in entries):
            entries.append({"name": name, "is_dir": False})
        self._act(device, f"上传 {name} 到 {d}")

    async def pull_file(self, device: Device, remote_path: str, local_path: str) -> bool:
        rt = self._rt(device)
        d, name = _split_remote(remote_path)
        d = _norm_dir(d)
        if not any(e["name"] == name and not e["is_dir"] for e in rt["fs"].get(d, [])):
            raise DeviceCommandError(device.id, f"下载 {remote_path}", "文件不存在")
        with open(local_path, "w") as f:
            f.write(f"[sim] {device.name} pulled {remote_path}\n")
        self._act(device, f"下载 {name}")
        return True

    async def delete_file(self, device: Device, remote_path: str) -> None:
        rt = self._rt(device)
        d, name = _split_remote(remote_path)
        d = _norm_dir(d)
        entries = rt["fs"].get(d)
        if entries is None:
            raise DeviceCommandError(device.id, f"删除 {remote_path}", "所在目录不存在")
        hit = next((e for e in entries if e["name"] == name), None)
        if hit is None:
            raise DeviceCommandError(device.id, f"删除 {remote_path}", "文件或目录不存在")
        entries.remove(hit)
        if hit["is_dir"]:
            # 连带清掉该目录及其子树，避免留下访问不到的孤儿目录
            prefix = _norm_dir(d + name)
            for k in [k for k in rt["fs"] if k.startswith(prefix)]:
                rt["fs"].pop(k, None)
        self._act(device, f"删除 {name}")
