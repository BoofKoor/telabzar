"""`/reports` — خودِ **اعداد** باید به صفحه برسند، نه فقط برچسب‌ها.

پیشینه (صفحهٔ آمارِ قدیم، `f00d37e`): پنج نگهبانِ محتوا، هر پنج دربارهٔ **برچسبِ**
دامنه. سابوتاژِ `{% for e in s.errors %}` → `{% for e in [] %}` هیچ‌کدام را
نینداخت: کارتِ خطاها می‌توانست کاملاً خالی شود و برچسبش سرِ جایش بماند. پس هر
ادعای این فایل یک **مقدار** است، از همان `panel_data.reports` که هندلر می‌خواند، و
به **کارتِ خودش** محدود است — چون نثرِ صفحه و جدولِ همسایه همان واژه‌ها را دارند
(همان «سه منبع برای یک توکن» که §۶ ثبت کرده).
"""
from __future__ import annotations

from pagefacts import missing_facts, shows
from test_panel_css_classes import _fetch
# یک پیاده‌سازیِ `_card`، نه دو کپیِ دست‌نویس — همان قاعدهٔ `remove_cookie_file`.
from test_scope_labels import _card, _f, _report


async def test_the_recorded_error_reaches_the_errors_card(seeded):
    """متنِ دقیقِ `Job.error` — چون گروه‌بندیِ خطاهای عملیات روی همان متن است."""
    d = await _report()
    msgs = [e["msg"] for e in d["errors"] if e["src"] == "job"]
    assert msgs == ["ffmpeg exploded"], f"پیش‌شرطِ کاشت: {msgs}"
    shows(_card(await _fetch(seeded, "/reports"), _f().t("rp.errors")), *msgs)


async def test_a_download_error_shows_its_class_and_raw_message(seeded):
    """خطای دانلود: دستهٔ خوانا + متنِ خامِ موتور (برای تشخیص)، و شمارش."""
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.errors"))
    shows(card, f.err("login_required"), "HTTP Error 401: Unauthorized", f.num(2))


async def test_the_op_performance_table_names_and_counts_its_operations(seeded):
    """هر opِ تمام‌شده: نام، تعداد، نرخِ موفقیت — و opِ در صف (trim) نه."""
    d = await _report()
    rows = {o["op"]: o for o in d["ops"]}
    assert set(rows) == {"compress", "convert"}, f"پیش‌شرطِ کاشت: {sorted(rows)}"
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.ops"))
    shows(card, f.op("compress"), f.op("convert"), f.pct(1.0), f.pct(0.0))
    assert missing_facts(card, [f.op("trim")]) == [f.op("trim")], "جابِ در صف در جدولِ کارایی آمد"


async def test_the_file_type_split_is_rendered(seeded):
    """۴ ویدیو + ۱ صوت — جدولِ کنارِ دونات، با سهمِ هر نوع."""
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.kinds"))
    shows(card, f.kind("video"), f.num(4), f.kind("audio"), f.num(1), f.ratio(4, 5))


async def test_the_quality_bars_read_the_downloaded_videos(seeded):
    """چهار ویدیوی ۱۰۸۰p — برچسبِ کیفیت لاتین است (`1080p`)، شمارش فارسی."""
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.quality"))
    shows(card, f.res(1080), f.num(4))


async def test_the_user_languages_card_counts_each_language(seeded):
    """۱ فارسی + ۱ انگلیسی — نامِ زبان و شمارش، نه فقط نوارِ رنگی."""
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.langs"))
    shows(card, "fa", "en", f.ratio(1, 2))


async def test_an_empty_deployment_says_so_on_every_card(panel):
    """کنترلِ معکوس: شاخهٔ خالیِ هر کارت هم رندر می‌شود و حرف می‌زند."""
    f = _f()
    html = await _fetch(panel, "/reports")
    shows(_card(html, f.t("rp.errors")), f.t("rp.errors.none"))
    shows(_card(html, f.t("rp.ops")), f.t("d.ops.none"))
    shows(_card(html, f.t("rp.quality")), f.t("rp.quality.none"))
    shows(_card(html, f.t("rp.plat")), f.t("d.plat.none"))
