"""دریافتِ فایل → کارتِ عملیات. (M1: عملیات‌ها placeholder)."""
from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..callbacks import Act
from ..filetypes import detect, human_size
from ..i18n import t
from ..keyboards import file_card_kb
from ..models import File, User

router = Router(name="files")

FILE_FILTER = (
    F.document | F.photo | F.video | F.audio | F.voice
    | F.animation | F.video_note | F.sticker
)


def _new_ref() -> str:
    return secrets.token_urlsafe(6)[:8]


@router.message(FILE_FILTER)
async def on_file(
    message: Message, session: AsyncSession, user: User | None, lang: str
) -> None:
    info = detect(message)
    if info is None or user is None:
        return

    ref = _new_ref()
    session.add(
        File(
            ref=ref,
            owner_id=user.id,
            file_unique_id=info.file_unique_id,
            file_id=info.file_id,
            kind=info.kind,
            mime=info.mime,
            name=info.name,
            size=info.size,
        )
    )
    await session.commit()

    caption = t(
        lang,
        f"detected_{info.kind}",
        name=info.name or "—",
        size=human_size(info.size),
    )
    await message.answer(caption, reply_markup=file_card_kb(ref, info.kind, lang))


@router.callback_query(Act.filter(F.op == "close"))
async def close_card(cq: CallbackQuery, lang: str) -> None:
    if isinstance(cq.message, Message):
        await cq.message.delete()
    await cq.answer(t(lang, "card_closed"))


@router.callback_query(Act.filter())
async def op_placeholder(cq: CallbackQuery, lang: str) -> None:
    # M1: عملیاتِ واقعی در M2 اضافه می‌شود.
    await cq.answer(t(lang, "coming_soon"), show_alert=True)


@router.message()
async def fallback(message: Message, lang: str) -> None:
    await message.answer(t(lang, "send_a_file"))
