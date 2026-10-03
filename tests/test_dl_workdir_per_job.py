"""فاز ۳ / موردِ ۱۳ — دو pick از یک منو، دو پوشهٔ کار.

پوشهٔ کارِ `run_download` به‌ازای `ref` بود (`dl-<ref>`)، ولی `on_dl_pick` برای هر
انتخابِ کیفیت از **همان** منو یک جابِ تازه با همان `ref` صف می‌کند. پس دو pick
یک پوشه داشتند و `finally`ِ جابی که زودتر تمام شد (`shutil.rmtree(workdir)`)
فایلِ جابِ دیگر را وسطِ کار پاک می‌کرد.

درهم‌آمیزی **مجبور** می‌شود (§۶): جابِ ۷۲۰ بعد از نوشتنِ فایلش روی یک `Event`
می‌ایستد تا جابِ ۳۶۰ کاملاً تمام شود — `finally`ش هم — و بعد سراغِ فایلِ خودش
می‌رود. روی سورسِ پیش از رفع این ترتیب حتماً فایل را پاک‌شده می‌بیند.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from app import tasks_download as TD
from tests.aiogram_double import ValidatingBot


class Bot(ValidatingBot):
    def _on(self, name, payload):
        class M:
            message_id = 77
        return M()


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "work"))
    monkeypatch.setattr(TD.settings, "safety_enabled", False)
    monkeypatch.setattr(TD.settings, "dl_cookie_when_needed", True)
    seen: dict[str, str] = {}
    survived: dict[str, bool] = {}
    gate = asyncio.Event()

    async def download_ytdlp(url, workdir, selector, opts, progress=None, cancel=None):
        os.makedirs(workdir, exist_ok=True)
        p = os.path.join(workdir, f"clip-{selector}.mp4")
        with open(p, "wb") as fh:
            fh.write(b"x" * 64)
        seen[selector] = workdir
        if selector == "720":
            await asyncio.wait_for(gate.wait(), 10)        # تا جابِ ۳۶۰ تمام شود
        survived[selector] = os.path.exists(p)
        return p, {"title": "clip", "id": "abc"}, None

    async def media_meta(path, kind, info, thumb):
        return path, info, thumb

    async def deliver(*a, **kw):
        return None

    monkeypatch.setattr(TD.D, "download_ytdlp", download_ytdlp)
    monkeypatch.setattr(TD, "_media_meta", media_meta)
    monkeypatch.setattr(TD, "_deliver_single", deliver)
    return seen, survived, gate


def _payload(sel: str) -> dict:
    return {"ref": "pick0001", "chat_id": 7, "status_mid": 9, "lang": "fa",
            "url": "https://www.youtube.com/watch?v=abc", "platform": "youtube",
            "engine": "ytdlp", "phase": "fetch", "selector": sel,
            "owner_id": 1, "tg_user_id": 42}


async def test_two_picks_from_one_menu_do_not_share_a_workdir(harness, redis):
    seen, survived, gate = harness
    slow = asyncio.create_task(TD.run_download({"bot": Bot(), "redis": redis}, _payload("720")))
    for _ in range(200):                                    # کران‌دار: تا ۷۲۰ فایلش را بنویسد
        if "720" in seen:
            break
        await asyncio.sleep(0.01)
    assert "720" in seen, "پیش‌شرط: جابِ کُند باید به نقطهٔ توقف رسیده باشد"
    await TD.run_download({"bot": Bot(), "redis": redis}, _payload("360"))
    gate.set()
    await asyncio.wait_for(slow, 10)
    # اول رفتار، بعد نام: ادعای اصلی «فایل زنده ماند» است، نه «دو رشتهٔ متفاوت».
    assert survived == {"720": True, "360": True}, \
        f"فایلِ یک جاب را `finally`ِ جابِ دیگر پاک کرد: {survived}"
    assert seen["720"] != seen["360"], "دو جاب یک پوشهٔ کار گرفتند"


async def test_the_workdir_is_still_named_after_the_link_and_removed(harness, redis):
    """کنترل: پیشوندِ `dl-<ref>` (برای ردگیری روی دیسک) می‌ماند و پاک‌سازی هنوز هست."""
    seen, _survived, gate = harness
    gate.set()
    await TD.run_download({"bot": Bot(), "redis": redis}, _payload("360"))
    assert os.path.basename(seen["360"]).startswith("dl-pick0001")
    assert not os.path.exists(seen["360"])
