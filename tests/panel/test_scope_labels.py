"""کارتی که فقط بخشی از کار را می‌شمارد باید دامنه‌اش را **بگوید** — یا جدا گزارشش کند.

**پیشینه (پنلِ پیش از ۲۰۲۶-۱۰).** «عملیات» دانلودها را نمی‌شمارد: `Job()` فقط در
`routers/ops.py` ساخته می‌شود و `tasks_download.py` صریح می‌گوید جابِ دانلود ردیفِ
`Job` ندارد. صفحهٔ آمارِ قدیم هشت سطحِ jobs-محور داشت که صفر دانلود می‌دیدند، و تصمیمِ
آن روز (اپراتور، ۲۰۲۶-۰۸-۱۸) **برچسبِ صریح** بود. و نرخِ موفقیتِ دانلود از
`dlstat:*`ِ یک‌روزهٔ UTC می‌آمد که با TTLِ دوروزه نوشته می‌شد — دو پنجرهٔ متفاوت.

**از بازطراحیِ ۲۰۲۶-۱۰ هر دو ریشه‌ای حل شده‌اند، نه با برچسب:** دانلود لاگِ ماندگارِ
خودش را دارد (`DownloadEvent`)، پس گزارش‌ها دانلود را **جدا** می‌شمارند (کارتِ پلتفرم،
تفکیکِ «از لینک / آپلود» زیرِ فایل‌ها، ستونِ «دانلود» کنارِ «عملیات» در کاربرانِ پرکار)
و «عملیات» همه‌جا یعنی کار روی فایل. نرخ از همان لاگ و روی **بازهٔ انتخاب‌شده** است، با
سطل‌های هم‌ترازِ روزِ تهران. این فایل همان قراردادها را نگه می‌دارد.

دادهٔ کاشته‌شده (`conftest.seeded`): ۴ فایلِ ساندکلاد بدونِ Job + ۱ آپلود با ۳ جاب ·
لاگِ دانلود: ساندکلاد ۴ موفق + ۲ ناموفق، اینستاگرام ۱ موفقِ کش‌خورده، یوتیوب ۱ ردشده.
"""
from __future__ import annotations

from pagefacts import missing_facts, shows
from test_panel_css_classes import _fetch


def _card(html: str, title: str) -> str:
    """بدنهٔ `<section class="card…">`ی که سربرگش `title` را دارد."""
    for block in html.split('<section class="card')[1:]:
        head = block[:600]
        if f"<h2>{title}</h2>" in head:
            return block.split("</section>", 1)[0]
    raise AssertionError(f"کارتِ «{title}» پیدا نشد")


def _f():
    from app.admin_web import Fmt
    return Fmt("fa")


async def _report(key: str = "30d") -> dict:
    from app import panel_data as PD
    return await PD.reports(key)


# ── «عملیات» = کار روی فایل؛ دانلود جدا شمرده می‌شود ─────────────────────────
async def test_the_operations_kpi_counts_jobs_not_downloads(seeded):
    """۳ جاب، با وجودِ ۸ رویدادِ دانلود — عدد نباید دانلودها را جمع کند."""
    d = await _report()
    assert d["jobs"][0] == 3, f"پیش‌شرطِ کاشت: {d['jobs']}"
    f = _f()
    card = _kpi(await _fetch(seeded, "/reports"), f.t("rp.k.ops"))
    shows(card, f.num(3), f.t("rp.k.ops.s", f=f.num(1)))


async def test_the_files_kpi_says_how_many_came_from_links(seeded):
    """تنها عددِ مشترکِ دانلود و آپلود، با تفکیکش — وگرنه «۵ فایل» دامنه ندارد."""
    d = await _report()
    assert (d["files"]["dl"][0], d["files"]["up"][0]) == (4, 1)
    f = _f()
    card = _kpi(await _fetch(seeded, "/reports"), f.t("rp.k.files"))
    shows(card, f.num(5), f.t("rp.k.files.s", dl=f.num(4), up=f.num(1)))


