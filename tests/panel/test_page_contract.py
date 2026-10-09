"""کفِ قراردادِ هر صفحه: ۲۰۰ بدهد — **هم با داده، هم بدونِ داده**.

**چرا «دادهٔ خالی» جدا از «دادهٔ پر» لازم است.** شاخهٔ `{% else %}`ِ یک حلقه با
fixtureِ `seeded` هرگز اجرا نمی‌شود، و شاخه‌ای که اجرا نشود می‌تواند در بازآرایی
بشکند بی‌آنکه کسی بفهمد. استقرارِ تازه هم همین حالت است، پس این کف دربارهٔ یک
حالتِ واقعی است نه ساختگی.

**و دادهٔ مشترک باید روی همهٔ صفحه‌ها یکی باشد.** از بازطراحیِ ۲۰۲۶-۱۰ صفحهٔ
`/health` جایش را به `/system` داده و چیزی که بینِ صفحه‌ها مشترک است «پوسته»
است (`admin_web._shell`): عمقِ صف در ستونِ کناری، نوارِ سرویس‌های داشبورد و
کارت‌های صفحهٔ سیستم همه از همان یک ساخت می‌خوانند. اگر صفحه‌ای عدد را از جای
دیگری بیاورد، دو صفحه دو عددِ متفاوت نشان می‌دهند — همان چیزی که این‌جا گرفته
می‌شود. عددها **کاشته‌شده و متمایز**ند (۱۳۷/۲۵۱/۱۴۹/۲۶۰)، چون «صفر» با «نرسید»
یکی است.
"""
from __future__ import annotations

import pytest
from pagefacts import shows
from test_panel_css_classes import PAGES, _fetch


@pytest.mark.parametrize("path", PAGES)
async def test_every_page_answers_on_an_empty_deployment(panel, path):
    """صفحه‌ای که روی دیتابیسِ خالی ۵۰۰ بدهد، اولین چیزی است که ادمینِ تازه می‌بیند."""
    resp = await panel.client.get(path, cookies=panel.cookies)
    assert resp.status == 200, f"{path} روی استقرارِ خالی → HTTP {resp.status}"


@pytest.mark.parametrize("path", PAGES)
async def test_every_page_answers_with_data(seeded, path):
    """و همان صفحه با داده — کنترلِ جفتِ بالا."""
    resp = await seeded.client.get(path, cookies=seeded.cookies)
    assert resp.status == 200, f"{path} با داده → HTTP {resp.status}"


@pytest.mark.parametrize("old, new", [("/health", "/system"), ("/stats", "/reports")])
async def test_the_old_addresses_still_lead_somewhere(panel, old, new):
    """نشانکِ مرورگرِ ادمین به صفحهٔ قدیم نباید ۴۰۴ بدهد."""
    resp = await panel.client.get(old, cookies=panel.cookies, allow_redirects=False)
    assert resp.status == 301 and resp.headers["Location"] == new


async def _queue_total(seeded) -> int:
    from app import admin_web as aw
    return sum((await aw._queue_depths(seeded.redis)).values())


async def test_the_system_page_lists_every_queue(seeded):
    """هر صفِ ARQ با عمقِ خودش — از همان `_QUEUES` که پوسته می‌خواند."""
    from app import admin_web as aw

    f = aw.Fmt("fa")
    depths = await aw._queue_depths(seeded.redis)
    assert sorted(depths.values()) == [137, 149, 251, 260], f"پیش‌شرطِ کاشت: {depths}"
    html = await _fetch(seeded, "/system")
    shows(html, *[name for _k, name in aw._QUEUES], *[f.num(n) for n in depths.values()])


@pytest.mark.parametrize("path", ["/", "/system", "/users", "/settings"])
async def test_the_shell_queue_total_is_the_same_everywhere(seeded, path):
    """ستونِ کناری روی **هر** صفحه همان مجموعِ صف را می‌گوید."""
    from app import admin_web as aw

    f = aw.Fmt("fa")
    total = await _queue_total(seeded)
    assert total == 137 + 251 + 149 + 260
    shows(await _fetch(seeded, path), f.t("sys.jobs", n=f.num(total)))


async def test_the_services_strip_and_the_system_page_agree(seeded):
    """«N از M سرویس سالم» روی داشبورد و صفحهٔ سیستم — یک منبع، یک عدد.

    کنترلِ معکوسِ داخلی: عدد از خودِ `_services` می‌آید نه هاردکد، و دو صفحه
    باید **همان** را بگویند — اگر یکی را از جای دیگری بخواند، این‌جا قرمز می‌شود.
    """
    from app import admin_web as aw

    f = aw.Fmt("fa")
    rows = await aw._services(seeded.client.server.app)
    assert len(rows) >= 4, f"پیش‌شرط: سرویس‌ها ساخته نشدند: {rows}"
    fact = f.t("d.svc", a=f.num(sum(1 for r in rows if r["ok"])), b=f.num(len(rows)))
    for path in ("/", "/system"):
        shows(await _fetch(seeded, path), fact)
