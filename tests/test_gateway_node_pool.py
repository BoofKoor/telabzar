"""فاز ۴ / موردِ ۲۱ — نودِ استریم با صد بینندهٔ هم‌زمان نباید بقیه را 502 کند.

`ClientSession`ِ بی‌connector یعنی `TCPConnector(limit=100)`، و هر استریمِ زنده
یک اتصالِ upstream را تا پایانِ استریم نگه می‌دارد. پس صد و یکمین درخواست در صفِ
استخر می‌ماند تا `connect=15` بگذرد و بعد 502 می‌گرفت — ظرفیتِ معمولی، نه حمله.
نیمهٔ دوم: کلاینتی که می‌ایستد و نمی‌خواند `resp.write` را برای همیشه معلق و
اتصالِ upstream را برای همیشه اشغال نگه می‌داشت.

upstreamِ واقعی (aiohttp روی لوپ‌بک)، نودِ واقعی، و همه‌چیز کران‌دار (§۶) — نسخهٔ
خراب دقیقاً همان است که تمام نمی‌شود.
"""
from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app import gateway_node as GN

STREAMS = 101          # یکی بیشتر از پیش‌فرضِ aiohttp


@pytest.fixture
async def upstream():
    state = {"active": 0, "fast": False}

    async def stream(request):
        resp = web.StreamResponse(headers={"Content-Type": "video/mp4"})
        await resp.prepare(request)
        state["active"] += 1
        try:
            while True:
                if state["fast"]:
                    await resp.write(b"x" * 65536)
                else:
                    await resp.write(b"x" * 1024)
                    await asyncio.sleep(0.05)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            state["active"] -= 1
        return resp

    app = web.Application()
    app.router.add_get("/s/{token}", stream)
    srv = TestServer(app)
    await srv.start_server()
    yield srv, state
    await srv.close()


@pytest.fixture
async def node(upstream, monkeypatch):
    srv, _state = upstream
    monkeypatch.setattr(GN, "_upstream", lambda: str(srv.make_url("")).rstrip("/"))
    monkeypatch.setattr(GN.settings, "node_role", "")
    nsrv = TestServer(GN.build_app())
    await nsrv.start_server()
    yield nsrv
    await nsrv.close()


async def test_the_hundred_and_first_stream_is_served(node):
    url = str(node.make_url("/s/tok"))
    # کلاینتِ خودِ تست نباید همان سقف را داشته باشد، وگرنه سقفِ تست را می‌سنجیم.
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as cs:
        open_ = []
        try:
            for _ in range(STREAMS - 1):
                r = await cs.get(url)
                await asyncio.wait_for(r.content.readany(), 5)   # واقعاً upstream گرفته
                open_.append(r)
            r = await cs.get(url, timeout=aiohttp.ClientTimeout(total=5))
            try:
                assert r.status == 200
                assert await asyncio.wait_for(r.content.readany(), 5)
            finally:
                r.close()
        except asyncio.TimeoutError:
            pytest.fail(f"استریمِ {STREAMS}ام در صفِ استخرِ upstream ماند")
        finally:
            for r in open_:
                r.close()


async def test_a_stalled_client_releases_its_upstream(node, upstream, monkeypatch):
    _srv, state = upstream
    state["fast"] = True                      # بافرها را سریع پر کن تا write واقعاً بایستد
    monkeypatch.setattr(GN, "_CLIENT_STALL", 0.3, raising=False)
    reader, writer = await asyncio.open_connection(node.host, node.port)
    try:
        writer.write(b"GET /s/tok HTTP/1.1\r\nHost: x\r\n\r\n")   # و دیگر هیچ نمی‌خواند
        await writer.drain()
        for _ in range(100):
            if state["active"] == 1:
                break
            await asyncio.sleep(0.05)
        assert state["active"] == 1, "upstream اصلاً شروع نشد — تست چیزی نسنجید"
        for _ in range(200):                  # تا ۱۰ ثانیه
            if state["active"] == 0:
                break
            await asyncio.sleep(0.05)
        assert state["active"] == 0, "کلاینتِ متوقف اتصالِ upstream را برای همیشه نگه داشت"
    finally:
        writer.close()


async def test_a_reading_client_is_not_dropped(node, upstream, monkeypatch):
    """کنترل: کلاینتی که می‌خواند — حتی کند — نباید با سقفِ مکث قطع شود."""
    _srv, state = upstream
    monkeypatch.setattr(GN, "_CLIENT_STALL", 0.3, raising=False)
    async with aiohttp.ClientSession() as cs:
        r = await cs.get(str(node.make_url("/s/tok")))
        got = 0
        try:
            for _ in range(30):               # ~۱٫۵ ثانیه، پنج برابرِ سقف
                got += len(await asyncio.wait_for(r.content.readany(), 5))
        finally:
            r.close()
    assert got >= 20 * 1024
