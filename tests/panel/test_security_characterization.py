"""ثبتِ **رفتارِ امروزِ** سه یافتهٔ امنیتیِ ممیزیِ فاز ۱ — نه تأییدشان.

⚠️ این فایل عمداً رفتارِ **باگ‌دار** را pin می‌کند. هدفش این نیست که بگوید این
رفتار درست است؛ هدفش این است که فاز ۲ وقتی رفعشان می‌کند **آشکارا قرمز شود** و
کسی مجبور شود این فایل را کنارِ رفع به‌روز کند. تستِ سبز این‌جا یعنی «هنوز رفع
نشده»، نه «سالم است».

هر تست دو نیم دارد: ادعای وضعِ فعلی، و — جایی که ممکن است — یک **کنترل** که
باید بعد از رفع هم سبز بماند. بدونِ کنترل، رفعِ فاز ۲ فقط «چند تست قرمز شد»
می‌شود و معلوم نمی‌شود چیزِ درستی هم حفظ شده یا نه.

جزئیاتِ آسیب‌پذیری‌ها عمداً این‌جا **نیست** — ریپو عمومی است. فقط رفتارِ
قابل‌مشاهده ثبت می‌شود.
"""
from __future__ import annotations

import pytest


# ── A-1: مشتقِ کلیدِ سشن — **رفع شد ۲۰۲۶-۰۸-۱۷** ───────────────────────────
# تستِ `TODAY` این بند حذف شد چون ادعایش دیگر صادق نیست: با رازِ خالی، کلید از
# `BOT_TOKEN` مشتق **نمی‌شود** و پنل اصلاً سرو نمی‌کند. جایش سه ادعای رفتارِ
# درست نشسته، به‌علاوهٔ کنترل‌هایی که از قبل بودند و باید سبز بمانند.
async def test_an_empty_admin_secret_no_longer_yields_a_usable_key(panel, monkeypatch):
    """با رازِ خالی، ساختِ کلید **می‌ترکد** — نه اینکه به `BOT_TOKEN` بیفتد."""
    monkeypatch.setattr(panel.aw.settings, "admin_secret", "")
    with pytest.raises(RuntimeError, match="ADMIN_SECRET"):
        panel.aw._fernet()


async def test_a_bot_token_cookie_is_rejected_when_the_secret_is_empty(panel, monkeypatch):
    """و مسیرِ درخواست **بسته** برمی‌گردد، نه ۵۰۰.

    نبودِ راز باید به «هیچ‌کس نمی‌تواند وارد شود» ترجمه شود؛ رگبارِ ۵۰۰ هم
    نشتِ اطلاعات است هم اپراتور را گمراه می‌کند.
    """
    monkeypatch.setattr(panel.aw.settings, "admin_secret", "")
    forged = panel.forged_cookies(panel.aw.settings.bot_token)
    resp = await panel.client.get("/", cookies=forged, allow_redirects=False)
    assert resp.status == 302
    assert resp.headers["Location"] == "/login"


async def test_the_panel_refuses_to_start_without_a_secret(panel, monkeypatch):
    """`main()` پیش از سرو کردن متوقف می‌شود، و پیام دستورِ رفع را دارد."""
    monkeypatch.setattr(panel.aw.settings, "admin_secret", "")
    with pytest.raises(SystemExit) as exc:
        panel.aw._require_admin_secret()
    assert exc.value.code == 1
    # کنترلِ جهتِ عکس: با رازِ ست‌شده نباید متوقف شود.
    monkeypatch.setattr(panel.aw.settings, "admin_secret", "c" * 64)
    panel.aw._require_admin_secret()


def test_the_refusal_message_tells_the_operator_what_to_run():
    """پیامِ خطا باید **دستورِ اجرایی** بدهد نه فقط شکایت.

    اپراتوری که این را در `docker compose logs admin` می‌بیند باید بتواند
    بدونِ باز کردنِ سورس رفعش کند.
    """
    from app import admin_web
    msg = admin_web._NO_SECRET
    assert "openssl rand -hex 32" in msg
    assert "ADMIN_SECRET" in msg and ".env" in msg
    assert "docker compose up -d admin" in msg


async def test_a_set_admin_secret_makes_the_bot_token_useless(panel, monkeypatch):
    """کنترل: با رازِ ست‌شده، کوکیِ مشتق از `BOT_TOKEN` رد می‌شود.

    این نیمه باید **بعد از رفعِ فاز ۲ هم سبز بماند**. اگر قرمز شد یعنی رفع
    چیزِ دیگری را هم شکسته.
    """
    monkeypatch.setattr(panel.aw.settings, "admin_secret", "a" * 64)
    forged = panel.forged_cookies(panel.aw.settings.bot_token)
    resp = await panel.client.get("/", cookies=forged, allow_redirects=False)
    assert resp.status == 302
    assert resp.headers["Location"] == "/login"


async def test_a_session_minted_under_one_secret_dies_under_another(panel, monkeypatch):
    """کنترل: چرخاندنِ راز، سشن‌های قبلی را باطل می‌کند.

    خاصیتِ مطلوبی است که باید بماند — و همان چیزی که ست‌کردنِ `ADMIN_SECRET`
    روی تولید انجام داد.
    """
    monkeypatch.setattr(panel.aw.settings, "admin_secret", "a" * 64)
    cookies = panel.cookies                      # با رازِ اول ساخته شد
    monkeypatch.setattr(panel.aw.settings, "admin_secret", "b" * 64)
    resp = await panel.client.get("/", cookies=cookies, allow_redirects=False)
    assert resp.status == 302


