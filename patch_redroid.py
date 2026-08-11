import os

path = r'E:\server_cloud_phone\backend\app\orchestrator\redroid.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '    async def input_text(self, device: Device, text: str) -> None:\n        await self._adb(device, "shell", "input", "text", text.replace(" ", "%s"))\n\n    async def key(self, device: Device, key: str) -> None:'

new = '''    async def input_text(self, device: Device, text: str) -> None:
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
        """确保 ADBKeyboard 输入法已安装并启用。返回 True 表示可用。"""
        import logging
        logger = logging.getLogger("redroid")
        code, out, _ = await self._adb(device, "shell", "pm", "list", "packages", "com.android.adbkeyboard")
        if b"com.android.adbkeyboard" in out:
            return True
        apk = os.path.join(_SKIN_DIR, "ADBKeyboard.apk")
        if not os.path.exists(apk):
            logger.warning(
                "缺少 ADBKeyboard.apk（%s），键盘输入将降级为仅支持 ASCII。"
                "放置 APK 到 app/skins/ADBKeyboard.apk 或执行 deploy/redroid/install-adbkeyboard.sh",
                apk,
            )
            return False
        code, _, err = await self._adb(device, "install", "-r", apk)
        if code != 0:
            logger.warning(
                "ADBKeyboard 安装失败：%s", err.decode(errors="replace").strip()[:200],
            )
            return False
        await self._adb(device, "shell", "ime", "enable", "com.android.adbkeyboard/.AdbIME")
        logger.info("设备 %s ADBKeyboard 安装并启用完成", device.id)
        return True

    async def key(self, device: Device, key: str) -> None:'''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK - redroid.py patched')
else:
    print('NOT FOUND - checking around line 470...')
    lines = content.split('\n')
    for i in range(468, 476):
        print(f'  {i+1}: {repr(lines[i])}')