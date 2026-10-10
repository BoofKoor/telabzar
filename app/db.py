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
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS dl_token_at TIMESTAMPTZ",
    # لینک‌های پیش از فاز ۴ مهرِ زمان ندارند؛ به‌جای «همه همین حالا منقضی» یک پنجرهٔ
    # تازه از لحظهٔ استقرار می‌گیرند. idempotent: `op_link` همیشه مهر می‌زند، پس
    # بعد از اجرای اول هیچ ردیفِ توکن‌داری NULL نمی‌ماند و اجراهای بعدی صفر ردیف‌اند.
    "UPDATE files SET dl_token_at = now() WHERE dl_token IS NOT NULL AND dl_token_at IS NULL",
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
    # کدِ زبان از `VARCHAR(2)` به `VARCHAR(16)` — تا `pt-BR` و `zh-Hant-TW`
    # بدونِ مهاجرتِ بعدی جا شوند. **این تنها ALTERِ نوعِ این فهرست است**، پس
    # هزینه‌اش جدا سنجیده شد روی PostgreSQL 16.13:
    #
    #   عرض‌دادنِ varchar روی ۲۰۰٬۴۲۸ ردیف / ۵۸ مگابایت  →  ۲٫۹ میلی‌ثانیه،
    #   و `pg_relation_filenode` هم برای جدول و هم برای ایندکسِ PK **عوض نشد**.
    #
    # یعنی catalog-only است و هزینه‌اش **مستقل از تعدادِ ردیف**. کنترلِ منفی
    # همان اندازه‌گیری: باریک‌کردنِ همان ستون (`(32)→(2)`) روی همان جدول
    # ۲۰۵۱ میلی‌ثانیه گرفت و filenodeِ هر دو را عوض کرد — پس هارنس بازنویسی را
    # می‌بیند و این یکی واقعاً بازنویسی نمی‌کند.
    #
    # اجرای دوباره هم امن است (۲٫۴ میلی‌ثانیه، بدونِ بازنویسی)، که مهم است چون
    # `init_models()` سرِ **هر** استارتِ ربات/ورکر می‌دود. قفلِ
    # ACCESS EXCLUSIVE می‌گیرد، ولی هم‌ردهٔ همان ۲۰ `ADD COLUMN`ِ بالاست، نه
    # ردهٔ تازه‌ای از هزینه.
    "ALTER TABLE users ALTER COLUMN lang TYPE VARCHAR(16)",
    "ALTER TABLE text_overrides ALTER COLUMN lang TYPE VARCHAR(16)",
    # یوزرنیم و نامِ تلگرامی برای پنل. هر دو nullable و بی‌پیش‌فرض‌اند، پس روی
    # Postgres 11+ catalog-only‌اند (بدونِ بازنویسیِ جدول) — هم‌ردهٔ ADD COLUMNهای بالا.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(64)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(128)",
    # تاریخچهٔ کاربر (۲۰۲۶-۱۰-۱۰). همه nullable و بی‌پیش‌فرض، پس catalog-only —
    # هم‌ردهٔ ADD COLUMNهای بالا. جدولِ `file_versions` تازه است و `create_all` می‌سازدش.
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS hidden_at TIMESTAMPTZ",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS starred_at TIMESTAMPTZ",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS group_ref VARCHAR(12)",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS source_url VARCHAR(1024)",
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS last_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS ix_files_group_ref ON files (group_ref)",
    # فهرستِ تاریخچه «فایل‌های همین کاربر، تازه‌ترین اول» است؛ ایندکسِ تک‌ستونیِ
    # `owner_id` مرتب‌سازی را نمی‌دهد. `create_all` ایندکسِ جدولِ **موجود** را نمی‌سازد.
    "CREATE INDEX IF NOT EXISTS ix_files_owner_created ON files (owner_id, created_at)",
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
