"""خواندنِ درستِ خطای یوتیوب — بررسیِ وابستگی به کوکی، ۲۰۲۶-۰۹.

**مسئله:** yt-dlp به هر دلیلِ یوتیوب که «sign in» داشته باشد جملهٔ
`Use --cookies-from-browser or --cookies …` را می‌چسباند، و فهرستِ نشانه‌های
bot-check همین `--cookies` (به‌علاوهٔ `sign in to confirm`) را داشت. پس ویدیوی
**خصوصی** و **سنی** «bot-check» خوانده می‌شدند، و «403» هم در نشانه‌های لاگین بود.
پیامدِ اندازه‌گیری‌شده روی دسته‌بندی‌کننده‌های واقعی:

  * probe (مسیرِ پیش‌فرضِ یوتیوب در تولید) یک لینکِ خصوصی را تا ۵ اکانت می‌چرخاند
    و به هرکدام ضربه + کول‌داون می‌زد، و کاربر «ادمین کوکی بگذارد» می‌گرفت؛
  * fetch با ≥۲ اکانت «خروجی مقصر است» را اعلام می‌کرد؛
  * ویدیوی سنی کوکی خرج می‌کرد فقط برای اینکه فیلترِ ایمنی بعدش ردش کند؛
  * ۴۰۳ِ دانلودِ رسانه (توکن/کلاینت/IP) اکانتِ سالم را می‌سوزاند؛
  * و «تکرارِ بدونِ pot» هر کدامِ این‌ها را دو برابر می‌کرد.

**هارنس:** متنِ خطا با **خودِ** yt-dlp ساخته می‌شود (`ExtractorError` + همان
`_youtube_login_hint` + همان ترکیبِ `reason`/`subreason`ِ `_real_extract`)، نه با
رشتهٔ دست‌نویس — §۶: «دابلی که قرارداد را خودش بازنویسی کند شکلِ API را پنهان
می‌کند». فقط متنِ دلیل‌ها (مالِ خودِ یوتیوب، نه yt-dlp) دست‌نویس است. رفتار از
`run_download`ِ **واقعی** با یک `yt-dlp`ِ اجراییِ جعلی روی PATH سنجیده می‌شود.
"""
from __future__ import annotations

import json
import os
import stat
import textwrap

import pytest

from tests.aiogram_double import ValidatingBot
# متنِ خطاها را خودِ yt-dlp می‌سازد — مشترک با تستِ ابزارِ سنجش
from tests.yt_errors import (
    AGE, API_403, BOT, FRAG_403, GVS_403, MEMBERS, PRIVATE, RATE, RELOAD, TRACEBACK)

from app import cookies as ck
from app import downloader as D
from app import probe_stats as PS
from app import tasks_download as TD
from app.i18n import t


def test_the_builder_reproduces_the_hint_that_caused_the_bug():
    """پیش‌شرط: متنِ ساخته‌شده همان `--cookies`ی را دارد که تشخیص را گول می‌زد.

    بدونِ این، ادعاهای پایین روی متنی سبز می‌شدند که اصلاً تله را ندارد.
    """
    for msg in (BOT, AGE, PRIVATE):
        assert "--cookies" in msg and msg.startswith("ERROR: [youtube] abc: ")
    assert "--cookies" not in MEMBERS and "--cookies" not in RELOAD


def test_the_fragment_builder_reproduces_the_carriage_return():
    """پیش‌شرط: متنِ واقعیِ yt-dlp همان `\\r`ِ بعد از `ERROR:` را دارد.

    بدونش تست‌های `_stderr_summary` پایین روی متنی سبز می‌شدند که تله را ندارد.
    """
    assert FRAG_403.startswith("ERROR: \r[download] Got error: HTTP Error 403")
    assert FRAG_403.splitlines()[0].strip() == "ERROR:"      # خودِ تله


