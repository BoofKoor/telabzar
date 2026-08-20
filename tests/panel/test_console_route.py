"""مسیرِ `/console` — کنسولِ Next که پنل به‌شکلِ ایستا سرو می‌کند.

سه ادعا، در سه سطح، چون هر کدام می‌تواند مستقل بشکند:

  ۱. بی‌نشست → به `/login`. کنسول همان دادهٔ عملیاتی را نشان می‌دهد که بقیهٔ
     پنل، پس نباید در دسترسِ عمومی باشد.
  ۲. با نشست و با buildِ موجود → همان HTML.
  ۳. با نشست و **بدونِ** build → ۵۰۳ با دستورِ رفع، نه ۵۰۰.

سومی مهم‌ترین است و در بازیِ اول نبود: «هنوز build نشده» حالتِ عادیِ توسعهٔ
محلی و هر ایمیجی است که مرحلهٔ Node را رد کرده باشد؛ اگر آن‌جا traceback
بدهد، اپراتور دنبالِ باگی می‌گردد که وجود ندارد.
"""
from __future__ import annotations

import pathlib

import pytest


async def test_the_console_needs_a_session(panel):
    r = await panel.client.get("/console", allow_redirects=False)
    assert r.status == 302
    assert r.headers["Location"] == "/login"


async def test_the_console_serves_the_built_page(panel, monkeypatch, tmp_path):
    built = tmp_path / "console"
    built.mkdir()
    (built / "index.html").write_text("<!DOCTYPE html><title>console</title>x", encoding="utf-8")
    monkeypatch.setattr(panel.aw, "_CONSOLE_DIR", str(built))

    r = await panel.client.get("/console", cookies=panel.cookies)
    assert r.status == 200
    assert r.content_type == "text/html"
    assert "console" in await r.text()


async def test_a_missing_build_says_how_to_build_it(panel, monkeypatch, tmp_path):
    """کنترلِ منفی: نبودِ فایل نباید ۵۰۰ بدهد و نباید ساکت باشد."""
    monkeypatch.setattr(panel.aw, "_CONSOLE_DIR", str(tmp_path / "nope"))
    r = await panel.client.get("/console", cookies=panel.cookies)
    assert r.status == 503
    body = await r.text()
    assert "export:panel" in body, "پیام باید دستورِ ساختن را بگوید"


async def test_the_missing_build_is_still_gated(panel, monkeypatch, tmp_path):
    """نبودِ build نباید گِیت را باز کند — ترتیبِ دو چک در هندلر باربر است."""
    monkeypatch.setattr(panel.aw, "_CONSOLE_DIR", str(tmp_path / "nope"))
    r = await panel.client.get("/console", allow_redirects=False)
    assert r.status == 302


@pytest.mark.parametrize("path", ["/console", "/console/"])
async def test_both_spellings_reach_the_page(panel, monkeypatch, tmp_path, path):
    """`/console` و `/console/` هر دو باید کار کنند.

    aiohttp این دو را یکی نمی‌گیرد، و لینکِ ریل با `/` تمام می‌شود در حالی که
    اپراتور معمولاً بدونش تایپ می‌کند. بدونِ ثبتِ هر دو، یکی‌شان ۴۰۴ می‌دهد.
    """
    built = tmp_path / "console"
    built.mkdir()
    (built / "index.html").write_text("<!DOCTYPE html>ok", encoding="utf-8")
    monkeypatch.setattr(panel.aw, "_CONSOLE_DIR", str(built))
    r = await panel.client.get(path, cookies=panel.cookies)
    assert r.status == 200


def test_the_console_dir_lives_under_app(panel):
    """قیدِ سخت: هرچه پنل از دیسک می‌خواند باید زیرِ `app/` باشد.

    `docker/admin.Dockerfile` فقط `COPY app` و `COPY node` دارد، پس مسیری
    بیرونِ `app/` در ایمیج نیست — و چون تست از ریشهٔ ریپو می‌دود، آن شکست
    فقط در تولید دیده می‌شود.
    """
    app_dir = pathlib.Path(panel.aw.__file__).resolve().parent
    assert pathlib.Path(panel.aw._CONSOLE_DIR).resolve().is_relative_to(app_dir)
