"""تاریخچهٔ فایل‌ها — نما و کنش‌ها (`app/routers/history.py`)، از مسیرِ **واقعیِ** هندلرها.

هندلرها با `Message`/`CallbackQuery`ِ واقعیِ aiogram رانده می‌شوند و بات
`ValidatingBot` است، پس هر فراخوانی (ارسالِ کارت، آلبوم، ویرایشِ پیام، پاسخِ دکمه)
همان اعتبارسنجیِ pydanticِ تولید را می‌خورد — درسِ §۶ بندِ ۴.

پنج ادعای اصلی:
1. **دوباره‌فرستادن با `file_id` است**: هیچ `FSInputFile`ی روی سیم نمی‌رود.
2. **هر دکمه مالکیت را از نو می‌سنجد**: callbackِ کاربرِ دیگر به فایلِ من نمی‌رسد.
3. **عددِ روی دکمهٔ دسته همان تعدادِ فهرست است**، و هیچ دسته‌ی خالی‌ای دکمه نمی‌گیرد.
4. **جست‌وجو لینک و دستور را نمی‌بلعد**: لینکی که وسطِ جست‌وجو فرستاده شود باید به
   دانلود برسد (`SkipHandler`)، نه اینکه «جست‌وجو» شود.
5. **هر callback زیرِ ۶۴ بایت است** — در بدترین ترکیب (توکنِ جست‌وجو + گروه + صفحه).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio
from aiogram import methods
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, FSInputFile, Message, User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import history as H
from app.callbacks import Hist, Nav
from app.i18n import t
from app.models import Base, File, FileVersion, User
from app.routers import history as R
from app.routers.start import navigate
from app.states import HistorySearch

from tests.aiogram_double import ValidatingBot

CHAT = 4242
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class RecordingBot(ValidatingBot):
    """هر فراخوانی را بعد از اعتبارسنجی نگه می‌دارد. `fail` = متدهایی که خطا می‌دهند."""

    def __init__(self, fail: dict[str, Exception] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail or {}

    def _on(self, name: str, payload: dict[str, Any]) -> Any:
        self.calls.append((name, payload))
        if name in self.fail:
            raise self.fail[name]
        return True

    def names(self) -> list[str]:
        return [n for n, _p in self.calls]

    def last(self, name: str) -> dict[str, Any]:
        for n, p in reversed(self.calls):
            if n == name:
                return p
        raise AssertionError(f"هیچ {name}ی ثبت نشد؛ ثبت‌شده‌ها: {self.names()}")

    def buttons(self, name: str = "edit_message_text") -> list[tuple[str, str]]:
        kb = self.last(name).get("reply_markup")
        if kb is None:
            return []
        rows = kb["inline_keyboard"] if isinstance(kb, dict) else kb.inline_keyboard
        return [((b["text"], b["callback_data"]) if isinstance(b, dict)
                 else (b.text, b.callback_data)) for row in rows for b in row]

    def alert(self) -> dict[str, Any]:
        return self.last("answer_callback_query")

    def sends(self) -> list[tuple[str, dict[str, Any]]]:
        return [(n, p) for n, p in self.calls
                if n.startswith("send_") and n != "send_message"]


# ── هارنس ────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ui.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    mk = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with mk() as s:
        me, other = User(tg_user_id=42, role="user"), User(tg_user_id=43, role="user")
        s.add_all([me, other])
        await s.commit()
    yield mk
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db):
    async with db() as s:
        yield s


@pytest_asyncio.fixture
async def me(session):
    return (await session.execute(select(User).where(User.tg_user_id == 42))).scalar_one()


@pytest_asyncio.fixture
async def other(session):
    return (await session.execute(select(User).where(User.tg_user_id == 43))).scalar_one()


@pytest.fixture
def state():
    return FSMContext(storage=MemoryStorage(),
                      key=StorageKey(bot_id=1, chat_id=CHAT, user_id=42))


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


_n = 0


def _file(owner: User, **kw) -> File:
    global _n
    _n += 1
    kw.setdefault("ref", f"R{_n:07d}")
    kw.setdefault("file_unique_id", f"U{_n}")
    kw.setdefault("file_id", f"FID{_n}")
    kw.setdefault("kind", "video")
    kw.setdefault("name", f"clip{_n}.mp4")
    kw.setdefault("size", 1000 * _n)
    kw.setdefault("changelog", [])
    kw.setdefault("created_at", T0 + timedelta(minutes=_n))
    return File(owner_id=owner.id, **kw)


async def _add(session, *rows) -> list[File]:
    session.add_all(rows)
    await session.commit()
    return list(rows)


def _msg(bot, text: str = "x", user_id: int = 42) -> Message:
    return Message(message_id=7, date=datetime.now(timezone.utc),
                   chat=Chat(id=CHAT, type="private"), text=text,
                   from_user=TgUser(id=user_id, is_bot=False, first_name="u")).as_(bot)


def _cq(bot, data: str, user_id: int = 42) -> CallbackQuery:
    return CallbackQuery(id="cb1", from_user=TgUser(id=user_id, is_bot=False, first_name="u"),
                         chat_instance="ci", data=data, message=_msg(bot)).as_(bot)


async def press(bot, data: str, session, user, state, redis=None, lang: str = "fa"):
    """یک دکمه — همان مسیری که روتر می‌رود: `Hist.unpack` و بعد هندلر."""
    await R.on_history(_cq(bot, data, user.tg_user_id), Hist.unpack(data), session, user,
                       lang, state, redis)


def _carries_bytes(payload: dict) -> bool:
    for v in payload.values():
        if isinstance(v, FSInputFile) or isinstance(getattr(v, "media", None), FSInputFile):
            return True
        if isinstance(v, list) and any(isinstance(getattr(x, "media", None), FSInputFile)
                                       for x in v):
            return True
    return False


# ══ ۱) ورود: منوی خانه و `/history` ═══════════════════════════════

async def test_the_home_button_opens_the_overview(session, me):
    await _add(session, _file(me), _file(me, kind="image", name="a.jpg"))
    bot = RecordingBot()
    await navigate(_cq(bot, "nv:history"), Nav(to="history"), me, "fa", session)
    text = bot.last("edit_message_text")["text"]
    assert t("fa", "hist_title") in text
    cbs = [cb for _t, cb in bot.buttons()]
    assert Hist(v="l", c="a").pack() in cbs and Hist(v="l", c="v").pack() in cbs
    assert Hist(v="l", c="i").pack() in cbs
    assert Nav(to="home").pack() in cbs, "بازگشت به خانه نیست"


async def test_an_empty_history_says_so_and_offers_only_the_way_back(session, me):
    bot = RecordingBot()
    await navigate(_cq(bot, "nv:history"), Nav(to="history"), me, "fa", session)
    assert bot.last("edit_message_text")["text"] == t("fa", "hist_empty")
    assert [cb for _t, cb in bot.buttons()] == [Nav(to="home").pack()]


async def test_the_history_command_answers_with_the_overview(session, me, state):
    await _add(session, _file(me))
    bot = RecordingBot()
    await R.cmd_history(_msg(bot, "/history"), CommandObject(prefix="/", command="history"),
                        session, me, "fa", state, None)
    assert t("fa", "hist_title") in bot.last("send_message")["text"]


async def test_only_non_empty_categories_get_a_button_and_counts_match_lists(
        session, me, state, redis):
    """عددِ روی هر دکمه = تعدادِ موردی که بازکردنش نشان می‌دهد؛ دستهٔ خالی دکمه ندارد."""
    await _add(session,
               _file(me, kind="video"), _file(me, kind="video"),
               _file(me, kind="pdf", name="a.pdf"),
               _file(me, kind="image", group_ref="gUIUIUIUIUIU", source="dl", platform="instagram"),
               _file(me, kind="image", group_ref="gUIUIUIUIUIU", source="dl", platform="instagram"))
    bot = RecordingBot()
    await press(bot, Hist(v="o").pack(), session, me, state, redis)
    cats = [(txt, cb) for txt, cb in bot.buttons() if cb.startswith("hs:l:")]
    codes = [Hist.unpack(cb).c for _t, cb in cats]
    assert set(codes) == {"a", "v", "p", "i", "g", "l"}, f"دکمه‌ها: {codes}"
    assert "u" not in codes and "z" not in codes, "دستهٔ خالی دکمه گرفت"
    for txt, cb in cats:
        b2 = RecordingBot()
        await press(b2, cb, session, me, state, redis)
        entries = [x for x in b2.buttons() if x[1].startswith(("hs:d:", "hs:g:"))]
        assert txt.endswith(R.F_.num(len(entries), "fa")), f"{txt} ولی فهرست {len(entries)} مورد"


# ══ ۲) فهرست و صفحه‌بندی ════════════════════════════════════════════

async def test_a_long_list_pages_and_the_back_button_keeps_the_page(session, me, state):
    await _add(session, *[_file(me) for _ in range(H.PAGE_SIZE + 3)])
    bot = RecordingBot()
    await press(bot, Hist(v="l", c="a", p=2).pack(), session, me, state)
    entries = [cb for _t, cb in bot.buttons() if cb.startswith("hs:d:")]
    assert len(entries) == 3
    detail = Hist.unpack(entries[0])
    assert detail.p == 2, "دکمهٔ مورد صفحه را نمی‌برد؛ «بازگشت» به صفحهٔ ۱ می‌پرید"
    await press(bot, entries[0], session, me, state)
    back = [cb for txt, cb in bot.buttons() if txt == t("fa", "btn_back")]
    assert back == [Hist(v="l", c="a", p=2).pack()]


async def test_a_stale_page_number_lands_on_the_last_page(session, me, state):
    await _add(session, *[_file(me) for _ in range(3)])
    bot = RecordingBot()
    await press(bot, Hist(v="l", c="a", p=9).pack(), session, me, state)
    assert len([cb for _t, cb in bot.buttons() if cb.startswith("hs:d:")]) == 3


# ══ ۳) فرستادنِ دوباره ═════════════════════════════════════════════

async def test_send_again_uses_the_file_id_and_uploads_no_bytes(session, me, state):
    (f,) = await _add(session, _file(me, kind="video", file_id="VIDEOFID"))
    bot = RecordingBot()
    await press(bot, Hist(v="ss", r=f.ref).pack(), session, me, state)
    sends = bot.sends()
    assert [n for n, _p in sends] == ["send_video"]
    assert sends[0][1]["video"] == "VIDEOFID"
    assert not any(_carries_bytes(p) for _n, p in sends), "بایت روی سیم رفت"
    assert bot.alert().get("text") == t("fa", "hist_sent")


async def test_a_failed_resend_tells_the_user(session, me, state):
    (f,) = await _add(session, _file(me, kind="document", name="a.bin"))
    bot = RecordingBot(fail={"send_document": RuntimeError("file is gone")})
    await press(bot, Hist(v="ss", r=f.ref).pack(), session, me, state)
    assert bot.alert().get("text") == t("fa", "hist_send_failed")
    assert bot.alert().get("show_alert") is True


# ══ ۴) مالکیت ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("v", ["d", "ss", "s1", "x", "xy", "vl", "sm"],
                         ids=["d", "ss", "s1", "x", "xy", "vl", "sm"])
async def test_another_users_callback_never_reaches_my_file(session, me, other, state, v):
    (f,) = await _add(session, _file(me))
    bot = RecordingBot()
    await press(bot, Hist(v=v, r=f.ref).pack(), session, other, state)
    assert bot.sends() == [], "فایلِ کاربرِ دیگر فرستاده شد"
    assert bot.alert().get("text") == t("fa", "hist_missing")
    await session.refresh(f)
    assert f.starred_at is None and f.hidden_at is None, "کنشِ کاربرِ دیگر روی فایلِ من نشست"


@pytest.mark.parametrize("v", ["g", "sa", "g1", "gx", "gxy"], ids=["g", "sa", "g1", "gx", "gxy"])
async def test_another_users_callback_never_reaches_my_group(session, me, other, state, v):
    rows = await _add(session, _file(me, group_ref="gMINEMINEMIN"),
                      _file(me, group_ref="gMINEMINEMIN"))
    bot = RecordingBot()
    await press(bot, Hist(v=v, r="gMINEMINEMIN").pack(), session, other, state)
    assert bot.sends() == [] and "send_media_group" not in bot.names()
    assert bot.alert().get("text") == t("fa", "hist_missing")
    for f in rows:
        await session.refresh(f)
        assert f.starred_at is None and f.hidden_at is None


async def test_restoring_another_users_version_is_refused(session, me, other, state):
    (f,) = await _add(session, _file(me))
    session.add(FileVersion(parent_id=f.id, file_id="ORIG", kind="video", name="o.mp4"))
    await session.commit()
    vid = (await session.execute(select(FileVersion.id))).scalar_one()
    bot = RecordingBot()
    await press(bot, Hist(v="vr", r=str(vid)).pack(), session, other, state)
    assert bot.sends() == []
    assert bot.alert().get("text") == t("fa", "hist_missing")


# ══ ۵) نشان و حذف ═══════════════════════════════════════════════════

async def test_starring_flips_the_button_and_shows_in_the_list(session, me, state):
    (f,) = await _add(session, _file(me, name="star.mp4"))
    bot = RecordingBot()
    await press(bot, Hist(v="s1", r=f.ref).pack(), session, me, state)
    labels = [txt for txt, _cb in bot.buttons()]
    assert t("fa", "hist_btn_unstar") in labels and t("fa", "hist_btn_star") not in labels
    await press(bot, Hist(v="l", c="s").pack(), session, me, state)
    assert any(txt.startswith("⭐") for txt, cb in bot.buttons() if cb.startswith("hs:d:"))


async def test_the_detail_page_agrees_with_the_list_about_the_star(session, me, state):
    """نشان روی ردیفِ قدیمیِ همان فایل، و ردیفِ تازهٔ تکراری بی‌نشان: فهرست ⭐
    نشان می‌دهد، پس صفحهٔ همان مورد هم باید «برداشتنِ نشان» بگوید نه «نشان کن»."""
    await _add(session, _file(me, file_unique_id="SAME", starred_at=T0))
    (newer,) = await _add(session, _file(me, file_unique_id="SAME"))
    bot = RecordingBot()
    await press(bot, Hist(v="l", c="a").pack(), session, me, state)
    (label,) = [txt for txt, cb in bot.buttons() if cb.startswith("hs:d:")]
    assert label.startswith("⭐")
    await press(bot, Hist(v="d", r=newer.ref).pack(), session, me, state)
    labels = [txt for txt, _cb in bot.buttons()]
    assert t("fa", "hist_btn_unstar") in labels, "فهرست ⭐ دارد ولی صفحهٔ مورد «نشان کن» می‌گوید"


async def test_hide_asks_first_then_removes_only_from_history(session, me, state):
    (f,) = await _add(session, _file(me))
    bot = RecordingBot()
    await press(bot, Hist(v="x", r=f.ref).pack(), session, me, state)
    assert bot.last("edit_message_text")["text"] == t("fa", "hist_confirm_hide")
    await session.refresh(f)
    assert f.hidden_at is None, "پرسش هنوز حذف نکرده"
    await press(bot, Hist(v="xy", r=f.ref).pack(), session, me, state)
    await session.refresh(f)
    assert f.hidden_at is not None
    assert bot.alert().get("text") == t("fa", "hist_hidden")
    assert t("fa", "hist_list_empty", title=t("fa", "hist_cat_all")) == \
        bot.last("edit_message_text")["text"]


async def test_clear_all_asks_first(session, me, state):
    await _add(session, _file(me), _file(me))
    bot = RecordingBot()
    await press(bot, Hist(v="c").pack(), session, me, state)
    assert bot.last("edit_message_text")["text"] == t("fa", "hist_confirm_clear")
    assert (await H.overview(session, me.id)).counts[H.CAT_ALL] == 2
    await press(bot, Hist(v="cy").pack(), session, me, state)
    assert bot.last("edit_message_text")["text"] == t("fa", "hist_empty")


# ══ ۶) گروه ═════════════════════════════════════════════════════════

async def _album(session, me, *, source="dl", n=3, caption="سلام <b>دنیا</b>"):
    kinds = ["image", "image", "video", "image"] * 4
    rows = [_file(me, group_ref="gALBUMALBUMA", source=source, kind=kinds[i],
                  platform="instagram" if source == "dl" else None, post_caption=caption,
                  file_id=f"AF{i}") for i in range(n)]
    return await _add(session, *rows)


async def test_send_all_rebuilds_the_album_with_the_right_media_types(session, me, state):
    await _album(session, me)
    bot = RecordingBot()
    await press(bot, Hist(v="sa", r="gALBUMALBUMA").pack(), session, me, state)
    p = bot.last("send_media_group")
    media = p["media"]
    assert [type(x).__name__ for x in media] == ["InputMediaPhoto", "InputMediaPhoto",
                                                 "InputMediaVideo"]
    assert [x.media for x in media] == ["AF0", "AF1", "AF2"]
    assert media[0].caption == "سلام &lt;b&gt;دنیا&lt;/b&gt;", "کپشنِ خام escape نشد"
    assert media[1].caption is None and media[2].caption is None
    assert not _carries_bytes(p)


async def test_an_op_output_group_goes_back_as_documents(session, me, state):
    """خروجیِ چندفایلیِ یک عملیات سند رفته؛ `file_id`ِ سند در آلبومِ عکس رد می‌شود."""
    await _album(session, me, source="op", caption=None)
    bot = RecordingBot()
    await press(bot, Hist(v="sa", r="gALBUMALBUMA").pack(), session, me, state)
    media = bot.last("send_media_group")["media"]
    assert {type(x).__name__ for x in media} == {"InputMediaDocument"}


async def test_a_rejected_album_falls_back_to_one_card_each(session, me, state):
    await _album(session, me)
    err = TelegramBadRequest(method=methods.SendMessage(chat_id=1, text="x"),
                             message="Bad Request: wrong file identifier")
    bot = RecordingBot(fail={"send_media_group": err})
    await press(bot, Hist(v="sa", r="gALBUMALBUMA").pack(), session, me, state)
    assert [n for n, _p in bot.sends() if n != "send_media_group"] == [
        "send_photo", "send_photo", "send_video"]
    assert bot.alert().get("text") == t("fa", "hist_sent")


async def test_group_star_and_hide_act_on_every_member(session, me, state):
    rows = await _album(session, me)
    bot = RecordingBot()
    await press(bot, Hist(v="g1", r="gALBUMALBUMA").pack(), session, me, state)
    for f in rows:
        await session.refresh(f)
    assert all(f.starred_at is not None for f in rows)
    assert t("fa", "hist_btn_unstar") in [txt for txt, _cb in bot.buttons()]
    await press(bot, Hist(v="gxy", r="gALBUMALBUMA").pack(), session, me, state)
    for f in rows:
        await session.refresh(f)
    assert all(f.hidden_at is not None for f in rows)


async def test_a_big_group_pages_its_members(session, me, state):
    await _album(session, me, n=H.GROUP_PAGE_SIZE + 2)
    bot = RecordingBot()
    await press(bot, Hist(v="g", r="gALBUMALBUMA").pack(), session, me, state)
    members = [cb for _t, cb in bot.buttons() if cb.startswith("hs:sm:")]
    assert len(members) == H.GROUP_PAGE_SIZE
    nxt = [cb for txt, cb in bot.buttons() if txt == t("fa", "hist_btn_next")]
    await press(bot, nxt[0], session, me, state)
    assert len([cb for _t, cb in bot.buttons() if cb.startswith("hs:sm:")]) == 2


async def test_one_member_is_sent_as_its_own_card(session, me, state):
    rows = await _album(session, me)
    bot = RecordingBot()
    await press(bot, Hist(v="sm", r=rows[2].ref).pack(), session, me, state)
    assert [n for n, _p in bot.sends()] == ["send_video"]
    assert bot.sends()[0][1]["video"] == "AF2"


# ══ ۷) نسخه‌ها ═══════════════════════════════════════════════════════

async def test_a_previous_version_comes_back_as_a_new_card(session, me, state):
    (f,) = await _add(session, _file(me, file_id="CUT", name="cut.mp4", changelog=["✂️"]))
    session.add(H.version_row(f.id, file_id="ORIGFID", file_unique_id="UO", kind="video",
                              mime="video/mp4", name="orig.mp4", size=10, width=None,
                              height=None, duration=None, changelog=[]))
    await session.commit()
    bot = RecordingBot()
    await press(bot, Hist(v="d", r=f.ref).pack(), session, me, state)
    vl = [cb for _t, cb in bot.buttons() if cb.startswith("hs:vl:")]
    assert vl, "دکمهٔ «نسخه‌های قبلی» نیامد"
    await press(bot, vl[0], session, me, state)
    (vr,) = [cb for txt, cb in bot.buttons() if cb.startswith("hs:vr:")]
    await press(bot, vr, session, me, state)
    assert [(n, p["video"]) for n, p in bot.sends()] == [("send_video", "ORIGFID")]
    rows = (await session.execute(select(File).where(File.file_id == "ORIGFID"))).scalars().all()
    assert len(rows) == 1 and rows[0].source == "op" and rows[0].ref != f.ref


async def test_a_restore_that_cannot_be_sent_leaves_no_row(session, me, state):
    (f,) = await _add(session, _file(me))
    session.add(FileVersion(parent_id=f.id, file_id="GONE", kind="video", name="o.mp4"))
    await session.commit()
    vid = (await session.execute(select(FileVersion.id))).scalar_one()
    bot = RecordingBot(fail={"send_video": RuntimeError("gone"),
                             "send_document": RuntimeError("gone")})
    await press(bot, Hist(v="vr", r=str(vid)).pack(), session, me, state)
    assert bot.alert().get("text") == t("fa", "hist_send_failed")
    left = (await session.execute(select(File).where(File.file_id == "GONE"))).scalars().all()
    assert left == [], "ردیفِ نسخه‌ای که نرسید در تاریخچه ماند"


# ══ ۸) جست‌وجو ══════════════════════════════════════════════════════

async def test_the_search_flow_stores_a_token_and_lists_results(session, me, state, redis):
    await _add(session, _file(me, kind="pdf", name="گزارش مالی.pdf"), _file(me, name="x.mp4"))
    bot = RecordingBot()
    await press(bot, Hist(v="q").pack(), session, me, state, redis)
    assert await state.get_state() == HistorySearch.waiting.state
    assert bot.last("edit_message_text")["text"] == t("fa", "hist_search_prompt")

    await R.on_search_text(_msg(bot, "مالي"), session, me, "fa", state, redis)
    assert await state.get_state() is None
    sent = bot.last("send_message")
    entries = [cb for _t, cb in bot.buttons("send_message") if cb.startswith("hs:d:")]
    assert len(entries) == 1
    c = Hist.unpack(entries[0]).c
    assert c.startswith("q") and len(c) > 1
    assert await redis.get(f"hsq:{c[1:]}") == "مالي".encode()
    assert 0 < await redis.ttl(f"hsq:{c[1:]}") <= R._SEARCH_TTL
    assert "مالي" in sent["text"] or "مالی" in sent["text"]


async def test_paging_a_search_result_keeps_the_query(session, me, state, redis):
    await _add(session, *[_file(me, name=f"report {i}.pdf", kind="pdf")
                          for i in range(H.PAGE_SIZE + 2)], _file(me, name="other.mp4"))
    bot = RecordingBot()
    await R.on_search_text(_msg(bot, "report"), session, me, "fa", state, redis)
    nxt = [cb for txt, cb in bot.buttons("send_message") if txt == t("fa", "hist_btn_next")]
    await press(bot, nxt[0], session, me, state, redis)
    entries = [cb for _t, cb in bot.buttons() if cb.startswith("hs:d:")]
    assert len(entries) == 2, "صفحهٔ دومِ جست‌وجو چیزِ دیگری نشان داد"


async def test_an_expired_search_says_so(session, me, state, redis):
    bot = RecordingBot()
    await press(bot, Hist(v="l", c="qGONEGONE").pack(), session, me, state, redis)
    assert bot.last("edit_message_text")["text"] == t("fa", "hist_search_expired")


@pytest.mark.parametrize("text", ["https://youtu.be/dQw4w9WgXcQ",
                                  "ببین https://www.instagram.com/p/x/",
                                  "/start", "/history"],
                         ids=["url", "url-in-text", "start", "history"])
async def test_a_link_or_a_command_while_searching_is_not_swallowed(
        session, me, state, redis, text):
    await state.set_state(HistorySearch.waiting)
    bot = RecordingBot()
    with pytest.raises(SkipHandler):
        await R.on_search_text(_msg(bot, text), session, me, "fa", state, redis)
    assert await state.get_state() is None, "حالتِ جست‌وجو ماند و پیامِ بعدی را هم می‌بلعید"
    assert bot.calls == [], "پیامی که باید به هندلرِ بعدی برسد این‌جا جواب گرفت"


async def test_a_too_short_query_is_refused(session, me, state, redis):
    await state.set_state(HistorySearch.waiting)
    bot = RecordingBot()
    await R.on_search_text(_msg(bot, "a"), session, me, "fa", state, redis)
    assert bot.last("send_message")["text"] == t("fa", "hist_search_short",
                                                   n=R.F_.num(H.SEARCH_MIN, "fa"))


async def test_the_history_command_with_words_searches_directly(session, me, state, redis):
    await _add(session, _file(me, name="holiday.mp4"), _file(me, name="work.mp4"))
    bot = RecordingBot()
    await R.cmd_history(_msg(bot, "/history holiday"),
                        CommandObject(prefix="/", command="history", args="holiday"),
                        session, me, "fa", state, redis)
    entries = [cb for _t, cb in bot.buttons("send_message") if cb.startswith("hs:d:")]
    assert len(entries) == 1


async def test_any_other_button_leaves_the_search_state(session, me, state, redis):
    await state.set_state(HistorySearch.waiting)
    bot = RecordingBot()
    await press(bot, Hist(v="o").pack(), session, me, state, redis)
    assert await state.get_state() is None


# ══ ۹) زبان و اندازهٔ callback ══════════════════════════════════════

async def test_an_added_language_gets_latin_digits_not_persian(session, me, state):
    """`panel_fmt.is_fa` یعنی «نه en»؛ بی `_fl`، اسپانیایی تاریخِ شمسی می‌دید."""
    await _add(session, *[_file(me) for _ in range(12)])
    bot = RecordingBot()
    await press(bot, Hist(v="o").pack(), session, me, state, lang="es")
    text = bot.last("edit_message_text")["text"]
    assert "12" in text and "۱۲" not in text
    bot2 = RecordingBot()
    await press(bot2, Hist(v="o").pack(), session, me, state, lang="fa")
    assert "۱۲" in bot2.last("edit_message_text")["text"]


async def test_every_callback_fits_in_64_bytes(session, me, state, redis):
    """بدترین ترکیب: نتیجهٔ جست‌وجو (توکن) + گروه + صفحهٔ چندرقمی + حذف."""
    await _album(session, me, n=H.GROUP_PAGE_SIZE + 2)
    await _add(session, *[_file(me, name=f"z{i}.mp4") for i in range(30)])
    bot = RecordingBot()
    await R.on_search_text(_msg(bot, "clip"), session, me, "fa", state, redis)
    seen = list(bot.buttons("send_message"))
    for data in [cb for _t, cb in seen if cb.startswith(("hs:g:", "hs:d:"))][:3]:
        await press(bot, data, session, me, state, redis)
        seen += bot.buttons()
    await press(bot, Hist(v="g", c="qABCDEFGH", p=999, m=999, r="gALBUMALBUMA").pack(),
                session, me, state, redis)
    seen += bot.buttons()
    seen.append(("", Hist(v="gxy", c="qABCDEFGH", p=999, m=999, r="gALBUMALBUMA").pack()))
    assert seen
    worst = max(len(cb.encode()) for _t, cb in seen)
    assert worst <= 64, f"callback {worst} بایت"


async def test_the_noop_page_counter_does_nothing(session, me, state):
    bot = RecordingBot()
    await press(bot, Hist(v="n").pack(), session, me, state)
    assert bot.names() == ["answer_callback_query"]


def test_the_history_router_sits_before_download_and_files():
    """ترتیبِ ثبت باربر است: پس از download، لینکِ وسطِ جست‌وجو حالت را جا می‌گذاشت؛
    پس از files، `files.fallback` متنِ جست‌وجو را می‌گرفت. AST، نه ساختنِ Dispatcher —
    روترهای ماژول فقط یک والد می‌پذیرند و تستِ دیگری را می‌شکست."""
    import ast
    import pathlib
    tree = ast.parse((pathlib.Path(__file__).resolve().parents[1] / "app" / "bot.py")
                     .read_text(encoding="utf-8"))
    order = [n.args[0].value.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "include_router"]
    assert order.index("history") < order.index("download") < order.index("files"), order
