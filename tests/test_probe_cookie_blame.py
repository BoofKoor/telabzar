"""حلقهٔ probe باید به اندازهٔ حلقهٔ fetch ایمن باشد.

سه چیز در یک هدف: کلاسِ خطا به استخر برسد، شکست در لاگ دیده شود، و حلقه سقف
داشته باشد. هر سه در همان ۱۶ خطِ `run_download` بودند که تا امروز **هیچ تستی
واردش نمی‌شد** — جهش‌آزمایی نشان داد حذفِ کاملِ `mark_fail`ِ این شاخه صفر تست
را می‌شکند. پس هر تستِ این فایل از `run_download`ِ **واقعی** می‌رود؛ صداکردنِ
مستقیمِ `ck.mark_fail`/`_resolve_blame` تابعِ کمکی را تست می‌کند و اتصال را نه،
که دقیقاً همان شکافی است که این فایل برای بستنش هست.

هارنس عمداً یک `yt-dlp`ِ **اجراییِ واقعی** روی PATH است، نه `D.probe`ِ ماک‌شده:
پیامی که `classify_error` می‌بیند خروجیِ `_stderr_summary` است نه رشتهٔ خامی که
تست دوست دارد، و ماک‌کردنِ `probe` همان تفاوت را پنهان می‌کرد.

سه تلهٔ توخالی‌شدن که با اجرا پیدا شدند و طراحیِ این فایل دورشان می‌زند:

۱) `assert fail_streak == 0` روی یک ۴۲۹ **امروز هم سبز است** — چون
   `_is_cookie_error` عبارتِ `429`/`too many requests` را ندارد، پس آن خطا
   اصلاً به `mark_fail` نمی‌رسد و ادعا بی‌ربط به رفع می‌شود. تست‌های این‌جا
   متن‌هایی می‌گیرند که واقعاً از گارد رد می‌شوند، و یک assertِ صریح روی خودِ
   `_is_cookie_error` این پیش‌شرط را پین می‌کند تا با تغییرِ فهرست بی‌صدا نپوسد.
۲) `assert bot.messages` امروز هم سبز است، چون `_alert_if_low` یک DMِ 🔴
   می‌فرستد. پس تستِ چک‌پوینت روی نشانهٔ 🛑 **و** کلیدِ throttleِ `ckcheck:`
   assert می‌کند، نه روی «پیامی آمد».
۳) `assert last_error != ""` با رفعی که `message=` را فراموش کند سبز می‌ماند
   (`'transient'`ِ خالی). پس علاوه بر کلاس، تکه‌ای از متنِ خودِ موتور هم خواسته
   می‌شود.
"""
from __future__ import annotations

import logging
import os
import stat
import textwrap

import pytest

from tests.aiogram_double import ValidatingBot

from app import cookies as ck
from app import tasks_download as TD

# پیام‌هایی که واقعاً از موتور می‌آیند. `probe()` استرِر را از `_stderr_summary`
# رد می‌کند، پس خطِ `ERROR:` همان چیزی است که به `classify_error` می‌رسد.
MSG_TRANSIENT = ("An unexpected error occurred: JSONDecodeError - "
                 "Expecting value: line 1 column 1 (char 0)")
MSG_RATE = "rate limit exceeded, try again later"
MSG_CHECKPOINT = "your account has been disabled; confirm your identity to continue"
MSG_BOTCHECK = ("Sign in to confirm you're not a bot. "
                "Use --cookies-from-browser or --cookies for the authentication.")
MSG_LOGIN = "Unable to download API page: HTTP Error 403: Forbidden"
MSG_CONTENT = "Video unavailable. This video has been removed by the uploader"

