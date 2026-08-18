"""هر کلیدِ `RUNTIME_KEYS` باید روی صفحهٔ تنظیمات **ورودی** داشته باشد.

`tests/test_settings_rename.test_every_panel_row_is_a_real_runtime_key` جهتِ
دیگر را می‌سنجد (ردیفِ پنل باید کلیدِ واقعی باشد). آن جهت هرگز کافی نبود، و
نتیجه‌اش شش کلیدِ **زنده** بود که از هیچ صفحه‌ای دیده نمی‌شدند:
`proxy_url`, `dl_max_duration_min`, `dl_daily_mb`, `dl_cooldown_sec`,
`dl_op_daily_min`, `dl_min_free_gb` — هر شش‌تا از `settings_store` خوانده
می‌شوند (پس بدونِ ری‌استارت اثر دارند) و از `/admin`ِ تلگرام قابلِ تنظیم بودند.

ادعاها روی **HTMLِ رندرشده**اند نه روی `GROUPS`: ردیفی که در فهرست باشد و به
ورودی تبدیل نشود همان‌قدر نامرئی است.
"""
from __future__ import annotations

import re

from app.settings_store import RUNTIME_KEYS

#: شش کلیدی که این PR پیدایشان کرد. فهرست عمداً **صریح** است: گاردِ عامِ زیرش
#: از رگرسیونِ عمومی محافظت می‌کند، ولی این یکی مشخصاً می‌گوید همان شش‌تا
#: برنگردند — و اگر کسی ردیفشان را پاک کند، پیامِ شکست نامشان را می‌برد.
REPORTED_MISSING = ("proxy_url", "dl_max_duration_min", "dl_daily_mb",
                    "dl_cooldown_sec", "dl_op_daily_min", "dl_min_free_gb")


def form_fields(html: str) -> set[str]:
    """نامِ هر ورودیِ فرمِ تنظیمات — input/select/textarea."""
    form = re.search(r'<form[^>]*action=/save[^>]*>(.*?)</form>', html, re.S)
    assert form, "فرمِ /save در صفحه پیدا نشد"
    return set(re.findall(r'<(?:input|select|textarea)[^>]*name="([^"]+)"', form.group(1)))


async def _settings_html(panel) -> str:
    resp = await panel.client.get("/", cookies=panel.cookies)
    assert resp.status == 200
    return await resp.text()


async def test_every_runtime_key_has_an_input_on_the_settings_page(panel):
    fields = form_fields(await _settings_html(panel))
    assert len(fields) >= 60, f"فقط {len(fields)} ورودی رندر شد — فرم واقعاً ساخته نشد؟"
    missing = sorted(set(RUNTIME_KEYS) - fields)
    assert not missing, (
        f"این کلیدها زنده‌اند ولی هیچ ورودی‌ای در پنل ندارند: {missing} — "
        f"از `/admin`ِ تلگرام قابلِ تنظیم‌اند و از پنل نه.")


async def test_the_six_reported_keys_are_on_the_page(panel):
    fields = form_fields(await _settings_html(panel))
    for key in REPORTED_MISSING:
        assert key in fields, f"«{key}» دوباره از صفحهٔ تنظیمات افتاد"


async def test_the_page_does_not_render_a_key_that_cannot_be_saved(panel):
    """جهتِ معکوس، روی رندر: ورودی‌ای که `RUNTIME_KEYS` نشناسد ذخیره نمی‌شود.

    `save()` مقدارش را به `validate_value` می‌دهد که برای کلیدِ ناشناخته خطا
    می‌سازد، پس چنین ردیفی کلِ فرم را می‌شکند — نه فقط بی‌اثر است.
    """
    assert not (form_fields(await _settings_html(panel)) - set(RUNTIME_KEYS))


# ── دوام: کلیدِ بعدی خودکار بیاید، نه با ویرایشِ یک فهرستِ دستیِ دیگر ─────────
async def test_a_brand_new_runtime_key_shows_up_without_touching_the_panel(panel, monkeypatch):
    """اثباتِ اینکه رفع «شش ردیفِ دستی» نیست.

    اگر گروهِ خودکار برداشته شود، شش ردیفِ دست‌نویس همچنان سرِ جایشان‌اند و
    `test_every_runtime_key_has_an_input…` **سبز می‌ماند** — پس فقط این تست
    است که دوام را می‌سنجد، و سابوتاژِ متناظر عمداً همین را هدف می‌گیرد.
    """
    monkeypatch.setitem(RUNTIME_KEYS, "zz_a_key_from_the_future", ("int", 7))
    html = await _settings_html(panel)
    assert "zz_a_key_from_the_future" in form_fields(html)
    assert str(7) in html


async def test_the_auto_row_says_it_needs_a_label(panel, monkeypatch):
    """گروهِ خودکار باید در **UI** نق بزند، وگرنه کلید بی‌صدا بی‌برچسب می‌ماند."""
    from app import admin_web as aw

    monkeypatch.setitem(RUNTIME_KEYS, "zz_a_key_from_the_future", ("int", 7))
    html = await _settings_html(panel)
    assert aw._AUTO_GROUP in html and aw._AUTO_HINT in html


async def test_the_auto_group_is_absent_when_every_key_has_a_label(panel):
    """کنترلِ معکوس: امروز همه‌چیز دسته‌بندی شده، پس گروهِ خودکار نباید بیاید."""
    from app import admin_web as aw

    assert aw._AUTO_GROUP not in await _settings_html(panel)


async def test_a_value_typed_into_an_auto_rendered_row_actually_saves(panel, monkeypatch):
    """رندر بدونِ ذخیره یعنی «بنرِ سبز روی کاری که انجام نشد».

    `save()` مجموعهٔ `rendered` را از همان تابعی می‌سازد که صفحه از آن رندر شد؛
    اگر یکی `GROUPS`ِ خام بخواند و دیگری تابع را، ردیفِ خودکار دیده می‌شود و
    مقدارش بی‌صدا دور ریخته می‌شود.
    """
    from app import settings_store

    monkeypatch.setitem(RUNTIME_KEYS, "zz_a_key_from_the_future", ("int", 7))
    fields = form_fields(await _settings_html(panel))
    # فرم را همان‌طور که مرورگر می‌فرستد بازتولید کن: هر ورودیِ رندرشده.
    payload = {k: ("on" if RUNTIME_KEYS[k][0] == "bool" else str(RUNTIME_KEYS[k][1]))
               for k in fields}
    payload["zz_a_key_from_the_future"] = "42"
    resp = await panel.client.post("/save", data=payload, cookies=panel.cookies,
                                   allow_redirects=False)
    assert resp.status == 302, await resp.text()
    assert "err=" not in resp.headers["Location"], resp.headers["Location"]
    assert await settings_store.get_int("zz_a_key_from_the_future", 7) == 42


async def test_saving_still_works_for_a_hand_labelled_key(panel):
    """کنترل: مسیرِ ذخیرهٔ عادی نشکسته باشد — و یکی از همان شش‌تا را می‌زند."""
    from app import settings_store

    fields = form_fields(await _settings_html(panel))
    payload = {k: ("on" if RUNTIME_KEYS[k][0] == "bool" else str(RUNTIME_KEYS[k][1]))
               for k in fields}
    payload["dl_min_free_gb"] = "9"
    resp = await panel.client.post("/save", data=payload, cookies=panel.cookies,
                                   allow_redirects=False)
    assert resp.status == 302 and "err=" not in resp.headers["Location"]
    assert await settings_store.get_int("dl_min_free_gb", 0) == 9
