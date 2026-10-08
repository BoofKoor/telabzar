"""HTTPSِ خودکار، سمتِ پنل: گیتِ صدور (`/tls/ask`)، کارتِ «HTTPS» در سلامت، صدورِ
پیش‌دستانه بعد از ذخیره، و IPِ واقعیِ کلاینت پشتِ Caddy.

**چرا گیتِ صدور مهم‌ترینِ این فایل است:** Caddy پیش از گرفتن (و حتی بارگذاریِ)
سرتیفیکیتِ **هر** نامِ SNI همین اندپوینت را می‌پرسد. اگر بیش از دو نامِ ما را تأیید کند،
هر کسی با یک SNIِ دلخواه سهمیهٔ صدورِ Let's Encrypt را می‌سوزاند؛ اگر کمتر، پنل یا لینک
هرگز HTTPS نمی‌شوند — و هیچ‌کدام خطایی در هیچ لاگی نمی‌دهند جز «سرتیفیکیت نیامد».
"""
from __future__ import annotations

import asyncio
import logging
import ssl
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp.test_utils import make_mocked_request
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pagefacts import page_text, shows
from test_panel_css_classes import _fetch, undefined_in
from test_save_failures import _error_text, _follow, _settings_form, _shows_ok

PANEL = "panel.example.com"
LINK = "dl.example.com"


@pytest.fixture
def domains(panel, monkeypatch):
    """دامنهٔ پنل از env؛ دامنهٔ لینک با `set(...)` از مسیرِ واقعیِ store نوشته می‌شود."""
    monkeypatch.setattr(panel.aw.settings, "panel_domain", PANEL)
    monkeypatch.setattr(panel.aw.settings, "tls_cert", "")
    from app import settings_store
    return settings_store.get_store()


async def _ask(panel, name: str | None):
    params = {} if name is None else {"domain": name}
    r = await panel.client.get("/tls/ask", params=params)     # بدونِ کوکی: Caddy نشست ندارد
    return r.status


# ── گیتِ صدور ────────────────────────────────────────────────────────────────
async def test_the_panel_domain_is_approved(panel, domains):
    assert await _ask(panel, PANEL) == 200


async def test_the_comparison_is_on_the_canonical_name(panel, domains):
    """Caddy نامِ SNI را می‌فرستد؛ `PANEL.Example.com.` همان `panel.example.com` است."""
    assert await _ask(panel, "PANEL.Example.com.") == 200


async def test_the_panel_domain_needs_neither_redis_nor_postgres(panel, domains, monkeypatch):
    """دامنهٔ پنل از env می‌آید، پس Redisِ گیرکرده نباید HTTPSِ خودِ پنل را بخواباند."""
    from app import settings_store

    async def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(settings_store, "link_domain", boom)
    assert await _ask(panel, PANEL) == 200


async def test_the_link_domain_is_approved_once_saved(panel, domains):
    assert await _ask(panel, LINK) == 403
    await domains.set("link_domain", LINK)
    assert await _ask(panel, LINK) == 200


async def test_changing_the_link_domain_retires_the_old_one(panel, domains):
    """Caddy پیش از **بارگذاریِ** سرتیفیکیتِ ذخیره‌شده هم می‌پرسد (certmagic #185)،
    پس «نه» این‌جا یعنی دامنهٔ قبلی از ری‌استارتِ بعدیِ Caddy خاموش است، نه فقط «تمدید
    نمی‌شود». (تا آن ری‌استارت از حافظه سرو می‌شود — با Caddy و Pebbleِ واقعی اجرا شد.)"""
    await domains.set("link_domain", "old.example.com")
    assert await _ask(panel, "old.example.com") == 200
    await domains.set("link_domain", LINK)
    assert await _ask(panel, "old.example.com") == 403
    assert await _ask(panel, LINK) == 200


