"""用户管理（RBAC：管理员及以上可管理用户与角色）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth
from ..database import get_db
from ..models import User
from ..rbac import ROLE_LEVELS, record_audit, require_role

# 路由整体要求“管理员”及以上
router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_role("admin"))],
)

VALID_ROLES = set(ROLE_LEVELS)  # {"viewer", "operator", "admin", "superadmin"}


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class UserPatch(BaseModel):
    role: str | None = None
    password: str | None = None


def _to_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "created_at": u.created_at,
    }


async def _count_superadmin(db: AsyncSession) -> int:
    return (
        await db.execute(
            select(func.count(User.id)).where(User.role == "superadmin")
        )
    ).scalar_one()


@router.get("")
async def list_users(db: AsyncSession = Depends(get_db)) -> list[dict]:
    users = (await db.execute(select(User).order_by(User.id))).scalars().all()
    return [_to_out(u) for u in users]


@router.post("")
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(auth.get_current_user),
) -> dict:
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "用户名不能为空")
    if body.role not in VALID_ROLES:
        raise HTTPException(400, "非法角色")
    if not body.password:
        raise HTTPException(400, "密码不能为空")
    exists = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(400, "用户名已存在")

    user = User(
        username=username,
        password_hash=auth.hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await record_audit(db, actor.username, "创建用户", user.username, {"role": user.role})
    return _to_out(user)


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    body: UserPatch,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(auth.get_current_user),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")

    changes: dict = {}
    if body.role is not None and body.role != user.role:
        if body.role not in VALID_ROLES:
            raise HTTPException(400, "非法角色")
        # 保护：不能把最后一个超级管理员降级
        if user.role == "superadmin" and await _count_superadmin(db) <= 1:
            raise HTTPException(400, "不能降级最后一个超级管理员")
        changes["role"] = {"from": user.role, "to": body.role}
        user.role = body.role
    if body.password:
        user.password_hash = auth.hash_password(body.password)
        changes["password"] = "已重置"

    if not changes:
        return _to_out(user)

    await db.commit()
    await db.refresh(user)
    await record_audit(db, actor.username, "修改用户", user.username, changes)
    return _to_out(user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(auth.get_current_user),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    # 保护：不能删除最后一个超级管理员
    if user.role == "superadmin" and await _count_superadmin(db) <= 1:
        raise HTTPException(400, "不能删除最后一个超级管理员")

    username = user.username
    role = user.role
    await db.delete(user)
    await db.commit()
    await record_audit(db, actor.username, "删除用户", username, {"role": role})
    return {"ok": True}
