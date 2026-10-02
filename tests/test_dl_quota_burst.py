"""فاز ۲ / موردِ ۷ — سقفِ روزانه و کول‌داونِ دانلود با درخواست‌های هم‌زمان.

تا این رفع، چک (`_precheck`، فقط‌خواندنی) و شارژ (`_charge`) دو گامِ جدا بودند
و بینشان چند `await` بود (DNS، فیلترِ محتوا، کش، پاسخ به کاربر). پس N درخواستِ
هم‌زمان همه از چک رد می‌شدند و بعد همه شارژ می‌شدند: سقفِ روزانهٔ ۲ با یک پیامِ
پنج‌لینکی پنج دانلود می‌داد و کول‌داون هیچ‌کدام را نمی‌گرفت.

درهم‌آمیزی **مجبور** می‌شود (§۶): در مسیرِ واقعیِ `on_dl_pick`، `get_cached` —
که بینِ چک و شارژِ قدیمی می‌نشست — روی یک `Barrier` منتظر می‌ماند، پس در نسخهٔ
پیش از رفع همهٔ درخواست‌ها **حتماً** پیش از اولین شارژ از چک رد شده‌اند.
"""
from __future__ import annotations

import asyncio
import ast
import inspect
import json
from datetime import datetime, timezone

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User as TgUser

from app.callbacks import Dl
from app.config import settings
from app.i18n import t
from app.routers import download as DR
from tests.aiogram_double import ValidatingBot

UID = 42


class FakeBot(ValidatingBot):
    def _on(self, name, payload):
        return True


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


@pytest.fixture
def limits(monkeypatch):
    def _set(count=0, cooldown=0, mb=0):
        monkeypatch.setattr(settings, "dl_daily_count", count)
        monkeypatch.setattr(settings, "dl_cooldown_sec", cooldown)
        monkeypatch.setattr(settings, "dl_daily_mb", mb)
    return _set


# ── سطحِ ۱: خودِ رزرو ─────────────────────────────────────────────────
async def test_concurrent_reservations_respect_the_daily_cap(redis, limits):
    limits(count=2)
    got = await asyncio.gather(*[DR._reserve(redis, UID, "fa") for _ in range(5)])
    assert got.count(None) == 2, got
    assert int(await redis.get(f"dlq:cnt:{UID}:{_today()}")) == 2, \
        "ردشده‌ها باید شارژشان برگردد"


async def test_concurrent_reservations_respect_the_cooldown(redis, limits):
    limits(cooldown=30)
    got = await asyncio.gather(*[DR._reserve(redis, UID, "fa") for _ in range(5)])
    assert got.count(None) == 1
    assert got.count(t("fa", "dl_cooldown")) == 4


async def test_a_daily_limit_rejection_does_not_leave_a_cooldown(redis, limits):
    limits(count=1, cooldown=30)
    assert await DR._reserve(redis, UID, "fa") is None
    await redis.delete(f"dlq:cd:{UID}")                   # کول‌داونِ اولی گذشت
    assert await DR._reserve(redis, UID, "fa") == t("fa", "dl_daily_limit")
    assert not await redis.exists(f"dlq:cd:{UID}")


async def test_unlimited_still_counts(redis, limits):
    """کنترل: سقفِ صفر یعنی بی‌سقف، ولی شمارش (برای آمار) مثلِ قبل ادامه دارد."""
    limits()
    for _ in range(4):
        assert await DR._reserve(redis, UID, "fa") is None
    assert int(await redis.get(f"dlq:cnt:{UID}:{_today()}")) == 4


# ── سطحِ ۲: on_dl_pickِ واقعی، درهم‌آمیزیِ اجباری ──────────────────────
def _cq(ref: str, bot) -> CallbackQuery:
    msg = Message(message_id=9, date=datetime.now(timezone.utc),
                  chat=Chat(id=4242, type="private"), text="menu").as_(bot)
    return CallbackQuery(id="cb1", from_user=TgUser(id=UID, is_bot=False, first_name="u"),
                         chat_instance="ci", data=f"dl:{ref}:720", message=msg).as_(bot)


@pytest.fixture
def picks(redis, monkeypatch):
    jobs: list[dict] = []

    async def _enqueue(name, payload, **kw):
        jobs.append(payload)
    monkeypatch.setattr(redis, "enqueue_job", _enqueue, raising=False)
    monkeypatch.setattr(settings, "dl_cache_enabled", True)

    async def _queue(pool, platform):
        return None
    monkeypatch.setattr(DR, "_dl_queue", _queue)

    async def run(n: int, cache=None, deliver_ok: bool = False):
        barrier = asyncio.Barrier(n)

        async def get_cached(session, url, sel):
            try:   # کران‌دار: بعد از رفع فقط برنده‌ها به این‌جا می‌رسند
                await asyncio.wait_for(barrier.wait(), 0.5)
            except (asyncio.TimeoutError, asyncio.BrokenBarrierError):
                pass
            return cache

        async def deliver(*a, **kw):
            return deliver_ok
        monkeypatch.setattr(DR.dl_cache, "get_cached", get_cached)
        monkeypatch.setattr(DR.dl_cache, "deliver_from_cache", deliver)
        bot = FakeBot()
        refs = [f"q{i}" for i in range(n)]
        for r in refs:
            await redis.set(f"dlctx:{r}", json.dumps(
                {"url": "https://youtu.be/abc", "platform": "youtube", "engine": "ytdlp",
                 "owner_id": 1, "tg_user_id": UID}))
        await asyncio.gather(*[
            DR.on_dl_pick(_cq(r, bot), Dl(ref=r, sel="720"), "fa", redis, None, None)
            for r in refs])
        return jobs
    return run


async def test_simultaneous_picks_cannot_exceed_the_daily_cap(redis, limits, picks):
    limits(count=2)
    jobs = await picks(5)
    assert len(jobs) == 2, f"سقفِ روزانهٔ ۲، ولی {len(jobs)} دانلود صف شد"


async def test_simultaneous_picks_cannot_skip_the_cooldown(redis, limits, picks):
    limits(cooldown=60)
    jobs = await picks(4)
    assert len(jobs) == 1, f"کول‌داون، ولی {len(jobs)} دانلود صف شد"


async def test_a_stale_cache_hit_is_charged_once(redis, limits, picks):
    """`file_id`ِ باطلِ کش → دانلودِ واقعی. پیش از رفع دو بار شارژ می‌شد."""
    limits()
    jobs = await picks(1, cache=object(), deliver_ok=False)
    assert len(jobs) == 1
    assert int(await redis.get(f"dlq:cnt:{UID}:{_today()}")) == 1


def test_the_link_and_pick_handlers_reserve_rather_than_check_then_charge():
    """گارد: کپیِ تازهٔ «چک، چند await، بعد شارژ» به روتر برنگردد."""
    for fn in (DR.on_link, DR.on_dl_pick):
        names = {n.func.id for n in ast.walk(ast.parse(inspect.getsource(fn).lstrip()))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "_charge" not in names, f"{fn.__name__} هنوز شارژِ جدا دارد"
    assert "_reserve" in inspect.getsource(DR.on_dl_pick)
    assert "_reserve" in inspect.getsource(DR.on_link)
