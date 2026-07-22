"""عملیاتِ روی کارت: enqueue، منوی تبدیل، اسکن، تغییرِ نام، جمعِ چندفایلی
(زیپ / ادغامِ PDF)، ویرایشِ متادیتا (FSM)، و کنترلِ سوءاستفاده."""
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_store
from ..cards import card_caption, meta_editor_view, set_card_note, update_card
from ..callbacks import Act, Cmp, Conv, Meta, Rot, Rsz, Spd, Tr, Wm
from ..config import settings
from ..crud import get_file_by_ref
from ..filetypes import detect, suggested_name
from ..i18n import t
from ..keyboards import (
    CONVERTIBLE, FIELD_LABEL, VIDEO_KBPS, cancel_job_kb, cancel_kb, collapsed_kb, collect_kb,
    compress_menu_kb, convert_menu_kb, effective_kbps, link_menu_kb, resize_menu_kb, rotate_menu_kb,
    speed_menu_kb, transcribe_menu_kb, watermark_pos_kb,
)
from ..models import Job, User
from ..states import Collect, MetaEdit, Rename, Screenshot, SetCover, Trim, Watermark

router = Router(name="ops")

# عملیاتی که واقعاً پردازش/فایل تولید می‌کنند (بقیه در M4)
_PROCESSING_KINDS = {"image", "video", "audio"}

# فیلترِ فایل (برای حالتِ جمع‌کردن)
_FILE_F = (
    F.document | F.photo | F.video | F.audio | F.voice
    | F.animation | F.video_note | F.sticker
)

# قفلِ هر-چت برای جمع‌کردن: آپدیت‌های آلبوم همزمان پردازش می‌شوند
# (aiogram با task)، و بدونِ قفل، read-modify-writeِ لیستِ اعضا دچارِ رقابت می‌شود.
_collect_locks: dict[int, asyncio.Lock] = {}


def _collect_lock(chat_id: int) -> asyncio.Lock:
    lock = _collect_locks.get(chat_id)
    if lock is None:
        lock = _collect_locks[chat_id] = asyncio.Lock()
    return lock


# هدفِ جمع‌کردن → (کلیدِ راهنما, کلیدِ سرآیندِ لیست)
_COLLECT_TEXT = {
    "merge": ("merge_collect_prompt", "merge_list_header"),
    "img_pdf": ("img_pdf_collect_prompt", "img_pdf_list_header"),
    "zip": ("zip_collect_prompt", "zip_list_header"),
}
# هدف‌هایی که فقط یک نوعِ خاص می‌پذیرند → (نوعِ مجاز, کلیدِ هشدار)
_COLLECT_ONLY = {
    "merge": ("pdf", "merge_only_pdf"),
    "img_pdf": ("image", "img_pdf_only_image"),
}


def _collect_note(lang: str, purpose: str, members: list[dict], last: str | None = None) -> str:
    prompt, header = _COLLECT_TEXT.get(purpose, _COLLECT_TEXT["zip"])
    lines = [t(lang, prompt)]
    if last:
        lines.append(t(lang, "zip_received", name=escape(last)))
    names = [str(m.get("name") or "file") for m in members]
    shown = names[-12:]
    body = "\n".join(f"• {escape(n[:48])}" for n in shown)
    block = f"{t(lang, header, n=len(names))}\n<blockquote>{body}"
    if len(names) > len(shown):
        block += f"\n… (+{len(names) - len(shown)})"
    block += "</blockquote>"
    lines.append(block)
    return "\n".join(lines)


def _too_large(size: int | None) -> bool:
    return bool(size and size > settings.max_file_mb * 1024 * 1024)


