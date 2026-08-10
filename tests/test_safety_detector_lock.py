"""بارگذاریِ مدلِ NudeNet باید فقط یک‌بار انجام شود، حتی زیرِ فشارِ هم‌زمانی.

`_detect_sync` داخلِ `asyncio.to_thread` اجرا می‌شود و ورکر `max_jobs=4` دارد،
پس روی ورکرِ تازه‌ری‌استارت‌شده چند جاب هم‌زمان به `_get_detector()` می‌رسند.
بدونِ قفل هر کدام یک `NudeDetector` می‌ساخت (~۸۱ مگابایت، اندازه‌گیریِ روی سرور)
و سه‌تا بلافاصله زباله می‌شدند.

خودِ nudenet در محیطِ تست نصب نیست (فقط در ایمیجِ ورکر است)، پس سازنده وصله
می‌خورد — چیزی که سنجیده می‌شود قاعدهٔ «یک‌بار» است، نه خودِ مدل.
"""
from __future__ import annotations

import sys
import threading
import time
import types

import pytest

from app import safety


@pytest.fixture(autouse=True)
def _reset_detector():
    """حالتِ سراسریِ ماژول بین تست‌ها پاک شود."""
    safety._detector = None
    safety._detector_failed = False
    yield
    safety._detector = None
    safety._detector_failed = False


def _install_fake_nudenet(monkeypatch, build_seconds: float = 0.05):
    """`nudenet` جعلی که ساخته‌شدنش کند است و خودش را می‌شمارد."""
    calls: list[float] = []

    class FakeDetector:
        def __init__(self) -> None:
            calls.append(time.monotonic())
            time.sleep(build_seconds)     # پنجرهٔ مسابقه را باز نگه می‌دارد

        def detect(self, _path):
            return []

    mod = types.ModuleType("nudenet")
    mod.NudeDetector = FakeDetector
    monkeypatch.setitem(sys.modules, "nudenet", mod)
    return calls


def test_concurrent_first_jobs_build_the_model_once(monkeypatch):
    """قلبِ باگ: چهار threadِ هم‌زمان، دقیقاً یک بارگذاری."""
    calls = _install_fake_nudenet(monkeypatch)
    results, start = [], threading.Barrier(4)

    def worker():
        start.wait()                      # هر چهار تا با هم وارد شوند
        results.append(safety._get_detector())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(calls) == 1, f"مدل {len(calls)} بار ساخته شد، باید ۱ باشد"
    assert len(results) == 4
    assert all(r is results[0] for r in results), "همه باید یک شیء بگیرند"


def test_the_hot_path_does_not_take_the_lock(monkeypatch):
    """بعد از بارگذاری نباید هیچ جابی سرِ قفل معطل شود.

    اگر چکِ اولِ بدونِ قفل حذف شود، هر فریمِ هر ویدیو قفل می‌گیرد — این تست
    الگوی double-checked را نگه می‌دارد.
    """
    _install_fake_nudenet(monkeypatch)
    safety._get_detector()                # گرم شود

    safety._detector_lock.acquire()       # قفل را گروگان بگیر
    try:
        got = safety._get_detector()      # نباید بلاک شود
    finally:
        safety._detector_lock.release()
    assert got is not None


def test_a_failed_load_is_remembered_and_not_retried(monkeypatch):
    """نبودِ مدل نباید هر فایل را کند کند (fail-open و فقط یک تلاش)."""
    attempts = []

    class Boom:
        def __init__(self):
            attempts.append(1)
            raise RuntimeError("no model")

    mod = types.ModuleType("nudenet")
    mod.NudeDetector = Boom
    monkeypatch.setitem(sys.modules, "nudenet", mod)

    assert safety._get_detector() is None
    assert safety._get_detector() is None
    assert safety.available() is False
    assert len(attempts) == 1, "بارگذاریِ شکست‌خورده نباید هر بار دوباره تلاش شود"


def test_a_failed_load_under_concurrency_is_also_single(monkeypatch):
    """همان قاعده در مسیرِ شکست — وگرنه ۴ جاب ۴ بار importِ گران می‌زنند."""
    attempts = []

    class Boom:
        def __init__(self):
            attempts.append(1)
            time.sleep(0.05)
            raise RuntimeError("no model")

    mod = types.ModuleType("nudenet")
    mod.NudeDetector = Boom
    monkeypatch.setitem(sys.modules, "nudenet", mod)

    start = threading.Barrier(4)

    def worker():
        start.wait()
        safety._get_detector()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(attempts) == 1, f"{len(attempts)} تلاشِ بارگذاری، باید ۱ باشد"
    assert safety._detector_failed is True
