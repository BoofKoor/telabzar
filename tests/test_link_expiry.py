"""فاز ۴ / موردِ ۳۰ — لینکِ عمومی منقضی/باطل شود.

پیش از رفع `dl_token` هرگز منقضی نمی‌شد و گیت‌وی مالک را نگاه نمی‌کرد: لینکی که
یک‌بار پخش شد برای همیشه کار می‌کرد، **حتی بعد از بلاک‌شدنِ مالک** — یعنی بلاک‌کردن
توزیعِ همان محتوایی را که دلیلِ بلاک بود متوقف نمی‌کرد.

گیت‌وی واقعی (aiohttp + SQLiteِ فایل‌محور)، و `op_link` با `CallbackQuery`ِ واقعیِ
aiogram روی `ValidatingBot`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from aiogram.types import CallbackQuery, Chat, Message, User as TgUser
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import gateway as G
from app.callbacks import Act
from app.crud import link_expired
from app.models import Base, File, User
from app.routers import ops
from tests.aiogram_double import ValidatingBot

NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'l.db'}")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(G, "Sessionmaker", maker)
    monkeypatch.setattr(G.settings, "dl_link_days", 30)
    G._meta_cache.clear()
    yield maker
    await eng.dispose()


async def _seed(maker, *, blocked=False, age_days: float | None = 1.0, token="tok123"):
    async with maker() as s:
        u = User(tg_user_id=900 + int(blocked), role="user", is_blocked=blocked)
        s.add(u)
        await s.flush()
        f = File(ref="ref1", owner_id=u.id, file_unique_id="u", file_id="F", kind="video",
                 name="clip.mp4", mime="video/mp4", dl_token=token,
                 dl_token_at=None if age_days is None else NOW - timedelta(days=age_days))
        s.add(f)
        await s.commit()
        return u, f


class _GBot:
    def __init__(self, path):
        self.path = path

        class _S:
            async def close(self):
                return None
        self.session = _S()

    async def get_file(self, _fid):
        return type("F", (), {"file_path": self.path})()


async def _status(tmp_path, token="tok123") -> int:
    p = tmp_path / "blob.mp4"
    p.write_bytes(b"\x00" * 32)
    app = G.build_app()
    app["bot"] = _GBot(str(p))
    async with TestClient(TestServer(app)) as client:
        r = await client.get(f"/s/{token}")
        await r.read()
        return r.status


async def test_a_fresh_link_is_served(db, tmp_path):
    """کنترل: لینکِ تازهٔ کاربرِ عادی کار می‌کند."""
    await _seed(db)
    assert await _status(tmp_path) == 200


async def test_a_blocked_owners_link_is_dead(db, tmp_path):
    await _seed(db, blocked=True)
    assert await _status(tmp_path) == 404, "لینکِ کاربرِ بلاک‌شده هنوز سرو می‌شود"


async def test_an_expired_link_is_dead(db, tmp_path):
    await _seed(db, age_days=31)
    assert await _status(tmp_path) == 404, "لینکِ ۳۱ روزه با عمرِ ۳۰ روز هنوز سرو می‌شود"


async def test_zero_days_means_never_expires(db, tmp_path, monkeypatch):
    monkeypatch.setattr(G.settings, "dl_link_days", 0)
    await _seed(db, age_days=3650)
    assert await _status(tmp_path) == 200


def test_link_expired_rules():
    assert link_expired(NOW - timedelta(days=31), 30, NOW) is True
    assert link_expired(NOW - timedelta(days=29), 30, NOW) is False
    assert link_expired(None, 30, NOW) is True        # ردیفی که از مسیرِ درست نگذشته
    assert link_expired(None, 0, NOW) is False        # ۰ = بی‌انقضا
    naive = (NOW - timedelta(days=1)).replace(tzinfo=None)   # شکلِ SQLite
    assert link_expired(naive, 30, NOW) is False


# ── op_link: توکنِ منقضی عوض می‌شود، تازه تمدید ────────────────────
def _cq(bot, data: str) -> CallbackQuery:
    msg = Message(message_id=7, date=NOW, chat=Chat(id=4242, type="private"),
                  caption="x").as_(bot)
    return CallbackQuery(id="cb1", from_user=TgUser(id=900, is_bot=False, first_name="u"),
                         chat_instance="ci", data=data, message=msg).as_(bot)


class _Bot(ValidatingBot):
    def _on(self, name, payload):
        return True


async def _op_link(maker, monkeypatch) -> File:
    async def base() -> str:
        return "https://dl.example"
    monkeypatch.setattr(ops, "_link_base", base)
    bot = _Bot()
    act = Act(op="link", ref="ref1")
    async with maker() as s:
        user = await s.get(User, 1)
        await ops.op_link(_cq(bot, act.pack()), act, s, "fa", user)
    async with maker() as s:
        return await s.get(File, 1)


async def test_asking_again_rotates_an_expired_token(db, monkeypatch):
    await _seed(db, age_days=31)
    f = await _op_link(db, monkeypatch)
    assert f.dl_token and f.dl_token != "tok123", "نشانیِ منقضی با تمدیدِ مالک دوباره زنده شد"
    assert not link_expired(f.dl_token_at, 30)


async def test_asking_again_keeps_and_refreshes_a_live_token(db, monkeypatch):
    await _seed(db, age_days=20)
    f = await _op_link(db, monkeypatch)
    assert f.dl_token == "tok123"
    at = f.dl_token_at if f.dl_token_at.tzinfo else f.dl_token_at.replace(tzinfo=timezone.utc)
    assert NOW - at < timedelta(minutes=5), "درخواستِ دوباره باید پنجره را تازه کند"


async def test_a_first_link_is_stamped(db, monkeypatch):
    await _seed(db, token=None, age_days=None)
    f = await _op_link(db, monkeypatch)
    assert f.dl_token and f.dl_token_at is not None