# ── ۱) خواندنِ نوعِ خطا ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("msg,kind", [
    (BOT, D.YT_BOT_CHECK), (AGE, D.YT_AGE_GATE), (PRIVATE, D.YT_PRIVATE),
    (MEMBERS, D.YT_MEMBERS), (RELOAD, D.YT_RELOAD), (RATE, D.YT_RATE_LIMIT),
    (GVS_403, D.YT_GVS_403), (API_403, None),
], ids=["bot", "age", "private", "members", "reload", "rate", "gvs403", "api403"])
def test_each_youtube_error_reads_as_its_own_kind(msg, kind):
    assert D.youtube_error_kind(msg) == kind


@pytest.mark.parametrize("msg", [AGE, PRIVATE], ids=["age", "private"])
def test_a_sign_in_hint_alone_is_not_a_bot_check(msg):
    """خودِ باگ: پیش از رفع هر دو `True` بودند (به‌خاطرِ `--cookies`)."""
    assert D.is_youtube_botcheck(msg, "youtube") is False


def test_the_real_bot_check_is_still_a_bot_check():
    """کنترلِ معکوس: رفع نباید تشخیصِ اصلی را خاموش کند — هر دو آپاستروف."""
    assert D.is_youtube_botcheck(BOT, "youtube") is True
    assert D.is_youtube_botcheck(BOT.replace("’", "'"), "youtube") is True


def test_the_generic_classifier_no_longer_calls_an_age_gate_a_bot_check():
    """`cookies.classify_error` هم «sign in to confirm» را داشت → سنی = bot_check."""
    assert ck.classify_error(AGE) != ck.BOT_CHECK
    assert ck.classify_error(BOT) == ck.BOT_CHECK


@pytest.mark.parametrize("msg,cls", [
    (BOT, ck.BOT_CHECK), (RATE, ck.RATE_LIMIT),
    (GVS_403, ck.TRANSIENT), (RELOAD, ck.TRANSIENT),
    (API_403, ck.LOGIN_REQUIRED),
], ids=["bot", "rate", "gvs403", "reload", "api403"])
def test_the_pool_class_of_each_youtube_error(msg, cls):
    """۴۰۳ِ دانلود و reload ضربه نمی‌زنند؛ bot-check/محدودیتِ نرخ/۴۰۳ِ API مثلِ قبل."""
    assert TD._error_class(msg, "youtube") == cls


@pytest.mark.parametrize("msg,expected", [
    (PRIVATE, False), (MEMBERS, False), (AGE, False),
    (BOT, True), (RELOAD, True), (GVS_403, True), (RATE, True),
], ids=["private", "members", "age", "bot", "reload", "gvs403", "rate"])
def test_which_youtube_errors_are_worth_another_account(msg, expected):
    assert TD._is_cookie_error(msg, "youtube") is expected


def test_youtube_kinds_do_not_leak_into_other_platforms():
    """اینستاگرام «private» هم دارد — آن‌جا قواعدِ عمومی حاکم می‌مانند."""
    assert TD._yt_kind(PRIVATE, "instagram") is None
    assert TD._yt_kind(PRIVATE, "spotify") == D.YT_PRIVATE, \
        "پلتفرمِ ماچ از یوتیوب دانلود می‌کند، پس خطایش خطای یوتیوب است"


@pytest.mark.parametrize("msg,crash", [
    (f"download failed: {BOT}", False),
    ("download failed: KeyError: 'challenge'", True),
    ("download failed: ERROR: [youtube] abc: [pot:bgutil:http] boom", True),
    ("download timed out", False),
    ("download produced no file", False),
    ("download failed: unknown", False),
], ids=["clean", "traceback", "names-plugin", "timeout", "nofile", "unknown"])
def test_only_a_plugin_crash_earns_a_retry_without_pot(msg, crash):
    assert D.is_pot_crash(msg) is crash


# ── خلاصهٔ stderr: ۴۰۳ِ دانلودِ تکه‌ای ───────────────────────────────────────────
@pytest.mark.parametrize("raw", [FRAG_403 + "\n", "WARNING: slow\n" + FRAG_403 + "\n"],
                         ids=["alone", "after-warning"])
