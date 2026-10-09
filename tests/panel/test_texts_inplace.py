"""`/texts` بی رفرش — قراردادی که ذخیره و فیلترِ درجای `panel.js` رویش بنا شده.

گزارشِ ادمین: «موقعِ ذخیره اسکرولِ الکی و رفرش داریم». اندازه‌گیری در مرورگرِ واقعی
(Playwright روی همین پنل) پنج باگ داد که هر پنج تا از یک ریشه بودند — هر کاری صفحه را
از نو می‌ساخت: (۱) ذخیره و «برگرداندن» ریدایرکت می‌کردند و صفحه به بالا می‌پرید؛
(۲) ردِ اعتبارسنجی متنِ تایپ‌شده را دور می‌ریخت و خطا را در بنرِ بالای صفحه می‌گفت؛
(۳) کلیک روی تراشهٔ دسته ویرایشِ ذخیره‌نشده را بی‌صدا از بین می‌برد؛ (۴) «برگرداندن»ِ
یک متن ویرایش‌های ذخیره‌نشدهٔ بقیه را می‌برد؛ (۵) «انصراف» خطای placeholder را جا
می‌گذاشت و دکمهٔ ذخیره قفل می‌ماند. به‌علاوه پنلِ انگلیسی خطای اعتبارسنجی را فارسی
می‌دید و جعبه‌ها بعد از تغییرِ عرضِ پنجره بریده می‌شدند.

رفتارِ مرورگر در CI سنجیدنی نیست (مرورگری نیست)؛ آن را Playwright در طولِ کار سنجید.
این‌جا چیزی قفل می‌شود که آن رفتار به آن تکیه دارد: پاسخِ JSONِ `texts_save` (ذخیره،
رد با خطای هر کلید، نشستِ منقضی بی‌ریدایرکت، برگرداندن از همان مسیر)، و این‌که هر
قلابی که `panel.js` می‌خواند واقعاً رندر شود — نام‌عوض‌کردنِ یک `data-tx-*` در قالب
خطا نمی‌دهد، فقط اسکریپت بی‌صدا از کار می‌افتد.
"""
from __future__ import annotations

import pathlib
import re

from test_admin_log import _rows
from test_panel_css_classes import _fetch

ROOT = pathlib.Path(__file__).resolve().parents[2]
JS = ROOT / "app" / "static" / "js" / "panel.js"
JSON_ACCEPT = {"Accept": "application/json"}


def _plain_key() -> str:
    """کلیدی که پیش‌فرضش نه placeholder دارد نه HTML — کشف‌شده، نه هاردکد."""
    from app import langpack
    from app.i18n import default_text

    return next(k for k in sorted(langpack.TEXT_KEYS)
                if not any(c in default_text("fa", k) for c in "{<\n"))


def _two_plain_keys() -> tuple[str, str]:
    from app import langpack
    from app.i18n import default_text

    keys = [k for k in sorted(langpack.TEXT_KEYS) if not any(c in default_text("fa", k) for c in "{<\n")]
    return keys[0], keys[1]


async def _save(panel, data: dict, *, cookies=None, lang: str | None = None):
    jar = dict(panel.cookies if cookies is None else cookies)
    if lang:
        jar["tab_lang"] = lang
    r = await panel.client.post("/texts/save", data=data, cookies=jar, headers=JSON_ACCEPT,
                                allow_redirects=False)
    return r, await r.json()


# ── پاسخِ JSON ────────────────────────────────────────────────────────────────
async def test_a_fetch_save_answers_with_the_saved_rows(panel):
    """ردیف‌ها درجا به‌روز می‌شوند، پس پاسخ باید **مقدارِ ذخیره‌شده** را بدهد، نه فقط «باشه»."""
    from app import textstore
    from app.i18n import default_text
    from app.panel_i18n import pt

    key = _plain_key()
    r, j = await _save(panel, {"lang": "fa", f"v:{key}": "متنِ تازه"})
    assert r.status == 200, j
    assert j["ok"] is True and j["msg"] == pt("fa", "tx.saved.one")
    assert j["saved"] == {key: {"value": "متنِ تازه", "edited": True, "default": default_text("fa", key)}}
    assert j["n_edited"] == 1 and j["n_edited_t"] == "۱"
    assert "۱" in j["sub"]
    assert textstore.get_override("fa", key) == "متنِ تازه"
    assert [(x.target, x.detail) for x in await _rows(panel, "text_save")] == [(key, {"lang": "fa", "n": 1})]


