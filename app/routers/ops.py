"""عملیاتِ روی کارت: enqueue، منوی تبدیل، اسکن، تغییرِ نام (FSM)، و کنترلِ سوءاستفاده."""
from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from ..cards import card_caption, set_card_note
from ..callbacks import Act, Conv
from ..config import settings
from ..crud import get_file_by_ref
from ..i18n import t
from ..keyboards import CONVERTIBLE, cancel_kb, convert_menu_kb
from ..models import Job, User
from ..states import Rename

router = Router(name="ops")

# عملیاتی که واقعاً پردازش/فایل تولید می‌کنند (بقیه در M4)
_PROCESSING_KINDS = {"image", "video", "audio"}


def _too_large(size: int | None) -> bool:
    return bool(size and size > settings.max_file_mb * 1024 * 1024)


async def _check_limits(pool: ArqRedis, user_id: int) -> str | None:
    """None اگر مجاز؛ وگرنه 'rate' یا 'quota'."""
    rkey = f"rate:{user_id}"
    r = await pool.incr(rkey)
    if r == 1:
        await pool.expire(rkey, 60)
    if r > settings.rate_per_min:
        return "rate"

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    qkey = f"quota:{user_id}:{day}"
    q = await pool.incr(qkey)
    if q == 1:
        await pool.expire(qkey, 90000)  # ~۲۵ ساعت
    if q > settings.daily_op_quota:
        return "quota"
    return None


async def _enqueue(arq_pool: ArqRedis, session: AsyncSession, file_id: int, op: str,
                   args: dict, chat_id: int, card_mid: int, lang: str) -> None:
    job = Job(file_id=file_id, op=op, args=args, status="queued")
    session.add(job)
    await session.commit()
    await arq_pool.enqueue_job("run_op", job.id, chat_id, card_mid, lang)


async def _start(cq: CallbackQuery, file, lang, arq_pool, session, op, args, user) -> None:
    """چکِ محدودیت (پاپ‌آپ) → حالتِ پردازش → enqueue."""
    if user is not None:
        limit = await _check_limits(arq_pool, user.tg_user_id)
        if limit:
            await cq.answer(t(lang, f"limit_{limit}"), show_alert=True)
            return
    await cq.answer()
    await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang,
                        note=t(lang, "processing"), keyboard=False)
    await _enqueue(arq_pool, session, file.id, op, args, cq.message.chat.id, cq.message.message_id, lang)


# ── فشرده‌سازی ──────────────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "compress"))
async def op_compress(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str,
                      arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind not in _PROCESSING_KINDS:
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, "compress", {}, user)


# ── اسکنِ امنیت ─────────────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "scan"))
async def op_scan(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str,
                  arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, "scan", {}, user)


# ── سند/آرشیو: عملیاتِ مستقیم (zip · to_pdf · list_zip · extract) ─
_DIRECT_OPS = {"zip", "to_pdf", "list_zip", "extract"}


@router.callback_query(Act.filter(F.op.in_(_DIRECT_OPS)))
async def op_direct(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str,
                    arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, callback_data.op, {}, user)


# ── تبدیلِ فرمت: منو ────────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "convert"))
async def op_convert_menu(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind not in CONVERTIBLE:
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=t(lang, "choose_format")),
            reply_markup=convert_menu_kb(file.ref, file.kind, lang),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


# ── تبدیلِ فرمت: انتخاب ─────────────────────────────────────────
@router.callback_query(Conv.filter())
async def op_convert_pick(cq: CallbackQuery, callback_data: Conv, session: AsyncSession, lang: str,
                          arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, "convert", {"target": callback_data.fmt}, user)


# ── بازگشت به منوی اصلیِ کارت ───────────────────────────────────
@router.callback_query(Act.filter(F.op == "menu"))
async def op_back(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is not None and isinstance(cq.message, Message):
        await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang, keyboard=True)
    await cq.answer()


# ── لغو (وسطِ تغییرِ نام) ───────────────────────────────────────
@router.callback_query(Act.filter(F.op == "cancel"))
async def op_cancel(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str, state: FSMContext) -> None:
    await state.clear()
    file = await get_file_by_ref(session, callback_data.ref)
    if file is not None and isinstance(cq.message, Message):
        await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang, keyboard=True)
    await cq.answer()


# ── تغییرِ نام (FSM) ───────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "rename"))
async def op_rename_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=t(lang, "ask_new_name")),
            reply_markup=cancel_kb(file.ref, lang),
        )
    except Exception:  # noqa: BLE001
        pass
    await state.set_state(Rename.waiting_name)
    await state.update_data(ref=file.ref, card_chat=cq.message.chat.id, card_mid=cq.message.message_id)
    await cq.answer()


@router.message(Rename.waiting_name, F.text)
async def op_rename_recv(message: Message, state: FSMContext, session: AsyncSession, lang: str,
                         arq_pool: ArqRedis, user: User | None) -> None:
    data = await state.get_data()
    await state.clear()
    new_name = (message.text or "").strip()
    file = await get_file_by_ref(session, data.get("ref", ""))
    card_chat = data.get("card_chat")
    card_mid = data.get("card_mid")
    if file is None or card_chat is None:
        return
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    if user is not None:
        limit = await _check_limits(arq_pool, user.tg_user_id)
        if limit:
            await set_card_note(message.bot, card_chat, card_mid, file, lang, note=t(lang, f"limit_{limit}"), keyboard=True)
            return
    await set_card_note(message.bot, card_chat, card_mid, file, lang, note=t(lang, "processing"), keyboard=False)
    await _enqueue(arq_pool, session, file.id, "rename", {"new_name": new_name}, card_chat, card_mid, lang)


# ── بستن ───────────────────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "close"))
async def op_close(cq: CallbackQuery, lang: str) -> None:
    if isinstance(cq.message, Message):
        try:
            await cq.message.delete()
        except Exception:  # noqa: BLE001
            pass
    await cq.answer(t(lang, "card_closed"))


# ── بقیهٔ عملیات (فعلاً placeholder — M4) ───────────────────────
@router.callback_query(Act.filter())
async def op_placeholder(cq: CallbackQuery, lang: str) -> None:
    await cq.answer(t(lang, "coming_soon"), show_alert=True)
