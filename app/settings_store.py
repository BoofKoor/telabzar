"""فروشگاهِ تنظیماتِ زمانِ‌اجرا (admin-lite).

منبعِ زنده = **Redis** (همهٔ پروسه‌ها — bot و download-worker و … — ازش می‌خوانند،
پس تغییرِ ادمین فوراً و به‌شکلِ بین‌پروسه‌ای دیده می‌شود). منبعِ ماندگار = **Postgres**.
`env` (config.Settings) پیش‌فرض است؛ کلیدِ ذخیره‌شده آن را override می‌کند.

چون read-through از Redis است (نه کشِ in-process با TTL)، مشکلِ «کهنه‌ماندنِ یک
پروسه تا انقضای TTL» پیش نمی‌آید: نوشتنِ ادمین بلافاصله در Redis می‌نشیند و هر
خواننده در خواندنِ بعدی آن را می‌بیند.
"""
from __future__ import annotations

import redis.asyncio as aioredis
from sqlalchemy import select

from .config import settings
from .db import Sessionmaker
from .models import Setting

_PREFIX = "cfg:"
_MISSING = "\x00"  # نشانهٔ negative-cache: «در DB نیست → از پیش‌فرضِ env استفاده کن»

# کلیدهای قابلِ‌تنظیم از پنل → (نوع, پیش‌فرضِ env). مرجعِ /admin و اعتبارسنجی.
# همگام با docs/ADMIN_PANEL.md.
RUNTIME_KEYS: dict[str, tuple[str, object]] = {
    "rate_per_min": ("int", settings.rate_per_min),
    "daily_op_quota": ("int", settings.daily_op_quota),
    "whisper_model": ("str", settings.whisper_model),
    "max_file_mb": ("int", settings.max_file_mb),
    # ── دانلودر ──
    "downloader_enabled": ("bool", settings.downloader_enabled),
    "proxy_url": ("str", settings.proxy_url),
    "dl_default_ux": ("str", settings.dl_default_ux),
    "dl_ux_youtube": ("str", ""),      # خالی = ارث از dl_default_ux
    "dl_ux_instagram": ("str", ""),
    "dl_ux_twitter": ("str", ""),
    "dl_ux_tiktok": ("str", ""),
    "dl_max_size_mb": ("int", settings.dl_max_size_mb),
    "dl_max_duration_min": ("int", settings.dl_max_duration_min),
    "dl_daily_count": ("int", settings.dl_daily_count),
    "dl_daily_mb": ("int", settings.dl_daily_mb),
    "dl_concurrency": ("int", settings.dl_concurrency),
    "dl_cooldown_sec": ("int", settings.dl_cooldown_sec),
    "dl_op_daily_min": ("int", settings.dl_op_daily_min),
    "dl_min_free_gb": ("int", settings.dl_min_free_gb),
}

# کلیدهایی با مقادیرِ مجازِ محدود (اعتبارسنجیِ /admin).
ENUM_VALUES: dict[str, tuple[str, ...]] = {
    "whisper_model": ("tiny", "base", "small", "medium", "large-v3"),
    "dl_default_ux": ("probe", "quick"),
    "dl_ux_youtube": ("probe", "quick", ""),
    "dl_ux_instagram": ("probe", "quick", ""),
    "dl_ux_twitter": ("probe", "quick", ""),
    "dl_ux_tiktok": ("probe", "quick", ""),
}


class SettingsStore:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self.r = redis_client

    async def get(self, key: str) -> str | None:
        """override را برمی‌گرداند؛ None = تنظیم نشده (از پیش‌فرضِ env استفاده کن)."""
        try:
            cached = await self.r.get(_PREFIX + key)
        except Exception:  # noqa: BLE001  — Redis پایین؛ برگرد به DB
            cached = None
        if cached is not None:
            return None if cached == _MISSING else cached
        async with Sessionmaker() as s:
            row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        val = row.value if row is not None else None
        try:
            await self.r.set(_PREFIX + key, _MISSING if val is None else val)
        except Exception:  # noqa: BLE001  — کشِ Redis اختیاری است
            pass
        return val

    async def set(self, key: str, value: str) -> None:
        async with Sessionmaker() as s:
            row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
            if row is None:
                s.add(Setting(key=key, value=value))
            else:
                row.value = value
            await s.commit()
        try:
            await self.r.set(_PREFIX + key, value)  # همهٔ پروسه‌ها فوراً می‌بینند
        except Exception:  # noqa: BLE001
            pass

    async def reset(self, key: str) -> None:
        async with Sessionmaker() as s:
            row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
        try:
            await self.r.set(_PREFIX + key, _MISSING)
        except Exception:  # noqa: BLE001
            pass

    async def all_overrides(self) -> dict[str, str]:
        async with Sessionmaker() as s:
            rows = (await s.execute(select(Setting))).scalars().all()
        return {r.key: r.value for r in rows}

    async def get_int(self, key: str, default: int) -> int:
        v = await self.get(key)
        if v is None:
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    async def get_str(self, key: str, default: str) -> str:
        v = await self.get(key)
        return default if v is None else v

    async def get_bool(self, key: str, default: bool) -> bool:
        v = await self.get(key)
        if v is None:
            return default
        return v.strip().lower() in ("1", "true", "yes", "on")


# ── singletonِ سطحِ پروسه (bot/worker یک‌بار init می‌کنند) ───────
_store: SettingsStore | None = None


def init_store(redis_url: str) -> SettingsStore:
    global _store
    if _store is None:
        _store = SettingsStore(aioredis.from_url(redis_url, decode_responses=True))
    return _store


def set_store(store: SettingsStore | None) -> None:
    """تزریقِ مستقیم (برای تست)."""
    global _store
    _store = store


def get_store() -> SettingsStore | None:
    return _store


# توابعِ راحتِ سطحِ‌ماژول: اگر store مقداردهی نشده، به پیش‌فرضِ env برمی‌گردند.
async def get_int(key: str, default: int) -> int:
    return await _store.get_int(key, default) if _store is not None else default


async def get_str(key: str, default: str) -> str:
    return await _store.get_str(key, default) if _store is not None else default


async def get_bool(key: str, default: bool) -> bool:
    return await _store.get_bool(key, default) if _store is not None else default
