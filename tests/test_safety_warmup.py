"""فاز ۳پ / موردِ ۱۲ — warm-upِ مدلِ NudeNet سرِ استارتِ ورکر.

بارگذاری ~۸۱ مگابایت و چند ثانیه است و تا امروز روی **اولین** فایلِ کاربر
اتفاق می‌افتاد — بدترین لحظهٔ ممکن، درست بعد از هر `telabzar update`.

سه قیدِ طراحی این‌جا تست می‌شوند و هر سه رفتاری‌اند، نه ساختاری: گیتِ دو فلگِ
ایمنی، ردشدن روی نودِ پردازش، و اجرا **در thread** (چون `_get_detector` همگام
است و صداکردنش روی حلقهٔ رویداد کلِ ورکر را تا پایانِ بارگذاری کر می‌کند).

`nudenet` در محیطِ تست نصب نیست، پس مثلِ `test_safety_detector_lock` سازنده
وصله می‌خورد — چیزی که سنجیده می‌شود قاعده است نه خودِ مدل.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
import types

import pytest

from app import safety, worker


@pytest.fixture(autouse=True)
def _reset_detector():
    safety._detector = None
    safety._detector_failed = False
    yield
    safety._detector = None
    safety._detector_failed = False


def _flags(monkeypatch, enabled: bool = True, pixels: bool = True, node_role: str = "") -> None:
    async def _get_bool(key: str, default: bool) -> bool:
        return {"safety_enabled": enabled, "safety_scan_pixels": pixels}.get(key, default)

    monkeypatch.setattr(worker.settings_store, "get_bool", _get_bool)
    monkeypatch.setattr(worker.settings, "node_role", node_role)


def _spy(monkeypatch) -> list[str]:
    """`safety.available` را با جاسوسی که نامِ threadش را ثبت می‌کند عوض می‌کند."""
    seen: list[str] = []

    def _available() -> bool:
        seen.append(threading.current_thread().name)
        return True

    monkeypatch.setattr(safety, "available", _available)
    return seen


# ── گیتِ فلگ‌ها ────────────────────────────────────────────────────────────
async def test_warm_up_runs_when_both_safety_flags_are_on(monkeypatch):
    seen = _spy(monkeypatch)
    _flags(monkeypatch, True, True)
    await worker._warm_safety_model()
    assert len(seen) == 1, "مدل باید دقیقاً یک‌بار warm شود"


async def test_warm_up_is_skipped_when_safety_is_off(monkeypatch):
    seen = _spy(monkeypatch)
    _flags(monkeypatch, enabled=False)
    await worker._warm_safety_model()
    assert seen == [], "با فیلترِ خاموش نباید ۸۱ مگابایت بار شود"


async def test_warm_up_is_skipped_when_the_pixel_layer_is_off(monkeypatch):
    seen = _spy(monkeypatch)
    _flags(monkeypatch, pixels=False)
    await worker._warm_safety_model()
    assert seen == [], "لایهٔ پیکسل خاموش است — مدل لازم نیست"


# ── گیتِ نقشِ نود ──────────────────────────────────────────────────────────
async def test_the_processing_node_does_not_warm_a_model_it_never_uses(monkeypatch):
    """`run_screen` بدونِ `_queue_name` صف می‌شود، پس به `arq:queue:proc` نمی‌رسد؛
    و `run_op` هیچ مسیری به safety ندارد."""
    seen = _spy(monkeypatch)
    _flags(monkeypatch, node_role="processing")
    await worker._warm_safety_model()
    assert seen == [], "نودِ پردازش نباید ۸۱ مگابایتِ بی‌مصرف بار کند"


async def test_the_download_node_does_warm_up(monkeypatch):
    """کنترل: نودِ دانلود **واقعاً** اسکن می‌کند، پس باید warm شود."""
    seen = _spy(monkeypatch)
    _flags(monkeypatch, node_role="download")
    await worker._warm_safety_model()
    assert len(seen) == 1


# ── قیدِ سوم: نباید حلقهٔ رویداد را ببندد ─────────────────────────────────
async def test_the_load_happens_in_a_thread_not_on_the_event_loop(monkeypatch):
    seen = _spy(monkeypatch)
    _flags(monkeypatch)
    await worker._warm_safety_model()
    assert seen and seen[0] != threading.current_thread().name, \
        "بارگذاری روی threadِ اصلی انجام شد — حلقهٔ رویداد بسته می‌شود"


async def test_the_worker_stays_responsive_while_the_model_loads(monkeypatch):
    """سنجهٔ واقعیِ «مسدود نمی‌کند»: حلقه باید در طولِ بارگذاری تیک بزند.

    اگر `safety.available()` مستقیم (بدونِ `to_thread`) صدا زده شود، این ده
    `sleep` تا پایانِ بارگذاری اصلاً اجرا نمی‌شوند و زمانِ سپری‌شده از مجموعِ
    هر دو بیشتر می‌شود.
    """
    def _slow_available() -> bool:
        time.sleep(0.4)
        return True

    monkeypatch.setattr(safety, "available", _slow_available)
    _flags(monkeypatch)

    task = asyncio.create_task(worker._warm_safety_model())
    t0 = time.monotonic()
    for _ in range(10):
        await asyncio.sleep(0.02)
    loop_elapsed = time.monotonic() - t0
    assert loop_elapsed < 0.35, (
        f"حلقهٔ رویداد {loop_elapsed:.2f} ثانیه بسته بود — بارگذاری روی خودِ حلقه است")
    await task


# ── تاب‌آوری و هم‌زمانی ────────────────────────────────────────────────────
async def test_a_broken_warm_up_never_breaks_worker_startup(monkeypatch):
    def _boom() -> bool:
        raise RuntimeError("model file corrupt")

    monkeypatch.setattr(safety, "available", _boom)
    _flags(monkeypatch)
    await worker._warm_safety_model()      # نباید چیزی بالا بیاید


async def test_warm_up_racing_a_real_job_still_builds_one_detector(monkeypatch):
    """قفلِ #۸۹ پیش‌نیازِ این کار است، نه جانبیِ آن.

    warm-upِ پس‌زمینه‌ای احتمالِ ساختِ هم‌زمان را **بیشتر** می‌کند، چون حالا یک
    بارگذاری می‌تواند دقیقاً هم‌زمان با اولین جابِ واقعی در جریان باشد.
    """
    built: list[float] = []

    class FakeDetector:
        def __init__(self) -> None:
            built.append(time.monotonic())
            time.sleep(0.05)              # پنجرهٔ مسابقه را باز نگه می‌دارد

        def detect(self, _path):
            return []

    mod = types.ModuleType("nudenet")
    mod.NudeDetector = FakeDetector
    monkeypatch.setitem(sys.modules, "nudenet", mod)
    _flags(monkeypatch)

    # warm-up و یک «جابِ واقعی» هم‌زمان به `_get_detector` می‌رسند
    await asyncio.gather(
        worker._warm_safety_model(),
        asyncio.to_thread(safety._get_detector),
        asyncio.to_thread(safety._get_detector),
    )
    assert len(built) == 1, f"{len(built)} بار مدل ساخته شد — قفل نگرفت"
