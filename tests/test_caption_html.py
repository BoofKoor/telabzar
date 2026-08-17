"""کپشنِ HTMLدار: پاک‌سازی، و مهم‌تر از آن **دست‌نزدن** به کپشنِ ساده.

**علامت.** توضیحاتِ اپیزودِ کست‌باکس با تگ‌های خام به کاربر می‌رسید — `<strong>`،
`</p>`، `<p>` عیناً دیده می‌شدند. توضیحاتِ پادکست HTML است و اکسترکتورِ `html5`
خام برمی‌داردش؛ `cards.post_view` هم escapeش می‌کند (که **درست** است، وگرنه یک
`<` واقعی کلِ پیام را برای تلگرام خراب می‌کند). گامِ غایب **پاک‌کردن** بود.

**و چرا نصفِ این فایل دربارهٔ متنِ ساده است.** `clean_caption` مشترک است و
کپشنِ **سادهٔ** اینستاگرام هم از آن رد می‌شود. پاک‌کردنِ بی‌قید اندازه‌گیری شد و
روی ۱۰ متنِ سادهٔ واقعی **۳ تا را خراب کرد**، یکی‌شان شدید:

    کد: if (a<b) return;   →   کد: if (a          ← بقیه‌اش خورده شد
    use --flag <value> here →  use --flag  here
    به <a@b.com> ایمیل بزن  →  به  ایمیل بزن

`<b>` نامِ تگِ واقعی است و پارسر تا انتهای رشته را می‌بلعد. یعنی رفعِ بی‌قید یک
زشتیِ کوچک در کست‌باکس را با یک **باگِ واقعی** در پرترافیک‌ترین مسیر عوض می‌کرد.
پس `test_a_plain_caption_is_untouched` از تستِ خودِ رفع مهم‌تر است، و سابوتاژِ
«گیت را بردار» دقیقاً همان را می‌اندازد.

**فیکسچر واقعی است، نه ساختگی** — خروجیِ عینیِ `yt-dlp --dump-json` روی
`castbox.fm/ep/798014224`. سه چیز را با هم می‌سنجد که رشتهٔ دست‌ساز نمی‌سنجید:
`<strong>`ِ تودرتو کنارِ ایموجی، سه `<p>` پشتِ‌هم، و `<p>`ی که با **فاصله** شروع
می‌شود. خودِ کست‌باکس متن را با `...` بریده، پس کوتاه است و سقفِ ۱۰۲۴ رویش
هرگز شلیک نمی‌کند — سقف با فیکسچرِ **دست‌سازِ بلند** جدا تست می‌شود.
"""
from __future__ import annotations

import pytest

from app.downloader import _HTML_GATE, clean_caption, strip_html

# ── فیکسچرِ واقعی (yt-dlp --dump-json، castbox.fm/ep/798014224) ──────
REAL_DESC = (
    "<p>🎙️ <strong>تنهایی و آمادگی برای عشق</strong></p>"
    "<p>برای داشتن یه رابطه سالم، باید بلد باشیم تنها زندگی کنیم.</p>"
    "<p> توی این اپیزود، از تنهایی می‌گیم...")

# متن‌های **بدونِ HTML** که کاربر واقعاً می‌نویسد. هر کدام یک شکلِ `<` است که
# پاک‌سازیِ بی‌قید می‌خوردش. `id`ها عمداً **بی‌فاصله**اند: دفترچهٔ سابوتاژ نامِ
# تستِ افتاده را روی فاصله می‌شکند، پس idِ فاصله‌دار یک سابوتاژِ موفق را
# «نگرفت» گزارش می‌کند (§۶).
PLAIN = [
    pytest.param("عاشقتم <3", id="persian-heart"),
    pytest.param("i <3 this song", id="latin-heart"),
    pytest.param("5 < 10 and 10 > 5", id="inequality"),
    pytest.param("use --flag <value> here", id="cli-placeholder"),
    pytest.param("به <a@b.com> ایمیل بزن", id="email-in-angles"),
    pytest.param("<<< بهترین >>>", id="decorative-angles"),
    pytest.param("قیمت < ۱۰۰ تومان", id="persian-digits"),
    pytest.param("A -> B <- C", id="arrows"),
    pytest.param("کد: if (a<b) return;", id="code-lt-b"),
    pytest.param("معمولی، بدونِ هیچ نشانه‌ای", id="no-markers"),
    pytest.param("ایمیل: foo@bar.com | تماس: ۰۲۱", id="contact-line"),
    pytest.param("x<y و y<z پس x<z", id="chained-lt"),
]

