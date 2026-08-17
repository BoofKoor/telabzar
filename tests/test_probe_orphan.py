"""دو زیرفرایندِ یتیمِ باقی‌مانده: `probe` و `_yt_search_candidates`.

`_run` (ffmpeg) و `_run_dl` (دانلود) از قبل روی `CancelledError` فرزندشان را
می‌کُشتند. دو مسیرِ دیگر که yt-dlp اجرا می‌کنند نمی‌کُشتند — هر دو فقط
`asyncio.TimeoutError` را می‌گرفتند:

  • `downloader.probe` — فازِ probeِ یوتیوب. در تولید `dl_ux_youtube = probe`
    ست است، پس **هر** لینکِ یوتیوب از این‌جا رد می‌شود.
  • `downloader._yt_search_candidates` — مسیرِ تطبیقِ اسپاتیفای/اپل. در یک جابِ
    پلی‌لیست تا `match_max_tracks` (پیش‌فرض ۲۰) بار × تا دو شکلِ کوئری.

محرک `job_timeout`ِ ARQ نیست — **خاموشیِ ورکر** است، یعنی هر `telabzar update`.
و هر دو `--cookies` می‌فرستند، پس یتیمشان همان چیزی را می‌سوزاند که یتیمِ
`_run_dl` می‌سوزاند: سهمیهٔ یک اکانتِ سشن، بی‌آنکه جایی ثبت شود (جاب مرده، پس
`mark_ok`/`mark_fail`/`note_spend` هیچ‌کدام صدا زده نمی‌شوند).

**دو قیدِ هارنس، هر دو از درس‌های ثبت‌شده:**

۱. yt-dlpِ جعلی **خودش هرگز تمام نمی‌شود** (درسِ ۳الف). اگر تمام‌شدنی باشد،
   «فرایند رفت» می‌تواند یعنی «خودش تمام شد» و تست همان‌جا vacuous است — دقیقاً
   اتفاقی که برای تست‌های یتیمِ ffmpeg افتاد و چهار تست را با سورسِ سابوتاژشده
   سبز گذاشت.

۲. PID از **فایلی که خودِ فرایند می‌نویسد** خوانده می‌شود، نه از `pgrep`.
   `pgrep -f` خطِ فرمانِ خودِ شل/تست را هم می‌شمارد و `pgrep -x` هم به نامِ
   باینری بند است، در حالی که این‌جا مفسرِ پایتون است. فایلِ PID دقیقاً همان
   فرایندی را می‌شناساند که `probe` بالا آورده.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

import pytest

from app import downloader as D


# ── هارنس ──────────────────────────────────────────────────────────
def _fake_ytdlp(tmp_path, name: str, body: str) -> str:
    """اسکریپتی اجرایی که جای `yt-dlp` می‌نشیند (`D.YTDLP` یک رشتهٔ مسیر است)."""
    p = tmp_path / name
    p.write_text(f"#!{sys.executable}\n" + body)
    p.chmod(0o755)
    return str(p)


_ENDLESS = """
import json, os, sys
here = os.environ["FAKE_STATE"]
with open(here + ".argv", "w") as fh:
    json.dump(sys.argv[1:], fh)
with open(here + ".pid", "w") as fh:
    fh.write(str(os.getpid()))
    fh.flush()
import time
while True:            # خودبه‌خود تمام‌شدنی نیست → «رفت» فقط یعنی «کشته شد»
    time.sleep(0.05)