def test_a_fragment_download_error_keeps_its_text(raw):
    """پیش از رفع `_stderr_summary` این را «ERROR:» می‌کرد (`splitlines()` روی
    `\\r`): کاربر `<code>ERROR:</code>` می‌دید و ۴۰۳ ناشناخته می‌ماند. یافته‌شده
    حینِ ساختِ ابزارِ سنجش، که همین قالب را از `FileDownloader` بازتولید کرد."""
    summary = D._stderr_summary(raw.encode())
    assert summary.startswith("ERROR:") and "HTTP Error 403" in summary, summary
    assert D.youtube_error_kind(summary) == D.YT_GVS_403


@pytest.mark.parametrize("raw,expected", [
    (TRACEBACK + "\n", "KeyError: 'challenge'"),
    ("line one\nline two\n", "line one | line two"),
    ("WARNING: w\n" + GVS_403 + "\n", GVS_403),
], ids=["traceback", "last-two", "error-line"])
def test_the_summary_is_otherwise_unchanged(raw, expected):
    """کنترلِ معکوس: رفعِ `\\r` شاخه‌های دیگرِ خلاصه را عوض نکرده است."""
    assert D._stderr_summary(raw.encode()) == expected


# ── هارنسِ رفتاری ─────────────────────────────────────────────────────────────
_FAKE_YTDLP = r'''#!/usr/bin/env python3
"""yt-dlpِ جعلی: هر فراخوانی را ثبت می‌کند؛ خطا بسته به کوکی/pot از env می‌آید."""
import json, os, sys
argv = sys.argv[1:]
ckp = argv[argv.index("--cookies") + 1] if "--cookies" in argv else ""
pot = any(a.startswith("youtubepot-bgutilhttp:") for a in argv)
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(("ck" if ckp else "-") + "|" + ("pot" if pot else "nopot") + "\n")
err = os.environ.get("FAKE_ERR_COOKIE" if ckp else "FAKE_ERR_ANON", "")
if pot and os.environ.get("FAKE_ERR_POT"):
    err = os.environ["FAKE_ERR_POT"]
if not err and "-J" in argv:
    print(json.dumps({"id": "abc", "title": "Clip", "duration": 10, "thumbnail": None,
                      "formats": [{"format_id": "18", "height": 360, "vcodec": "avc1",
                                   "acodec": "mp4a", "tbr": 500}]}))
    sys.exit(0)
sys.stderr.write((err or "ERROR: this stub does not download") + "\n")
sys.exit(1)
'''

NETSCAPE = ("# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tLOGIN_INFO\tvalue\n")


class FakeBot(ValidatingBot):
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
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "yt-dlp"
    script.write_text(textwrap.dedent(_FAKE_YTDLP))
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_LOG", str(log))

    class _Ctl:
        def cookie(self, err: str) -> None:
            monkeypatch.setenv("FAKE_ERR_COOKIE", err)

        def anon(self, err: str) -> None:
            monkeypatch.setenv("FAKE_ERR_ANON", err)

        def with_pot(self, err: str) -> None:
            monkeypatch.setenv("FAKE_ERR_POT", err)

        def calls(self) -> list[str]:
            return log.read_text().splitlines() if log.exists() else []

    return _Ctl()


def _payload(tmp_path, monkeypatch, phase: str) -> dict:
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "work"))
    os.makedirs(tmp_path / "work", exist_ok=True)
    return {"ref": "ytk00001", "chat_id": 7, "status_mid": 9, "lang": "fa",
            "url": "https://www.youtube.com/watch?v=abc", "platform": "youtube",
            "engine": "ytdlp", "phase": phase, "selector": "best",
            "owner_id": 1, "tg_user_id": 42}


async def _stock(redis, monkeypatch, tmp_path, n: int) -> list[str]:
    ckdir = tmp_path / "ck"
    os.makedirs(ckdir, exist_ok=True)
    monkeypatch.setattr(ck.settings, "cookies_dir", str(ckdir))
    names = [f"cookies_youtube-{c}.txt" for c in "abcdefgh"[:n]]
    for name in names:
        assert await ck._save_cookie(redis, name, NETSCAPE) == ""
    assert len(await ck.accounts(redis, "youtube")) == n
    return names


async def _run(redis, payload) -> FakeBot:
    bot = FakeBot()
    await TD.run_download({"bot": bot, "redis": redis}, payload)
    return bot


