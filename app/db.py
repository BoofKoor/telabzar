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
#
# **این فهرست نحوِ Postgres است، نه SQL قابلِ‌حمل.** `ALTER TABLE … ADD COLUMN
# IF NOT EXISTS` را SQLite با خطای نحوی رد می‌کند (`near "EXISTS"`)؛ فقط
# `CREATE INDEX IF NOT EXISTS` روی هر دو کار می‌کند. امروز **باگِ فعال نیست**،
# چون `init_models()` تنها از `__main__.py` و `worker.py` صدا زده می‌شود و آن‌ها
# همیشه به Postgres وصل‌اند (تست‌ها SQLite را مستقیم می‌سازند و از این مسیر
# رد نمی‌شوند). عمداً قابلِ‌حمل نشده — استقرارِ SQLiteای نه هست نه برنامه‌ریزی
# شده. اگر روزی شد، این‌جا باید dialect-aware شود، نه این‌که یک `IF NOT EXISTS`
# دیگر اضافه شود. (فاز ۳الف، موردِ ۹)
_MIGRATIONS = [
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS changelog JSON DEFAULT '[]'",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS meta JSON",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS width INTEGER",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS height INTEGER",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS duration INTEGER",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS dl_token VARCHAR(32)",
    "CREATE INDEX IF NOT EXISTS ix_files_dl_token ON files (dl_token)",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS cover_id VARCHAR(256)",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS source VARCHAR(16)",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS post_caption TEXT",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS platform VARCHAR(24)",
    "ALTER TABLE download_cache ADD COLUMN IF NOT EXISTS post_caption TEXT",
    "ALTER TABLE download_cache ADD COLUMN IF NOT EXISTS platform VARCHAR(24)",
    "ALTER TABLE download_cache ADD COLUMN IF NOT EXISTS hits INTEGER DEFAULT 0",
    "ALTER TABLE download_cache ADD COLUMN IF NOT EXISTS items JSON",
    # ایندکس‌های آمار: بدونِ این‌ها GROUP BY روی بازهٔ ۳۰ روزه با رشدِ داده کند می‌شود
    "CREATE INDEX IF NOT EXISTS ix_files_created_at ON files (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_files_platform ON files (platform)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_created_at ON jobs (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs (status)",
    "CREATE INDEX IF NOT EXISTS ix_users_created_at ON users (created_at)",
    # صفحهٔ کاربران با `last_seen DESC` مرتب می‌شود و ایندکسی نداشت، پس هر بار
    # کلِ جدول مرتب می‌شد. اندازه‌گیری‌شده روی Postgres 16 با ۲۰۰هزار ردیف:
    # `Sort` → `Index Scan Backward`، و خودِ کوئریِ صفحه از ۳۷ به ۰٫۴۵ میلی‌ثانیه.
    # ساختش روی جدولِ امروزیِ تولید (۱۶۶۸ ردیف) **۲٫۳ تا ۳٫۴ میلی‌ثانیه** است.
    "CREATE INDEX IF NOT EXISTS ix_users_last_seen ON users (last_seen)",
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
