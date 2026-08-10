"""شمارشِ دانلودهای هم‌زمان — **خودترمیم**.

تا دیروز یک `INCR dl:active` بود با `DECR` در `finally`. مشکل: `finally` روی
OOM/kill/ری‌استارتِ کانتینر اجرا **نمی‌شود** و آن کلید هیچ TTLی نداشت، پس شمارنده
تا ابد بالا می‌ماند و به‌محضِ عبور از `dl_concurrency` **هر** دانلودی «شلوغ است»
می‌گرفت. هیچ‌چیز هم خودش را درست نمی‌کرد؛ فقط پاک‌کردنِ دستیِ کلید.

طرحِ فعلی: sorted-set با مهرِ زمانِ **سرورِ Redis** (نه ساعتِ محلی — مستر و نودِ
دانلود دو ماشین‌اند و اختلافِ ساعت نباید ظرفیت را جابه‌جا کند). هر جابِ زنده یک
عضو دارد، یک تسکِ keepalive امتیازش را تازه نگه می‌دارد، و هر شمارش اول ورودی‌های
کهنه را هرس می‌کند — پس جابی که با kill مرد دیگر تازه نمی‌شود و پس از
`ACTIVE_TTL` خودبه‌خود ناپدید می‌شود.

این ماژول عمداً **هیچ وابستگیِ سنگینی** ندارد (نه Pillow، نه aiogram): هم ورکرِ
دانلود از آن می‌خوانَد هم پروسهٔ پنل، و ایمیجِ پنل استکِ پردازش را نصب ندارد.
"""
from __future__ import annotations

import asyncio
import time

ACTIVE_KEY = "dl:active:z"
ACTIVE_TTL = 90.0          # ثانیه — ورودیِ تازه‌نشده بعد از این «مرده» حساب می‌شود
ACTIVE_BEAT = 30.0         # ثانیه — فاصلهٔ تازه‌سازی (باید خیلی کمتر از TTL باشد)


async def redis_now(redis) -> float:
    """ثانیهٔ ساعتِ **سرورِ Redis** — تا اختلافِ ساعتِ مستر/نود بی‌اثر شود."""
    try:
        sec, usec = await redis.time()
        return float(sec) + float(usec) / 1_000_000
    except Exception:  # noqa: BLE001 — Redisِ عجیب/ماک: ساعتِ محلی هم بهتر از هیچ است
        return time.time()


async def _prune(redis, now: float) -> None:
    await redis.zremrangebyscore(ACTIVE_KEY, "-inf", now - ACTIVE_TTL)


async def enter(redis, member: str) -> int:
    """این جاب را ثبت کن و تعدادِ دانلودهای زنده را بده (پس از هرسِ مرده‌ها)."""
    now = await redis_now(redis)
    await _prune(redis, now)
    await redis.zadd(ACTIVE_KEY, {member: now})
    return int(await redis.zcard(ACTIVE_KEY))


async def leave(redis, member: str) -> None:
    try:
        await redis.zrem(ACTIVE_KEY, member)
    except Exception:  # noqa: BLE001
        pass


async def keepalive(redis, member: str) -> None:
    """تا وقتی جاب زنده است امتیازش را تازه نگه دار — شاملِ فازِ آپلود، نه فقط دانلود.
    فراخوان باید این تسک را در `finally` کنسل کند."""
    while True:
        await asyncio.sleep(ACTIVE_BEAT)
        try:
            await redis.zadd(ACTIVE_KEY, {member: await redis_now(redis)})
        except Exception:  # noqa: BLE001
            pass


async def count(redis) -> int:
    """تعدادِ دانلودهای واقعاً زنده — مصرف‌کننده: صفحهٔ سلامتِ پنل."""
    try:
        await _prune(redis, await redis_now(redis))
        return int(await redis.zcard(ACTIVE_KEY))
    except Exception:  # noqa: BLE001
        return 0
