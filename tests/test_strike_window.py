"""فاز ۴ / موردِ ۳۴ث — پنجرهٔ «تخلف‌های ۳۰ روزِ اخیر» واقعاً ۳۰ روز باشد.

`note_block` با `INCR` و بعد `EXPIRE 30d` روی **هر** تخلف کار می‌کرد، پس هر تخلفِ
تازه عمرِ همهٔ قبلی‌ها را تمدید می‌کرد: کاربری که هر سه هفته یک مثبتِ کاذب
می‌خورد شمارنده‌اش هرگز پایین نمی‌آمد، و با `safety_strikes` روشن سرانجام خودکار
مسدود می‌شد. ساعت مدل‌شده است (`safety.time`)؛ ZSET و حذفِ بازه کارِ fakeredisِ واقعی.
"""
from __future__ import annotations

import pytest

from app import safety as S

DAY = 86400


class Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def time(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(S, "time", c, raising=False)
    return c


async def test_old_strikes_fall_out_of_the_window(redis, clock):
    pol = S.Policy()
    assert await S.note_block(redis, 42, pol) == 1
    clock.now += 20 * DAY
    assert await S.note_block(redis, 42, pol) == 2
    clock.now += 20 * DAY                       # اولی ۴۰ روز پیش بود
    assert await S.note_block(redis, 42, pol) == 2, "تخلفِ ۴۰ روز پیش هنوز شمرده می‌شود"


async def test_a_steady_trickle_never_reaches_the_auto_block(redis, clock):
    """هر ۲۰ روز یک تخلف، ده بار — هرگز بیش از دو تا در یک پنجره."""
    pol = S.Policy()
    seen = []
    for _ in range(10):
        seen.append(await S.note_block(redis, 7, pol))
        clock.now += 20 * DAY
    assert max(seen) <= 2, seen


async def test_a_burst_still_counts(redis, clock):
    """کنترل: پنجره نباید تخلف‌های واقعاً نزدیک را گم کند."""
    pol = S.Policy()
    counts = [await S.note_block(redis, 9, pol) for _ in range(4)]
    assert counts == [1, 2, 3, 4]


async def test_the_health_total_counts_only_the_window(redis, clock):
    pol = S.Policy()
    await S.note_block(redis, 1, pol)
    clock.now += 40 * DAY
    await S.note_block(redis, 2, pol)
    assert await S.blocked_total(redis) == 1
