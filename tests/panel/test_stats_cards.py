"""`/stats` — برچسب‌های دامنه نگهبان داشتند، خودِ **اعداد** نه.

اندازه‌گیری روی `f00d37e`: پنج نگهبانِ محتوا، هر پنج از PR #126 و هر پنج دربارهٔ
**برچسبِ** دامنه («بدونِ دانلود»، «عملیات روی فایل»). سابوتاژِ
`{% for e in s.errors %}` → `{% for e in [] %}` هیچ‌کدام را نینداخت: کارتِ
خطاها می‌توانست کاملاً خالی شود و برچسبش سرِ جایش بماند.

`test_the_numbers_themselves_did_not_move` در `test_scope_labels.py` هم عددها
را می‌سنجد ولی از `aw._stats("all")` — یعنی **تابع** را، نه رندر را. پس بینِ
«محاسبه درست است» و «صفحه نشانش می‌دهد» شکاف بود.
"""
from __future__ import annotations

from pagefacts import shows
from test_panel_css_classes import _fetch


async def test_the_recorded_error_reaches_the_errors_card(seeded):
    """متنِ دقیقِ `Job.error` — چون گروه‌بندیِ خطاها روی همان متن است.

    دادهٔ کاشته‌شده یک جابِ شکست‌خورده با «ffmpeg exploded» دارد.
    """
    from app import admin_web as aw

    s = await aw._stats("all")
    assert s["errors"], "پیش‌شرط: جابِ شکست‌خورده کاشته شده باشد"
    shows(await _fetch(seeded, "/stats"), s["errors"][0]["msg"])


async def test_the_headline_counts_reach_the_page(seeded):
    """فایل‌ها و عملیات — دو عددی که کلِ صفحه دورشان چیده شده."""
    from app import admin_web as aw

    s = await aw._stats("all")
    assert (s["files"], s["dl_files"], s["ops"]) == (5, 4, 3), (
        "دادهٔ کاشته‌شده عوض شده — پیش‌شرطِ این تست همان ۵/۴/۳ است")
    shows(await _fetch(seeded, "/stats"), s["files"], s["dl_files"], s["ops"])


async def test_the_file_source_split_is_rendered(seeded):
    """آپلود در برابرِ دانلود — تنها جایی از `/stats` که دانلودها را می‌بیند."""
    from app import admin_web as aw

    s = await aw._stats("all")
    shows(await _fetch(seeded, "/stats"), s["src_up"], s["src_dl"])


async def test_the_per_op_rows_name_their_operations(seeded):
    """کارتِ «پرکاربردترین عملیات» باید نامِ opها را بدهد نه فقط عدد.

    `_bars` برچسب را از قبل فارسی کرده و کلیدش `k` است — با اجرا معلوم شد، نه
    با خواندن: نسخهٔ اولِ این تست `r["op"]` می‌خواست و `KeyError` داد.
    """
    from app import admin_web as aw

    s = await aw._stats("all")
    assert s["by_op"], "پیش‌شرط: جاب کاشته شده باشد"
    labels = {r["k"] for r in s["by_op"]}
    assert labels == {aw._OP_FA[o] for o in ("compress", "convert", "trim")}, (
        f"دادهٔ کاشته‌شده عوض شده: {labels}")
    shows(await _fetch(seeded, "/stats"), *labels)


async def test_the_op_performance_table_names_its_operations(seeded):
    """جدولِ کارایی opِ **خام** را می‌دهد، نه برچسبِ فارسی — دو مسیرِ متفاوت."""
    from app import admin_web as aw

    s = await aw._stats("all")
    assert s["op_perf"], "پیش‌شرط: جاب کاشته شده باشد"
    shows(await _fetch(seeded, "/stats"), *[r["op"] for r in s["op_perf"]])


async def test_a_database_with_no_failures_says_so(panel):
    """کنترلِ معکوس: شاخهٔ خالی هم رندر می‌شود."""
    shows(await _fetch(panel, "/stats"), "خطایی ثبت نشده")
