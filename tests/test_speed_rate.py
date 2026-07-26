"""رگرسیونِ حلقهٔ بی‌نهایتِ `processing._atempo_chain`.

باگ: `while r < 0.5: parts.append(...); r /= 0.5` روی نرخِ منفی واگرا می‌شود و
روی `inf` هم `inf/2 = inf` است. چون تابع **همگام** است و قبل از هر `await` صدا
زده می‌شود، `job_timeout`ِ ARQ (که asyncio-محور است) نمی‌تواند شلیک کند: کلِ
پروسهٔ ورکر قفل می‌شود و `parts` تا OOM رشد می‌کند. `rate` هم از callbackِ کاربر
می‌آمد (`Spd.rate` رشتهٔ آزاد است) و `op_speed_pick` هیچ اعتبارسنجی‌ای نداشت.

هر فراخوانیِ خطرناک در یک **زیرفرایند** با مهلت اجرا می‌شود تا نبودِ گارد به‌جای
هنگ‌کردنِ کلِ suite یک failِ تمیز بدهد.
"""
from __future__ import annotations

import multiprocessing as mp

import pytest

from app import processing as P
from app.keyboards import AUDIO_SPEEDS

_TIMEOUT = 10.0


def _call_chain(rate: float, out) -> None:
    try:
        out.put(("ok", P._atempo_chain(rate)))
    except Exception as exc:  # noqa: BLE001
        out.put((type(exc).__name__, str(exc)))


def _chain_in_subprocess(rate: float):
    """`_atempo_chain(rate)` را با مهلت اجرا کن → (نامِ نتیجه, مقدار)."""
    # fork چون ماژول از قبل import شده است؛ spawn برای هر پارامتر کلِ app را
    # دوباره بار می‌کند و تست را ده‌ها ثانیه کند می‌کند.
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    proc = ctx.Process(target=_call_chain, args=(rate, q))
    proc.start()
    proc.join(_TIMEOUT)
    if proc.is_alive():
        proc.terminate()
        proc.join()
        pytest.fail(f"_atempo_chain({rate}) در {_TIMEOUT} ثانیه برنگشت — حلقهٔ بی‌نهایت")
    return q.get_nowait()


@pytest.mark.parametrize("rate", [0.0, -0.0, -1.0, -0.5, -100.0,
                                  float("inf"), float("-inf"), float("nan"),
                                  0.1, 0.24, 4.01, 1e9])
def test_invalid_rate_raises_instead_of_looping(rate):
    kind, msg = _chain_in_subprocess(rate)
    assert kind == "ValueError", f"انتظار ValueError بود، شد {kind}: {msg}"


@pytest.mark.parametrize("rate,expected", [
    (1.0, "atempo=1.0000"),
    (0.75, "atempo=0.7500"),
    (1.5, "atempo=1.5000"),
    (2.0, "atempo=2.0000"),
    (0.5, "atempo=0.5000"),
    (3.0, "atempo=2.0,atempo=1.5000"),
    (4.0, "atempo=2.0,atempo=2.0000"),
    (0.25, "atempo=0.5,atempo=0.5000"),
])
def test_valid_rates_still_build_the_right_chain(rate, expected):
    assert P._atempo_chain(rate) == expected


def test_every_offered_speed_is_accepted():
    """هر ضریبی که دکمه‌اش در ربات هست باید از گارد رد شود."""
    for raw in AUDIO_SPEEDS:
        assert P._atempo_chain(float(raw))


# ── گاردِ ورودی در `_do_op` ─────────────────────────────────────
def _call_do_op(rate: str, out) -> None:
    import asyncio

    from app import tasks
    from app.models import File

    file = File(ref="r", owner_id=1, file_unique_id="u", file_id="f",
                kind="audio", name="a.mp3", size=10, changelog=[])
    try:
        asyncio.run(tasks._do_op(None, "speed", {"rate": rate}, file,
                                 "/nonexistent/a.mp3", "/tmp", "fa"))
        out.put(("ok", ""))
    except Exception as exc:  # noqa: BLE001
        out.put((type(exc).__name__, str(exc)))


def _do_op_speed(rate: str):
    """`_do_op` را با مهلت و در زیرفرایند صدا بزن.

    زیرفرایند فقط برای شتاب نیست: قبل از رفع، `rate="-1"` همین‌جا کلِ پروسه را قفل
    می‌کرد — دقیقاً همان اتفاقی که در ورکر می‌افتاد. تستِ رگرسیون نباید بتواند
    کلِ suite را هنگ کند.
    """
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    proc = ctx.Process(target=_call_do_op, args=(rate, q))
    proc.start()
    proc.join(_TIMEOUT)
    if proc.is_alive():
        proc.terminate()
        proc.join()
        pytest.fail(f"_do_op(speed, rate={rate!r}) در {_TIMEOUT} ثانیه برنگشت")
    return q.get_nowait()


@pytest.mark.parametrize("rate", ["-1", "1e999", "0", "nan", "9999", "abc", "", "0.3"])
def test_do_op_rejects_rates_the_bot_never_offered(rate):
    kind, msg = _do_op_speed(rate)
    assert kind == "ValueError", f"انتظار ValueError بود، شد {kind}: {msg}"
    assert "unsupported speed rate" in msg


@pytest.mark.parametrize("rate", AUDIO_SPEEDS)
def test_do_op_accepts_offered_rates(rate):
    """ضریبِ معتبر نباید سرِ اعتبارسنجی رد شود؛ خطای بعدی مربوط به فایلِ نبودنی است."""
    kind, msg = _do_op_speed(rate)
    assert "unsupported speed rate" not in msg, f"{rate} باید پذیرفته شود ({kind})"
