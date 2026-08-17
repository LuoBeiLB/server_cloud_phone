"""WebSocket：实时推送设备状态/批量进度（广播）+ 按订阅推送预览帧。

前端消息协议：
  客户端 → 服务端: {"type":"subscribe","device_ids":[1,2,3],"fps":1}
  服务端 → 客户端:
    {"type":"device_status","device":{...}}
    {"type":"batch_progress","action":"open_url","done":3,"total":10}
    {"type":"preview","device_id":1,"frame":"data:image/svg+xml;base64,..."}
    {"type":"device_unreachable","device_id":1,"name":"真机-001","detail":"device offline"}
    {"type":"script_done","run_id":1,"status":"success"}
"""
from __future__ import annotations

import asyncio

import jwt

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import Device, User
from ..rbac import _check_device_access
from ..orchestrator.base import DeviceUnreachable
from ..services import backend
from ..ws_manager import manager

router = APIRouter()

MAX_PREVIEW_FPS = 30

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


async def _get_ws_user(ws: WebSocket, db) -> User | None:
    """从 WebSocket 查询参数 token 解析当前用户。"""
    token = ws.query_params.get("token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username = payload.get("sub")
        if not username:
            return None
    except jwt.PyJWTError:
        return None
    return (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()


async def _preview_loop(ws: WebSocket, state: dict) -> None:
    """按订阅列表周期性渲染并推送预览帧。"""
    while True:
        ids = state.get("device_ids", [])
        interval = max(1.0 / MAX_PREVIEW_FPS, 1.0 / max(1, min(MAX_PREVIEW_FPS, state.get("fps", 1))))
        if ids:
            async with SessionLocal() as db:
                devices = list(
                    (await db.execute(select(Device).where(Device.id.in_(ids)))).scalars().all()
                )
            for d in devices:
                # 单台失联不能拖垮整条预览循环（否则一台掉线，所有人的画面全停）；
                # 且必须把失联如实推给前端，而不是继续推旧帧/皮肤图假装正常。
                try:
                    frame = await backend.screenshot(d)
                except DeviceUnreachable as e:
                    try:
                        await ws.send_json({
                            "type": "device_unreachable",
                            "device_id": d.id,
                            "name": d.name,
                            "detail": e.detail,
                        })
                    except Exception:  # noqa: BLE001  socket 已关
                        return
                    continue
                except Exception:  # noqa: BLE001  其它后端异常：跳过这台，不中断循环
                    continue
                try:
                    await ws.send_json({"type": "preview", "device_id": d.id, "frame": frame})
                except Exception:  # noqa: BLE001  socket 关闭时退出
                    return
        await asyncio.sleep(interval)


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    state: dict = {"device_ids": [], "fps": 1}
    async with SessionLocal() as db:
        user = await _get_ws_user(ws, db)
    preview_task = asyncio.create_task(_preview_loop(ws, state))
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "subscribe":
                ids = msg.get("device_ids", [])
                if user is not None:
                    async with SessionLocal() as db:
                        devices = list((await db.execute(select(Device).where(Device.id.in_(ids)))).scalars().all())
                        allowed = {d.id for d in devices if user.role in ("admin", "superadmin") or d.created_by == user.id}
                        ids = [i for i in ids if i in allowed]
                state["device_ids"] = ids
                state["fps"] = msg.get("fps", 1)
            elif msg.get("type") == "input_text":
                device_id = msg.get("device_id")
                text = msg.get("text", "")
                if device_id and text and user is not None:
                    async with SessionLocal() as db:
                        device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
                        if device:
                            try:
                                _check_device_access(user, device)
                                await backend.input_text(device, text)
                            except HTTPException:
                                pass
            elif msg.get("type") == "key_event":
                device_id = msg.get("device_id")
                key = msg.get("key", "")
                if device_id and key and user is not None:
                    async with SessionLocal() as db:
                        device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
                        if device:
                            try:
                                _check_device_access(user, device)
                                code = _KEYEVENT_MAP.get(key, key)
                                await backend.key(device, code)
                            except HTTPException:
                                pass
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        preview_task.cancel()
        await manager.disconnect(ws)