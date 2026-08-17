"""سه پیامی که دربارهٔ «سشن» حرف می‌زنند، برای سطلی که سشن ندارد و نمی‌تواند داشته باشد.

`_cookie_platform` می‌تواند ۱۴ سطل بخواهد ولی `admin_web.COOKIE_PLATFORMS` شش تا
می‌سازد، پس ساندکلاود (و هفت پلتفرمِ دیگر) سطلی می‌خواهند که **هیچ راهی برای
پرکردنش نیست**. با این حال:

  ۱) وسطِ حلقه «اکانتِ دیگری را امتحان می‌کنم» نشان داده می‌شد — وعده‌ای که
     اکانتی برای عمل‌کردن به آن وجود ندارد؛
  ۲) در پایان «ادمین باید کوکی تنظیم کند» — دستورِ اجراناپذیر؛
  ۳) یا «سشن دیگر معتبر نیست» — دربارهٔ سشنی که وجود ندارد.

مرزِ رفع دقیقاً همان تفکیکِ سه‌حالتهٔ `_alert_if_low` است و **کنترل‌ها از خودِ
رفع مهم‌ترند**: «۰ از N» (استخرِ سوخته) و «۰ از ۰ ولی زمانی پر بوده» هر دو
واقعاً دربارهٔ سشن‌اند و باید پیامِ قبلی را نگه دارند. گاردی که روی «قابلِ‌استفاده»
نوشته شود هر سه را خفه می‌کند — همان اشتباهی که یک‌بار در `_alert_if_low` بود.
"""
from __future__ import annotations

import os
import stat
import textwrap

import pytest

from tests.aiogram_double import ValidatingBot

from app import cookies as ck
from app import tasks_download as TD

