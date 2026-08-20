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


def _console_nav() -> list[dict[str, str]]:
    """`[{n, label, href, legacy}]` از `nav.ts`.

    کامنت‌ها **پیش از** تطبیق دور ریخته می‌شوند: آن فایل کامنتِ فارسیِ
    مفصلی دارد که نامِ همین مسیرها را می‌برد، و §۶ ثبت کرده که هر گاردِ
    متن‌خوانی سرانجام توضیحاتِ خودش را می‌خواند.
    """
    src = NAV_TS.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))
    out = []
    for m in re.finditer(
        r"\{\s*n:\s*'(\d+)',\s*label:\s*'([^']+)',\s*href:\s*'([^']+)',\s*legacy:\s*'([^']+)'",
        src,
    ):
        out.append({"n": m.group(1), "label": m.group(2), "href": m.group(3), "legacy": m.group(4)})
    return out


def test_the_parser_actually_finds_the_nav():
    """کنترلِ ضدِتوخالی: فهرستِ تهی هر ادعای زیر را بی‌معنا می‌کند."""
    assert len(_console_nav()) >= 8


def test_the_comment_stripper_is_not_decorative():
    """اگر کامنت‌ها دور ریخته نشوند، این ورودیِ ساختگی شمرده می‌شود."""
    fake = "/* { n: '99', label: 'GHOST', href: '/x/', legacy: '/x' } */\nexport const NAV = []\n"
    stripped = re.sub(r"/\*.*?\*/", "", fake, flags=re.S)
    assert "GHOST" not in stripped


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
