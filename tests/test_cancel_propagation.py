"""فاز ۲پ / ۲-۷ — بستنِ ticker نباید لغوِ خودِ جاب را ببلعد.

`await ticker` بعد از `ticker.cancel()` به دو دلیلِ متفاوت `CancelledError`
می‌دهد و از روی خودِ استثنا قابلِ تفکیک نیست: تسکی که خودمان لغو کردیم، یا
لغوِ **خودِ جاب** (`job_timeout`ِ ARQ / خاموشیِ ورکر). فرمِ قبلی هر دو را
می‌بلعید.

بدونِ ffmpeg اجرا می‌شوند — این‌ها دربارهٔ معناشناسیِ asyncio‌اند.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap

import pytest

from app import processing as P


async def _slow_to_cancel() -> None:
    """tickerی که لغوش لحظه‌ای طول می‌کشد — مثلِ وقتی وسطِ فراخوانیِ HTTP است."""
    try:
        await asyncio.sleep(100)
    except asyncio.CancelledError:
        await asyncio.sleep(0.3)      # درخواستِ در پرواز باز می‌شود
        raise


async def test_it_swallows_the_cancellation_it_caused_itself():
    """حالتِ عادی: بستنِ ticker نباید به فراخوان خطا بدهد."""
    ticker = asyncio.create_task(asyncio.sleep(100))
    await asyncio.sleep(0.05)
    await P.stop_task(ticker)         # نباید raise کند
    assert ticker.cancelled()


async def test_a_none_task_is_accepted():
    await P.stop_task(None)


async def test_a_broken_helper_task_does_not_break_the_job():
    async def boom():
        raise RuntimeError("ticker exploded")

    t = asyncio.create_task(boom())
    await asyncio.sleep(0.05)
    await P.stop_task(t)              # استثنای معمولی بلعیده می‌شود


async def test_the_job_cancellation_is_not_swallowed():
    """قلبِ ۲-۷: لغو **حین انتظار برای ticker** برسد و باید بالا برود.

    پیش از رفع، `RuntimeError`ِ کارِ اصلی برنده می‌شد و جاب لغو **نمی‌شد**.
    """
    async def job() -> str:
        ticker = asyncio.create_task(_slow_to_cancel())
        await asyncio.sleep(0.05)
        try:
            raise RuntimeError("op failed")
        finally:
            await P.stop_task(ticker)

    task = asyncio.create_task(job())
    await asyncio.sleep(0.12)         # حالا داخلِ `await ticker` هستیم
    task.cancel()                     # لغوِ سطحِ جاب دقیقاً همین‌جا می‌رسد
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled(), "لغوِ جاب بلعیده شد"


async def test_cancellation_during_the_work_itself_still_propagates():
    """حالتِ رایج (لغو وسطِ خودِ کار) نباید رگرسیون بدهد."""
    async def job() -> None:
        ticker = asyncio.create_task(asyncio.sleep(100))
        try:
            await asyncio.sleep(100)  # کارِ اصلی
        finally:
            await P.stop_task(ticker)

    task = asyncio.create_task(job())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def _caught_names(fn) -> set[str]:
    """نامِ هر استثنایی که در بدنهٔ این تابع `except` می‌شود.

    با AST خوانده می‌شود نه تطبیقِ رشته — نسخهٔ اولِ این تخت، **کامنتِ خودم** را
    که کلمهٔ `except BaseException` داشت می‌گرفت و مثبتِ کاذب می‌داد.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        parts = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
        for p in parts:
            if isinstance(p, ast.Name):
                names.add(p.id)
            elif isinstance(p, ast.Attribute):
                names.add(p.attr)
    return names


def test_neither_ticker_site_swallows_by_hand_any_more():
    """هر دو محل باید از تابعِ مشترک بروند، نه از except دست‌نویس."""
    from app import tasks, tasks_download

    op_src = inspect.getsource(tasks.run_op)
    assert "P.stop_task(ticker)" in op_src
    assert "CancelledError" not in _caught_names(tasks.run_op), \
        "run_op هنوز خودش CancelledError می‌گیرد"

    dl_src = inspect.getsource(tasks_download.run_download)
    assert "P.stop_task(ticker)" in dl_src
    assert "BaseException" not in _caught_names(tasks_download.run_download), \
        "_stop_ticker هنوز BaseException را می‌بلعد (شاملِ SystemExit)"
