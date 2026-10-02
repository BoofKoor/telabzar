"""فاز ۲ / موردِ ۸ — شکستِ ارسال نباید «انجام شد» گزارش شود.

گاردِ سقفِ آپلود (`test_upload_ceiling.py`) فقط **حجم** را پیش از ارسال می‌بندد.
هر شکستِ دیگرِ ارسال — قطعیِ شبکه، ۴۰۰ِ تلگرام، سرورِ محلیِ از کار افتاده — در
سه شاخهٔ `run_op` فقط لاگ می‌شد:

    spawn    → job=done، برچسب در changelog، ردیفِ `files` با `file_id=""` یتیم
    files    → job=done حتی با صفر فایلِ رسیده
    message  → job=done بی‌آنکه فهرست برسد

و یک شکلِ چهارم با دو رو: `move_card_below` (آرایشِ چت **بعد از** تحویلِ
موفق). در شاخهٔ `send_media` داخلِ همان `try`ِ ارسال بود، پس شکستش جابی را که
خروجی‌اش **رسیده بود** `failed` می‌خواند؛ در `files`/`message` بی‌گارد بود و
خطا از شاخهٔ `else` بیرون می‌زد — `finally` جاب را با وضعیتِ **`running`**
commit می‌کرد و استثنا از `run_op` بالا می‌رفت (اجراشده روی سورسِ پیش از رفع).

هارنس همان `run_op`ِ واقعی و DBِ واقعیِ `test_upload_ceiling` است؛ فقط بات در
متدهای نام‌برده خطا می‌دهد.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func as sqfunc
from sqlalchemy import select

from app import tasks as T
from app.models import File, Job
from tests.test_upload_ceiling import (  # noqa: F401 — `env` یک fixture است
    CARD_MID, CHAT, SHAPES, UNDER_MB, Bot, _install_result, env)


class FailingBot(Bot):
    """همان باتِ ضبط‌کننده، ولی متدهای `fail_on` قطعیِ شبکه را بازی می‌کنند."""

    def __init__(self, fail_on: set[str]) -> None:
        super().__init__()
        self.fail_on = fail_on
        self.calls: list[str] = []

    def _on(self, name: str, payload: dict):
        self.calls.append(name)
        if name in self.fail_on:
            raise RuntimeError(f"network down during {name}")
        return super()._on(name, payload)


MORE = {**SHAPES, "message": lambda out: {"message": "archive listing", "label": "L"}}


async def _run(env, monkeypatch, shape: str, fail_on: set[str]):
    maker, (job_id, file_id) = env
    _install_result(monkeypatch, MORE[shape], UNDER_MB)
    bot = FailingBot(fail_on)
    await T.run_op({"bot": bot, "redis": None}, job_id, CHAT, CARD_MID, "fa")
    async with maker() as s:
        job = await s.get(Job, job_id)
        file = await s.get(File, file_id)
        rows = (await s.execute(select(sqfunc.count()).select_from(File))).scalar()
    return bot, job, file, rows


# شاخه → متدی که خروجی را حمل می‌کند (کارتِ spawn صوتی است → send_audio)
CARRIER = {"spawn": "send_audio", "files": "send_document", "message": "send_message"}


@pytest.mark.parametrize("shape", sorted(CARRIER), ids=sorted(CARRIER))
async def test_a_failed_send_is_a_failed_job(env, monkeypatch, shape):
    _bot, job, _file, _rows = await _run(env, monkeypatch, shape, {CARRIER[shape]})
    assert job.status == "failed", f"{shape}: ارسال شکست خورد ولی جاب {job.status} شد"
    assert "network down" in (job.error or ""), f"علت ثبت نشد: {job.error!r}"


@pytest.mark.parametrize("shape", sorted(CARRIER), ids=sorted(CARRIER))
async def test_a_failed_send_claims_nothing_in_the_changelog(env, monkeypatch, shape):
    _bot, _job, file, _rows = await _run(env, monkeypatch, shape, {CARRIER[shape]})
    assert file.changelog == [], f"changelog ادعای کاذب دارد: {file.changelog}"


async def test_a_failed_spawn_leaves_no_orphan_row(env, monkeypatch):
    _bot, _job, _file, rows = await _run(env, monkeypatch, "spawn", {"send_audio"})
    assert rows == 1, f"{rows} ردیف در files — کارتِ نرسیده یتیم جا گذاشت"


async def test_the_user_sees_the_failure_on_the_card(env, monkeypatch):
    bot, _job, _file, _rows = await _run(env, monkeypatch, "files", {"send_document"})
    from app.i18n import t
    assert bot.captions and t("fa", "failed") in bot.captions[-1]


# شاخه → متدی که خودِ خروجی را می‌برد (باید موفق باشد تا ادعا معنا داشته باشد)
DELIVERED_BY = {"send_media": "send_animation", "files": "send_document",
                "message": "send_message"}


@pytest.mark.parametrize("shape", sorted(DELIVERED_BY), ids=sorted(DELIVERED_BY))
async def test_a_card_move_failure_after_delivery_is_still_done(env, monkeypatch, shape):
    """خروجی رسید، فقط جابه‌جاییِ کارت شکست خورد → `done`، و کارت درجا به‌روز شد.

    کارتِ ویدیو با `file_id` فرستاده می‌شود (`send_video`) و خودِ خروجی با متدِ
    دیگری رفته — پس خطای `send_video` فقط آرایشِ چت را می‌زند.
    """
    bot, job, file, _rows = await _run(env, monkeypatch, shape, {"send_video"})
    assert DELIVERED_BY[shape] in bot.calls, "پیش‌شرط: خودِ خروجی باید رسیده باشد"
    assert job.status == "done", f"جاب {job.status} ماند"
    assert file.changelog == ["L"]
    assert bot.captions, "کارتِ قدیمی باید درجا منو بگیرد"


@pytest.mark.parametrize("shape", sorted(MORE), ids=sorted(MORE))
async def test_a_clean_delivery_is_still_done(env, monkeypatch, shape):
    """کنترل: بدونِ هیچ خطایی هر پنج شکل مثلِ قبل `done` می‌شوند."""
    _bot, job, file, rows = await _run(env, monkeypatch, shape, set())
    assert job.status == "done"
    assert file.changelog == ["L"]
    assert rows == (2 if shape == "spawn" else 1)