async def _untouched(redis) -> None:
    """هیچ اکانتی نه ضربه خورده، نه کول‌داون گرفته، نه خطایی رویش نوشته شده."""
    for acct in await ck.accounts(redis, "youtube"):
        assert acct["fail_streak"] == 0, acct
        assert acct["last_error"] == "", acct
        assert await redis.ttl(ck._CK_CD + acct["name"]) == -2, acct


async def _exit_failures(redis) -> int:
    return sum(r.get("fail", 0) for r in await ck.exit_stats(redis, "youtube"))


# ── ۲) probe (مسیرِ پیش‌فرضِ یوتیوب در تولید) ──────────────────────────────────
async def test_probe_private_video_costs_one_attempt_and_no_account(
        ytdlp, redis, tmp_path, monkeypatch):
    """پیش از رفع: ۳ اکانت × ضربه + کول‌داون، و پیامِ bot-check به کاربر."""
    await _stock(redis, monkeypatch, tmp_path, 3)
    ytdlp.cookie(PRIVATE)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "probe"))

    assert len(ytdlp.calls()) == 1, f"هیچ اکانتی این ویدیو را نمی‌بیند: {ytdlp.calls()}"
    await _untouched(redis)
    assert bot.edits[-1] == t("fa", "dl_yt_private")
    assert await _exit_failures(redis) == 0, "ویدیوی خصوصی دربارهٔ خروجی چیزی نمی‌گوید"


async def test_probe_members_only_video_stops_without_strikes(
        ytdlp, redis, tmp_path, monkeypatch):
    await _stock(redis, monkeypatch, tmp_path, 2)
    ytdlp.cookie(MEMBERS)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "probe"))

    assert len(ytdlp.calls()) == 1
    await _untouched(redis)
    assert bot.edits[-1] == t("fa", "dl_yt_members")


async def test_probe_age_gate_is_blocked_without_a_second_account(
        ytdlp, redis, tmp_path, monkeypatch):
    """فیلترِ ایمنی روشن (پیش‌فرض): همان نتیجهٔ `check_meta`، بدونِ چرخش و ضربه."""
    await _stock(redis, monkeypatch, tmp_path, 3)
    ytdlp.cookie(AGE)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "probe"))

    assert len(ytdlp.calls()) == 1
    await _untouched(redis)
    assert bot.edits[-1] == t("fa", "nsfw_blocked")
    assert int(await redis.get(PS.key(PS.BLOCKED)) or 0) == 1, \
        "مثلِ شاخهٔ `check_meta`: سیاست رد کرد، نه شکستِ probe"
    assert not await redis.get(PS.key(PS.FAIL))


async def test_probe_age_gate_with_safety_off_rotates_without_strikes(
        ytdlp, redis, tmp_path, monkeypatch):
    """فیلتر خاموش: اکانتِ دیگر شاید احرازِ سن داشته باشد — چرخش بله، ضربه نه."""
    monkeypatch.setattr(TD.settings, "safety_enabled", False)
    await _stock(redis, monkeypatch, tmp_path, 2)
    ytdlp.cookie(AGE)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "probe"))

    assert len(ytdlp.calls()) == 2, "هر دو اکانت امتحان شوند"
    await _untouched(redis)
    assert bot.edits[-1] == t("fa", "dl_yt_age_login")


async def test_probe_page_reload_with_a_cookie_is_retried_once_without_one(
        ytdlp, redis, tmp_path, monkeypatch):
    """توصیهٔ yt-dlp (#17497): «The page needs to be reloaded» با کوکی → بی‌کوکی."""
    await _stock(redis, monkeypatch, tmp_path, 2)
    ytdlp.cookie(RELOAD)
    ytdlp.anon("")                                # بی‌کوکی جواب می‌دهد

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "probe"))

    assert [c.split("|")[0] for c in ytdlp.calls()] == ["ck", "-"]
    assert await redis.exists(PS.menu_key("ytk00001")), "منو باید ساخته شده باشد"
    assert t("fa", "dl_pick_quality", title="Clip") in bot.edits
    for a in await ck.accounts(redis, "youtube"):
        assert a["fail_streak"] == 0, "reload تقصیرِ اکانت نیست"


