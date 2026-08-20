"""ریلِ کنسول باید همان صفحاتی را بپوشاند که پنل واقعاً دارد.

**چرا این گارد لازم است و چرا این شکل:** ناوبریِ کنسول در TypeScript زندگی
می‌کند (`panel/lib/nav.ts`) و ناوبریِ پنلِ Jinja در پایتون (`admin_web._NAV`).
دو فهرستِ دست‌نویس برای یک واقعیت — دقیقاً همان الگویی که §۷ بارها ثبتش
کرده (`remove_cookie_file`، `_search_queries`، `kill_orphan`). شکستش هم
**خاموش** است: صفحهٔ تازه‌ای که به پنل اضافه شود در کنسول نامرئی می‌ماند و
هیچ تستی قرمز نمی‌شود؛ فقط کسی روزی می‌پرسد «چرا این‌جا نیست؟».

فهرست با **پارس** خوانده می‌شود نه import: `tests/` نه Node دارد نه
TypeScript، و خواندنِ رشته‌ایِ یک فایلِ اعلانی ارزان‌تر از هر جایگزینی است.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
NAV_TS = ROOT / "panel" / "lib" / "nav.ts"


_REQUIRED = ("n", "label", "href", "legacy")

#: یک آبجکتِ لیترالِ **بدونِ تودرتویی** — هر ردیفِ `NAV` دقیقاً همین شکل است.
_ENTRY_RE = re.compile(r"\{[^{}]*\}")
#: `key: 'value'` — نام از خودِ متن خوانده می‌شود، نه از موقعیتش.
_FIELD_RE = re.compile(r"(\w+)\s*:\s*'([^']*)'")


def _strip_comments(src: str) -> str:
    """کامنت‌های بلوکی و خطیِ TypeScript.

    **پیش از** هر تطبیقی اجرا می‌شود: `nav.ts` کامنتِ فارسیِ مفصلی دارد که
    نامِ همین مسیرها را می‌برد، و §۶ ثبت کرده که هر گاردِ متن‌خوانی سرانجام
    توضیحاتِ خودش را می‌خواند.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))


def _parse_nav(src: str) -> list[dict[str, str]]:
    """`[{n, label, href, legacy}]` از متنِ `nav.ts`.

    فیلدها **با نام** خوانده می‌شوند نه با موقعیت، و کلیدِ ناشناخته دور
    ریخته می‌شود. این شکل تصادفی نیست: نسخهٔ اولْ یک رجکسِ ترتیبی بود
    (`n` بعد `label` بعد `href` بعد `legacy`) و افزودنِ فیلدِ `sig` بینِ
    دو تای اول کافی بود تا **هیچ‌چیز** جور نشود و پارسر فهرستِ تهی بدهد —
    یعنی هر ادعای پوششِ زیر بی‌صدا صادق می‌شد. آن‌بار کنترلِ ضدِتوخالی
    گرفتش؛ ولی درستش این است که پارسر اصلاً به ترتیبِ کلیدها بند نباشد،
    چون فیلدِ بعدی هم روزی اضافه می‌شود.
    """
    out = []
    for block in _ENTRY_RE.findall(_strip_comments(src)):
        fields = dict(_FIELD_RE.findall(block))
        if all(k in fields for k in _REQUIRED):
            out.append({k: fields[k] for k in _REQUIRED})
    return out


def _console_nav() -> list[dict[str, str]]:
    return _parse_nav(NAV_TS.read_text(encoding="utf-8"))


def test_the_parser_actually_finds_the_nav():
    """کنترلِ ضدِتوخالی: فهرستِ تهی هر ادعای زیر را بی‌معنا می‌کند."""
    assert len(_console_nav()) >= 8


def test_the_parser_does_not_depend_on_key_order():
    """همان رگرسیونی که `sig` ساخت — این‌بار به‌عنوان ادعا، نه تصادف.

    سه شکلِ یک ردیف: امروزی، با کلیدِ تازه در وسط، و با ترتیبِ برهم‌خورده.
    هر سه باید یک چیز بدهند، وگرنه گاردِ پوشش با اولین فیلدِ اضافه‌شده
    بی‌صدا از کار می‌افتد.
    """
    shapes = [
        "[{ n: '01', label: 'X', href: '/console/', legacy: '/' }]",
        "[{ n: '01', sig: '◈', label: 'X', href: '/console/', legacy: '/' }]",
        "[{ legacy: '/', href: '/console/', label: 'X', n: '01', extra: 'z' }]",
    ]
    parsed = [_parse_nav(s) for s in shapes]
    want = [{"n": "01", "label": "X", "href": "/console/", "legacy": "/"}]
    assert parsed == [want, want, want]


def test_the_comment_stripper_is_not_decorative():
    """اگر کامنت‌ها دور ریخته نشوند، این ورودیِ ساختگی شمرده می‌شود."""
    fake = "/* { n: '99', label: 'GHOST', href: '/x/', legacy: '/x' } */\nexport const NAV = []\n"
    assert _parse_nav(fake) == []


def test_every_console_entry_points_at_a_real_panel_page(panel):
    """هر `legacy` باید یک روتِ ثبت‌شدهٔ واقعی باشد، نه یک آرزو."""
    routes = {r.resource.canonical for r in panel.client.app.router.routes() if r.resource}
    missing = [e["legacy"] for e in _console_nav() if e["legacy"] not in routes]
    assert not missing, f"این مسیرها در پنل وجود ندارند: {missing}"


def test_every_panel_page_appears_in_the_console(panel):
    """جهتِ برگشت — همانی که بدونش صفحهٔ تازه بی‌صدا جا می‌ماند."""
    legacy = {e["legacy"] for e in _console_nav()}
    panel_pages = {path for _, items in panel.aw._NAV for _, _, path, _ in items}
    missing = panel_pages - legacy
    assert not missing, (
        "این صفحاتِ پنل در ریلِ کنسول نیستند: "
        f"{sorted(missing)} — یا به panel/lib/nav.ts اضافه‌شان کن یا دلیلش را بنویس."
    )


def test_the_numbering_is_dense_and_unique():
    """شماره‌ها روی صفحه دیده می‌شوند و میان‌بُرِ صفحه‌کلید به آن‌ها بند است."""
    ns = [e["n"] for e in _console_nav()]
    assert len(ns) == len(set(ns)), f"شمارهٔ تکراری: {ns}"
    assert ns == [f"{i:02d}" for i in range(1, len(ns) + 1)], f"شماره‌ها پیوسته نیستند: {ns}"


def test_every_console_href_is_under_the_console_prefix():
    """`href` باید مسیرِ کنسول باشد؛ اشتباهِ ساده‌اش لینک‌دادن به صفحهٔ Jinja است."""
    bad = [e["href"] for e in _console_nav() if not e["href"].startswith("/console/")]
    assert not bad, bad
