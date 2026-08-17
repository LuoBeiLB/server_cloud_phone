"""单机实时操控（demo 验收 §6：点开任一台，实时操控浏览器）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Device, User
from ..rbac import _check_device_access
from ..schemas import DisplayCmd, InstallCmd, KeyCmd, OpenUrlCmd, SwipeCmd, TapCmd, TextCmd
from .. import services

router = APIRouter(
    prefix="/devices/{device_id}/control",
    tags=["control"],
    dependencies=[Depends(get_current_user)],
)


async def _get(db: AsyncSession, device_id: int, user: User) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    _check_device_access(user, device)
    return device


@router.post("/open_url")
async def open_url(device_id: int, cmd: OpenUrlCmd, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    device = await _get(db, device_id, user)
    await services.backend.open_url(device, cmd.url)
    await db.commit()
    await services.broadcast_device(device)
    return {"ok": True, "url": cmd.url}


@router.post("/tap")
async def tap(device_id: int, cmd: TapCmd, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.tap(await _get(db, device_id), cmd.x, cmd.y)
    return {"ok": True}


@router.post("/swipe")
async def swipe(device_id: int, cmd: SwipeCmd, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.swipe(await _get(db, device_id), cmd.x1, cmd.y1, cmd.x2, cmd.y2, cmd.duration_ms)
    return {"ok": True}


@router.post("/text")
async def text(device_id: int, cmd: TextCmd, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    await services.backend.input_text(await _get(db, device_id, user), cmd.text)
    return {"ok": True}


@router.post("/key")
async def key(device_id: int, cmd: KeyCmd, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.key(await _get(db, device_id), cmd.key)
    return {"ok": True}


@router.post("/install")
async def install(device_id: int, cmd: InstallCmd, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    await services.backend.install(await _get(db, device_id, user), cmd.apk_url)
    return {"ok": True}


@router.post("/display")
async def set_display(device_id: int, cmd: DisplayCmd, db: AsyncSession = Depends(get_db)) -> dict:
    """运行时切换分辨率/DPI（CP-007）。"""
    device = await _get(db, device_id)
    await services.backend.set_display(device, cmd.width, cmd.height, cmd.dpi)
    await db.commit()
    await services.broadcast_device(device)
    return {"ok": True, "width": cmd.width, "height": cmd.height, "dpi": cmd.dpi}
