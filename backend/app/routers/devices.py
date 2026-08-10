"""设备生命周期（D4 编排 API）：创建 / 批量建 N 台 / 启停 / 删除 / 列表 / 详情 / 截图。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Device, DeviceStatus, User
from ..schemas import (
    DeviceBatchCreate,
    DeviceBatchDelete,
    DeviceCreate,
    DeviceOut,
    DeviceUpdate,
)
from .. import services

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(get_current_user)])


async def _get_or_404(db: AsyncSession, device_id: int) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    return device


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    group_id: int | None = None,
    status: DeviceStatus | None = None,
    q: str | None = Query(None, description="按名称模糊搜索"),
) -> list[Device]:
    stmt = select(Device).order_by(Device.id)
    if group_id is not None:
        stmt = stmt.where(Device.group_id == group_id)
    if status is not None:
        stmt = stmt.where(Device.status == status)
    if q:
        stmt = stmt.where(Device.name.ilike(f"%{q}%"))
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=DeviceOut)
async def create_device(body: DeviceCreate, db: AsyncSession = Depends(get_db)) -> Device:
    # 生成默认名
    if not body.name:
        count = len((await db.execute(select(Device.id))).all())
        body.name = f"云手机-{count + 1:03d}"
    return await services.create_device(
        db,
        name=body.name,
        group_id=body.group_id,
        width=body.width,
        height=body.height,
        dpi=body.dpi,
        target_url=body.target_url,
        proxy=body.proxy,
    )


@router.post("/batch", response_model=list[DeviceOut])
async def batch_create(body: DeviceBatchCreate, db: AsyncSession = Depends(get_db)) -> list[Device]:
    """一键创建/启动 N 台云手机（demo 验收 §2 建机）。"""
    base = len((await db.execute(select(Device.id))).all())
    devices: list[Device] = []
    # 并发拉起，提高 demo 建机体验
    async def _one(i: int) -> Device:
        return await services.create_device(
            db,
            name=f"{body.name_prefix}-{base + i:03d}",
            group_id=body.group_id,
            width=body.width,
            height=body.height,
            dpi=body.dpi,
            target_url=body.target_url,
            auto_start=body.auto_start,
        )

    # SQLite 单连接不宜高并发写，顺序建；Postgres 可改并发
    for i in range(1, body.count + 1):
        devices.append(await _one(i))
    return devices


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)) -> Device:
    return await _get_or_404(db, device_id)


@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(device_id: int, body: DeviceUpdate, db: AsyncSession = Depends(get_db)) -> Device:
    device = await _get_or_404(db, device_id)
    if body.name is not None:
        device.name = body.name
    if body.group_id is not None:
        device.group_id = body.group_id
    await db.commit()
    await db.refresh(device)
    await services.broadcast_device(device)
    return device


@router.delete("/{device_id}")
async def delete_device(device_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    device = await _get_or_404(db, device_id)
    await services.destroy_device(db, device)
    return {"ok": True}


@router.post("/batch/delete")
async def batch_delete(body: DeviceBatchDelete, db: AsyncSession = Depends(get_db)) -> dict:
    """批量删除设备。

    切换过设备后端、或冒烟测试留下几十台废设备时，一台台点「删除」不可接受
    （甲方现场就卡在这里）。逐台删除并**逐台记录结果**：某台底层容器已不存在时
    不能整批失败，也不能静默跳过 —— 返回 failed 明细，让界面能说清哪几台没删掉。
    """
    ok, failed = 0, []
    for did in body.device_ids:
        device = await db.get(Device, did)
        if device is None:
            failed.append({"device_id": did, "error": "设备不存在（可能已被删除）"})
            continue
        name = device.name
        try:
            await services.destroy_device(db, device)
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"device_id": did, "name": name, "error": f"{e.__class__.__name__}: {e}"})
    return {"total": len(body.device_ids), "ok": ok, "failed": len(failed), "details": failed}


@router.post("/{device_id}/start", response_model=DeviceOut)
async def start_device(device_id: int, db: AsyncSession = Depends(get_db)) -> Device:
    return await services.start_device(db, await _get_or_404(db, device_id))


@router.post("/{device_id}/stop", response_model=DeviceOut)
async def stop_device(device_id: int, db: AsyncSession = Depends(get_db)) -> Device:
    return await services.stop_device(db, await _get_or_404(db, device_id))


@router.post("/{device_id}/restart", response_model=DeviceOut)
async def restart_device(device_id: int, db: AsyncSession = Depends(get_db)) -> Device:
    device = await _get_or_404(db, device_id)
    await services.stop_device(db, device)
    await asyncio.sleep(0.05)
    return await services.start_device(db, device)


@router.get("/{device_id}/screenshot")
async def screenshot(device_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    device = await _get_or_404(db, device_id)
    frame = await services.backend.screenshot(device)
    # last_action 一并返回：tap / swipe / 输入文本 这类操作在画面上看不出变化，
    # 前端把它显示在预览卡片上，用户才知道指令确实到了设备
    return {
        "device_id": device_id,
        "frame": frame,
        "last_action": services.backend.last_action(device),
    }
