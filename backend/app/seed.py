"""首次启动播种：管理员账号 + 默认分组。"""
from __future__ import annotations

from sqlalchemy import select

from .auth import hash_password
from .config import settings
from .database import SessionLocal
from .models import Group, User


async def seed() -> None:
    async with SessionLocal() as db:
        exists = (
            await db.execute(select(User).where(User.username == settings.admin_username))
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                User(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    role="superadmin",
                )
            )
        has_group = (await db.execute(select(Group.id))).first()
        if not has_group:
            db.add(Group(name="默认分组"))
        await db.commit()
