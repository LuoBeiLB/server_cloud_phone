"""异步 SQLAlchemy 引擎与会话。"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    # demo 阶段直接建表；生产用 Alembic 迁移。
    from sqlalchemy import text

    from . import models  # noqa: F401  确保模型已注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 轻量幂等迁移：为已存在的老库补新列（create_all 不会 ALTER 已有表）。
    # 每条 DDL 必须独立事务：Postgres 下任何语句报错都会作废整个事务，
    # 而 COMMIT 会被静默降级为 ROLLBACK（不抛异常）。若与上面的 create_all 同事务，
    # 全新库上这条 ALTER 必因“列已存在”失败（models.py 已定义 skin），
    # 连带把刚建好的表一起回滚掉，随后 seed() 会报 relation "users" does not exist。
    for ddl in (
        "ALTER TABLE devices ADD COLUMN skin VARCHAR(32) DEFAULT 'ios'",
        "ALTER TABLE devices ADD COLUMN last_error VARCHAR(2000)",
    ):
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
        except Exception:
            pass  # 列已存在 / 不支持——忽略
