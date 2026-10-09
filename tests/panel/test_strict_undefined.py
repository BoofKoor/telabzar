"""هر صفحه با `StrictUndefined` هم رندر شود — کلیدِ **غایب** باید صریح اختیاری باشد.

در Jinja کلیدی که در dict نیست `Undefined` است، **نه** `None`: در متن خالی رندر
می‌شود و در شرطِ ساده نادرست است، پس بیشترِ وقت‌ها بی‌صدا می‌گذرد — تا روزی که به
یک عمل برسد. نمونهٔ واقعیِ همین بازطراحی (۲۰۲۶-۱۰): ردیفِ سرویسِ pot کلیدِ `ms`
نداشت، `s.ms is not none` برای `Undefined` **صادق** است، و `f.num(Undefined)`
صفحهٔ `/system` را ۵۰۰ می‌کرد — فقط وقتی pot **سالم** بود، یعنی حالتِ عادیِ تولید.

تولید عمداً همان `Undefined`ِ نرم را نگه می‌دارد (یک کلیدِ گم‌شده نباید کلِ صفحه را
بخواباند)؛ این تست در عوض هر جای «شاید نباشد» را مجبور می‌کند صریح باشد:
`x.get('k')`، یا کلید همیشه در دادهٔ پایتونی ست شود. اولین اجرا شش مورد پیدا کرد
(`form.code`، `x.sub`/`mono`، `it.ph`/`plat`، `g.more`، `e.at`) به‌علاوهٔ همان `ms`.
"""
from __future__ import annotations

import pytest
from jinja2 import StrictUndefined, UndefinedError
from test_pages_render import PAGES


@pytest.fixture
def strict(monkeypatch):
    from app import admin_web as aw
    monkeypatch.setattr(aw.ENV, "undefined", StrictUndefined)
    return aw


def test_the_strict_mode_really_raises(strict):
    """کنترلِ منفی: اگر این نیفتد، کلِ فایل دربارهٔ هیچ‌چیز است."""
    with pytest.raises(UndefinedError):
        strict.ENV.from_string("{{ x.missing + 1 }}").render(x={})
    with pytest.raises(UndefinedError):
        strict.ENV.from_string("{% if x.missing %}y{% endif %}").render(x={})
    assert strict.ENV.from_string("{{ x.get('missing') or '-' }}").render(x={}) == "-"


@pytest.mark.parametrize("path", PAGES)
async def test_every_page_renders_strictly_with_data(seeded, strict, path):
    r = await seeded.client.get(path, cookies=seeded.cookies, allow_redirects=False)
    assert r.status == 200, (path, (await r.text())[:300])


@pytest.mark.parametrize("path", [p for p in PAGES if "open=" not in p and "dl=" not in p
                                  and "job=" not in p])
async def test_every_page_renders_strictly_on_an_empty_install(panel, strict, path):
    r = await panel.client.get(path, cookies=panel.cookies, allow_redirects=False)
    assert r.status == 200, (path, (await r.text())[:300])


@pytest.mark.parametrize("path", ["/", "/activity?tab=log", "/settings", "/system", "/reports"])
async def test_the_english_panel_renders_strictly(seeded, strict, path):
    r = await seeded.client.get(path, cookies={**seeded.cookies, "tab_lang": "en"},
                                allow_redirects=False)
    assert r.status == 200, path


async def test_the_login_page_renders_strictly(panel, strict):
    r = await panel.client.get("/login")
    assert r.status == 200
    r = await panel.client.get("/login?e=wrong")
    assert r.status == 200
