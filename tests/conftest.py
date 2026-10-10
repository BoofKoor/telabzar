"""پیکربندیِ مشترکِ تست‌ها.

`app.config.Settings` مقدارِ `BOT_TOKEN` را اجباری می‌خواند، پس **قبل از** هر
importی از `app` باید env ست شود؛ به همین دلیل این کار در سطحِ ماژول انجام
می‌شود نه داخلِ fixture.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

os.environ.setdefault("BOT_TOKEN", "0:test")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://t:t@127.0.0.1/t")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_runtest_setup(item: pytest.Item) -> None:
    """تستِ نشان‌دارِ `ffmpeg` بدونِ ffmpeg/ffprobe روی PATH رد می‌شود، نه fail."""
    if item.get_closest_marker("ffmpeg") and not (
            shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe on PATH لازم است")


@pytest.fixture
def redis():
    """Redisِ درون‌حافظه‌ای (fakeredis) — رفتارِ واقعیِ ZSET/TIME، بدونِ ماک."""
    import fakeredis.aioredis as fr
    return fr.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def dl_event_rows(monkeypatch):
    """نوشتنِ `download_events` در حافظه ضبط می‌شود، نه در Postgres.

    `run_download` در پایانِ هر جاب یک ردیف می‌نویسد. بدونِ این fixture هر تستی
    که آن را اجرا کند یک اتصالِ ردشده به `127.0.0.1:5432` می‌زد (DSNِ بالا) — بی‌خطر
    چون بلعیده می‌شود، ولی هم کُند و هم کور: هیچ تستی نمی‌توانست ببیند **چه چیزی**
    ثبت شد. حالا همان آرگومان‌هایی که به `DownloadEvent` می‌رسید در این فهرست است.
    """
    from app import dl_events

    rows: list[dict] = []

    async def _write(kw: dict) -> None:
        rows.append(dict(kw))

    monkeypatch.setattr(dl_events, "_write", _write)
    return rows


@pytest.fixture(autouse=True)
def history_rows(monkeypatch):
    """ثبتِ تاریخچه از مسیرهای تحویلِ دانلود (`history.record_safely`) در حافظه.

    همان استدلالِ `dl_event_rows`: آن تابع نشستِ **خودش** را باز می‌کند، پس بی این
    fixture هر تستِ `run_download` یک اتصالِ ردشده به Postgresِ ناموجود می‌زد —
    بی‌خطر چون بلعیده می‌شود، ولی کور. تستی که خودِ نوشتن در DB را می‌خواهد
    (`tests/test_history_data.py`) نسخهٔ اصلی را از `history._record_safely_real`
    برمی‌دارد.
    """
    from app import history

    rows: list[dict] = []

    async def _record(owner_id, infos, **kw):
        rows.append({"owner_id": owner_id, "infos": list(infos or []), **kw})
        return []

    monkeypatch.setattr(history, "record_safely", _record)
    return rows
