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


_EXTERNAL = re.compile(r"(?:src|href)=[\"']?https?://[^\"' >]+")


def _panel_asset_files() -> list[Path]:
    """هر فایلی که چیزی از آن به HTMLِ پنل می‌رسد — **کشف‌محور**.

    دامنه باید خودش رشد کند، وگرنه همان حفره‌ای که این تابع برایش نوشته شد
    دوباره باز می‌شود (پایینِ داکس‌استرینگِ تست).
    """
    app = ROOT / "app"
    return sorted([app / "admin_web.py", *app.glob("templates/*.html"),
                   *app.glob("static/css/*.css")])


def external_refs(paths) -> list[str]:
    out = []
    for p in paths:
        out += _EXTERNAL.findall(p.read_text(encoding="utf-8"))
    return out


def test_the_panel_has_no_external_resources_for_the_csp_to_break():
    """چیزی که `default-src 'self'` را امن می‌کند: صفر منبعِ خارجی.

    اگر روزی کسی یک CDN اضافه کند، CSP بی‌صدا بلاکش می‌کند و صفحه نیمه‌خراب
    می‌شود. این تست همان لحظه قرمز می‌شود.

    **و این تست یک‌بار بی‌صدا مرد — نه از تغییرِ کسی، بلکه از استخراجِ قالب‌ها.**
    تا پیش از آن فقط `app/admin_web.py` را می‌خواند، و اندازه‌گیری‌شده **هر ۲۰**
    موردِ `href=`/`src=` داخلِ **ثابت‌های قالب** بود و **صفر** در بقیهٔ فایل. پس
    لحظه‌ای که قالب‌ها به `app/templates/*.html` رفتند، این تست فایلی را اسکن
    می‌کرد که هیچ‌کدام را ندارد و **برای همیشه سبز می‌ماند** — دقیقاً همان ردهٔ
    «گاردِ دائماً سبز» که §۶ بارها ثبت کرده، این‌بار ساخته‌شده به‌دستِ همان
    کامیتی که استخراج را انجام داد. دامنه حالا کشف‌محور است.
    """
    files = _panel_asset_files()
    external = external_refs(files)
    assert not external, f"منبعِ خارجی که CSP بلاکش می‌کند: {external}"


def test_the_scope_really_covers_the_templates():
    """کنترلِ دامنه: «صفر منبعِ خارجی» نباید یعنی «صفر فایلِ اسکن‌شده».

    بدونِ این، حذفِ الگوی `templates/*.html` از `_panel_asset_files` هیچ‌چیز را
    قرمز نمی‌کند.
    """
    names = {p.name for p in _panel_asset_files()}
    assert "admin_web.py" in names
    assert "base.html" in names and "stats.html" in names
    assert sum(1 for n in names if n.endswith(".html")) >= 12, (
        f"قالب‌ها اسکن نمی‌شوند: {sorted(names)}")


def test_a_cdn_planted_in_a_template_is_caught(tmp_path):
    """کنترلِ منفی: چکر باید یک URLِ واقعی را داخلِ یک قالب بگیرد.

    روی یک قالبِ **موقت** اجرا می‌شود نه داخلِ درختِ ریپو: یک اجرای نیمه‌کاره
    نباید فایلِ آلوده جا بگذارد (§۷ — همان درسی که دفترچهٔ سابوتاژ داد). اینکه
    دامنهٔ واقعی هم قالب‌ها را می‌بیند، تستِ بالا جدا می‌سنجد.
    """
    good = tmp_path / "clean.html"
    good.write_text('<link rel=stylesheet href="/static/css/panel.css">', encoding="utf-8")
    assert external_refs([good]) == []

    bad = tmp_path / "poisoned.html"
    bad.write_text('<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
                   encoding="utf-8")
    assert external_refs([bad]) == ["src=\"https://cdn.jsdelivr.net/npm/chart.js"]
