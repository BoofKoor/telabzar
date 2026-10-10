"""`/langs` — چرخهٔ export → چت‌بات → import.

ادعاها روی **رفتار** بسته‌اند نه مارک‌آپ (فازِ بعد قالب‌ها را بازمی‌آراید)، و
مقادیرِ انتظاری از همان توابعی می‌آیند که هندلر صدا می‌زند، نه هاردکد.
"""
from __future__ import annotations

import json
import pathlib
import re

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


def _f():
    from app.admin_web import Fmt
    return Fmt("fa")


def _row(html: str, code: str) -> str:
    """ردیفِ جدولِ همین زبان — از `<tr>` تا `</tr>`ی که کدش را دارد."""
    at = html.index(f'<bdi class="mono">{code}</bdi>')
    return html[html.rindex("<tr>", 0, at):html.index("</tr>", at)]


async def test_the_page_states_how_many_keys_a_language_still_lacks(panel):
    """پوششْ محاسبه‌شده است نه برچسبِ ثابت — وگرنه هیچ‌وقت خاموش نمی‌شود.

    دو نشانه، هر دو **روی ردیفِ همان زبان**: «۵۰ از ۲۲۳» و پهنای نوار.
    """
    _r, pack = await _export(panel)
    pack["texts"] = dict(list(pack["texts"].items())[:50])
    await _import(panel, pack)
    row = _row(await _fetch(panel, "/langs"), "es")
    f, total = _f(), len(L.TEXT_KEYS)
    shows(row, f.t("c.of", a=f.num(50), b=f.num(total)))
    assert f'style="width:{50 / total * 100:.1f}%"' in row


async def test_a_builtin_language_cannot_be_deleted(panel):
    r = await panel.client.post("/langs/delete", cookies=panel.cookies, data={"code": "fa"})
    shows(await r.text(), _f().t("lng.err.builtin"))
    assert "fa" in await panel.aw._languages()


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
    shows(body, "welcome", _f().t("lng.d.nothing"))


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
    """متنی که هیچ JSONی ندارد. (پیام از ۲۰۲۶-۱۰-۱۰ دقیق‌تر است: «JSONِ نامعتبر» برای
    پاسخی هم گفته می‌شد که JSONِ سالمش فقط یک جملهٔ مقدمه داشت.)"""
    _r, body = await _import(panel, "sorry, here is your translation!")
    shows(body, "هیچ شیءِ JSON")
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
    f = _f()
    shows(body, f.t("lng.d.confirm_btn"), f.t("lng.d.confirm", c=f.num(len(changed))))
    assert '<input type="hidden" name="confirm" value="yes">' in body


async def test_the_confirmation_states_what_changes_and_what_does_not(panel):
    from app.i18n import DEFAULT

    _r, pack = await _export(panel, lang=DEFAULT, source=DEFAULT)
    pack["texts"] = dict(list(pack["texts"].items())[:40])
    for k in list(pack["texts"])[:7]:
        pack["texts"][k] = "CHANGED " + pack["texts"][k]
    _r, body = await _import(panel, pack, lang=DEFAULT, name="فارسی")
    # ۷ عوض می‌شود · ۳۳ همان است · بقیه اصلاً در بسته نیست
    f = _f()
    shows(body, f.t("lng.d.changes", c=f.num(7), s=f.num(33)),
          f.t("lng.d.missing", n=f.num(len(L.TEXT_KEYS) - 40)))


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


# ── «JSONِ خودم را برای انگلیسی اضافه کنم» (گزارشِ اپراتور، ۲۰۲۶-۱۰-۱۰) ──────────
# «خیلی طول کشید و نتوانستم»: پنجره برای یک زبانِ **موجود** هم از فارسی خروجی می‌داد،
# پس اصلاحِ چند متنِ انگلیسی یعنی ترجمهٔ دوبارهٔ هر ۲۸۰ متن با یک چت‌بات؛ و پاسخِ
# چت‌بات به شکل‌های رایجش رد می‌شد (پوششِ `tests/test_langpack.py`)، فقط ۳۰ خطای اول
# دیده می‌شد، و پنجره دربارهٔ کلیدِ ناشناخته و قالبِ فایل حرفِ غلط می‌زد.
_JS = pathlib.Path(__file__).resolve().parents[2] / "app" / "static" / "js" / "panel.js"


def _selected_source(html: str) -> str:
    """زبانی که منوی «زبانِ مبدأ»ِ پنجره انتخاب‌شده رندر می‌کند — دقیقاً یکی."""
    m = re.search(r'<select[^>]*name="source"[^>]*>(.*?)</select>', html, re.S)
    assert m, "منوی زبانِ مبدأ در صفحه نیست"
    picked = re.findall(r'<option value="([^"]+)" selected', m.group(1))
    assert len(picked) == 1, picked
    return picked[0]


