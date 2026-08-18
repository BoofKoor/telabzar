"""کرانِ مقادیرِ تنظیمات، و اینکه **هر دو** مسیرِ ادمین یک قاعده دارند.

پنلِ وب و `/admin`ِ تلگرام تا امروز دو اعتبارسنجیِ دست‌نویسِ جدا داشتند و هیچ
کدام کرانِ عددی نداشت، پس `max_file_mb = -1` از هر دو در می‌رفت. این فایل عمداً
**بیرونِ** `tests/panel/` است: `settings_store` و `routers/admin` هیچ‌کدام
`jinja2`/`cryptography` نمی‌خواهند، پس ادعای «یک قاعده» باید در jobِ اصلیِ CI هم
سنجیده شود، نه فقط در jobِ پنل.
"""
from __future__ import annotations

import pytest

from app import settings_store as ss


# ── کرانِ عددی ───────────────────────────────────────────────────
@pytest.mark.parametrize("key,value", [
    ("max_file_mb", "-1"),
    ("dl_max_size_mb", "-5"),
    ("dl_concurrency", "-1"),
    ("safety_strikes", "-2"),
], ids=["max_file_mb", "dl_max_size_mb", "dl_concurrency", "safety_strikes"])
def test_a_negative_number_is_refused(key, value):
    """منفی هیچ‌جا معنا ندارد؛ فقط به یک مقایسهٔ همیشه‌غلط تبدیل می‌شود."""
    assert ss.validate_value(key, value) is not None


#: کلیدهایی که مقدارشان به **آپلودِ بایتِ تازه** ختم می‌شود → سقفِ ۲۰۰۰ دارند.
#: هر کدام با ردیابیِ محلِ خواندن تأیید شده، نه با شباهتِ نام (جدول در §۷).
_UPLOAD_SIDE = ["dl_max_size_mb", "dl_direct_max_mb", "vjoin_max_mb",
                "compress_tiny_target_mb"]


@pytest.mark.parametrize("key", _UPLOAD_SIDE)
def test_a_size_over_the_upload_ceiling_is_refused(key):
    """سقف از سقفِ **آپلودِ** Bot API می‌آید، نه از سلیقه."""
    assert ss.validate_value(key, "2001") is not None
    assert ss.validate_value(key, str(ss._UPLOAD_CEILING_MB)) is None   # کنترلِ مرز


def test_a_receive_side_limit_has_no_telegram_ceiling():
    """`max_file_mb` سمتِ **دریافت** است و `--local` دانلود را بی‌سقف می‌کند.

    نسخهٔ اولِ این کار سقفِ ۲۰۰۰ را روی هر پنج کلیدِ مگابایتی گذاشت، و برای این
    یکی غلط بود: تنها خواننده‌اش `ops.py:_max_mb()` است و تنها مصرفش
    `_too_large()` — یعنی «آیا روی این فایلِ **از قبل دریافت‌شده** عملیات اجرا
    شود؟». نه intake چیزی را رد می‌کند و نه کارتش بایتی آپلود می‌کند.
    شاهدِ تولید: جدولِ `files` ۴۴ ردیفِ بالای ۲۰۰۰ مگ دارد، بزرگ‌ترین ۳۹۱۲ مگ.
    """
    assert ss.validate_value("max_file_mb", "4000") is None
    assert ss.validate_value("max_file_mb", "10000") is None
    assert "max_file_mb" not in ss.BOUNDS, "این کلید نباید سقفِ آپلود بگیرد"


def test_the_upload_ceiling_matches_what_the_docs_state():
    """کران باید به همان عددی گره بخورد که `docs/telegram-api.md` اعلام می‌کند.

    بدونِ این، `_UPLOAD_CEILING_MB` یک ثابتِ دستی است که از مستندش جدا می‌افتد —
    همان پوسیدگی‌ای که §۷ برای `_KNOWN_UNREACHABLE` ثبت کرده.

    **و پین‌کردنِ عدد به‌تنهایی کافی نیست.** نسخهٔ اولِ همین تست فقط دنبالِ
    «۲۰۰۰ MB» می‌گشت و سبز بود، در حالی که خودِ سند آن عدد را برای **هر دو**
    جهت می‌فروخت («lifts the 50 MB download / 20 MB upload limits to ~2000 MB»)
    — یعنی تست دقیقاً همان جمله‌ای را تأیید می‌کرد که باعثِ باگ شد. پس جهت هم
    پین می‌شود: سند باید صریح بگوید دانلود بی‌سقف است و ۲۰۰۰ مالِ آپلود است.
    """
    import pathlib
    doc = (pathlib.Path(__file__).resolve().parent.parent
           / "docs" / "telegram-api.md").read_text(encoding="utf-8")
    assert f"{ss._UPLOAD_CEILING_MB} MB" in doc, (
        f"سقفِ {ss._UPLOAD_CEILING_MB} در docs/telegram-api.md پیدا نشد")
    low = doc.lower()
    assert "no size limit" in low, "سند باید بگوید دانلود سقفِ حجم ندارد"
    assert "**download**" in low and "**upload**" in low, (
        "سند باید دو جهت را **جدا** نام ببرد؛ یک عدد برای هر دو جهت همان "
        "ثابتی است که می‌پوسد")


