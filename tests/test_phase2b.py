"""فاز ۲ب — موارد ۲-۳ (سیکِ برش)، ۲-۴ (لغو)، ۲-۵ (fallbackِ انکودر).

اولین تست‌های ریپو که مارکرِ `ffmpeg` را دارند. تا امروز آن مارکر روی صفر تست
بود، پس قلابِ skip در `conftest` از چیزی محافظت نمی‌کرد.

ffmpegِ واقعی، نه ماک: ۲-۳ دربارهٔ معناشناسیِ خودِ `-ss/-to` است و ۲-۵ دربارهٔ
رفتارِ واقعیِ تایم‌اوت — هر دو با ماک فقط ادعای تست‌اند.
"""
from __future__ import annotations

import asyncio
import inspect
import subprocess
import time

import pytest

from app import processing as P
from app.exceptions import ProcessingCancelled, ProcessingTimeout

# مارکر **per-test** است نه سطحِ ماژول: تست‌های ۲-۵ با `_run`ِ وصله‌خورده کار
# می‌کنند و به ffmpeg نیاز ندارند، پس نباید با نبودِ ffmpeg بی‌صدا skip شوند —
# ظریف‌ترین باگِ این فاز همان است و پوششش نباید به نصبِ CI گره بخورد.
needs_ffmpeg = pytest.mark.ffmpeg


def _probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60).stdout
    return float(out.strip())


def _make_video(path, seconds: int, rate: int = 25, size: str = "320x240") -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"testsrc=size={size}:rate={rate}:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "250", str(path)],
        check=True, capture_output=True, timeout=300)
    return str(path)


# ── ۲-۳: سیکِ ورودی در trim_video ───────────────────────────────
def test_trim_video_seeks_before_input():
    """پیش از رفع fail می‌شود: `-ss` بعد از `-i` بود (سیکِ خروجی).

    این تستِ ساختاری است چون خودِ باگ **کارایی** است نه درستی — خروجی قبلاً هم
    درست بود، فقط همهٔ فریم‌های پیش از `start` بی‌جهت دیکود می‌شدند.
    """
    src = inspect.getsource(P.trim_video)
    cmd_part = src[src.index("_run(["):]
    i_ss, i_to, i_in = cmd_part.index('"-ss"'), cmd_part.index('"-to"'), cmd_part.index('"-i"')
    assert i_ss < i_in, "`-ss` باید قبل از `-i` باشد (سیکِ ورودی)"
    assert i_to < i_in, (
        "`-to` هم باید قبل از `-i` باشد؛ بعد از آن گزینهٔ خروجی می‌شود و چون سیکِ "
        "ورودی تایم‌استمپ را صفر می‌کند، مدتِ برش غلط درمی‌آید")


@needs_ffmpeg
async def test_trim_video_cuts_exactly_the_requested_range(tmp_path):
    """مدتِ خروجی باید دقیقاً `end - start` باشد.

    این یکی روی سورسِ **پیش از رفع هم پاس می‌شود** و عمداً همین‌طور است: کارش
    گرفتنِ رفعِ ساده‌انگارانه است (فقط `-ss` را جلو ببری و `-to` را بعدِ `-i`
    بگذاری) که برشِ [۳،۷] را ۷ ثانیه می‌دهد نه ۴.
    """
    src = _make_video(tmp_path / "src.mp4", seconds=12)
    out = str(tmp_path / "cut.mp4")
    await P.trim_video(src, out, 3.0, 7.0)
    assert _probe_duration(out) == pytest.approx(4.0, abs=0.25)


@needs_ffmpeg
async def test_trim_video_is_accurate_far_into_the_file(tmp_path):
    """برشِ دیرهنگام هم باید همان‌قدر دقیق باشد — سیکِ ورودی نباید به کی‌فریم بچسبد.

    ffmpeg از کی‌فریمِ پیش از `start` دیکود می‌کند و اضافه‌ها را دور می‌ریزد، پس
    با `-g 250` (کی‌فریم هر ۱۰ ثانیه) هم شروعِ برش سرِ جایش است.
    """
    src = _make_video(tmp_path / "long.mp4", seconds=60)
    out = str(tmp_path / "late.mp4")
    await P.trim_video(src, out, 52.0, 56.0)
    assert _probe_duration(out) == pytest.approx(4.0, abs=0.25)