def _kpi(html: str, label: str) -> str:
    """کارتِ KPIِ همین برچسب — از `<div class="card kpi">` تا KPIِ بعدی."""
    for p in html.split('<div class="card kpi">')[1:]:
        if f'<span class="kpi-label">{label}</span>' in p:
            return p.split('<div class="kpi-sub">', 1)[0] + p.split('<div class="kpi-sub">', 1)[1].split("</div>", 1)[0]
    raise AssertionError(f"KPIِ «{label}» پیدا نشد")


async def test_the_top_users_table_keeps_downloads_and_operations_apart(seeded):
    """کاربرِ ۹۰۱: ۵ فایل، ۶ دانلود (۴ موفق + ۲ ناموفق)، ۳ عملیات — سه ستونِ جدا."""
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.top"))
    for col, n in (("rp.files", 5), ("rp.dls", 6), ("rp.opsn", 3)):
        assert f'data-l="{f.t(col)}">{f.num(n)}</td>' in card, f"ستونِ «{f.t(col)}» عددِ {n} را نمی‌گوید"


# ── نرخِ موفقیت: از لاگِ دانلود، روی همان بازه ───────────────────────────────
async def test_the_platform_rate_comes_from_the_download_log(seeded):
    """ساندکلاد ۴ از ۶؛ «ردشده» (حجم/سقف) در مخرج نیست چون شکستِ سرویس نیست."""
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.plat"))
    shows(card, f.plat("soundcloud"), f.pct(4 / 6), f.num(6))


async def test_a_platform_that_only_fails_is_still_reported(seeded):
    """پلتفرمی که هیچ فایلی نداد همان است که باید **دیده** شود، با نرخِ صفر.

    نسخهٔ اولِ گزارش ردیف‌ها را فقط از فایل‌ها می‌ساخت — یعنی پلتفرمِ کاملاً خراب
    از کارت ناپدید می‌شد (اجراشده).
    """
    import datetime as dt

    from app.models import DownloadEvent

    # توییتر یکی از پلتفرم‌های رنگ‌دارِ `PD.PLATS` است؛ بقیه عمداً در «سایر» جمع
    # می‌شوند (پالتِ دسته‌ای محدود است) و آن‌جا نامِ خودشان دیده نمی‌شود.
    async with seeded.maker() as s:
        for _ in range(3):
            s.add(DownloadEvent(platform="twitter", outcome="fail", error_class="unrelated",
                                created_at=dt.datetime.now(dt.timezone.utc)))
        await s.commit()
    await seeded.redis.flushdb()            # کشِ گزارش
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.plat"))
    row = card.split(f.plat("twitter"), 1)
    assert len(row) == 2, "ردیفِ توییتر (فقط شکست) در کارت نیست"
    shows(row[1].split('<div class="sm-row">', 1)[0], f.pct(0.0), f.num(3))


async def test_refused_downloads_are_not_failures(seeded):
    """کنترلِ معکوس: یوتیوب فقط یک «ردشده» دارد و نباید ردیفِ پلتفرم با نرخ بگیرد."""
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.plat"))
    assert missing_facts(card, [f.plat("youtube")]) == [f.plat("youtube")]


async def test_errors_name_their_source(seeded):
    """خطاهای پرتکرار حالا هر دو منبع را دارند — و هر ردیف می‌گوید از کجاست."""
    f = _f()
    card = _card(await _fetch(seeded, "/reports"), f.t("rp.errors"))
    shows(card, f.err("login_required"), f.plat("soundcloud"),   # دانلود
          "ffmpeg exploded", f.op("convert"))                    # عملیات


async def test_the_numbers_themselves_did_not_move(seeded):
    """گزارش‌دادنِ جدای دانلود نباید هیچ عددِ jobs-محوری را عوض کند."""
    d = await _report("all")
    assert d["jobs"][0] == 3, "این عدد باید همچنان فقط jobs را بشمارد"
    assert sum(o["n"] for o in d["ops"]) == 2, "جدولِ کارایی فقط کارهای تمام‌شده را دارد"