async def _check_limits(pool: ArqRedis, user_id: int) -> str | None:
    """None اگر مجاز؛ وگرنه 'rate' یا 'quota'. سقفِ ≤۰ یعنی نامحدود (خاموش).

    سقف‌ها از فروشگاهِ تنظیمات خوانده می‌شوند (قابلِ‌تغییر از /admin بدونِ ری‌استارت)؛
    اگر تنظیم نشده باشد، پیش‌فرضِ env به‌کار می‌رود."""
    rate = await settings_store.get_int("rate_per_min", settings.rate_per_min)
    quota = await settings_store.get_int("daily_op_quota", settings.daily_op_quota)
    if rate > 0:
        rkey = f"rate:{user_id}"
        r = await pool.incr(rkey)
        if r == 1:
            await pool.expire(rkey, 60)
        if r > rate:
            return "rate"

    if quota > 0:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        qkey = f"quota:{user_id}:{day}"
        q = await pool.incr(qkey)
        if q == 1:
            await pool.expire(qkey, 90000)  # ~۲۵ ساعت
        if q > quota:
            return "quota"
    return None


async def _enqueue(bot, arq_pool: ArqRedis, session: AsyncSession, file, op: str,
                   args: dict, chat_id: int, card_mid: int, lang: str) -> None:
    """جاب می‌سازد، کارت را به حالتِ «پردازش + دکمهٔ لغو» می‌برد، و enqueue می‌کند."""
    job = Job(file_id=file.id, op=op, args=args, status="queued")
    session.add(job)
    await session.commit()
    await set_card_note(bot, chat_id, card_mid, file, lang,
                        note=t(lang, "processing"), keyboard=cancel_job_kb(job.id, lang))
    await arq_pool.enqueue_job("run_op", job.id, chat_id, card_mid, lang)


async def _queue_quiet(arq_pool: ArqRedis, session: AsyncSession, file_id: int, op: str,
                       args: dict, chat_id: int, card_mid: int, lang: str) -> None:
    """enqueue بدونِ دست‌زدن به کپشن (برای meta_read که خودش ویرایشگر را رندر می‌کند)."""
    job = Job(file_id=file_id, op=op, args=args, status="queued")
    session.add(job)
    await session.commit()
    await arq_pool.enqueue_job("run_op", job.id, chat_id, card_mid, lang)


# عملیاتِ گران که وقتی روی یک فایلِ «دانلودی» اجرا شوند، در بودجهٔ روزانه حساب می‌شوند
# (نقدِ طراحی: دانلود ارزان است ولی رونویسی/فشرده‌سازیِ یک ویدیوی ۲ساعته گران).
_EXPENSIVE_OPS = {"transcribe", "compress", "convert", "scan", "bg_remove", "to_gif"}


async def _check_dl_op_budget(pool: ArqRedis, user_id: int, file, op: str) -> bool:
    """True اگر کاربر سقفِ روزانهٔ «دقیقه‌پردازشِ رسانهٔ دانلودی» را رد کند."""
    if getattr(file, "source", None) != "dl" or op not in _EXPENSIVE_OPS:
        return False
    cap = await settings_store.get_int("dl_op_daily_min", settings.dl_op_daily_min)
    if cap <= 0:
        return False
    minutes = max(1, round((file.duration or 60) / 60))
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = f"dlop:{user_id}:{day}"
    try:
        used = await pool.incrby(key, minutes)  # INCRBY یک عددِ int می‌دهد (نه bytes)
        if used == minutes:
            await pool.expire(key, 90000)
        if used > cap:
            await pool.decrby(key, minutes)  # ردشد → بازپرداخت تا بودجه دقیق بماند
            return True
    except Exception:  # noqa: BLE001
        return False
    return False


