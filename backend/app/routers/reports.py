"""统计报表（PC-204 / §8.3.3 统计报表 + 导出）。

在「数据看板」的实时指标之外，提供一份面向导出/复盘的聚合报表：
- GET /reports/summary     -> 设备按状态 / 机型 / 分组的分布 + 分组/脚本/任务数量 + 脚本运行成败统计。
- GET /reports/devices.csv -> 全部设备明细 CSV（stdlib csv），带 UTF-8 BOM 便于 Excel 正确显示中文。

统计口径与 metrics.py 一致：机型 / 出口 IP 存放在 Device.fingerprint（JSON 列，一机一码），
无法在 SQL 层聚合，因此把设备行一次取回后在 Python 内单次遍历完成计数，避免逐台查询。
"""
from __future__ import annotations

import csv
import io
from collections import Counter

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Device, DeviceStatus, Group, Script, ScriptRun

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user)])

# 定时任务模型单独成模块（scheduler_models），import 失败时任务数记为 0，保证报表可用。
try:  # pragma: no cover - 取决于是否启用任务调度
    from ..scheduler_models import ScheduledTask
except Exception:  # noqa: BLE001
    ScheduledTask = None  # type: ignore[assignment]


def _model_of(device: Device) -> str:
    """从指纹中取机型；缺失时归入「未知机型」。"""
    fp = device.fingerprint or {}
    model = (fp.get("device") or {}).get("model")
    return model or "未知机型"


def _exit_ip_of(device: Device) -> str | None:
    fp = device.fingerprint or {}
    return (fp.get("network") or {}).get("exit_ip")


# CSV 列定义：表头（中文，供 Excel 阅读）与取值函数一一对应。
_CSV_COLUMNS: list[tuple[str, str]] = [
    ("id", "ID"),
    ("name", "名称"),
    ("status", "状态"),
    ("model", "机型"),
    ("exit_ip", "出口IP"),
    ("group_id", "分组ID"),
    ("current_url", "当前页面"),
    ("created_at", "创建时间"),
]

# 状态英文枚举 -> 中文（与前端一致）
_STATUS_CN = {
    "running": "运行中",
    "stopped": "已停止",
    "creating": "创建中",
    "error": "异常",
}


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)) -> dict:
    """统计报表总览：一次性返回分布 + 各类数量 + 脚本运行成败统计。"""
    devices = list((await db.execute(select(Device).order_by(Device.id))).scalars().all())
    groups = list((await db.execute(select(Group).order_by(Group.id))).scalars().all())

    # 数量类：分组 / 脚本 / 任务（用 count(*) 避免整表取回）
    script_count = (await db.execute(select(func.count(Script.id)))).scalar_one()
    task_count = 0
    if ScheduledTask is not None:
        task_count = (await db.execute(select(func.count(ScheduledTask.id)))).scalar_one()

    # 脚本运行成败统计：按 status 分组计数（running / success / failed）
    run_rows = (
        await db.execute(select(ScriptRun.status, func.count(ScriptRun.id)).group_by(ScriptRun.status))
    ).all()
    run_counter = {status: count for status, count in run_rows}
    script_runs = {
        "total": sum(run_counter.values()),
        "success": run_counter.get("success", 0),
        "failed": run_counter.get("failed", 0),
        "running": run_counter.get("running", 0),
    }

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

    # 状态分布（固定四态顺序，便于前端稳定渲染）
    by_status = [
        {"status": s.value, "label": _STATUS_CN.get(s.value, s.value), "count": status_counter.get(s.value, 0)}
        for s in DeviceStatus
    ]

    # 机型分布：按数量降序
    by_model = [
        {"model": m, "count": c}
        for m, c in sorted(model_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # 分组分布：所有分组（含 0 台）+ 未分组兜底
    by_group = [
        {"group_id": g.id, "name": g.name, "count": group_counter.get(g.id, 0)}
        for g in groups
    ]
    ungrouped = group_counter.get(None, 0)
    if ungrouped:
        by_group.append({"group_id": None, "name": "未分组", "count": ungrouped})

    return {
        "total_devices": len(devices),
        "total_groups": len(groups),
        "total_scripts": script_count,
        "total_tasks": task_count,
        "unique_exit_ips": len(exit_ips),
        "by_status": by_status,
        "by_model": by_model,
        "by_group": by_group,
        "script_runs": script_runs,
    }


@router.get("/devices.csv")
async def devices_csv(db: AsyncSession = Depends(get_db)) -> Response:
    """导出全部设备明细为 CSV。带 UTF-8 BOM，避免 Excel 打开中文乱码。"""
    devices = list((await db.execute(select(Device).order_by(Device.id))).scalars().all())

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([header for _, header in _CSV_COLUMNS])
    for d in devices:
        writer.writerow([
            d.id,
            d.name,
            _STATUS_CN.get(d.status.value, d.status.value),
            _model_of(d),
            _exit_ip_of(d) or "",
            d.group_id if d.group_id is not None else "",
            d.current_url or "",
            d.created_at.isoformat() if d.created_at else "",
        ])

    # ﻿ = UTF-8 BOM：让 Excel 以 UTF-8 解析，中文不乱码
    content = "﻿" + buf.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=devices.csv"},
    )
