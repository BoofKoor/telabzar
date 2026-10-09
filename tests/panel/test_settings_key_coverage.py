"""هر کلیدِ `RUNTIME_KEYS` باید روی صفحهٔ تنظیمات **ورودی** داشته باشد.

`tests/test_settings_rename.test_every_panel_row_is_a_real_runtime_key` جهتِ
دیگر را می‌سنجد (ردیفِ پنل باید کلیدِ واقعی باشد). آن جهت هرگز کافی نبود، و
نتیجه‌اش شش کلیدِ **زنده** بود که از هیچ صفحه‌ای دیده نمی‌شدند:
`proxy_url`, `dl_max_duration_min`, `dl_daily_mb`, `dl_cooldown_sec`,
`dl_op_daily_min`, `dl_min_free_gb` — هر شش‌تا از `settings_store` خوانده
می‌شوند (پس بدونِ ری‌استارت اثر دارند) و از `/admin`ِ تلگرام قابلِ تنظیم بودند.

ادعاها روی **HTMLِ رندرشده**اند نه روی `panel_settings.SECTIONS`: ردیفی که در
فهرست باشد و به ورودی تبدیل نشود همان‌قدر نامرئی است. از بازطراحیِ ۲۰۲۶-۱۰ فرم در
`/settings` است (نه `/`) و به `/settings/save` می‌رود؛ رازها (`secret`) با مقدارِ
**خالی** رندر می‌شوند و یک تیکِ `clear__<کلید>` کنارشان دارند.
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
    """نامِ هر ورودیِ فرمِ تنظیمات — input/select/textarea — بدونِ تیکِ «پاک کن»ِ رازها."""
    form = re.search(r'<form[^>]*action="/settings/save"[^>]*>(.*?)</form>', html, re.S)
    assert form, "فرمِ /settings/save در صفحه پیدا نشد"
    names = set(re.findall(r'<(?:input|select|textarea)[^>]*name="([^"]+)"', form.group(1)))
    return {n for n in names if not n.startswith("clear__")}


async def _settings_html(panel) -> str:
    resp = await panel.client.get("/settings", cookies=panel.cookies)
    assert resp.status == 200
    return await resp.text()


def _payload(fields: set[str]) -> dict:
    """فرم را همان‌طور که مرورگر می‌فرستد بازتولید کن: هر ورودیِ رندرشده با پیش‌فرضش.

    رازِ خالی یعنی «دست نزن» (`save()`)، پس رازها اصلاً فرستاده نمی‌شوند.
    """
    from app import panel_settings as PS

    secret = {f["k"] for f in PS.fields() if f["type"] in PS.SECRET_TYPES}
    return {k: ("on" if RUNTIME_KEYS[k][0] == "bool" else str(RUNTIME_KEYS[k][1]))
            for k in fields if k not in secret
            and not (RUNTIME_KEYS[k][0] == "bool" and not RUNTIME_KEYS[k][1])}


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
    from app.admin_web import Fmt
    # عدد در پنلِ فارسی با رقمِ فارسی رندر می‌شود (`Fmt.digits`) و `save()` نرمالش می‌کند.
    assert f'name="zz_a_key_from_the_future" value="{Fmt("fa").digits(7)}"' in html


async def test_the_auto_row_says_it_needs_a_label(panel, monkeypatch):
    """گروهِ خودکار باید در **UI** نق بزند، وگرنه کلید بی‌صدا بی‌برچسب می‌ماند."""
    from app.panel_i18n import pt

    monkeypatch.setitem(RUNTIME_KEYS, "zz_a_key_from_the_future", ("int", 7))
    html = await _settings_html(panel)
    assert pt("fa", "st.auto.h") in html, "ردیفِ خودکار نمی‌گوید برچسب ندارد"


async def test_the_auto_group_is_absent_when_every_key_has_a_label(panel):
    """کنترلِ معکوس: امروز همه‌چیز دسته‌بندی شده، پس گروهِ خودکار نباید بیاید."""
    from app import admin_web as aw
    from app.panel_i18n import pt

    assert aw._settings_auto_keys() == [], f"کلیدِ بی‌دسته: {aw._settings_auto_keys()}"
    assert pt("fa", "st.auto.h") not in await _settings_html(panel)


async def test_a_value_typed_into_an_auto_rendered_row_actually_saves(panel, monkeypatch):
    """رندر بدونِ ذخیره یعنی «بنرِ سبز روی کاری که انجام نشد».

    `save()` مجموعهٔ `rendered` را از همان تابعی می‌سازد که صفحه از آن رندر شد؛
    اگر یکی `GROUPS`ِ خام بخواند و دیگری تابع را، ردیفِ خودکار دیده می‌شود و
    مقدارش بی‌صدا دور ریخته می‌شود.
    """
    from app import settings_store

    monkeypatch.setitem(RUNTIME_KEYS, "zz_a_key_from_the_future", ("int", 7))
    payload = _payload(form_fields(await _settings_html(panel)))
    payload["zz_a_key_from_the_future"] = "42"
    resp = await panel.client.post("/settings/save", data=payload, cookies=panel.cookies,
                                   allow_redirects=False)
    assert resp.status == 302, await resp.text()
    assert "err=" not in resp.headers["Location"], resp.headers["Location"]
    assert await settings_store.get_int("zz_a_key_from_the_future", 7) == 42


async def test_saving_still_works_for_a_hand_labelled_key(panel):
    """کنترل: مسیرِ ذخیرهٔ عادی نشکسته باشد — و یکی از همان شش‌تا را می‌زند."""
    from app import settings_store

    payload = _payload(form_fields(await _settings_html(panel)))
    payload["dl_min_free_gb"] = "9"
    resp = await panel.client.post("/settings/save", data=payload, cookies=panel.cookies,
                                   allow_redirects=False)
    assert resp.status == 302 and "err=" not in resp.headers["Location"]
    assert await settings_store.get_int("dl_min_free_gb", 0) == 9


# ── رازها ────────────────────────────────────────────────────────────────
async def test_a_stored_secret_never_reaches_the_html(panel):
    """`secret` با مقدارِ خالی رندر می‌شود؛ فقط «تنظیم شده» گفته می‌شود، نه خودِ مقدار."""
    from app import settings_store
    from app.panel_i18n import pt

    value = "SECRET-VALUE-4417"
    await settings_store.get_store().set("spotify_client_secret", value)
    html = await _settings_html(panel)
    assert value not in html
    assert pt("fa", "st.secret.set") in html, "صفحه نمی‌گوید راز تنظیم شده"


async def test_an_empty_secret_box_keeps_the_stored_secret(panel):
    """جعبهٔ خالی یعنی «دست نزن» — وگرنه هر ذخیرهٔ فرم رازها را پاک می‌کرد."""
    from app import settings_store

    await settings_store.get_store().set("spotify_client_secret", "KEEP-ME")
    payload = _payload(form_fields(await _settings_html(panel)))
    resp = await panel.client.post("/settings/save", data={**payload, "spotify_client_secret": ""},
                                   cookies=panel.cookies, allow_redirects=False)
    assert resp.status == 302 and "err=" not in resp.headers["Location"]
    assert await settings_store.get_str("spotify_client_secret", "") == "KEEP-ME"


async def test_the_clear_box_really_clears_a_secret(panel):
    """کنترلِ معکوس: پاک‌کردن ممکن است، ولی فقط با تیکِ صریح."""
    from app import settings_store

    await settings_store.get_store().set("spotify_client_secret", "DROP-ME")
    payload = _payload(form_fields(await _settings_html(panel)))
    resp = await panel.client.post("/settings/save",
                                   data={**payload, "clear__spotify_client_secret": "on"},
                                   cookies=panel.cookies, allow_redirects=False)
    assert resp.status == 302 and "err=" not in resp.headers["Location"]
    assert await settings_store.get_str("spotify_client_secret", "") == ""