@needs_ffmpeg
async def test_trim_audio_keeps_the_shape_trim_video_now_matches(tmp_path):
    """`trim_audio` از قبل درست بود؛ این تست هر دو را هم‌شکل نگه می‌دارد."""
    src = str(tmp_path / "a.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                    "-c:a", "libmp3lame", src], check=True, capture_output=True, timeout=120)
    out = str(tmp_path / "acut.mp3")
    await P.trim_audio(src, out, 3.0, 7.0)
    assert _probe_duration(out) == pytest.approx(4.0, abs=0.35)


# ── ۲-۴: لغو مستقل از progress ──────────────────────────────────
@needs_ffmpeg
async def test_cancel_works_without_progress(tmp_path, monkeypatch):
    """قلبِ ۲-۴: `_run` بدونِ progress/duration هم باید لغو را ببیند.

    پیش از رفع، چکِ لغو فقط داخلِ خوانندهٔ `-progress` بود، پس این فراخوانی تا
    آخر می‌رفت و `ProcessingCancelled` نمی‌داد.
    """
    monkeypatch.setattr(P, "_CANCEL_POLL", 0.2)
    src = _make_video(tmp_path / "src.mp4", seconds=30, rate=30, size="640x480")
    out = str(tmp_path / "slow.mp4")

    async def always_cancel() -> bool:
        return True

    started = time.monotonic()
    with pytest.raises(ProcessingCancelled):
        # -preset veryslow تا کار به‌قدرِ کافی طول بکشد که ناظر برسد
        await P._run(["ffmpeg", "-y", "-i", src, "-c:v", "libx264",
                      "-preset", "veryslow", "-crf", "18", out], cancel=always_cancel)
    assert time.monotonic() - started < 25, "لغو باید زود اثر کند، نه سرِ اتمامِ کار"


@needs_ffmpeg
async def test_concat_normalisation_phase_is_cancellable(tmp_path, monkeypatch):
    """`concat_videos` در حلقهٔ نرمال‌سازی `cancel` می‌داد ولی progress نه.

    همان حلقه طولانی‌ترین بخشِ کار است، پس دکمهٔ لغو عملاً بی‌اثر بود.
    """
    monkeypatch.setattr(P, "_CANCEL_POLL", 0.2)
    a = _make_video(tmp_path / "a.mp4", seconds=15, rate=30, size="640x480")
    b = _make_video(tmp_path / "b.mp4", seconds=15, rate=30, size="640x480")

    async def always_cancel() -> bool:
        return True

    with pytest.raises(ProcessingCancelled):
        await P.concat_videos([a, b], str(tmp_path / "joined.mp4"),
                              width=640, height=480, cancel=always_cancel)


@needs_ffmpeg
async def test_a_cancel_that_never_fires_does_not_break_the_run(tmp_path):
    """کنترل: با cancelی که همیشه False است کار باید عادی تمام شود."""
    src = _make_video(tmp_path / "src.mp4", seconds=3)
    out = str(tmp_path / "muted.mp4")

    async def never() -> bool:
        return False

    await P.mute_video(src, out, cancel=never)
    assert _probe_duration(out) == pytest.approx(3.0, abs=0.3)


async def test_mute_and_metadata_accept_cancel():
    """این دو اصلاً `cancel` نمی‌گرفتند، پس رفعِ `_run` تنهایی درستشان نمی‌کرد."""
    assert "cancel" in inspect.signature(P.mute_video).parameters
    assert "cancel" in inspect.signature(P.write_audio_metadata).parameters
    from app import tasks
    src = inspect.getsource(tasks._do_op)
    assert "P.mute_video(inpath, out, cancel=cancel)" in src
    assert "cancel=cancel)" in src[src.index("write_audio_metadata"):][:120]


@needs_ffmpeg
async def test_the_watcher_does_not_outlive_the_run(tmp_path):
    """ناظر باید در `finally` کنسل شود، وگرنه مثلِ keepaliveِ dl_active نشت می‌کند."""
    src = _make_video(tmp_path / "src.mp4", seconds=2)
    out = str(tmp_path / "o.mp4")

    async def never() -> bool:
        return False

    before = len(asyncio.all_tasks())
    await P.mute_video(src, out, cancel=never)
    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) <= before, "تسکِ ناظر بعد از پایانِ کار زنده مانده"


# ── ۲-۵: تایم‌اوت نباید fallback بدهد ───────────────────────────
@needs_ffmpeg
async def test_timeout_raises_a_distinct_error(tmp_path):
    src = _make_video(tmp_path / "src.mp4", seconds=20, rate=30, size="640x480")
    with pytest.raises(ProcessingTimeout):
        await P._run(["ffmpeg", "-y", "-i", src, "-c:v", "libx264",
                      "-preset", "veryslow", "-crf", "18", str(tmp_path / "o.mp4")],
                     timeout=0.7)


