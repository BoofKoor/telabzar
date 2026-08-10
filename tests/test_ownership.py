"""فاز ۲الف — گاردِ مالکیت (۲-۱).

هیچ‌جای `routers/ops.py` مالکیت سنجیده نمی‌شد: ۴۱ فراخوانیِ `get_file_by_ref` فقط
`ref` را می‌گرفتند. `ref` هشت کاراکترِ تصادفی است پس حدس‌زدنی نیست، ولی `op_cancel_job`
شناسهٔ **ترتیبیِ** `Job.id` را می‌گرفت — آن یکی اصلاً حدس لازم نداشت.

تست‌ها روی DBِ واقعی (SQLite در حافظه) اجرا می‌شوند، نه ماک.
"""
from __future__ import annotations

import ast
import inspect

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import crud
from app.models import Base, File, Job, User


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def two_users(session):
    """آلیس صاحبِ فایل و جاب است؛ بابْ مهاجم."""
    alice, bob = User(tg_user_id=111, role="user"), User(tg_user_id=222, role="user")
    session.add_all([alice, bob])
    await session.flush()
    f = File(ref="AaBbCcDd", owner_id=alice.id, file_unique_id="u1", file_id="f1",
             name="secret.mp4", kind="video", size=10)
    session.add(f)
    await session.flush()
    job = Job(file_id=f.id, op="compress", status="running")
    session.add(job)
    await session.flush()
    return alice, bob, f, job


# ── فایل ────────────────────────────────────────────────────────
async def test_owner_gets_their_own_file(session, two_users):
    alice, _bob, f, _job = two_users
    got = await crud.get_file_by_ref(session, f.ref, alice)
    assert got is not None and got.id == f.id


async def test_another_user_cannot_touch_the_file(session, two_users):
    """قلبِ ۲-۱: بابْ با دانستنِ ref هم نباید چیزی بگیرد."""
    _alice, bob, f, _job = two_users
    assert await crud.get_file_by_ref(session, f.ref, bob) is None


async def test_no_user_is_denied_not_allowed(session, two_users):
    """جهتِ خطا عمدی است: نبودِ کاربر یعنی **رد**، نه «بدونِ بررسی»."""
    _alice, _bob, f, _job = two_users
    assert await crud.get_file_by_ref(session, f.ref, None) is None


async def test_unknown_ref_is_still_none(session, two_users):
    alice, _bob, _f, _job = two_users
    assert await crud.get_file_by_ref(session, "ZZZZZZZZ", alice) is None


# ── جاب (شناسهٔ ترتیبی) ─────────────────────────────────────────
async def test_owner_can_cancel_their_own_job(session, two_users):
    alice, _bob, _f, job = two_users
    assert await crud.get_owned_job(session, job.id, alice) is not None


async def test_another_user_cannot_cancel_the_job(session, two_users):
    """`Job.id` ترتیبی است، پس این‌جا مهاجم فقط می‌شمارد: ۱، ۲، ۳…"""
    _alice, bob, _f, job = two_users
    assert await crud.get_owned_job(session, job.id, bob) is None


async def test_job_lookup_denies_without_a_user(session, two_users):
    _alice, _bob, _f, job = two_users
    assert await crud.get_owned_job(session, job.id, None) is None


async def test_counting_job_ids_finds_nothing_for_a_stranger(session, two_users):
    """همان کاری که مهاجم واقعاً می‌کرد: پیمایشِ شناسه‌های کوچک."""
    _alice, bob, _f, _job = two_users
    assert [i for i in range(1, 25)
            if await crud.get_owned_job(session, i, bob) is not None] == []


# ── ساختاری: هیچ فراخوانی‌ای نباید گارد را دور بزند ─────────────
def _ops_calls() -> list[tuple[int, int]]:
    """(شمارهٔ خط, تعدادِ آرگومان) برای هر فراخوانیِ `get_file_by_ref` در ops.py."""
    from app.routers import ops
    tree = ast.parse(inspect.getsource(ops))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "get_file_by_ref":
            out.append((n.lineno, len(n.args)))
    return out


def test_every_ops_call_site_passes_a_user():
    """کشفِ خودکار — هندلرِ تازه‌ای که فردا اضافه شود هم باید گارد را پاس بدهد."""
    calls = _ops_calls()
    assert len(calls) >= 40, f"کشف شکست خورد، فقط {len(calls)} فراخوانی پیدا شد"
    bad = [ln for ln, argc in calls if argc < 3]
    assert not bad, f"این خط‌ها بدونِ user صدا می‌زنند: {bad}"


def test_the_guard_cannot_be_made_optional_by_accident():
    """`user` نباید مقدارِ پیش‌فرض بگیرد.

    اگر پیش‌فرضِ `None` داشته باشد، یک فراخوانیِ فراموش‌شده به‌جای خطا **بی‌صدا
    بدونِ بررسی** رد می‌شود — همان شکستِ خاموشی که این فاز برای بستنش است.
    """
    sig = inspect.signature(crud.get_file_by_ref)
    assert sig.parameters["user"].default is inspect.Parameter.empty