# کپشنِ چندخطیِ سبکِ اینستاگرام. **این ضبطِ واقعی نیست** — نمایندهٔ شکلِ رایج
# است (چند خط، ایموجی، خطِ تجهیزات، یک `<3` در پایان). صادقانه علامت می‌خورد
# چون هیچ کپشنی در فیکسچرهای ضبط‌شدهٔ ریپو نبود؛ ادعایش «این شکل دست‌نخورده
# می‌ماند» است، نه «اسکیمای اینستاگرام این است».
IG_CAPTION = ("پاییز اومد 🍂\n\n"
              "این عکسا رو تو جنگل گرفتم، امیدوارم خوشتون بیاد.\n"
              "دوربین: Canon R6 | لنز: 24-70\n\n"
              "نظرتون چیه؟ <3")


# ── ۱) فیکسچرِ واقعی ─────────────────────────────────────────────────
def test_the_real_castbox_description_loses_its_tags():
    out = clean_caption(REAL_DESC)
    for tag in ("<p>", "</p>", "<strong>", "</strong>"):
        assert tag not in out, f"تگِ خامِ {tag} به کاربر می‌رسد."


def test_the_real_description_keeps_its_emoji():
    assert "🎙️" in clean_caption(REAL_DESC)


def test_the_real_description_keeps_its_paragraphs_apart():
    """`</p><p>` باید مرزِ خط بسازد، نه حذف شود.

    بدونِ تبدیلِ تگِ بلوکی به `\\n`، سه پاراگراف به هم می‌چسبند
    (اندازه‌گیری‌شده: «خط یکخط دو»).
    """
    out = clean_caption(REAL_DESC)
    assert "عشق\n" in out, "پاراگرافِ اول به دومی چسبیده."
    assert "کنیم.\n" in out, "پاراگرافِ دوم به سومی چسبیده."


def test_the_real_description_has_no_leading_indent():
    """سومین `<p>` با یک **فاصله** شروع می‌شود؛ بعد از `\\n` تورفتگی می‌داد.

    `clean_caption` خودش این را جمع نمی‌کند — `ln.rstrip()` فقط راست را می‌گیرد.
    """
    out = clean_caption(REAL_DESC)
    assert not any(ln.startswith((" ", "\t")) for ln in out.splitlines()), \
        f"خطِ تورفته: {out!r}"


# ── ۲) کنترل: متنِ ساده بیت‌به‌بیت دست‌نخورده ─────────────────────────
@pytest.mark.parametrize("text", PLAIN)
def test_a_plain_caption_is_untouched(text):
    """**مهم‌ترین تستِ این فایل.** سابوتاژِ «گیت را بردار» همین را می‌اندازد."""
    assert clean_caption(text) == text, "پاک‌سازی به متنِ سادهٔ کاربر دست زد."


def test_a_multiline_instagram_caption_is_untouched():
    """پرترافیک‌ترین مسیر — رگرسیونش گران‌ترین است."""
    assert clean_caption(IG_CAPTION) == IG_CAPTION


@pytest.mark.parametrize("text", PLAIN)
def test_the_gate_stays_silent_on_plain_text(text):
    assert not _HTML_GATE.search(text)


@pytest.mark.parametrize("text", [
    pytest.param("<p>خط</p>", id="paragraph"),
    pytest.param("یک<br>دو", id="br"),
    pytest.param("<div class='x'>م</div>", id="div-with-attr"),
    pytest.param('<a href="https://x.com">ا</a>', id="anchor"),
    pytest.param("<ul><li>یک</li></ul>", id="list"),
    pytest.param("متن<br/>ادامه", id="self-closing-br"),
])
def test_the_gate_fires_on_real_html(text):
    assert _HTML_GATE.search(text)