# ── A-2: توکنِ joinِ نود ────────────────────────────────────────────────────
@pytest.fixture
def no_wireguard(monkeypatch):
    """`add_peer` روی هاست می‌نویسد؛ در تست بی‌اثرش می‌کنیم."""
    from app import nodes as node_mod
    monkeypatch.setattr(node_mod, "add_peer", lambda *a, **kw: None)
    return node_mod


@pytest.fixture
async def join_token(panel, no_wireguard):
    """یک توکنِ joinِ معتبر، **مستقیم** از لایهٔ نود.

    عمداً از redirect بیرون کشیده نمی‌شود: تنها تستی که باید به شکلِ URL گره
    بخورد همان تستی است که دربارهٔ URL است. اگر بقیه هم `tok=` را از Location
    می‌خواندند، رفعِ فاز ۲ (بیرون‌بردنِ توکن از URL) یک‌جا چهار تست را
    می‌انداخت و معلوم نمی‌شد کدام ادعا واقعاً شکسته.
    """
    return await no_wireguard.make_join_token(panel.redis, "download")


async def test_TODAY_the_join_token_is_handed_back_in_the_redirect_url(panel, no_wireguard):
    """وضعِ فعلی: توکنِ join در query stringِ redirect می‌رود.

    ⚠️ رفتارِ باگ‌دار — query string در لاگِ دسترسی و تاریخچهٔ مرورگر می‌نشیند.
    **رفعِ فاز ۲ باید این را قرمز کند**: توکن نباید در URL باشد.
    """
    resp = await panel.client.post("/nodes/add", data={"role": "download"},
                                   cookies=panel.cookies, allow_redirects=False)
    assert resp.status == 302
    assert "tok=" in resp.headers["Location"], (
        "اگر این افتاد یعنی توکن دیگر در URL نیست — این تست را به‌روز کن.")


async def test_TODAY_an_unauthenticated_caller_can_redeem_that_token(panel, join_token):
    """وضعِ فعلی: `/node/join` عمومی است و با توکن، پیکربندیِ سرویس‌ها را می‌دهد.

    ⚠️ رفتارِ باگ‌دار در **ترکیب** با تستِ بالا: توکنی که در لاگ نشسته، بدونِ
    هیچ احراز هویتی قابلِ استفاده است. **رفعِ فاز ۲ باید این را قرمز کند.**

    محتوای پاسخ عمداً assert نمی‌شود (ریپو عمومی است)؛ فقط اینکه صدا زدنش
    **بدونِ کوکی** موفق است و پیکربندی برمی‌گرداند.
    """
    resp = await panel.client.post("/node/join",             # ← بدونِ کوکی
                                   json={"token": join_token, "pubkey": "k" * 44})
    assert resp.status == 200
    cfg = await resp.json()
    assert "services" in cfg and cfg["services"], (
        "اگر این افتاد یعنی مسیرِ join سفت شده — این تست را به‌روز کن.")


async def test_a_forged_join_token_is_rejected(panel, no_wireguard):
    """کنترل: توکن امضا دارد؛ ساختگی‌اش رد می‌شود. بعد از رفع هم باید سبز بماند."""
    resp = await panel.client.post("/node/join",
                                   json={"token": "not.a.real.token", "pubkey": "k" * 44})
    assert resp.status == 403


async def test_a_join_token_cannot_be_replayed(panel, join_token):
    """کنترل: توکن یک‌بارمصرف است. بعد از رفع هم باید سبز بماند."""
    first = await panel.client.post("/node/join", json={"token": join_token, "pubkey": "a" * 44})
    second = await panel.client.post("/node/join", json={"token": join_token, "pubkey": "b" * 44})
    assert first.status == 200
    assert second.status == 403


# ── A-3: ترتیبِ مصرف و اعتبارسنجیِ توکن ────────────────────────────────────
async def test_TODAY_a_malformed_join_burns_the_token(panel, join_token):
    """وضعِ فعلی: توکن **پیش از** اعتبارسنجیِ درخواست مصرف می‌شود.

    ⚠️ رفتارِ باگ‌دار: یک درخواستِ ناقص (بدونِ pubkey) توکن را می‌سوزاند، پس
    تلاشِ بعدیِ نودِ واقعی «invalid or used token» می‌گیرد. **رفعِ فاز ۲ باید
    این را قرمز کند** — یعنی بعد از یک ۴۰۰، همان توکن باید هنوز کار کند.
    """
    bad = await panel.client.post("/node/join", json={"token": join_token})  # بدونِ pubkey
    assert bad.status == 400

    retry = await panel.client.post("/node/join", json={"token": join_token, "pubkey": "c" * 44})
    assert retry.status == 403, (
        "اگر این ۲۰۰ شد یعنی ترتیب اصلاح شده و توکن دیگر با یک درخواستِ ناقص "
        "نمی‌سوزد — این تست را به‌روز کن.")
