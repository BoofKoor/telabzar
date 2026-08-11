"""فاز ۲پ / ۲-۲ — لغوِ سطحِ تسک نباید ffmpeg را یتیم بگذارد.

`_run` روی مسیرِ دکمهٔ لغو و روی تایم‌اوت فرایند را می‌کُشت، ولی روی
`CancelledError` — یعنی `job_timeout`ِ ARQ یا خاموشیِ ورکر — فقط ناظر را
می‌بست و خودِ ffmpeg زنده می‌ماند و تا آخر CPU می‌سوزاند.
"""
from __future__ import annotations

import asyncio
import subprocess
import time

import pytest

from app import processing as P

needs_ffmpeg = pytest.mark.ffmpeg


def _live_ffmpeg() -> int:
    """ffmpegهای **زنده** — زامبی عمداً شمرده نمی‌شود.

    قراردادِ رفعِ ۲-۲ «فرایند کشته شود» است، نه «بی‌درنگ reap شود»: `_run` روی
    مسیرِ لغو عمداً `await proc.wait()` نمی‌زند (اگر بزند، خودِ آن await دوباره
    `CancelledError` می‌گیرد و رفع را بی‌اثر می‌کند). پس بینِ SIGKILL و reapِ
    ناظرِ فرزندِ asyncio یک پنجرهٔ کوتاهِ `Z` هست که هیچ CPUای نمی‌سوزاند —
    یعنی دقیقاً همان چیزی که این تست‌ها **نباید** شکست بدانند.

    `pgrep -x` زامبی را هم می‌شمارد؛ اندازه‌گیری‌شده: بلافاصله بعد از لغو
    `pgrep=1` ولی حالتِ فرایند `Z` است و ۱۵۰ms بعد صفر می‌شود. همین باعث شده
    بود این ماژول به **ترتیبِ اجرا** حساس شود و تستِ سومْ پیش‌شرطِ خودش را
    ببازد چون تستِ دوم زامبیِ خودش را جا می‌گذاشت.
    """
    out = subprocess.run(["ps", "-eo", "stat=,comm="],
                         capture_output=True, text=True).stdout
    live = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "ffmpeg" and not parts[0].startswith("Z"):
            live += 1
    return live


async def _wait_no_ffmpeg(timeout: float = 2.0) -> int:
    """تا خالی‌شدن صبر می‌کند و تعدادِ نهایی را می‌دهد (به kill فرصتِ اثر بده).

    مهلت عمداً **کوتاه** است: کشتنِ واقعی بلافاصله اثر می‌کند (اندازه‌گیری‌شده:
    درست بعد از لغو، حالتِ فرایند `Z` است یعنی از قبل مرده)، پس دو ثانیه چند
    مرتبه بزرگ‌تر از چیزی است که لازم است. مهلتِ بلندتر فقط شکستِ واقعی را
    کندتر گزارش می‌کند و — با ورودیِ مدت‌دار — می‌تواند تست را بی‌معنا کند.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _live_ffmpeg() == 0:
            return 0
        await asyncio.sleep(0.05)
    return _live_ffmpeg()


def _make_source(path, seconds: int = 2) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"testsrc=size=640x480:rate=30:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True, timeout=300)
    return str(path)


def _endless_encode(out: str) -> list[str]:
    """انکودی که **خودش هرگز تمام نمی‌شود** — تنها راهِ پایانش کشته‌شدن است.

    نسخهٔ قبلی یک منبعِ ۳۰ثانیه‌ای می‌ساخت و با `-preset veryslow` انکودش
    می‌کرد، به این امید که «به‌قدرِ کافی کند» باشد. آن امید یک عددِ شانسی بود و
    تست را **بی‌معنا** می‌کرد: اندازه‌گیری روی همین ماشین نشان داد آن انکود
    ۵٫۵ ثانیه طول می‌کشد، یعنی حدودِ ۴ ثانیه بعد از لغو خودبه‌خود تمام می‌شد.
    پس هر مهلتِ انتظارِ بلندتر از آن، «فرایند مُرد» را می‌دید و سبز می‌شد —
    حتی وقتی کشتن اصلاً انجام نشده بود. با سابوتاژِ رفعِ ۲-۲ راستی‌آزمایی شد:
    هر چهار تست سبز ماندند.

    ورودیِ lavfi **بدونِ `duration`** آن متغیر را حذف می‌کند: فرایند تا ابد
    می‌ماند، پس «صفر شد» فقط و فقط یعنی کشته شد. ضمناً ساختنِ منبع هم لازم
    نیست، پس این ماژول از قبل هم سریع‌تر شد.
    """
    return ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x480:rate=30",
            "-c:v", "libx264", "-preset", "veryfast", out]


@needs_ffmpeg
async def test_task_cancellation_kills_the_subprocess(tmp_path):
    """قلبِ ۲-۲: پیش از رفع، یک ffmpeg زنده باقی می‌ماند."""
    assert _live_ffmpeg() == 0, "محیط از قبل ffmpegِ در حال اجرا دارد"

    task = asyncio.create_task(P._run(_endless_encode(str(tmp_path / "o.mp4"))))
    await asyncio.sleep(1.0)
    assert _live_ffmpeg() == 1, "ffmpeg اصلاً بالا نیامد — تست بی‌معنا می‌شود"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    try:
        assert await _wait_no_ffmpeg() == 0, "ffmpeg بعد از لغوِ تسک زنده ماند (یتیم)"
    finally:
        subprocess.run(["pkill", "-x", "ffmpeg"], capture_output=True)


@needs_ffmpeg
async def test_cancellation_still_propagates(tmp_path):
    """کشتنِ فرایند نباید لغو را ببلعد — جاب باید واقعاً لغو شود."""
    task = asyncio.create_task(P._run(_endless_encode(str(tmp_path / "o.mp4"))))
    await asyncio.sleep(1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    # بعدِ خودت را تمیز کن: بدونِ این انتظار، فرایندِ همین تست به تستِ بعدی
    # نشت می‌کرد و پیش‌شرطِ آن را می‌شکست. pkill فقط تورِ ایمنیِ آخر است تا
    # یک شکست به آبشارِ شکست تبدیل نشود.
    try:
        assert await _wait_no_ffmpeg() == 0, "فرایندِ این تست بعد از لغو زنده ماند"
    finally:
        subprocess.run(["pkill", "-x", "ffmpeg"], capture_output=True)


@needs_ffmpeg
async def test_the_progress_branch_is_covered_too(tmp_path):
    """هر دو شاخهٔ `_run` باید پاک‌سازی کنند، نه فقط شاخهٔ بدونِ progress."""
    assert _live_ffmpeg() == 0

    async def on_progress(_pct: float) -> None:
        return None

    task = asyncio.create_task(P._run(
        _endless_encode(str(tmp_path / "o.mp4")),
        progress=on_progress, duration=30.0))
    await asyncio.sleep(1.0)
    assert _live_ffmpeg() == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    try:
        assert await _wait_no_ffmpeg() == 0, "شاخهٔ progress فرایند را یتیم گذاشت"
    finally:
        subprocess.run(["pkill", "-x", "ffmpeg"], capture_output=True)


@needs_ffmpeg
async def test_a_normal_run_is_unaffected(tmp_path):
    """کنترل: مسیرِ عادی نباید عوض شود."""
    src = _make_source(tmp_path / "src.mp4", seconds=2)
    out = str(tmp_path / "ok.mp4")
    await P._run(["ffmpeg", "-y", "-i", src, "-c", "copy", out])
    import os
    assert os.path.exists(out) and os.path.getsize(out) > 0
    assert _live_ffmpeg() == 0
