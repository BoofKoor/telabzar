"""فاز ۲ / موردِ ۱۰ — خطای «محتوایی» خروجی را مقصر نمی‌کند.

`_resolve_blame` قاعده‌ای ساده داشت: درخواست شکست خورد و ≥۲ اکانتِ متفاوت
امتحان شد ⇒ مقصر IPِ خروجی است ⇒ هیچ اکانتی ضربه نمی‌خورد، خروجی کول‌داون
می‌گیرد و ادمین DMِ «کوکی‌ها را عوض نکن» می‌گیرد.

ولی آخرین شکست می‌تواند **محتوایی** باشد (۴۰۴/خصوصی/حذف‌شده): اکانتِ اول با
خطای ورود افتاد، اکانتِ دوم به خودِ پست رسید و «۴۰۴» گرفت. آن ۴۰۴ ثابت می‌کند
خروجی **کار می‌کند** — درخواست به پلتفرم رسید و جوابِ قطعی گرفت — ولی شمارشِ
«۲ اکانت افتادند» همان حکم را می‌داد: خروجیِ سالم برای `dl_exit_cooldown_min`
کنار گذاشته می‌شد (همهٔ دانلودهای آن پلتفرم از آن خروجی متوقف) و ادمین هشدارِ
غلط می‌گرفت. یوتیوب این را از قبل جدا کرده بود (`YT_CONTENT_KINDS` پیش از ثبتِ
شکست `break` می‌کند)؛ مسیرِ عمومی نه.

دو سطح، چون هرکدام ادعای جداست (§۶): تصمیمِ خودِ `_resolve_blame`، و اینکه
`run_download` واقعاً همین شکست‌ها را به آن می‌دهد.
"""
from __future__ import annotations

import os
import stat
import textwrap

import pytest

from app import cookies as ck
from app import tasks_download as TD
from tests.aiogram_double import ValidatingBot

NETSCAPE = ("# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\tvalue\n")
LOGIN = "ERROR: [Instagram] abc: Requested content is not available, redirect to login page"
NOTFOUND = "ERROR: [Instagram] abc: HTTP Error 404: Not Found"


class FakeBot(ValidatingBot):
    def __init__(self) -> None:
        self.edits: list[str] = []
        self.messages: list[str] = []

    def _on(self, name, payload):
        if name == "edit_message_text":
            self.edits.append(payload["text"])
        elif name == "send_message":
            self.messages.append(payload["text"])
        return True


@pytest.fixture
def accounts(redis, tmp_path, monkeypatch):
    d = tmp_path / "ck"
    d.mkdir()
    monkeypatch.setattr(ck.settings, "cookies_dir", str(d))
    monkeypatch.setattr(ck.settings, "node_id", "")
    monkeypatch.setattr(TD.settings, "admin_ids", "900")

    async def _make() -> list[str]:
        names = ["cookies_instagram-a.txt", "cookies_instagram-b.txt"]
        for n in names:
            assert await ck._save_cookie(redis, n, NETSCAPE) == ""
        return names
    return _make


def _exit_dm(bot: FakeBot) -> list[str]:
    return [m for m in bot.messages if "خروجی کنار گذاشته شد" in m]


# ── سطحِ ۱: خودِ تصمیم ────────────────────────────────────────────────
async def test_a_content_error_keeps_the_exit_in_service(redis, accounts):
    a, b = await accounts()
    bot = FakeBot()
    failures = [(a, LOGIN, ck.classify_error(LOGIN)),
                (b, NOTFOUND, ck.classify_error(NOTFOUND))]
    blamed = await TD._resolve_blame(redis, bot, "instagram", "", failures, won=False)
    assert blamed is False
    assert not await ck.exit_cooled(redis, "", "instagram")
    assert not _exit_dm(bot), "ادمین نباید هشدارِ «IP مقصر است» بگیرد"


async def test_with_the_exit_cleared_the_login_failure_is_on_the_account(redis, accounts):
    """خروجی سالم ثابت شد، پس شکستِ ورودِ اکانتِ اول تقصیرِ خودِ اوست."""
    a, b = await accounts()
    failures = [(a, LOGIN, ck.classify_error(LOGIN)),
                (b, NOTFOUND, ck.classify_error(NOTFOUND))]
    await TD._resolve_blame(redis, FakeBot(), "instagram", "", failures, won=False)
    meta = {x["name"]: x for x in await ck.accounts(redis, "instagram")}
    assert meta[a]["fail_streak"] >= 1
    assert meta[b]["fail_streak"] == 0, "۴۰۴ تقصیرِ اکانت نیست"


async def test_two_genuine_account_failures_still_blame_the_exit(redis, accounts):
    """کنترل: قاعدهٔ اصلی سرِ جایش است — ۲ شکستِ ورود روی یک خروجی ⇒ IP مقصر است."""
    a, b = await accounts()
    bot = FakeBot()
    failures = [(a, LOGIN, ck.classify_error(LOGIN)), (b, LOGIN, ck.classify_error(LOGIN))]
    assert await TD._resolve_blame(redis, bot, "instagram", "", failures, won=False)
    assert await ck.exit_cooled(redis, "", "instagram")
    assert _exit_dm(bot)


# ── سطحِ ۲: run_downloadِ واقعی، yt-dlpِ اجراییِ واقعی ─────────────────
_FAKE = r'''#!/usr/bin/env python3
import os, sys
if "--version" in sys.argv:
    print("2026.07.04"); sys.exit(0)
state = os.environ["FAKE_STATE"]
n = int(open(state).read()) if os.path.exists(state) else 0
open(state, "w").write(str(n + 1))
sys.stderr.write((%r if n == 0 else %r) + "\n")
sys.exit(1)
''' % (LOGIN, NOTFOUND)


@pytest.fixture
def ytdlp(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "yt-dlp"
    script.write_text(textwrap.dedent(_FAKE))
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_STATE", str(tmp_path / "calls"))
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "work"))
    return tmp_path / "calls"


async def test_run_download_does_not_bench_a_working_exit_on_a_404(redis, accounts, ytdlp):
    await accounts()
    bot = FakeBot()
    await TD.run_download({"bot": bot, "redis": redis}, {
        "ref": "exit0001", "chat_id": 7, "status_mid": 9, "lang": "fa",
        "url": "https://www.instagram.com/p/abc/", "platform": "instagram",
        "engine": "ytdlp", "phase": "fetch", "selector": "best",
        "owner_id": 1, "tg_user_id": 42})
    assert int(ytdlp.read_text()) == 2, "پیش‌شرط: هر دو اکانت واقعاً امتحان شدند"
    assert not await ck.exit_cooled(redis, "", "instagram"), \
        "۴۰۴ ثابت می‌کند خروجی کار می‌کند — نباید کنار گذاشته شود"
    assert not _exit_dm(bot)