async def test_probe_page_reload_without_a_cookie_is_not_repeated(
        ytdlp, redis, tmp_path, monkeypatch):
    """استخرِ خالی: تلاشِ اول خودش بی‌کوکی بوده؛ تکرارش همان شکست است."""
    ytdlp.anon(RELOAD)

    await _run(redis, _payload(tmp_path, monkeypatch, "probe"))

    assert ytdlp.calls() == ["-|nopot"]


async def test_probe_bot_check_still_rotates_and_strikes(
        ytdlp, redis, tmp_path, monkeypatch):
    """کنترلِ معکوس: bot-checkِ واقعی همان رفتارِ قبلی را دارد."""
    await _stock(redis, monkeypatch, tmp_path, 2)
    ytdlp.cookie(BOT)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "probe"))

    assert len(ytdlp.calls()) == 2
    assert all(a["fail_streak"] == 1 for a in await ck.accounts(redis, "youtube"))
    assert bot.edits[-1] == t("fa", "dl_youtube_botcheck")


# ── ۳) fetch ─────────────────────────────────────────────────────────────────
async def test_fetch_private_video_never_escalates_to_a_cookie(
        ytdlp, redis, tmp_path, monkeypatch):
    await _stock(redis, monkeypatch, tmp_path, 3)
    ytdlp.anon(PRIVATE)
    ytdlp.cookie(PRIVATE)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    assert ytdlp.calls() == ["-|nopot"], "پاسِ بی‌کوکی کافی است؛ هیچ اکانتی کمکی نمی‌کند"
    await _untouched(redis)
    assert await _exit_failures(redis) == 0, "ویدیوی خصوصی دربارهٔ خروجی چیزی نمی‌گوید"
    assert bot.edits[-1] == t("fa", "dl_yt_private")


async def test_fetch_private_after_escalation_does_not_blame_the_exit(
        ytdlp, redis, tmp_path, monkeypatch):
    """bot-check بی‌کوکی → کوکی → «خصوصی»: پیش از رفع با ≥۲ اکانت «خروجی مقصر
    است» اعلام می‌شد (DMِ ادمین + کول‌داونِ خروجی + پیامِ «مشکلِ اتصال»)."""
    monkeypatch.setattr(TD.settings, "admin_ids", "99")
    await _stock(redis, monkeypatch, tmp_path, 3)
    ytdlp.anon(BOT)
    ytdlp.cookie(PRIVATE)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    assert [c.split("|")[0] for c in ytdlp.calls()] == ["-", "ck"]
    assert not await redis.exists(f"{ck._CK_EXIT_CD}master:youtube"), "خروجی مقصر نیست"
    assert not [m for m in bot.messages if m.startswith("🌐")], bot.messages
    assert bot.edits[-1] == t("fa", "dl_yt_private")


async def test_fetch_age_gate_is_blocked_before_any_cookie(
        ytdlp, redis, tmp_path, monkeypatch):
    """پیش از رفع: کوکی خرج می‌شد تا `--match-filter` ۱۸+ بودن را ببیند و رد کند."""
    await _stock(redis, monkeypatch, tmp_path, 2)
    ytdlp.anon(AGE)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    assert ytdlp.calls() == ["-|nopot"]
    await _untouched(redis)
    assert bot.edits[-1] == t("fa", "nsfw_blocked")


async def test_fetch_age_gate_with_safety_off_rotates_but_blames_nobody(
        ytdlp, redis, tmp_path, monkeypatch):
    """فیلتر خاموش: کوکی شاید کمک کند (اکانتِ احرازِ سن‌شده)، ولی شکستش نه تقصیرِ
    اکانت است نه خروجی. پیش از رفع با ≥۲ اکانت «خروجی مقصر است» می‌شد."""
    monkeypatch.setattr(TD.settings, "safety_enabled", False)
    monkeypatch.setattr(TD.settings, "admin_ids", "99")
    await _stock(redis, monkeypatch, tmp_path, 3)
    ytdlp.anon(AGE)
    ytdlp.cookie(AGE)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    modes = [c.split("|")[0] for c in ytdlp.calls()]
    assert modes[0] == "-" and modes.count("ck") >= 2, f"باید بچرخد: {modes}"
    await _untouched(redis)
    assert not await redis.exists(f"{ck._CK_EXIT_CD}master:youtube")
    assert not [m for m in bot.messages if m.startswith("🌐")], bot.messages
    assert bot.edits[-1] == t("fa", "dl_yt_age_login")


