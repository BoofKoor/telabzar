"""سیستمِ کارت: فایل + کپشن (سرآیند + لاگِ تغییراتِ بلاک‌کوت) + کیبوردِ اینلاین.

کارت = خودِ فایل که ربات می‌فرستد و کیبورد زیرش است. هر عملیات، همین کارت را
درجا (editMessageMedia) به‌روزرسانی می‌کند.
"""
from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from .filetypes import human_size
from .i18n import t
from .keyboards import file_card_kb
from .models import File

_ICON = {"document": "🗎", "image": "🖼", "video": "🎬", "audio": "🎵",
         "archive": "🗜", "app": "📦", "pdf": "📕"}
_INPUT_MEDIA = {"image": InputMediaPhoto, "video": InputMediaVideo, "audio": InputMediaAudio}


def _fmt_dur(seconds: int | None) -> str | None:
    if not seconds:
        return None
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _format_label(file: File) -> str | None:
    if file.name and "." in file.name:
        ext = file.name.rsplit(".", 1)[1]
        if 1 <= len(ext) <= 5:
            return ext.upper()
    if file.mime and "/" in file.mime:
        return file.mime.split("/", 1)[1].upper()[:6]
    return None


def _info_line(file: File) -> str:
    """خطِ اطلاعات: حجم · ابعاد · مدت · فرمت (فقط مواردِ موجود)."""
    parts = [f"<code>{human_size(file.size)}</code>"]
    if file.width and file.height:
        parts.append(f"{file.width}×{file.height}")
    dur = _fmt_dur(file.duration)
    if dur:
        parts.append(f"⏱ {dur}")
    fmt = _format_label(file)
    if fmt:
        parts.append(fmt)
    return "  ·  ".join(parts)


def card_caption(file: File, lang: str, note: str | None = None) -> str:
    icon = _ICON.get(file.kind, "📄")
    lines = [
        f"{icon} <b>{escape(file.name or '—')}</b>",
        _info_line(file),
    ]
    changelog = file.changelog or []
    if changelog:
        body = "\n".join(escape(x) for x in changelog[-8:])
        lines.append(f"<blockquote expandable>{body}</blockquote>")
    if note:
        lines.append(note)
    return "\n".join(lines)


def message_media_id(msg: Message) -> tuple[str | None, str | None]:
    """(file_id, file_unique_id) از پیامِ رسانه‌ایِ ارسال‌شده."""
    if msg.photo:
        p = msg.photo[-1]
        return p.file_id, p.file_unique_id
    for attr in ("document", "video", "audio", "animation", "voice", "video_note"):
        obj = getattr(msg, attr, None)
        if obj is not None:
            return obj.file_id, obj.file_unique_id
    return None, None


def _media_arg(file: File, path: str | None):
    return FSInputFile(path, filename=file.name or "file") if path else file.file_id


async def _send_typed(bot: Bot, chat_id: int, file: File, media, caption, kb):
    if file.kind == "image":
        return await bot.send_photo(chat_id, media, caption=caption, reply_markup=kb)
    if file.kind == "video":
        return await bot.send_video(chat_id, media, caption=caption, reply_markup=kb)
    if file.kind == "audio":
        return await bot.send_audio(chat_id, media, caption=caption, reply_markup=kb)
    return await bot.send_document(chat_id, media, caption=caption, reply_markup=kb)


async def send_card(bot: Bot, chat_id: int, file: File, lang: str, *, path: str | None = None) -> Message:
    """ارسالِ کارتِ فایل (فایل + کپشن + کیبورد). با fallback به سند."""
    caption = card_caption(file, lang)
    kb = file_card_kb(file.ref, file.kind, lang)
    try:
        return await _send_typed(bot, chat_id, file, _media_arg(file, path), caption, kb)
    except TelegramBadRequest:
        return await bot.send_document(chat_id, _media_arg(file, path), caption=caption, reply_markup=kb)


async def update_card(bot: Bot, chat_id: int, message_id: int, file: File, lang: str, *, path: str | None = None) -> Message:
    """به‌روزرسانیِ درجای کارت با فایلِ جدید (editMessageMedia). در صورت ناتوانی،
    کارتِ تازه می‌فرستد و قدیمی را پاک می‌کند."""
    caption = card_caption(file, lang)
    kb = file_card_kb(file.ref, file.kind, lang)
    im_cls = _INPUT_MEDIA.get(file.kind, InputMediaDocument)
    try:
        return await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=im_cls(media=_media_arg(file, path), caption=caption),
            reply_markup=kb,
        )
    except TelegramBadRequest:
        # تغییرِ نوعِ رسانه یا محدودیت → کارتِ تازه + حذفِ قدیمی
        msg = await send_card(bot, chat_id, file, lang, path=path)
        try:
            await bot.delete_message(chat_id, message_id)
        except TelegramBadRequest:
            pass
        return msg


def _meta_editor_note(lang: str, file: File, pending: dict) -> str:
    from .keyboards import FIELD_LABEL

    def label(k: str) -> str:
        return escape(t(lang, FIELD_LABEL.get(k, k)))

    lines = [t(lang, "meta_edit_prompt")]
    current = file.meta
    if current is None:
        lines.append(t(lang, "meta_reading"))
    elif current:
        body = "\n".join(f"{label(k)}: {escape(str(v)[:60])}" for k, v in current.items() if v)
        lines.append(f"{t(lang, 'meta_current_header')}\n<blockquote>{body}</blockquote>"
                     if body else t(lang, "meta_current_empty"))
    else:
        lines.append(t(lang, "meta_current_empty"))
    if pending:
        rows = []
        for k, v in pending.items():
            if k == "_cover":
                rows.append(f"{escape(t(lang, 'btn_f_cover'))}: {t(lang, 'meta_cover_new')}")
            else:
                rows.append(f"{label(k)}: {escape(str(v)[:60])}")
        lines.append(f"{t(lang, 'meta_pending_header')}\n<blockquote>" + "\n".join(rows) + "</blockquote>")
    return "\n".join(lines)


def meta_editor_view(file: File, lang: str, pending: dict):
    """(caption, keyboard) برای ویرایشگرِ متادیتا — اطلاعاتِ فعلی + تغییراتِ آماده."""
    from .keyboards import meta_edit_kb
    return card_caption(file, lang, note=_meta_editor_note(lang, file, pending)), meta_edit_kb(file.ref, lang)


async def move_card_below(bot: Bot, chat_id: int, old_message_id: int, file: File, lang: str) -> Message:
    """کارتِ تازه پایینِ چت می‌فرستد و کارتِ قدیمی را پاک می‌کند.

    برای عملیاتی که خروجیِ جدا می‌فرستند (استخراج/لیست/GIF/تامبنیل) تا منو
    زیرِ خروجی بیاید و چت تمیز بماند.
    """
    new_msg = await send_card(bot, chat_id, file, lang)
    try:
        await bot.delete_message(chat_id, old_message_id)
    except TelegramBadRequest:
        pass
    return new_msg


async def set_card_note(bot: Bot, chat_id: int, message_id: int, file: File, lang: str, note: str | None = None, *, keyboard: bool) -> None:
    """فقط کپشن/کیبوردِ کارت را عوض کن (برای حالتِ «در حال پردازش» یا «خطا»)."""
    kb = file_card_kb(file.ref, file.kind, lang) if keyboard else None
    try:
        await bot.edit_message_caption(
            chat_id=chat_id, message_id=message_id,
            caption=card_caption(file, lang, note=note), reply_markup=kb,
        )
    except TelegramBadRequest:
        pass
