"""کارتی که فقط بخشی از کار را می‌شمارد باید دامنه‌اش را **بگوید**.

دو مورد، هر دو از یک ردهٔ «عدد درست است، معنی‌اش غلط فهمیده می‌شود».

**۱ — «عملیات» دانلودها را نمی‌شمارد.** `Job()` فقط در `routers/ops.py:172,184`
ساخته می‌شود، و `tasks_download.py:7` صریح می‌گوید «جابِ دانلود، رکوردِ
File/Job از پیش ندارد» — یعنی طراحیِ عمدی، نه فراموشی. ولی نتیجه‌اش این است که
هشت سطحِ jobs-محورِ `/stats` صفر دانلود می‌بینند، در حالی که همان صفحه
«فایل · N از لینک» را از `files` می‌گیرد و همه‌شان را دارد. با اعدادِ تولید
(۳۲۰۴ فایلِ دانلودی از ۴۰۵۰ در برابرِ ۱۰۱۶ جاب) یعنی ~۷۹٪ کار در کارتِ کناری
نامرئی است. تصمیم (اپراتور): **برچسب**، نه ساختنِ Job — مسئله گمراهی است نه
نبودِ عدد. گزینهٔ «Job برای دانلودها» با هزینه‌اش در §۷ ثبت شد.

**۲ — کارتِ نرخِ دانلود پنجرهٔ یک‌روزهٔ UTC دارد.** `_health` کلیدِ
`dlstat:{p}:ok:{روزِ جاریِ UTC}` را می‌خواند در حالی که `_metric` با TTLِ **دو
روز** می‌نویسد، پس یک `KEYS dlstat:*`ِ دستی عددِ بزرگ‌تری می‌دهد و مستقیماً
قابلِ مقایسه نیست. همین یک بار اپراتور را گمراه کرد («۳۳٪ · ۱ از ۳» در پنل در
برابرِ ۱۱ و ۷ در Redis — دو پنجرهٔ متفاوت، نه دو منبعِ متفاوت). و «امروز» برای
کاربرِ ایرانی بس نیست: روزِ تهران با روزِ UTC یکی نیست.
"""
from __future__ import annotations

import re

from test_panel_css_classes import _fetch


def _card(html: str, marker: str) -> str:
    """بدنهٔ کارتی که `marker` در سربرگش هست."""
    for block in re.split(r'<div class=card', html):
        if marker in block[:400]:
            return block
    raise AssertionError(f"کارتِ «{marker}» پیدا نشد")


# ── ۱: دامنهٔ کارت‌های jobs-محور ────────────────────────────────────────────
async def test_the_stats_page_says_which_numbers_exclude_downloads(seeded):
    """یک توضیحِ صریح، یک‌بار — به‌جای شش تکرار روی شش کارت."""
    html = await _fetch(seeded, "/stats")
    assert "دانلودها در این عددها نیستند" in html
    assert "/health" in html, "باید به جایی که نرخِ دانلود هست ارجاع بدهد"


async def test_the_operations_kpi_states_its_scope(seeded):
    html = await _fetch(seeded, "/stats")
    assert "<em>عملیات روی فایل</em>" in html
    assert "<em>عملیات</em>" not in html, "برچسبِ بی‌قیدِ «عملیات» برگشته"


async def test_the_jobs_backed_cards_are_tagged(seeded):
    """سه کارتی که مستقیم از `jobs` می‌آیند."""
    html = await _fetch(seeded, "/stats")
    assert "بدونِ دانلود" in _card(html, "پرکاربردترین عملیات")
    assert "بدونِ دانلود" in _card(html, "کارایی هر عملیات")
    assert "فقط عملیات روی فایل" in _card(html, "پرتکرارترین خطاها")


async def test_the_trend_legend_states_its_scope(seeded):
    html = await _fetch(seeded, "/stats")
    trend = _card(html, "روند")
    assert "عملیات روی فایل" in trend
    assert "شاملِ دانلود" in trend, "سریِ «فایل» دانلودها را دارد و باید بگوید"


async def test_the_file_side_cards_are_not_tagged_as_ops_only(seeded):
    """کنترلِ معکوس: کارت‌های `files`-محور دانلود را **می‌بینند** و نباید برچسب بخورند.

    بدونِ این، «برچسب همه‌جا بزن» هم سبز می‌شد و برچسب معنایش را از دست می‌داد.
    """
    html = await _fetch(seeded, "/stats")
    for marker in ("پلتفرمِ دانلود", "منبعِ فایل"):
        assert "بدونِ دانلود" not in _card(html, marker), (
            f"کارتِ «{marker}» از `files` می‌آید و دانلودها را دارد")


async def test_the_numbers_themselves_did_not_move(seeded):
    """برچسب‌گذاری نباید هیچ عددی را عوض کند — گزینهٔ «پ» فقط متن است.

    دادهٔ کاشته‌شده ۴ فایلِ دانلودی (بدونِ Job) و ۱ آپلود با ۳ جاب دارد.
    """
    from app import admin_web as aw

    s = await aw._stats("all")
    assert s["files"] == 5 and s["dl_files"] == 4, "پیش‌شرطِ تست عوض شده"
    assert s["ops"] == 3, "این عدد باید همچنان فقط jobs را بشمارد"


# ── ۲: پنجرهٔ کارتِ نرخِ دانلود ──────────────────────────────────────────────
async def test_the_download_rate_card_names_its_timezone(seeded):
    html = await _fetch(seeded, "/health")
    card = _card(html, "نرخِ موفقیتِ دانلود")
    assert "امروز (UTC)" in card, "برچسبِ «امروز» بدونِ منطقهٔ زمانی گمراه‌کننده است"


async def test_the_download_rate_card_really_reads_one_utc_day(seeded):
    """اثباتِ اینکه برچسب راست می‌گوید.

    کلیدِ **دیروز** ست می‌شود و کارت نباید تکان بخورد — وگرنه برچسبِ «امروز»
    خودش یک ادعای نادرستِ تازه است. دادهٔ کاشته‌شده امروز ۱ موفق و ۲ ناموفق است.
    """
    from datetime import datetime, timedelta, timezone

    yday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
    await seeded.redis.set(f"dlstat:soundcloud:ok:{yday}", 10)
    await seeded.redis.set(f"dlstat:soundcloud:fail:{yday}", 5)

    html = await _fetch(seeded, "/health")
    card = _card(html, "نرخِ موفقیتِ دانلود")
    assert "33% · 1/3" in card, (
        "کارت باید فقط روزِ جاریِ UTC را بدهد؛ اگر عددِ دیروز داخلش آمده، "
        "برچسبِ «امروز (UTC)» دروغ است.")