# yt-dlpِ جعلی که با خطای **ورود** می‌افتد — همان شکلی که یک سایت به درخواستِ
# بی‌سشن جواب می‌دهد. عمداً اجراییِ واقعی، نه ماکِ `D.download_ytdlp`: پیامی که
# `_LOGIN_HINTS` می‌بیند خروجیِ `_stderr_summary` است نه رشتهٔ خامِ دلخواهِ تست.
_FAKE_YTDLP = '''#!/usr/bin/env python3
import os, sys
sys.stderr.write("ERROR: [%s] Please sign in to your account to continue\\n"
                 % os.environ.get("FAKE_IE", "generic"))
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


@pytest.fixture
def payload(tmp_path, monkeypatch):
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "work"))
    os.makedirs(tmp_path / "work", exist_ok=True)

    def _make(platform: str, url: str) -> dict:
        return {"ref": "sc000001", "chat_id": 7, "status_mid": 9, "lang": "fa",
                "url": url, "platform": platform, "engine": "ytdlp",
                "phase": "fetch", "selector": "audio", "owner_id": 1, "tg_user_id": 42}
    return _make


SC = ("soundcloud", "https://soundcloud.com/mossihashemi/siavash-ghomeishi-ey-gharibe")
YT = ("youtube", "https://www.youtube.com/watch?v=abc")


async def _run(redis, pl, bot=None):
    bot = bot or FakeBot()
    await TD.run_download({"bot": bot, "redis": redis}, pl)
    return bot


# ── ۱) گاردِ «اکانتِ دیگری را امتحان می‌کنم» ────────────────────────
async def test_an_empty_pool_never_promises_another_account(redis, ytdlp, payload):
    """ادعای اصلیِ کارِ ۳-الف: وعده‌ای که اکانتی پشتش نیست داده نشود."""
    bot = await _run(redis, payload(*SC))
    retry = [e for e in bot.edits if "اکانتِ دیگری" in (e or "")]
    assert not retry, f"استخرِ ساندکلاود صفر اکانت دارد ولی وعدهٔ چرخش داده شد: {retry}"


async def test_a_stocked_pool_still_promises_the_next_account(
        redis, ytdlp, payload, tmp_path, monkeypatch):
    """کنترل: جایی که اکانت **هست**، پیامِ چرخش باید سرِ جایش بماند.

    گاردی که این را هم خفه کند، بازخوردِ درستِ کاربر را از بین برده است.
    """
    ckdir = tmp_path / "ck"
    os.makedirs(ckdir, exist_ok=True)
    monkeypatch.setattr(ck.settings, "cookies_dir", str(ckdir))
    for c in "ab":
        assert await ck._save_cookie(redis, f"cookies_youtube-{c}.txt", NETSCAPE) == ""
    assert len(await ck.accounts(redis, "youtube")) == 2, \
        "پیش‌شرط: تست باید واقعاً اکانت داشته باشد وگرنه ادعا توخالی است"

    bot = await _run(redis, payload(*YT))
    assert any("اکانتِ دیگری" in (e or "") for e in bot.edits), \
        "با استخرِ پر، کاربر باید بداند دارد اکانتِ بعدی امتحان می‌شود"


# ── ۲و۳) پیامِ پایانی ───────────────────────────────────────────────
async def test_an_unstockable_bucket_does_not_order_the_admin_to_add_cookies(
        redis, ytdlp, payload):
    bot = await _run(redis, payload(*SC))
    last = bot.edits[-1]
    assert "ادمین" not in last, f"دستورِ اجراناپذیر به ادمین داده شد: {last}"
    assert "حسابی ندارد" in last, f"پیامِ بن‌بستِ تازه نیامد: {last}"


async def test_a_stocked_bucket_still_tells_the_admin_to_fix_cookies(
        redis, ytdlp, payload, tmp_path, monkeypatch):
    """کنترل: سطلی که اکانت دارد ولی همه افتاده‌اند **واقعاً** مسئلهٔ سشن است."""
    ckdir = tmp_path / "ck"
    os.makedirs(ckdir, exist_ok=True)
    monkeypatch.setattr(ck.settings, "cookies_dir", str(ckdir))
    assert await ck._save_cookie(redis, "cookies_youtube-a.txt", NETSCAPE) == ""

    bot = await _run(redis, payload(*YT))
    assert any("ادمین" in (e or "") for e in bot.edits), \
        "استخرِ سوخته همچنان باید ادمین را خبر کند — این همان چیزی است که پیام برایش هست"


# ── گاردِ سه‌حالته، مستقیم ──────────────────────────────────────────
async def test_a_bucket_that_was_once_stocked_is_not_called_unsupported(redis):
    """مرزِ ظریف: «۰ از ۰ ولی زمانی پر بوده» = قابلیتی از کار افتاده، نه ناپشتیبانی.

    این همان حالتی است که ادمین سشن‌های مرده را پاک کرده و هنوز تازه‌ها را
    نچسبانده — دقیقاً وقتی که باید خبر بدهیم، نه اینکه بگوییم «پشتیبانی نمی‌شود».
    """
    assert await TD._no_account_possible(redis, "instagram") is True
    await ck.set_meta(redis, "cookies_instagram-a.txt",
                      {"platform": "instagram", "fail_streak": 0})
    await ck.del_meta(redis, "cookies_instagram-a.txt")
    assert await ck.was_stocked(redis, "instagram") is True, "پیش‌شرطِ تست"
    assert await TD._no_account_possible(redis, "instagram") is False


async def test_a_burned_pool_is_not_called_unsupported(redis, tmp_path, monkeypatch):
    """«۰ از N» = استخرِ سوخته، که پیامِ سشن‌محور برایش **درست** است.

    استخر باید **واقعاً** سوخته باشد نه فقط پر: نسخهٔ اول یک اکانتِ سالم
    می‌ساخت، پس `usable` هم ۱ بود و گاردِ غلط (`not usable`) از تست رد می‌شد —
    یعنی این کنترل دقیقاً همان چیزی را که برایش هست نمی‌سنجید. سابوتاژ گرفتش.
    """
    ckdir = tmp_path / "ck"
    os.makedirs(ckdir, exist_ok=True)
    monkeypatch.setattr(ck.settings, "cookies_dir", str(ckdir))
    name = "cookies_youtube-a.txt"
    assert await ck._save_cookie(redis, name, NETSCAPE) == ""
    meta = await ck.get_meta(redis, name)
    await ck.set_meta(redis, name, {**meta, "frozen": True})   # چک‌پوینت‌خورده

    total, usable = await ck.pool_counts(redis, "youtube")
    assert (total, usable) == (1, 0), \
        f"پیش‌شرط: استخر باید پر ولی غیرقابلِ‌استفاده باشد، شد {(total, usable)}"
    assert await TD._no_account_possible(redis, "youtube") is False


async def test_a_never_stocked_bucket_is_unsupported(redis):
    assert await TD._no_account_possible(redis, "soundcloud") is True


async def test_a_redis_failure_falls_back_to_todays_message(redis):
    """fail-safe: خرابیِ Redis نباید متنِ خطا را عوض کند."""
    class Broken:
        def __getattr__(self, _n):
            raise RuntimeError("redis down")
    assert await TD._no_account_possible(Broken(), "soundcloud") is False
    assert await TD._no_account_possible(None, "soundcloud") is False
