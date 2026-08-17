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


# A-2 **رفع شد ۲۰۲۶-۰۸-۱۷**: تستِ `TODAY`ِ «توکن در URL است» حذف شد چون دیگر
# صادق نیست. سه ادعای رفتارِ درست جایش نشست.
async def test_the_join_token_never_appears_in_a_url(panel, no_wireguard):
    """نه در `Location`، نه در بدنهٔ صفحه‌ای که بعدش می‌آید.

    ادعا روی **خودِ توکن** است نه روی نامِ پارامتر: چکِ `"tok=" not in ...`
    با تغییرِ نامِ پارامتر بی‌صدا سبز می‌شد.
    """
    resp = await panel.client.post("/nodes/add", data={"role": "download"},
                                   cookies=panel.cookies, allow_redirects=False)
    assert resp.status == 302
    loc = resp.headers["Location"]
    assert loc == "/nodes", f"redirect باید بی‌کوئری باشد، بود: {loc!r}"

    stored = await panel.redis.get(f"njoinview:{panel.admin_id}")
    assert stored, "توکن باید در Redis برای همان ادمین ذخیره شده باشد"
    assert stored not in loc


async def test_the_install_command_is_shown_once_from_the_session(panel, no_wireguard):
    """صفحه توکن را از Redisِ بسته‌به‌سشن می‌خواند، و **یک‌بار** نشانش می‌دهد."""
    await panel.client.post("/nodes/add", data={"role": "download"},
                            cookies=panel.cookies, allow_redirects=False)
    first = await (await panel.client.get("/nodes", cookies=panel.cookies)).text()
    assert "/node/install.sh" in first and "sudo bash" in first

    second = await (await panel.client.get("/nodes", cookies=panel.cookies)).text()
    assert "sudo bash" not in second, (
        "رفرشِ صفحه نباید دوباره دستور را نشان دهد — نمایش یک‌بارمصرف است.")


async def test_another_admin_cannot_pick_up_the_token(panel, no_wireguard, monkeypatch):
    """توکن به شناسهٔ سازنده‌اش بسته است، نه به یک شناسهٔ عمومی."""
    monkeypatch.setattr(panel.aw.settings, "admin_ids", f"{panel.admin_id},222")
    await panel.client.post("/nodes/add", data={"role": "download"},
                            cookies=panel.cookies, allow_redirects=False)
    other = {panel.aw._COOKIE: panel.aw._make_session(222)}
    body = await (await panel.client.get("/nodes", cookies=other)).text()
    assert "sudo bash" not in body
    # کنترل: توکن هنوز برای صاحبش هست (یعنی تست بالا به «اصلاً ساخته نشد» تکیه نکرده)
    mine = await (await panel.client.get("/nodes", cookies=panel.cookies)).text()
    assert "sudo bash" in mine


async def test_the_token_never_reaches_the_access_log(panel, no_wireguard):
    """ادعای اصلیِ A-2، با **لاگِ واقعی** نه استدلال.

    لاگرِ `aiohttp.access` همان چیزی است که تولید استفاده می‌کند (`main()` →
    `run_app` بدونِ `access_log=None`، و `basicConfig(INFO)` آن را به stdout و
    در نتیجه به `docker compose logs admin` می‌برد). فرمتش `%r` دارد، یعنی
    **path + query string**.

    **کنترلِ منفی داخلِ خودِ تست**: اول assert می‌کنیم لاگ واقعاً خطِ درخواست را
    گرفته. بدونِ آن، «توکن در لاگ نیست» وقتی لاگ‌گیری اصلاً خاموش باشد هم صادق
    است — یعنی یک سبزِ توخالی.
    """
    import io
    import logging

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    alog = logging.getLogger("aiohttp.access")
    alog.addHandler(handler)
    alog.setLevel(logging.INFO)
    try:
        resp = await panel.client.post("/nodes/add", data={"role": "download"},
                                       cookies=panel.cookies, allow_redirects=False)
        # توکن را **پیش از** بارکردنِ صفحه بردار: نمایش یک‌بارمصرف است
        # (`getdel`)، پس خواندنِ بعدی تهی برمی‌گردد و پیش‌شرط را می‌شکند.
        token = await panel.redis.get(f"njoinview:{panel.admin_id}")
        await panel.client.get(resp.headers["Location"], cookies=panel.cookies)
    finally:
        alog.removeHandler(handler)

    logged = buf.getvalue()
    assert token, "پیش‌شرط: توکن باید ساخته شده باشد"
    assert "/nodes" in logged, (
        "لاگِ دسترسی چیزی ثبت نکرده — پس «توکن در لاگ نیست» چیزی ثابت نمی‌کند.")
    assert token not in logged, f"توکن در لاگِ دسترسی نشست:\n{logged}"


