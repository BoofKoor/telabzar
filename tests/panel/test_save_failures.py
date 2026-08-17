"""خوشهٔ «شکستِ خاموش» در پنل — فرم موفقیت اعلام می‌کند و کاری نکرده.

هر چهار یافته یک شکل دارند و به همین دلیل یک فایل‌اند: ورودیِ نامعتبر بی‌صدا
دور ریخته می‌شود (یا بدتر، دادهٔ سالم را پاک می‌کند) و کاربر بنرِ سبز می‌بیند.
از بیرون، «ذخیره شد» از «ذخیره نشد» قابلِ تفکیک نیست — که دقیقاً همان چیزی
است که این باگ‌ها را ماه‌ها زنده نگه می‌دارد.

تست‌ها **رفتاری**‌اند نه ساختاری: سرورِ واقعیِ aiohttp، POSTِ واقعی، و بعد
خواندنِ همان صفحه‌ای که کاربر می‌بیند. یک assert روی سورس این‌جا بی‌معنا بود،
چون ادعا دربارهٔ چیزی است که به **کاربر** نشان داده می‌شود.

⚠ `"errbox" in body` معیارِ خطا **نیست** — آن رشته در `_CSS` هست و در هر صفحه
تکرار می‌شود، پس همیشه صادق است. اولین نسخهٔ همین پروب دقیقاً همین مثبتِ کاذب
را داد. معیارِ درست `<div class=errbox>` رندرشده است، که `_shows_error` می‌سنجد.
"""
from __future__ import annotations

import pytest


#: نشانهٔ رندرشدهٔ بنرِ خطا (نه کلاسِ CSS، که در هر صفحه هست).
_ERR_MARK = "<div class=errbox>"


def _shows_error(body: str) -> bool:
    return _ERR_MARK in body


def _error_text(body: str) -> str:
    """**محتوای** بنرِ خطا، نه کلِ صفحه.

    تفاوت باربر است: نسخهٔ اولِ `test_..._names_the_button` روی کلِ بدنه assert
    می‌کرد و روی سورسِ **پیش از رفع** هم سبز بود — چون نامِ دکمه به‌هرحال داخلِ
    فرم رندر می‌شود. یعنی تست چیزی را که ادعا می‌کرد نمی‌سنجید. با کنترلِ منفی
    پیدا شد، نه با بازخوانی.
    """
    if _ERR_MARK not in body:
        return ""
    tail = body.split(_ERR_MARK, 1)[1]
    return tail.split("</div>", 1)[0]


def _shows_ok(body: str) -> bool:
    return "<div class=saved>" in body


async def _follow(panel, resp) -> str:
    """ریدایرکتِ نتیجه را دنبال کن و متنِ صفحه‌ای را بده که ادمین می‌بیند."""
    assert resp.status == 302, f"انتظارِ ریدایرکت، دریافت {resp.status}"
    page = await panel.client.get(resp.headers["Location"], cookies=panel.cookies)
    return await page.text()


# ── B-1: /buttons ───────────────────────────────────────────────
async def _first_video_op():
    from app.keyboards import OPS_BY_KIND
    return OPS_BY_KIND["video"][0]


def _default_label(key: str) -> str:
    """پیش‌فرضِ locale — عمداً `t()` نه، چون `t()` **override را برمی‌گرداند**.

    نسخهٔ اولِ این فایل `t()` را صدا می‌زد و تستِ «برابرِ پیش‌فرض = حذف» به
    دلیلِ غلط می‌افتاد: بعد از `set_text` مقدارِ برگشتی خودِ override بود، پس
    تست داشت override را دوباره به خودش می‌فرستاد. همان مسیری که `admin_web`
    می‌رود (`CATALOG`) این‌جا هم باید طی شود.
    """
    from app.i18n import CATALOG
    return CATALOG.get("fa", {}).get(key) or CATALOG["fa"].get(key) or key


def _buttons_form(op: str, text: str, **over) -> dict:
    form = {"kind": "video", "lang": "fa", "order": op,
            f"show_{op}": "on", f"width_{op}": "full", f"text_{op}": text}
    form.update(over)
    return form


async def test_a_rejected_label_does_not_delete_the_healthy_one(panel):
    """B-1: قلبِ ماجرا — متنِ نامعتبر نباید overrideِ سالم را پاک کند."""
    from app import textstore
    op, key = await _first_video_op()
    await textstore.set_text("fa", key, "برچسبِ سالمِ من")
    assert textstore.get_override("fa", key) == "برچسبِ سالمِ من", "پیش‌شرط برقرار نشد"

    r = await panel.client.post("/buttons/save", data=_buttons_form(op, "بد {ناشناخته}"),
                                cookies=panel.cookies, allow_redirects=False)
    await _follow(panel, r)
    assert textstore.get_override("fa", key) == "برچسبِ سالمِ من"


