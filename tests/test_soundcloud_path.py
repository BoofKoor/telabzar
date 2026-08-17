"""مسیرِ ساندکلاود: انتخابگرِ فرمت، کلیدِ کش، و پیام‌های بن‌بست.

سه کارِ مستقل که یک پلتفرم مشترکشان است.

**۱) انتخابگر.** `ba/b`ِ عمومی روی همان ترک `hls_aac_96k` را برمی‌داشت (۹۶k،
۲۶ فرگمنتِ HLS، به‌علاوهٔ یک ترنسکدِ کاملِ AAC→MP3) در حالی که `http_mp3_0_0`
یک GETِ ساده و ۱۲۸k است. اندازه‌گیریِ اپراتور: ۱٫۳۹MB/۶ث در برابرِ ۴٫۰۲MB/۲ث.

تست‌ها انتخاب را با **موتورِ خودِ yt-dlp** می‌سنجند نه با assert روی رشتهٔ
انتخابگر، چون دامِ اصلی فقط با اجرا دیده می‌شود: `[acodec^=mp3]` درست به‌نظر
می‌رسد و **بی‌صدا AAC برمی‌دارد**، چون `acodec` برای فرمت‌های mp3ِ ساندکلاود
`None` است (از `codecs="…"`ِ mime-type می‌آید و `audio/mpeg` آن را ندارد).

**۲) کلیدِ کش.** `soundcloud.com/…`، `m.soundcloud.com/…` و `on.soundcloud.com/…`
سه کلیدِ متفاوت می‌ساختند. دوتای اول با نرمال‌سازیِ `sc:` یکی می‌شوند؛ سومی
بدونِ resolve نرمال‌شدنی **نیست** و با نوشتنِ کلیدِ دوم از `webpage_url` پوشش
داده می‌شود.

**۳) پیام‌ها.** سه پیام دربارهٔ «سشن» حرف می‌زدند در حالی که سطلِ ساندکلاود
هیچ اکانتی ندارد و پنل هم نمی‌تواند برایش بسازد.

**۰) خودِ هارنس** (بعداً اضافه شد، بخشِ «۰» پایین). نسخهٔ اولِ `_picked` ctxِ
انتخابگر را هاردکد می‌کرد و **هر دو فلگش غلط بود**. نتیجهٔ کارِ ۱ عوض نشد —
ولی همان نقص در کارِ کست‌باکس یک نقصِ تولیدیِ **خیالی** ساخت. حالا ctx از
`YoutubeDL._select_formats` می‌آید، یعنی همان جایی که تولید می‌سازدش.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from yt_dlp import YoutubeDL

from app import dl_cache
from app import downloader as D
from app.models import Base, File

# ── فرمت‌های واقعیِ یک ترکِ ساندکلاود ──────────────────────────────
# ساخته‌شده دقیقاً مثلِ `SoundcloudBaseIE` (شاخهٔ `formats.append`): `acodec` از
# `codecs="…"`ِ mime-type می‌آید، پس برای mp3 (که `audio/mpeg` است و چنین
# attributeی ندارد) **None** است و فقط `ext` تمایزدهنده است. فهرستِ فرمت‌ها
# همانی است که اپراتور روی سرور دید: hls_mp3_0_0 · http_mp3_0_0 · hls_aac_96k.
HLS_MP3 = {"format_id": "hls_mp3_0_0", "url": "https://cdn/a.m3u8", "ext": "mp3",
           "acodec": None, "vcodec": "none", "abr": 128, "protocol": "m3u8_native",
           "quality": -1}
HTTP_MP3 = {"format_id": "http_mp3_0_0", "url": "https://cdn/b.mp3", "ext": "mp3",
            "acodec": None, "vcodec": "none", "abr": 128, "protocol": "http",
            "quality": -1}
HLS_AAC = {"format_id": "hls_aac_96k", "url": "https://cdn/c.m3u8", "ext": "m4a",
           "acodec": "mp4a.40.2", "vcodec": "none", "abr": 96,
           "protocol": "m3u8_native", "quality": -1, "container": "m4a_dash"}
# **ترتیب باربر است، تزئینی نیست.** `ba` آخرین گزینهٔ جورشده را برمی‌دارد، پس
# ترتیبِ این فهرست تعیین می‌کند `ba/b`ِ عمومی چه چیزی بردارد. اپراتور روی سرور
# اندازه گرفت که تولید `hls_aac_96k` را برمی‌دارد، پس AAC باید **آخر** باشد
# وگرنه هارنس چیزی را بازتولید نمی‌کند که رفع برایش ساخته شده.
#
# نسخهٔ اولِ این فایل AAC را **اول** گذاشته بود و در نتیجه تستِ اصلی روی سورسِ
# پیش از رفع هم سبز می‌ماند — تستی توخالی با ظاهرِ سالم. سابوتاژ گرفتش، نه
# بازخوانی. `test_the_harness_reproduces_the_measured_production_choice` پایین
# همین را قفل می‌کند تا دوباره بی‌صدا نلغزد.
ALL_THREE = [HTTP_MP3, HLS_MP3, HLS_AAC]


def _picked(expr: str, formats: list[dict]) -> str | None:
    """فرمتی که yt-dlp با این عبارت برمی‌دارد — با موتورِ خودش، نه شبیه‌سازی.

    **ctx از `_select_formats` می‌آید، نه از یک دیکشنریِ دست‌ساز.** آن متد همان
    چیزی است که `process_video_result` صدا می‌زند (`YoutubeDL.py:2885`)، پس
    `incomplete_formats`/`has_merged_format` را دقیقاً همان‌جایی می‌سازد که تولید
    می‌سازدشان.

    نسخهٔ اول ctx را هاردکد می‌کرد (`incomplete_formats: False`، و
    `has_merged_format` را اصلاً نمی‌داد) و **هر دو مقدار غلط بودند**:
    اندازه‌گیری‌شده روی همین فیکسچر، yt-dlp مقدارِ `True` و `False` می‌سازد. این
    باگِ تولیدی نبود — انتخابگرِ ساندکلاود با هر دو ctx همان `http_mp3_0_0` را
    می‌دهد، چون `ba` بی‌اعتنا به این فلگ‌ها جور می‌شود — ولی هارنس یک نقصِ
    **خیالی** ساخت: در کارِ کست‌باکس گزارش کرد `bv*+ba/b` روی منبعِ فقط‌صوتی
    «هیچ فرمتی برنمی‌دارد»، نتیجه‌ای تمیز و بازتولیدپذیر و کاملاً غلط که نزدیک
    بود کدِ سالم را «تعمیر» کند. §۶: false fail، نه false pass — و سابوتاژ این
    رده را نمی‌گیرد، چون آن‌جا خودِ اندازه‌گیری خراب است نه assert.

    اگر روزی yt-dlp این متد را تغییرِ نام بدهد، این‌جا `AttributeError` می‌دهد و
    **کلِ فایل بلند می‌افتد** — که همان چیزی است که می‌خواهیم؛ سکوت و برگشت به
    ctxِ دست‌ساز دقیقاً همان تله است.
    """
    ydl = YoutubeDL({"format": expr, "quiet": True})
    got = ydl._select_formats(formats, ydl.build_format_selector(expr))
    return got[0]["format_id"] if got else None


def _ctx_yt_dlp_builds(formats: list[dict]) -> dict:
    """ctxی که خودِ yt-dlp برای این فرمت‌ها می‌سازد (با یک انتخابگرِ جاسوس)."""
    seen: dict = {}

    def _spy(ctx):
        seen.update(ctx)
        return []

    YoutubeDL({"quiet": True})._select_formats(formats, _spy)
    return seen


# شکلِ **پیش از رفع** — عمداً این‌جا نگه داشته شده تا کنترلِ منفی بتواند نشان
# دهد نسخهٔ محافظت‌نشده روی همین هارنس واقعاً می‌افتد. بدونِ آن، «فلگ درست است»
# از «این مسیر اصلاً اجرا نمی‌شود» تفکیک‌پذیر نیست.
def _picked_with_a_hardcoded_ctx(expr: str, formats: list[dict]) -> str | None:
    ydl = YoutubeDL({"format": expr, "quiet": True})
    got = list(ydl.build_format_selector(expr)(
        {"formats": formats, "incomplete_formats": False}))
    return got[0]["format_id"] if got else None


def _sc(formats: list[dict]) -> str | None:
    """انتخابِ **تولید** برای یک لینکِ ساندکلاودِ صوتی."""
    return _picked(D._selector_to_format("audio", "soundcloud"), formats)


# ── ۰) خودِ هارنس ───────────────────────────────────────────────────
# سه ادعا در سه سطح، چون این هم یک «دفاع در عمق» است و یک تستِ انتها‌به‌انتها
# نمی‌تواند هر دو فلگ را جدا اثبات کند (§۷).
def test_the_harness_computes_the_flags_like_yt_dlp_does():
    """پینِ حقیقتِ زمینی: yt-dlp برای این فیکسچر چه ctxی می‌سازد.

    هر دو مقداری که نسخهٔ اولِ هارنس فرض کرده بود **غلط** بودند:
    `incomplete_formats` را `False` می‌گفت (درستش `True` است — همهٔ فرمت‌ها
    `vcodec="none"` دارند، یعنی همان حالتِ «فقط‌صوتی» که کامنتِ خودِ yt-dlp
    ساندکلاود را به‌عنوان مثالش نام می‌برد) و `has_merged_format` را اصلاً
    نمی‌داد.
    """
    ctx = _ctx_yt_dlp_builds(ALL_THREE)
    assert ctx["incomplete_formats"] is True, "هارنس `False` فرض کرده بود"
    assert "has_merged_format" in ctx, "هارنس این کلید را اصلاً نمی‌داد"
    assert ctx["has_merged_format"] is False


@pytest.mark.parametrize("expr", ["b", "bv*+ba/b"])
def test_a_hardcoded_ctx_invents_a_defect_that_does_not_exist(expr):
    """کنترلِ منفی — **این چیزی است که هارنسِ درست را از هارنسِ مرده جدا می‌کند**.

    `format_fallback` در `YoutubeDL.py` مستقیماً به `ctx['incomplete_formats']`
    گیت خورده، پس روی یک منبعِ **تک‌نوع** یک `False`ِ هاردکد باعث می‌شود
    انتخابگر «هیچ‌چیز» برگرداند. اندازه‌گیری‌شده، و دقیقاً همان چیزی است که در
    کارِ کست‌باکس به‌عنوان یک نقصِ تولیدی گزارش شد و نبود.
    """
    assert _picked_with_a_hardcoded_ctx(expr, ALL_THREE) is None, (
        "پیش‌شرط: نسخهٔ محافظت‌نشده باید روی همین هارنس بیفتد، وگرنه این تست "
        "چیزی را جدا نمی‌کند.")
    assert _picked(expr, ALL_THREE) == "hls_aac_96k"


def test_a_hardcoded_ctx_omits_a_key_the_selector_reads_directly():
    """ادعای دوم و مستقل: کلیدِ **غایب** هم بی‌صدا falsy نیست.

    `build_format_selector` مقدارِ `ctx['has_merged_format']` را با `[]`
    می‌خواند نه `.get()`، پس هر انتخابگری که به شاخهٔ `seperate_fallback` برسد
    (یعنی نامِ یک پسوندِ ویدیویی، مثلِ `mp4`) با ctxِ دست‌ساز `KeyError`
    می‌دهد. جدا از ادعای بالا تست می‌شود چون فلگِ دیگری است و سابوتاژِ دیگری
    دارد.
    """
    with pytest.raises(KeyError):
        _picked_with_a_hardcoded_ctx("mp4", ALL_THREE)
    assert _picked("mp4", ALL_THREE) is None   # هیچ mp4ی نیست، ولی تمیز


# ── ۱) انتخابگر ────────────────────────────────────────────────────
def test_the_harness_reproduces_the_measured_production_choice():
    """کنترلِ منفی — **پیش‌شرطِ اعتبارِ بقیهٔ این فایل**.

    اگر انتخابگرِ **عمومی** روی این فیکسچر همان `hls_aac_96k`ی را برندارد که
    اپراتور روی سرور دید، هارنس رفتارِ تولید را مدل نمی‌کند و هر عددِ سبزِ دیگری
    این‌جا دربارهٔ سندباکس حرف می‌زند نه دربارهٔ کد. §۶: «اندازه‌گیری تا وقتی
    نشان نداده‌ای هارنس می‌تواند بیفتد، هیچ نگفته».
    """
    assert _picked("ba/b", ALL_THREE) == "hls_aac_96k"


def test_soundcloud_takes_progressive_mp3_when_it_exists():
    """قلبِ رفع: MP3ِ progressive، نه AACِ HLS."""
    assert _sc(ALL_THREE) == "http_mp3_0_0"


def test_soundcloud_falls_back_to_aac_when_mp3_is_gone():
    """ساندکلاود اعلام کرده MP3 را حذف می‌کند — زنجیره باید بی‌تغییرِ کد بچرخد.

    کنترل: باید **هر دو طرفِ** رفع سبز بماند (امروز هم AAC انتخاب می‌شود).
    """
    assert _sc([HLS_AAC]) == "hls_aac_96k"


def test_soundcloud_takes_hls_mp3_when_progressive_is_gone():
    """پلهٔ میانی: progressive رفته ولی MP3ی هست → هنوز نباید AAC برداریم."""
    assert _sc([HLS_AAC, HLS_MP3]) == "hls_mp3_0_0"


def test_the_choice_does_not_depend_on_the_order_yt_dlp_hands_us():
    """چرا شرطِ `[protocol^=http]` صریح است و نه ضمنی.

    بدونِ آن، انتخاب به ترتیبِ مرتب‌سازیِ yt-dlp وابسته می‌شود: اندازه‌گیری‌شده،
    با جابه‌جاییِ دو فرمتِ mp3 فرمِ ضمنی به `hls_mp3_0_0` می‌افتد (۲۶ فرگمنت
    به‌جای یک GET). همان درسِ لنگرِ `regexp`، این‌بار پیش از merge.
    """
    for order in ([HLS_AAC, HLS_MP3, HTTP_MP3], [HLS_AAC, HTTP_MP3, HLS_MP3]):
        assert _sc(order) == "http_mp3_0_0", f"ترتیب نتیجه را عوض کرد: {order}"


def test_an_acodec_based_selector_matches_nothing_at_all():
    """چرا این تست‌ها موتور را اجرا می‌کنند و رشتهٔ انتخابگر را assert نمی‌کنند.

    این **پینِ رفتارِ yt-dlp** است، نه ادعای رفع. طبیعی‌ترین شرطی که آدم
    می‌نویسد — `[acodec^=mp3]` — روی فرمت‌های mp3ِ ساندکلاود **هیچ تطبیقی
    ندارد**، چون `acodec` آن‌ها `None` است (از `codecs="…"`ِ mime-type می‌آید و
    `audio/mpeg` چنین attributeی ندارد).

    ادعا عمداً روی **بی‌اثر بودنِ** شرط است نه روی فرمتی که در عمل انتخاب
    می‌شود: با `/ba/b`ِ انتهایی، آنچه دستِ آخر برداشته می‌شود به ترتیبِ فهرست
    بستگی دارد، پس نسخهٔ اول این تست خودش order-dependent بود و ادعای
    نادقیقی می‌کرد. «هیچ‌چیز جور نمی‌شود» مستقل از ترتیب است و همان چیزی است
    که تله را می‌سازد.
    """
    for order in ([HLS_AAC, HLS_MP3, HTTP_MP3], [HTTP_MP3, HLS_MP3, HLS_AAC]):
        assert _picked("ba[acodec^=mp3]", order) is None, "شرطِ acodec نباید جور شود"
        # و ext جور می‌شود. *کدام* mp3 برداشته شود به ترتیب بستگی دارد — به همین
        # دلیل انتخابگرِ تولید `[protocol^=http]` را هم صریح می‌گوید.
        assert _picked("ba[ext=mp3]", order) in ("http_mp3_0_0", "hls_mp3_0_0")


@pytest.mark.parametrize("platform", ["bandcamp", "spotify", "apple", "youtube", None])
def test_no_other_platform_changed_its_audio_selector(platform):
    """شعاعِ انفجار: فقط ساندکلاود. بقیه بیت‌به‌بیت همان `ba/b`ِ قبلی."""
    assert D._selector_to_format("audio", platform) == "ba/b"


@pytest.mark.parametrize("sel,expected", [
    ("best", "bv*+ba/b"), ("", "bv*+ba/b"), ("720", "bv*[height<=720]+ba/b[height<=720]/b"),
])
def test_video_selectors_are_untouched_even_for_soundcloud(sel, expected):
    """گیت روی `sel == "audio"` است، نه روی پلتفرم به‌تنهایی."""
    assert D._selector_to_format(sel, "soundcloud") == expected


def test_the_engine_is_asked_for_the_platform_of_the_url():
    """`download_ytdlp` باید پلتفرم را از `url` بدهد، وگرنه رفع هرگز شلیک نمی‌کند.

    ساختاری، چون اجرای واقعیِ `download_ytdlp` یک yt-dlpِ زنده می‌خواهد.
    """
    import inspect
    src = inspect.getsource(D.download_ytdlp)
    assert "_selector_to_format(selector, platform_of(url))" in src, (
        "انتخابگر بدونِ پلتفرم صدا زده می‌شود → شاخهٔ ساندکلاود مرده است.")


# ── ۲) کلیدِ کش ─────────────────────────────────────────────────────
CANONICAL = "https://soundcloud.com/mossihashemi/siavash-ghomeishi-ey-gharibe"
SHORT = "https://on.soundcloud.com/IdLs5FiDTkS6yljUe0"


@pytest.mark.parametrize("url", [
    pytest.param(CANONICAL, id="plain"),
    pytest.param("https://www.soundcloud.com/mossihashemi/siavash-ghomeishi-ey-gharibe",
                 id="www"),
    pytest.param("https://m.soundcloud.com/mossihashemi/siavash-ghomeishi-ey-gharibe",
                 id="mobile"),
    pytest.param(CANONICAL + "/", id="trailing-slash"),
    pytest.param(CANONICAL + "?utm_source=clipboard&si=abc", id="tracking-params"),
])
def test_every_full_form_of_a_track_collapses_to_one_key(url):
    assert dl_cache.cache_key(url, "audio") == dl_cache.cache_key(CANONICAL, "audio")


def test_a_set_is_not_confused_with_a_track():
    """`/sets/` عمداً کلیدِ جداست — یک ست با یک ترک یکی نیست."""
    a = dl_cache.cache_key("https://soundcloud.com/u/sets/summer", "audio")
    b = dl_cache.cache_key("https://soundcloud.com/u/summer", "audio")
    assert a != b


def test_two_different_tracks_never_share_a_key():
    """کنترلِ ضدِ over-normalization: نرمال‌ساز نباید محتوا را قاطی کند."""
    a = dl_cache.cache_key("https://soundcloud.com/u/track-one", "audio")
    b = dl_cache.cache_key("https://soundcloud.com/u/track-two", "audio")
    assert a != b


def test_a_short_link_cannot_be_normalised_on_its_own():
    """پینِ **علت**: به همین دلیل کلیدِ دوم لازم است، نه یک الگوی دیگر."""
    assert dl_cache.cache_key(SHORT, "audio") != dl_cache.cache_key(CANONICAL, "audio")


@pytest.fixture()
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


def _file() -> File:
    return File(ref="abc12345", owner_id=1, file_unique_id="u1", file_id="FID",
                kind="audio", name="track.mp3", size=4_210_000, platform="soundcloud")


async def test_a_short_link_download_makes_the_full_link_hit_later(db):
    """ادعای اصلیِ کار ۲، انتها به انتها.

    کاربر لینکِ **کوتاهِ** اپ را می‌فرستد (تنها چیزی که دکمهٔ Share می‌دهد)؛
    بعداً همان ترک با لینکِ **کامل** باید آنی تحویل شود.
    """
    await dl_cache.put_cached(db, SHORT, "audio", _file(), canonical_url=CANONICAL)

    assert await dl_cache.get_cached(db, SHORT, "audio") is not None, "تکرارِ لینکِ کوتاه"
    assert await dl_cache.get_cached(db, CANONICAL, "audio") is not None, "لینکِ کامل"
    # و هر شکلِ دیگری از لینکِ کامل، چون کلیدِ دوم از همان نرمال‌ساز رد شده است
    mobile = "https://m.soundcloud.com/mossihashemi/siavash-ghomeishi-ey-gharibe"
    assert await dl_cache.get_cached(db, mobile, "audio") is not None, "شکلِ موبایل"


async def test_the_second_key_goes_through_the_same_normaliser(db):
    """اگر کلیدِ دوم از URLِ خام ساخته می‌شد، شکلِ دیگرِ لینکِ کامل miss می‌خورد.

    کانونیکِ داده‌شده عمداً فرمِ **`m.`** است، نه `www.`: شاخهٔ عمومیِ
    `_cache_url` خودش `www.` را می‌ریزد، پس تستی که آن فرم را بدهد حتی بدونِ
    نرمال‌سازیِ `sc:` هم سبز می‌ماند — یعنی توخالی. `m.` تنها با `sc:` جمع
    می‌شود. (نسخهٔ اول همین اشتباه را داشت و سابوتاژ گرفتش.)
    """
    await dl_cache.put_cached(
        db, SHORT, "audio", _file(),
        canonical_url="https://m.soundcloud.com/mossihashemi/siavash-ghomeishi-ey-gharibe")
    assert await dl_cache.get_cached(db, CANONICAL, "audio") is not None


async def test_no_second_row_when_the_canonical_url_adds_nothing(db):
    """کنترل: لینکی که از قبل کانونیک است نباید ردیفِ اضافه بسازد."""
    await dl_cache.put_cached(db, CANONICAL, "audio", _file(), canonical_url=CANONICAL)
    from sqlalchemy import func, select

    from app.models import DownloadCache
    n = (await db.execute(select(func.count()).select_from(DownloadCache))).scalar_one()
    assert n == 1


async def test_a_match_platform_never_writes_a_youtube_keyed_row(db):
    """کنترلِ معکوس، و باربر: برای اسپاتیفای `webpage_url` **یوتیوب** است.

    نوشتنش یعنی ردیفی که `_MATCH_VERSION` نمی‌گیرد و تغییرِ ماچر باطلش نمی‌کند
    — همان «جوابِ کهنه برای همیشه» که نسخه‌دارکردن برای بستنش ساخته شد.
    """
    from app.tasks_download import _canonical_url
    info = {"webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    assert _canonical_url(info, "spotify") is None
    assert _canonical_url(info, "apple") is None
    assert _canonical_url(info, "soundcloud") == info["webpage_url"]
    assert _canonical_url({}, "soundcloud") is None
