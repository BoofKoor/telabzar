"""مسیرِ `/console/...` — کنسولِ Next که پنل به‌شکلِ ایستا سرو می‌کند.

ادعاها در سطوحِ مستقل، چون هر کدام جدا می‌شکند:

  ۱. HTML بی‌نشست → `/login`. کنسول همان دادهٔ عملیاتی را نشان می‌دهد که
     بقیهٔ پنل.
  ۲. **دارایی** گِیت ندارد — تفکیک روی نوعِ فایل است، نه مسیر.
  ۳. زیرصفحه (`/console/health/`) باید به `health/index.html` برسد. خروجیِ
     Next دایرکتوری‌محور است و `add_static` دایرکتوری را باز نمی‌کند، پس
     بدونِ این تبدیل هر صفحه‌ای جز خانه ۴۰۴ می‌شد — کلاسی از شکست که فقط
     وقتی دیده می‌شود که کسی روی منو کلیک کند.
  ۴. پیمایشِ مسیر باید رد شود.
  ۵. بدونِ build → ۵۰۳ با دستورِ ساختن، نه ۵۰۰.
"""
from __future__ import annotations

import pathlib

import pytest


@pytest.fixture
def built(panel, monkeypatch, tmp_path):
    """یک خروجیِ کوچکِ شبیهِ `next build`: خانه، زیرصفحه و یک دارایی."""
    root = tmp_path / "console"
    (root / "health").mkdir(parents=True)
    (root / "_next" / "static").mkdir(parents=True)
    (root / "index.html").write_text("<!DOCTYPE html><title>console</title>OVERVIEW", encoding="utf-8")
    (root / "health" / "index.html").write_text("<!DOCTYPE html>HEALTH PAGE", encoding="utf-8")
    (root / "_next" / "static" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(panel.aw, "_CONSOLE_DIR", str(root))
    return panel


async def test_the_console_needs_a_session(built):
    r = await built.client.get("/console", allow_redirects=False)
    assert r.status == 302
    assert r.headers["Location"] == "/login"


async def test_a_sub_page_needs_a_session_too(built):
    r = await built.client.get("/console/health/", allow_redirects=False)
    assert r.status == 302


async def test_the_console_serves_the_built_page(built):
    r = await built.client.get("/console", cookies=built.cookies)
    assert r.status == 200
    assert "OVERVIEW" in await r.text()


@pytest.mark.parametrize("path", ["/console/health/", "/console/health"])
async def test_a_sub_page_resolves_to_its_index_html(built, path):
    """با و بدونِ اسلشِ پایانی — لینکِ ریل یکی دارد و تایپِ دستی معمولاً نه."""
    r = await built.client.get(path, cookies=built.cookies)
    assert r.status == 200
    assert "HEALTH PAGE" in await r.text()


async def test_assets_are_not_gated(built):
    """کنترلِ عمدیِ مکمل: دارایی **باید** بدونِ نشست برسد.

    اگر روزی گِیت روی کلِ زیردرخت برود، این تست می‌افتد — که همان چیزی است
    که باید، چون آن تغییر کشِ مرورگر را می‌شکند بدونِ اینکه چیزی بخرد.
    """
    r = await built.client.get("/console/_next/static/app.js")
    assert r.status == 200
    assert "console.log" in await r.text()


async def test_an_unknown_path_is_a_404_not_a_redirect(built):
    r = await built.client.get("/console/nope/", cookies=built.cookies, allow_redirects=False)
    assert r.status == 404


@pytest.mark.parametrize("tail", ["../secret.txt", "../../etc/passwd", "health/../..", "/../secret.txt"])
def test_path_traversal_is_refused(built, tail, tmp_path):
    """گاردِ پیمایش، در سطحی که **خودش** تصمیم می‌گیرد.

    اولین نسخهٔ این تست انتها‌به‌انتها بود و شکست — ولی نه چون گارد خراب
    بود: کلاینتِ aiohttp مسیر را **پیش از ارسال** نرمال می‌کرد، پس درخواست
    اصلاً به این هندلر نمی‌رسید و چیزی که سنجیده می‌شد نرمال‌سازیِ کلاینت
    بود نه دفاعِ ما. §۶: هر لایه باید جایی سنجیده شود که تنها تصمیم‌گیرنده
    است؛ ادعای انتها‌به‌انتها تستِ جدای خودش را دارد.
    """
    (tmp_path / "secret.txt").write_text("s", encoding="utf-8")
    assert built.aw._console_target(tail) is None


def test_the_guard_still_serves_ordinary_paths(built):
    """کنترلِ معکوس: گاردی که همه‌چیز را رد کند هم «صفر پیمایش» می‌دهد."""
    for tail in ("", "/", "health", "health/", "./health"):
        assert built.aw._console_target(tail) is not None


async def test_a_missing_build_says_how_to_build_it(panel, monkeypatch, tmp_path):
    """کنترلِ منفی: نبودِ فایل نباید ۵۰۰ بدهد و نباید ساکت باشد."""
    monkeypatch.setattr(panel.aw, "_CONSOLE_DIR", str(tmp_path / "nope"))
    r = await panel.client.get("/console", cookies=panel.cookies)
    assert r.status == 503
    assert "export:panel" in await r.text()


async def test_the_missing_build_is_still_gated(panel, monkeypatch, tmp_path):
    """نبودِ build نباید گِیت را باز کند."""
    monkeypatch.setattr(panel.aw, "_CONSOLE_DIR", str(tmp_path / "nope"))
    r = await panel.client.get("/console", allow_redirects=False)
    assert r.status == 302


def test_the_console_dir_lives_under_app(panel):
    """قیدِ سخت: هرچه پنل از دیسک می‌خواند باید زیرِ `app/` باشد.

    `docker/admin.Dockerfile` فقط `COPY app` و `COPY node` دارد، پس مسیری
    بیرونِ `app/` در ایمیج نیست — و چون تست از ریشهٔ ریپو می‌دود، آن شکست
    فقط در تولید دیده می‌شود.
    """
    app_dir = pathlib.Path(panel.aw.__file__).resolve().parent
    assert pathlib.Path(panel.aw._CONSOLE_DIR).resolve().is_relative_to(app_dir)


def test_woff2_has_a_real_mime_type():
    """بدونِ ثبتِ صریح، فونت `application/octet-stream` سرو می‌شود."""
    import mimetypes

    assert mimetypes.guess_type("x.woff2")[0] == "font/woff2"