async def _start(cq: CallbackQuery, file, lang, arq_pool, session, op, args, user) -> None:
    """چکِ محدودیت (پاپ‌آپ) → حالتِ پردازش + دکمهٔ لغو → enqueue."""
    if user is not None:
        limit = await _check_limits(arq_pool, user.tg_user_id)
        if limit:
            await cq.answer(t(lang, f"limit_{limit}"), show_alert=True)
            return
        if await _check_dl_op_budget(arq_pool, user.tg_user_id, file, op):
            await cq.answer(t(lang, "dl_op_limit"), show_alert=True)
            return
    await cq.answer()
    await _enqueue(cq.message.bot, arq_pool, session, file, op, args,
                   cq.message.chat.id, cq.message.message_id, lang)


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
    if file.kind == "video":  # منوی کیفیت (رزولوشن‌های پایین‌تر + تخمینِ حجم)
        try:
            await cq.message.edit_caption(
                caption=card_caption(file, lang, note=t(lang, "compress_choose")),
                reply_markup=compress_menu_kb(file.ref, file, lang),
            )
        except Exception:  # noqa: BLE001
            pass
        await cq.answer()
        return
    await _start(cq, file, lang, arq_pool, session, "compress", {}, user)


@router.callback_query(Cmp.filter())
async def op_compress_pick(cq: CallbackQuery, callback_data: Cmp, session: AsyncSession, lang: str,
                           arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    if callback_data.res == "same":
        args: dict = {}
    else:
        h = int(callback_data.res)
        target = VIDEO_KBPS.get(h)
        # بیت‌ریت را زیر منبع سقف بزن تا خروجی واقعاً کوچک‌تر شود (نه بزرگ‌تر)
        args = {"height": h, "kbps": effective_kbps(target, file) if target else None}
    await _start(cq, file, lang, arq_pool, session, "compress", args, user)


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
# سند/آرشیو: to_pdf · list_zip · extract   ·   رسانه: to_gif · extract_audio · mute
# نکته: zip / meta / cover / link / watermark / trim / screenshot فلوی چندمرحله‌ای دارند.
_DIRECT_OPS = {"to_pdf", "list_zip", "extract", "to_gif", "extract_audio", "mute"}


def _parse_time(s: str) -> float | None:
    """'1:23' یا '0:01:05' یا '83' → ثانیه."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        parts = [float(p) for p in s.split(":")]
    except ValueError:
        return None
    if len(parts) == 1:
        sec = parts[0]
    elif len(parts) == 2:
        sec = parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
    else:
        return None
    return sec if sec >= 0 else None


def _parse_range(s: str) -> tuple[float, float] | None:
    """'0:10-0:45' یا '0:10 تا 0:45' → (start, end)."""
    s = (s or "").strip()
    for sep in ("-", "تا", " to ", "–"):
        if sep in s:
            a, b = s.split(sep, 1)
            ta, tb = _parse_time(a), _parse_time(b)
            if ta is not None and tb is not None and tb > ta:
                return ta, tb
    return None


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


# ── جعبه‌ابزارِ تصویر ───────────────────────────────────────────
# عملیاتِ مستقیمِ تصویر (بدونِ ورودی): متن (OCR) · بهبود · حذفِ پس‌زمینه
_IMG_OPS = {"ocr", "enhance", "bg_remove"}


@router.callback_query(Act.filter(F.op.in_(_IMG_OPS)))
async def op_image_direct(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str,
                          arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "image":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, callback_data.op, {}, user)


# ── تغییرِ اندازهٔ تصویر: منو → انتخاب ──────────────────────────
@router.callback_query(Act.filter(F.op == "resize"))
async def op_resize(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "image":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=t(lang, "resize_choose")),
            reply_markup=resize_menu_kb(file.ref, file, lang),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


@router.callback_query(Rsz.filter())
async def op_resize_pick(cq: CallbackQuery, callback_data: Rsz, session: AsyncSession, lang: str,
                         arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, "resize", {"w": callback_data.w}, user)


# ── چرخش/آینهٔ تصویر: منو → انتخاب ──────────────────────────────
@router.callback_query(Act.filter(F.op == "rotate"))
async def op_rotate(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "image":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=t(lang, "rotate_choose")),
            reply_markup=rotate_menu_kb(file.ref, lang),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


@router.callback_query(Rot.filter())
async def op_rotate_pick(cq: CallbackQuery, callback_data: Rot, session: AsyncSession, lang: str,
                         arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, "rotate", {"mode": callback_data.mode}, user)


# ── عکس‌ها به PDF: شروع (جمع‌آوریِ چند تصویر) ───────────────────
@router.callback_query(Act.filter(F.op == "img_pdf"))
async def op_img_pdf_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession,
                           lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "image":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    await _collect_start(cq, file, lang, state, "img_pdf")


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
    await _enqueue(message.bot, arq_pool, session, file, "rename", {"new_name": new_name}, card_chat, card_mid, lang)


async def _collect_start(cq: CallbackQuery, file, lang: str, state: FSMContext, purpose: str) -> None:
    members = [{"file_id": file.file_id, "name": suggested_name(file.name, file.kind, file.mime)}]
    await state.set_state(Collect.collecting)
    await state.update_data(ref=file.ref, card_chat=cq.message.chat.id,
                            card_mid=cq.message.message_id, members=members, purpose=purpose)
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=_collect_note(lang, purpose, members)),
            reply_markup=collect_kb(file.ref, lang, purpose),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


# ── زیپِ چندفایلی: شروع ─────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "zip"))
async def op_zip_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession,
                       lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    await _collect_start(cq, file, lang, state, "zip")


# ── ادغامِ PDF: شروع ────────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "merge"))
async def op_merge_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession,
                         lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "pdf":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    await _collect_start(cq, file, lang, state, "merge")


# ── جمع‌کردن: دریافتِ فایل‌های بعدی ─────────────────────────────
@router.message(Collect.collecting, _FILE_F)
async def collect_recv(message: Message, state: FSMContext, session: AsyncSession, lang: str) -> None:
    info = detect(message)
    try:
        await message.delete()  # آپلود را پاک کن تا چت تمیز و کارت پایین بماند
    except Exception:  # noqa: BLE001
        pass
    if info is None:
        return
    data = await state.get_data()
    purpose = data.get("purpose", "zip")
    card_chat, card_mid, ref = data.get("card_chat"), data.get("card_mid"), data.get("ref", "")
    if card_chat is None:
        return
    file = await get_file_by_ref(session, ref)
    if file is None:
        return
    # هدف‌های نوع‌مقید (ادغامِ PDF → فقط PDF · عکس‌ها به PDF → فقط تصویر)
    only = _COLLECT_ONLY.get(purpose)
    if only and info.kind != only[0]:
        try:
            await message.bot.edit_message_caption(
                chat_id=card_chat, message_id=card_mid,
                caption=card_caption(file, lang, note=_collect_note(lang, purpose, list(data.get("members", [])))
                                     + "\n" + t(lang, only[1])),
                reply_markup=collect_kb(ref, lang, purpose),
            )
        except Exception:  # noqa: BLE001
            pass
        return
    # قفلِ هر-چت: افزودنِ همزمانِ عکس‌های آلبوم دچارِ رقابت نشود
    async with _collect_lock(message.chat.id):
        data = await state.get_data()
        members = list(data.get("members", []))
        name = suggested_name(info.name, info.kind, info.mime, idx=len(members) + 1)
        members.append({"file_id": info.file_id, "name": name})
        await state.update_data(members=members)
    try:
        await message.bot.edit_message_caption(
            chat_id=card_chat, message_id=card_mid,
            caption=card_caption(file, lang, note=_collect_note(lang, purpose, members, last=name)),
            reply_markup=collect_kb(ref, lang, purpose),
        )
    except Exception:  # noqa: BLE001
        pass


# ── جمع‌کردن: اجرا (زیپ یا ادغامِ PDF) ──────────────────────────
@router.callback_query(Act.filter(F.op == "collect_go"))
async def op_collect_go(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str,
                        state: FSMContext, arq_pool: ArqRedis, user: User | None) -> None:
    data = await state.get_data()
    members = list(data.get("members", []))
    purpose = data.get("purpose", "zip")
    await state.clear()
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if not members:
        members = [{"file_id": file.file_id, "name": file.name or "file"}]
    if purpose == "merge" and len(members) < 2:
        await cq.answer(t(lang, "merge_need_more"), show_alert=True)
        await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang, keyboard=True)
        return
    if user is not None:
        limit = await _check_limits(arq_pool, user.tg_user_id)
        if limit:
            await cq.answer(t(lang, f"limit_{limit}"), show_alert=True)
            await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang, keyboard=True)
            return
    await cq.answer()
    op = {"merge": "pdf_merge", "img_pdf": "images_to_pdf"}.get(purpose, "zip_many")
    await _enqueue(cq.message.bot, arq_pool, session, file, op, {"members": members},
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
    # اطلاعاتِ فعلی را در پس‌زمینه بخوان و روی همین کارت پر کن (بدونِ نوتِ پردازش)
    await _queue_quiet(arq_pool, session, file.id, "meta_read", {},
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
    await _enqueue(cq.message.bot, arq_pool, session, file, "meta_write", {"tags": tags, "cover_id": cover_id},
                   cq.message.chat.id, cq.message.message_id, lang)


# ── صوتِ عمیق: رونویسی / نرمال‌سازی / سرعت ──────────────────────
@router.callback_query(Act.filter(F.op == "transcribe"))
async def op_transcribe(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "audio":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=t(lang, "tr_choose")),
            reply_markup=transcribe_menu_kb(file.ref, lang),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


@router.callback_query(Tr.filter())
async def op_transcribe_pick(cq: CallbackQuery, callback_data: Tr, session: AsyncSession, lang: str,
                             arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, "transcribe", {"mode": callback_data.mode}, user)


@router.callback_query(Act.filter(F.op == "normalize"))
async def op_normalize(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str,
                       arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "audio":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, "normalize", {}, user)


@router.callback_query(Act.filter(F.op == "speed"))
async def op_speed(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "audio":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=t(lang, "speed_choose")),
            reply_markup=speed_menu_kb(file.ref, lang),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


@router.callback_query(Spd.filter())
async def op_speed_pick(cq: CallbackQuery, callback_data: Spd, session: AsyncSession, lang: str,
                        arq_pool: ArqRedis, user: User | None) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if _too_large(file.size):
        await cq.answer(t(lang, "too_large", mb=settings.max_file_mb), show_alert=True)
        return
    await _start(cq, file, lang, arq_pool, session, "speed", {"rate": callback_data.rate}, user)


# ── لینکِ دانلود/استریم: زیرمنوی درجا ───────────────────────────
@router.callback_query(Act.filter(F.op == "link"))
async def op_link(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if not settings.public_base:
        await cq.answer(t(lang, "link_unconfigured"), show_alert=True)
        return
    if not file.dl_token:
        file.dl_token = secrets.token_urlsafe(18)[:24]
        await session.commit()
    base = settings.public_base.rstrip("/")
    dl, stream = f"{base}/dl/{file.dl_token}", f"{base}/s/{file.dl_token}"
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=t(lang, "link_ready_menu")),
            reply_markup=link_menu_kb(file.ref, lang, dl, stream, file.kind in ("video", "audio")),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


# ── ست‌کردنِ کاورِ ویدیو (FSM؛ درجا با editMessageMedia) ─────────
@router.callback_query(Act.filter(F.op == "cover"))
async def op_cover_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession,
                         lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "video":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    await state.set_state(SetCover.waiting)
    await state.update_data(ref=file.ref, card_chat=cq.message.chat.id, card_mid=cq.message.message_id)
    try:
        await cq.message.edit_caption(
            caption=card_caption(file, lang, note=t(lang, "cover_ask")),
            reply_markup=cancel_kb(file.ref, lang),
        )
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


@router.message(SetCover.waiting)
async def op_cover_recv(message: Message, state: FSMContext, session: AsyncSession, lang: str) -> None:
    if not message.photo:  # فقط عکس؛ بقیه را پاک کن و منتظر بمان
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass
        return
    data = await state.get_data()
    await state.clear()
    cover_fid = message.photo[-1].file_id
    ref, card_chat, card_mid = data.get("ref", ""), data.get("card_chat"), data.get("card_mid")
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    file = await get_file_by_ref(session, ref)
    if file is None or card_chat is None:
        return
    file.cover_id = cover_fid
    file.changelog = list(file.changelog or []) + [t(lang, "cl_cover")]
    await session.commit()
    try:
        await update_card(message.bot, card_chat, card_mid, file, lang)
    except Exception:  # noqa: BLE001
        await set_card_note(message.bot, card_chat, card_mid, file, lang, keyboard=True)


# ── واترمارک: انتخابِ موقعیت ────────────────────────────────────
@router.callback_query(Act.filter(F.op == "watermark"))
async def op_watermark_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind not in ("video", "image"):
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    try:
        await cq.message.edit_caption(caption=card_caption(file, lang, note=t(lang, "wm_choose_pos")),
                                      reply_markup=watermark_pos_kb(file.ref, lang))
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


@router.callback_query(Wm.filter())
async def op_watermark_pos(cq: CallbackQuery, callback_data: Wm, session: AsyncSession,
                           lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    await state.set_state(Watermark.waiting)
    await state.update_data(ref=file.ref, card_chat=cq.message.chat.id,
                            card_mid=cq.message.message_id, pos=callback_data.pos)
    try:
        await cq.message.edit_caption(caption=card_caption(file, lang, note=t(lang, "wm_ask_content")),
                                      reply_markup=cancel_kb(file.ref, lang))
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


@router.message(Watermark.waiting)
async def op_watermark_recv(message: Message, state: FSMContext, session: AsyncSession, lang: str,
                            arq_pool: ArqRedis, user: User | None) -> None:
    data = await state.get_data()
    if message.photo:
        args = {"pos": data.get("pos", "br"), "logo": message.photo[-1].file_id}
    elif message.text and message.text.strip():
        args = {"pos": data.get("pos", "br"), "text": message.text.strip()[:80]}
    else:
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass
        return  # نه متن نه عکس؛ منتظر بمان
    ref, card_chat, card_mid = data.get("ref", ""), data.get("card_chat"), data.get("card_mid")
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    await state.clear()
    file = await get_file_by_ref(session, ref)
    if file is None or card_chat is None:
        return
    if user is not None:
        limit = await _check_limits(arq_pool, user.tg_user_id)
        if limit:
            await set_card_note(message.bot, card_chat, card_mid, file, lang, note=t(lang, f"limit_{limit}"), keyboard=True)
            return
    await _enqueue(message.bot, arq_pool, session, file, "watermark", args, card_chat, card_mid, lang)


# ── برش: دریافتِ بازه ───────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "trim"))
async def op_trim_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession,
                        lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind not in ("video", "audio"):
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    await state.set_state(Trim.waiting)
    await state.update_data(ref=file.ref, card_chat=cq.message.chat.id, card_mid=cq.message.message_id)
    try:
        await cq.message.edit_caption(caption=card_caption(file, lang, note=t(lang, "trim_ask")),
                                      reply_markup=cancel_kb(file.ref, lang))
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


@router.message(Trim.waiting, F.text)
async def op_trim_recv(message: Message, state: FSMContext, session: AsyncSession, lang: str,
                       arq_pool: ArqRedis, user: User | None) -> None:
    data = await state.get_data()
    ref, card_chat, card_mid = data.get("ref", ""), data.get("card_chat"), data.get("card_mid")
    rng = _parse_range(message.text or "")
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    file = await get_file_by_ref(session, ref)
    if file is None or card_chat is None:
        return
    if rng is None:  # نامعتبر → همان‌جا بمان و دوباره بپرس
        await set_card_note(message.bot, card_chat, card_mid, file, lang,
                            note=t(lang, "trim_bad"), keyboard=cancel_kb(file.ref, lang))
        return
    await state.clear()
    if user is not None:
        limit = await _check_limits(arq_pool, user.tg_user_id)
        if limit:
            await set_card_note(message.bot, card_chat, card_mid, file, lang, note=t(lang, f"limit_{limit}"), keyboard=True)
            return
    await _enqueue(message.bot, arq_pool, session, file, "trim", {"start": rng[0], "end": rng[1]},
                   card_chat, card_mid, lang)


# ── اسکرین‌شات: دریافتِ لحظه ────────────────────────────────────
@router.callback_query(Act.filter(F.op == "screenshot"))
async def op_screenshot_start(cq: CallbackQuery, callback_data: Act, session: AsyncSession,
                              lang: str, state: FSMContext) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is None or not isinstance(cq.message, Message):
        await cq.answer()
        return
    if file.kind != "video":
        await cq.answer(t(lang, "coming_soon"), show_alert=True)
        return
    await state.set_state(Screenshot.waiting)
    await state.update_data(ref=file.ref, card_chat=cq.message.chat.id, card_mid=cq.message.message_id)
    try:
        await cq.message.edit_caption(caption=card_caption(file, lang, note=t(lang, "shot_ask")),
                                      reply_markup=cancel_kb(file.ref, lang))
    except Exception:  # noqa: BLE001
        pass
    await cq.answer()


@router.message(Screenshot.waiting, F.text)
async def op_screenshot_recv(message: Message, state: FSMContext, session: AsyncSession, lang: str,
                             arq_pool: ArqRedis, user: User | None) -> None:
    data = await state.get_data()
    ref, card_chat, card_mid = data.get("ref", ""), data.get("card_chat"), data.get("card_mid")
    ts = _parse_time(message.text or "")
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    file = await get_file_by_ref(session, ref)
    if file is None or card_chat is None:
        return
    if ts is None:
        await set_card_note(message.bot, card_chat, card_mid, file, lang,
                            note=t(lang, "shot_bad"), keyboard=cancel_kb(file.ref, lang))
        return
    await state.clear()
    if user is not None:
        limit = await _check_limits(arq_pool, user.tg_user_id)
        if limit:
            await set_card_note(message.bot, card_chat, card_mid, file, lang, note=t(lang, f"limit_{limit}"), keyboard=True)
            return
    await _enqueue(message.bot, arq_pool, session, file, "screenshot", {"ts": ts}, card_chat, card_mid, lang)


# ── لغوِ جابِ در حالِ اجرا ──────────────────────────────────────
@router.callback_query(Act.filter(F.op == "canceljob"))
async def op_cancel_job(cq: CallbackQuery, callback_data: Act, arq_pool: ArqRedis, lang: str) -> None:
    job_id = callback_data.ref
    if job_id.isdigit():
        try:
            await arq_pool.set(f"cancel:{job_id}", "1", ex=1200)
        except Exception:  # noqa: BLE001
            pass
    await cq.answer(t(lang, "cancelling"))


# ── بستن ───────────────────────────────────────────────────────
@router.callback_query(Act.filter(F.op == "close"))
async def op_close(cq: CallbackQuery, lang: str) -> None:
    if isinstance(cq.message, Message):
        try:
            await cq.message.delete()
        except Exception:  # noqa: BLE001
            pass
    await cq.answer(t(lang, "card_closed"))


# ── جمع‌کردنِ منو (فایلِ لینک): فقط منو بسته می‌شود، فایل می‌ماند ──
@router.callback_query(Act.filter(F.op == "collapse"))
async def op_collapse(cq: CallbackQuery, callback_data: Act, session: AsyncSession, lang: str) -> None:
    file = await get_file_by_ref(session, callback_data.ref)
    if file is not None and isinstance(cq.message, Message):
        await set_card_note(cq.message.bot, cq.message.chat.id, cq.message.message_id, file, lang,
                            keyboard=collapsed_kb(file.ref, lang))
    await cq.answer()


# ── بقیهٔ عملیات (فعلاً placeholder — M4) ───────────────────────
@router.callback_query(Act.filter())
async def op_placeholder(cq: CallbackQuery, lang: str) -> None:
    await cq.answer(t(lang, "coming_soon"), show_alert=True)
