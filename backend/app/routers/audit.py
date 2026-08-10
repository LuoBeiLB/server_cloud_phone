"""操作审计日志查询（RBAC：管理员及以上可查看）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit_models import AuditLog
from ..database import get_db
from ..rbac import require_role

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(require_role("admin"))],
)


@router.get("")
async def list_audit(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(200))
    ).scalars().all()
    return [
        {
            "id": r.id,
            "username": r.username,
            "action": r.action,
            "target": r.target,
            "detail": r.detail,
            "ts": r.ts,
        }
        for r in rows
    ]
