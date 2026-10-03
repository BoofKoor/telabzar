"""فاز ۴ / موردِ ۲۹ — `max_file_mb = 0` یعنی بی‌سقف، نه «هیچ فایلی».

کفِ `BOUNDS` صفر است و صفر در کلِ پروژه معنیِ «خاموش/بی‌سقف» دارد (`vjoin_max_mb`،
`ck_cap_*`، `safety_strikes`، …)، ولی `_too_large` آن را `size > 0` می‌خواند: هر
عملیاتی روی هر فایلی رد می‌شد. مقدار از مسیرِ **واقعیِ** `settings_store` می‌آید
(کشِ Redis)، نه از وصلهٔ `_max_mb`.
"""
from __future__ import annotations

import pytest

from app import settings_store as S
from app.routers import ops

GB = 1024 ** 3


@pytest.fixture
async def cap(redis, monkeypatch):
    monkeypatch.setattr(S, "_store", S.SettingsStore(redis))

    async def set_cap(mb: int) -> None:
        await redis.set("cfg:max_file_mb", str(mb))
    return set_cap


async def test_zero_means_no_cap(cap):
    await cap(0)
    assert await ops._too_large(5 * GB) is False, "سقفِ صفر هر فایلی را می‌بست"
    assert await ops._too_large(1) is False


async def test_a_real_cap_still_applies(cap):
    """کنترل: رفع نباید سقفِ واقعی را خاموش کند."""
    await cap(100)
    assert await ops._too_large(200 * 1024 * 1024) is True
    assert await ops._too_large(50 * 1024 * 1024) is False


async def test_an_unknown_size_is_never_too_large(cap):
    await cap(100)
    assert await ops._too_large(None) is False
    assert await ops._too_large(0) is False


async def test_zero_vjoin_falls_back_to_no_cap_too(cap, redis):
    """`vjoin_max_mb = 0` به `max_file_mb` برمی‌گردد؛ با آن هم صفر، `collect_recv` بی‌سقف است."""
    await cap(0)
    await redis.set("cfg:vjoin_max_mb", "0")
    assert await ops._vjoin_cap_mb() == 0
