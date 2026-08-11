"""فاز ۲پ / ۲-۲ — لغوِ سطحِ تسک نباید ffmpeg را یتیم بگذارد.

`_run` روی مسیرِ دکمهٔ لغو و روی تایم‌اوت فرایند را می‌کُشت، ولی روی
`CancelledError` — یعنی `job_timeout`ِ ARQ یا خاموشیِ ورکر — فقط ناظر را
می‌بست و خودِ ffmpeg زنده می‌ماند و تا آخر CPU می‌سوزاند.
"""
from __future__ import annotations

import asyncio
import subprocess

import pytest

from app import processing as P

needs_ffmpeg = pytest.mark.ffmpeg


def _live_ffmpeg() -> int:
    return len(subprocess.run(["pgrep", "-x", "ffmpeg"],
                              capture_output=True, text=True).stdout.split())


def _make_source(path, seconds: int = 30) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"testsrc=size=640x480:rate=30:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True, timeout=300)
    return str(path)


def _slow_encode(src: str, out: str) -> list[str]:
    """به‌قدرِ کافی کند که وسطِ کار بتوان لغوش کرد."""
    return ["ffmpeg", "-y", "-i", src, "-c:v", "libx264",
            "-preset", "veryslow", "-crf", "18", out]


@needs_ffmpeg
async def test_task_cancellation_kills_the_subprocess(tmp_path):
    """قلبِ ۲-۲: پیش از رفع، یک ffmpeg زنده باقی می‌ماند."""
    assert _live_ffmpeg() == 0, "محیط از قبل ffmpegِ در حال اجرا دارد"
    src = _make_source(tmp_path / "src.mp4")

    task = asyncio.create_task(P._run(_slow_encode(src, str(tmp_path / "o.mp4"))))
    await asyncio.sleep(1.5)
    assert _live_ffmpeg() == 1, "ffmpeg اصلاً بالا نیامد — تست بی‌معنا می‌شود"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(20):                      # به kill فرصتِ اثر بده
        if _live_ffmpeg() == 0:
            break
        await asyncio.sleep(0.1)
    assert _live_ffmpeg() == 0, "ffmpeg بعد از لغوِ تسک زنده ماند (یتیم)"


@needs_ffmpeg
async def test_cancellation_still_propagates(tmp_path):
    """کشتنِ فرایند نباید لغو را ببلعد — جاب باید واقعاً لغو شود."""
    src = _make_source(tmp_path / "src.mp4", seconds=20)
    task = asyncio.create_task(P._run(_slow_encode(src, str(tmp_path / "o.mp4"))))
    await asyncio.sleep(1.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    subprocess.run(["pkill", "-x", "ffmpeg"], capture_output=True)


@needs_ffmpeg
async def test_the_progress_branch_is_covered_too(tmp_path):
    """هر دو شاخهٔ `_run` باید پاک‌سازی کنند، نه فقط شاخهٔ بدونِ progress."""
    assert _live_ffmpeg() == 0
    src = _make_source(tmp_path / "src.mp4")

    async def on_progress(_pct: float) -> None:
        return None

    task = asyncio.create_task(P._run(
        _slow_encode(src, str(tmp_path / "o.mp4")),
        progress=on_progress, duration=30.0))
    await asyncio.sleep(1.5)
    assert _live_ffmpeg() == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(20):
        if _live_ffmpeg() == 0:
            break
        await asyncio.sleep(0.1)
    assert _live_ffmpeg() == 0, "شاخهٔ progress فرایند را یتیم گذاشت"


@needs_ffmpeg
async def test_a_normal_run_is_unaffected(tmp_path):
    """کنترل: مسیرِ عادی نباید عوض شود."""
    src = _make_source(tmp_path / "src.mp4", seconds=2)
    out = str(tmp_path / "ok.mp4")
    await P._run(["ffmpeg", "-y", "-i", src, "-c", "copy", out])
    import os
    assert os.path.exists(out) and os.path.getsize(out) > 0
    assert _live_ffmpeg() == 0
