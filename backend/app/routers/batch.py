"""批量操作 + 同步操控（demo 验收 §7：一键让全部设备打开同一网页并同步执行一组操作）。

D11 批量开 URL / 批量点击·滑动·输入 / 批量装 APK；
D12 同步操控（1 控 N）：主控动作广播到选中从机，跨分辨率坐标适配。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Device, User
from ..rbac import _check_device_access
from ..schemas import (
    BatchInstall,
    BatchKey,
    BatchOpenUrl,
    BatchResult,
    BatchSwipe,
    BatchTap,
    BatchText,
)
from .. import services
from ..ws_manager import manager

router = APIRouter(prefix="/batch", tags=["batch"], dependencies=[Depends(get_current_user)])


async def _fetch(db: AsyncSession, ids: list[int]) -> list[Device]:
    return list((await db.execute(select(Device).where(Device.id.in_(ids)))).scalars().all())


async def _run_all(db: AsyncSession, ids: list[int], action_name: str, fn, user: User) -> BatchResult:
    """对目标设备并发执行 fn(device)，实时广播进度，汇总结果。"""
    devices = await _fetch(db, ids)
    for device in devices:
        _check_device_access(user, device)
    details: list[dict] = []
    done = 0

    async def _one(device: Device) -> None:
        nonlocal done
        try:
            await fn(device)
            details.append({"device_id": device.id, "name": device.name, "ok": True})
        except Exception as e:  # noqa: BLE001
            details.append({"device_id": device.id, "name": device.name, "ok": False, "error": str(e)})
        finally:
            done += 1
            await manager.broadcast(
                {"type": "batch_progress", "action": action_name, "done": done, "total": len(devices)}
            )

    await asyncio.gather(*[_one(d) for d in devices])
    await db.commit()
    ok = sum(1 for d in details if d["ok"])
    return BatchResult(total=len(devices), ok=ok, failed=len(devices) - ok, details=details)


def _scale(device: Device, x: int, y: int, ref_w: int = 1080, ref_h: int = 1920) -> tuple[int, int]:
    """跨分辨率坐标适配：主控坐标按参考分辨率折算到目标设备。"""
    return int(x * device.width / ref_w), int(y * device.height / ref_h)


@router.post("/open_url", response_model=BatchResult)
async def batch_open_url(body: BatchOpenUrl, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> BatchResult:
    async def fn(d: Device) -> None:
        await services.backend.open_url(d, body.url)
        await services.broadcast_device(d)

    return await _run_all(db, body.device_ids, "open_url", fn, user)


@router.post("/tap", response_model=BatchResult)
async def batch_tap(body: BatchTap, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> BatchResult:
    async def fn(d: Device) -> None:
        x, y = _scale(d, body.x, body.y)
        await services.backend.tap(d, x, y)

    return await _run_all(db, body.device_ids, "tap", fn, user)


@router.post("/swipe", response_model=BatchResult)
async def batch_swipe(body: BatchSwipe, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> BatchResult:
    async def fn(d: Device) -> None:
        x1, y1 = _scale(d, body.x1, body.y1)
        x2, y2 = _scale(d, body.x2, body.y2)
        await services.backend.swipe(d, x1, y1, x2, y2, body.duration_ms)

    return await _run_all(db, body.device_ids, "swipe", fn, user)


@router.post("/text", response_model=BatchResult)
async def batch_text(body: BatchText, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> BatchResult:
    async def fn(d: Device) -> None:
        await services.backend.input_text(d, body.text)

    return await _run_all(db, body.device_ids, "text", fn, user)


@router.post("/key", response_model=BatchResult)
async def batch_key(body: BatchKey, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> BatchResult:
    async def fn(d: Device) -> None:
        await services.backend.key(d, body.key)

    return await _run_all(db, body.device_ids, "key", fn, user)


@router.post("/install", response_model=BatchResult)
async def batch_install(body: BatchInstall, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> BatchResult:
    async def fn(d: Device) -> None:
        await services.backend.install(d, body.apk_url)

    return await _run_all(db, body.device_ids, "install", fn, user)
