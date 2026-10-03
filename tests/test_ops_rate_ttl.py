"""فاز ۲ / موردِ ۱۶ — شمارندهٔ نرخِ ربات نباید جاودان شود.

`routers/ops._check_limits` فرمِ `if r == 1: expire(...)` را داشت. اگر پروسه
دقیقاً بینِ `INCR` و `EXPIRE` بمیرد، `rate:<uid>` بدونِ انقضا می‌ماند و چون هر
فراخوانِ بعدی فقط بالا می‌بردش، کاربر برای **همیشه** «زیادی سریع» خوانده
می‌شد — قفلی که خودش ترمیم نمی‌شود. پنل همین را پیش‌تر در `_rate_limit` رفع
کرده بود ولی ربات کپیِ دست‌نویسِ بی‌ترمیمِ خودش را داشت.

مرگِ بینِ دو فرمان را مستقیم می‌سازیم: کلید را با مقدار و **بدونِ TTL**
می‌کاریم، یعنی دقیقاً حالتی که آن مرگ جا می‌گذارد.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import counters
from app.config import settings
from app.routers import ops

UID = 7


@pytest.fixture(autouse=True)
def _limits(monkeypatch):
    # بدونِ settings_store، `get_int` پیش‌فرضِ env را برمی‌گرداند.
    monkeypatch.setattr(settings, "rate_per_min", 3)
    monkeypatch.setattr(settings, "daily_op_quota", 100)
    monkeypatch.setattr(settings, "dl_op_daily_min", 50)


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


async def test_a_rate_counter_that_lost_its_ttl_is_repaired(redis):
    key = f"rate:{UID}"
    await redis.set(key, 9)                     # مرگ بینِ INCR و EXPIRE
    assert await redis.ttl(key) == -1           # پیش‌شرط: واقعاً جاودان است
    assert await ops._check_limits(redis, UID) == "rate"
    ttl = await redis.ttl(key)
    assert 0 < ttl <= 60, f"TTL ترمیم نشد: {ttl}"


async def test_a_daily_quota_counter_that_lost_its_ttl_is_repaired(redis, monkeypatch):
    monkeypatch.setattr(settings, "rate_per_min", 0)        # فقط مسیرِ سهمیه
    key = f"quota:{UID}:{_day()}"
    await redis.set(key, 4)
    assert await ops._check_limits(redis, UID) is None
    assert 0 < await redis.ttl(key) <= 90000


async def test_a_dl_op_budget_counter_that_lost_its_ttl_is_repaired(redis):
    key = f"dlop:{UID}:{_day()}"
    await redis.set(key, 3)
    f = SimpleNamespace(source="dl", duration=120)
    assert await ops._check_dl_op_budget(redis, UID, f, "compress") is False
    assert int(await redis.get(key)) == 5       # ۳ + ۲ دقیقه
    assert 0 < await redis.ttl(key) <= 90000


async def test_the_normal_window_still_limits(redis):
    """کنترل: مسیرِ عادی همان سقف را می‌دهد و همان TTLِ ۶۰ ثانیه را."""
    got = [await ops._check_limits(redis, UID) for _ in range(4)]
    assert got == [None, None, None, "rate"]
    assert 0 < await redis.ttl(f"rate:{UID}") <= 60


async def test_the_budget_refund_still_works(redis):
    """کنترل: ردِ سقفِ دقیقه‌پردازش همچنان بازپرداخت می‌شود."""
    f = SimpleNamespace(source="dl", duration=60 * 60)      # ۶۰ دقیقه > سقفِ ۵۰
    assert await ops._check_dl_op_budget(redis, UID, f, "compress") is True
    assert int(await redis.get(f"dlop:{UID}:{_day()}")) == 0


async def test_incr_window_repairs_and_returns_the_new_value(redis):
    await redis.set("k", 2)
    assert await counters.incr_window(redis, "k", 30, 5) == 7
    assert 0 < await redis.ttl("k") <= 30


async def test_incr_window_does_not_extend_a_live_window(redis):
    """کنترل: روی کلیدی که TTL دارد، انقضا جلو نمی‌رود (پنجرهٔ ثابت می‌ماند)."""
    await counters.incr_window(redis, "k", 30)
    await redis.expire("k", 5)
    await counters.incr_window(redis, "k", 30)
    assert await redis.ttl("k") <= 5


def test_no_hand_written_incr_then_expire_left_in_ops():
    """گارد: کپیِ تازهٔ «INCR و بعد EXPIRE فقط روی اولی» در ops جا نیفتد."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(ops))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("incr", "incrby"):
            bad.append(node.lineno)
    assert not bad, f"INCRِ دست‌نویس در ops (از counters.incr_window استفاده کن): {bad}"