async def test_fetch_download_403_does_not_strike_the_account(
        ytdlp, redis, tmp_path, monkeypatch):
    """۴۰۳ِ googlevideo توکن/کلاینت/IP است؛ پیش از رفع `login_required` = ضربه."""
    names = await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.anon(BOT)
    ytdlp.cookie(GVS_403)

    await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    meta = await ck.get_meta(redis, names[0])
    assert meta["fail_streak"] == 0
    assert str(meta.get("last_error", "")).startswith(ck.TRANSIENT), meta


async def test_fetch_fragment_403_escalates_and_shows_its_cause(
        ytdlp, redis, tmp_path, monkeypatch):
    """همان ۴۰۳، از مسیرِ تکه‌ای (HLS/DASH). پیش از رفعِ `_stderr_summary` پیام
    «ERROR:» می‌شد → `unrelated` → پاسِ بی‌کوکی به کوکی ارتقا **نمی‌یافت**، و
    کاربر `<code>download failed: ERROR:</code>` می‌دید."""
    names = await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.anon(FRAG_403)
    ytdlp.cookie(FRAG_403)

    bot = await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    assert [c.split("|")[0] for c in ytdlp.calls()] == ["-", "ck"]
    assert (await ck.get_meta(redis, names[0]))["fail_streak"] == 0
    assert "HTTP Error 403" in bot.edits[-1], bot.edits[-1]


async def test_fetch_page_reload_with_a_cookie_tries_once_without_one(
        ytdlp, redis, tmp_path, monkeypatch):
    """حالتِ کوکی‌اول (`dl_cookie_when_needed` خاموش): reload → یک‌بار بی‌کوکی."""
    monkeypatch.setattr(TD.settings, "dl_cookie_when_needed", False)
    await _stock(redis, monkeypatch, tmp_path, 2)
    ytdlp.cookie(RELOAD)
    ytdlp.anon(BOT)

    await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    assert [c.split("|")[0] for c in ytdlp.calls()][:2] == ["ck", "-"]


# ── ۴) تکرارِ «بدونِ pot» فقط برای کرشِ پلاگین ─────────────────────────────────
async def test_a_clean_youtube_error_is_not_repeated_without_pot(
        ytdlp, redis, tmp_path, monkeypatch):
    """پیش از رفع: هر شکستی یک اجرای دوم (بی‌pot) روی همان IP می‌زد."""
    monkeypatch.setattr(TD.settings, "pot_provider_url", "http://pot.invalid:4416")
    ytdlp.anon(BOT)

    await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    assert ytdlp.calls() == ["-|pot"]


async def test_a_plugin_crash_is_still_retried_without_pot(
        ytdlp, redis, tmp_path, monkeypatch):
    """کنترلِ معکوس: همان حالتی که آن تکرار برایش ساخته شده بود هنوز کار می‌کند."""
    monkeypatch.setattr(TD.settings, "pot_provider_url", "http://pot.invalid:4416")
    ytdlp.with_pot(TRACEBACK)
    ytdlp.anon(BOT)

    await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    assert ytdlp.calls() == ["-|pot", "-|nopot"]


