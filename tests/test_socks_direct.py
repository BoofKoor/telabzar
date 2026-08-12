"""فاز ۳ت / موردِ ۱۱ — موتورِ `direct` باید از پروکسیِ socks هم برود.

تا امروز نمی‌رفت و **بی‌صدا** نمی‌رفت: `_http_proxy` هر چیزِ غیرِ http(s) را دور
می‌ریخت، پس با `PROXY_URL=socks5h://…` — همان چیزی که `docs/ADMIN_PANEL.md`
توصیه می‌کرد — یوتیوب و اینستاگرام از پروکسی می‌رفتند و دانلودِ فایلِ مستقیم از
IPِ خودِ مستر. تناقضِ مستند با کد، و بلاکرِ برنامهٔ خروجیِ موبایل.

**سرورِ SOCKS5 این‌جا واقعی است، نه ماکِ کانکتور.** `aiohttp_socks` یک کتابخانهٔ
بیرونی است و درسِ همین هفته این بود که ماک شکلِ کتابخانه را پنهان می‌کند؛ پس
این‌جا خودِ پروتکل حرف می‌زند: دست‌دادن، CONNECT، و رله. سرور مقصدی را که از او
خواسته شده ثبت می‌کند، و همان ثبت است که اثبات می‌کند ترافیک واقعاً از پروکسی رد
شده — نه اینکه صرفاً دانلود موفق بوده.

**تنها چیزی که ماک می‌شود** `_addr_is_internal` است (الگوی موجودِ
`tests/test_ssrf.py`): سرورِ تست روی ۱۲۷٫۰٫۰٫۱ است و بدونِ آن، گاردِ آدرسِ
داخلی — که کارِ درستش را می‌کند — هر دانلودِ محلی را رد می‌کرد.
"""
from __future__ import annotations

import asyncio
import socket

import pytest
import pytest_asyncio
from aiohttp import web

from app import downloader as D

PAYLOAD = b"telabzar-direct-payload-" * 64


# ── سرورِ واقعیِ SOCKS5 (بدونِ احراز هویت) ─────────────────────────────────
async def _pipe(reader, writer) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except Exception:  # noqa: BLE001 — بستنِ عادیِ سوکت
        pass
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


class Socks5Server:
    """پیاده‌سازیِ کمینه ولی **واقعیِ** SOCKS5؛ مقصدهای خواسته‌شده را ثبت می‌کند."""

    def __init__(self) -> None:
        self.requested: list[tuple[str, int]] = []
        self.port = 0
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer) -> None:
        try:
            greeting = await reader.readexactly(2)          # VER, NMETHODS
            await reader.readexactly(greeting[1])           # METHODS
            writer.write(b"\x05\x00")                       # بدونِ احراز هویت
            await writer.drain()

            hdr = await reader.readexactly(4)               # VER, CMD, RSV, ATYP
            atyp = hdr[3]
            if atyp == 1:
                host = socket.inet_ntoa(await reader.readexactly(4))
            elif atyp == 3:                                  # نامِ دامنه (rdns)
                n = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(n)).decode()
            else:
                host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
            port = int.from_bytes(await reader.readexactly(2), "big")
            self.requested.append((host, port))

            up_r, up_w = await asyncio.open_connection(host, port)
            writer.write(b"\x05\x00\x00\x01" + b"\x00" * 4 + b"\x00\x00")
            await writer.drain()
            await asyncio.gather(_pipe(reader, up_w), _pipe(up_r, writer))
        except Exception:  # noqa: BLE001 — کلاینتی که وسطِ کار می‌رود
            pass
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass


@pytest_asyncio.fixture
async def socks():
    s = Socks5Server()
    await s.start()
    yield s
    await s.stop()


@pytest_asyncio.fixture
async def origin():
    """سرورِ مقصد — همان فایلی که باید از پروکسی رد شود."""
    async def blob(_req):
        return web.Response(body=PAYLOAD, content_type="application/octet-stream",
                            headers={"Content-Disposition": 'attachment; filename="x.bin"'})

    app = web.Application()
    app.router.add_route("*", "/blob", blob)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield port
    await runner.cleanup()


@pytest.fixture(autouse=True)
def allow_loopback(monkeypatch):
    """تنها ماکِ این فایل — گاردِ آدرسِ داخلی، تا سرورِ ۱۲۷٫۰٫۰٫۱ قابلِ تست باشد."""
    monkeypatch.setattr(D, "_addr_is_internal", lambda addr: False)


# ── طبقه‌بندی و نگاشتِ اسکیم ───────────────────────────────────────────────
def test_socks5h_is_mapped_to_socks5():
    """python_socks اسکیمِ `socks5h` را نمی‌شناسد؛ معنیِ `h` پیش‌فرضِ آن است."""
    assert D._proxy_kind("socks5h://h:1080") == ("socks", "socks5://h:1080")
    assert D._proxy_kind("socks5://h:1080") == ("socks", "socks5://h:1080")