"""


def _alive(pid: int) -> bool:
    """آیا فرایند **زنده** است — زامبی حساب نمی‌شود.

    رفع عمداً `await proc.wait()` نمی‌زند (داکس‌استرینگِ `kill_orphan`)، پس بینِ
    SIGKILL و reapِ ناظرِ فرزندِ asyncio یک پنجرهٔ کوتاهِ `Z` هست که هیچ کاری
    نمی‌کند و **نباید** شکست خوانده شود — همان تمایزی که ماژولِ یتیمِ ffmpeg هم
    مجبور شد قائل شود. `os.kill(pid, 0)` این تمایز را نمی‌گذارد (روی زامبی هم
    موفق است)، پس حالت از `/proc` خوانده می‌شود.
    """
    try:
        with open(f"/proc/{pid}/stat") as fh:
            # نامِ فرمان داخلِ پرانتز است و می‌تواند فاصله داشته باشد → از آخر
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
        return False


async def _wait_dead(pid: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        await asyncio.sleep(0.05)
    return not _alive(pid)


async def _spawned_pid(state, timeout: float = 5.0) -> int:
    """تا بالا آمدنِ فرایندِ جعلی صبر کن و PIDش را بده."""
    pidf = state.with_suffix(state.suffix + ".pid")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pidf.exists() and pidf.read_text().strip():
            return int(pidf.read_text().strip())
        await asyncio.sleep(0.02)
    raise AssertionError("زیرفرایندِ جعلی اصلاً بالا نیامد — تست بی‌معنا می‌شود")


@pytest.fixture()
def endless(tmp_path, monkeypatch):
    """`D.YTDLP` را به یک yt-dlpِ تمام‌نشدنی می‌بندد و مسیرِ حالتش را می‌دهد."""
    state = tmp_path / "state"
    monkeypatch.setenv("FAKE_STATE", str(state))
    monkeypatch.setattr(D, "YTDLP", _fake_ytdlp(tmp_path, "yt-dlp", _ENDLESS))
    return state


async def _cancel_and_check(coro, state) -> int:
    """کورو را شروع کن، تا بالا آمدنِ فرزند صبر کن، لغو کن، PID را برگردان."""
    task = asyncio.create_task(coro)
    pid = await _spawned_pid(state)
    assert _alive(pid), "پیش‌شرط: فرزند باید زنده باشد وگرنه تست چیزی نمی‌سنجد"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return pid


# ── کنترلِ مثبت: هارنس می‌تواند یک kill را ببیند ────────────────────
async def test_the_harness_can_observe_a_kill(tmp_path):
    """**پیش‌شرطِ اعتبارِ دو تستِ بعدی.**

    `_run_dl` از قبل رفع شده، پس این‌جا فرایند **باید** کشته شود. اگر این
    بیفتد، هارنس (فایلِ PID، `_alive`، مهلتِ انتظار) خراب است و هر سبزِ دیگری
    در این فایل دربارهٔ هارنس حرف می‌زند نه دربارهٔ کد — و اگر روزی رفعِ
    `_run_dl` هم برگردد، همین‌جا دیده می‌شود.
    """
    state = tmp_path / "state"
    monkey = tmp_path / "yt-dlp"
    monkey.write_text(f"#!{sys.executable}\n" + _ENDLESS)
    monkey.chmod(0o755)
    import os
    os.environ["FAKE_STATE"] = str(state)
    try:
        pid = await _cancel_and_check(D._run_dl([str(monkey)], timeout=120), state)
        assert await _wait_dead(pid), "کنترلِ مثبت افتاد — هارنس kill را نمی‌بیند"
    finally:
        os.environ.pop("FAKE_STATE", None)


# ── ۱: probe ───────────────────────────────────────────────────────
async def test_probe_does_not_leave_yt_dlp_running_after_cancellation(endless):
    """قلبِ کار: پیش از رفع، yt-dlpِ فازِ probe زنده می‌ماند."""
    pid = await _cancel_and_check(
        D.probe("https://youtu.be/x", {"cookies": None}), endless)
    assert await _wait_dead(pid), (
        "yt-dlp بعد از لغوِ تسک زنده ماند — فازِ probe یتیم می‌گذارد و سهمیهٔ "
        "اکانتِ سشن را می‌سوزاند")


async def test_the_orphaned_probe_was_holding_a_cookie(endless, tmp_path):
    """چرا یتیمِ این مسیر گران است، نه فقط نامرتب.

    ادعا روی خودِ `--cookies` است: `_common_flags` آن را می‌فرستد، پس فرایندی
    که یتیم می‌ماند دارد با هویتِ یک اکانتِ **واقعی** به یوتیوب می‌زند. اگر این
    روزی جور نشود، استدلالِ «هزینه‌اش سهمیهٔ سشن است» بی‌پشتوانه می‌شود.
    """
    ckfile = tmp_path / "ck.txt"
    ckfile.write_text("# Netscape HTTP Cookie File\n")
    pid = await _cancel_and_check(
        D.probe("https://youtu.be/x", {"cookies": str(ckfile)}), endless)
    await _wait_dead(pid)

    argv = json.loads((tmp_path / "state.argv").read_text())
    assert "--cookies" in argv, f"probe بدونِ کوکی اجرا شد: {argv}"


# ── ۲: _yt_search_candidates ───────────────────────────────────────
async def test_the_match_search_does_not_leave_yt_dlp_running(endless):
    """مسیرِ تطبیقِ اسپاتیفای/اپل — تا ۴۰ زیرفرایند در یک جابِ پلی‌لیست."""
    pid = await _cancel_and_check(
        D._yt_search_candidates("some track", {"cookies": None}), endless)
    assert await _wait_dead(pid), (
        "yt-dlp بعد از لغوِ تسک زنده ماند — مسیرِ تطبیق یتیم می‌گذارد")


async def test_the_match_search_also_holds_a_cookie(endless, tmp_path):
    """همان ادعا برای مسیرِ تطبیق: این‌جا هم `--cookies` می‌رود.

    این تابع پرچم‌ها را **خودش** می‌سازد و از `_common_flags` استفاده نمی‌کند،
    پس ادعای کوکی باید جدا سنجیده شود؛ وگرنه یک تغییر در آن شاخه بی‌صدا از
    تستِ `probe` رد می‌شود.
    """
    ckfile = tmp_path / "ck.txt"
    ckfile.write_text("# Netscape HTTP Cookie File\n")
    pid = await _cancel_and_check(
        D._yt_search_candidates("t", {"cookies": str(ckfile)}), endless)
    await _wait_dead(pid)

    argv = json.loads((tmp_path / "state.argv").read_text())
    assert "--cookies" in argv, f"جست‌وجوی تطبیق بدونِ کوکی اجرا شد: {argv}"


# ── کنترل‌ها: مسیرهای سالم نباید عوض شوند ──────────────────────────
async def test_a_normal_probe_still_parses(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "YTDLP", _fake_ytdlp(tmp_path, "yt-dlp", """
import json, sys
json.dump({"title": "t", "duration": 12, "formats": []}, sys.stdout)
"""))
    info = await D.probe("https://youtu.be/x", {})
    assert info["title"] == "t" and info["duration"] == 12


async def test_a_failing_probe_still_reports_the_error(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "YTDLP", _fake_ytdlp(tmp_path, "yt-dlp", """
import sys
print("ERROR: Sign in to confirm you're not a bot", file=sys.stderr)
sys.exit(1)
"""))
    with pytest.raises(RuntimeError) as ei:
        await D.probe("https://youtu.be/x", {})
    assert "not a bot" in str(ei.value), "دُمِ stderr باید به دستِ حلقهٔ کوکی برسد"


async def test_a_probe_timeout_still_raises_and_kills(endless):
    """کنترل: شاخهٔ تایم‌اوت دست‌نخورده — نه پیامش عوض شود نه فرایندش بماند."""
    task = asyncio.create_task(D.probe("https://youtu.be/x", {}, timeout=0.5))
    pid = await _spawned_pid(endless)
    with pytest.raises(RuntimeError, match="probe timed out"):
        await task
    assert await _wait_dead(pid), "شاخهٔ تایم‌اوت فرایند را یتیم گذاشت"


async def test_a_normal_search_still_returns_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "YTDLP", _fake_ytdlp(tmp_path, "yt-dlp", """
import json, sys
json.dump({"entries": [{"id": "a"}, {"id": "b"}]}, sys.stdout)
"""))
    assert await D._yt_search_candidates("q", {}) == [{"id": "a"}, {"id": "b"}]


async def test_a_failing_search_still_swallows_and_returns_empty(tmp_path, monkeypatch):
    """کنترل: این تابع عمداً خطا را می‌بلعد (بالادست fallback دارد).

    رفعِ یتیم نباید این را عوض کند — `except BaseException` فقط سرِ راهِ
    استثناهایی است که **از قبل** بالا می‌رفتند، نه سرِ راهِ خروجِ ناموفقِ عادی.
    """
    monkeypatch.setattr(D, "YTDLP", _fake_ytdlp(tmp_path, "yt-dlp", """
import sys
sys.exit(1)
"""))
    assert await D._yt_search_candidates("q", {}) == []


async def test_a_search_timeout_still_returns_empty(endless):
    """کنترل: تایم‌اوت باید `[]` بدهد نه استثنا — و فرایند نماند."""
    task = asyncio.create_task(D._yt_search_candidates("q", {}, timeout=0.5))
    pid = await _spawned_pid(endless)
    assert await task == []
    assert await _wait_dead(pid), "شاخهٔ تایم‌اوتِ جست‌وجو فرایند را یتیم گذاشت"