async def test_a_refused_fetch_save_writes_nothing_and_names_each_key(panel):
    """اتمیک: یک متنِ نامعتبر یعنی هیچ‌کدام — و خطا به **کلیدِ خودش** می‌رسد، نه بنرِ کلی."""
    from app import textstore
    from app.panel_i18n import pt

    good, bad = _two_plain_keys()
    r, j = await _save(panel, {"lang": "fa", f"v:{good}": "درست", f"v:{bad}": "با <div>تگ</div>"})
    assert r.status == 400, j
    assert j["ok"] is False and set(j["errors"]) == {bad}
    assert "<div>" in j["errors"][bad]
    assert j["msg"] == pt("fa", "tx.err.n", n="۱")
    assert textstore.get_override("fa", good) is None and textstore.get_override("fa", bad) is None
    assert await _rows(panel, "text_save") == []


async def test_the_refusal_speaks_the_panel_language(panel):
    """پنلِ انگلیسی خطای ذخیره را فارسی می‌دید — `validate` حالا زبانِ پنل را می‌گیرد."""
    key = _plain_key()
    _r, j = await _save(panel, {"lang": "fa", f"v:{key}": "x <div>y</div>"}, lang="en")
    assert j["errors"][key].startswith("Tag not allowed"), j
    assert j["msg"].startswith("Not saved"), j
    _r, j = await _save(panel, {"lang": "fa", f"v:{key}": "x <div>y</div>"}, lang="fa")
    assert j["errors"][key].startswith("تگِ غیرمجاز"), j


async def test_an_expired_session_gets_401_json_not_the_login_page(panel):
    """fetch ریدایرکت را دنبال می‌کند: بی این، صفحهٔ ورود با ۲۰۰ برمی‌گشت و ویرایش‌ها
    بی‌دلیلِ گفته‌شده ذخیره نمی‌شدند. فرمِ معمولی (بی JS) همچنان به `/login` می‌رود."""
    from app import textstore

    key = _plain_key()
    r, j = await _save(panel, {"lang": "fa", f"v:{key}": "بعداً"}, cookies={})
    assert r.status == 401 and j["login"] is True and j["msg"], j
    assert textstore.get_override("fa", key) is None
    plain = await panel.client.post("/texts/save", data={"lang": "fa", f"v:{key}": "بعداً"},
                                    allow_redirects=False)
    assert plain.status == 302 and plain.headers["Location"].startswith("/login")


async def test_restoring_through_save_clears_the_override_and_logs_a_reset(panel):
    """«برگرداندن» با JS از همین مسیر می‌رود (مقدار = پیش‌فرض)؛ لاگ باید آن را «برگرداندن»
    بنویسد نه «ویرایش» — و ویرایشِ ذخیره‌نشدهٔ بقیهٔ ردیف‌ها اصلاً فرستاده نمی‌شود."""
    from app import textstore
    from app.i18n import default_text
    from app.panel_i18n import pt

    key = _plain_key()
    await textstore.set_text("fa", key, "موقت")
    r, j = await _save(panel, {"lang": "fa", f"v:{key}": default_text("fa", key)})
    assert r.status == 200 and j["msg"] == pt("fa", "tx.reset.ok"), j
    assert j["saved"][key] == {"value": default_text("fa", key), "edited": False,
                               "default": default_text("fa", key)}
    assert textstore.get_override("fa", key) is None
    assert [(x.target, x.detail) for x in await _rows(panel, "text_reset")] == [(key, {"lang": "fa", "n": 1})]
    assert await _rows(panel, "text_save") == []


async def test_saving_what_is_already_saved_says_so(panel):
    """بنرِ سبز روی کاری که انجام نشد همان چیزی است که §۷ چهار بار ثبت کرده."""
    from app.panel_i18n import pt

    key = _plain_key()
    from app.i18n import default_text
    _r, j = await _save(panel, {"lang": "fa", f"v:{key}": default_text("fa", key)})
    assert j["ok"] is True and j["msg"] == pt("fa", "tx.saved.none"), j
    assert await _rows(panel, "text_reset") == [] and await _rows(panel, "text_save") == []


async def test_an_unknown_language_is_refused_in_json_too(panel):
    from app.panel_i18n import pt

    r, j = await _save(panel, {"lang": "xx", "v:start": "x"})
    assert r.status == 400 and j["ok"] is False and j["msg"] == pt("fa", "tx.err.lang", l="xx"), j


