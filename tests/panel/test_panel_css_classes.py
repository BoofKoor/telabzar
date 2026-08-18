"""هر کلاسی که پنل **رندر می‌کند** باید در استایلِ همان صفحه قاعده داشته باشد.

CLAUDE.md §۵ این قاعده را از قبل نوشته بود («هر کلاسی که قالب استفاده می‌کند
باید در `_CSS` باشد — کلاسِ تعریف‌نشده بی‌صدا به یک عنصرِ بی‌استایل و
بدونِ padding تبدیل می‌شود؛ `.pad`/`.hint`/`.tabs` این‌طور خراب شیپ شدند»)، ولی
هیچ‌چیز اجرایش نمی‌کرد. نتیجه‌اش `.err` و `.mute` و `.s-unproven` بود: سه کلاس
که رندر می‌شدند و هیچ‌جا تعریف نشده بودند، و دو تایشان دقیقاً روی دو وضعیتی
می‌نشستند که دخالتِ انسان می‌خواهند («باطل» و «چک‌پوینت»).

**چرا کشف‌محور و نه فهرستِ دستیِ سه‌تایی.** این سومین بارِ همان الگوست، پس
مسئله «آن سه کلاس» نیست بلکه «هیچ‌کس متوجه نمی‌شود» است. گارد هر ۹ صفحهٔ GET را
با داده رندر می‌کند و کلاس‌ها را با CSSِ همان پاسخ تطبیق می‌دهد — یعنی کلاسِ
مردهٔ بعدی هم بدونِ یک خط تغییر در این فایل گرفته می‌شود.

**دو قیدِ اندازه‌گیری‌شده که شکلِ تست را ساختند.**

* `/login` باید **بدونِ کوکی** گرفته شود. با کوکیِ ادمین به `/` ریدایرکت
  می‌شود و aiohttp دنبالش می‌کند، پس تست بی‌خبر داشبورد را دوباره می‌سنجید.
  در پروبِ اولِ همین کار دقیقاً همین اتفاق افتاد (`/login` عددِ کلاسِ `/` را
  می‌داد) و فقط با شمردنِ کلاس‌ها معلوم شد.
* صفحه باید **داده** داشته باشد. `/cookies`ِ بی‌اکانت هیچ بجی رندر نمی‌کند، پس
  گارد روی آن دربارهٔ `.err` هیچ نمی‌گوید. `seeded` برای همین است، و
  `test_the_seeded_pages_really_carry_the_risky_markup` صریح می‌سنجد که آن
  شاخه‌ها واقعاً رندر شده‌اند — وگرنه «صفر کلاسِ تعریف‌نشده» می‌تواند صرفاً
  یعنی «صفر کلاس».
"""
from __future__ import annotations

import re

import pytest

#: هر مسیرِ GETی که یک صفحهٔ HTML می‌دهد. `/healthz` و `/node/*` بیرون‌اند
#: (HTML نیستند) و `/logout` فقط ریدایرکت است.
PAGES = ("/", "/cookies", "/health", "/users", "/stats", "/texts", "/buttons", "/nodes")

_CLASS_ATTR_Q = re.compile(r'class="([^"]*)"')
_CLASS_ATTR_BARE = re.compile(r"class=([A-Za-z][\w-]*)")
_STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
_CSS_CLASS = re.compile(r"\.([A-Za-z][\w-]*)")
#: کامنتِ CSS داخلِ `<style>` **ارسال می‌شود**، پس نثرِ توضیحی هم اسکن می‌شد.
#: این با اجرا پیدا شد نه با بازخوانی: اولین سابوتاژِ همین گارد «نگرفت» داد،
#: چون کامنتی که خودم بالای `.err` نوشتم عبارتِ «`.err`» را دارد و چک آن را
#: «تعریف‌شده» می‌خواند. سومین بارِ همان تلهٔ ثبت‌شده در §۶ (گاردِ ASTی که
#: داکس‌استرینگِ خودش را می‌گرفت) — کامنت **قاعده نیست**.
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def classes_used(html: str) -> set[str]:
    """کلاس‌های واقعاً رندرشده — هر دو شکلِ `class="a b"` و `class=a`."""
    out: set[str] = set()
    for m in _CLASS_ATTR_Q.finditer(html):
        out |= {c for c in m.group(1).split() if c}
    out |= {m.group(1) for m in _CLASS_ATTR_BARE.finditer(html)}
    return out


def stylesheet(html: str) -> str:
    """CSSِ خودِ همین پاسخ، **بدونِ کامنت**."""
    return _CSS_COMMENT.sub(" ", "\n".join(_STYLE_BLOCK.findall(html)))


