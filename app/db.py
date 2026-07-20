"""موتور و نشستِ async دیتابیس."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings

# مهاجرت‌های سبک (تا وقتی Alembic اضافه شود): افزودنِ ستون‌ها به جدولِ موجود.
_MIGRATIONS = [
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS changelog JSON DEFAULT '[]'",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS meta JSON",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS width INTEGER",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS height INTEGER",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS duration INTEGER",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS dl_token VARCHAR(32)",
    "CREATE INDEX IF NOT EXISTS ix_files_dl_token ON files (dl_token)",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS cover_id VARCHAR(256)",
]


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
Sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    """ساختِ جدول‌ها (M1؛ بعداً با Alembic)."""
    from . import models  # noqa: F401  اطمینان از ثبتِ مدل‌ها

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _MIGRATIONS:
            await conn.execute(text(stmt))