async def test_the_dialog_for_an_existing_language_downloads_that_language(panel):
    """پیوندِ «بارگذاری ترجمه»ِ ردیفِ English: «دانلودِ فایل» باید متن‌های **انگلیسیِ**
    فعلی را بدهد تا ادمین فقط همان چند متن را عوض کند — نه هر ۲۸۰ متن را از فارسی."""
    from app.locales.en import MESSAGES as EN

    page = await _fetch(panel, "/langs")
    link = next(h for h in re.findall(r'href="(/langs\?dlg=lng-import&amp;code=[^"]+)"', page)
                if h.endswith("code=en"))
    html = await _fetch(panel, link.replace("&amp;", "&"))
    src = _selected_source(html)
    assert src == "en"
    r = await panel.client.get(f"/langs/export?lang=en&name=English&source={src}", cookies=panel.cookies)
    pack = json.loads(await r.text())
    assert pack["source"] == "en"
    assert pack["texts"]["welcome"] == EN["welcome"]


@pytest.mark.parametrize("query", ["", "&code=xx", "&code=es"], ids=["add", "unknown-code", "not-added-yet"])
async def test_the_dialog_for_a_new_language_still_starts_from_the_default(panel, query):
    """کنترلِ معکوس: زبانِ **تازه** چیزی برای «اصلاح» ندارد و از زبانِ پیش‌فرض ترجمه می‌شود."""
    from app.i18n import DEFAULT

    assert _selected_source(await _fetch(panel, "/langs?dlg=lng-import" + query)) == DEFAULT


async def test_the_row_menu_and_the_add_button_carry_the_source(panel):
    """با JS پنجره از قلاب‌های `data-fill-*` پر می‌شود نه از سرور: ردیف مبدأِ خودش را
    می‌برد، و «افزودنِ زبان» پنجره را خالی و روی زبانِ پیش‌فرض باز می‌کند."""
    from app.i18n import DEFAULT

    html = await _fetch(panel, "/langs")
    assert 'data-fill-source="en"' in _row(html, "en")
    add = re.search(r'<a [^>]*href="/langs\?dlg=lng-import"[^>]*>', html).group(0)
    assert 'data-fill-code=""' in add and 'data-fill-name=""' in add
    assert f'data-fill-source="{DEFAULT}"' in add


def _langs_js() -> str:
    src = _JS.read_text(encoding="utf-8")
    a = src.index("/* ── languages: the import dialog")
    return src[a:src.index("/* ── sign-in code", a)]


async def test_every_hook_the_language_script_reads_is_rendered(panel):
    """نام‌عوض‌کردنِ یک قلاب در قالب خطا نمی‌دهد — فقط اسکریپت بی‌صدا کار نمی‌کند."""
    js = _langs_js()
    fills = set(re.findall(r'data-fill="(\w+)"', js))
    assert {"code", "source"} <= fills, fills               # ضدِتوخالی
    html = await _fetch(panel, "/langs")
    dlg = html[html.index('id="lng-import"'):]
    missing = [f'data-fill="{n}"' for n in fills if f'data-fill="{n}"' not in dlg]
    missing += [a for a in ("data-" + re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), n)
                            for n in re.findall(r"dataset\.(\w+)", js)) if a not in dlg]
    missing += [s for s in re.findall(r'\[(data-dialog="[\w-]+")\]', js) if s not in html]
    assert not missing, f"panel.js این قلاب‌ها را می‌خواند ولی صفحه ندارد: {missing}"
    assert "mountLangs(r);" in _JS.read_text(encoding="utf-8"), "اسکریپت به mount وصل نیست"


@pytest.mark.parametrize("lang,want", [("en", "en"), ("fa", "fa"), ("es", "fa")])
async def test_an_export_without_a_source_comes_from_the_language_itself(panel, lang, want):
    r = await panel.client.get(f"/langs/export?lang={lang}", cookies=panel.cookies)
    assert json.loads(await r.text())["source"] == want


async def test_a_rejected_import_reopens_with_the_same_source(panel):
    _r, pack = await _export(panel, lang="en", source="en", name="English")
    pack["texts"]["welcome"] = "<script>x</script>"
    _r, body = await _import(panel, pack, lang="en", name="English")
    shows(body, _f().t("lng.d.nothing"))
    assert _selected_source(body) == "en"