# ── C-2: نشتِ Referer، که نیمهٔ دومِ همین رفع است ─────────────────────────
async def test_every_response_carries_a_referrer_policy(panel):
    """روی صفحهٔ معمولی، روی ریدایرکت، و روی مسیرِ ناموجود.

    ریدایرکت‌ها مهم‌ترین‌اند: جریانِ نودها با `HTTPFound` کار می‌کند و لاگِ
    تولید نشان داد same-origin همان URL را در `Referer` تکثیر می‌کرده.
    """
    page = await panel.client.get("/nodes", cookies=panel.cookies)
    assert page.headers["Referrer-Policy"] == "no-referrer"

    redirect = await panel.client.get("/", allow_redirects=False)   # 302 به /login
    assert redirect.status == 302
    assert redirect.headers["Referrer-Policy"] == "no-referrer"

    missing = await panel.client.get("/no-such-page")
    assert missing.status == 404
    assert missing.headers["Referrer-Policy"] == "no-referrer"


async def test_an_unauthenticated_caller_can_still_redeem_a_valid_token(panel, join_token):
    """**باگ نیست و رفع نشد** — ثبت می‌شود تا کسی بعداً «رفعش» نکند.

    `/node/join` باید بی‌احراز‌هویت بماند: نودِ تازه پیش از پیوستن هیچ اعتبارنامه‌ای
    ندارد، و خودِ توکنِ یک‌بارمصرفِ امضاشده همان اعتبارنامه است. ممیزی این را
    **در ترکیب با نشتِ URL** خطرناک خوانده بود؛ با بسته‌شدنِ نشت، آنچه می‌ماند
    یک اندپوینتِ توکن‌گیت‌شدهٔ متعارف است.
    """
    resp = await panel.client.post("/node/join",             # ← بدونِ کوکی
                                   json={"token": join_token, "pubkey": "k" * 44})
    assert resp.status == 200
    cfg = await resp.json()
    assert "services" in cfg and cfg["services"]


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
# A-3 **رفع شد ۲۰۲۶-۰۸-۱۷**: تستِ `TODAY` حذف شد، رفتارِ درست جایش نشست.
async def test_a_malformed_join_does_not_burn_the_token(panel, join_token):
    """درخواستِ ناقص توکن را نمی‌سوزاند؛ تلاشِ بعدیِ نودِ واقعی موفق می‌شود."""
    bad = await panel.client.post("/node/join", json={"token": join_token})  # بدونِ pubkey
    assert bad.status == 400

    retry = await panel.client.post("/node/join", json={"token": join_token, "pubkey": "c" * 44})
    assert retry.status == 200, (
        "توکن باید بعد از یک درخواستِ ناقص هنوز معتبر باشد.")


async def test_an_oversized_pubkey_also_leaves_the_token_usable(panel, join_token):
    """همان قاعده برای شاخهٔ دومِ اعتبارسنجی، نه فقط شاخهٔ «غایب».

    دو شرط در یک `if`اند؛ تستِ تک‌شاخه‌ای با نصفه‌رفعِ آینده سبز می‌ماند.
    """
    bad = await panel.client.post("/node/join",
                                  json={"token": join_token, "pubkey": "x" * 65})
    assert bad.status == 400
    retry = await panel.client.post("/node/join", json={"token": join_token, "pubkey": "d" * 44})
    assert retry.status == 200


async def test_an_invalid_token_is_still_rejected_before_anything_is_created(panel, no_wireguard):
    """کنترل: جابه‌جاییِ ترتیب نباید اعتبارسنجیِ خودِ توکن را شل کند.

    توکنِ نامعتبر با pubkeyِ **درست** باید همچنان ۴۰۳ بگیرد و هیچ ردیفی نسازد.
    """
    from sqlalchemy import select as _select

    from app.models import Node as _Node
    resp = await panel.client.post("/node/join",
                                   json={"token": "bad.token", "pubkey": "e" * 44})
    assert resp.status == 403
    async with panel.aw.Sessionmaker() as s:
        rows = (await s.execute(_select(_Node))).scalars().all()
    assert rows == []