def test_processing_timeout_is_still_a_runtime_error():
    """زیرکلاسِ RuntimeError می‌ماند تا هر `except RuntimeError`ِ دیگری نشکند."""
    assert issubclass(ProcessingTimeout, RuntimeError)


def test_the_ffmpeg_marker_is_not_dead_weight():
    """نگهبانِ خودِ مارکر: اگر تست‌های نشان‌دار حذف شوند باید بفهمیم.

    قلابِ skip در `conftest` از ۲۰۲۶-۰۷ وجود داشت ولی **صفر** تست مارکر را
    داشت، پس ماه‌ها از هیچ‌چیز محافظت نمی‌کرد و کسی متوجه نشد. گامِ CIی که اول
    برای این نوشتم کار نمی‌کرد: با صفر تستِ نشان‌دار، `pytest -m ffmpeg` همه را
    deselect می‌کند و با کدِ **صفر** خارج می‌شود (کدِ ۵ فقط وقتی است که اصلاً
    چیزی جمع نشود). پس نگهبان باید خودش تست باشد — و این‌طور محلی هم می‌دود.
    """
    import re
    from pathlib import Path

    tests_dir = Path(__file__).resolve().parent
    hits = sum(len(re.findall(r"@needs_ffmpeg|pytest\.mark\.ffmpeg", p.read_text(encoding="utf-8")))
               for p in tests_dir.glob("test_*.py"))
    assert hits >= 5, (
        f"فقط {hits} تست مارکرِ ffmpeg دارد — یا تست‌های مسیرِ رسانه حذف شده‌اند "
        f"یا مارکر دوباره بی‌اثر شده است")


async def test_a_timed_out_encode_does_not_run_a_second_full_encode(tmp_path, monkeypatch):
    """قلبِ ۲-۵: nvencِ تایم‌اوت‌شده نباید یک اجرای کاملِ x264 راه بیندازد.

    پیش از رفع، `except RuntimeError` تایم‌اوت را هم می‌گرفت و مجموعِ دو اجرا از
    `job_timeout`ِ ARQ رد می‌شد.
    """
    calls: list[list[str]] = []

    async def fake_run(cmd, **kw):
        calls.append(cmd)
        raise ProcessingTimeout("processing timed out")

    monkeypatch.setattr(P, "_run", fake_run)
    with pytest.raises(ProcessingTimeout):
        await P.compress_video("in.mp4", "out.mp4", encoder="nvenc")
    assert len(calls) == 1, f"بعد از تایم‌اوت {len(calls)} اجرا شد، باید ۱ باشد"


async def test_a_real_encoder_failure_still_falls_back(tmp_path, monkeypatch):
    """کنترلِ جهتِ عکس: شکستِ واقعیِ انکودر باید همچنان fallback بدهد."""
    calls: list[list[str]] = []

    async def fake_run(cmd, **kw):
        calls.append(cmd)
        if "h264_nvenc" in cmd:
            raise RuntimeError("ffmpeg failed (code 1): Unknown encoder 'h264_nvenc'")

    monkeypatch.setattr(P, "_run", fake_run)
    await P.compress_video("in.mp4", "out.mp4", encoder="nvenc")
    assert len(calls) == 2, "شکستِ انکودر باید به x264 برگردد"
    assert "libx264" in calls[1]


async def test_the_tiny_path_has_the_same_two_rules(tmp_path, monkeypatch):
    """`compress_video_tiny` همان دو شاخه را دارد و جدا فراموش می‌شود."""
    calls: list[list[str]] = []

    async def timeout_run(cmd, **kw):
        calls.append(cmd)
        raise ProcessingTimeout("processing timed out")

    monkeypatch.setattr(P, "_run", timeout_run)
    with pytest.raises(ProcessingTimeout):
        await P.compress_video_tiny("in.mp4", "out.mp4", duration=60.0, encoder="nvenc")
    assert len(calls) == 1, "مسیرِ tiny هم نباید بعد از تایم‌اوت دوباره انکود کند"

    calls.clear()

    async def failing_run(cmd, **kw):
        calls.append(cmd)
        if "h264_nvenc" in cmd:
            raise RuntimeError("ffmpeg failed (code 1): no NVENC capable devices found")

    monkeypatch.setattr(P, "_run", failing_run)
    await P.compress_video_tiny("in.mp4", "out.mp4", duration=60.0, encoder="nvenc")
    assert len(calls) == 2, "مسیرِ tiny باید روی شکستِ واقعی fallback بدهد"
