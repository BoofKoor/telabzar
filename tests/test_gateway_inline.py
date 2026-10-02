"""رگرسیونِ سرو کردنِ محتوای کاربر به‌صورتِ inline در گیت‌وی.

باگ: `/s/<token>` هر فایلِ آپلودی را با mimeی خودِ کاربر و `inline` و بدونِ
`nosniff`/CSP سرو می‌کرد. چون گیت‌وی و پنل روی یک دامنه (پورتِ متفاوت = همان
site) اجرا می‌شوند، یک فایلِ `text/html`/`image/svg+xml`ِ inline یعنی XSSِ ذخیره‌شده
روی مبدأی که کوکیِ نشستِ پنل را هم می‌بیند. رفع: inline فقط برای ویدیو/صوت/عکسِ
رستر؛ بقیه (و mimeِ خالی) attachment، به‌علاوهٔ `X-Content-Type-Options: nosniff`
و `Content-Security-Policy: sandbox`.
"""
from __future__ import annotations

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app import gateway as G


@pytest.mark.parametrize("mime,inline_ok", [
    ("video/mp4", True),
    ("audio/mpeg", True),
    ("image/jpeg", True),
    ("image/png", True),
    ("image/svg+xml", False),     # اسکریپت اجرا می‌کند
    ("text/html", False),
    ("application/pdf", False),
    ("application/octet-stream", False),
    ("", False),                  # نوعِ ناشناخته sniff نشود
    (None, False),
])
def test_only_media_is_inline_safe(mime, inline_ok):
    assert G._is_inline_safe(mime) is inline_ok


class _FakeTgFile:
    def __init__(self, path):
        self.file_path = path


class _FakeSession:
    async def close(self):
        return None


class _FakeBot:
    def __init__(self, path):
        self._path = path
        self.session = _FakeSession()

    async def get_file(self, _fid):
        return _FakeTgFile(self._path)


def _app_with(tmp_path, mime, monkeypatch, body=b"<script>alert(1)</script>"):
    p = tmp_path / "blob"
    p.write_bytes(body)

    async def fake_resolve(_req, _token):
        return str(p), mime, "x"
    monkeypatch.setattr(G, "_resolve", fake_resolve)
    app = G.build_app()
    app["bot"] = _FakeBot(str(p))
    return app


async def _get(app, path):
    async with TestClient(TestServer(app)) as client:
        resp = await client.get(path)
        await resp.read()
        return resp


@pytest.mark.parametrize("mime,want_attach", [
    ("text/html", True),
    ("image/svg+xml", True),
    ("application/octet-stream", True),
    ("video/mp4", False),
])
def test_stream_forces_attachment_and_sets_security_headers(tmp_path, monkeypatch, mime, want_attach):
    app = _app_with(tmp_path, mime, monkeypatch)
    resp = asyncio.run(_get(app, "/s/anytoken"))
    disp = resp.headers.get("Content-Disposition", "")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert "sandbox" in resp.headers.get("Content-Security-Policy", "")
    if want_attach:
        assert disp.startswith("attachment"), disp
    else:
        assert disp.startswith("inline"), disp
