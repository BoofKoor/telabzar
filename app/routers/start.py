"""‏/start و انتخابِ زبان."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..callbacks import Lang
from ..i18n import t
from ..keyboards import lang_keyboard
from ..models import User

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, user: User | None, lang: str) -> None:
    if user is None or not user.lang:
        await message.answer(t(lang, "choose_language"), reply_markup=lang_keyboard())
    else:
        await message.answer(t(lang, "welcome"))


@router.callback_query(Lang.filter())
async def choose_lang(
    cq: CallbackQuery,
    callback_data: Lang,
    session: AsyncSession,
    user: User | None,
) -> None:
    code = callback_data.code if callback_data.code in ("fa", "en") else "fa"
    if user is not None:
        user.lang = code
        await session.commit()
    if isinstance(cq.message, Message):
        await cq.message.edit_text(t(code, "welcome"))
    await cq.answer(t(code, "language_set"))
