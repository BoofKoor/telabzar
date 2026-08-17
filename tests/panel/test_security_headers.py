"""هدرهای امنیتیِ پنل.

`Referrer-Policy` عمداً این‌جا نیست — آن بخشی از رفعِ نشتِ توکنِ join است و
تستش کنارِ همان می‌ماند (`test_security_characterization`). این فایل دربارهٔ
سخت‌سازیِ عمومی است: clickjacking، MIME sniffing، CSP، و HSTS.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


async def test_the_hardening_headers_are_on_an_ordinary_page(panel):
    resp = await panel.client.get("/", cookies=panel.cookies)
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


async def test_they_survive_redirects_and_errors(panel):
    """همان دلیلِ middleware: ریدایرکت‌ها و ۴۰۴ هم باید پوشش داشته باشند."""
    redirect = await panel.client.get("/", allow_redirects=False)
    assert redirect.status == 302
    assert redirect.headers["X-Frame-Options"] == "DENY"

    missing = await panel.client.get("/no-such-page")
    assert missing.status == 404
    assert missing.headers["X-Frame-Options"] == "DENY"


async def test_hsts_is_sent_only_over_https(panel):
    """روی HTTPِ ساده نباید فرستاده شود.

    نصبِ بدونِ دامنه پنل را روی HTTP سرو می‌کند (`_ssl_context` بی‌سرتیفیکیت
    `None` می‌دهد)؛ HSTSِ بی‌قید مرورگر را برای آن هاست به HTTPSِ ناموجود قفل
    می‌کند و پنل از دسترس خارج می‌شود.
    """
    plain = await panel.client.get("/", cookies=panel.cookies)
    assert "Strict-Transport-Security" not in plain.headers

    proxied = await panel.client.get("/", cookies=panel.cookies,
                                     headers={"X-Forwarded-Proto": "https"})
    assert proxied.headers["Strict-Transport-Security"].startswith("max-age=")


async def test_the_csp_permits_what_the_panel_actually_serves(panel):
    """CSP باید با چیزی که پنل واقعاً می‌فرستد جور باشد.

    کلِ طراحی یک `<style>`ِ درون‌خطی است و صفحهٔ `/buttons` یک `<script>`ِ
    درون‌خطی دارد؛ CSPی که این دو را ندهد صفحه را **خالی و بی‌کارکرد** می‌کند
    و هیچ تستِ HTTPی هم متوجه نمی‌شود، چون سرور همچنان ۲۰۰ می‌دهد.
    """
    resp = await panel.client.get("/buttons", cookies=panel.cookies)
    csp = resp.headers["Content-Security-Policy"]
    body = await resp.text()
    assert "<style>" in body and "<script>" in body, "پیش‌شرضِ تست عوض شده"
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "script-src 'self' 'unsafe-inline'" in csp


def test_the_panel_has_no_external_resources_for_the_csp_to_break():
    """چیزی که `default-src 'self'` را امن می‌کند: صفر منبعِ خارجی.

    اگر روزی کسی یک CDN اضافه کند، CSP بی‌صدا بلاکش می‌کند و صفحه نیمه‌خراب
    می‌شود. این تست همان لحظه قرمز می‌شود و می‌گوید یا منبع را محلی کن یا CSP
    را آگاهانه عوض کن.
    """
    src = (ROOT / "app" / "admin_web.py").read_text(encoding="utf-8")
    external = re.findall(r"(?:src|href)=[\"']?https?://[^\"' >]+", src)
    assert not external, f"منبعِ خارجی که CSP بلاکش می‌کند: {external}"
