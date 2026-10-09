"""`/system` (جانشینِ `/health`) باید هر چیزی را که پوسته جمع کرده **بگوید**.

## پیشینه

اندازه‌گیریِ پوشش روی `f00d37e` نشان داد بدنهٔ اختصاصیِ `/health` **صفر** نگهبان
داشت: حذفِ «صفِ پردازش · دانلودِ فعال · نسخهٔ موتور · خطِ استخرِ کوکی · نوارِ دیسک»
هیچ تستی را نمی‌انداخت. از بازطراحیِ ۲۰۲۶-۱۰ سلامت در `/system` است (سرویس‌ها،
کار، دیسک، موتورها، گواهی‌ها) و استخرِ کوکی در کارتِ داشبورد؛ همان ادعاها آن‌جا.

## شکلِ ادعاها

روی **مقدار** نه مارک‌آپ، و مقدارِ انتظاری از همان تابعی که هندلر صدا می‌زند
(`_services`, `dl_active.count`, `_disk`, `ck.accounts`) — نه هاردکد. عددهای کاشته‌شده
عمداً سه‌رقمی و متمایزند (`conftest.seeded`): «۲ در صفحه هست» ادعای ضعیفی است.
"""
from __future__ import annotations

from pagefacts import missing_facts, shows
from test_panel_css_classes import _fetch


def _f():
    from app.admin_web import Fmt
    return Fmt("fa")


def _app(panel):
    return panel.client.server.app


def _svc_card(html: str, key: str) -> str:
    """کارتِ یک سرویس در `/system` — با برچسبِ همان سرویس."""
    label = _f().t("sy.svc." + key)
    for block in html.split('<div class="card svc">')[1:]:
        if f'<div class="n">{label}</div>' in block:
            return block.split('<div class="card svc">', 1)[0]
    raise AssertionError(f"کارتِ سرویسِ «{key}» رندر نشد")


# ── سرویس‌ها ─────────────────────────────────────────────────────────────────
async def test_every_service_reports_its_state(seeded):
    """هر سرویس نامش را **کنارِ** وضعیتش می‌دهد — سه حالت، سه برچسب."""
    from app import admin_web as aw

    rows = await aw._services(_app(seeded))
    html = await _fetch(seeded, "/system")
    f = _f()
    for r in rows:
        want = f.t("sy.ok") if r["ok"] else f.t("sy.unknown") if r["ok"] is None else f.t("sy.down")
        shows(_svc_card(html, r["key"]), want)


async def test_the_service_list_has_not_drifted(seeded):
    """گاردِ کشف: هر سرویسی که `_services` بسازد کارت می‌گیرد، و برعکس."""
    import re

    from app import admin_web as aw

    keys = {r["key"] for r in await aw._services(_app(seeded))}
    assert {"postgres", "redis"} <= keys, keys
    html = await _fetch(seeded, "/system")
    f = _f()
    labels = set(re.findall(r'<div class="card svc">.*?<div class="n">([^<]+)</div>', html, re.S))
    assert labels == {f.t("sy.svc." + k) for k in keys}


async def test_a_dead_database_is_reported_as_down(seeded, monkeypatch):
    """کنترلِ معکوس: «سالم» بی‌قیدوشرط نیست — پینگِ شکست‌خورده «قطع» می‌شود."""
    from app import admin_web as aw

    async def dead():
        raise ConnectionError("no route to postgres")

    monkeypatch.setattr(aw, "_pg_ping", dead)
    card = _svc_card(await _fetch(seeded, "/system"), "postgres")
    f = _f()
    shows(card, f.t("sy.down"), f.t("sy.down.s"))
    assert missing_facts(card, [f.t("sy.ok")]) == [f.t("sy.ok")]


# ── کار ──────────────────────────────────────────────────────────────────────
async def test_the_live_download_count_reaches_the_page(seeded):
    """۷۳ دانلودِ در جریان (کاشته از مسیرِ خودِ `dl_active`)، با سقفِ هم‌زمانی."""
    from app import dl_active

    n = await dl_active.count(seeded.redis)
    assert n == 73, f"پیش‌شرطِ کاشت: {n}"
    f = _f()
    shows(await _fetch(seeded, "/system"), f.t("sy.dl_active"), f.num(73))