@pytest.mark.parametrize("name", [None, "", "evil.example.com", "203.0.113.5", "localhost",
                                  "panel.example.com:443", "*.example.com"],
                         ids=["missing", "empty", "stranger", "ip", "single-label", "port",
                              "wildcard"])
async def test_every_other_name_is_refused(panel, domains, name):
    await domains.set("link_domain", LINK)
    assert await _ask(panel, name) == 403


async def test_without_any_domain_nothing_is_approved(panel, monkeypatch):
    """نصبِ بدونِ دامنه: `PANEL_DOMAIN` خالی است و compose به Caddy `panel.invalid` می‌دهد."""
    monkeypatch.setattr(panel.aw.settings, "panel_domain", "")
    for name in ("panel.invalid", "", PANEL):
        assert await _ask(panel, name) == 403


async def test_a_hanging_settings_read_refuses_quickly(panel, domains, monkeypatch):
    """Caddy منتظرِ این پاسخ است و یک کلاینت پشتِ handshake؛ Redisِ گیرکرده نباید هر دو را
    گیر بیندازد. «نه» امن است: Caddy در handshakeِ بعدی دوباره می‌پرسد."""
    from app import settings_store

    async def hang():
        await asyncio.sleep(30)
        return LINK

    monkeypatch.setattr(settings_store, "link_domain", hang)
    monkeypatch.setattr(panel.aw, "_TLS_ASK_TIMEOUT", 0.2)
    started = asyncio.get_running_loop().time()
    assert await _ask(panel, LINK) == 403
    assert asyncio.get_running_loop().time() - started < 5


# ── کارتِ HTTPS در سلامت ─────────────────────────────────────────────────────
def _write_cert(root, issuer_dir: str, domain: str, *, days: float, org: str) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
                                    x509.NameAttribute(NameOID.COMMON_NAME, "R11")]))
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=days))
            .sign(key, hashes.SHA256()))
    d = root / "caddy" / "certificates" / issuer_dir / domain
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{domain}.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


@pytest.fixture
def caddy_data(panel, tmp_path, monkeypatch):
    root = tmp_path / "caddy-data"
    root.mkdir()
    monkeypatch.setattr(panel.aw, "_CADDY_DATA", str(root))
    return root


def _https_card(html: str) -> str:
    """فقط کارتِ HTTPS — ادعاها نباید از بجِ کارتِ دیگری سبز شوند."""
    start = html.index("HTTPS</h3>")
    end = html.find("<div class=card>", start)
    return html[start:end if end != -1 else None]


async def test_the_card_shows_each_domain_and_its_certificate(panel, domains, caddy_data):
    await domains.set("link_domain", LINK)
    _write_cert(caddy_data, "acme-v02.api.letsencrypt.org-directory", PANEL, days=80,
                org="Let's Encrypt")
    expires = (datetime.now(timezone.utc) + timedelta(days=80)).strftime("%Y-%m-%d")
    html = await _fetch(panel, "/health")
    card = _https_card(html)
    shows(card, PANEL, f"معتبر تا {expires}", LINK, "هنوز صادر نشده")
    assert "badge ok" in card
    shows(card, "telabzar logs caddy")          # راهنما فقط وقتی چیزی صادر نشده
    assert not undefined_in(html), undefined_in(html)


async def test_a_soon_expiring_certificate_is_a_warning(panel, domains, caddy_data):
    _write_cert(caddy_data, "acme-v02.api.letsencrypt.org-directory", PANEL, days=3,
                org="Let's Encrypt")
    card = _https_card(await _fetch(panel, "/health"))
    assert "badge warn" in card and "badge ok" not in card
    assert "telabzar logs caddy" not in page_text(card)     # همه صادر شده‌اند → بی‌راهنما


