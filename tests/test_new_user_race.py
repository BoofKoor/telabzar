"""فاز ۲ / موردِ ۱۸ — ساختِ کاربرِ تازه با دو آپدیتِ هم‌زمان.

`get_or_create_user` یک check-then-act بود (`SELECT` بعد `INSERT`). اولین پیامِ
کاربرِ تازه اغلب با چند آپدیتِ هم‌زمان می‌رسد و aiogram آن‌ها را موازی هندل
می‌کند؛ هر دو `None` می‌دیدند و دومی روی ستونِ یکتای `tg_user_id` با
`IntegrityError` می‌مرد — یعنی همان پیامِ اولِ کاربر بی‌جواب.

درهم‌آمیزی **مجبور** می‌شود، نه اینکه منتظرش بمانیم (§۶): نشستی که تست به
تابع می‌دهد، درست بعد از اولین `SELECT`ش، ردیفِ «برنده» را از یک اتصالِ دیگر
درج می‌کند. پایگاه‌داده فایل‌محور است نه `:memory:`، چون آن یکی همهٔ نشست‌ها را
روی یک اتصال می‌برد و تعارضی نمی‌سازد (درسِ §۶).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import middlewares as MW
from app.models import Base, User

TG = 555


@pytest_asyncio.fixture
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'u.db'}")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


def _racing_session_cls(engine):
    class Racing(AsyncSession):
        """بعد از اولین SELECT، رقیب کاربر را می‌سازد — همان پنجرهٔ باگ."""
        raced = False

        async def execute(self, *a, **kw):
            res = await super().execute(*a, **kw)
            if not Racing.raced:
                Racing.raced = True
                async with AsyncSession(engine) as other:
                    other.add(User(tg_user_id=TG, role="user", lang="en"))
                    await other.commit()
            return res
    return Racing


async def _count(engine) -> int:
    async with AsyncSession(engine) as s:
        return (await s.execute(select(func.count()).select_from(User))).scalar_one()


async def test_a_concurrent_first_update_does_not_crash(engine):
    sm = async_sessionmaker(engine, class_=_racing_session_cls(engine),
                            expire_on_commit=False)
    async with sm() as session:
        user = await MW.get_or_create_user(session, SimpleNamespace(id=TG))
    assert user.tg_user_id == TG
    assert await _count(engine) == 1


async def test_the_loser_gets_the_winners_row(engine):
    """بازنده ردیفِ برنده را برمی‌گرداند (زبانِ ثبت‌شده‌اش حفظ می‌شود)، نه یک کپی."""
    sm = async_sessionmaker(engine, class_=_racing_session_cls(engine),
                            expire_on_commit=False)
    async with sm() as session:
        user = await MW.get_or_create_user(session, SimpleNamespace(id=TG))
    assert user.lang == "en"
    assert user.last_seen is not None


async def test_an_existing_user_is_read_not_duplicated(engine):
    """کنترل: مسیرِ عادی همان قبلی است."""
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        first = await MW.get_or_create_user(s, SimpleNamespace(id=TG))
    async with sm() as s:
        again = await MW.get_or_create_user(s, SimpleNamespace(id=TG))
    assert first.id == again.id
    assert await _count(engine) == 1


async def test_an_unrelated_integrity_error_is_not_hidden(engine, monkeypatch):
    """اگر بعد از تعارض هم ردیفی نبود، خطا بالا برود — نه یک کاربرِ None."""
    from sqlalchemy.exc import IntegrityError

    sm = async_sessionmaker(engine, expire_on_commit=False)

    async def boom(self):
        raise IntegrityError("x", {}, Exception("other constraint"))

    monkeypatch.setattr(AsyncSession, "commit", boom)
    async with sm() as s:
        with pytest.raises(IntegrityError):
            await MW.get_or_create_user(s, SimpleNamespace(id=TG))
