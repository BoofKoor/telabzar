"""قالب‌ها از فایل بار می‌شوند — و سه چیزی که همان لحظه می‌تواند بی‌صدا بشکند.

استخراجِ قالب‌ها از رشته‌های پایتونی به `app/templates/*.html` **یک** ردهٔ خرابی
تازه می‌سازد که هیچ تستِ رفتاری‌ای نمی‌گیردش: فایلی که در ایمیج نباشد. تست از
ریشهٔ ریپو می‌دود و پوشه را می‌بیند؛ کانتینر فقط چیزی را دارد که Dockerfile
کپی کرده. یعنی **CI سبز، تولید ۵۰۰** — همان حادثه‌ای که یک‌بار برای
`node/install.sh` افتاد.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app import admin_web as aw

ROOT = Path(__file__).resolve().parents[2]
TPL_DIR = Path(aw._TEMPLATE_DIR)

#: نامِ هر قالبی که `_render`/`_page` صدا می‌زند — از خودِ سورس کشف می‌شود نه
#: فهرستِ دستی. نامِ **لفظی** فقط وقتی شمرده می‌شود که به `+` نچسبیده باشد؛ شکلِ
#: پویا (`"_sheet_" + sheet_kind`) جدا باز می‌شود، وگرنه «`_sheet_.html`» خواسته
#: می‌شد که قالبی نیست.
_RENDER_CALL = re.compile(r'(?:_render\(|_page\(\s*request,)\s*"([a-z_]+)"(?!\s*\+)')
_DYNAMIC_SHEET = re.compile(r'_render\(\s*"_sheet_"\s*\+')
_SHEET_KIND = re.compile(r'sheet_kind\s*=.*,\s*"([a-z_]+)"\s*$', re.M)
#: `extends`/`include`/`import`/`from` با نامِ **لفظی**، هر دو نوعِ کوتیشن
_REF = re.compile(r"""{%-?\s*(?:extends|include|import|from)\s*(['"])([^'"]+)\1\s*(?:%|-|as\b|import\b|with\b)""")
#: شکلِ پویا: `{% include '_sheet_' ~ x ~ '.html' %}`
_DYNAMIC_REF = re.compile(r"""{%-?\s*include\s*(['"])_sheet_\1\s*~""")


def _dockerfile_copy_roots(path: Path) -> set[str]:
    """ریشه‌هایی که ایمیج واقعاً کپی می‌کند.

    کامنتِ `#` **پیش از** هر تطبیقی دور ریخته می‌شود: یک `COPY`ِ کامنت‌شده
    نباید به‌عنوان پوشش شمرده شود، و متنِ توضیحیِ خودِ Dockerfile هم نباید
    داده شود — همان تلهٔ خودارجاعی که §۶ چهار نمونه‌اش را ثبت کرده.
    """
    lines = [re.sub(r"#.*$", "", ln) for ln in path.read_text(encoding="utf-8").splitlines()]
    roots: set[str] = set()
    for ln in lines:
        m = re.match(r"\s*COPY\s+(.+)$", ln, re.I)
        if m:
            parts = m.group(1).split()
            roots.update(parts[:-1])          # آخری مقصد است
    return roots


def test_every_runtime_asset_dir_ships_in_the_admin_image():
    """تنها راهی که این فاز می‌تواند تولید را با CIِ سبز بشکند.

    اگر قالب‌ها یا CSS بیرونِ `app/` بروند، `FileSystemLoader` در کانتینر
    `TemplateNotFound` می‌دهد و هر صفحه ۵۰۰ می‌شود — در حالی که تست‌ها از ریشهٔ
    ریپو می‌دوند و پوشه را پیدا می‌کنند.
    """
    roots = _dockerfile_copy_roots(ROOT / "docker" / "admin.Dockerfile")
    assert roots, "هیچ COPYی در Dockerfile پیدا نشد — پارسر شکسته است"
    for label, d in (("templates", TPL_DIR), ("static", Path(aw._STATIC_DIR))):
        rel = os.path.relpath(d, ROOT)
        assert not rel.startswith(".."), f"{label} بیرونِ ریپوست: {rel}"
        top = rel.split(os.sep)[0]
        assert top in roots, (
            f"{label} در «{rel}» است ولی ایمیج فقط {sorted(roots)} را کپی می‌کند — "
            f"پنل روی تولید ۵۰۰ می‌دهد و CI سبز می‌ماند.")


def test_the_copy_parser_ignores_comments(tmp_path):
    """کنترلِ منفی برای پارسر: کامنت پوشش نیست.

    **کامنتِ ابتدای خط این را ثابت نمی‌کند** و نسخهٔ اولِ همین تست وقتش را تلف
    کرد: `re.match` به ابتدای خط لنگر می‌خورد، پس `# COPY ghost` از هر حال رد
    می‌شود و برداشتنِ حذفِ کامنت هیچ‌چیز را نمی‌شکست — سابوتاژ «نگرفت» داد و
    درست هم می‌گفت. چیزی که واقعاً به حذفِ کامنت بند است **کامنتِ انتهای خط**
    است: بدونِ آن، توکن‌های کامنت به‌عنوان ریشهٔ COPY خوانده می‌شوند.
    """
    f = tmp_path / "Dockerfile"
    f.write_text("FROM x\n"
                 "# COPY ghost ./ghost\n"
                 "COPY app ./app  # قالب‌ها و static از همین می‌آیند\n",
                 encoding="utf-8")
    assert _dockerfile_copy_roots(f) == {"app"}


def _wanted_templates() -> set[str]:
    src = (ROOT / "app" / "admin_web.py").read_text(encoding="utf-8")
    wanted = {f"{n}.html" for n in _RENDER_CALL.findall(src)}
    dynamic = bool(_DYNAMIC_SHEET.search(src))
    for f in TPL_DIR.glob("*.html"):
        text = f.read_text(encoding="utf-8")
        wanted |= {name for _q, name in _REF.findall(text)}
        dynamic |= bool(_DYNAMIC_REF.search(text))
    if dynamic:                     # برگه‌های کشویی: هر نوعی که هندلر می‌سازد
        wanted |= {f"_sheet_{k}.html" for k in _SHEET_KIND.findall(src)}
    return wanted


def test_every_template_name_the_panel_asks_for_resolves():
    """هر نامی که `_render`/`_page` یا `extends`/`include`/`import` می‌خواهد."""
    wanted = _wanted_templates()
    assert len(wanted) >= 15, f"محل‌های فراخوانی پیدا نشدند: {sorted(wanted)}"
    assert {"base.html", "_macros.html", "_sheet_dl.html", "_sheet_job.html"} <= wanted, sorted(wanted)
    for name in sorted(wanted):
        aw.ENV.get_template(name)        # TemplateNotFound اگر نباشد


def test_no_template_file_is_orphaned():
    """جهتِ عکس: قالبی که هیچ‌کس نمی‌خواهد کدِ مرده است — یا فراخوانیِ گم‌شده."""
    orphans = sorted({p.name for p in TPL_DIR.glob("*.html")} - _wanted_templates())
    assert not orphans, f"این قالب‌ها هیچ‌جا رندر یا include نمی‌شوند: {orphans}"


def test_the_reference_patterns_are_not_dead_weight():
    """کنترلِ منفی برای کشف: هر چهار شکل، و پویا جدا از لفظی."""
    tpl = ("{% extends 'base.html' %}{% import \"_m.html\" as m with context %}"
           "{% include 'x.html' %}{% from 'y.html' import z %}{% include '_sheet_' ~ k ~ '.html' %}")
    assert {n for _q, n in _REF.findall(tpl)} == {"base.html", "_m.html", "x.html", "y.html"}
    assert _DYNAMIC_REF.search(tpl)
    src = 'return _render("_sheet_" + kind, request)\n    return await _page(request, "users", "users")\n'
    assert _RENDER_CALL.findall(src) == ["users"] and _DYNAMIC_SHEET.search(src)


def test_the_template_directory_is_not_empty():
    """`parametrize` روی یک کشفِ **تهی** بی‌صدا ناپدید می‌شود، نه قرمز.

    اندازه‌گیری‌شده: با مسیرِ غلطِ `_TEMPLATE_DIR`، جمع‌آوری از ۱۶ تست به ۵ تا
    افتاد — یعنی ۱۱ ادعا بدونِ یک خطِ قرمز از دست رفت. این کف همان را می‌گیرد.
    """
    assert len(list(TPL_DIR.glob("*.html"))) >= 12, f"قالبی در {TPL_DIR} نیست"


@pytest.mark.parametrize("path", sorted(TPL_DIR.glob("*.html")), ids=lambda p: p.name)
def test_a_template_file_ends_with_exactly_one_newline(path):
    """Jinja **دقیقاً یک** خطِ جدیدِ پایانی را می‌خورد (اندازه‌گیری‌شده).

    پس فایلی با **دو** خطِ خالیِ پایانی یک `\\n` به **هر صفحه** اضافه می‌کند —
    محتمل‌ترین تصادفِ ویرایشگر، و کاملاً بی‌صدا.
    """
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n"), f"{path.name} خطِ پایانی ندارد"
    assert not text.endswith("\n\n"), (
        f"{path.name} بیش از یک خطِ جدیدِ پایانی دارد — یک `\\n` به هر صفحه اضافه می‌شود")


_LINK = re.compile(r'<link rel="stylesheet" href="(/static/css/panel\.css)\?v=([0-9a-f]+)"')


async def test_the_stylesheet_that_ships_is_the_file_on_disk(panel, panel_css_text):
    """از بازطراحیِ ۲۰۲۶-۱۰ استایل **لینک** می‌شود، با `?v=<هش>` و کشِ یک‌ساله.

    تصمیمِ آگاهانه‌ای که نسخهٔ قبلیِ این تست برایش قرمز می‌شد: نسخهٔ درونِ‌خطی
    هر صفحه را ~۶۰ کیلوبایت سنگین می‌کرد و کش نمی‌شد. ادعای تازه این است که
    URL **از خودِ فایل** ساخته شده — اگر فایل عوض شود و هش نه، مرورگرها یک سال
    نسخهٔ کهنه را با صفحهٔ تازه قاطی می‌کنند.
    """
    import hashlib

    html = await (await panel.client.get("/", cookies=panel.cookies)).text()
    m = _LINK.search(html)
    assert m, "صفحه panel.css را با نسخه لینک نکرده"
    data = panel_css_text.encode("utf-8")
    assert m.group(2) == hashlib.sha256(data).hexdigest()[:10], "هشِ URL مالِ این فایل نیست"
    resp = await panel.client.get(f"{m.group(1)}?v={m.group(2)}", headers={"Accept-Encoding": "identity"})
    assert resp.status == 200 and await resp.read() == data
    assert "immutable" in resp.headers["Cache-Control"]


async def test_a_stale_version_is_not_cached_for_a_year(panel):
    """کنترلِ معکوس: URLِ نسخهٔ کهنه نباید `immutable` بگیرد — وگرنه همان قاطی‌شدن."""
    resp = await panel.client.get("/static/css/panel.css?v=0000000000")
    assert resp.status == 200 and resp.headers["Cache-Control"] == "no-cache"


async def test_the_font_the_stylesheet_names_is_served(panel, panel_css_text):
    """فونت محلی است (CSP هیچ هاستِ بیرونی نمی‌دهد)؛ URLش باید واقعاً سرو شود."""
    urls = re.findall(r"url\('(/static/fonts/[^']+)'\)", panel_css_text)
    assert urls, "panel.css هیچ فونتِ محلی‌ای نام نمی‌برد"
    for u in urls:
        resp = await panel.client.get(u)
        assert resp.status == 200 and len(await resp.read()) > 10_000, u


def test_the_stylesheet_ends_with_exactly_one_newline(panel_css_text):
    assert panel_css_text.endswith("\n") and not panel_css_text.endswith("\n\n")


@pytest.fixture
def panel_css_text() -> str:
    return (Path(aw._STATIC_DIR) / "css" / "panel.css").read_text(encoding="utf-8")


def test_no_page_template_is_left_behind_as_a_python_string():
    """ضدِ رگرسیون: قالبِ بعدی هم باید فایل باشد، نه رشته‌ای در `admin_web`."""
    leftovers = [n for n in ("_BASE", "_STATS", "_COOKIES", "_LOGIN", "_HEALTH_CARDS")
                 if getattr(aw, n, None)]
    assert not leftovers, f"این قالب‌ها هنوز رشتهٔ پایتونی‌اند: {leftovers}"
