"""مهاجرتِ کلیدهای `spotify_*`ِ ماچر به `match_*`.

آن پنج کلید رفتارِ **ماچر** را تعیین می‌کنند، نه اسپاتیفای را — و از وقتی
اپل‌موزیک هم از همان ماچر می‌گذرد، نامشان دیگر صادق نیست. نامی که صادق نیست
بعداً هزینه می‌دهد (همان درسی که «کشِ اسپاتیفای را قبل از اسموک پاک کن» را از
دستور به دستورِ **مضر** تبدیل کرد).

**چرا مهاجرت، نه fallbackِ خالص:** fallback یعنی پنل مقدارِ پیش‌فرض را نشان
می‌دهد در حالی که مقدارِ مؤثر چیزِ دیگری است — و ذخیره از آن نمای غلط، دادهٔ
واقعی را پاک می‌کند. دقیقاً همان چیزی که `/buttons` یک‌بار کرد و §۷ ثبتش کرده.

DBِ واقعی (SQLiteِ درون‌حافظه‌ای) و Redisِ واقعیِ درون‌حافظه‌ای، نه ماک.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import pathlib

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import settings_store as S
from app.models import Base, Setting


@pytest.fixture
async def store(redis, monkeypatch, tmp_path):
    # **فایل، نه `:memory:`** — و این تفاوت باعثِ نتیجهٔ گمراه‌کننده شده بود.
    # SQLAlchemy برای SQLiteِ حافظه‌ای یک اتصالِ مشترک نگه می‌دارد، پس چند
    # session هم‌زمان روی همان اتصال multiplex می‌شوند و اصلاً رقابتِ واقعی
    # مدل نمی‌شود: اندازه‌گیری روی `:memory:` می‌گفت «۲ نویسنده سالم، ۴ خراب»
    # در حالی که روی فایل نسخهٔ retry‌دار **از همان ۲ هم** می‌شکند. هر تستِ
    # رقابتی که DB لازم دارد باید اتصالِ جدا داشته باشد.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'settings.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(S, "Sessionmaker", maker)
    yield S.SettingsStore(redis), maker
    await engine.dispose()


async def _seed(maker, key: str, value: str) -> None:
    async with maker() as s:
        s.add(Setting(key=key, value=value))
        await s.commit()


async def _rows(maker) -> dict[str, str]:
    from sqlalchemy import select
    async with maker() as s:
        return {r.key: r.value for r in (await s.execute(select(Setting))).scalars().all()}


@pytest.mark.parametrize("new,old", sorted(S._RENAMED.items()))
async def test_every_renamed_key_still_returns_the_admins_stored_value(store, new, old):
    """پیش از رفع، ادمینی که این را تنظیم کرده بود بی‌صدا به پیش‌فرض برمی‌گشت."""
    st, maker = store
    await _seed(maker, old, "42")
    assert await st.get(new) == "42"


async def test_the_value_moves_to_the_new_name_and_the_old_row_is_dropped(store):
    """بعد از یک خواندن، جدول فقط نامِ تازه را دارد — پس پنل حقیقت را نشان می‌دهد."""
    st, maker = store
    await _seed(maker, "spotify_match_min", "70")
    assert await st.get_int("match_min", 55) == 70
    assert await _rows(maker) == {"match_min": "70"}


async def test_the_migration_is_announced_loudly_not_silently(store, caplog):
    """سقوطِ خاموش به مسیرِ دیگر همان چیزی است که پارسر را هفته‌ها مرده نگه داشت.

    و این خط تنها نشانه‌ای است که می‌گوید `_RENAMED` هنوز حذف‌شدنی نیست.
    """
    st, maker = store
    await _seed(maker, "spotify_meta", "on")
    with caplog.at_level(logging.WARNING, logger="telabzar.settings"):
        assert await st.get_bool("match_meta", False) is True
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "مهاجرت باید WARNING بدهد، نه INFO"
    assert "spotify_meta" in warnings[0].getMessage()
    assert "match_meta" in warnings[0].getMessage()


async def test_the_migration_happens_once_not_on_every_read(store, caplog):
    """سه خواندن، **یک** هشدار — وگرنه هر خواندن یک رفت‌وبرگشتِ اضافه دارد.

    هشدار به‌عنوان شمارنده استفاده می‌شود چون تنها اثرِ قابلِ‌مشاهدهٔ مهاجرت است.
    شمارشِ کلِ رکوردها به‌جای «بعد از اولی هیچ» عمدی است: `caplog.records` از
    قبل از بلاکِ `with` هم پر است، پس فرمِ دوم به دلیلِ غلط می‌افتاد — خودِ همین
    تست اولش این‌طور نوشته شده بود و افتاد.
    """
    st, maker = store
    with caplog.at_level(logging.WARNING, logger="telabzar.settings"):
        await _seed(maker, "spotify_source", "youtube")
        assert await st.get_str("match_source", "ytmusic") == "youtube"
        for _ in range(2):
            await st.r.flushall()               # کشِ Redis پاک شود تا واقعاً از DB بخواند
            assert await st.get_str("match_source", "ytmusic") == "youtube"
    migrations = [r for r in caplog.records if "migrating" in r.getMessage()]
    assert len(migrations) == 1, f"مهاجرت باید یک‌بار باشد، شد {len(migrations)}"


async def test_an_untouched_key_falls_through_to_the_env_default(store):
    """هیچ ردیفی نیست → پیش‌فرض، و هیچ هشداری هم نباید باشد."""
    st, _maker = store
    assert await st.get("match_min") is None
    assert await st.get_int("match_min", 55) == 55


async def test_a_value_already_under_the_new_name_wins_over_the_old_one(store):
    """اگر ادمین بعد از استقرار مقدارِ تازه‌ای گذاشته، مهاجرت نباید رویش بنویسد."""
    st, maker = store
    await _seed(maker, "spotify_match_min", "70")
    await st.set("match_min", "80")
    assert await st.get_int("match_min", 55) == 80


async def test_only_the_five_matcher_keys_are_renamed(store):
    """`spotify_enabled`/`client_id`/`secret` واقعاً مالِ اسپاتیفای‌اند و می‌مانند."""
    assert set(S._RENAMED) == {"match_meta", "match_max_tracks", "match_source",
                               "match_min", "match_yt_fallback"}
    for k in ("spotify_enabled", "spotify_client_id", "spotify_client_secret"):
        assert k in S.RUNTIME_KEYS
    for old in S._RENAMED.values():
        assert old not in S.RUNTIME_KEYS, f"{old} دیگر نباید در پنل باشد"


def _panel_groups() -> list:
    """`GROUPS` را **بدونِ import** از سورس می‌خواند.

    `app/admin_web.py` سرِ import به `cryptography`/`jinja2` نیاز دارد که فقط در
    `requirements-admin.txt`اند و در محیطِ تست و **روی رانرِ CI نصب نیستند** —
    همان محدودیتی که `_func_src` در `tests/test_phase2a.py` از قبل مستندش کرده
    و همان چیزی که `routers/admin.py` را وادار کرد helper را در `cookies.py`
    بگذارد. نسخهٔ اولِ این تست مستقیم import می‌کرد و **فقط روی CI** افتاد،
    چون سندباکسِ من `cryptography` نصب داشت.

    `GROUPS` یک لیترالِ خالص است، پس `literal_eval` کافی است و چیزی اجرا
    نمی‌شود.
    """
    src = pathlib.Path("app/admin_web.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "GROUPS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("GROUPS در app/admin_web.py پیدا نشد")


def test_every_panel_row_is_a_real_runtime_key():
    """گاردِ موجود برای ردیف‌های تازه — کلیدِ پنل که در RUNTIME_KEYS نباشد بی‌اثر است."""
    groups = _panel_groups()
    assert groups, "GROUPS خالی خوانده شد — تست بی‌معنا می‌شود"
    for _title, rows in groups:
        for key, _label, _hint in rows:
            assert key in S.RUNTIME_KEYS, f"ردیفِ پنلِ {key!r} کلیدِ زمانِ‌اجرا نیست"


# ── رقابت: بعد از `telabzar update` همهٔ پروسه‌ها با هم بالا می‌آیند ──────────
async def test_two_processes_migrating_at_once_do_not_crash(store, redis):
    """bot و download-worker هم‌زمان اولین خواندن را می‌زنند.

    پیش از رفع این **می‌ترکید**، نه اینکه بی‌صدا خراب شود:
    `IntegrityError: UNIQUE constraint failed: settings.key` — چون `set()` اول
    SELECT می‌کرد و بعد INSERT، و هر دو پروسه `row is None` می‌دیدند. با اجرا
    پیدا شد نه با خواندن. `get()` در مسیرِ داغِ `_dl_opts` است، پس این یعنی
    شکستِ دانلود.
    """
    st, maker = store
    other = S.SettingsStore(redis)                 # «پروسهٔ» دوم، همان DB و همان Redis
    await _seed(maker, "spotify_match_min", "70")
    got = await asyncio.gather(st.get_int("match_min", 55), other.get_int("match_min", 55))
    assert got == [70, 70]
    assert await _rows(maker) == {"match_min": "70"}
    assert await st.get_int("match_min", 55) == 70


async def test_a_late_reader_does_not_bury_the_migrated_value(store, redis):
    """پروسهٔ دومی که «چیزی برای مهاجرت نیست» می‌بیند نباید کشِ کلیدِ تازه را خراب کند.

    نسخهٔ اول در آن شاخه `_MISSING` می‌نوشت. کلیدِ منفی TTL ندارد، پس مقدارِ
    تازه‌مهاجرت‌کردهٔ ادمین **ماندگار** دفن می‌شد — دقیقاً همان سقوطِ خاموشی که
    این مهاجرت برای جلوگیری از آن نوشته شد.

    **درهم‌آمیزی مجبور می‌شود، نه انتظار کشیده** (قاعدهٔ §۶): پنجره باریک است —
    خواندنِ DBِ پروسهٔ دوم باید **پیش از** `set()`ِ اولی بیفتد و `get(old)`ش
    **پس از** `reset()`ِ اولی. نسخهٔ اولِ همین تست دو `get` پشتِ‌هم می‌زد و
    هرگز به آن شاخه نمی‌رسید (پس از مهاجرت ردیفِ DB هست و مسیرِ عادی جواب
    می‌دهد) — سابوتاژ نشان داد که برای آن ادعا **vacuous** بود. این‌جا پروسهٔ
    دوم دقیقاً در همان نقطه گذاشته می‌شود.
    """
    st, maker = store
    other = S.SettingsStore(redis)
    await _seed(maker, "spotify_meta", "on")
    assert await st.get_bool("match_meta", False) is True     # پروسهٔ اول مهاجرت را تمام کرد
    assert await redis.get("cfg:match_meta") == "on"

    # پروسهٔ دوم: DB را قبل از `set()`ِ اولی خالی دیده بود، و حالا که به سراغِ
    # نامِ قدیمی می‌رود دیگر نیست. این همان لحظهٔ clobber است.
    assert await other._migrate_renamed("match_meta") is None
    assert await redis.get("cfg:match_meta") == "on", "کشِ کلیدِ تازه نباید _MISSING شود"
    assert await st.get_bool("match_meta", False) is True     # مقدارِ ادمین سرِ جایش


@pytest.mark.parametrize("writers", [2, 4, 8, 16])
async def test_concurrent_writes_of_a_new_key_do_not_crash(store, redis, writers):
    """باگِ **نهفتهٔ** خودِ `set()` — مهاجرت فقط قابلِ‌دسترسش کرد.

    تا امروز بی‌خطر بود چون تنها نویسنده پنل بود؛ حالا هر پروسه‌ای سرِ بالا
    آمدن می‌نویسد.

    **چند نویسنده، عمداً.** نسخهٔ اولِ رفع یک «دوباره SELECT/INSERT» بود و روی
    هارنسِ `:memory:` سالم به‌نظر می‌رسید؛ روی DBِ فایل‌محور (اتصالِ جدا برای هر
    session) **از همان دو نویسنده هم** می‌شکست. مسیرِ دوم حالا `UPDATE`ِ مستقیم
    است — تعارض خودش ثابت می‌کند ردیف هست — که روی کلیدِ یکتا نمی‌تواند تعارض
    بدهد.
    """
    st, maker = store
    others = [S.SettingsStore(redis) for _ in range(writers - 1)]
    await asyncio.gather(st.set("match_min", "60"),
                         *[o.set("match_min", "60") for o in others])
    assert await _rows(maker) == {"match_min": "60"}
    assert await st.get_int("match_min", 55) == 60
