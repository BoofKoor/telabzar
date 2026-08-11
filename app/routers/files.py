"""دریافتِ فایل → کارت (خودِ فایل + کیبورد زیرش)."""
from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from .. import safety
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
    lang: str, state: FSMContext, arq_pool: ArqRedis,
) -> None:
    await state.clear()  # فایلِ جدید، هر فلوی نیمه‌کارهٔ FSM را لغو می‌کند
    info = detect(message)
    if info is None or user is None:
        return

    # فیلترِ بزرگسال، لایهٔ ارزان: نامِ فایل و کپشن، همین‌جا و بدونِ هیچ I/O.
    pol = await safety.load_policy()
    if pol.enabled:
        why = (safety.check_text(info.name) or safety.check_text(message.caption))
        if why:
            await message.reply(t(lang, "nsfw_blocked"))
            if await safety.report_block(message.bot, arq_pool, user.tg_user_id, why,
                                         pol, detail="نام/کپشنِ فایلِ آپلودی"):
                await message.answer(t(lang, "nsfw_user_blocked"))
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

    # عکس/ویدیو → قبل از ساختنِ کارت اسکن شود. **مکانیزم را دقیق بگوییم**، چون
    # نسخهٔ قبلیِ همین کامنت می‌گفت کارت یعنی «آپلودِ دوباره» و آن غلط است: کارت
    # با `file_id` می‌رود (`cards.py`)، تلگرام سمتِ خودش کپی می‌کند و رباتْ هیچ
    # بایتی آپلود نمی‌کند. ریسک پهنای‌باند نیست، **انتساب** است — پیامی که آن
    # محتوا را دارد از حسابِ ربات فرستاده شده. همین کافی است که گیت قبل از کارت
    # باشد نه بعدش. اسکن در ورکر است (کارِ CPU نباید حلقهٔ long-pollingِ ربات را
    # بگیرد)، پس این‌جا فقط یک یادداشتِ «در حالِ بررسی» می‌ماند که خودِ ورکر یا
    # کارت می‌کندش یا پیامِ رد.
    if pol.enabled and pol.scan_pixels and info.kind in safety.SCANNABLE_KINDS:
        note = await message.answer(t(lang, "nsfw_checking"))
        await arq_pool.enqueue_job("run_screen", {
            "file_id_row": file.id, "chat_id": message.chat.id,
            "note_mid": note.message_id, "lang": lang,
            "tg_user_id": user.tg_user_id,
        })
    else:
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