async def test_of_two_issuers_the_later_expiry_wins(panel, domains, caddy_data):
    _write_cert(caddy_data, "acme.zerossl.com-v2-dv90", PANEL, days=10, org="ZeroSSL")
    _write_cert(caddy_data, "acme-v02.api.letsencrypt.org-directory", PANEL, days=60,
                org="Let's Encrypt")
    rows = await panel.aw._tls_status()
    assert rows[0]["role"] == "panel" and 59 <= rows[0]["days"] <= 60
    assert rows[0]["cert"]["issuer"] == "Let's Encrypt"


async def test_a_corrupt_certificate_file_does_not_break_the_page(panel, domains, caddy_data):
    d = caddy_data / "caddy" / "certificates" / "x" / PANEL
    d.mkdir(parents=True)
    (d / f"{PANEL}.crt").write_text("not a certificate")
    card = _https_card(await _fetch(panel, "/health"))
    shows(card, PANEL, "هنوز صادر نشده")


async def test_no_domain_means_no_https_card(panel, caddy_data, monkeypatch):
    monkeypatch.setattr(panel.aw.settings, "panel_domain", "")
    assert "HTTPS</h3>" not in await _fetch(panel, "/health")


# ── صدورِ پیش‌دستانه بعد از ذخیره ────────────────────────────────────────────
@pytest.fixture
def warmed(panel, monkeypatch):
    calls: list[str] = []

    async def fake(domain):
        calls.append(domain)

    monkeypatch.setattr(panel.aw, "_tls_warm", fake)
    return calls


async def _drain(panel):
    task = panel.client.server.app.get(panel.aw._TLS_WARM_TASK)
    if task is not None:
        await asyncio.wait_for(task, 5)


async def test_saving_a_link_domain_requests_its_certificate_now(panel, domains, warmed):
    """بدونِ این، اولین کاربری که روی لینک می‌زند صدور را راه می‌انداخت — و ادمین تا آن
    لحظه نمی‌فهمید DNS درست است یا نه."""
    r = await panel.client.post("/save", data=_settings_form(link_domain="https://DL.Example.com/"),
                                cookies=panel.cookies, allow_redirects=False)
    assert _shows_ok(await _follow(panel, r))
    await _drain(panel)
    assert warmed == [LINK]                       # شکلِ کانونیک، همان که Caddy می‌بیند


async def test_an_invalid_link_domain_is_refused_and_nothing_is_requested(panel, domains, warmed):
    from app import settings_store
    r = await panel.client.post("/save", data=_settings_form(link_domain="dl.example.com:8443"),
                                cookies=panel.cookies, allow_redirects=False)
    assert "dl.example.com:8443" in _error_text(await _follow(panel, r))
    await _drain(panel)
    assert warmed == [] and await settings_store.link_domain() == ""


async def test_the_panel_domain_cannot_be_saved_as_the_link_domain(panel, domains, warmed):
    r = await panel.client.post("/save", data=_settings_form(link_domain=PANEL),
                                cookies=panel.cookies, allow_redirects=False)
    assert PANEL in _error_text(await _follow(panel, r))
    assert warmed == []


async def test_no_link_domain_requests_nothing(panel, domains, warmed):
    r = await panel.client.post("/save", data=_settings_form(), cookies=panel.cookies,
                                allow_redirects=False)
    assert _shows_ok(await _follow(panel, r))
    await _drain(panel)
    assert warmed == []


def _tls_server_ctx(tmp_path, seen: list[str]) -> ssl.SSLContext:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "caddy")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256()))
    (tmp_path / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "k.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    ctx.sni_callback = lambda sock, server_name, _ctx: seen.append(server_name)
    return ctx


async def test_the_warm_up_handshake_carries_the_domain_as_sni(panel, tmp_path, monkeypatch, caplog):
    """Caddy سرتیفیکیت را بر اساسِ **SNI** انتخاب و صادر می‌کند، نه مقصدِ اتصال."""
    seen: list[str] = []
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0,
                                        ssl=_tls_server_ctx(tmp_path, seen))
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(panel.aw, "_CADDY_HOST", "127.0.0.1")
    monkeypatch.setattr(panel.aw, "_CADDY_PORT", port)
    with caplog.at_level(logging.INFO):
        async with server:
            await panel.aw._tls_warm(LINK)
    assert seen == [LINK]
    assert f"{LINK} answers over HTTPS" in caplog.text


