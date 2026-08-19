"""`/langs` — چرخهٔ export → چت‌بات → import.

ادعاها روی **رفتار** بسته‌اند نه مارک‌آپ (فازِ بعد قالب‌ها را بازمی‌آراید)، و
مقادیرِ انتظاری از همان توابعی می‌آیند که هندلر صدا می‌زند، نه هاردکد.
"""
from __future__ import annotations

import json

import pytest
from pagefacts import page_text, shows
from test_panel_css_classes import _fetch

from app import langpack as L
from app import textstore


async def _export(panel, lang="es", source="fa", name="Español"):
    r = await panel.client.get(
        f"/langs/export?lang={lang}&source={source}&name={name}", cookies=panel.cookies)
    assert r.status == 200
    return r, json.loads(await r.text())


async def _import(panel, pack, *, lang="es", name="Español", **extra):
    raw = pack if isinstance(pack, str) else json.dumps(pack, ensure_ascii=False)
    data = {"lang": lang, "name": name, "pack": raw, **extra}
    r = await panel.client.post("/langs/import", cookies=panel.cookies, data=data)
    body = await r.text()
    await textstore.load()          # پروسهٔ تست کشِ خودش را دارد
    return r, body


def _translated(pack, prefix="ES "):
    pack["texts"] = {k: prefix + v for k, v in pack["texts"].items()}
    return pack


# ── صفحه ───────────────────────────────────────────────────────
async def test_the_page_lists_every_available_language(panel):
    html = await _fetch(panel, "/langs")
    from app import admin_web as aw

    langs = await aw._languages()
    assert langs, "پیش‌شرط: دستِ‌کم زبان‌های داخلی باید باشند"
    shows(html, *langs.keys(), *langs.values())


async def test_the_page_states_how_many_keys_a_language_still_lacks(panel):
    """پوششْ محاسبه‌شده است نه برچسبِ ثابت — وگرنه هیچ‌وقت خاموش نمی‌شود."""
    _r, pack = await _export(panel)
    pack["texts"] = dict(list(pack["texts"].items())[:50])
    await _import(panel, pack)
    html = await _fetch(panel, "/langs")
    shows(html, f"50/{len(L.TEXT_KEYS)}", f"{50 * 100 // len(L.TEXT_KEYS)}٪")


async def test_a_builtin_language_cannot_be_deleted(panel):
    r = await panel.client.post("/langs/delete", cookies=panel.cookies, data={"code": "fa"})
    shows(await r.text(), "زبانِ داخلی حذف‌شدنی نیست")


async def test_deleting_a_language_takes_its_texts_with_it(panel):
    _r, pack = await _export(panel)
    await _import(panel, _translated(pack))
    assert textstore.lang_texts("es"), "پیش‌شرط: import باید چیزی نوشته باشد"
    await panel.client.post("/langs/delete", cookies=panel.cookies, data={"code": "es"})
    await textstore.load()
    assert textstore.lang_texts("es") == {}
    assert "es" not in await textstore.languages()


# ── export ─────────────────────────────────────────────────────
async def test_the_export_is_a_downloadable_pack_of_every_key(panel):
    r, pack = await _export(panel)
    assert "attachment" in r.headers.get("Content-Disposition", "")
    assert "telabzar-es.json" in r.headers["Content-Disposition"]
    assert set(pack["texts"]) == set(L.TEXT_KEYS)
    assert pack["lang"] == "es" and pack["source"] == "fa"


async def test_the_export_carries_the_admins_own_edits_not_the_code_default(panel):
    """صاحبِ پنل متن‌ها را ویرایش کرده؛ همان‌ها باید ترجمه شوند."""
    key = L.TEXT_KEYS[0]
    await textstore.set_text("fa", key, "متنِ دست‌کاری‌شدهٔ من")
    _r, pack = await _export(panel)
    assert pack["texts"][key] == "متنِ دست‌کاری‌شدهٔ من"


