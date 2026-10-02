"""فاز ۲ / موردِ ۱۷ — تیکرِ پیشرفتِ دانلود نباید جابِ مرده را زنده نشان دهد.

`run_download` تیکری می‌سازد که هر ۳ ثانیه پیامِ وضعیت را ویرایش می‌کند، و آن را
فقط در **شاخه‌های شناخته‌شده** (`_stop_ticker()`) می‌بست. هر چیزی که از آن
شاخه‌ها فرار کند — مهم‌ترینش `CancelledError`ِ `job_timeout`ِ ARQ یا خاموشیِ
ورکر، که از کنارِ `except Exception` رد می‌شود — تیکر را در حلقهٔ رویدادِ ورکر
**تا ابد** زنده می‌گذاشت: کاربر روی جابی که مرده بود «در حال دانلود…» با زمانِ
بالارونده می‌دید، و ورکر هر ۳ ثانیه یک درخواستِ تلگرام برای هیچ می‌زد.

تست قطعی است نه زمان‌محور: دنبالِ **تسکِ** `_ticker` می‌گردد، نه دنبالِ نبودِ
ویرایش در چند ثانیه (که با دورهٔ ۳ ثانیه‌ای تیکر تصادفاً صادق می‌شد). موتور یک
`yt-dlp`ِ اجراییِ واقعی است که **هرگز تمام نمی‌شود** — پس تنها راهِ پایانِ جاب
همان لغوی است که تست می‌فرستد.
"""
from __future__ import annotations

import asyncio
import os
import stat
import textwrap

import pytest

from app import tasks_download as TD
from tests.aiogram_double import ValidatingBot

_HANG = r'''#!/usr/bin/env python3
import sys, time
if "--version" in sys.argv:
    print("2026.07.04"); sys.exit(0)
while True:
    time.sleep(1)
'''


class FakeBot(ValidatingBot):
    def __init__(self) -> None:
        self.edits: list[str] = []

    def _on(self, name, payload):
        if name in ("edit_message_text", "edit_message_caption"):
            self.edits.append(payload.get("text") or payload.get("caption"))
        return True


@pytest.fixture
def hang_ytdlp(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "yt-dlp"
    script.write_text(textwrap.dedent(_HANG))
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")


@pytest.fixture
def payload(tmp_path, monkeypatch):
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "work"))
    return {"ref": "tick123", "chat_id": 7, "status_mid": 9, "lang": "fa",
            "url": "https://www.youtube.com/watch?v=hangs", "platform": "youtube",
            "engine": "ytdlp", "phase": "fetch", "selector": "best",
            "owner_id": 1, "tg_user_id": 42}


def _tickers() -> list[asyncio.Task]:
    return [t for t in asyncio.all_tasks()
            if getattr(t.get_coro(), "__qualname__", "").endswith("._ticker")]


async def _wait_for_ticker(job: asyncio.Task) -> None:
    for _ in range(200):                       # کران‌دار — هرگز await لخت (§۶)
        if _tickers():
            return
        assert not job.done(), f"جاب پیش از ساختنِ تیکر تمام شد: {job.exception()!r}"
        await asyncio.sleep(0.05)
    pytest.fail("تیکر هرگز ساخته نشد — هارنس به آن نقطه نرسید")


async def test_a_cancelled_download_leaves_no_live_ticker(hang_ytdlp, payload, redis):
    job = asyncio.create_task(TD.run_download({"bot": FakeBot(), "redis": redis}, payload))
    await _wait_for_ticker(job)

    job.cancel()                               # همان چیزی که job_timeout می‌فرستد
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(job, 10)

    for _ in range(40):
        if not [t for t in _tickers() if not t.done()]:
            break
        await asyncio.sleep(0.05)
    alive = [t for t in _tickers() if not t.done()]
    for t in alive:                            # نگذار به تست‌های بعدی نشت کند
        t.cancel()
    assert not alive, "تیکر بعد از لغوِ جاب زنده ماند"


async def test_the_cancelled_job_still_frees_its_slot(hang_ytdlp, payload, redis):
    """کنترل: بستنِ تیکر در `finally` نباید بقیهٔ پاک‌سازی را قطع کند.

    `P.stop_task` روی لغوِ خودِ جاب دوباره raise می‌کند — اگر آن‌جا صدا زده شود،
    `dl_active.leave` و حذفِ workdir بعدش هرگز اجرا نمی‌شوند.
    """
    from app import dl_active
    job = asyncio.create_task(TD.run_download({"bot": FakeBot(), "redis": redis}, payload))
    await _wait_for_ticker(job)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(job, 10)
    assert await dl_active.count(redis) == 0
    assert not os.path.exists(os.path.join(TD.settings.work_dir, f"dl-{payload['ref']}"))