# ── قلاب‌های `panel.js` ───────────────────────────────────────────────────────
def _texts_js() -> str:
    src = JS.read_text(encoding="utf-8")
    a = src.index("/* ── texts page ──")
    return src[a:src.index("/* ── button editor", a)]


def test_the_texts_script_is_found_and_reads_hooks():
    """ضدِتوخالی: اگر بخشِ اسکریپت پیدا نشود یا قلابی نخواند، تستِ بعدی چیزی نمی‌سنجد."""
    hooks = set(re.findall(r"data-tx-[a-z-]+", _texts_js()))
    assert len(hooks) >= 12, hooks


async def test_every_hook_the_texts_script_reads_is_rendered(panel):
    """هر `data-tx-*` و هر `#id`ی که اسکریپت می‌خواند باید در صفحه باشد.

    روی صفحه‌ای که یک ردیفِ ویرایش‌شده دارد (جعبهٔ پیش‌فرض و دکمهٔ برگرداندن فقط
    همان‌جا رندر می‌شوند). camelCaseِ `dataset` هم به شکلِ ویژگی برگردانده می‌شود.
    """
    from app import textstore

    await textstore.set_text("fa", _plain_key(), "ویرایش‌شده")
    html = await _fetch(panel, "/texts")
    js = _texts_js()
    hooks = set(re.findall(r"data-tx-[a-z-]+", js))
    hooks |= {"data-" + re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), n)
              for n in re.findall(r"dataset\.(tx[A-Z]\w*)", js)}
    ids = set(re.findall(r"#(tx-[a-z-]+)", js))
    missing = sorted(h for h in hooks if not re.search(rf"\s{re.escape(h)}(?=[\s=>])", html))
    missing += sorted(f"#{i}" for i in ids if f'id="{i}"' not in html)
    assert not missing, f"panel.js این قلاب‌ها را می‌خواند ولی صفحه ندارد: {missing}"


def _between(html: str, start: str, end: str) -> str:
    a = html.index(start)
    return html[a:html.index(end, a) + len(end)]


async def test_the_template_row_parts_match_the_server_markup(panel):
    """ردیفی که تازه «ویرایش‌شده» می‌شود نشان و جعبهٔ پیش‌فرض را از `#tx-tpl` می‌گیرد؛
    باید دقیقاً همان مارک‌آپی باشد که سرور برای ردیفِ ویرایش‌شده می‌سازد، وگرنه ردیفِ
    ذخیره‌شده تا رفرشِ بعدی شکلِ دیگری دارد."""
    from app import textstore
    from app.i18n import default_text

    key = _plain_key()
    await textstore.set_text("fa", key, "ویرایش‌شده")
    html = await _fetch(panel, "/texts")
    tpl = _between(html, '<template id="tx-tpl">', "</template>")
    at = html.index(f'data-f="{key}"')
    row = html[at:html.index('<div class="txt-row', at)]
    pill = _between(row, "<span class=\"pill", "</span>")
    assert pill in tpl
    box = _between(row, '<div class="tx-def"', "</button></div>")
    box = box.replace(f'value="{key}"', 'value=""').replace(f">{default_text('fa', key)}</div>", "></div>")
    assert box in tpl, (box, tpl)


def test_the_in_place_filter_folds_like_the_server():
    """فیلترِ درجا و فیلترِ سمتِ سرور (بی JS) باید یک جواب بدهند: «میشود» «می‌شود» را
    پیدا کند و «كتاب»ِ عربی «کتاب» را. `fold`ِ JS این‌جا با همان قاعده‌های خودش اجرا
    می‌شود و با `admin_web._fold` مقایسه."""
    from app import admin_web as aw

    line = next(x for x in _texts_js().splitlines() if "const fold" in x)
    steps = re.findall(r"\.replace\(/(.+?)/g, '([^']*)'\)", line)
    assert len(steps) >= 3 and "toLowerCase()" in line, line

    def js_fold(s: str) -> str:
        s = s.lower()
        for pat, rep in steps:
            s = re.sub(pat, rep, s)
        return s

    for probe in ("ABC يى ك", "می‌شود", "x‍y‎‏z", "كتاب Mixed ي", "plain متن"):
        assert js_fold(probe) == aw._fold(probe), probe