async def test_re_exporting_a_half_translated_language_carries_what_is_done(panel):
    """مبدأ = خودِ همان زبان، پس بسته «کارِ نیمه‌تمام» را می‌دهد نه از صفر.

    کلیدهای ترجمه‌شده اسپانیایی برمی‌گردند و بقیه — طبقِ زنجیرهٔ تازهٔ fallback —
    **انگلیسی**، که دقیقاً همان چیزی است که مدل باید تمامش کند.

    **لینک از خودِ صفحه برداشته می‌شود، نه ساخته.** نسخهٔ اول URL را دستی
    می‌ساخت و سابوتاژِ لینکِ ردیف را **نمی‌گرفت** — یعنی ادعا دربارهٔ هندلر بود
    در حالی که چیزی که ادمین واقعاً می‌زند لینکِ ردیف است. دنبال‌کردنِ همان
    لینک، هر دو نیمه را یک‌جا می‌سنجد.
    """
    import html as _html
    import re

    from app.locales.en import MESSAGES as EN

    _r, pack = await _export(panel)
    done, todo = L.TEXT_KEYS[0], L.TEXT_KEYS[1]
    pack["texts"] = {done: "ES hecho"}
    await _import(panel, pack)

    page = await _fetch(panel, "/langs")
    hrefs = [_html.unescape(h) for h in re.findall(r'href="(/langs/export\?[^"]+)"', page)]
    link = next((h for h in hrefs if "lang=es" in h), None)
    assert link, f"صفحه لینکِ خروجیِ es را نداد؛ لینک‌ها: {hrefs}"

    r = await panel.client.get(link, cookies=panel.cookies)
    again = json.loads(await r.text())
    assert again["texts"][done] == "ES hecho"
    assert again["texts"][todo] == EN[todo]


async def test_an_invalid_code_on_export_is_refused_with_a_reason(panel):
    r = await panel.client.get("/langs/export?lang=espanol", cookies=panel.cookies)
    shows(await r.text(), "کدِ زبانِ نامعتبر")


# ── import: مسیرِ سالم ──────────────────────────────────────────
async def test_a_translated_pack_reaches_the_bot(panel):
    """چرخهٔ کامل: خروجی → «ترجمه» → import → `t()` همان را می‌دهد."""
    from app.i18n import t

    _r, pack = await _export(panel)
    await _import(panel, _translated(pack))
    assert len(textstore.lang_texts("es")) == len(L.TEXT_KEYS)
    assert t("es", "btn_convert").startswith("ES ")
    assert await textstore.languages() == {"es": "Español"}


async def test_a_reply_wrapped_in_a_code_fence_is_accepted(panel):
    """مدل تقریباً همیشه داخلِ ```json می‌گذارد."""
    _r, pack = await _export(panel)
    raw = "```json\n" + json.dumps(_translated(pack), ensure_ascii=False) + "\n```"
    await _import(panel, raw)
    assert len(textstore.lang_texts("es")) == len(L.TEXT_KEYS)


async def test_the_imported_language_becomes_selectable_on_the_other_pages(panel):
    """اگر زبان در `/texts` و `/buttons` دیده نشود، اصلاحش ممکن نیست."""
    _r, pack = await _export(panel)
    await _import(panel, _translated(pack))
    for path in ("/texts?lang=es", "/buttons?lang=es&kind=video"):
        html = await _fetch(panel, path)
        assert "ES " in page_text(html), f"{path} مقدارِ es را رندر نکرد"


async def test_merge_leaves_the_keys_the_pack_does_not_mention(panel):
    """پیش‌فرضِ ادغام: importِ دوم نباید کلیدهای importِ اول را پاک کند."""
    _r, pack = await _export(panel)
    await _import(panel, _translated(pack))
    small = {**pack, "texts": {L.TEXT_KEYS[0]: "SOLO UNO"}}
    await _import(panel, small)
    rows = textstore.lang_texts("es")
    assert len(rows) == len(L.TEXT_KEYS)
    assert rows[L.TEXT_KEYS[0]] == "SOLO UNO"
    assert rows[L.TEXT_KEYS[1]].startswith("ES ")


async def test_replace_drops_the_keys_the_pack_does_not_mention(panel):
    """تیکِ صریح: زبان دقیقاً همان چیزی می‌شود که در فایل است."""
    _r, pack = await _export(panel)
    await _import(panel, _translated(pack))
    small = {**pack, "texts": {L.TEXT_KEYS[0]: "SOLO UNO"}}
    await _import(panel, small, replace="on")
    assert textstore.lang_texts("es") == {L.TEXT_KEYS[0]: "SOLO UNO"}


