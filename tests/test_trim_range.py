"""فاز ۳ / موردِ ۲۷ — برشِ بیرون از طولِ فایل خطاست، نه «فایلِ خالی».

ffmpeg روی `-ss`ِ بعد از پایانِ فایل با کدِ صفر خارج می‌شود و یک کانتینرِ
**بی‌محتوا** می‌نویسد (۲۶۲ بایت mp4، ۶۷۱ بایت mp3 — اندازه‌گیری‌شده)، پس
`os.path.exists` صادق بود و کاربر یک «فایلِ بریده» می‌گرفت که چیزی نداشت.

دو لایه، دو ادعای جدا (§۶ «هر دفاع در سطحی که خودش تصمیم می‌گیرد»):
روتر با مدتِ (صحیحِ) تلگرام زودتر و به زبانِ کاربر رد می‌کند و در همان FSM
می‌ماند؛ `processing` با مدتِ **اعشاریِ** ffprobe تورِ دقیق است برای وقتی که مدتِ
کارت نامعلوم است — تستِ لایهٔ دوم عمداً بدونِ روتر است.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import processing as P
from app.i18n import t
from app.models import Base, File, User
from app.routers import ops
from app.states import Trim
from tests.aiogram_double import ValidatingBot

needs_ffmpeg = pytest.mark.ffmpeg
CHAT = 4242


def _make(path, kind: str) -> str:
    if kind == "video":
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=3",
               "-f", "lavfi", "-i", "sine=duration=3", "-shortest",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)]
    else:
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=3",
               "-c:a", "libmp3lame", str(path)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    return str(path)


def _seconds(path) -> float:
    """مدتِ اعشاری با ffprobeِ خودِ تست — نه `P._media_seconds`، تا کنترل‌ها روی
    سورسِ پیش از رفع (که آن تابع را ندارد) هم دربارهٔ رفتار باشند نه نبودِ صفت."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    return float(out.strip())


TRIM = {"video": (P.trim_video, "mp4"), "audio": (P.trim_audio, "mp3")}


# ── لایهٔ ۲: processing، مستقل از روتر ──────────────────────────────────
@needs_ffmpeg
@pytest.mark.parametrize("where", ["at-end", "far-past"], ids=["at-end", "far-past"])
@pytest.mark.parametrize("kind", sorted(TRIM), ids=sorted(TRIM))
async def test_a_range_past_the_end_is_an_error(tmp_path, kind, where):
    """«at-end» = دقیقاً مدتِ اعشاریِ خودِ فایل (mp3ِ ۳ ثانیه‌ای با paddingِ lame
    ‏۳٫۰۳ است، پس `3.0` هنوز داخلِ فایل است و برشِ ۰٫۰۳ثانیه‌ایِ معتبر می‌دهد)."""
    fn, ext = TRIM[kind]
    src = _make(tmp_path / f"in.{ext}", kind)
    start = _seconds(src) if where == "at-end" else 100.0
    out = tmp_path / f"out.{ext}"
    with pytest.raises(RuntimeError, match="after the end"):
        await fn(src, str(out), start, start + 5)
    assert not out.exists(), "فایلِ خالی نباید ساخته شود"


@needs_ffmpeg
@pytest.mark.parametrize("kind", sorted(TRIM), ids=sorted(TRIM))
async def test_a_range_that_overruns_the_end_still_cuts_the_tail(tmp_path, kind):
    """کنترل: شروع داخلِ فایل و پایان بیرونش → تا آخرِ فایل بریده می‌شود، مثلِ قبل."""
    fn, ext = TRIM[kind]
    src = _make(tmp_path / f"in.{ext}", kind)
    out = tmp_path / f"out.{ext}"
    await fn(src, str(out), 1.0, 60.0)
    secs = _seconds(out)
    assert 1.5 < secs < 2.5, secs


# ── لایهٔ ۱: روتر ────────────────────────────────────────────────────────
class Bot(ValidatingBot):
    def _on(self, name, payload):
        return True


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    notes: list[str] = []
    jobs: list[dict] = []

    async def note(bot, chat, mid, file, lang, note=None, **kw):
        notes.append(note or "")

    async def enqueue(bot, pool, session, file, op, args, *a, **kw):
        jobs.append({"op": op, **args})

    async def no_limit(pool, uid):
        return None
    monkeypatch.setattr(ops, "set_card_note", note)
    monkeypatch.setattr(ops, "_enqueue", enqueue)
    monkeypatch.setattr(ops, "_check_limits", no_limit)
    async with maker() as session:
        user = User(tg_user_id=777, role="user")
        session.add(user)
        await session.flush()
        f = File(ref="TrimRng1", owner_id=user.id, file_unique_id="u", file_id="f",
                 name="clip.mp4", kind="video", size=10, duration=30)
        session.add(f)
        await session.flush()
        state = FSMContext(storage=MemoryStorage(),
                           key=StorageKey(bot_id=1, chat_id=CHAT, user_id=777))
        await state.set_state(Trim.waiting)
        await state.update_data(ref=f.ref, card_chat=CHAT, card_mid=9)
        yield session, user, f, state, notes, jobs
    await engine.dispose()


def _msg(text: str) -> Message:
    return Message(message_id=5, date=datetime.now(timezone.utc),
                   chat=Chat(id=CHAT, type="private"), text=text).as_(Bot())


async def test_the_router_refuses_a_range_past_the_card_duration(env):
    session, user, f, state, notes, jobs = env
    await ops.op_trim_recv(_msg("0:40-0:50"), state, session, "fa", None, user)
    assert not jobs, "جابِ محکوم‌به‌خالی صف شد"
    assert notes and notes[-1] == t("fa", "trim_past_end", dur="0:30"), notes
    assert await state.get_state() == Trim.waiting, "باید در همان FSM بماند تا بازهٔ دیگری بفرستد"


async def test_a_range_inside_the_file_is_still_queued(env):
    """کنترل."""
    session, user, f, state, notes, jobs = env
    await ops.op_trim_recv(_msg("0:10-0:45"), state, session, "fa", None, user)
    assert jobs == [{"op": "trim", "start": 10.0, "end": 45.0}]


async def test_an_unknown_duration_leaves_the_check_to_the_worker(env):
    """مدتِ نامعلوم → روتر رد نمی‌کند؛ لایهٔ دقیق در `processing` است."""
    session, user, f, state, notes, jobs = env
    f.duration = None
    await ops.op_trim_recv(_msg("0:40-0:50"), state, session, "fa", None, user)
    assert jobs and jobs[0]["start"] == 40.0


@pytest.mark.parametrize("text", ["0-inf", "0-1e999", "0-nan"],
                         ids=["inf", "overflow", "nan"])
def test_non_finite_times_are_not_a_range(text):
    """`nan` کنترل است — از قبل با `sec >= 0` رد می‌شد؛ `inf` و سرریز نه."""
    assert ops._parse_range(text) is None