async def test_a_rejected_label_is_reported_not_celebrated(panel):
    """B-1: صفحه باید دلیل را نشان بدهد، نه بنرِ سبز."""
    from app import textstore
    op, key = await _first_video_op()
    await textstore.set_text("fa", key, "برچسبِ سالمِ من")

    r = await panel.client.post("/buttons/save", data=_buttons_form(op, "بد {ناشناخته}"),
                                cookies=panel.cookies, allow_redirects=False)
    body = await _follow(panel, r)
    assert _shows_error(body), "خطا به کاربر گزارش نشد"
    assert not _shows_ok(body), "ذخیره‌ای انجام نشده ولی بنرِ سبز نشان داده شد"


async def test_a_rejected_label_names_the_button(panel):
    """پیام باید بگوید **کدام** دکمه؛ منوی ویدیو ۱۱ کلید دارد."""
    from app import textstore
    op, key = await _first_video_op()
    default = textstore.get_override("fa", key) or None
    assert default is None, "پیش‌شرط: این کلید نباید override داشته باشد"
    label = _default_label(key)

    r = await panel.client.post("/buttons/save", data=_buttons_form(op, "بد {ناشناخته}"),
                                cookies=panel.cookies, allow_redirects=False)
    body = await _follow(panel, r)
    assert label in _error_text(body), f"نامِ دکمه ({label!r}) در پیامِ خطا نیست"


async def test_a_rejected_label_writes_nothing_at_all(panel):
    """اتمیک بودن: چیدمان و رنگ هم نباید نیم‌بند اعمال شوند.

    ادعای مستقلی از دو تستِ بالاست: آن‌ها دربارهٔ **متن**اند، این دربارهٔ اینکه
    یک متنِ بد بقیهٔ فرم را هم متوقف کند. بدونِ این، «ذخیره نشد» و «نصفش ذخیره
    شد» از بیرون یکی به‌نظر می‌رسند.
    """
    from app import textstore
    op, _key = await _first_video_op()
    before_layout = textstore.get_menu_layout("video")
    before_styles = textstore.button_snapshot()

    form = _buttons_form(op, "بد {ناشناخته}", **{f"style_{op}": "danger"})
    r = await panel.client.post("/buttons/save", data=form,
                                cookies=panel.cookies, allow_redirects=False)
    await _follow(panel, r)
    assert textstore.get_menu_layout("video") == before_layout
    assert textstore.button_snapshot() == before_styles


# ── کنترل‌ها: مسیرِ سالم نباید عوض شده باشد ─────────────────────
async def test_a_valid_label_still_saves(panel):
    from app import textstore
    op, key = await _first_video_op()
    r = await panel.client.post("/buttons/save", data=_buttons_form(op, "برچسبِ تازه"),
                                cookies=panel.cookies, allow_redirects=False)
    body = await _follow(panel, r)
    assert textstore.get_override("fa", key) == "برچسبِ تازه"
    assert _shows_ok(body) and not _shows_error(body)


async def test_clearing_the_box_still_removes_the_override(panel):
    """حذفِ **عمدی** باید کار کند — وگرنه رفعِ B-1 راهِ برگشت را بسته است."""
    from app import textstore
    op, key = await _first_video_op()
    await textstore.set_text("fa", key, "برچسبِ سالمِ من")
    r = await panel.client.post("/buttons/save", data=_buttons_form(op, ""),
                                cookies=panel.cookies, allow_redirects=False)
    body = await _follow(panel, r)
    assert textstore.get_override("fa", key) is None
    assert _shows_ok(body)


async def test_a_label_equal_to_the_default_removes_the_override(panel):
    from app import textstore
    op, key = await _first_video_op()
    await textstore.set_text("fa", key, "برچسبِ سالمِ من")
    r = await panel.client.post("/buttons/save", data=_buttons_form(op, _default_label(key)),
                                cookies=panel.cookies, allow_redirects=False)
    await _follow(panel, r)
    assert textstore.get_override("fa", key) is None


# ── B-3/B-4: /save ──────────────────────────────────────────────
def _settings_form(**over) -> dict:
    """فرمِ کاملِ صفحهٔ تنظیمات با مقادیرِ پیش‌فرض، بعد override.

    باید **همهٔ** کلیدهای رندرشده را داشته باشد: هندلر هر کلیدِ غایب را «تهی»
    می‌خواند، پس یک فرمِ ناقص چیزی را می‌سنجد که هیچ مرورگری نمی‌فرستد.
    """
    from app import settings_store as ss
    from app.admin_web import GROUPS
    form: dict[str, str] = {}
    for _title, fields in GROUPS:
        for k, _l, _h in fields:
            kind, default = ss.RUNTIME_KEYS[k]
            if kind == "bool":
                if default:
                    form[k] = "on"
            else:
                form[k] = str(default)
    form.update(over)
    return form


async def _post_settings(panel, **over):
    r = await panel.client.post("/save", data=_settings_form(**over),
                                cookies=panel.cookies, allow_redirects=False)
    return r, await _follow(panel, r)


