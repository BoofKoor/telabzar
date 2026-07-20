"""عملیاتِ روی کارت: enqueue، منوی تبدیل، اسکن، تغییرِ نام، جمعِ چندفایلی برای زیپ،
ویرایشِ متادیتا (FSM)، و کنترلِ سوءاستفاده."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from ..cards import card_caption, meta_editor_view, set_card_note
from ..callbacks import Act, Conv, Meta
from ..config import settings
from ..crud import get_file_by_ref
from ..filetypes import detect, suggested_name
from ..i18n import t
from ..keyboards import CONVERTIBLE, FIELD_LABEL, cancel_kb, convert_menu_kb, zip_collect_kb
from ..models import Job, User
from ..states import MetaEdit, Rename, ZipCollect

router = Router(name="ops")

# عملیاتی که واقعاً پردازش/فایل تولید می‌کنند (بقیه در M4)
_PROCESSING_KINDS = {"image", "video", "audio"}

# فیلترِ فایل (برای حالتِ جمع‌کردنِ زیپ)
_FILE_F = (
    F.document | F.photo | F.video | F.audio | F.voice
    | F.animation | F.video_note | F.sticker
)

# قفلِ هر-چت برای جمع‌کردنِ زیپ: آپدیت‌های آلبوم همزمان پردازش می‌شوند
# (aiogram با task)، و بدونِ قفل، read-modify-writeِ لیستِ اعضا دچارِ رقابت می‌شود.
_collect_locks: dict[int, asyncio.Lock] = {}


def _collect_lock(chat_id: int) -> asyncio.Lock:
    lock = _collect_locks.get(chat_id)
    if lock is None:
        lock = _collect_locks[chat_id] = asyncio.Lock()
    return lock


def _zip_note(lang: str, members: list[dict], last: str | None = None) -> str:
    lines = [t(lang, "zip_collect_prompt")]
    if last:
        lines.append(t(lang, "zip_received", name=escape(last)))
    names = [str(m.get("name") or "file") for m in members]
    shown = names[-12:]
    body = "\n".join(f"• {escape(n[:48])}" for n in shown)
    block = f"{t(lang, 'zip_list_header', n=len(names))}\n<blockquote>{body}"
    if len(names) > len(shown):
        block += f"\n… (+{len(names) - len(shown)})"
    block += "</blockquote>"
    lines.append(block)
    return "\n".join(lines)


def _too_large(size: int | None) -> bool:
    return bool(size and size > settings.max_file_mb * 1024 * 1024)


async def _check_limits(pool: ArqRedis, user_id: int) -> str | None:
    """None اگر مجاز؛ وگرنه 'rate' یا 'quota'. سقفِ ≤۰ یعنی نامحدود (خاموش)."""
    if settings.rate_per_min > 0:
        rkey = f"rate:{user_id}"
        r = await pool.incr(rkey)
        if r == 1:
            await pool.expire(rkey, 60)
        if r > settings.rate_per_min:
            return "rate"

    if settings.daily_op_quota > 0:
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


# ── عملیاتِ مستقیم (بدونِ منو/ورودی): enqueue و تمام ───────────
# سند/آرشیو: to_pdf · list_zip · extract   ·   رسانه: to_gif · thumb (ویدیو)
# نکته: zip و meta فلوی چندمرحله‌ای دارند (پایین‌تر).
_DIRECT_OPS = {"to_pdf", "list_zip", "extract", "to_gif", "thumb"}


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


# ── زیپِ چندفایلی: شروعِ جمع‌کردن ───────────────────────────────
@router.callback_query(Act.filter(F.op == "zip"))
async def op_zip_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession,
                       lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    members = [{"file_id": file.file_id, "name": suggested_name(file.name, file.kind, file.mime)}]
    await state.set_state(ZipCollect.collecting)
    await state.update_data(ref=file.ref, card_chat=cq.message.chat.id,
                            card_mid=cq.message.message_id, members=members)
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=_zip_note(lang, members)),
            reply_markup=zip_collect_kb(file.ref, lang),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


# ── زیپِ چندفایلی: دریافتِ فایل‌های بعدی ─────────────────────────
@router.message(ZipCollect.collecting, _FILE_F)
async def zip_collect_recv(message: Message, state: FSMContext, session: AsyncSession, lang: str) -> None:
    info = detect(message)
    try:
        await message.delete()  # آپلود را پاک کن تا چت تمیز و کارت پایین بماند
    except Exception:  # noqa: BLE001
        pass
    if info is None:
        return
    # قفلِ هر-چت: افزودنِ همزمانِ عکس‌های آلبوم دچارِ رقابت نشود
    async with _collect_lock(message.chat.id):
        data = await state.get_data()
        members = list(data.get("members", []))
        name = suggested_name(info.name, info.kind, info.mime, idx=len(members) + 1)
        members.append({"file_id": info.file_id, "name": name})
        await state.update_data(members=members)
    ref = data.get("ref", "")
    card_chat, card_mid = data.get("card_chat"), data.get("card_mid")
    if card_chat is None:
        return
    file = await get_file_by_ref(session, ref)
    if file is None:
        return
    try:
        await message.bot.edit_message_caption(
            chat_id=card_chat, message_id=card_mid,
            caption=card_caption(file, lang, note=_zip_note(lang, members, last=name)),
            reply_markup=zip_collect_kb(ref, lang),
        )
    except Exception:  # noqa: BLE001
        pass


# ── زیپِ چندفایلی: اجرا ─────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "zip_go"))
async def op_zip_go(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str,
                    state: FSMContext, arq_pool: ArqRedis, user: User | None) -> None:
    data = await state.get_data()
    members = list(data.get("members", []))
    await state.clear()
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if not members:
        members = [{"file_id": file.file_id, "name": file.name or "file"}]
    if user is not None:
        limit = await _check_limits(arq_pool, user.tg_user_id)
        if limit:
            await cq.answer(t(lang, f"limit_{limit}"), show_alert=True)
            await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang, keyboard=True)
            return
    await cq.answer()
    await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang,
                        note=t(lang, "processing"), keyboard=False)
    await _enqueue(arq_pool, session, file.id, "zip_many", {"members": members},
                   cq.message.chat.id, cq.message.message_id, lang)


# ── ویرایشِ متادیتای صوت: منوی فیلدها (+ خواندنِ اطلاعاتِ فعلی) ──
@router.callback_query(Act.filter(F.op == "meta"))
async def op_meta_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession,
                        lang: str, state: FSMContext, arq_pool: ArqRedis) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    await state.set_state(MetaEdit.choosing)
    await state.update_data(ref=file.ref, card_chat=cq.message.chat.id,
                            card_mid=cq.message.message_id, pending={})
    caption, kb = meta_editor_view(file, lang, {})
    try:
        await cq.message.edit_caption(caption=caption, reply_markup=kb)
    except Exception:  # noqa: BLE001
        pass
    # اطلاعاتِ فعلی را در پس‌زمینه بخوان و روی همین کارت پر کن
    await _enqueue(arq_pool, session, file.id, "meta_read", {},
                   cq.message.chat.id, cq.message.message_id, lang)
    await cq.answer()


# ── ویرایشِ متادیتا: انتخابِ فیلد → درخواستِ مقدار/عکس ─────────
@router.callback_query(Meta.filter())
async def op_meta_field(cq: CallbackQuery, callback_data: Meta, session: AsyncSession,
                        lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if callback_data.field == "cover":
        await state.set_state(MetaEdit.waiting_cover)
        note = t(lang, "meta_ask_cover")
    else:
        await state.set_state(MetaEdit.waiting_value)
        await state.update_data(field=callback_data.field)
        note = t(lang, "meta_ask_value", field=t(lang, FIELD_LABEL.get(callback_data.field, callback_data.field)))
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=note), reply_markup=cancel_kb(file.ref, lang),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


async def _meta_refresh(message: Message, ref: str, card_chat, card_mid,
                        session: AsyncSession, lang: str, pending: dict) -> None:
    file = await get_file_by_ref(session, ref)
    if file is None or card_chat is None:
        return
    caption, kb = meta_editor_view(file, lang, pending)
    try:
        await message.bot.edit_message_caption(chat_id=card_chat, message_id=card_mid, caption=caption, reply_markup=kb)
    except Exception:  # noqa: BLE001
        pass


# ── ویرایشِ متادیتا: دریافتِ مقدارِ متنی ───────────────────────
@router.message(MetaEdit.waiting_value, F.text)
async def op_meta_value(message: Message, state: FSMContext, session: AsyncSession, lang: str) -> None:
    data = await state.get_data()
    field = data.get("field")
    pending = dict(data.get("pending", {}))
    val = (message.text or "").strip()[:120]
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    if field and val:
        pending[field] = val
    await state.update_data(pending=pending)
    await state.set_state(MetaEdit.choosing)
    await _meta_refresh(message, data.get("ref", ""), data.get("card_chat"), data.get("card_mid"),
                        session, lang, pending)


# ── ویرایشِ متادیتا: دریافتِ عکسِ کاور ─────────────────────────
@router.message(MetaEdit.waiting_cover)
async def op_meta_cover(message: Message, state: FSMContext, session: AsyncSession, lang: str) -> None:
    if not message.photo:  # فقط عکس؛ بقیه را پاک کن و منتظر بمان
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass
        return
    data = await state.get_data()
    pending = dict(data.get("pending", {}))
    pending["_cover"] = message.photo[-1].file_id
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    await state.update_data(pending=pending)
    await state.set_state(MetaEdit.choosing)
    await _meta_refresh(message, data.get("ref", ""), data.get("card_chat"), data.get("card_mid"),
                        session, lang, pending)


# ── ویرایشِ متادیتا: اعمال ─────────────────────────────────────
@router.callback_query(Act.filter(F.op == "meta_apply"))
async def op_meta_apply(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str,
                        state: FSMContext, arq_pool: ArqRedis, user: User | None) -> None:
    data = await state.get_data()
    pending = dict(data.get("pending", {}))
    await state.clear()
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    tags = {k: v for k, v in pending.items() if not k.startswith("_")}
    cover_id = pending.get("_cover")
    if not tags and not cover_id:
        await cq.answer(t(lang, "meta_nothing"), show_alert=True)
        await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang, keyboard=True)
        return
    if user is not None:
        limit = await _check_limits(arq_pool, user.tg_user_id)
        if limit:
            await cq.answer(t(lang, f"limit_{limit}"), show_alert=True)
            await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang, keyboard=True)
            return
    await cq.answer()
    await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang,
                        note=t(lang, "processing"), keyboard=False)
    await _enqueue(arq_pool, session, file.id, "meta_write", {"tags": tags, "cover_id": cover_id},
                   cq.message.chat.id, cq.message.message_id, lang)


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
