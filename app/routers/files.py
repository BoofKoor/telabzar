"""دریافتِ فایل → کارت (خودِ فایل + کیبورد زیرش)."""
from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..cards import send_card
from ..filetypes import detect
from ..i18n import t
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
    await state.clear()  # فایلِ جدید، هر فلوی نیمه‌کارهٔ FSM را لغو می‌کند
    info = detect(message)
    if info is None or user is None:
        return

    file = File(
        ref=_new_ref(),
        owner_id=user.id,
        file_unique_id=info.file_unique_id,
        file_id=info.file_id,
        kind=info.kind,
        mime=info.mime,
        name=info.name,
        size=info.size,
        width=info.width,
        height=info.height,
        duration=info.duration,
        changelog=[],
    )
    session.add(file)
    await session.commit()

    # کارت = خودِ فایل، دوباره فرستاده‌شده با کیبورد زیرش
    await send_card(message.bot, message.chat.id, file, lang)
    # پیامِ آپلودیِ کاربر را پاک کن تا چت تمیز بماند (در چتِ خصوصی مجاز است)
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass


@router.message()
async def fallback(message: Message, lang: str) -> None:
    await message.answer(t(lang, "send_a_file"))
