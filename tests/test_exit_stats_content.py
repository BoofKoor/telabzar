"""فاز ۴ / موردِ ۳۴ب — ۴۰۴ در آمارِ «IPِ این خروجی مسدود است» شمرده نشود.

فاز ۲ تقصیرِ خروجی را از خطای محتوایی جدا کرد (`_resolve_blame`)، ولی شمارندهٔ
`note_exit` — که کارتِ «🌐 خروجی‌ها» از آن «مسدود است» می‌سازد (`exit_stats`:
صفر موفقیت و ≥۳ شکست) — هنوز هر ۴۰۴ را شکستِ خروجی می‌شمرد. پس سه لینکِ
حذف‌شده روی خروجیِ سالم کافی بود تا پنل به ادمین بگوید IP مسدود است.

`run_download`ِ واقعی با `yt-dlp`ِ اجراییِ جعلی روی PATH.
"""
from __future__ import annotations

import os
import stat

import pytest

from app import cookies as ck
from app import tasks_download as TD
from tests.test_exit_blame_content import (  # noqa: F401 — fixtures
    LOGIN, NOTFOUND, FakeBot, accounts)


def _ytdlp(tmp_path, monkeypatch, err: str):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / "yt-dlp"
    script.write_text("#!/usr/bin/env python3\nimport sys\n"
                      "if '--version' in sys.argv:\n    print('2026.07.04'); sys.exit(0)\n"
                      f"sys.stderr.write({err!r} + '\\n')\nsys.exit(1)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "work"))


async def _three_downloads(redis, phase: str = "fetch"):
    for i in range(3):
        await TD.run_download({"bot": FakeBot(), "redis": redis}, {
            "ref": f"exst{i:04d}", "chat_id": 7, "status_mid": 9, "lang": "fa",
            "url": f"https://www.instagram.com/p/abc{i}/", "platform": "instagram",
            "engine": "ytdlp", "phase": phase, "selector": "best",
            "owner_id": 1, "tg_user_id": 42})
    rows = [r for r in await ck.exit_stats(redis, "instagram")]
    return rows[0] if rows else {"fail": 0, "blocked": False}


@pytest.mark.parametrize("phase", ["fetch", "probe"], ids=["fetch", "probe"])
async def test_deleted_posts_do_not_mark_the_exit_blocked(redis, accounts, tmp_path,
                                                         monkeypatch, phase):
    await accounts()
    _ytdlp(tmp_path, monkeypatch, NOTFOUND)
    row = await _three_downloads(redis, phase)
    assert row["fail"] == 0 and not row["blocked"], \
        f"سه ۴۰۴ خروجیِ سالم را «مسدود» نشان داد: {row}"


async def test_genuine_failures_still_count_against_the_exit(redis, accounts, tmp_path,
                                                            monkeypatch):
    """کنترل: شکستِ ورود همچنان شاهد است — وگرنه کارت هرگز «مسدود» نمی‌گفت."""
    await accounts()
    _ytdlp(tmp_path, monkeypatch, LOGIN)
    row = await _three_downloads(redis)
    assert row["fail"] == 3 and row["blocked"]