def test_http_and_unknown_schemes_are_unchanged():
    assert D._proxy_kind("http://squid:3128") == ("http", "http://squid:3128")
    assert D._proxy_kind("ftp://x") == ("", None)
    assert D._proxy_kind(None) == ("", None)


def test_the_request_level_proxy_still_only_takes_http():
    """socks از کانکتور می‌رود، نه از پارامترِ `proxy=`ِ درخواست."""
    assert D._http_proxy("socks5://h:1080") is None
    assert D._http_proxy("http://h:3128") == "http://h:3128"


# ── قلبِ موردِ ۱۱: ترافیک واقعاً از پروکسی رد شود ─────────────────────────
async def test_a_direct_download_goes_through_a_real_socks_proxy(socks, origin, tmp_path):
    """پیش از رفع: دانلود موفق می‌شد ولی پروکسی هیچ‌وقت صدا زده نمی‌شد."""
    opts = {"proxy": f"socks5h://127.0.0.1:{socks.port}", "direct_proxy": True}
    path, _info = await D.download_direct(
        f"http://127.0.0.1:{origin}/blob", str(tmp_path), opts)

    assert open(path, "rb").read() == PAYLOAD, "محتوا باید سالم برسد"
    assert socks.requested, "پروکسی هیچ درخواستی ندید — ترافیک از آن رد نشده"
    assert socks.requested[-1][1] == origin, \
        f"پروکسی مقصدِ اشتباه دید: {socks.requested!r}"


async def test_probe_direct_also_goes_through_the_proxy(socks, origin):
    """`probe_direct` قبل از دانلود اجرا می‌شود؛ اگر جا بماند یک HEADِ
    محافظت‌نشده از IPِ مستر بیرون می‌رود."""
    opts = {"proxy": f"socks5://127.0.0.1:{socks.port}", "direct_proxy": True}
    info = await D.probe_direct(f"http://127.0.0.1:{origin}/blob", opts)
    assert info and info.get("is_file"), "probe باید فایل را تشخیص دهد"
    assert socks.requested, "probe_direct از پروکسی رد نشد"


async def test_turning_the_switch_off_bypasses_the_proxy(socks, origin, tmp_path):
    """`dl_direct_proxy=off` = رفتارِ قدیمی (از IPِ خودِ سرور) — عمداً و صریح."""
    opts = {"proxy": f"socks5h://127.0.0.1:{socks.port}", "direct_proxy": False}
    path, _ = await D.download_direct(
        f"http://127.0.0.1:{origin}/blob", str(tmp_path), opts)
    assert open(path, "rb").read() == PAYLOAD
    assert socks.requested == [], "با کلیدِ خاموش نباید از پروکسی رد شود"


# ── رگرسیون: حالت‌های دیگر دست‌نخورده ─────────────────────────────────────
async def test_no_proxy_still_gets_the_vetoing_resolver():
    """بدونِ پروکسی، دفاعِ ضدِ TOCTOU باید سرِ جایش بماند."""
    conn = D._direct_connector({})
    assert type(conn._resolver).__name__ == "SafeResolver"


async def test_http_proxy_still_omits_the_resolver():
    """رگرسیونِ فازِ ۱: با پروکسیِ نام‌دارِ http نباید رزولور وصل شود."""
    conn = D._direct_connector({"proxy": "http://squid:3128"})
    assert type(conn._resolver).__name__ != "SafeResolver"


async def test_socks_uses_the_proxy_connector():
    from aiohttp_socks import ProxyConnector
    conn = D._direct_connector({"proxy": "socks5h://h:1080", "direct_proxy": True})
    assert isinstance(conn, ProxyConnector)


async def test_socks_with_the_switch_off_falls_back_to_the_guarded_connector():
    conn = D._direct_connector({"proxy": "socks5h://h:1080", "direct_proxy": False})
    assert type(conn._resolver).__name__ == "SafeResolver", \
        "وقتی از پروکسی رد نمی‌شویم، اتصال مستقیم است و وتو لازم است"


# ── fail-closed برای هر دو نوعِ پروکسی ────────────────────────────────────
async def test_dns_failure_is_rejected_even_with_a_proxy(monkeypatch):
    """قبلاً با پروکسیِ ست‌شده اجازه می‌داد — و در حالتِ پروکسی همین در **تنها**
    دفاع است، چون رزولورِ وتوکننده آن‌جا وصل نمی‌شود."""
    D._dns_cache.clear()

    def _boom(*a, **kw):
        raise socket.gaierror("nope")

    monkeypatch.setattr(D.socket, "getaddrinfo", _boom)
    for proxy in (None, "http://squid:3128", "socks5h://h:1080"):
        D._dns_cache.clear()
        assert not await D.is_safe_url_resolved("https://nxdomain.example/x", proxy=proxy), \
            f"شکستِ DNS با proxy={proxy!r} باید رد شود"
