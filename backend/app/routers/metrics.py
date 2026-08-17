"""数据看板（监控大盘）：总览统计 + 轻量设备列表。

对齐前端「数据看板」页：
- GET /metrics/overview  -> 设备/分组/在线连接的聚合指标（含机型分布、分组分布）。
- GET /metrics/devices   -> 每台设备的精简监控行（含机型、出口 IP、当前页面）。

统计口径说明：机型 / 出口 IP 存放在 Device.fingerprint（JSON 列，一机一码），
无法直接在 SQL 层聚合，因此把设备行取回后在 Python 内一次遍历完成计数，
避免对每台设备各发一次查询。
"""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Device, DeviceStatus, Group, User
from ..ws_manager import manager

router = APIRouter(prefix="/metrics", tags=["metrics"], dependencies=[Depends(get_current_user)])


def _model_of(device: Device) -> str:
    """从指纹中取机型；缺失时归入「未知机型」。"""
    fp = device.fingerprint or {}
    model = (fp.get("device") or {}).get("model")
    return model or "未知机型"


def _exit_ip_of(device: Device) -> str | None:
    fp = device.fingerprint or {}
    return (fp.get("network") or {}).get("exit_ip")


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """看板总览：一次性返回 KPI + 状态分布 + 机型/分组分布 + 最近设备。"""
    all_devices = list((await db.execute(select(Device).order_by(Device.id))).scalars().all())
    devices = all_devices if user.role in ("admin", "superadmin") else [d for d in all_devices if d.created_by == user.id]
    groups = list((await db.execute(select(Group).order_by(Group.id))).scalars().all())

    # 单次遍历完成状态计数 / 机型分布 / 分组计数 / 出口 IP 去重
    status_counter: Counter[str] = Counter()
    model_counter: Counter[str] = Counter()
    group_counter: Counter[int | None] = Counter()
    exit_ips: set[str] = set()
    for d in devices:
        status_counter[d.status.value] += 1
        model_counter[_model_of(d)] += 1
        group_counter[d.group_id] += 1
        ip = _exit_ip_of(d)
        if ip:
            exit_ips.add(ip)

    # 分组分布：所有分组（含 0 台）+ 未分组兜底
    by_group = [
        {"group_id": g.id, "name": g.name, "count": group_counter.get(g.id, 0)}
        for g in groups
    ]
    ungrouped = group_counter.get(None, 0)
    if ungrouped:
        by_group.append({"group_id": None, "name": "未分组", "count": ungrouped})

    # 机型分布：按数量降序
    model_distribution = [
        {"model": m, "count": c}
        for m, c in sorted(model_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # 最近创建的设备（最多 8 台）
    recent = sorted(devices, key=lambda d: d.created_at, reverse=True)[:8]
    recent_devices = [
        {"id": d.id, "name": d.name, "status": d.status.value, "created_at": d.created_at}
        for d in recent
    ]

    return {
        "total_devices": len(devices),
        "running": status_counter.get(DeviceStatus.running.value, 0),
        "stopped": status_counter.get(DeviceStatus.stopped.value, 0),
        "error": status_counter.get(DeviceStatus.error.value, 0),
        "creating": status_counter.get(DeviceStatus.creating.value, 0),
        "total_groups": len({d.group_id for d in devices if d.group_id}),
        "ws_clients": manager.count,
        "unique_exit_ips": len(exit_ips),
        "by_group": by_group,
        "model_distribution": model_distribution,
        "recent_devices": recent_devices,
    }


@router.get("/devices")
async def device_rows(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    """每台设备的精简监控行。"""
    all_devices = list((await db.execute(select(Device).order_by(Device.id))).scalars().all())
    devices = all_devices if user.role in ("admin", "superadmin") else [d for d in all_devices if d.created_by == user.id]
    return [
        {
            "id": d.id,
            "name": d.name,
            "status": d.status.value,
            "group_id": d.group_id,
            "model": _model_of(d),
            "exit_ip": _exit_ip_of(d),
            "current_url": d.current_url,
            "created_at": d.created_at,
        }
        for d in devices
    ]
