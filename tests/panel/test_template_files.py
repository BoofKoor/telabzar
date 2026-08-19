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

#: نامِ هر قالبی که `_render` صدا می‌زند — از خودِ سورس کشف می‌شود نه فهرستِ دستی.
_RENDER_CALL = re.compile(r'_render\(\s*"([a-z_]+)"')
#: `{% extends %}` و `{% include %}` داخلِ قالب‌ها
_REF = re.compile(r'{%\s*(?:extends|include)\s*"([^"]+)"')


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


def test_every_template_name_the_panel_asks_for_resolves():
    """هر نامی که `_render` یا یک `{% extends %}`/`{% include %}` می‌خواهد."""
    src = (ROOT / "app" / "admin_web.py").read_text(encoding="utf-8")
    wanted = {f"{n}.html" for n in _RENDER_CALL.findall(src)}
    assert len(wanted) >= 10, f"محل‌های فراخوانیِ _render پیدا نشدند: {wanted}"
    for f in TPL_DIR.glob("*.html"):
        wanted |= set(_REF.findall(f.read_text(encoding="utf-8")))
    for name in sorted(wanted):
        aw.ENV.get_template(name)        # TemplateNotFound اگر نباشد


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


def test_the_stylesheet_that_ships_is_the_file_on_disk(panel_css_text):
    """CSS از فایل خوانده می‌شود ولی **درون‌خطی** تزریق می‌شود.

    اگر روزی به `<link>` برود، این تست قرمز می‌شود و آن **درست** است: آن سوییچ
    بایت‌های HTML را عوض می‌کند و سه خوانندهٔ `<style>`ِ همان پاسخ را می‌شکند،
    پس باید تصمیمِ آگاهانه باشد نه یک اثرِ جانبی.
    """
    assert panel_css_text.strip(), "panel.css خالی است"
    assert panel_css_text == aw._CSS


async def test_the_served_page_carries_the_stylesheet_from_the_file(panel, panel_css_text):
    """کنترلِ انتها‌به‌انتها: فایل واقعاً به مرورگر می‌رسد.

    بدونِ این، «`_CSS` برابرِ فایل است» می‌تواند صادق باشد در حالی که `_render`
    اصلاً تزریقش نمی‌کند.
    """
    html = await (await panel.client.get("/", cookies=panel.cookies)).text()
    marker = "@font-face{font-family:'Vazirmatn'"
    assert marker in panel_css_text and marker in html
    assert ".card{background:" in html, "قواعدِ اصلی در صفحه نیستند"


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
