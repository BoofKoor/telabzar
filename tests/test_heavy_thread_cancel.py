"""فاز ۳ / موردِ ۱۹ — لغوِ رونویسی/حذفِ پس‌زمینه، و قفلی که تا پایانِ thread بماند.

Whisper و rembg در thread اجرا می‌شوند و thread را نمی‌شود کشت. پیش از رفع
`async with _ASR_SEM: await asyncio.to_thread(...)` بود، پس لغوِ جاب فقط `await`
را رها می‌کرد و `async with` قفل را آزاد می‌کرد در حالی که thread هنوز می‌دوید:
جابِ بعدی مدلِ دوم را **کنارِ** اولی بالا می‌آورد. دکمهٔ لغو هم بی‌اثر بود چون
`transcribe_audio`/`remove_background` اصلاً `cancel` نمی‌گرفتند.

مدل‌ها در محیطِ تست نصب نیستند، پس کارِ thread جایگزین می‌شود — ولی با **همان
قرارداد** (`stop` را بینِ قطعه‌ها می‌پرسد). برای Whisper یک تست هم خودِ
`_transcribe_sync`ِ واقعی را با `faster_whisper`ِ جعلی در `sys.modules` می‌زند،
تا ادعای «بینِ قطعه‌ها می‌ایستد» دربارهٔ کدِ تولید باشد نه دربارهٔ جایگزین.

همه‌چیز کران‌دار است (§۶): نسخهٔ خراب دقیقاً همان است که ممکن است تمام نشود.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
import types

import pytest

from app import processing as P
from app.exceptions import ProcessingCancelled


class Probe:
    """کارِ جایگزینِ thread: چند «قطعه»، هرکدام ۵۰ms، با شمارشِ هم‌زمانی."""

    def __init__(self, segments: int = 40, honours_stop: bool = True) -> None:
        self.segments = segments
        self.honours_stop = honours_stop
        self.live = 0
        self.max_live = 0
        self.done_segments: list[int] = []
        self.finished = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, *args):
        stop = args[-1] if args and isinstance(args[-1], threading.Event) else None
        with self._lock:
            self.live += 1
            self.max_live = max(self.max_live, self.live)
        n = 0
        try:
            for _ in range(self.segments):
                if self.honours_stop and stop is not None and stop.is_set():
                    raise P._Stopped() if hasattr(P, "_Stopped") else RuntimeError("stopped")
                time.sleep(0.05)
                n += 1
            return "text"
        finally:
            self.done_segments.append(n)
            with self._lock:
                self.live -= 1
            self.finished.set()


OPS = {
    "transcribe": ("_transcribe_sync", "_ASR_SEM",
                   lambda **kw: P.transcribe_audio("in.wav", "base", "txt", **kw)),
    "bg_remove": ("_remove_bg_sync", "_BG_SEM",
                  lambda **kw: P.remove_background("in.png", "out.png", **kw)),
}


@pytest.fixture(autouse=True)
def fresh_semaphores(monkeypatch):
    """هر تست لوپِ خودش را دارد؛ سمافورِ سطحِ ماژول نباید از تستِ قبل قفل بماند."""
    monkeypatch.setattr(P, "_ASR_SEM", asyncio.Semaphore(1))
    monkeypatch.setattr(P, "_BG_SEM", asyncio.Semaphore(1))
    monkeypatch.setattr(P, "_CANCEL_POLL", 0.05)


@pytest.mark.parametrize("op", sorted(OPS), ids=sorted(OPS))
async def test_a_cancelled_job_keeps_the_slot_until_its_thread_ends(monkeypatch, op):
    """لغوِ جاب (مثلِ `job_timeout`) نباید مدلِ دوم را کنارِ اولی راه بیندازد.

    کارِ thread این‌جا عمداً `stop` را **نمی‌پرسد**: rembg یک فراخوانیِ یکپارچه است و
    Whisper هم حینِ بارگذاریِ مدل/VAD تا اولین قطعه نمی‌پرسد. نسخهٔ اولِ این تست
    `stop` را می‌پرسید و thread ظرفِ ۵۰ms می‌ایستاد، پس سابوتاژِ «قفل را روی لغو آزاد
    کن» پنجرهٔ هم‌پوشانی را به چند میلی‌ثانیه می‌رساند و **نگرفت** — دفترچهٔ سابوتاژ
    گرفتش، نه بازخوانی. ادعای درست دربارهٔ threadی است که نمی‌تواند زود بایستد.
    """
    fn_name, _sem, call = OPS[op]
    probe = Probe(segments=20, honours_stop=False)
    monkeypatch.setattr(P, fn_name, probe)
    first = asyncio.create_task(call())
    await asyncio.sleep(0.15)                              # thread واقعاً شروع کرده
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(first, 5)
    second = asyncio.create_task(call())
    try:
        await asyncio.wait_for(second, 10)
    except Exception:  # noqa: BLE001 — خروجیِ واقعی ساخته نمی‌شود؛ فقط هم‌زمانی مهم است
        pass
    assert probe.max_live == 1, f"{op}: دو مدل هم‌زمان اجرا شدند ({probe.max_live})"


@pytest.mark.parametrize("op", sorted(OPS), ids=sorted(OPS))
async def test_the_cancel_button_stops_the_wait(monkeypatch, op):
    fn_name, _sem, call = OPS[op]
    probe = Probe(segments=200)                            # ۱۰ ثانیه اگر کسی نایستاندش
    monkeypatch.setattr(P, fn_name, probe)
    flag = {"on": False}

    async def cancel() -> bool:
        return flag["on"]

    task = asyncio.create_task(call(cancel=cancel))
    await asyncio.sleep(0.15)
    flag["on"] = True
    t0 = time.monotonic()
    with pytest.raises(ProcessingCancelled):
        await asyncio.wait_for(task, 5)
    assert time.monotonic() - t0 < 2, "لغو باید در چند ده میلی‌ثانیه اثر کند"
    assert probe.finished.wait(5), "thread باید در مرزِ قطعهٔ بعدی بایستد"
    assert probe.done_segments[-1] < 200, "thread تا آخر ادامه داد"


async def test_real_transcribe_stops_between_segments(monkeypatch):
    """`_transcribe_sync`ِ تولید، با `faster_whisper`ِ جعلی: generator قطعه‌به‌قطعه."""
    produced: list[int] = []

    class Seg:
        def __init__(self, i):
            self.start, self.end, self.text = float(i), float(i) + 1, f"s{i}"

    class Model:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, inp, vad_filter=True):
            def gen():
                for i in range(1000):
                    produced.append(i)
                    yield Seg(i)
            return gen(), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(P, "_WHISPER_MODELS", {})
    stop = threading.Event()
    stop.set()
    with pytest.raises(P._Stopped):
        P._transcribe_sync("in.wav", "base", "txt", stop)
    assert len(produced) <= 1, f"بعد از stop هنوز {len(produced)} قطعه رونویسی شد"


async def test_real_transcribe_without_stop_still_returns_text(monkeypatch):
    """کنترل: بی‌لغو، همان خروجیِ قبلی (txt و srt)."""
    class Seg:
        def __init__(self, i):
            self.start, self.end, self.text = float(i), float(i) + 1, f" s{i} "

    class Model:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, inp, vad_filter=True):
            return (Seg(i) for i in range(3)), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(P, "_WHISPER_MODELS", {})
    assert P._transcribe_sync("in.wav", "base", "txt") == "s0 s1 s2"
    assert P._transcribe_sync("in.wav", "base", "srt").startswith("1\n00:00:00,000 --> 00:00:01,000\ns0")
