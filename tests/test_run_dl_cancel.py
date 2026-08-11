"""فاز ۳ب / موردِ ۳ — لغو در `_run_dl`: از «هر خط یک EXISTS» به ناظرِ مشترک.

سه چیزِ مستقل که همگی از یک جا می‌آمدند (چکِ لغو سوارِ حلقهٔ خواندنِ stdout بود):

۱. **طوفانِ EXISTS** — yt-dlp با `--newline` و `--concurrent-fragments 4` ده‌ها
   خط در ثانیه می‌دهد و هر خط یک `redis.exists` می‌شد؛ روی نودِ دانلود این یک
   رفت‌وبرگشتِ WireGuard است.
۲. **دانلودِ گیرکرده اصلاً لغو نمی‌شد** — وقتی خطی نمی‌آید، `async for` بلاک
   می‌ماند و چکِ لغو هرگز اجرا نمی‌شود. دکمهٔ لغو تا تایم‌اوتِ ۳۰۰۰ ثانیه‌ای
   بی‌اثر بود.
۳. **یتیمِ ۲-۲، این‌بار گران‌تر** — `_run_dl` هیچ `except BaseException`ی نداشت،
   پس روی `job_timeout`/خاموشیِ ورکر yt-dlp زنده می‌ماند و **به دانلود ادامه
   می‌دهد**: سهمیهٔ همان اکانتِ کوکی را می‌سوزاند بی‌آنکه جایی ثبت شود.

زیرفرایندها واقعی‌اند. تستِ یتیم عمداً فرایندی می‌سازد که **خودش تمام نمی‌شود**
— درسِ ۳الف: تستی که سوژه‌اش می‌تواند خودبه‌خود بمیرد، همان‌جا vacuous است.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

from app import downloader as D
from app import processing as P
from app.exceptions import ProcessingCancelled


def _script(tmp_path, name: str, body: str) -> list[str]:
    p = tmp_path / name
    p.write_text(body)
    return [sys.executable, "-u", str(p)]


# ── ۱: طوفانِ EXISTS ───────────────────────────────────────────────────────
async def test_cancel_is_not_polled_once_per_output_line(tmp_path):
    """پیش از رفع: به‌ازای هر خطِ stdout یک `cancel()` (یعنی یک EXISTS)."""
    lines = 400
    cmd = _script(tmp_path, "chatty.py", f"""
for i in range({lines}):
    print(f"dl:  {{i / {lines} * 100:.1f}}%")
""")
    calls = 0

    async def cancel() -> bool:
        nonlocal calls
        calls += 1
        return False

    seen: list[float] = []

    async def progress(pct: float) -> None:
        seen.append(pct)

    await D._run_dl(cmd, progress=progress, cancel=cancel, timeout=60)

    assert len(seen) >= lines // 2, "خطوطِ پیشرفت باید خوانده شوند — تست بی‌معنا نشود"
    assert calls <= 5, (
        f"{calls} بار `cancel()` برای {lines} خط صدا زده شد — چکِ لغو هنوز "
        "سوارِ حلقهٔ خواندن است")


# ── ۲: دانلودِ گیرکرده (مهم‌ترین: امروز اصلاً لغو نمی‌شود) ─────────────────
async def test_a_stalled_download_can_still_be_cancelled(tmp_path, monkeypatch):
    """فرایندی که هیچ خروجی نمی‌دهد باید با دکمهٔ لغو بمیرد.

    پیش از رفع، `_read_out` روی `async for` بلاک است و چکِ لغو هرگز اجرا
    نمی‌شود، پس این فراخوانی تا تایم‌اوت طول می‌کشد و `RuntimeError` می‌دهد.
    """
    monkeypatch.setattr(P, "_CANCEL_POLL", 0.2)
    cmd = _script(tmp_path, "stalled.py", """
