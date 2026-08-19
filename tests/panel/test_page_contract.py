"""کفِ قراردادِ هر صفحه: ۲۰۰ بدهد — **هم با داده، هم بدونِ داده**.

دو موردِ §۴٫۵ سندِ بازطراحی، و هر دو با اجرا تأیید شد که واقعاً غایب‌اند نه
صرفاً کم‌رنگ: امروز هر هشت صفحه روی دادهٔ خالی ۲۰۰ می‌دهند و فرگمنتِ سلامت روی
`/` هم رندر می‌شود — ولی **هیچ تستی هیچ‌کدام را assert نمی‌کند**.

**چرا «دادهٔ خالی» جدا از «دادهٔ پر» لازم است.** شاخهٔ `{% else %}`ِ یک حلقه با
fixtureِ `seeded` هرگز اجرا نمی‌شود، و شاخه‌ای که اجرا نشود می‌تواند در بازآرایی
بشکند بی‌آنکه کسی بفهمد — دقیقاً همان چیزی که برای `{% if health.disk_total %}`
اتفاق افتاده بود (در `test_health_page` ثبت شده): آن شاخه در **هیچ** تستی اجرا
نمی‌شد. استقرارِ تازه هم همین حالت است، پس این کف دربارهٔ یک حالتِ واقعی است نه
یک حالتِ ساختگی.

**و فرگمنتِ مشترک باید روی هر دو صفحه سنجیده شود** (ریسکِ ۴ سند):
`_HEALTH_CARDS` عضوِ `DictLoader` نیست، بلکه با الحاقِ **رشته‌ایِ پایتون** در دو
جا داخلِ `_SETTINGS` و `_HEALTH` نشانده می‌شود (`admin_web.py:506,708`). یعنی
اگر استخراج آن را به `{% include %}` تبدیل کند، شکستنش روی یکی از دو صفحه
کاملاً ممکن است در حالی که دیگری سالم بماند. تست‌های `test_health_page` همه
`/health` را می‌زنند، پس نیمهٔ داشبورد تا امروز پوشش نداشت.
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


@pytest.mark.parametrize("path", ["/", "/health"])
async def test_the_shared_health_partial_renders_on_both_pages(seeded, path):
    """`_HEALTH_CARDS` روی داشبورد و صفحهٔ سلامت — همان محتوا، دو مسیرِ رندر.

    ادعا روی **مقدار** است نه مارک‌آپ، و مقدار از خودِ `_health()` می‌آید: اگر
    استخراج یکی از دو محلِ الحاق را جا بیندازد، همین‌جا قرمز می‌شود.
    """
    from app import admin_web as aw

    health = await aw._health(seeded.client.server.app)
    html = await _fetch(seeded, path)
    shows(html, health["q_main"], health["q_dl"], "Postgres", "pot-provider")


async def test_the_partial_is_not_silently_one_sided(seeded):
    """کنترلِ معکوس: دو صفحه باید **همان** اعداد را بدهند، نه یکی خالی.

    بدونِ این، تستِ بالا با قالبی که فرگمنت را فقط در یکی رندر کند و در دیگری
    عددها را از جای دیگری بیاورد هم می‌توانست سبز بماند.
    """
    from app import admin_web as aw

    health = await aw._health(seeded.client.server.app)
    dash = await _fetch(seeded, "/")
    hp = await _fetch(seeded, "/health")
    for fact in (health["q_main"], health["q_proc"], health["q_dl"], health["dl_active"]):
        assert str(fact) in dash and str(fact) in hp, (
            f"«{fact}» روی هر دو صفحه نیست — فرگمنتِ مشترک یک‌طرفه شده")
