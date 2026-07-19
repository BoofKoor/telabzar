"""موتور و نشستِ async دیتابیس."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
Sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    """ساختِ جدول‌ها (M1؛ بعداً با Alembic)."""
    from . import models  # noqa: F401  اطمینان از ثبتِ مدل‌ها

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
