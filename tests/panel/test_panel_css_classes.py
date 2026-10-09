"""هر کلاسی که پنل **رندر می‌کند** باید یا قاعدهٔ CSS داشته باشد یا قلابِ JS باشد.

کلاسِ تعریف‌نشده خطا نمی‌دهد — بی‌صدا به یک عنصرِ بی‌استایل تبدیل می‌شود. پنلِ
قدیم سه بار همین را شیپ کرد (`.pad`/`.hint`/`.tabs`، بعد `.err`/`.mute`/
`.s-unproven`)، و دو تای آخری دقیقاً روی دو وضعیتی می‌نشستند که دخالتِ انسان
می‌خواهند. پس گارد **کشف‌محور** است: هر صفحهٔ GET (به‌علاوهٔ دیالوگ‌ها، برگه‌ها و
فیلترها) با داده رندر می‌شود و هر کلاسِ خروجی با استایل‌شیتِ **پیوندشدهٔ همان
پاسخ** تطبیق داده می‌شود.

**از بازطراحیِ ۲۰۲۶-۱۰ استایل درون‌خطی نیست**: `base.html` فایلِ
`/static/css/panel.css?v=<هش>` را لینک می‌کند. گارد همان فایلی را می‌خواند که صفحه
لینک کرده (از روی `href`)، نه یک مسیرِ هاردکد — وگرنه اگر صفحه روزی فایلِ دیگری
لینک کند، گارد فایلِ اشتباه را می‌سنجد و سبز می‌ماند.

**قلابِ JS** کلاسی است که عمداً استایل ندارد و `panel.js` با سلکتور پیدایش می‌کند
(`js-clear-err`، `otp-fallback`، …). معیارش هم کشف‌محور است: نامِ کلاس باید در یک
**رشتهٔ سلکتورِ** `panel.js` بیاید. کلاسی که نه قاعده دارد نه JS دنبالش می‌گردد،
همان کلاسِ مرده است.

دو قیدِ اندازه‌گیری‌شده:

* `/login` باید **بدونِ کوکی** گرفته شود؛ با کوکیِ ادمین به `/` ریدایرکت می‌شود و
  تست بی‌خبر داشبورد را دوباره می‌سنجد.
* صفحه باید **داده** داشته باشد (`seeded`) — `/cookies`ِ بی‌اکانت هیچ پیلی
  رندر نمی‌کند و گارد دربارهٔ آن شاخه‌ها هیچ نمی‌گوید.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js" / "panel.js"

#: هر صفحهٔ GET، به‌علاوهٔ حالت‌هایی که شاخهٔ دیگری از قالب را رندر می‌کنند.
PAGES = (
    "/", "/?r=90d", "/activity", "/activity?tab=ops", "/activity?tab=log",
    "/activity?tab=dl&st=fail", "/reports", "/reports?r=all", "/users", "/users?st=blocked",
    "/cookies", "/cookies?dlg=ck-add", "/nodes", "/nodes?dlg=nd-add", "/system",
    "/texts", "/texts?edited=1", "/buttons", "/buttons?kind=audio", "/langs",
    "/langs?dlg=lng-import", "/settings", "/settings?q=proxy", "/search?q=se", "/search",
)

_CLASS_ATTR_Q = re.compile(r'class="([^"]*)"')
_CLASS_ATTR_BARE = re.compile(r"class=([A-Za-z][\w-]*)")
_STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
_LINKED_CSS = re.compile(r'<link rel="stylesheet" href="(/static/[^"?]+)(?:\?[^"]*)?"')
_CSS_CLASS = re.compile(r"\.([A-Za-z][\w-]*)")
#: کامنتِ CSS **قاعده نیست** — §۶: هر گاردی که متن اسکن می‌کند سرانجام
#: توضیحاتِ خودش را می‌خواند. این گارد یک‌بار دقیقاً همین‌طور کور شد.
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_JS_STRING = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`", re.S)
_JS_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\\'\"])//[^\n]*", re.S)
#: سلکتورِ کلاس داخلِ یک رشتهٔ JS: `.name` (و `tag.name`). پیش از نقطه رقم
#: نیامده باشد («1.5» سلکتور نیست). رشته‌ای مثلِ «panel.css» هم «css» را قلاب
#: می‌شمارد — بی‌ضرر، چون فقط مجموعهٔ معاف را بزرگ‌تر می‌کند.
_SELECTOR_CLASS = re.compile(r"(?<!\d)\.([A-Za-z][\w-]*)")


def classes_used(html: str) -> set[str]:
    """کلاس‌های واقعاً رندرشده — هر دو شکلِ `class="a b"` و `class=a`."""
    out: set[str] = set()
    for m in _CLASS_ATTR_Q.finditer(html):
        out |= {c for c in m.group(1).split() if c and "{" not in c}
    out |= {m.group(1) for m in _CLASS_ATTR_BARE.finditer(html)}
    return out


def stylesheet(html: str, *, read=lambda rel: (STATIC / rel).read_text(encoding="utf-8")) -> str:
    """استایلِ خودِ همین پاسخ — `<style>`ها **و** فایل‌هایی که لینک کرده — بدونِ کامنت."""
    parts = _STYLE_BLOCK.findall(html)
    for href in _LINKED_CSS.findall(html):
        parts.append(read(href.removeprefix("/static/")))
    return _CSS_COMMENT.sub(" ", "\n".join(parts))


def js_hooks(src: str | None = None) -> set[str]:
    """کلاس‌هایی که `panel.js` در **رشتهٔ سلکتور** دنبالشان می‌گردد."""
    src = JS.read_text(encoding="utf-8") if src is None else src
    src = _JS_COMMENT.sub(" ", src)
    out: set[str] = set()
    for lit in _JS_STRING.findall(src):
        # `${…}` داخلِ template literal کدِ JS است نه سلکتور (`${x.dataset}`)
        body = re.sub(r"\$\{[^}]*\}", " ", lit[1:-1])
        out |= set(_SELECTOR_CLASS.findall(body))
    return out


def classes_defined(html: str) -> set[str]:
    return set(_CSS_CLASS.findall(stylesheet(html)))


def undefined_in(html: str, hooks: set[str] | None = None) -> list[str]:
    hooks = js_hooks() if hooks is None else hooks
    return sorted(classes_used(html) - classes_defined(html) - hooks)


async def _fetch(panel, path: str) -> str:
    resp = await panel.client.get(path, cookies=panel.cookies)
    assert resp.status == 200, f"{path} → HTTP {resp.status}"
    return await resp.text()


# ── کنترل‌های منفی: اول ثابت کن این چک اصلاً می‌تواند بیفتد ──────────────────
def test_the_checker_reports_a_class_that_has_no_rule():
    html = '<style>.good{color:red}</style><div class="good ghost"><b class=alsoghost></b></div>'
    assert undefined_in(html, hooks=set()) == ["alsoghost", "ghost"]
    assert undefined_in('<style>.good{color:red}</style><div class=good></div>', hooks=set()) == []


def test_the_checker_reads_the_linked_stylesheet_not_a_hardcoded_one():
    """گارد فایلی را می‌خواند که **صفحه** لینک کرده — با یک خوانندهٔ جعلی سنجیده می‌شود."""
    html = '<link rel="stylesheet" href="/static/css/x.css?v=abc"><div class="from-link"></div>'
    css = stylesheet(html, read=lambda rel: ".from-link{color:red}" if rel == "css/x.css" else "")
    assert "from-link" in set(_CSS_CLASS.findall(css))


def test_a_class_named_only_inside_a_css_comment_does_not_count():
    """کامنت قاعده نیست — همان چیزی که یک‌بار خودِ این گارد را کور کرد."""
    html = ('<style>/* درباره‌ی .ghost حرف می‌زنیم ولی تعریفش نمی‌کنیم */'
            '.real{color:red}</style><div class="real ghost"></div>')
    assert classes_defined(html) == {"real"}
    assert undefined_in(html, hooks=set()) == ["ghost"]


def test_a_js_hook_counts_only_inside_a_selector_string():
    """قلابِ JS = سلکتورِ داخلِ رشته؛ نامی که فقط در کامنت یا کدِ عادی بیاید قلاب نیست."""
    src = ("// .commented-out is not a hook\n"
           "const a = $('.real-hook', d); el.classList.add('added'); x.dataset.y = 1;\n"
           "q(`details.dd[open] .tpl-hook`);")
    hooks = js_hooks(src)
    assert {"real-hook", "dd", "tpl-hook"} <= hooks
    assert "commented-out" not in hooks and "dataset" not in hooks


def test_the_real_js_has_hooks():
    """ضدِتوخالی: اگر کشفِ قلاب صفر برگرداند، معافیتش بی‌معناست."""
    assert {"sheet", "dialog", "js-clear-err"} <= js_hooks()


# ── ادعای اصلی ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", PAGES)
async def test_every_class_a_page_renders_has_a_rule(seeded, path):
    html = await _fetch(seeded, path)
    assert _LINKED_CSS.search(html), f"{path} استایل‌شیتِ پنل را لینک نکرده"
    used = classes_used(html)
    assert len(used) >= 15, f"{path} فقط {len(used)} کلاس رندر کرد — صفحه واقعاً ساخته نشد؟"
    missing = undefined_in(html)
    assert not missing, (
        f"{path} این کلاس‌ها را رندر می‌کند ولی نه قاعده‌ای دارند نه JS دنبالشان می‌گردد: "
        f"{missing}. کلاسِ تعریف‌نشده خطا نمی‌دهد — بی‌صدا بی‌استایل رندر می‌شود.")


async def test_the_login_page_is_checked_as_itself_not_as_the_dashboard(panel):
    """`/login` **بدونِ** کوکی، وگرنه ریدایرکت می‌شود و داشبورد سنجیده می‌شود."""
    resp = await panel.client.get("/login")
    assert resp.status == 200
    html = await resp.text()
    assert 'action="/auth/request"' in html, "این صفحهٔ ورود نیست"
    assert undefined_in(html) == []


async def test_the_seeded_pages_really_carry_the_risky_markup(seeded):
    """کنترلِ محتوا: شاخه‌هایی که گارد باید ببیند واقعاً رندر شده‌اند.

    بدونِ این، «هیچ کلاسِ تعریف‌نشده‌ای نیست» می‌تواند دلیلِ غلط داشته باشد —
    مثلاً اینکه `/cookies` اصلاً اکانتی نداشت و هیچ پیلی نساخت.
    """
    html = await _fetch(seeded, "/cookies")
    for cls in ("pill good", "pill bad", "pill warn", "pill neutral"):
        assert f'class="{cls}"' in html, f"«{cls}» رندر نشد — دادهٔ کاشته‌شده شاخه‌اش را نساخت"