# ── import: رد ─────────────────────────────────────────────────
async def test_a_rejected_pack_writes_nothing_at_all(panel):
    """اتمیک: یک کلیدِ خراب یعنی **صفر** ردیف، نه ۲۱۳ ردیف."""
    _r, pack = await _export(panel)
    _translated(pack)
    pack["texts"]["welcome"] = "<script>x</script>"
    r, body = await _import(panel, pack)
    assert textstore.lang_texts("es") == {}
    assert await textstore.languages() == {}
    shows(body, "welcome", "هیچ‌چیز نوشته نشد")


async def test_a_rejected_pack_names_every_kind_of_problem(panel):
    _r, pack = await _export(panel)
    src = dict(pack["texts"])
    _translated(pack)
    ph_key = next(k for k in L.TEXT_KEYS if "{" in src[k])
    pack["texts"]["welcome"] = "<b>unclosed"
    pack["texts"][ph_key] = "sin marcador"
    pack["texts"]["definitely_not_a_key"] = "x"
    _r, body = await _import(panel, pack)
    shows(body, "welcome", ph_key, "definitely_not_a_key",
          "بسته‌نشده", "جاافتاده", "ناشناخته")


async def test_a_file_the_model_mangled_says_so(panel):
    _r, body = await _import(panel, "sorry, here is your translation!")
    shows(body, "JSONِ نامعتبر")
    assert textstore.lang_texts("es") == {}


async def test_a_pack_retargeted_by_the_model_is_caught(panel):
    """چت‌بات می‌تواند `lang` را بی‌خبر عوض کند؛ آن‌وقت ترجمه زیرِ زبانِ غلط می‌نشیند."""
    _r, pack = await _export(panel)
    _translated(pack)
    pack["lang"] = "de"
    _r, body = await _import(panel, pack, lang="es")
    shows(body, "یکی نیست")
    assert textstore.lang_texts("es") == {} and textstore.lang_texts("de") == {}


# ── زبانِ پیش‌فرض: تأییدِ صریح ───────────────────────────────────
async def test_importing_over_the_default_language_asks_first(panel):
    from app.i18n import DEFAULT

    _r, pack = await _export(panel, lang=DEFAULT, source=DEFAULT)
    changed = sorted(pack["texts"])[:3]
    for k in changed:
        pack["texts"][k] = "CHANGED " + pack["texts"][k]
    r, body = await _import(panel, pack, lang=DEFAULT, name="فارسی")
    assert textstore.lang_texts(DEFAULT) == {}, "پیش از تأیید نباید چیزی نوشته شود"
    shows(body, "بله، اعمال کن", str(len(changed)))


async def test_the_confirmation_states_what_changes_and_what_does_not(panel):
    from app.i18n import DEFAULT

    _r, pack = await _export(panel, lang=DEFAULT, source=DEFAULT)
    pack["texts"] = dict(list(pack["texts"].items())[:40])
    for k in list(pack["texts"])[:7]:
        pack["texts"][k] = "CHANGED " + pack["texts"][k]
    _r, body = await _import(panel, pack, lang=DEFAULT, name="فارسی")
    # ۷ عوض می‌شود · ۳۳ همان است · بقیه اصلاً در بسته نیست
    shows(body, "7", "33", str(len(L.TEXT_KEYS) - 40))


async def test_the_confirmed_import_writes(panel):
    from app.i18n import DEFAULT

    _r, pack = await _export(panel, lang=DEFAULT, source=DEFAULT)
    pack["texts"] = {k: "CHANGED " + v for k, v in pack["texts"].items()}
    await _import(panel, pack, lang=DEFAULT, name="فارسی", confirm="yes")
    assert len(textstore.lang_texts(DEFAULT)) == len(L.TEXT_KEYS)


async def test_a_non_default_language_needs_no_confirmation(panel):
    """کنترلِ معکوس: تأیید فقط برای زبانِ پیش‌فرض است، نه یک گیتِ سراسری."""
    _r, pack = await _export(panel)
    await _import(panel, _translated(pack))
    assert len(textstore.lang_texts("es")) == len(L.TEXT_KEYS)


@pytest.mark.parametrize("path,method", [
    ("/langs", "get"), ("/langs/export?lang=es", "get"),
    ("/langs/import", "post"), ("/langs/delete", "post"),
])
async def test_every_langs_route_is_behind_the_login_gate(panel, path, method):
    r = await getattr(panel.client, method)(path, allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "/login"
