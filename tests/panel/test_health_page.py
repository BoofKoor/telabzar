"""`/health` باید هر چیزی را که `_health()` جمع کرده **بگوید**.

## چرا این فایل، و چرا حالا

اندازه‌گیریِ پوشش (بدنهٔ هر قالب را جدا خالی کن، ببین چند تست قرمز می‌شود) روی
`f00d37e` نشان داد `_HEALTH` شش تست می‌اندازد که **پنج‌تایش عیناً همان پنج‌تای
`_HEALTH_CARDS` است** و ششمی گاردِ کلاس است. یعنی بدنهٔ اختصاصیِ `/health` —
هرچه بیرونِ فرگمنتِ مشترک است — **صفر** نگهبان داشت.

و سابوتاژِ ریزدانه بدتر بود. این پنج حذف **هیچ** تستی را نینداختند:

    صفِ پردازش · دانلودِ فعال · نسخهٔ موتور · خطِ استخرِ کوکی · نوارِ دیسک

پس «قالب نگهبان دارد» فقط دربارهٔ بجِ pot و کارتِ نرخِ دانلود صادق بود.

## شکلِ ادعاها

روی **مقدار** بسته می‌شوند نه روی مارک‌آپ، چون گامِ بعدی همین صفحه را بازآرایی
می‌کند: جابه‌جاییِ کارت باید سبز بماند، افتادنِ عدد باید قرمز شود. مقدارِ
انتظاری هم از خودِ `_health()` گرفته می‌شود نه هاردکد، پس تست دربارهٔ «قالب
چیزی را که کد محاسبه کرده رندر می‌کند» حرف می‌زند، نه دربارهٔ یک عددِ ثابت.

عددهای کاشته‌شده عمداً **سه‌رقمی و متمایز**اند (`conftest.seeded`): در صفحه‌ای
که نرخِ درصدی و نسخهٔ `1.29` و گیگابایتِ دیسک هم دارد، «۲ در صفحه هست» ادعای
ضعیفی است. غیرِتصادفی‌بودنشان با سابوتاژ اثبات می‌شود نه با استدلال.
"""
from __future__ import annotations

import pytest
from pagefacts import page_text, shows
from test_panel_css_classes import _fetch

#: سرویس‌هایی که کارتِ «سلامتِ سرویس‌ها» ردیف می‌سازد: (متنِ صفحه, کلیدِ health).
#: صریح است — ولی `test_the_service_list_has_not_drifted` نگه‌داری‌اش می‌کند، پس
#: سرویسِ تازه‌ای که رندر نشود بی‌صدا رد نمی‌شود. همان شکلِ فهرستِ صریح +
#: گاردِ کشف که `_KNOWN_UNREACHABLE` و `_SESSIONMAKER_HOLDERS` هم دارند.
BOOL_SERVICES = [("Postgres", "postgres"), ("Redis", "redis")]


def _app(panel):
    return panel.client.server.app


# ── کارتِ سرویس‌ها ──────────────────────────────────────────────────────────
async def test_every_boolean_service_reports_its_state(seeded):
    """هر سرویس باید نامش را **کنارِ** وضعیتش بدهد، نه یکی از آن دو را."""
    from app import admin_web as aw

    health = await aw._health(_app(seeded))
    html = await _fetch(seeded, "/health")
    for label, key in BOOL_SERVICES:
        expected = "آنلاین" if health[key] else "خطا"
        shows(html, f"{label} {expected}")


async def test_the_pot_provider_row_reports_its_third_state(seeded):
    """pot سه‌حالته است و «تنظیم‌شده ولی نسنجیده» با «پیکربندی‌نشده» یکی نیست.

    در هارنس `pot_provider_url` تهی است، پس حالتِ قطعی «پیکربندی‌نشده» است.
    """
    from app import admin_web as aw

    health = await aw._health(_app(seeded))
    assert health["pot"] is None, "پیش‌شرطِ تست عوض شده — هارنس pot را تهی می‌گذارد"
    shows(await _fetch(seeded, "/health"), "pot-provider (یوتیوب) پیکربندی‌نشده")


async def test_the_service_list_has_not_drifted(seeded):
    """گاردِ کشف: سرویسِ تازه‌ای که به `_health` اضافه شود باید ردیف هم بگیرد.

    بدونِ این، `BOOL_SERVICES` یک فهرستِ دستی است که می‌پوسد — همان چیزی که §۶
    بارها ثبت کرده. `all_ok` مشتق است نه سرویس، پس کنار گذاشته می‌شود.
    """
    from app import admin_web as aw

    health = await aw._health(_app(seeded))
    booleans = {k for k, v in health.items() if isinstance(v, bool)} - {"all_ok"}
    assert booleans == {k for _l, k in BOOL_SERVICES}, (
        "مجموعهٔ سرویس‌های بولیِ `_health` عوض شده؛ اگر ردیفِ تازه‌ای لازم است "
        "هم قالب هم `BOOL_SERVICES` باید به‌روز شوند.")


