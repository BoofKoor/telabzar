"""کنترل‌های منفیِ `pagefacts` — پیش از آنکه هیچ ادعایی رویش بنا شود.

§۶: هر بنچی پیش از اینکه عددِ سبزش معنا داشته باشد باید نشان دهد نسخهٔ خراب را
**می‌گیرد**. این‌جا سه کانالِ «متنی که ارسال می‌شود ولی دیدنی نیست» جدا جدا زده
می‌شوند، چون هر سه یک‌بار در این ریپو گاردی را کور کرده‌اند یا می‌توانند بکنند.

نکتهٔ ظریفی که این فایل را از یک کنترلِ معمولی جدا می‌کند: کنترلی که فقط ثابت
کند «چک می‌تواند بیفتد» این تله را **پوشش نمی‌دهد**. چک می‌تواند بیفتد؛ چیزی که
نمی‌تواند، افتادن روی همان ورودی‌ای است که سورسِ خودش تضمین می‌کند وجود دارد.
پس هر کنترل مستقیماً خودارجاعی را می‌زند.
"""
from __future__ import annotations

from pagefacts import missing_facts, page_text, shows


def test_a_fact_the_page_really_shows_is_found():
    """کنترلِ مثبت: بدونِ این، «هیچ چیزی گم نشد» می‌تواند یعنی «چک کور است»."""
    assert missing_facts("<div><b>137</b> صفِ پردازش</div>", ["137", "صفِ پردازش"]) == []


def test_a_fact_named_only_inside_a_css_comment_is_reported_missing():
    """دقیقاً همان چیزی که یک‌بار گاردِ کلاسِ CSS را کور کرد.

    کامنتِ CSS داخلِ `<style>` به مرورگر **ارسال می‌شود**، پس یک اسکنِ خامِ متن
    نامی را که فقط در نثرِ توضیحی آمده «موجود» می‌خواند. `_CSS` امروز ۶ کامنت
    دارد، یعنی این ورودی فرضی نیست.
    """
    html = "<style>/* عددِ 137 را این‌جا توضیح می‌دهیم ولی نشانش نمی‌دهیم */.a{color:red}</style><div>سلام</div>"
    assert missing_facts(html, ["137"]) == ["137"]


def test_a_fact_named_only_inside_an_html_comment_is_reported_missing():
    """امروز صفر کامنتِ HTML هست — و دقیقاً به همین دلیل نوشته می‌شود.

    بازطراحیِ §۵ می‌تواند اضافه کند، و آن روز کسی این فایل را باز نمی‌کند.
    """
    assert missing_facts("<div><!-- 137 جابِ در صف --></div>", ["137"]) == ["137"]


def test_a_fact_named_only_inside_a_script_is_reported_missing():
    """`/buttons` اسکریپتِ درون‌خطی دارد؛ محتوای آن «متنِ دیدنی» نیست."""
    assert missing_facts("<script>var q=137;</script><div>خالی</div>", ["137"]) == ["137"]


def test_two_numbers_in_adjacent_tags_do_not_fuse():
    """`<b>10</b><b>2</b>` نباید «۱۰۲» بدهد.

    اگر تگ با رشتهٔ تهی جایگزین شود، ادعای «۱۰۲ در صفحه هست» تصادفی سبز می‌شود —
    یعنی دقیقاً همان ادعای ضعیفی که کلِ این هلپر برای جلوگیری از آن است.
    """
    assert missing_facts("<b>10</b><b>2</b>", ["102"]) == ["102"]
    assert missing_facts("<b>10</b><b>2</b>", ["10", "2"]) == []


def test_escaped_markup_the_page_shows_literally_survives():
    """ترتیب: تگ‌ها از متنِ خام، بعد entityها.

    برعکسش متنی را که صفحه عمداً escape کرده می‌خورد — همان باگی که
    `downloader.strip_html` هم برایش ترتیب دارد.
    """
    assert "<b>" in page_text("<div>&lt;b&gt;</div>")


def test_shows_names_the_missing_fact():
    """پیامِ شکست باید بگوید چه چیزی گم شده، وگرنه دیباگش از صفر است."""
    try:
        shows("<div>هیچ</div>", "137")
    except AssertionError as exc:
        assert "137" in str(exc)
    else:
        raise AssertionError("shows باید روی واقعیتِ غایب بیفتد")


# ── `hidden` و `<template>` (۲۰۲۶-۱۰-۰۹) ─────────────────────────────────────
def test_a_fact_inside_a_hidden_subtree_is_reported_missing():
    """`/texts` و `/settings` فیلتر را با `hidden` اعمال می‌کنند؛ ردیفِ پنهان دیدنی نیست.

    بدونِ این، «جست‌وجو ردیفِ دیگر را کنار گذاشت» همیشه غلط خوانده می‌شد — ردیف
    در HTML هست، فقط پنهان است.
    """
    html = '<div><div hidden><div>137</div> نیمهٔ دوم</div><b>سلام</b></div>'
    assert missing_facts(html, ["137", "نیمهٔ دوم", "سلام"]) == ["137", "نیمهٔ دوم"]


def test_the_sibling_after_a_hidden_subtree_is_still_read():
    """کنترلِ معکوس: شمارشِ تودرتویی نباید بعد از زیردرختِ پنهان همه‌چیز را بخورد."""
    html = '<div hidden><div><div>x</div></div></div><p>137</p><div>صف</div>'
    assert missing_facts(html, ["137", "صف"]) == []


def test_template_content_is_not_visible_text():
    """`<template>` الگوی خامِ JS است — مرورگر نشانش نمی‌دهد."""
    assert missing_facts('<template><span>ویرایش‌شده</span></template><div>x</div>', ["ویرایش‌شده"]) \
        == ["ویرایش‌شده"]


def test_only_the_hidden_attribute_hides():
    """`aria-hidden` و `data-hidden` روی صفحه دیده می‌شوند؛ فقط خودِ `hidden` پنهان می‌کند."""
    html = '<div aria-hidden="true">۱۲</div><div data-hidden>۱۳</div><input hidden value="x"><b>۱۴</b>'
    assert missing_facts(html, ["۱۲", "۱۳", "۱۴"]) == []


def test_a_dropped_subtree_does_not_fuse_its_neighbours():
    """`۱۰<div hidden>…</div>۲` نباید «۱۰۲» بدهد — همان قاعدهٔ «تگ = فاصله»."""
    assert missing_facts("<p>10<span hidden>x</span>2</p>", ["102"]) == ["102"]
