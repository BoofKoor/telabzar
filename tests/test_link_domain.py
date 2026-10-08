"""دامنهٔ لینک (`link_domain`) و دامنهٔ پنل — قاعدهٔ نام، اعتبارسنجی، و ترتیبِ ساختنِ لینک.

این فایل عمداً **بیرونِ** `tests/panel/` است: `settings_store` و `routers/ops` هیچ‌کدام
استکِ پنل نمی‌خواهند، و قاعدهٔ نام دو مصرف‌کننده دارد که باید یکی بمانند — `_link_base`ِ
ربات (لینک را می‌سازد) و `/tls/ask`ِ پنل (سرتیفیکیتش را تأیید می‌کند). اگر روزی ربات
لینکی بسازد که پنل تأییدش نکند، کاربر لینکی می‌گیرد که هرگز HTTPS نمی‌شود — بی‌هیچ خطایی.
"""
from __future__ import annotations

import fakeredis.aioredis as fr
import pytest

from app import nodes, settings_store as ss
from app.routers import ops


# ── شکلِ نام ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,want", [
    ("dl.example.com", "dl.example.com"),
    ("DL.Example.COM.", "dl.example.com"),            # نقطهٔ پایانیِ DNS و حروفِ بزرگ
    ("https://DL.example.com/", "dl.example.com"),     # همان چیزی که ادمین از مرورگر paste می‌کند
    ("http://dl.example.com", "dl.example.com"),
    ("  dl.example.com/  ", "dl.example.com"),
    ("دانلود.example.com", "xn--mgbpb7fjn.example.com"),   # Let's Encrypt شکلِ punycode می‌خواهد
], ids=["plain", "case-and-dot", "https-url", "http-url", "spaces-slash", "idn"])
def test_a_pasted_domain_is_canonicalised(raw, want):
    assert ss.normalize_domain(raw) == want


@pytest.mark.parametrize("raw", ["", "   "], ids=["empty", "blank"])
def test_an_empty_domain_means_off_not_invalid(raw):
    assert ss.normalize_domain(raw) == ""


@pytest.mark.parametrize("raw", [
    "https://dl.example.com:8443",       # پورت: لینک همیشه روی ۴۴۳ِ Caddy است
    "dl.example.com:8443",
    "https://dl.example.com/files",      # مسیر
    "dl.example.com/files",
    "https://dl.example.com/?a=1",
    "https://dl.example.com/#x",
    "https://u:p@dl.example.com",
    "ftp://dl.example.com",
    "*.example.com",                     # wildcard با HTTP-01 صادر نمی‌شود
    "localhost",                         # یک‌برچسبی
    "1.2.3.4",                           # IP سرتیفیکیتِ دامنه نمی‌گیرد
    "-bad.example.com",
    "bad-.example.com",
    "a..example.com",
    "dl example.com",
    "dl_example.com",
    ("x" * 64) + ".example.com",         # برچسبِ بیش از ۶۳
    ".".join(["a" * 60] * 5) + ".com",   # کلِ نام بیش از ۲۵۳
], ids=["url-port", "port", "url-path", "path", "query", "fragment", "userinfo", "ftp",
        "wildcard", "single-label", "ipv4", "lead-hyphen", "trail-hyphen", "empty-label",
        "space", "underscore", "long-label", "long-name"])
def test_a_domain_that_cannot_get_a_certificate_is_refused(raw):
    """رد می‌شود، **بی‌صدا دور ریخته نمی‌شود**: `:8443` یا `/files` یعنی ادمین چیزِ دیگری
    در ذهن دارد، و لینکِ متفاوتی که بی‌خبر ساخته شود از یک پیامِ خطا بدتر است."""
    assert ss.normalize_domain(raw) is None


# ── اعتبارسنجیِ پنل/`/admin` ────────────────────────────────────────────────
def test_link_domain_is_a_runtime_string_key():
    assert ss.RUNTIME_KEYS["link_domain"][0] == "str"


def test_the_panel_domain_is_deliberately_not_runtime():
    """پنلی که دامنهٔ خودش را عوض کند، با یک ذخیرهٔ اشتباه خودش را قفل می‌کند."""
    assert "panel_domain" not in ss.RUNTIME_KEYS


def test_a_valid_or_empty_link_domain_passes(monkeypatch):
    monkeypatch.setattr(ss.settings, "tls_cert", "")
    assert ss.validate_value("link_domain", "dl.example.com") is None
    assert ss.validate_value("link_domain", "https://dl.example.com/") is None
    assert ss.validate_value("link_domain", "") is None          # خاموش‌کردن


def test_an_invalid_link_domain_is_refused_with_a_reason(monkeypatch):
    monkeypatch.setattr(ss.settings, "tls_cert", "")
    err = ss.validate_value("link_domain", "dl.example.com:8443")
    assert err and "dl.example.com:8443" in err