import time
time.sleep(600)          # هیچ خروجی‌ای نمی‌دهد — دقیقاً مثلِ اتصالِ هنگ‌کرده
""")

    async def cancel() -> bool:
        return True

    started = time.monotonic()
    with pytest.raises(ProcessingCancelled):
        await D._run_dl(cmd, cancel=cancel, timeout=6)
    assert time.monotonic() - started < 4, "لغو باید سریع اثر کند، نه سرِ تایم‌اوت"


async def test_a_chatty_download_is_still_cancellable(tmp_path, monkeypatch):
    """کنترل: مسیرِ پرحرف هم باید لغو شود (نه فقط مسیرِ ساکت)."""
    monkeypatch.setattr(P, "_CANCEL_POLL", 0.2)
    cmd = _script(tmp_path, "loud.py", """
import time
i = 0
while True:
    print(f"dl:  {i % 100}.0%")
    time.sleep(0.01)
    i += 1
""")

    async def cancel() -> bool:
        return True

    with pytest.raises(ProcessingCancelled):
        await asyncio.wait_for(D._run_dl(cmd, cancel=cancel, timeout=30), timeout=10)


# ── ۳: یتیمِ yt-dlp ────────────────────────────────────────────────────────
async def test_task_cancellation_does_not_leave_yt_dlp_downloading(tmp_path):
    """قلبِ یافتهٔ سوم: یتیم فقط زنده نمی‌ماند — **به کار ادامه می‌دهد**.

    سوژه فرایندی است که هرگز خودش تمام نمی‌شود و مدام روی دیسک می‌نویسد، پس
    «کارِ ادامه‌دار» مستقیماً دیده می‌شود: اگر بعد از لغو فایل باز هم رشد کند،
    یعنی دانلود هنوز در جریان است (و سهمیهٔ کوکی هنوز می‌سوزد).
    """
    marker = tmp_path / "bytes.log"
    cmd = _script(tmp_path, "endless.py", f"""
import time
with open({str(marker)!r}, "a") as fh:
    while True:                       # خودبه‌خود تمام‌شدنی نیست
        fh.write("x")
        fh.flush()
        time.sleep(0.02)
""")

    task = asyncio.create_task(D._run_dl(cmd, timeout=120))
    await asyncio.sleep(1.0)
    assert marker.exists() and marker.stat().st_size > 0, "فرایند اصلاً بالا نیامد"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.3)               # به kill فرصتِ اثر بده
    size_after_cancel = marker.stat().st_size
    await asyncio.sleep(0.5)
    assert marker.stat().st_size == size_after_cancel, (
        "فرایند بعد از لغوِ تسک هنوز می‌نویسد — yt-dlpِ یتیم به دانلود ادامه "
        "می‌دهد و سهمیهٔ اکانتِ کوکی را می‌سوزاند")


async def test_a_normal_download_is_unaffected(tmp_path):
    """کنترل: مسیرِ عادی نباید عوض شود — خروجی و دُمِ stdout سرِ جایشان."""
    cmd = _script(tmp_path, "ok.py", """
print("dl:  50.0%")
print("[download] Destination: whatever.mp4")
""")
    pct: list[float] = []

    async def progress(p: float) -> None:
        pct.append(p)

    tail = await D._run_dl(cmd, progress=progress, timeout=30)
    assert pct == [50.0]
    assert "Destination" in tail, "دُمِ stdout باید برگردد (تشخیصِ match-filter به آن بند است)"


async def test_a_failing_download_still_reports_stderr(tmp_path):
    """کنترل: خطا باید همان شکلِ قبلی را داشته باشد (پیامِ کاربر عوض نشود)."""
    cmd = _script(tmp_path, "bad.py", """
import sys
print("some stdout line")
print("ERROR: nope", file=sys.stderr)
sys.exit(1)
""")
    with pytest.raises(RuntimeError) as ei:
        await D._run_dl(cmd, timeout=30)
    assert "download failed" in str(ei.value)
    assert "some stdout line" in getattr(ei.value, "stdout_tail", "")