async def test_the_stuck_jobs_line_counts_what_panel_data_counts(seeded):
    """جابِ گیرکرده همان عددی است که `stuck_jobs` می‌دهد — نه بازشماریِ قالب."""
    from app import panel_data as PD

    stuck = await PD.stuck_jobs()
    f = _f()
    shows(await _fetch(seeded, "/system"), f.t("sy.stuck"), f.num(stuck["n"]),
          f.t("sy.running"), f.num(stuck["running"]))


# ── دیسک ─────────────────────────────────────────────────────────────────────
async def test_the_disk_meter_reports_what_it_measured(seeded, monkeypatch):
    """`shutil.disk_usage` وصله می‌شود — `settings.work_dir` (`/work`) روی رانر نیست.

    بدونِ وصله شاخهٔ «دیسک سنجیده شد» در **هیچ** تستی اجرا نمی‌شد.
    """
    from collections import namedtuple

    from app import admin_web as aw

    du = namedtuple("du", "total used free")
    gib = 1024 ** 3
    monkeypatch.setattr(aw.shutil, "disk_usage", lambda _p: du(500 * gib, 120 * gib, 380 * gib))
    f = _f()
    shows(await _fetch(seeded, "/system"),
          f.t("sy.disk.s", u=f.size(120 * gib), t=f.size(500 * gib), f=f.size(380 * gib)),
          f.pct(120 / 500))


async def test_an_unmeasurable_disk_says_so(seeded, monkeypatch):
    """کنترلِ معکوس: شاخهٔ «نسنجیده» واقعی است، نه نوارِ همیشه‌روشن."""
    from app import admin_web as aw

    def boom(_p):
        raise OSError("no such directory")

    monkeypatch.setattr(aw.shutil, "disk_usage", boom)
    shows(await _fetch(seeded, "/system"), _f().t("sy.disk.none"))


# ── موتورها ──────────────────────────────────────────────────────────────────
async def test_the_engine_versions_reach_the_page(seeded):
    """اولین سؤالِ «پاسخِ نامعتبر»: موتور عقب افتاده یا سشن مرده؟

    ورکرِ مستر با نامِ خوانا («مستر») نشان داده می‌شود، نه شناسهٔ خامِ `master`.
    """
    f = _f()
    shows(await _fetch(seeded, "/system"), f.t("ck.exit.master"), "1.29", "2026.07.04")


async def test_a_worker_that_never_reported_says_so(seeded):
    """شاخهٔ خالی هم باید حرف بزند، نه اینکه کارت را ساکت کند."""
    await seeded.redis.delete("dlver:master")
    shows(await _fetch(seeded, "/system"), _f().t("sy.engines.none"))


# ── استخرِ کوکی (کارتِ داشبورد) ───────────────────────────────────────────────
async def test_the_cookie_pool_card_reports_each_platform_and_its_ready_count(seeded):
    """پلتفرم و «آماده از کل» کنارِ هم؛ «آماده» همان `cookies.USABLE` است.

    هفت اکانتِ اینستاگرام، یکی از هر وضعیت: آماده = سالم + بی‌سابقه + مشکوک.
    """
    from app import cookies as ck

    accs = await ck.accounts(seeded.redis)
    ready = sum(1 for a in accs if a["status"] in ck.USABLE)
    assert (ready, len(accs)) == (3, 7), f"پیش‌شرطِ کاشت: {ready}/{len(accs)}"
    f = _f()
    html = await _fetch(seeded, "/")
    card = html.split('class="card d-pool"', 1)[1].split("</section>", 1)[0]
    shows(card, f.plat("instagram"), f.t("d.pool.ready", a=f.num(ready), b=f.num(len(accs))))


async def test_an_empty_pool_says_so(panel):
    """کنترلِ معکوس روی `panel`ِ بی‌داده: شاخهٔ خالی هم رندر می‌شود."""
    shows(await _fetch(panel, "/"), _f().t("d.pool.none"))
