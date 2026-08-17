"""RBAC 权限体系：四级角色分级依赖 + 操作审计写入。

角色分级（低 → 高）：查看员 viewer < 操作员 operator < 管理员 admin < 超级管理员 superadmin。
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .audit_models import AuditLog
from .auth import get_current_user
from .models import Device, User

# 角色等级：数值越大权限越高
ROLE_LEVELS: dict[str, int] = {
    "viewer": 1,
    "operator": 2,
    "admin": 3,
    "superadmin": 4,
}

# 角色中文名（供前端/审计展示）
ROLE_LABELS: dict[str, str] = {
    "superadmin": "超级管理员",
    "admin": "管理员",
    "operator": "操作员",
    "viewer": "查看员",
}


def require_role(min_role: str):
    """依赖工厂：返回一个校验“当前用户角色 >= min_role”的依赖。

    用法：`Depends(require_role("admin"))`，权限不足抛 403。
    """
    min_level = ROLE_LEVELS[min_role]

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if ROLE_LEVELS.get(user.role, 0) < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要「{ROLE_LABELS.get(min_role, min_role)}」及以上权限",
            )
        return user

    return _dependency


async def record_audit(
    db: AsyncSession,
    username: str,
    action: str,
    target: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """写入一条操作审计日志并提交。"""
    db.add(AuditLog(username=username, action=action, target=target, detail=detail))
    await db.commit()


def _check_device_access(user: User, device: Device) -> None:
    """检查用户是否有权访问/操作该设备。admin/superadmin 可看全部，其他只能看自己创建的设备。"""
    if user.role in ("admin", "superadmin"):
        return
    if device.created_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问该设备")
