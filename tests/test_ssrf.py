"""رگرسیونِ SSRF — `downloader.is_safe_url` / `is_safe_url_resolved` / رزولورِ کانکتور.

باگ: فیلتر فقط `ipaddress.ip_address(host)` را امتحان می‌کرد و روی ValueError
نتیجه می‌گرفت «پس نامِ میزبان است → مجاز». ولی `2130706433`, `0x7f000001`,
`127.1`, `017700000001` همگی ValueError می‌دهند و همگی به `127.0.0.1` وصل
می‌شوند؛ و هیچ resolveی هم انجام نمی‌شد، پس هر دامنه‌ای با A-recordِ داخلی رد
می‌شد. با پیش‌فرضِ `dl_allow_unknown` و `dl_direct_enabled` (هر دو True) این یعنی
هر کاربری می‌توانست بدنهٔ سرویسِ داخلی/متادیتای کلاود را به‌عنوان فایل بگیرد.
"""
from __future__ import annotations

import socket

import aiohttp
import pytest
from aiohttp import web

from app import downloader as D

SECRET = b"internal-service-response"


# ── لایهٔ نحوی (بدونِ DNS) ───────────────────────────────────────
@pytest.mark.parametrize("url", [
    "http://2130706433/",           # اعشاریِ 127.0.0.1
    "http://0x7f000001/",           # هگز
    "http://127.1/",                # فرمِ کوتاهِ inet_aton
    "http://017700000001/",         # اکتال
    "http://127.0.0.1/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",   # IPv4-mapped: is_loopback برایش False است
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://0.0.0.0/",
    "http://[::]/",
    "http://224.0.0.1/",            # multicast
    "http://100.64.0.1/",           # CGNATِ اپراتور (RFC 6598)
    "http://[fd00::1]/",            # ULAی IPv6
    "http://[fe80::1]/",            # link-localِ IPv6
    "http://localhost:8080/",
    "http://metadata.google.internal/",
])
def test_internal_targets_are_blocked(url):
    assert D.is_safe_url(url) is False


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://example.com/file.zip",
    "http://8.8.8.8/",
    "http://142.250.185.14/",
    "http://151.101.1.140/",
    "https://[2001:4860:4860::8888]/",
    "https://[2606:4700:4700::1111]/",
    "https://[2a03:2880:f10c::face:b00c]/",
])
def test_public_targets_are_allowed(url):
    """سخت‌گیریِ فیلتر نباید به مثبتِ کاذب روی IPِ واقعاً عمومی برسد."""
    assert D.is_safe_url(url) is True


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x",
                                 "gopher://example.com/", "not a url", ""])
def test_non_http_is_blocked(url):
    assert D.is_safe_url(url) is False


# ── لایهٔ resolve ────────────────────────────────────────────────
_real_getaddrinfo = socket.getaddrinfo


def _fake_getaddrinfo(mapping: dict[str, str], calls: list[str] | None = None):
    """جایگزینِ getaddrinfo. تنها چیزی که در این تست‌ها جعل می‌شود «رکوردِ DNS» است —
    چیزی که در دنیای واقعی مهاجم با ثبتِ یک A-record می‌سازد و در تست ساختنی نیست.

    فراخوانیِ `AI_NUMERICHOST` (تشخیصِ IPِ لفظی) به تابعِ **واقعی** واگذار می‌شود:
    آن‌جا اصلاً DNSی در کار نیست و جعلش تست را از موضوع دور می‌کند.
    """
    def _f(host, *a, **kw):
        if kw.get("flags", 0) & socket.AI_NUMERICHOST:
            return _real_getaddrinfo(host, *a, **kw)
        if calls is not None:
            calls.append(host)
        if host not in mapping:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        addr = mapping[host]
        fam = socket.AF_INET6 if ":" in addr else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, "", (addr, 0))]
    return _f


@pytest.fixture(autouse=True)
def _clear_dns_cache():
    # `getattr` تا اگر کسی این تست‌ها را روی سورسِ قبل از رفع اجرا کرد، خطای واقعیِ
    # هر تست را ببیند نه یک ارورِ setup روی همه‌شان.
    getattr(D, "_dns_cache", {}).clear()
    yield
    getattr(D, "_dns_cache", {}).clear()


@pytest.mark.parametrize("addr", ["127.0.0.1", "169.254.169.254", "10.1.2.3",
                                  "192.168.5.5", "::1", "::ffff:169.254.169.254"])
async def test_hostname_resolving_internal_is_blocked(monkeypatch, addr):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({"evil.example": addr}))
    assert await D.is_safe_url_resolved("http://evil.example/x") is False


async def test_hostname_resolving_public_is_allowed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({"ok.example": "93.184.216.34"}))
    assert await D.is_safe_url_resolved("https://ok.example/v") is True


