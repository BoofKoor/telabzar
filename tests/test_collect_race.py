"""فاز ۳ب / موردِ ۱ — رقابت در `collect_recv`.

چکِ سقفِ حجم روی `data`ی خوانده‌شده در بالای تابع کار می‌کرد، ولی افزودنِ عضو
داخلِ قفل بود. بینِ آن دو یک نقطهٔ yieldِ واقعی هست (`await _vjoin_cap_mb()`)،
پس دو آپلودِ هم‌زمانِ یک آلبوم — که aiogram موازی هندل می‌کند — هر دو از چک رد
می‌شدند و بعد هر دو append می‌کردند.

تست‌ها **قطعی‌اند، نه زمان‌محور**: با یک `asyncio.Barrier` وسطِ خواندنِ سقف،
هر دو هندلر دقیقاً در همان نقطه‌ای هم‌زمان می‌شوند که باگ در آن زندگی می‌کند.
پس شکستِ نسخهٔ پیش از رفع تصادفی نیست و روی ماشینِ کند/تندْ یکسان است.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, Video
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, File, User
from app.routers import ops
from tests.aiogram_double import ValidatingBot, bind_like_aiogram

CHAT_ID = 4242
CAP_MB = 10
HALF = 6 * 1024 * 1024          # دو تا از این‌ها از سقفِ ۱۰ مگابایتی رد می‌شود


class FakeBot(ValidatingBot):
    """فقط چیزی که این مسیر لازم دارد؛ ویرایش‌ها را برای بازرسی نگه می‌دارد.

    از `ValidatingBot` ارث می‌برد تا شکلِ فراخوانی با APIِ واقعی سنجیده شود؛
    نسخهٔ قبلی `*a, **kw` می‌گرفت و هر شکلی را می‌پذیرفت.
    """

    def __init__(self) -> None:
        self.captions: list[str] = []
        self.edit_error: Exception | None = None
        # اولین ویرایش را عقب می‌اندازد. این چیزی را «شبیه‌سازی» نمی‌کند؛ ابزارِ
        # تفکیک است: اگر ویرایش بیرونِ قفل باشد، ویرایشِ کُندِ اولی را بعدی‌ها
        # جا می‌زنند و کپشنِ **کهنه** آخر می‌نشیند. اگر داخلِ قفل باشد، ترتیب
        # ذاتاً سریالی است و این تأخیر هیچ اثری ندارد.
        self.delay_first = 0.0

    async def edit_message_caption(self, *a, **kw):
        payload = bind_like_aiogram("edit_message_caption", a, kw)
        if self.edit_error is not None:
            raise self.edit_error
        if self.delay_first and not self.captions:
            self.delay_first, pause = 0.0, self.delay_first
            await asyncio.sleep(pause)
        self.captions.append(payload.get("caption", ""))
        return True


def _video_message(bot: FakeBot, size: int, uid: str) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=CHAT_ID, type="private"),
        video=Video(file_id=f"vid-{uid}", file_unique_id=uid,
                    width=640, height=480, duration=5, file_size=size),
    ).as_(bot)


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        user = User(tg_user_id=777, role="user")
        session.add(user)
        await session.flush()
        f = File(ref="CollEct1", owner_id=user.id, file_unique_id="c0", file_id="c0",
                 name="base.mp4", kind="video", size=HALF)
        session.add(f)
        await session.flush()

        state = FSMContext(storage=MemoryStorage(),
                           key=StorageKey(bot_id=1, chat_id=CHAT_ID, user_id=user.tg_user_id))
        await state.update_data(purpose="vjoin", card_chat=CHAT_ID, card_mid=99, ref=f.ref,
                                members=[])
        yield session, user, f, state
    await engine.dispose()


async def _members(state: FSMContext) -> list[dict]:
    return list((await state.get_data()).get("members", []))


# ── قلبِ موردِ ۱ ────────────────────────────────────────────────────────────
async def test_two_concurrent_uploads_cannot_both_pass_the_cap(env, monkeypatch):
    """پیش از رفع: هر دو رد می‌شوند و مجموع از سقف می‌زند."""
    session, user, _f, state = env
    bot = FakeBot()

    # هر دو هندلر را دقیقاً در نقطهٔ خواندنِ سقف هم‌زمان کن — همان `await`ی که
    # در کدِ واقعی بینِ خواندنِ کهنه و گرفتنِ قفل قرار دارد.
    barrier = asyncio.Barrier(2)

    async def _capped() -> int:
        await barrier.wait()
        return CAP_MB

    monkeypatch.setattr(ops, "_vjoin_cap_mb", _capped)

    await asyncio.gather(
        ops.collect_recv(_video_message(bot, HALF, "a"), state, session, "fa", user),
        ops.collect_recv(_video_message(bot, HALF, "b"), state, session, "fa", user),
    )

    members = await _members(state)
    total = sum(m["size"] for m in members)
    assert total <= CAP_MB * 1024 * 1024, (
        f"سقف شکست: {len(members)} عضو، مجموع {total} بایت > {CAP_MB}MB")
    assert len(members) == 1, "فقط یکی از دو آپلود باید پذیرفته می‌شد"


async def test_the_rejected_upload_is_told_why(env, monkeypatch):
    """ردشدن باید هشدار بدهد، نه اینکه بی‌صدا بیفتد."""
    session, user, _f, state = env
    bot = FakeBot()
    barrier = asyncio.Barrier(2)

    async def _capped() -> int:
        await barrier.wait()
        return CAP_MB

    monkeypatch.setattr(ops, "_vjoin_cap_mb", _capped)
    await asyncio.gather(
        ops.collect_recv(_video_message(bot, HALF, "a"), state, session, "fa", user),
        ops.collect_recv(_video_message(bot, HALF, "b"), state, session, "fa", user),
    )
    assert any("۱۰" in c or "10" in c for c in bot.captions), \
        "کاربرِ ردشده باید پیامِ سقف را ببیند"


async def test_uploads_under_the_cap_all_land(env, monkeypatch):
    """کنترل: وقتی سقف اجازه می‌دهد، رقابت نباید چیزی را بیندازد."""
    session, user, _f, state = env
    bot = FakeBot()
    barrier = asyncio.Barrier(3)

    async def _capped() -> int:
        await barrier.wait()
        return 0          # ۰ = بی‌سقف

    monkeypatch.setattr(ops, "_vjoin_cap_mb", _capped)
    await asyncio.gather(*[
        ops.collect_recv(_video_message(bot, HALF, u), state, session, "fa", user)
        for u in ("a", "b", "c")
    ])
    members = await _members(state)
    assert len(members) == 3, f"هر سه باید ثبت می‌شدند، شد {len(members)}"
    assert len({m["name"] for m in members}) == 3, "نام‌ها نباید تکراری باشند"


# ── نکتهٔ (الف) اپراتور: مسیرِ خطای تلگرام ────────────────────────────────
async def test_a_failing_caption_edit_neither_breaks_collect_nor_holds_the_lock(env, monkeypatch):
    """۴۲۹/خطای ویرایش نباید عضو را از دست بدهد یا قفل را نگه دارد.

    `async with` قفل را در هر مسیری آزاد می‌کند، ولی چون ویرایشِ کپشن حالا
    **داخلِ** قفل است این باید صریحاً تست شود: اگر آزاد نمی‌شد، آپلودِ بعدی
    برای همیشه معلق می‌ماند و کلِ کالکتِ آن چت می‌مرد.
    """
    session, user, _f, state = env
    bot = FakeBot()

    async def _capped() -> int:
        return 0

    monkeypatch.setattr(ops, "_vjoin_cap_mb", _capped)

    bot.edit_error = RuntimeError("Telegram says 429")
    await ops.collect_recv(_video_message(bot, HALF, "a"), state, session, "fa", user)
    assert len(await _members(state)) == 1, "با وجودِ خطای ویرایش، عضو باید ثبت شود"

    # قفل باید آزاد شده باشد: آپلودِ بعدی نباید معلق بماند.
    bot.edit_error = None
    await asyncio.wait_for(
        ops.collect_recv(_video_message(bot, HALF, "b"), state, session, "fa", user),
        timeout=5)
    assert len(await _members(state)) == 2, "آپلودِ بعدی باید عادی ثبت شود"
    assert bot.captions, "بعد از رفعِ خطا، کارت باید دوباره به‌روز شود"


async def test_the_card_never_ends_on_a_stale_caption(env, monkeypatch):
    """باگِ دومِ هم‌ریشه: ویرایشِ بیرونِ قفل می‌توانست جابه‌جا تمام شود.

    با تأخیر روی **اولین** ویرایش، نسخهٔ پیش از رفع قطعاً می‌بازد: هندلرِ اول
    عضوِ خودش را ثبت می‌کند، قفل را رها می‌کند و وسطِ ویرایش معطل می‌ماند؛
    دو هندلرِ بعدی از او جلو می‌زنند و در پایان کپشنِ «۱ عضو» آخرین چیزی است
    که روی کارت می‌نشیند، در حالی که state سه عضو دارد. با ویرایشِ داخلِ قفل
    این ترتیب اصلاً ممکن نیست.
    """
    session, user, _f, state = env
    bot = FakeBot()
    bot.delay_first = 0.05
    barrier = asyncio.Barrier(3)

    async def _capped() -> int:
        await barrier.wait()
        return 0

    monkeypatch.setattr(ops, "_vjoin_cap_mb", _capped)
    await asyncio.gather(*[
        ops.collect_recv(_video_message(bot, HALF, u), state, session, "fa", user)
        for u in ("a", "b", "c")
    ])
    stored = len(await _members(state))
    assert stored == 3
    last = bot.captions[-1]
    assert str(stored) in last or "۳" in last, \
        f"کارت روی وضعیتِ کهنه ماند (state={stored} عضو): {last!r}"
