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

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..database import SessionLocal
from ..models import Device
from ..orchestrator.base import DeviceUnreachable
from ..services import backend
from ..ws_manager import manager

router = APIRouter()

# 预览帧率上限 60fps（前端可选 10~60）。
# 实际能跑多高取决于单帧截图耗时：simulator 渲染快基本能跑满；
# 真机 screencap ~64ms，≈15fps 封顶 —— 这里只放开间隔钳制，不硬顶设备。
MAX_PREVIEW_FPS = 60


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
    preview_task = asyncio.create_task(_preview_loop(ws, state))
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "subscribe":
                state["device_ids"] = msg.get("device_ids", [])
                state["fps"] = msg.get("fps", 1)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        preview_task.cancel()
        await manager.disconnect(ws)