_FAKE_YTDLP = r'''#!/usr/bin/env python3
"""yt-dlpِ جعلی: هر فراخوانی را ثبت می‌کند و با پیامِ $FAKE_ERR می‌افتد."""
import os, sys
with open(os.environ["FAKE_LOG"], "a") as fh:
    argv = sys.argv[1:]
    ckp = argv[argv.index("--cookies") + 1] if "--cookies" in argv else ""
    fh.write(os.path.basename(ckp) + "\n")
sys.stderr.write("ERROR: [youtube] abc: %s\n" % os.environ["FAKE_ERR"])
sys.exit(1)
'''

NETSCAPE = ("# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tLOGIN_INFO\tvalue\n")


class FakeBot(ValidatingBot):
    """فقط چیزی که `run_download` صدا می‌زند؛ امضاها از خودِ aiogram می‌آیند."""

    def __init__(self) -> None:
        self.edits: list[str] = []
        self.messages: list[str] = []

    def _on(self, name, payload):
        if name == "edit_message_text":
            self.edits.append(payload["text"])
        elif name == "edit_message_caption":
            self.edits.append(payload.get("caption"))
        elif name == "send_message":
            self.messages.append(payload["text"])
        return True


@pytest.fixture
def ytdlp(tmp_path, monkeypatch):
    """یک `yt-dlp`ِ اجرایی روی PATH که پیامِ خطایش از تست تنظیم می‌شود."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "yt-dlp"
    script.write_text(textwrap.dedent(_FAKE_YTDLP))
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    logpath = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_LOG", str(logpath))

    def _set(err: str) -> None:
        monkeypatch.setenv("FAKE_ERR", err)

    _set("boom")
    _set.calls = lambda: [ln for ln in logpath.read_text().splitlines()] \
        if logpath.exists() else []
    return _set


@pytest.fixture
def payload(tmp_path, monkeypatch):
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "work"))
    os.makedirs(tmp_path / "work", exist_ok=True)
    return {"ref": "prb00001", "chat_id": 7, "status_mid": 9, "lang": "fa",
            "url": "https://www.youtube.com/watch?v=abc", "platform": "youtube",
            "engine": "ytdlp", "phase": "probe", "owner_id": 1, "tg_user_id": 42}


async def _stock(redis, monkeypatch, tmp_path, n: int) -> list[str]:
    """استخرِ واقعی روی دیسک + آینهٔ Redis، از همان مسیرِ `_save_cookie`ِ تولید."""
    ckdir = tmp_path / "ck"
    os.makedirs(ckdir, exist_ok=True)
    monkeypatch.setattr(ck.settings, "cookies_dir", str(ckdir))
    names = [f"cookies_youtube-{c}.txt" for c in "abcdefgh"[:n]]
    for name in names:
        assert await ck._save_cookie(redis, name, NETSCAPE) == ""
    assert len(await ck.accounts(redis, "youtube")) == n, \
        "تست باید واقعاً اکانت داشته باشد وگرنه هر ادعایی دربارهٔ استخر توخالی است"
    return names


async def _run(redis, payload, bot=None):
    bot = bot or FakeBot()
    await TD.run_download({"bot": bot, "redis": redis}, payload)
    return bot


# ── ادعای اصلی: یک خطای مبهم نباید کلِ استخر را بخواباند ──────────────
async def test_a_probe_transient_does_not_bench_the_whole_pool(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """این ادعای اصلیِ کل تغییر است، و **سطحش استخر است نه اکانت**.

    حلقهٔ probe سقف نداشت، پس یک `JSONDecodeError` تا تهِ استخر می‌رفت و چون
    `mark_fail` بی‌کلاس صدا زده می‌شد هر اکانتی که لمس می‌کرد ضربه و کول‌داون
    می‌گرفت. اندازه‌گیری‌شده روی سورسِ پیش از رفع: ۰ از ۳ قابلِ‌استفاده.
    """
    names = await _stock(redis, monkeypatch, tmp_path, 3)
    ytdlp(MSG_TRANSIENT)
    # پیش‌شرط را پین کن: اگر این خطا از گارد رد نشود، تست چیزی را که ادعا
    # می‌کند نمی‌سنجد (تلهٔ ۱).
    assert TD._is_cookie_error("ERROR: " + MSG_TRANSIENT, "youtube") is True
    assert ck.classify_error("ERROR: " + MSG_TRANSIENT) == ck.TRANSIENT

    await _run(redis, payload)

    total, usable = await ck.pool_counts(redis, "youtube")
    assert (total, usable) == (3, 3), "یک خطای مبهم نباید هیچ اکانتی را از سرویس خارج کند"
    for acct in await ck.accounts(redis, "youtube"):
        assert acct["fail_streak"] == 0
        assert await redis.ttl(ck._CK_CD + acct["name"]) == -2, "کول‌داون نباید ست شود"
    assert set(names) == {a["name"] for a in await ck.accounts(redis, "youtube")}


async def test_a_probe_rate_limit_costs_no_strike(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """محدودیتِ نرخ یعنی *ما* تند رفته‌ایم — استراحت بله، ضربه نه."""
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp(MSG_RATE)
    # تلهٔ ۱: متنِ رایجِ «429 Too Many Requests» اصلاً از گارد رد نمی‌شود، پس
    # تستی که آن را بگیرد امروز هم سبز است و هیچ‌چیز اثبات نمی‌کند.
    assert TD._is_cookie_error("ERROR: " + MSG_RATE, "youtube") is True
    assert ck.classify_error("ERROR: " + MSG_RATE) == ck.RATE_LIMIT

    await _run(redis, payload)

    acct = (await ck.accounts(redis, "youtube"))[0]
    assert acct["fail_streak"] == 0, "محدودیتِ نرخ نباید شمارنده را بالا ببرد"
    ttl = await redis.ttl(ck._CK_CD + acct["name"])
    assert ttl > 0, "ولی باید استراحتِ بلند بگیرد"
    assert ttl > ck.default_limits().cooldown, \
        "استراحتِ محدودیتِ نرخ باید بلندتر از کول‌داونِ پایه باشد، نه پلکانیِ آن"


async def test_a_probe_checkpoint_freezes_the_account(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """چک‌پوینت با تلاشِ خودکار حل نمی‌شود → فریز، نه کول‌داون."""
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp(MSG_CHECKPOINT)
    assert ck.classify_error("ERROR: " + MSG_CHECKPOINT) == ck.CHECKPOINT
    assert ck.needs_human(ck.CHECKPOINT) is True

    await _run(redis, payload)

    acct = (await ck.accounts(redis, "youtube"))[0]
    assert acct["frozen"] is True
    assert acct["status"] == ck.FROZEN
    assert acct["fail_streak"] == 0, "فریز جای شمارنده را می‌گیرد، نه اینکه رویش سوار شود"


async def test_a_probe_checkpoint_tells_the_admin(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """تلهٔ ۲: `assert bot.messages` امروز هم سبز است.

    امروز هم یک DM می‌آید — ولی 🔴«کوکیِ سالمی نمانده»ی `_alert_if_low`، نه
    🛑«نیازمندِ رسیدگی». پس ادعا باید روی همان پیامِ مشخص و کلیدِ throttleِ
    خودش باشد.
    """
    names = await _stock(redis, monkeypatch, tmp_path, 1)
    monkeypatch.setattr(TD.settings, "admin_ids", "42")
    ytdlp(MSG_CHECKPOINT)

    bot = await _run(redis, payload)

    checkpoint_dms = [m for m in bot.messages if m.startswith("🛑")]
    assert len(checkpoint_dms) == 1, f"دقیقاً یک DMِ چک‌پوینت انتظار می‌رود: {bot.messages}"
    assert await redis.exists(f"ckcheck:{names[0]}"), \
        "throttleِ ۶ساعتهٔ `_alert_checkpoint` باید ست شده باشد"


# `ids` صریح و **بدونِ فاصله**، نه به‌خاطرِ خوانایی: دفترچهٔ سابوتاژ نامِ تستِ
# افتاده را از خروجیِ pytest با شکستنِ روی فاصله برمی‌دارد، پس idِ خودکار (که
# از خودِ پیام ساخته می‌شود و فاصله دارد) باعث می‌شود یک سابوتاژِ **موفق** به‌شکلِ
# «نگرفت» گزارش شود. اولین اجرای این دفترچه دقیقاً همین را داد.
@pytest.mark.parametrize("msg,expected_cls,fragment", [
    (MSG_TRANSIENT, ck.TRANSIENT, "JSONDecodeError"),
    (MSG_RATE, ck.RATE_LIMIT, "rate limit exceeded"),
    (MSG_CHECKPOINT, ck.CHECKPOINT, "confirm your identity"),
    (MSG_BOTCHECK, ck.BOT_CHECK, "not a bot"),
    (MSG_LOGIN, ck.LOGIN_REQUIRED, "403"),
], ids=["transient", "rate_limit", "checkpoint", "bot_check", "login_required"])
async def test_a_probe_failure_records_why_in_the_panel(
        ytdlp, payload, redis, tmp_path, monkeypatch, msg, expected_cls, fragment):
    """تلهٔ ۳: `last_error != ""` با فراموشیِ `message=` هم سبز می‌ماند.

    آن‌وقت پنل رشتهٔ خالیِ `'transient'` را نشان می‌دهد که برای ادمین بی‌فایده
    است. پس هم کلاس خواسته می‌شود هم تکه‌ای از متنِ خودِ موتور.
    """
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp(msg)

    await _run(redis, payload)

    acct = (await ck.accounts(redis, "youtube"))[0]
    assert acct["last_error"].startswith(expected_cls), \
        f"کلاس باید ثبت شود: {acct['last_error']!r}"
    assert fragment in acct["last_error"], \
        f"متنِ موتور هم باید ثبت شود وگرنه ادمین چیزی برای دیدن ندارد: {acct['last_error']!r}"


# ── سقفِ تلاش ─────────────────────────────────────────────────────────
async def test_the_probe_loop_stops_at_dl_max_cookie_tries(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """بدونِ سقف، یک خطای کوکی‌محور کلِ استخر را می‌پیماید."""
    await _stock(redis, monkeypatch, tmp_path, 5)
    monkeypatch.setattr(TD.settings, "dl_max_cookie_tries", 2)
    ytdlp(MSG_BOTCHECK)

    await _run(redis, payload)

    calls = ytdlp.calls()
    assert len(calls) == 2, f"سقف باید بعد از ۲ تلاش بایستد، نه ۵ تا: {calls}"
    assert len(set(calls)) == 2, "و آن دو تلاش باید با دو اکانتِ متفاوت باشند"
    touched = [a for a in await ck.accounts(redis, "youtube") if a["fail_streak"]]
    assert len(touched) == 2, "فقط همان دو اکانت باید ضربه خورده باشند"


# ── خطِ لاگ (تنها راهِ اندازه‌گیریِ توزیعِ خطای probe) ─────────────────
async def test_a_probe_failure_is_greppable_in_the_log(
        ytdlp, payload, redis, tmp_path, monkeypatch, caplog):
    """تا امروز شکستِ probe در لاگ **نامرئی** بود: تنها خطِ آن نامِ اکانت را
    می‌نوشت و متنِ خطا را هرگز، پس هر سرشماریِ لاگ عملاً آمارِ fetch بود."""
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp(MSG_TRANSIENT)

    with caplog.at_level(logging.INFO, logger="telabzar.dl"):
        await _run(redis, payload)

    lines = [r.getMessage() for r in caplog.records if r.name == "telabzar.dl"]
    hits = [ln for ln in lines if "probe attempt" in ln]
    assert len(hits) == 1, f"هر شکستِ probe باید دقیقاً یک خط بدهد: {lines}"
    assert ck.TRANSIENT in hits[0], f"کلاس باید در خط باشد: {hits[0]!r}"
    assert "JSONDecodeError" in hits[0], f"تکه‌ای از متنِ موتور هم: {hits[0]!r}"


# ── کنترل‌ها: باید روی سورسِ قبل و بعد **هر دو** سبز باشند ─────────────
@pytest.mark.parametrize("seed", [0, 1])
async def test_a_probe_bot_check_is_punished_exactly_as_before(
        ytdlp, payload, redis, tmp_path, monkeypatch, seed):
    """کنترلِ معکوسِ اصلی.

    فرمِ غالبِ خطای یوتیوب در تولید همین است و `burns_account(bot_check)` صادق
    است، پس رفع **نباید** این را نرم کند. اگر این تست سبز نماند، رفع از هدفش
    فراتر رفته و تقصیرِ درست را هم خنثی کرده است.
    """
    names = await _stock(redis, monkeypatch, tmp_path, 1)
    meta = await ck.get_meta(redis, names[0])
    meta["fail_streak"] = seed
    await ck.set_meta(redis, names[0], meta)
    ytdlp(MSG_BOTCHECK)

    await _run(redis, payload)

    acct = (await ck.accounts(redis, "youtube"))[0]
    assert acct["fail_streak"] == seed + 1, "بات‌چک باید مثلِ قبل شمارنده را بالا ببرد"
    assert await redis.ttl(ck._CK_CD + names[0]) > 0, "و کول‌داونِ پلکانی بگیرد"


async def test_a_probe_login_required_is_punished_exactly_as_before(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """کنترل: کلاسِ سوزانندهٔ دوم هم نباید نرم شود."""
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp(MSG_LOGIN)
    assert ck.burns_account(ck.classify_error("ERROR: " + MSG_LOGIN)) is True

    await _run(redis, payload)

    acct = (await ck.accounts(redis, "youtube"))[0]
    assert acct["fail_streak"] == 1
    assert await redis.ttl(ck._CK_CD + acct["name"]) > 0


async def test_a_non_cookie_probe_failure_still_records_nothing(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """کنترلِ دامنه: گاردِ `_is_cookie_error` عمداً دست‌نخورده ماند.

    ویدیوی حذف‌شده تقصیرِ هیچ اکانتی نیست و نباید چیزی رویش ثبت شود. اگر روزی
    آن گارد باز شد، این تست می‌افتد — که خواسته است، چون تغییرِ جداست.
    """
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp(MSG_CONTENT)
    assert TD._is_cookie_error("ERROR: " + MSG_CONTENT, "youtube") is False

    await _run(redis, payload)

    acct = (await ck.accounts(redis, "youtube"))[0]
    assert acct["fail_streak"] == 0
    assert acct["last_error"] == ""
    assert acct["status"] == ck.HEALTHY


async def test_the_probe_still_walks_to_the_next_account(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """کنترلِ شکلِ حلقه: سقف نباید چرخش را قبل از موعد بکشد.

    با سقفِ پیش‌فرضِ ۵ و استخرِ ۲تایی، هر دو اکانت باید امتحان شوند — همان
    رفتارِ امروز.
    """
    await _stock(redis, monkeypatch, tmp_path, 2)
    monkeypatch.setattr(TD.settings, "dl_max_cookie_tries", 5)
    ytdlp(MSG_BOTCHECK)

    await _run(redis, payload)

    calls = ytdlp.calls()
    assert len(calls) == 2, f"هر دو اکانت باید امتحان شوند: {calls}"
    assert len(set(calls)) == 2, "و با دو فایلِ کوکیِ متفاوت"


async def test_the_user_still_gets_the_botcheck_message(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """کنترل: این تغییر کارِ کمتری می‌کند، پیامِ کاربر را عوض نمی‌کند."""
    from app.i18n import t
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp(MSG_BOTCHECK)

    bot = await _run(redis, payload)

    assert bot.edits[-1] == t("fa", "dl_youtube_botcheck")
