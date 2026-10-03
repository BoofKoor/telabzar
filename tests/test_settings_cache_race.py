"""فاز ۴ / موردِ ۲۰ — پرکردنِ کشِ تنظیمات نباید نوشتنِ تازه‌ترِ ادمین را دفن کند.

`SettingsStore.get` روی miss از DB می‌خواند و بعد **بی‌قید** `cfg:<key>` را
می‌نوشت. بینِ آن SELECT و آن نوشتن چند await فاصله است؛ اگر همین وسط پنل
`set()` زده باشد، خواننده مقدارِ تازه را با نتیجهٔ کهنهٔ SELECTِ خودش بازنویسی
می‌کرد — و چون کلید انقضا نداشت، **برای همیشه**: پنل «ذخیره شد» می‌گفت و هیچ
پروسه‌ای تنظیم را نمی‌دید تا دستی کلید پاک شود.

درهم‌آمیزی **مجبور** می‌شود (§۶): `Sessionmaker` طوری پیچیده شده که دقیقاً بعد از
SELECTِ خواننده و پیش از پرکردنش، نویسنده اجرا شود. منتظرِ رقابت نمی‌مانیم.

DB فایل‌محور و fakeredis؛ fixtureِ `store` از `test_settings_rename` می‌آید.
"""
from __future__ import annotations

import contextlib

import pytest

from app import settings_store as S
from tests.test_settings_rename import _seed, store  # noqa: F401 — `store` یک fixture است

KEY = "dl_max_size_mb"


def _gate(monkeypatch, maker, hook):
    """اولین session (= SELECTِ خواننده) که بسته شد، `hook` اجرا می‌شود — یک‌بار."""
    fired = {"done": False}

    @contextlib.asynccontextmanager
    async def gated():
        async with maker() as s:
            yield s
        if not fired["done"]:
            fired["done"] = True
            await hook()

    monkeypatch.setattr(S, "Sessionmaker", gated)
    return fired


async def test_a_cold_read_does_not_bury_a_concurrent_save(store, monkeypatch, redis):
    """پیش از رفع: `_MISSING` روی مقدارِ ادمین → `get` برای همیشه None."""
    st, maker = store
    fired = _gate(monkeypatch, maker, lambda: st.set(KEY, "777"))
    assert await st.get(KEY) is None          # خوانندهٔ پیش از نوشتن، درست None می‌بیند
    assert fired["done"], "درهم‌آمیزی اجرا نشد — تست چیزی نسنجید"
    assert await redis.get("cfg:" + KEY) == "777"
    assert await st.get(KEY) == "777", "تنظیمِ ذخیره‌شده زیرِ negative-cache دفن شد"


async def test_a_stale_read_does_not_overwrite_a_newer_save(store, monkeypatch, redis):
    st, maker = store
    await _seed(maker, KEY, "100")
    fired = _gate(monkeypatch, maker, lambda: st.set(KEY, "777"))
    assert await st.get(KEY) == "100"
    assert fired["done"]
    assert await st.get(KEY) == "777", "مقدارِ کهنه روی مقدارِ تازه نشست"


async def test_a_stale_read_does_not_undo_a_concurrent_reset(store, monkeypatch, redis):
    st, maker = store
    await _seed(maker, KEY, "100")
    fired = _gate(monkeypatch, maker, lambda: st.reset(KEY))
    assert await st.get(KEY) == "100"
    assert fired["done"]
    assert await st.get(KEY) is None, "reset بی‌اثر شد؛ مقدارِ حذف‌شده از کش سرو می‌شود"


@pytest.mark.parametrize("seed", [None, "100"], ids=["missing", "present"])
async def test_every_cache_entry_expires(store, redis, seed):
    """کش بهینه‌سازی است؛ هر کهنگیِ باقی‌مانده (مثلاً نوشتنِ ازدست‌رفتهٔ Redis) کران‌دار است.

    `TTL` روی کلیدِ بی‌انقضا `-1` می‌دهد، پس این ادعا انقضای صریح را می‌سنجد.
    """
    st, maker = store
    if seed is not None:
        await _seed(maker, KEY, seed)
    await st.get(KEY)
    assert 0 < await redis.ttl("cfg:" + KEY) <= S._CACHE_TTL
    await st.set(KEY, "5")
    assert 0 < await redis.ttl("cfg:" + KEY) <= S._CACHE_TTL
    await st.reset(KEY)
    assert 0 < await redis.ttl("cfg:" + KEY) <= S._CACHE_TTL


async def test_a_cold_read_still_fills_the_cache(store, monkeypatch, redis):
    """کنترل: `NX` نباید پرکردنِ عادی را بکشد — خواندنِ دوم به DB نمی‌رود."""
    st, maker = store
    await _seed(maker, KEY, "100")
    assert await st.get(KEY) == "100"
    opened = {"n": 0}

    @contextlib.asynccontextmanager
    async def counting():
        opened["n"] += 1
        async with maker() as s:
            yield s
    monkeypatch.setattr(S, "Sessionmaker", counting)
    assert await st.get(KEY) == "100"
    assert opened["n"] == 0, "خواندنِ دوم باید از کش بیاید"