# ── ۳) تلهٔ ۱: پارسر، نه رجکس ────────────────────────────────────────
def test_a_less_than_sign_in_prose_survives():
    """`<[^>]+>` از `<` تا اولین `>` را می‌بلعد — اندازه‌گیری‌شده: «اگر x  2»."""
    src = "<p>اگر x < 5 باشد و y > 2 آن‌گاه ادامه بده</p>"
    out = clean_caption(src)
    assert "x < 5" in out and "y > 2" in out, f"متن خورده شد: {out!r}"


# ── ۴) تلهٔ ۲: موجودیت‌ها ────────────────────────────────────────────
def test_html_entities_are_unescaped():
    out = clean_caption("<p>A &amp; B &#8217;test&#8217;</p>")
    assert "&amp;" not in out and "&#8217;" not in out
    assert "A & B" in out and "’test’" in out


def test_nbsp_becomes_an_ordinary_space():
    """`&nbsp;` → `\\xa0` که `clean_caption` جمعش نمی‌کند (الگویش `[ \\t]{2,}`)."""
    assert "\xa0" not in clean_caption("<p>A &nbsp;&nbsp; B</p>")


# ── ۵) ترتیب: strip قبل از unescape ──────────────────────────────────
def test_deliberately_escaped_markup_stays_text():
    """ترتیبِ برعکس متنی را که مبدأ عمداً escape کرده **می‌خورد**.

    اجراشده: با unescape-اول، `&lt;script&gt;alert(1)&lt;/script&gt;` می‌شد
    `alert(1)`. با ترتیبِ درست متنِ لفظی می‌ماند و `post_view` دوباره escapeاش
    می‌کند، پس امنیت تضعیف نمی‌شود.
    """
    out = clean_caption("<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>")
    assert out == "<script>alert(1)</script>"


# ── ۶) تصمیمِ «ب»: آدرسِ لینک حفظ شود ────────────────────────────────
def test_an_anchor_keeps_both_its_text_and_its_url():
    assert clean_caption('<p>حمایت: <a href="https://x.io/pay">اینجا</a></p>') \
        == "حمایت: اینجا (https://x.io/pay)"


def test_an_empty_anchor_falls_back_to_the_url():
    """تنها اطلاعاتی که دارد همان آدرس است؛ حذفش تحویلِ ناقصِ بی‌نشانه بود."""
    assert clean_caption('<p>لینک: <a href="https://x.io/pay"></a></p>') \
        == "لینک: https://x.io/pay"


def test_a_url_already_in_the_anchor_text_is_not_repeated():
    assert clean_caption('<p><a href="https://x.io/p">https://x.io/p</a></p>') \
        == "https://x.io/p"


def test_a_non_http_anchor_contributes_no_url():
    """`mailto:`/`javascript:` نباید در متن بنشیند."""
    assert clean_caption('<p><a href="mailto:a@b.com">ایمیل</a></p>') == "ایمیل"
    assert clean_caption('<p><a href="javascript:alert(1)">کلیک</a></p>') == "کلیک"


# ── ۷) سقف: هست و نشانه دارد ─────────────────────────────────────────
def test_the_cap_still_applies_and_is_not_silent():
    """فیکسچرِ **دست‌سازِ بلند** — نمونهٔ واقعی کوتاه است و سقف رویش شلیک نمی‌کند."""
    long_html = "<p>" + ("متنِ بلند " * 300) + '<a href="https://x.io/l">ل</a></p>'
    out = clean_caption(long_html)
    assert len(out) <= 1024
    assert out.endswith("…"), "برش خاموش است — کاربر نمی‌فهمد متن ناقص شده."


# ── ۸) HTMLِ خراب نباید کپشن را از بین ببرد ──────────────────────────
def test_malformed_html_still_yields_text():
    assert "ناتمام" in clean_caption("<p>ناتمام <strong>بدونِ بسته")


def test_strip_html_is_only_reached_through_the_gate():
    """`strip_html` مستقیم روی متنِ ساده **مخرب** است — دلیلِ وجودِ گیت.

    کنترلِ معکوس: اگر روزی این هم بی‌ضرر شد، گیت شاید دیگر لازم نباشد؛ تا آن
    روز، این تست ثابت می‌کند خطر واقعی است و فرضی نیست.
    """
    assert strip_html("کد: if (a<b) return;") != "کد: if (a<b) return;"
    assert clean_caption("کد: if (a<b) return;") == "کد: if (a<b) return;"