def classes_defined(html: str) -> set[str]:
    """کلاس‌هایی که `<style>`های خودِ همین پاسخ واقعاً تعریف می‌کنند."""
    return set(_CSS_CLASS.findall(stylesheet(html)))


def undefined_in(html: str) -> list[str]:
    return sorted(classes_used(html) - classes_defined(html))


async def _fetch(panel, path: str) -> str:
    resp = await panel.client.get(path, cookies=panel.cookies)
    assert resp.status == 200, f"{path} → HTTP {resp.status}"
    return await resp.text()


# ── کنترلِ منفی: اول ثابت کن این چک اصلاً می‌تواند بیفتد ────────────────────
def test_the_checker_reports_a_class_that_has_no_rule():
    """بدونِ این، «صفر کلاسِ تعریف‌نشده» می‌تواند یعنی «چک کور است».

    §۶: هر بنچی پیش از آنکه عددِ سبزش معنا داشته باشد باید نشان دهد نسخهٔ خراب
    را می‌گیرد. این‌جا نسخهٔ خراب دستی ساخته می‌شود.
    """
    html = '<style>.good{color:red}</style><div class="good ghost"><b class=alsoghost></b></div>'
    assert undefined_in(html) == ["alsoghost", "ghost"]
    assert undefined_in('<style>.good{color:red}</style><div class=good></div>') == []


def test_the_checker_reads_both_class_attribute_spellings():
    """قالب‌های این ریپو هر دو شکل را می‌نویسند (`class=card` و `class="badge ok"`)."""
    assert classes_used('<div class=card><i class="badge ok"></i>') == {"card", "badge", "ok"}


def test_a_class_named_only_inside_a_css_comment_does_not_count():
    """کامنت قاعده نیست — و این همان چیزی است که یک‌بار خودِ گارد را کور کرد.

    اولین سابوتاژِ این گارد «نگرفت» گزارش شد، در حالی که خرابکاری کاملاً اعمال
    شده بود: کامنتِ فارسیِ بالای `.err` در `_CSS` عبارتِ «`.err`» را دارد،
    کامنت داخلِ `<style>` به مرورگر **ارسال می‌شود**، و چک آن را «تعریف‌شده»
    می‌خواند. یعنی نه تستِ ضعیف بود و نه سابوتاژِ ناموفق، بلکه ردهٔ سومِ ثبت‌شده
    در §۶: **ابزارِ سنجش نتیجهٔ درست را غلط می‌خواند.**
    """
    html = ('<style>/* درباره‌ی .ghost حرف می‌زنیم ولی تعریفش نمی‌کنیم */'
            '.real{color:red}</style><div class="real ghost"></div>')
    assert classes_defined(html) == {"real"}
    assert undefined_in(html) == ["ghost"]


# ── ادعای اصلی ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", PAGES)
async def test_every_class_a_page_renders_has_a_rule(seeded, path):
    html = await _fetch(seeded, path)
    used = classes_used(html)
    # اگر صفحه‌ای تقریباً بی‌کلاس دربیاید یعنی رندر نشده و ادعا توخالی است.
    assert len(used) >= 15, f"{path} فقط {len(used)} کلاس رندر کرد — صفحه واقعاً ساخته نشد؟"
    missing = undefined_in(html)
    assert not missing, (
        f"{path} این کلاس‌ها را رندر می‌کند ولی هیچ قاعده‌ای برایشان نیست: {missing}. "
        f"کلاسِ تعریف‌نشده خطا نمی‌دهد — بی‌صدا بی‌استایل رندر می‌شود.")


async def test_the_login_page_is_checked_as_itself_not_as_the_dashboard(panel):
    """`/login` **بدونِ** کوکی، وگرنه ریدایرکت می‌شود و داشبورد سنجیده می‌شود."""
    resp = await panel.client.get("/login")
    assert resp.status == 200
    html = await resp.text()
    assert "ورود" in html and "auth/request" in html, "این صفحهٔ ورود نیست"
    assert undefined_in(html) == []


async def test_the_seeded_pages_really_carry_the_risky_markup(seeded):
    """کنترلِ محتوا: شاخه‌هایی که گارد باید ببیند واقعاً رندر شده‌اند.

    بدونِ این، «هیچ کلاسِ تعریف‌نشده‌ای نیست» می‌تواند دلیلِ غلط داشته باشد —
    مثلاً اینکه `/cookies` اصلاً اکانتی نداشت و هیچ بجی نساخت.
    """
    html = await _fetch(seeded, "/cookies")
    for cls in ("badge err", "badge ok", "badge warn", "badge dim"):
        assert cls in html, f"«{cls}» رندر نشد — دادهٔ کاشته‌شده شاخه‌اش را نساخت"
    assert "s-unproven" in html and "s-invalid" in html and "s-frozen" in html