def test_the_link_domain_cannot_be_the_panel_domain(monkeypatch):
    """Caddy میزبانِ پنل را به پنل می‌فرستد: لینک روی آن ۴۰۴ِ پنل می‌گرفت، و محتوای
    کاربر هم‌مبدأ با پنل سرو می‌شد. مقایسه روی شکلِ **کانونیک** است."""
    monkeypatch.setattr(ss.settings, "tls_cert", "")
    monkeypatch.setattr(ss.settings, "panel_domain", "panel.example.com")
    err = ss.validate_value("link_domain", "https://Panel.Example.com/")
    assert err and "panel.example.com" in err
    assert ss.validate_value("link_domain", "dl.example.com") is None    # کنترل


def test_a_legacy_origin_certificate_install_is_told_to_reconfigure(monkeypatch):
    """با `TLS_CERT` ست، گیت‌وی خودش TLS حرف می‌زند و Caddy (HTTPِ ساده) فقط ۵۰۲ می‌گرفت —
    هر لینک بی‌صدا می‌شکست. خاموش‌کردن (مقدارِ خالی) همچنان مجاز است."""
    monkeypatch.setattr(ss.settings, "tls_cert", "/certs/cert.pem")
    err = ss.validate_value("link_domain", "dl.example.com")
    assert err and "telabzar reconfigure" in err
    assert ss.validate_value("link_domain", "") is None


# ── تنها خواننده ────────────────────────────────────────────────────────────
@pytest.fixture
def store(monkeypatch):
    """storeِ واقعی روی fakeredis، با کشِ از-پیش-پرشده — هیچ خواندنی به Postgres نمی‌رسد."""
    r = fr.FakeRedis(decode_responses=True)
    s = ss.SettingsStore(r)
    monkeypatch.setattr(ss, "_store", s)
    return s


async def _seed(store, **values):
    for key in ("link_domain", "stream_base"):
        v = values.get(key)
        await store.r.set(ss._PREFIX + key, ss._MISSING if v is None else v)


async def test_the_reader_canonicalises_what_the_panel_stored(store):
    await _seed(store, link_domain="https://DL.Example.com/")
    assert await ss.link_domain() == "dl.example.com"


async def test_a_broken_stored_value_reads_as_off_not_as_a_broken_link(store):
    """مقداری که از اعتبارسنجی رد نشده (env، یا نوشتنِ مستقیم) لینکِ شکسته نمی‌سازد."""
    await _seed(store, link_domain="dl.example.com:8443")
    assert await ss.link_domain() == ""


async def test_without_a_store_the_env_default_is_used(monkeypatch):
    monkeypatch.setattr(ss, "_store", None)
    monkeypatch.setattr(ss.settings, "link_domain", "DL.example.com.")
    assert await ss.link_domain() == "dl.example.com"


def test_the_panel_domain_reader_canonicalises_the_env(monkeypatch):
    monkeypatch.setattr(ss.settings, "panel_domain", "Panel.Example.com.")
    assert ss.panel_domain() == "panel.example.com"
    monkeypatch.setattr(ss.settings, "panel_domain", "panel.example.com:2083")
    assert ss.panel_domain() == ""


# ── ترتیبِ ساختنِ لینک ─────────────────────────────────────────────────────
async def test_the_link_domain_builds_https_links(store, monkeypatch):
    monkeypatch.setattr(ops.settings, "public_base", "https://old.example.com:8443")
    await _seed(store, link_domain="dl.example.com")
    assert await ops._link_base() == "https://dl.example.com"


async def test_the_old_public_base_still_works_without_a_link_domain(store, monkeypatch):
    """نصب‌های پیش از ۲۰۲۶-۱۰: دامنهٔ لینک ست نشده، پس همان `PUBLIC_BASE`."""
    monkeypatch.setattr(ops.settings, "public_base", "https://old.example.com:8443/")
    await _seed(store)
    assert await ops._link_base() == "https://old.example.com:8443"


async def test_a_broken_link_domain_falls_back_instead_of_breaking(store, monkeypatch):
    monkeypatch.setattr(ops.settings, "public_base", "")
    await _seed(store, link_domain="not a domain")
    assert await ops._link_base() == ""     # دکمهٔ لینک خاموش، نه `https://not a domain`


async def test_a_live_stream_node_still_wins(store, monkeypatch):
    await _seed(store, link_domain="dl.example.com", stream_base="https://cdn.example.com/")
    await nodes.write_heartbeat(store.r, "g1", {"role": "gateway"})
    assert await ops._link_base() == "https://cdn.example.com"


async def test_a_dead_stream_node_falls_back_to_the_link_domain(store, monkeypatch):
    """`stream_base` ست ولی نودِ گیت‌وی خاموش → لینک روی دامنهٔ خودِ مستر، نه نودِ مرده."""
    await _seed(store, link_domain="dl.example.com", stream_base="https://cdn.example.com")
    assert await ops._link_base() == "https://dl.example.com"