# ── کارتِ صف و دیسک ─────────────────────────────────────────────────────────
async def test_every_queue_depth_reaches_the_page(seeded):
    """چهار عمقِ صف، هر کدام عددِ خودش.

    مقدارِ انتظاری از `_health()` می‌آید؛ ولی یک پینِ پیش‌شرط هم هست، وگرنه اگر
    روزی همهٔ صف‌ها صفر شوند این تست به «صفر در صفحه هست» تنزل می‌کند و بی‌صدا
    بی‌معنا می‌شود.
    """
    from app import admin_web as aw

    health = await aw._health(_app(seeded))
    depths = (health["q_main"], health["q_proc"], health["q_dl"], health["dl_active"])
    assert depths == (137, 251, 409, 73), (
        f"دادهٔ کاشته‌شده عوض شده ({depths}) — عددهای متمایز شرطِ معنادارییِ این تست‌اند")
    shows(await _fetch(seeded, "/health"), *depths)


async def test_the_disk_meter_reports_what_it_measured(seeded, monkeypatch):
    """`shutil.disk_usage` وصله می‌شود، و این یک قیدِ محیطی است نه سلیقه.

    `settings.work_dir` پیش‌فرضش `/work` است که نه در سندباکس هست نه روی رانر،
    پس `_health` استثنا می‌گیرد و `disk_total = 0` می‌گذارد — یعنی شاخهٔ
    `{% if health.disk_total %}` **در هیچ تستی اجرا نمی‌شد**. مکانیزمِ زیرِ
    سنجش «قالب عددی را که کد محاسبه کرده رندر می‌کند» است، و منبعِ آن عدد یک
    فراخوانیِ سیستمیِ محیط‌وابسته است؛ پس وصله‌کردنش تست را قطعی می‌کند بی‌آنکه
    مسیرِ واقعی را دور بزند.
    """
    from collections import namedtuple

    from app import admin_web as aw

    du = namedtuple("du", "total used free")
    gib = 1024 ** 3
    monkeypatch.setattr(aw.shutil, "disk_usage",
                        lambda _p: du(500 * gib, 120 * gib, 380 * gib))
    health = await aw._health(_app(seeded))
    assert (health["disk_used"], health["disk_total"]) == (120, 500)
    shows(await _fetch(seeded, "/health"), "120/500G")


async def test_an_unmeasurable_disk_hides_the_meter(seeded, monkeypatch):
    """کنترلِ معکوس: شاخهٔ `{% if %}` واقعی است، نه همیشه‌روشن.

    بدونِ این، تستِ بالا با قالبی که نوار را بی‌قیدوشرط رندر کند هم سبز می‌ماند.
    """
    from app import admin_web as aw

    def boom(_p):
        raise OSError("no such directory")

    monkeypatch.setattr(aw.shutil, "disk_usage", boom)
    assert (await aw._health(_app(seeded)))["disk_total"] == 0
    assert "G" not in page_text(await _fetch(seeded, "/health")).split("دیسک")[-1][:40]


# ── کارتِ نسخهٔ موتورها ─────────────────────────────────────────────────────
async def test_the_engine_versions_reach_the_page(seeded):
    """اولین سؤالِ «پاسخِ نامعتبر»: موتور عقب افتاده یا سشن مرده؟

    اگر این کارت بی‌صدا بیفتد، آن سؤال دوباره بی‌جواب می‌شود.
    """
    from app import admin_web as aw

    health = await aw._health(_app(seeded))
    assert health["engines"], "پیش‌شرط: `dlver:*` کاشته شده باشد"
    e = health["engines"][0]
    shows(await _fetch(seeded, "/health"), e["who"], e["gallery-dl"], e["yt-dlp"])


async def test_a_worker_that_never_reported_says_so(seeded):
    """شاخهٔ خالی هم باید حرف بزند، نه اینکه کارت را ساکت کند."""
    await seeded.redis.delete("dlver:master")
    shows(await _fetch(seeded, "/health"), "هنوز ورکرِ دانلودی نسخه‌اش را گزارش نکرده")


# ── کارتِ استخرِ کوکی ───────────────────────────────────────────────────────
async def test_the_cookie_pool_line_reports_each_platform_and_its_count(seeded):
    """پلتفرم و شمارِ سالمش کنارِ هم — نه یکی از آن دو.

    عدد به‌تنهایی در این صفحه ضعیف است و نامِ پلتفرم به‌تنهایی حذفِ شمارش را
    نمی‌گیرد، پس ادعا روی **جفت** بسته می‌شود. برچسبِ «سالم» واژگانِ پایدارِ
    دامنه است؛ اگر §۵ عوضش کند این تست قرمز می‌شود و همان‌جا یک خط به‌روز
    می‌شود — یعنی یک اعلانِ بازبینی، نه یک از‌دست‌رفتنِ خاموش.
    """
    from app import admin_web as aw
    from app import cookies as ck_pool

    summary = await ck_pool.pool_summary(seeded.redis)
    assert summary, "پیش‌شرط: اکانتِ کوکی کاشته شده باشد"
    html = await _fetch(seeded, "/health")
    for platform, d in summary.items():
        live = d["healthy"] + d["suspect"]
        shows(html, aw._PLATFORM_FA.get(platform, platform), f"{live} سالم")


async def test_an_empty_pool_says_so(panel):
    """کنترلِ معکوس روی `panel`ِ بی‌داده: شاخهٔ خالی هم رندر می‌شود."""
    shows(await _fetch(panel, "/health"), "کوکی‌ای ثبت نشده")
