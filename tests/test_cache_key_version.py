"""نسخهٔ کلیدِ کش: فقط برای پلتفرم‌هایی که هدف را خودمان انتخاب می‌کنیم.

کلید تا امروز `(URLِ نرمال‌شده، selector)` بود و **هیچ‌چیز از منطقِ خودمان** در
آن نبود، پس هر تغییرِ ماچر یا پارسر ردیف‌ها را روی جوابِ قبلی رها می‌کرد —
اپراتور مجبور بود قبل از هر اسموک ۳۴ ردیفِ اسپاتیفای را دستی پاک کند. و چون کش
**`file_id`** نگه می‌دارد نه بایت، ردیفِ کهنه پهنای‌باند خرج نمی‌کند بلکه فایلِ
**غلط** تحویل می‌دهد؛ یعنی مسئلهٔ درستی است نه ذخیره‌سازی.

**چرا سراسری نه:** برای لینکِ یوتیوب چیزی برای غلط بودن نیست — شناسهٔ کش‌شده
دقیقاً همان است که URL نام می‌برد. نسخهٔ سراسری ردیف‌های سالم را برای مشکلی که
هرگز نداشتند دور می‌ریخت. پس تستِ **منفی** (کلیدِ یوتیوب/اینستاگرام دست‌نخورده)
مهم‌ترین تستِ این فایل است، و روی **هر دو** کلید زده می‌شود — `cache_key` و
`_legacy_key` — چون اگر نرمال‌سازیِ `sp:` نشت کند همان‌جا لو می‌رود.

**و ردِ fallbackِ legacy، که بدونش کلِ کار بی‌اثر است:** برای URLِ اسپاتیفای
`cache_key` و `_legacy_key` **از قبل** متفاوت‌اند (چون `_cache_url` اسکیم را
می‌ریزد)، پس مسیر این بود: کلیدِ نسخه‌دار → miss → اصابت روی ردیفِ خامِ کهنه →
مهاجرت به کلیدِ نو → همان جوابِ غلط، این‌بار زیرِ کلیدِ تازه.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import dl_cache as C
from app import downloader as D
from app.models import Base, DownloadCache

SPOTIFY = "https://open.spotify.com/track/4Mrmg7XjDKqKWTw38hFCq6"
YOUTUBE = "https://youtu.be/abcdefghijk"
INSTAGRAM = "https://instagram.com/p/Cxyz123"
PLAYLIST = "https://open.spotify.com/playlist/37i9dQZF1DX0XUfTFmNBRM"


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


# ── دامنهٔ نسخه ─────────────────────────────────────────────────────────────
def test_only_match_platforms_are_versioned():
    assert C._we_choose_the_target(SPOTIFY) is True
    assert C._we_choose_the_target(PLAYLIST) is True
    assert C._we_choose_the_target(YOUTUBE) is False
    assert C._we_choose_the_target(INSTAGRAM) is False


def test_bumping_the_version_moves_only_the_spotify_key(monkeypatch):
    """تستِ منفیِ اصلی: ردیف‌های سالم نباید دور ریخته شوند."""
    before = {u: C.cache_key(u, "best") for u in (SPOTIFY, PLAYLIST, YOUTUBE, INSTAGRAM)}
    monkeypatch.setattr(C, "_MATCH_VERSION", C._MATCH_VERSION + 1)
    after = {u: C.cache_key(u, "best") for u in (SPOTIFY, PLAYLIST, YOUTUBE, INSTAGRAM)}
    assert before[SPOTIFY] != after[SPOTIFY]
    assert before[PLAYLIST] != after[PLAYLIST]
    assert before[YOUTUBE] == after[YOUTUBE], "کلیدِ یوتیوب عوض شد — ردیفِ سالم دور ریخته می‌شود"
    assert before[INSTAGRAM] == after[INSTAGRAM], "کلیدِ اینستاگرام عوض شد"


def test_the_legacy_key_is_untouched_for_non_match_platforms(monkeypatch):
    """`_legacy_key` نباید نه نسخه بگیرد نه نرمال‌سازیِ تازه.

    اگر `sp:` به آن نشت کند، مهاجرتِ کشِ موجود برای یوتیوب/اینستاگرام می‌شکند.
    """
    before = {u: C._legacy_key(u, "best") for u in (SPOTIFY, YOUTUBE, INSTAGRAM)}
    monkeypatch.setattr(C, "_MATCH_VERSION", C._MATCH_VERSION + 5)
    for u in (SPOTIFY, YOUTUBE, INSTAGRAM):
        assert C._legacy_key(u, "best") == before[u], f"_legacy_key برای {u} عوض شد"
    # و همچنان همان هشِ URLِ خام است (نه `_cache_url`)
    import hashlib
    assert C._legacy_key(YOUTUBE, "best") == \
        hashlib.sha1(f"{YOUTUBE}\nbest".encode()).hexdigest()[:64]


def test_the_selector_still_separates_qualities():
    assert C.cache_key(SPOTIFY, "best") != C.cache_key(SPOTIFY, "worst")
    assert C.cache_key(YOUTUBE, "720") != C.cache_key(YOUTUBE, "1080")


# ── ردِ fallbackِ legacy ────────────────────────────────────────────────────
async def test_a_stale_legacy_spotify_row_is_not_resurrected(maker):
    """قلبِ کار: ردیفِ خامِ کهنهٔ اسپاتیفای نباید جلو آورده شود.

    بدونِ این، بمپِ نسخه صفر اثر داشت — و بدتر، ردیفِ کهنه را زیرِ کلیدِ تازه
    «نو» می‌کرد.
    """
    async with maker() as s:
        s.add(DownloadCache(key=C._legacy_key(SPOTIFY, "best"), file_id="STALE",
                            kind="audio", platform="spotify"))
        await s.commit()
    async with maker() as s:
        assert C.cache_key(SPOTIFY, "best") != C._legacy_key(SPOTIFY, "best"), \
            "پیش‌فرضِ این تست: دو کلید متفاوت‌اند"
        assert await C.get_cached(s, SPOTIFY, "best") is None, "جوابِ کهنه سرو شد"
    async with maker() as s:  # و مهاجرتی هم نوشته نشده باشد
        assert await s.get(DownloadCache, C.cache_key(SPOTIFY, "best")) is None


async def test_a_legacy_youtube_row_is_still_migrated(maker):
    """کنترل: مهاجرتِ کشِ موجود برای پلتفرم‌های غیرِتطبیقی باید سرِ جایش بماند."""
    async with maker() as s:
        s.add(DownloadCache(key=C._legacy_key(YOUTUBE, "best"), file_id="KEEP",
                            kind="video", platform="youtube"))
        await s.commit()
    async with maker() as s:
        row = await C.get_cached(s, YOUTUBE, "best")
        assert row is not None and row.file_id == "KEEP"
    async with maker() as s:
        migrated = await s.get(DownloadCache, C.cache_key(YOUTUBE, "best"))
        assert migrated is not None and migrated.file_id == "KEEP"


async def test_a_versioned_row_written_now_is_read_back(maker):
    """کنترلِ رفت‌وبرگشت: نوشتن و خواندن با کلیدِ نسخه‌دار باید کار کند."""
    async with maker() as s:
        await C._upsert(s, SPOTIFY, "best", file_id="FRESH", kind="audio",
                        platform="spotify")
    async with maker() as s:
        row = await C.get_cached(s, SPOTIFY, "best")
        assert row is not None and row.file_id == "FRESH"


async def test_a_row_from_an_older_version_is_ignored(maker):
    """ردیفی که با نسخهٔ قبلی نوشته شده نباید خوانده شود."""
    async with maker() as s:
        await C._upsert(s, SPOTIFY, "best", file_id="V1", kind="audio", platform="spotify")
    old_key = C.cache_key(SPOTIFY, "best")
    import unittest.mock as m
    with m.patch.object(C, "_MATCH_VERSION", C._MATCH_VERSION + 1):
        async with maker() as s:
            assert await C.get_cached(s, SPOTIFY, "best") is None
            assert C.cache_key(SPOTIFY, "best") != old_key
    async with maker() as s:  # ردیفِ قدیمی پاک نشده، فقط کنار گذاشته شده
        assert await s.get(DownloadCache, old_key) is not None


# ── پلی‌لیست/آلبوم (سؤالِ ۲) ────────────────────────────────────────────────
def test_the_album_cache_path_is_gallerydl_only_so_it_is_never_versioned():
    """`put_album_cached` پشتِ `engine == "gallerydl"` است، پس پلتفرمش هرگز تطبیقی نیست.

    و **درست هم همین است**: gallery-dl هدف را انتخاب نمی‌کند، همان چیزی را
    می‌کشد که URL نام می‌برد — پس نسخه‌دار کردنش ردیفِ سالم را دور می‌ریخت.
    """
    for u in ("https://instagram.com/p/Cabc123", "https://pinterest.com/pin/1234"):
        assert C._we_choose_the_target(u) is False
        assert D.engine_for(u) == "gallerydl"


def test_a_multi_track_spotify_playlist_writes_no_cache_row():
    """پلی‌لیستِ چندترکی `url=None` می‌گیرد، پس ردیفی ساخته نمی‌شود.

    `tasks_download.py:1113` → `url=url if len(paths) == 1 else None`، و
    `_spawn` فقط `if url and f.file_id` می‌نویسد (`:544`). پس سؤالِ نسخه برای
    ردیف‌های پلی‌لیست مطرح نمی‌شود — نه اینکه بدونِ نسخه بمانند.
    """
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "app" / "tasks_download.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.keyword) and node.arg == "url"
                and isinstance(node.value, ast.IfExp)):
            found = True                       # url=... if ... else None
            assert isinstance(node.value.orelse, ast.Constant)
            assert node.value.orelse.value is None
    assert found, "شرطِ `url=url if len(paths) == 1 else None` پیدا نشد"
    # و خودِ گاردِ نوشتن
    assert "if url and f.file_id:" in src


# ── ساختار ─────────────────────────────────────────────────────────────────
def test_no_import_cycle_between_dl_cache_and_downloader():
    """`downloader` نباید `dl_cache` را import کند، وگرنه حلقه می‌شود.

    با **AST** خوانده می‌شود نه تطبیقِ رشته: نسخهٔ اولِ این تست زیررشته‌ای بود و
    کامنتِ خودم را در `downloader.py` می‌گرفت (کامنتِ کنارِ `_MATCH_PLATFORMS`) که اسمِ `dl_cache` را می‌برد —
    دقیقاً همان تلهٔ «کامنتِ خودم را گرفت» که ۲۰۲۶-۰۸-۱۰ ثبت شده.
    """
    import ast
    import pathlib
    tree = ast.parse((pathlib.Path(__file__).resolve().parent.parent
                      / "app" / "downloader.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported += [f"{node.module or ''}.{a.name}" for a in node.names]
    assert not any("dl_cache" in m for m in imported), \
        f"downloader، dl_cache را import کرد — حلقهٔ import: {imported}"


def test_the_match_platform_set_is_not_duplicated_in_dl_cache():
    """یک منبع برای «هدف را ما انتخاب می‌کنیم» — نه دو فهرستِ دست‌نویس."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "app" / "dl_cache.py").read_text(encoding="utf-8")
    assert "_MATCH_PLATFORMS" in src and '"spotify"' not in src, \
        "dl_cache نامِ پلتفرم را هاردکد کرد به‌جای خواندن از _MATCH_PLATFORMS"
    assert C._MATCH_PLATFORMS is D._MATCH_PLATFORMS
