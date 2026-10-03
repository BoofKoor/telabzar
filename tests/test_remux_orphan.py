"""فاز ۴ / موردِ ۳۴ج — remuxِ `_ensure_mp4` فرزندش را یتیم نگذارد.

پنجمین زیرفرایند با همان باگ (چهارتای قبلی در `kill_orphan` جمع شدند):
روی تایم‌اوت `wait_for` فقط `proc.wait()` را لغو می‌کرد و ffmpeg می‌ماند، و
`CancelledError` (لغوِ جاب، خاموشیِ ورکر سرِ هر `telabzar update`) اصلاً از
`except Exception` رد می‌شد. remuxِ یک فایلِ چندگیگی یعنی دقیقه‌ها I/Oِ دیسک
برای جابی که مرده.

هارنس همان قیدهای `test_probe_orphan`: ffmpegِ جعلی **خودش تمام نمی‌شود** (پس
«رفت» فقط یعنی «کشته شد») و PID از فایلی که خودِ فرایند می‌نویسد خوانده می‌شود.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

from app import downloader as D
from tests.test_probe_orphan import _ENDLESS, _alive


@pytest.fixture
def endless_ffmpeg(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    p = bindir / "ffmpeg"
    p.write_text(f"#!{sys.executable}\n" + _ENDLESS)
    p.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    state = tmp_path / "ff"
    monkeypatch.setenv("FAKE_STATE", str(state))
    src = tmp_path / "clip.webm"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 64)
    return src, state


async def _pid(state) -> int:
    for _ in range(200):
        try:
            return int(open(str(state) + ".pid").read())
        except (FileNotFoundError, ValueError):
            await asyncio.sleep(0.02)
    raise AssertionError("ffmpegِ جعلی اصلاً اجرا نشد — تست چیزی نسنجید")


async def _gone(pid: int) -> bool:
    for _ in range(100):
        if not _alive(pid):
            return True
        await asyncio.sleep(0.05)
    return False


async def test_a_cancelled_remux_kills_ffmpeg(endless_ffmpeg):
    src, state = endless_ffmpeg
    task = asyncio.create_task(D._ensure_mp4(str(src)))
    pid = await _pid(state)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    try:
        assert await _gone(pid), "ffmpeg بعد از لغوِ جاب زنده ماند"
    finally:
        if _alive(pid):
            os.kill(pid, 9)


async def test_a_timed_out_remux_kills_ffmpeg_and_keeps_the_original(endless_ffmpeg,
                                                                      monkeypatch):
    src, state = endless_ffmpeg
    monkeypatch.setattr(D, "_REMUX_TIMEOUT", 0.5, raising=False)
    t0 = time.monotonic()
    task = asyncio.create_task(D._ensure_mp4(str(src)))
    pid = await _pid(state)
    try:
        out = await asyncio.wait_for(task, 10)
        assert out == str(src), "فایلِ اصلی باید برگردد"
        assert time.monotonic() - t0 < 8
        assert await _gone(pid), "ffmpeg بعد از تایم‌اوتِ remux زنده ماند"
    finally:
        if _alive(pid):
            os.kill(pid, 9)
