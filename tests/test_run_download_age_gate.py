"""مسیرِ **رد** شدنِ گیتِ سنی، تا آخرِ خط: از خروجیِ yt-dlp تا پیامِ کاربر.

`download_ytdlp` باید `AgeRestricted` بدهد و `run_download` باید آن را به
«محتوای غیرمجاز» نگاشت کند — نه به `dl_failed` و نه به «download produced no
file». حالتِ رایجِ yt-dlp در این وضع، خروج با کدِ **صفر** و بدونِ فایل است، پس
تشخیص نمی‌تواند به کدِ خروجی تکیه کند.

اینجا `run_download`ِ واقعی با یک `yt-dlp`ِ اجراییِ جعلی روی PATH و fakeredis
اجرا می‌شود؛ فقط `Bot` جایگزین شده چون تلگرام واقعی در تست موجود نیست.
"""
from __future__ import annotations

import os
import stat
import textwrap

import pytest

from app import tasks_download as TD
from app.i18n import t

_FAKE_YTDLP_REJECT = r'''#!/usr/bin/env python3
"""yt-dlpی که --match-filter ردش می‌کند: کدِ خروجی ۰، بدونِ هیچ فایلی."""
import sys
argv = sys.argv[1:]
mf = argv[argv.index("--match-filter") + 1] if "--match-filter" in argv else None
if mf:
    print("[download] Some Clip does not pass filter (%s), skipping .." % mf)
    sys.exit(0)
print("dl:100.0%")
sys.exit(1)
'''


class FakeBot:
    """فقط چیزی که `run_download` از Bot صدا می‌زند."""

    def __init__(self) -> None:
        self.edits: list[str] = []
        self.messages: list[str] = []

    async def edit_message_text(self, text, chat_id=None, message_id=None, reply_markup=None):
        self.edits.append(text)

    async def edit_message_caption(self, chat_id=None, message_id=None, caption=None,
                                   reply_markup=None):
        self.edits.append(caption)

    async def send_message(self, chat_id, text, **kw):
        self.messages.append(text)


@pytest.fixture
def reject_ytdlp(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "yt-dlp"
    script.write_text(textwrap.dedent(_FAKE_YTDLP_REJECT))
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")


@pytest.fixture
def payload(tmp_path, monkeypatch):
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path))
    return {"ref": "tst1234", "chat_id": 7, "status_mid": 9, "lang": "fa",
            "url": "https://www.youtube.com/watch?v=blocked", "platform": "youtube",
            "engine": "ytdlp", "phase": "fetch", "selector": "best",
            "owner_id": 1, "tg_user_id": 42}


async def test_age_filter_rejection_becomes_an_nsfw_stop(reject_ytdlp, payload, redis):
    bot = FakeBot()
    await TD.run_download({"bot": bot, "redis": redis}, payload)

    assert bot.edits, "کاربر باید یک پیامِ نهایی ببیند"
    final = bot.edits[-1]
    assert final == t("fa", "nsfw_blocked")
    assert t("fa", "dl_failed") not in final
    assert "produced no file" not in final
    assert "does not pass filter" not in final, "جزئیاتِ موتور نباید به کاربر برسد"


async def test_rejection_does_not_leave_the_slot_occupied(reject_ytdlp, payload, redis):
    """`finally` باید ظرفیت را آزاد کند حتی وقتی گیت وسطِ کار جاب را تمام می‌کند."""
    from app import dl_active
    await TD.run_download({"bot": FakeBot(), "redis": redis}, payload)
    assert await dl_active.count(redis) == 0


async def test_rejection_costs_no_cookie_strike(reject_ytdlp, payload, redis, tmp_path,
                                                monkeypatch):
    """اکانتِ دیگر نتیجهٔ متفاوتی نمی‌دهد، پس هیچ اکانتی نباید ضربه بخورد."""
    from app import cookies as ck
    monkeypatch.setattr(ck.settings, "cookies_dir", str(tmp_path / "ck"))
    os.makedirs(tmp_path / "ck", exist_ok=True)
    netscape = ("# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tLOGIN_INFO\tvalue\n")
    for name in ("youtube-a.txt", "youtube-b.txt"):
        assert await ck._save_cookie(redis, name, netscape) == ""
    before = await ck.accounts(redis, "youtube")
    assert before, "تست باید واقعاً اکانت داشته باشد وگرنه بی‌معنی است"

    await TD.run_download({"bot": FakeBot(), "redis": redis}, payload)

    for acct in await ck.accounts(redis, "youtube"):
        assert acct["fail_streak"] == 0, f"{acct['name']} نباید ضربه خورده باشد"
        assert acct["status"] == "healthy", f"{acct['name']} باید سالم بماند"
