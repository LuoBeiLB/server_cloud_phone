"""设备服务层：把「数据库 + 编排后端 + 指纹 + WS 广播」编排到一起。

routers 调用这里，避免在路由里堆业务逻辑。
"""
from __future__ import annotations

import logging
import random

from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .fingerprint import generate_fingerprint
from .models import Device, DeviceStatus
from .orchestrator import get_backend
from .orchestrator.base import DeviceProvisionError, DeviceUnreachable
from .schemas import DeviceOut
from .ws_manager import manager

logger = logging.getLogger(__name__)

backend = get_backend()


def _pick_proxy() -> str | None:
    return random.choice(settings.proxy_pool) if settings.proxy_pool else None


def _describe_failure(e: BaseException) -> str:
    """把异常整理成前端可直接展示的一段话：原因 ｜ 处置 ｜ 证据。

    落到 Device.last_error。目的是让「状态：异常」后面永远有下文 ——
    甲方不必 ssh 上服务器翻日志就能知道是镜像没拉、binder 缺失还是内存不够。
    """
    if isinstance(e, DeviceProvisionError):
        parts = [e.reason]
        if e.hint:
            parts.append(f"处置：{e.hint}")
        if e.evidence:
            parts.append(f"证据：{e.evidence}")
        return " ｜ ".join(parts)[:2000]
    if isinstance(e, DeviceUnreachable):
        return str(e)[:2000]
    # 兜底：至少带上异常类型，别只留一句 str(e) 可能为空的报文
    return f"{e.__class__.__name__}: {e}"[:2000] or e.__class__.__name__


async def create_device(
    db: AsyncSession,
    *,
    name: str,
    group_id: int | None,
    width: int,
    height: int,
    dpi: int,
    target_url: str | None = None,
    proxy: str | None = None,
    auto_start: bool = True,
) -> Device:
    """建库 → 生成一机一码 → 后端拉起（可选自动启动）。"""
    fp = generate_fingerprint(proxy=proxy or _pick_proxy())
    device = Device(
        name=name,
        group_id=group_id,
        width=width,
        height=height,
        dpi=dpi,
        current_url=target_url,
        fingerprint=fp,
        status=DeviceStatus.creating,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    try:
        prov = await backend.create(device)
        device.backend_ref = prov.backend_ref
        device.adb_port = prov.adb_port
        if auto_start:
            await backend.start(device)
            if target_url:
                await backend.open_url(device, target_url)
            device.status = DeviceStatus.running
        else:
            device.status = DeviceStatus.stopped
        device.last_error = None
    except Exception as e:  # noqa: BLE001
        # 单台拉起失败不阻塞其它设备（批量建机的前提），但**原因必须留下**。
        # 过去这里是空的 `except Exception: 标记 error`，界面上只有「状态：异常」，
        # 没有任何线索，是「无法拉起云手机又查不出问题」的直接原因。
        device.status = DeviceStatus.error
        device.last_error = _describe_failure(e)
        logger.warning("设备 %s(%s) 拉起失败：%s", device.id, device.name, device.last_error)

    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def start_device(db: AsyncSession, device: Device) -> Device:
    # 失败要同时做两件事：把原因落库让界面能显示，以及**继续抛**让接口明确报错。
    # 只做前者会让调用方以为成功，只做后者则页面刷新后又看不到原因。
    try:
        await backend.start(device)
    except Exception as e:  # noqa: BLE001
        device.status = DeviceStatus.error
        device.last_error = _describe_failure(e)
        logger.warning("设备 %s(%s) 启动失败：%s", device.id, device.name, device.last_error)
        await db.commit()
        await broadcast_device(device)
        raise
    device.status = DeviceStatus.running
    device.last_error = None
    if device.current_url:
        await backend.open_url(device, device.current_url)
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def stop_device(db: AsyncSession, device: Device) -> Device:
    try:
        await backend.stop(device)
    except Exception as e:  # noqa: BLE001
        device.status = DeviceStatus.error
        device.last_error = _describe_failure(e)
        logger.warning("设备 %s(%s) 停止失败：%s", device.id, device.name, device.last_error)
        await db.commit()
        await broadcast_device(device)
        raise
    device.status = DeviceStatus.stopped
    device.last_error = None
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def destroy_device(db: AsyncSession, device: Device) -> None:
    await backend.destroy(device)
    await db.delete(device)
    await db.commit()
    await manager.broadcast({"type": "device_removed", "device_id": device.id})


async def broadcast_device(device: Device) -> None:
    await manager.broadcast(
        {"type": "device_status", "device": DeviceOut.model_validate(device).model_dump()}
    )
