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
    DevicePage,
    DeviceUpdate,
)
from .. import services

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(get_current_user)])


async def _get_or_404(db: AsyncSession, device_id: int) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    return device


@router.get("", response_model=DevicePage)
async def list_devices(
    db: AsyncSession = Depends(get_db),
    group_id: int | None = None,
    ungrouped: bool = Query(False, description="只看未分组设备（group_id 为空）"),
    status: DeviceStatus | None = None,
    q: str | None = Query(None, description="\u641c\u7d22\u8bbe\u5907\u540d/IP/\u578b\u53f7/\u5e8f\u5217\u53f7/Android ID/\u8bbe\u5907ID"),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
) -> dict:
    from sqlalchemy import func, or_

    stmt = select(Device).order_by(Device.id)
    if ungrouped:
        stmt = stmt.where(Device.group_id.is_(None))
    elif group_id is not None:
        stmt = stmt.where(Device.group_id == group_id)
    if status is not None:
        stmt = stmt.where(Device.status == status)
    if q:
        from sqlalchemy import cast, String

        kw = f"%{q}%"
        # fingerprint 是 JSON 列。**不能**用 func.json_extract —— 那是 SQLite(JSON1) 专属，
        # Postgres 没有该函数，搜索会 UndefinedFunctionError → 500（线上真实事故）。
        # 也不能用 `.astext`（Postgres JSONB 专属，SQLite 会 AttributeError）。
        # 通用做法：整列 cast 成字符串后模糊匹配，两种库都原生支持，
        # 一并覆盖模型/序列号/Android ID/出口 IP 等所有嵌套字段。
        stmt = stmt.where(
            or_(
                Device.name.ilike(kw),
                cast(Device.fingerprint, String).ilike(kw),
                Device.current_url.ilike(kw),
            )
        )

    # count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # 前端不传分页参数时默认返回全部；传了 page/page_size 才分页
    if page is not None and page_size is not None:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())

    return {
        "total": total,
        "page": page or 1,
        "page_size": page_size if page_size is not None else len(items),
        "items": items,
    }


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
    """一键创建/启动 N 台云手机。优先从预热池分配，池空走异步创建+后台并发启动。"""
    from ..pool import pool

    base = len((await db.execute(select(Device.id))).all())
    devices: list[Device] = []

    for i in range(1, body.count + 1):
        name = f"{body.name_prefix}-{base + i:03d}"

        # 优先从预热池取已启动的设备
        pooled = await pool.acquire()
        if pooled is not None:
            pooled_in_db = await db.get(Device, pooled.id)
            if pooled_in_db is not None:
                pooled_in_db.name = name
                pooled_in_db.group_id = body.group_id
                if body.target_url:
                    pooled_in_db.current_url = body.target_url
                await db.commit()
                await db.refresh(pooled_in_db)
                await services.broadcast_device(pooled_in_db)
                devices.append(pooled_in_db)
                continue

        # 池子空了，走异步创建（不自动启动，后台并发启动）
        device = await services.create_device(
            db,
            name=name,
            group_id=body.group_id,
            width=body.width,
            height=body.height,
            dpi=body.dpi,
            target_url=body.target_url,
            auto_start=False,  # 不阻塞，后台并发启动
        )
        devices.append(device)

    # 后台并发启动非池子的设备（池子设备已经是 running）
    non_pooled = [d for d in devices if d.status != DeviceStatus.running]
    if non_pooled:
        from ..database import SessionLocal

        asyncio.create_task(
            services.start_devices_concurrent(
                db_factory=SessionLocal,
                devices=non_pooled,
                max_concurrent=5,
                target_url=body.target_url,
            )
        )

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