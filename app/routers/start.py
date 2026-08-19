"""‏/start، انتخابِ زبان، و منوهای کاربر (خوش‌آمد ← تنظیمات ← آموزش)."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..callbacks import Lang, Nav
from ..i18n import DEFAULT, available_languages, t
from ..keyboards import back_kb, home_kb, lang_keyboard, settings_kb
from ..models import User

router = Router(name="start")


async def _lang_menu(lang: str, current: str | None, back_to: str | None):
    """(متن, کیبورد) برای منوی انتخابِ زبان — فهرست از جدولِ زنده، نه هاردکد."""
    langs = await available_languages()
    return t(lang, "choose_language"), lang_keyboard(
        langs, lang, current=current, back_to=back_to)


@router.message(CommandStart())
async def cmd_start(message: Message, user: User | None, lang: str) -> None:
    # کاربری که زبانش را انتخاب کرده **هرگز دوباره پرسیده نمی‌شود**؛ فقط
    # خوش‌آمد + کلیدها می‌گیرد. (تنها نویسندهٔ `user.lang` هندلرِ زیر است، پس
    # «تهی» یعنی واقعاً هیچ‌وقت انتخاب نکرده.)
    if user is None or not user.lang:
        text, kb = await _lang_menu(lang, current=None, back_to=None)
        await message.answer(text, reply_markup=kb)
    else:
        await message.answer(t(lang, "welcome"), reply_markup=home_kb(lang))


@router.callback_query(Lang.filter())
async def choose_lang(
    cq: CallbackQuery,
    callback_data: Lang,
    session: AsyncSession,
    user: User | None,
) -> None:
    langs = await available_languages()
    code = callback_data.code if callback_data.code in langs else DEFAULT

    # «انتخابِ اول» در برابرِ «تغییر از تنظیمات» از **حالت** مشتق می‌شود نه از
    # callback: افزودنِ فیلد به `Lang` دکمه‌های در پرواز را می‌شکند (توضیحش در
    # `callbacks.Lang`). سالم است چون تنها راهِ رسیدنِ کاربرِ زبان‌دار به این
    # منو، تنظیمات است — `cmd_start` راهِ دیگر را می‌بندد.
    from_settings = bool(user is not None and user.lang)

    if user is not None:
        user.lang = code
        await session.commit()

    if isinstance(cq.message, Message):
        if from_settings:
            await cq.message.edit_text(
                t(code, "settings_title"), reply_markup=settings_kb(code))
        else:
            await cq.message.edit_text(
                t(code, "welcome"), reply_markup=home_kb(code))
    # تأیید **بصری** است نه متنی: منوی بعدی به زبانِ تازه رندر می‌شود. متنِ
    # `language_set` عمداً استفاده نمی‌شود چون لفظیِ per-language بود و برای
    # زبانِ ترجمه‌نشده به انگلیسی می‌افتاد — به کسی که اسپانیایی زده بود
    # می‌گفت «Language set to English». `answer()` خالی فقط چرخشِ دکمه را
    # می‌بندد، که تلگرام لازمش دارد.
    await cq.answer()


@router.callback_query(Nav.filter())
async def navigate(cq: CallbackQuery, callback_data: Nav,
                   user: User | None, lang: str) -> None:
    to = callback_data.to
    if isinstance(cq.message, Message):
        if to == "settings":
            await cq.message.edit_text(
                t(lang, "settings_title"), reply_markup=settings_kb(lang))
        elif to == "help":
            await cq.message.edit_text(
                t(lang, "help_text"), reply_markup=back_kb(lang, to="home"))
        elif to == "lang":
            current = user.lang if user and user.lang else None
            text, kb = await _lang_menu(lang, current=current, back_to="settings")
            await cq.message.edit_text(text, reply_markup=kb)
        else:  # home — و هر مقصدِ ناشناخته‌ای (دکمهٔ کهنه) به خانه برمی‌گردد
            await cq.message.edit_text(
                t(lang, "welcome"), reply_markup=home_kb(lang))
    await cq.answer()
