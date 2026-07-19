"""دریافتِ فایل → کارتِ عملیات."""
from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..cards import card_text
from ..filetypes import detect
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
    message: Message, session: AsyncSession, user: User | None,
    lang: str, state: FSMContext,
) -> None:
    await state.clear()  # ارسالِ فایلِ جدید، هر فلوی نیمه‌کارهٔ FSM را لغو می‌کند
    info = detect(message)
    if info is None or user is None:
        return

    ref = _new_ref()
    file = File(
        ref=ref,
        owner_id=user.id,
        file_unique_id=info.file_unique_id,
        file_id=info.file_id,
        kind=info.kind,
        mime=info.mime,
        name=info.name,
        size=info.size,
    )
    session.add(file)
    await session.commit()

    await message.answer(card_text(file, lang), reply_markup=file_card_kb(ref, info.kind, lang))


@router.message()
async def fallback(message: Message, lang: str) -> None:
    await message.answer(t(lang, "send_a_file"))
