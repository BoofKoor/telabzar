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