@pytest.mark.parametrize("key", ["safety_threshold", "ck_warmup_pct"])
def test_a_percent_over_a_hundred_is_refused(key):
    assert ss.validate_value(key, "101") is not None
    assert ss.validate_value(key, "9999") is not None
    assert ss.validate_value(key, "100") is None   # کنترل: خودِ ۱۰۰ مجاز است


def test_the_match_threshold_stays_inside_its_declared_range():
    assert ss.validate_value("match_min", "101") is not None
    assert ss.validate_value("match_min", "100") is None


@pytest.mark.parametrize("key", sorted(
    k for k, (kind, _d) in ss.RUNTIME_KEYS.items() if kind == "int"))
def test_zero_is_legal_everywhere(key):
    """۰ در این پروژه معنیِ تثبیت‌شده دارد: «بی‌سقف/خاموش».

    کشف‌محور روی همهٔ کلیدهای `int` — پس کلیدِ عددیِ بعدی هم خودبه‌خود پوشش
    می‌گیرد و کسی نمی‌تواند کفی بگذارد که «خاموش» را غیرممکن کند.
    """
    assert ss.validate_value(key, "0") is None


# ── چه چیزی «عدد» حساب می‌شود ────────────────────────────────────
@pytest.mark.parametrize("value", ["--5", "⑦", "²", "1,000", "1 000", "abc", ""],
                         ids=["double-minus", "circled-7", "superscript-2",
                              "comma", "space", "letters", "empty"])
def test_a_value_int_cannot_parse_is_refused(value):
    """معیار باید `int()` باشد، چون `get_int()` بعداً همان را می‌زند.

    `--5` و `⑦` و `²` هر سه از `str.isdigit()` رد می‌شوند و `int()` رویشان
    می‌ترکد (اندازه‌گیری‌شده) — یعنی با معیارِ قدیمی مقدار ذخیره و در صفحه نشان
    داده می‌شد در حالی که سیستم روی پیش‌فرض کار می‌کرد.
    """
    assert ss.validate_value("dl_concurrency", value) is not None


@pytest.mark.parametrize("value,expect", [("۲۰۰۰", 2000), ("٤٢", 42)],
                         ids=["persian", "arabic"])
def test_non_ascii_digits_keep_working(value, expect):
    """کنترل: این‌ها **از قبل** پذیرفته می‌شدند و باید بمانند.

    اندازه‌گیری‌شده روی سورسِ پیش از رفع: `'۲۰۰۰'.isdigit()` صادق است و
    `int('۲۰۰۰')` هم ۲۰۰۰ می‌دهد. سوییچ به `int()` این را نمی‌شکند.
    """
    assert int(value) == expect
    assert ss.validate_value("dl_max_duration_min", value) is None


# ── یک قاعده، دو مسیر ────────────────────────────────────────────
@pytest.mark.parametrize("key,value", [
    ("max_file_mb", "-1"),
    ("safety_threshold", "9999"),
    ("dl_concurrency", "--5"),
    ("dl_default_ux", "banana"),
], ids=["negative", "percent", "unparseable", "bad-enum"])
def test_the_telegram_path_refuses_what_the_panel_refuses(key, value):
    """`/admin set` باید همان چیزی را رد کند که فرمِ پنل رد می‌کند.

    ادعای «یک قاعده» است، نه تکرارِ تست‌های بالا: مسیرِ تلگرام تابعِ **خودش**
    را داشت و می‌توانست دوباره واگرا شود.
    """
    from app.routers.admin import _validate
    assert _validate(key, value) is not None
    assert ss.validate_value(key, value) is not None


def test_the_telegram_path_still_accepts_a_legal_value():
    from app.routers.admin import _validate
    assert _validate("dl_concurrency", "7") is None
    assert _validate("max_file_mb", "2000") is None


def test_the_telegram_path_escapes_its_error_for_html():
    """پیام با `parse_mode=HTML` می‌رود، پس `<` باید escape شود."""
    from app.routers.admin import _validate
    err = _validate("dl_concurrency", "<b>x</b>")
    assert err and "<b>" not in err and "&lt;b&gt;" in err