async def test_a_code_typed_in_capitals_still_reopens_on_that_language(panel):
    """فایلی که اصلاً خوانده نشد کدِ فرم را **خام** پس می‌دهد («EN»)؛ مبدأ باید همان
    انگلیسی باشد — panel.js هم بی‌اعتنا به حروفِ بزرگ می‌سنجد."""
    _r, body = await _import(panel, "this is not json", lang="EN", name="English")
    shows(body, "هیچ شیءِ JSON")
    assert _selected_source(body) == "en"


async def test_every_rejected_key_is_listed_and_copyable(panel):
    """پیش از رفع فقط ۳۰تای اول و یک «…» — هر خطای پنهان یک دورِ دیگر با ابزارِ ترجمه."""
    import html as _html

    _r, pack = await _export(panel)
    _translated(pack)
    keys = sorted(pack["texts"])[:45]
    for k in keys:
        pack["texts"][k] += "<br>"
    _r, body = await _import(panel, pack)
    box = re.search(r"data-lng-errors>(.*?)</div>\s*<div class=\"row", body, re.S)
    assert box, "جعبهٔ خطاها رندر نشد"
    assert set(re.findall(r"<div>([\w]+):", box.group(1))) == set(keys)
    assert "…" not in page_text(box.group(1))
    copy = re.search(r'data-copy="([^"]*)"', body[box.end():])
    assert copy, "دکمهٔ کپیِ فهرست نیست"
    assert {ln.split(":", 1)[0] for ln in _html.unescape(copy.group(1)).splitlines()} == set(keys)


async def test_the_unknown_key_summary_does_not_claim_they_were_ignored(panel):
    """پنجره می‌گفت «N کلید ناشناخته نادیده گرفته شد» و همان کلید کلِ فایل را رد می‌کرد."""
    _r, pack = await _export(panel)
    _translated(pack)
    pack["texts"]["definitely_not_a_key"] = "x"
    _r, body = await _import(panel, pack)
    f = _f()
    shows(body, f.t("lng.d.unknown", n=f.num(1)), f.t("lng.d.nothing"))
    assert "نادیده" not in page_text(body)
    assert textstore.lang_texts("es") == {}


async def test_a_chatbot_reply_with_prose_around_the_file_is_imported(panel):
    _r, pack = await _export(panel)
    _translated(pack)
    raw = ("Here is your translated file:\n\n```json\n" + json.dumps(pack, ensure_ascii=False, indent=2)
           + "\n```\n\nLet me know if you need anything else!")
    r, body = await _import(panel, raw)
    assert r.status == 200 and len(textstore.lang_texts("es")) == len(L.TEXT_KEYS), page_text(body)[:300]


async def test_an_english_file_without_its_envelope_is_checked_against_english(panel):
    """بسته‌ای که پاکتش افتاده `source` ندارد؛ مبدأ **خودِ انگلیسی** است، نه فارسی.

    تمایز این‌طور دیدنی می‌شود: ادمین متنِ **فارسیِ** کلید را ساده کرده (placeholderش را
    انداخته)، پس قراردادِ فارسی همان placeholder را در متنِ انگلیسی «ناشناخته» می‌خواند؛
    قراردادِ انگلیسی نه.
    """
    from app.locales.en import MESSAGES as EN

    key = next(k for k in sorted(L.TEXT_KEYS) if "{" in EN[k] and "<" not in EN[k])
    await textstore.set_text("fa", key, "بدون هیچ نشانه‌ای")
    mine = {key: "Mine: " + EN[key]}
    r, body = await _import(panel, json.dumps(mine, ensure_ascii=False), lang="en", name="English")
    assert textstore.lang_texts("en") == mine, page_text(body)[:400]


async def test_the_paste_box_shows_the_real_format(panel):
    """نمونهٔ کادر قالبی را نشان می‌داد که وجود ندارد (`"format": "telabzar-langpack"`)."""
    html = await _fetch(panel, "/langs?dlg=lng-import")
    box = re.search(r'<textarea[^>]*name="pack"[^>]*>', html).group(0)
    assert "telabzar_i18n" in box and "telabzar-langpack" not in box


async def test_the_language_mismatch_says_how_to_fix_it(panel):
    """خروجیِ ردیفِ «فارسی» که برای en فرستاده شود: رد، با گفتنِ اینکه چه باید کرد."""
    _r, pack = await _export(panel, lang="fa", source="fa", name="فارسی")
    _r, body = await _import(panel, pack, lang="en", name="English")
    shows(body, "یکی نیست", '"lang"', '"en"')
    assert textstore.lang_texts("en") == {}