#: هر مورد: (کلید, مقدارِ فرستاده‌شده, چرا باید رد شود)
_REJECTED = [
    ("max_file_mb", "-1", "negative"),
    ("dl_max_size_mb", "-5", "negative"),
    ("safety_threshold", "9999", "percent over 100"),
    ("ck_warmup_pct", "150", "percent over 100"),
    ("max_file_mb", "5000", "over the Bot API upload ceiling"),
    ("dl_daily_count", "1,000", "thousands separator"),
    ("dl_concurrency", "--5", "isdigit says yes, int() raises"),
    ("rate_per_min", "", "cleared box"),
    ("dl_default_ux", "banana", "not in ENUM_VALUES"),
]


@pytest.mark.parametrize(
    "key,value,why", _REJECTED,
    ids=[f"{k}={v or 'empty'}-{w}".replace(" ", "-") for k, v, w in _REJECTED])
async def test_an_invalid_setting_is_refused_not_swallowed(panel, key, value, why):
    """B-3/B-4: هیچ‌کدام نباید ذخیره شود و هیچ‌کدام نباید بنرِ سبز بگیرد."""
    from app import settings_store as ss
    _r, body = await _post_settings(panel, **{key: value})
    assert _shows_error(body), f"«{value}» ({why}) بی‌صدا دور ریخته شد"
    assert not _shows_ok(body), f"«{value}» ({why}) رد شد ولی بنرِ سبز نشان داده شد"
    assert await ss.get_store().get(key) is None, f"«{value}» ({why}) ذخیره شد"


async def test_a_refused_form_writes_nothing_at_all(panel):
    """اتمیک: یک فیلدِ بد نباید بقیهٔ فرم را نصفه اعمال کند."""
    from app import settings_store as ss
    store = ss.get_store()
    await _post_settings(panel, dl_concurrency="7", max_file_mb="-1")
    assert await store.get("dl_concurrency") is None, "کنارِ یک مقدارِ نامعتبر، بقیه هم نباید بنشیند"


async def test_the_stored_value_is_the_one_the_page_shows(panel):
    """ردیفِ ذخیره‌شده نباید با مقدارِ مؤثر فرق کند.

    `--5` را `isdigit()` قبول می‌کرد ولی `int()` رویش می‌ترکد. اندازه‌گیری روی
    سورسِ پیش از رفع (`f0a3cfe`): ردیف با مقدارِ `'--5'` **نوشته می‌شد**، ولی
    `get_int()` به پیش‌فرض برمی‌گشت (۳) و `_effective()` هم — که همان
    `except ValueError` را دارد — در صفحه ۳ نشان می‌داد.

    یعنی مقدار در دیتابیس می‌نشست و **هیچ‌جا دیده نمی‌شد**: نه اثری داشت نه
    بازتابی، فقط یک ردیفِ زباله و یک بنرِ سبز. نسخهٔ اولِ همین داکس‌استرینگ
    می‌گفت صفحه `--5` را نشان می‌داد؛ غلط بود و با اجرا تصحیح شد، نه با
    بازخوانی.
    """
    from app import settings_store as ss
    store = ss.get_store()
    await _post_settings(panel, dl_concurrency="--5")
    stored = await store.get("dl_concurrency")
    effective = await store.get_int("dl_concurrency", ss.RUNTIME_KEYS["dl_concurrency"][1])
    assert stored is None or int(stored) == effective, (
        f"ذخیره‌شده {stored!r} ولی مقدارِ مؤثر {effective!r} است")


# ── کنترل‌ها ─────────────────────────────────────────────────────
@pytest.mark.parametrize("key,value", [
    ("max_file_mb", "2000"),          # دقیقاً روی سقف
    ("safety_threshold", "100"),      # دقیقاً روی سقفِ درصد
    ("ck_cap_youtube", "0"),          # ۰ = بی‌سقف، معنیِ تثبیت‌شدهٔ پروژه
    ("vjoin_max_mb", "0"),            # ۰ = برگرد به max_file_mb
    ("dl_concurrency", "7"),
], ids=["ceiling", "percent-ceiling", "zero-uncapped", "zero-fallback", "ordinary"])
async def test_a_legal_setting_still_saves(panel, key, value):
    from app import settings_store as ss
    _r, body = await _post_settings(panel, **{key: value})
    assert _shows_ok(body) and not _shows_error(body)
    stored = await ss.get_store().get(key)
    expected = None if value == str(ss.RUNTIME_KEYS[key][1]) else value
    assert stored == expected, f"{key}={value!r} → ذخیره‌شده {stored!r}"


async def test_persian_digits_keep_working(panel):
    """رقمِ فارسی **از قبل** پذیرفته می‌شد و باید بماند.

    اندازه‌گیری‌شده روی سورسِ پیش از رفع: `'۲۰۰۰'.isdigit()` صادق است و
    `int('۲۰۰۰')` هم ۲۰۰۰ می‌دهد، پس این مسیر امروز هم کار می‌کند. سوییچ از
    `isdigit()` به `int()` نباید بشکندش — این تست همان کنترل است.
    """
    from app import settings_store as ss
    _r, body = await _post_settings(panel, rate_per_min="۲۰")
    assert _shows_ok(body) and not _shows_error(body)
    assert await ss.get_store().get_int("rate_per_min", -1) == 20