async def test_dns_failure_is_rejected_without_proxy(monkeypatch):
    """پیش‌فرضِ ما پروکسی ندارد، پس درخواست از همین ماشین می‌رود و شکستِ DNS
    دلیلِ موجهی ندارد → رد."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({}))
    assert await D.is_safe_url_resolved("https://nope.example/v") is False


async def test_dns_failure_is_allowed_with_proxy(monkeypatch):
    """با پروکسیِ خروجی، نام را **پروکسی** حل می‌کند و دیدِ محلیِ ما بی‌ربط است."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({}))
    assert await D.is_safe_url_resolved(
        "https://nope.example/v", proxy="http://exit:3128") is True


async def test_resolution_is_cached(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(socket, "getaddrinfo",
                        _fake_getaddrinfo({"ok.example": "93.184.216.34"}, calls))
    for _ in range(4):
        assert await D.is_safe_url_resolved("https://ok.example/a") is True
    assert len(calls) == 1, "مسیرِ داغِ ربات نباید به‌ازای هر لینک دوباره DNS بزند"


async def test_literal_host_does_not_hit_dns(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({}, calls))
    assert await D.is_safe_url_resolved("http://8.8.8.8/") is True
    assert calls == []


# ── مسیرِ واقعی: سرورِ aiohttp روی لوپ‌بک ────────────────────────
@pytest.fixture
async def server():
    """سرورِ **واقعی** (نه ماک) که نقشِ سرویسِ داخلی را بازی می‌کند."""
    async def blob(_req):
        return web.Response(body=SECRET, content_type="application/octet-stream",
                            headers={"Content-Disposition": 'attachment; filename="x.bin"'})

    box: dict[str, int] = {}

    async def redirect(_req):
        return web.Response(status=302,
                            headers={"Location": f"http://2130706433:{box['port']}/blob"})

    app = web.Application()
    app.router.add_route("*", "/blob", blob)
    app.router.add_route("*", "/redirect", redirect)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    box["port"] = port = site._server.sockets[0].getsockname()[1]
    yield port
    await runner.cleanup()


async def test_direct_download_of_numeric_loopback_is_blocked(server, tmp_path):
    """قبل از رفع: این دقیقاً `SECRET` را به‌عنوان فایل تحویل می‌داد."""
    with pytest.raises(RuntimeError, match="blocked url"):
        await D.download_direct(f"http://2130706433:{server}/blob", str(tmp_path))


async def test_direct_probe_of_numeric_loopback_is_blocked(server):
    """HEADِ اکتشافی هم نباید به لوپ‌بک برسد (و روی شکست None می‌دهد → مسیرِ yt-dlp)."""
    assert await D.probe_direct(f"http://0x7f000001:{server}/blob") is None


async def test_redirect_hop_to_numeric_loopback_is_blocked(server, monkeypatch):
    """پرشِ **دوم** هم چک می‌شود: هاستِ اولْ نام است (پس نحواً مجاز)، ولی
    Location به فرمِ عددیِ لوپ‌بک اشاره می‌کند."""
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"front.example": "127.0.0.1"}))

    class _Fixed(aiohttp.DefaultResolver):
        async def resolve(self, host, port=0, family=socket.AF_INET):
            return [{"hostname": host, "host": "127.0.0.1", "port": port,
                     "family": socket.AF_INET, "proto": 6, "flags": 0}]

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=_Fixed())) as s:
        with pytest.raises(RuntimeError, match="blocked url"):
            await D._follow(s, "GET", f"http://front.example:{server}/redirect", None)


async def test_connector_resolver_vetoes_at_connect_time(server):
    """لایهٔ ضدِ TOCTOU: حتی اگر چکِ نحوی دور زده شود، خودِ اتصال نمی‌گیرد."""
    async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=D._safe_resolver())) as s:
        with pytest.raises(aiohttp.ClientConnectorError):
            await s.get(f"http://localhost:{server}/blob")


async def test_public_direct_download_still_works(server, tmp_path, monkeypatch):
    """رفع نباید مسیرِ سالم را بشکند: هاستِ «عمومی» همچنان دانلود می‌شود."""
    monkeypatch.setattr(D, "_addr_is_internal", lambda addr: False)
    path, info = await D.download_direct(f"http://127.0.0.1:{server}/blob", str(tmp_path))
    with open(path, "rb") as fh:
        assert fh.read() == SECRET
    assert info["filesize"] == len(SECRET)


async def test_direct_size_cap_still_carries_its_numbers(server, tmp_path, monkeypatch):
    """`DirectTooLarge` باید `size`/`cap_bytes` داشته باشد — پیامِ «حجم زیاد است»
    به کاربر از همین‌ها ساخته می‌شود (`dl_direct_too_large`)."""
    monkeypatch.setattr(D, "_addr_is_internal", lambda addr: False)
    with pytest.raises(D.DirectTooLarge) as err:
        await D.download_direct(f"http://127.0.0.1:{server}/blob", str(tmp_path),
                                max_bytes=4)
    assert err.value.cap_bytes == 4 and err.value.size >= 4
