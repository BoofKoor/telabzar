"""رگرسیونِ SSRF — `downloader.is_safe_url` / `is_safe_url_resolved` / رزولورِ کانکتور.

باگ: فیلتر فقط `ipaddress.ip_address(host)` را امتحان می‌کرد و روی ValueError
نتیجه می‌گرفت «پس نامِ میزبان است → مجاز». ولی `2130706433`, `0x7f000001`,
`127.1`, `017700000001` همگی ValueError می‌دهند و همگی به `127.0.0.1` وصل
می‌شوند؛ و هیچ resolveی هم انجام نمی‌شد، پس هر دامنه‌ای با A-recordِ داخلی رد
می‌شد. با پیش‌فرضِ `dl_allow_unknown` و `dl_direct_enabled` (هر دو True) این یعنی
هر کاربری می‌توانست بدنهٔ سرویسِ داخلی/متادیتای کلاود را به‌عنوان فایل بگیرد.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import socket
import textwrap

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


@pytest.mark.parametrize("proxy", ["http://exit:3128", "socks5h://exit:1080"])
async def test_dns_failure_is_rejected_with_a_proxy_too(monkeypatch, proxy):
    """**رفتار در فاز ۳ت عوض شد — و این یکی یک دورزدنِ واقعی را می‌بست.**

    قبلاً با پروکسیِ ست‌شده اجازه می‌داد، به این استدلال که «نام را پروکسی حل
    می‌کند». آن فقط برای DNSِ افقِ‌تقسیم‌شده صادق است و خروجیِ ما بیرونی است.
    در مقابل: نامی که برای ما NXDOMAIN است ولی پروکسی حلش می‌کند از درِ ورودی
    رد می‌شد — و در حالتِ پروکسی همین در **تنها** دفاع است، چون رزولورِ
    وتوکننده وصل نمی‌شود. یعنی fail-open همان‌جا ضعیف بود که بیشترین اهمیت را
    داشت.
    """
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo({}))
    assert await D.is_safe_url_resolved("https://nope.example/v", proxy=proxy) is False


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


async def test_private_proxy_is_not_vetoed(server, monkeypatch):
    """`PROXY_URL` روی شبکهٔ خصوصی نباید قربانیِ رزولورِ ضدِ SSRF شود.

    یک پروکسیِ خودمیزبان معمولاً با نامِ سرویسِ داکر می‌آید (`http://squid:3128`)
    که به ۱۷۲٫x حل می‌شود. رزولور در حالتِ پروکسی هیچ حفاظتی از **مقصد** نمی‌دهد
    (مقصد را پروکسی حل می‌کند)، پس فقط می‌توانست همین پرش را بشکند.
    """
    async def _proxied(_req):
        return web.Response(text="via-proxy")

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", _proxied)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    pport = site._server.sockets[0].getsockname()[1]
    try:
        opts = {"proxy": f"http://myproxy.internal:{pport}"}
        assert isinstance(D._direct_connector(opts), aiohttp.TCPConnector)

        loop = asyncio.get_running_loop()
        real = loop.getaddrinfo

        async def _lga(host, port, **kw):
            if host == "myproxy.internal":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
            return await real(host, port, **kw)

        monkeypatch.setattr(loop, "getaddrinfo", _lga)
        async with aiohttp.ClientSession(connector=D._direct_connector(opts)) as s:
            async with s.get("http://example.com/x", proxy=opts["proxy"],
                             timeout=aiohttp.ClientTimeout(total=5)) as r:
                assert r.status == 200 and await r.text() == "via-proxy"
    finally:
        await runner.cleanup()


async def test_safe_resolver_is_attached_when_there_is_no_proxy():
    conn = D._direct_connector({})
    try:
        assert type(conn._resolver).__name__ == "SafeResolver"
    finally:
        await conn.close()


@pytest.mark.parametrize("proxy", ["socks5://127.0.0.1:1080", "socks5h://exit:1080",
                                   "socks4://exit:1080"])
async def test_socks_proxy_now_goes_through_the_proxy_connector(proxy):
    """**رفتار در فاز ۳ت عوض شد.**

    نسخهٔ قبلیِ این تست تثبیت می‌کرد که با پروکسیِ socks رزولورِ وتوکننده سرِ
    جایش می‌ماند — که درست بود، ولی فقط چون `_http_proxy` پروکسی را دور
    می‌ریخت و اتصال **واقعاً مستقیم** می‌شد. یعنی تست داشت یک باگ را پین
    می‌کرد: کاربری که `socks5h://` گذاشته بود، دانلودِ فایلِ مستقیمش از IPِ
    خودِ مستر بیرون می‌رفت.

    حالا socks از `ProxyConnector` می‌رود. رزولور آن‌جا **قابلِ وصل نیست**
    (`aiohttp_socks` بی‌قیدوشرط `NoResolver()` می‌گذارد) و دفاع درِ ورودی است —
    دقیقاً همان وضعِ پروکسیِ http(s). `test_socks_direct.py` را ببین.
    """
    from aiohttp_socks import ProxyConnector
    assert D._http_proxy(proxy) is None, "پارامترِ درخواست هنوز فقط http می‌گیرد"
    conn = D._direct_connector({"proxy": proxy, "direct_proxy": True})
    try:
        assert isinstance(conn, ProxyConnector)
    finally:
        await conn.close()


@pytest.mark.parametrize("proxy", ["socks5://127.0.0.1:1080", "socks5h://exit:1080"])
async def test_socks_with_direct_proxy_off_keeps_the_safe_resolver(proxy):
    """وقتی ادمین صریحاً `dl_direct_proxy` را خاموش کند، اتصال مستقیم است —
    و آن‌وقت رزولورِ وتوکننده دقیقاً همان چیزی است که لازم است."""
    conn = D._direct_connector({"proxy": proxy, "direct_proxy": False})
    try:
        assert type(conn._resolver).__name__ == "SafeResolver"
    finally:
        await conn.close()


async def test_aiohttp_does_not_fall_back_to_direct_for_socks():
    """چرا `_http_proxy` لازم است: aiohttp پروکسیِ socks را «نادیده» نمی‌گیرد،
    به همان host:port تلاشِ CONNECT می‌کند و می‌شکند."""
    async with aiohttp.ClientSession() as s:
        with pytest.raises(aiohttp.ClientError):
            await s.get("http://example.com/", proxy="socks5://127.0.0.1:1",
                        timeout=aiohttp.ClientTimeout(total=4))


def _callee(node: ast.AST) -> str:
    """نامِ چیزی که صدا زده می‌شود: `f(...)` → `f`، `a.b(...)` → `a.b`."""
    f = node.func if isinstance(node, ast.Call) else node
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f"{_callee(f.value)}.{f.attr}" if isinstance(
            f.value, (ast.Name, ast.Attribute)) else f.attr
    return ""


def _direct_engine_sessions() -> list[tuple[str, bool]]:
    """(نامِ تابع, آیا `connector=_direct_connector(...)` دارد) برای موتورِ `direct`.

    کشف **خودکار** است تا فهرست کهنه نشود: تابعی جزوِ موتورِ direct است اگر
    نامش `direct` داشته باشد **یا** `_follow` را صدا بزند (تنها راهِ درخواستِ
    این موتور). با AST خوانده می‌شود نه تطبیقِ رشته، چون آرگومانِ `connector`
    در سورس روی خطِ بعدیِ `ClientSession(` است.
    """
    tree = ast.parse(inspect.getsource(D))
    found: list[tuple[str, bool]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        if "direct" not in fn.name and not any(
                _callee(c) == "_follow" for c in calls):
            continue
        for call in calls:
            if _callee(call) != "aiohttp.ClientSession":
                continue
            found.append((fn.name, any(
                kw.arg == "connector" and isinstance(kw.value, ast.Call)
                and _callee(kw.value) == "_direct_connector"
                for kw in call.keywords)))
    return found


def test_every_direct_engine_session_uses_the_guarded_connector():
    """هر سشنِ موتورِ `direct` باید از `_direct_connector` بیاید.

    اگر `probe_direct` (که **قبل** از `download_direct` اجرا می‌شود) سشنِ ساده
    بگیرد، یک چکِ محافظت‌نشده جلوی چکِ محافظت‌شده می‌نشیند. فهرستِ توابع عمداً
    هاردکد نیست: سشنِ سومی که فردا اضافه شود هم باید همین‌جا گیر بیفتد.
    """
    sessions = _direct_engine_sessions()
    assert {n for n, _ in sessions} >= {"probe_direct", "download_direct"}, \
        f"کشف، سشن‌های شناخته‌شده را پیدا نکرد: {sessions}"
    bad = [n for n, guarded in sessions if not guarded]
    assert not bad, f"این سشن‌ها کانکتورِ محافظت‌شده ندارند: {bad}"


def test_the_session_discovery_is_not_vacuous():
    """کنترل: باگ را روی یک سورسِ ساختگی بساز و مطمئن شو کشف می‌گیردش.

    بدونِ این، اگر روزی `_callee`/کشف بشکند، تستِ بالا با فهرستِ خالی سبز
    می‌ماند و دیگر چیزی را اثبات نمی‌کند.
    """
    broken = textwrap.dedent("""
        async def probe_direct(url, opts=None):
            async with aiohttp.ClientSession(headers=h, timeout=t) as sess:
                resp = await _follow(sess, "HEAD", url, None)

        async def stream_it(url, opts=None):
            async with aiohttp.ClientSession(connector=_direct_connector(opts)) as s:
                resp = await _follow(s, "GET", url, None)

        async def unrelated(url):
            async with aiohttp.ClientSession() as s:
                return await s.get(url)
    """)
    tree = ast.parse(broken)
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        if "direct" not in fn.name and not any(_callee(c) == "_follow" for c in calls):
            continue
        for call in calls:
            if _callee(call) != "aiohttp.ClientSession":
                continue
            found.append((fn.name, any(
                kw.arg == "connector" and isinstance(kw.value, ast.Call)
                and _callee(kw.value) == "_direct_connector"
                for kw in call.keywords)))

    assert ("probe_direct", False) in found, "سشنِ محافظت‌نشده باید گیر بیفتد"
    # `stream_it` نامِ direct ندارد؛ فقط چون `_follow` را صدا می‌زند کشف می‌شود.
    assert ("stream_it", True) in found, "کشف نباید به نامِ تابع محدود بماند"
    assert "unrelated" not in [n for n, _ in found], "سشنِ بی‌ربط نباید شمرده شود"


@pytest.fixture
def dns_points_at_loopback(monkeypatch):
    """A-recordِ جعلی در **همان لایه‌ای** که aiohttp از آن می‌خواند.

    وصله روی `socket.getaddrinfo` کافی نیست: رزولورِ aiohttp از مسیرِ دیگری
    می‌رود، پس نام واقعاً NXDOMAIN می‌ماند و تست به دلیلِ **غلط** سبز می‌شود —
    یعنی با کانکتورِ ساده هم پاس می‌شود و دیگر چیزی را اثبات نمی‌کند.
    """
    async def _resolve(self, host, port=0, family=socket.AF_INET):
        return [{"hostname": host, "host": "127.0.0.1", "port": port,
                 "family": socket.AF_INET, "proto": 6, "flags": 0}]

    monkeypatch.setattr(aiohttp.DefaultResolver, "resolve", _resolve)


async def test_probe_direct_is_vetoed_for_a_name_resolving_to_loopback(
        server, dns_points_at_loopback):
    """`probe_direct` هم سرِ **اتصال** وتو می‌شود، نه فقط با چکِ نحوی.

    هاست یک **نام** است پس `is_safe_url` ردش نمی‌کند؛ حرفِ آخر با رزولورِ
    کانکتور است. با کانکتورِ ساده این HEAD موفق می‌شد و dict برمی‌گرداند.
    """
    url = f"http://sneaky.example:{server}/blob"
    assert D.is_safe_url(url) is True, "چکِ نحوی نباید نام را رد کند"
    async with aiohttp.ClientSession() as plain:      # کنترل: بدونِ رزولورِ ما می‌رسد
        async with await _follow_plain(plain, url) as resp:
            assert resp.status == 200 and await resp.read() == SECRET
    assert await D.probe_direct(url) is None, "با رزولورِ محافظ باید وتو شود"


async def _follow_plain(sess, url):
    return sess.get(url)


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
