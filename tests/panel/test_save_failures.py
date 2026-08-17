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
