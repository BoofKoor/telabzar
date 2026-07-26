"""رگرسیونِ شمارندهٔ دانلودِ هم‌زمان (`app.dl_active`).

باگ: `INCR dl:active` با `DECR` در `finally`. `finally` روی OOM/kill/ری‌استارتِ
کانتینر اجرا نمی‌شود و کلید TTL نداشت، پس شمارنده تا ابد بالا می‌ماند و به‌محضِ
عبور از `dl_concurrency` (پیش‌فرض ۳) **هر** دانلودی «شلوغ است» می‌گرفت.

تست‌ها روی fakeredis (رفتارِ واقعیِ ZSET/TIME) اجرا می‌شوند. برای «گذشتِ زمان»
ساعتِ `redis_now` جابه‌جا می‌شود — sleepِ ۹۰ ثانیه‌ای در تست معنا ندارد.
"""
from __future__ import annotations

import asyncio

import pytest

from app import dl_active


@pytest.fixture
def clock(monkeypatch):
    """ساعتِ قابلِ‌کنترل به‌جای `TIME`ِ سرورِ Redis."""
    state = {"t": 1_000_000.0}

    async def _now(_redis):
        return state["t"]

    monkeypatch.setattr(dl_active, "redis_now", _now)
    return state


async def test_counts_live_jobs(redis, clock):
    assert await dl_active.enter(redis, "a") == 1
    assert await dl_active.enter(redis, "b") == 2
    assert await dl_active.enter(redis, "c") == 3
    await dl_active.leave(redis, "b")
    assert await dl_active.count(redis) == 2


async def test_crashed_job_frees_capacity_by_itself(redis, clock):
    """جابی که با kill مرد `leave` نمی‌زند — ولی چون تازه هم نمی‌شود، خودش می‌رود.

    این همان چیزی است که طرحِ قبلی نمی‌توانست: `DECR`ی که اجرا نشد هیچ‌وقت جبران
    نمی‌شد و ظرفیت برای همیشه اشغال می‌ماند.
    """
    for i in range(3):
        await dl_active.enter(redis, f"dead-{i}")     # هیچ‌کدام leave نمی‌زنند
    assert await dl_active.count(redis) == 3

    clock["t"] += dl_active.ACTIVE_TTL + 1
    assert await dl_active.count(redis) == 0, "ورودیِ یتیم باید خودبه‌خود هرس شود"
    assert await dl_active.enter(redis, "fresh") == 1


async def test_old_incr_scheme_could_not_heal(redis):
    """چرایِ تغییرِ طرح، به‌صورتِ اجرایی: `INCR` بدونِ `DECR` تا ابد بالا می‌ماند."""
    for _ in range(3):
        await redis.incr("dl:active")                # سه جابی که با kill مردند
    assert int(await redis.get("dl:active")) == 3
    assert await redis.ttl("dl:active") == -1        # هیچ انقضایی ندارد
    assert int(await redis.incr("dl:active")) == 4   # جابِ بعدی همیشه «شلوغ است»


async def test_keepalive_holds_a_long_job(redis, clock, monkeypatch):
    """جابِ طولانی‌تر از TTL نباید هرس شود — تسکِ keepalive امتیازش را تازه می‌کند."""
    monkeypatch.setattr(dl_active, "ACTIVE_BEAT", 0.01)
    await dl_active.enter(redis, "long")
    beat = asyncio.create_task(dl_active.keepalive(redis, "long"))
    try:
        for _ in range(4):
            clock["t"] += dl_active.ACTIVE_TTL / 2
            await asyncio.sleep(0.05)               # اجازهٔ چند تپش
            assert await dl_active.count(redis) == 1
    finally:
        beat.cancel()
        with pytest.raises(asyncio.CancelledError):
            await beat


async def test_keepalive_stops_after_cancel(redis, clock, monkeypatch):
    """و بعد از کنسل‌شدنِ keepalive (در `finally`) دیگر تازه نمی‌شود."""
    monkeypatch.setattr(dl_active, "ACTIVE_BEAT", 0.01)
    await dl_active.enter(redis, "job")
    beat = asyncio.create_task(dl_active.keepalive(redis, "job"))
    await asyncio.sleep(0.05)
    beat.cancel()
    with pytest.raises(asyncio.CancelledError):
        await beat
    clock["t"] += dl_active.ACTIVE_TTL + 1
    await asyncio.sleep(0.05)
    assert await dl_active.count(redis) == 0


async def test_two_jobs_sharing_one_ref_are_counted_separately(redis, clock):
    """`ref` کلیدِ یکتای جاب **نیست**: بینِ فازِ probe و fetch مشترک است و
    `on_dl_pick` می‌تواند از یک منو چند کیفیت را پشتِ‌هم بفرستد. اگر عضوِ ZSET
    خودِ ref بود، جابِ دوم اولی را بازنویسی می‌کرد و `leave`ِ هرکدام سهمِ آن یکی
    را هم آزاد می‌کرد."""
    ref = "abc123"
    m1, m2 = f"{ref}:one", f"{ref}:two"
    assert await dl_active.enter(redis, m1) == 1
    assert await dl_active.enter(redis, m2) == 2, "دو جاب با یک ref باید دو تا شمرده شوند"
    await dl_active.leave(redis, m1)
    assert await dl_active.count(redis) == 1, "پایانِ جابِ اول نباید جابِ دوم را حذف کند"


async def test_count_is_safe_when_redis_is_broken():
    """صفحهٔ سلامت نباید روی خرابیِ Redis خطا بدهد."""
    class _Broken:
        async def time(self):
            raise RuntimeError("down")

        async def zremrangebyscore(self, *a):
            raise RuntimeError("down")

        async def zcard(self, *a):
            raise RuntimeError("down")

    assert await dl_active.count(_Broken()) == 0
