path = r'E:\server_cloud_phone\backend\app\routers\ws.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在 router = APIRouter() 后面插入 _KEYEVENT_MAP
old1 = 'router = APIRouter()\n\n\nasync def _preview_loop'
new1 = '''router = APIRouter()

_KEYEVENT_MAP = {
    "enter": "KEYCODE_ENTER",
    "backspace": "KEYCODE_DEL",
    "delete": "KEYCODE_FORWARD_DEL",
    "tab": "KEYCODE_TAB",
    "escape": "KEYCODE_ESCAPE",
    "arrow_up": "KEYCODE_DPAD_UP",
    "arrow_down": "KEYCODE_DPAD_DOWN",
    "arrow_left": "KEYCODE_DPAD_LEFT",
    "arrow_right": "KEYCODE_DPAD_RIGHT",
    "space": "KEYCODE_SPACE",
}


async def _preview_loop'''

if old1 in content:
    content = content.replace(old1, new1)
else:
    print('STEP 1 NOT FOUND')
    exit(1)

# 2. 在 subscribe 处理后面插入 input_text 和 key_event 处理
old2 = '''            if msg.get("type") == "subscribe":
                state["device_ids"] = msg.get("device_ids", [])
                state["fps"] = msg.get("fps", 1)
    except WebSocketDisconnect:'''

new2 = '''            if msg.get("type") == "subscribe":
                state["device_ids"] = msg.get("device_ids", [])
                state["fps"] = msg.get("fps", 1)
            elif msg.get("type") == "input_text":
                device_id = msg.get("device_id")
                text = msg.get("text", "")
                if device_id and text:
                    async with SessionLocal() as db:
                        device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
                    if device:
                        await backend.input_text(device, text)
            elif msg.get("type") == "key_event":
                device_id = msg.get("device_id")
                key = msg.get("key", "")
                if device_id and key:
                    async with SessionLocal() as db:
                        device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
                    if device:
                        code = _KEYEVENT_MAP.get(key, key)
                        await backend.key(device, code)
    except WebSocketDisconnect:'''

if old2 in content:
    content = content.replace(old2, new2)
else:
    print('STEP 2 NOT FOUND')
    exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('OK - ws.py patched')