async def _matched_pot_calls(monkeypatch, tmp_path, err_with_pot: str) -> list[str]:
    """یک ترکِ تطبیقی (اسپاتیفای/اپل) که با pot خطای `err_with_pot` می‌گیرد و بی‌pot
    موفق است؛ هر فراخوانیِ `download_ytdlp` با وضعیتِ pot ثبت می‌شود.

    فقط resolve و جست‌وجو (شبکه) و خودِ `download_ytdlp` (زیرفرایند) جایگزین
    می‌شوند — همان مرزِ `test_phase3e._spotify`. حلقهٔ `download_matched` واقعی است.
    """
    track = {"title": "t", "artist": "a", "duration": 100}
    calls: list[str] = []

    async def _resolve(*a, **kw):
        return {"kind": "playlist", "title": "pl", "tracks": [track]}

    async def _cands(track, opts, source):
        return [{"url": "https://y/x", "title": track["title"], "duration": 100}]

    async def _dl(target, tdir, sel, opts, progress=None, cancel=None):
        calls.append("pot" if opts.get("pot_provider") else "nopot")
        if opts.get("pot_provider"):
            raise RuntimeError(err_with_pot)
        path = tmp_path / "o.m4a"
        path.write_bytes(b"audio")
        return str(path), {"duration": 100}, None

    monkeypatch.setattr(D, "spotify_resolve", _resolve)
    monkeypatch.setattr(D, "_gather_candidates", _cands)
    monkeypatch.setattr(D, "_rank_candidates", lambda cands, track: [(99.0, cands[0])])
    monkeypatch.setattr(D, "download_ytdlp", _dl)
    try:
        await D.download_matched("https://open.spotify.com/playlist/x", str(tmp_path),
                                 {"pot_provider": "http://pot.invalid:4416"})
    except RuntimeError:
        pass
    return calls


async def test_a_matched_track_is_not_repeated_without_pot_on_a_clean_error(
        monkeypatch, tmp_path):
    """مسیرِ تطبیق همان تکرارِ کور را داشت، و آن‌جا به‌ازای **هر ترک**: پلی‌لیستِ
    ۲۰ترکه‌ای که bot-check بخورد ۲۰ اجرای اضافه روی همان IP می‌زد."""
    msg = "download failed: " + D._stderr_summary(BOT.encode())
    assert await _matched_pot_calls(monkeypatch, tmp_path, msg) == ["pot"]


async def test_a_matched_track_is_still_retried_without_pot_on_a_plugin_crash(
        monkeypatch, tmp_path):
    """کنترلِ معکوس: کرشِ واقعیِ پلاگین هنوز یک‌بار بی‌pot تکرار می‌شود."""
    msg = "download failed: " + D._stderr_summary(TRACEBACK.encode())
    assert await _matched_pot_calls(monkeypatch, tmp_path, msg) == ["pot", "nopot"]


# ── ۵) تله‌متری ───────────────────────────────────────────────────────────────
async def test_each_attempt_lands_in_its_own_counter(
        ytdlp, redis, tmp_path, monkeypatch):
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.cookie("")                               # probe با کوکی موفق
    await _run(redis, _payload(tmp_path, monkeypatch, "probe"))
    ytdlp.anon(BOT)
    ytdlp.cookie(GVS_403)
    await _run(redis, _payload(tmp_path, monkeypatch, "fetch"))

    day = TD._today()
    got = {k: int(await redis.get(k)) for k in await redis.keys("dlstat:ytauth:*")}
    assert got == {
        f"dlstat:ytauth:probe:cookie:ok:{day}": 1,
        f"dlstat:ytauth:fetch:anon:bot_check:{day}": 1,
        f"dlstat:ytauth:fetch:cookie:gvs_403:{day}": 1,
    }, got
    ttl = await redis.ttl(f"dlstat:ytauth:probe:cookie:ok:{day}")
    assert ttl > 2 * 86400, "پنجرهٔ دوروزهٔ `_metric` مقایسهٔ قبل/بعد را ناممکن می‌کرد"


async def test_other_platforms_write_no_youtube_counter(
        ytdlp, redis, tmp_path, monkeypatch):
    payload = _payload(tmp_path, monkeypatch, "fetch")
    payload.update(platform="twitter", url="https://x.com/a/status/1")
    ytdlp.anon(BOT)

    await _run(redis, payload)

    assert await redis.keys("dlstat:ytauth:*") == []


def test_the_stub_json_is_enough_for_a_quality_menu():
    """پیش‌شرطِ تستِ reload: JSONِ جعلی واقعاً یک گزینهٔ منو می‌سازد."""
    data = json.loads(json.dumps({"id": "abc", "title": "Clip", "duration": 10,
                                  "formats": [{"format_id": "18", "height": 360,
                                               "vcodec": "avc1", "acodec": "mp4a",
                                               "tbr": 500}]}))
    assert D.normalize_probe(data)["options"]