async def test_a_failed_warm_up_is_a_warning_not_an_error(panel, monkeypatch, caplog):
    monkeypatch.setattr(panel.aw, "_CADDY_HOST", "127.0.0.1")
    monkeypatch.setattr(panel.aw, "_CADDY_PORT", 1)          # هیچ‌کس گوش نمی‌دهد
    with caplog.at_level(logging.WARNING):
        await panel.aw._tls_warm(LINK)                       # نباید raise کند
    assert "A record" in caplog.text


async def test_cleanup_cancels_a_pending_warm_up(panel):
    app = {"redis": panel.redis}
    task = asyncio.create_task(asyncio.sleep(30))
    app[panel.aw._TLS_WARM_TASK] = task
    await panel.aw._on_cleanup(app)
    await asyncio.sleep(0)
    assert task.cancelled()


# ── IPِ واقعیِ کلاینت ─────────────────────────────────────────────────────────
def _ip(aw, peer: str, xff: str | None = None) -> str:
    headers = {} if xff is None else {"X-Forwarded-For": xff}
    return aw._client_ip(make_mocked_request("POST", "/auth/verify", headers=headers)
                         .clone(remote=peer))


@pytest.mark.parametrize("peer,xff,want", [
    ("172.18.0.7", "198.51.100.7", "198.51.100.7"),          # Caddy روی شبکهٔ داکر
    ("127.0.0.1", "198.51.100.7", "198.51.100.7"),
    ("172.18.0.7", "6.6.6.6, 198.51.100.7", "198.51.100.7"),  # آخری را نزدیک‌ترین پروکسی نوشته
    ("::ffff:172.18.0.7", "198.51.100.7", "198.51.100.7"),
    ("172.18.0.7", "not-an-ip", "172.18.0.7"),
    ("172.18.0.7", None, "172.18.0.7"),
    # همتای عمومی: XFF را خودش نوشته. **IPِ واقعاً عمومی**، نه بازه‌های مستندسازی —
    # `ipaddress` آن‌ها (203.0.113.0/24، 2001:db8::/32) را `is_private` می‌داند، و
    # نسخهٔ اولِ همین تست با آن‌ها به دلیلِ غلط افتاد.
    ("8.8.8.8", "198.51.100.7", "8.8.8.8"),
    ("2606:4700:4700::1111", "198.51.100.7", "2606:4700:4700::1111"),
], ids=["docker-peer", "loopback-peer", "chain-last", "v4-mapped", "garbage-xff", "no-xff",
        "public-peer", "public-v6-peer"])
def test_the_client_ip_trusts_forwarding_only_from_inside(panel, peer, xff, want):
    assert _ip(panel.aw, peer, xff) == want


async def test_two_clients_behind_caddy_get_two_login_buckets(panel, clock):
    """پشتِ Caddy همهٔ اتصال‌ها از یک IPِ داخلی می‌آیند. بدونِ XFF، مهاجم با پرکردنِ همان
    یک سطل ورودِ ادمینِ واقعی را می‌بست. (آستانهٔ ۳۰ = سقفِ per-IPِ verify.)"""
    aid = str(panel.admin_id)

    async def verify(ip):
        r = await panel.client.post("/auth/verify", data={"admin_id": aid, "code": "000000"},
                                    headers={"X-Forwarded-For": ip}, allow_redirects=False)
        return await r.text()

    for _ in range(30):
        await verify("198.51.100.66")
    assert "از این آدرس" in await verify("198.51.100.66")       # سطلِ مهاجم پر شد
    assert "از این آدرس" not in await verify("198.51.100.7")    # ادمین سطلِ خودش را دارد
