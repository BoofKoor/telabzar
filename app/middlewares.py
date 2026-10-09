"""میان‌افزارها: نشستِ DB + بارگذاریِ کاربر + تزریقِ زبان."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import textstore
from .config import settings
from .models import User


async def _find_user(session, tg_user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    return result.scalar_one_or_none()


def _tg_names(tg_user) -> tuple[str | None, str | None]:
    """یوزرنیم و نامِ کامل از شیءِ تلگرامی، بریده به عرضِ ستون.

    Postgres طولِ `VARCHAR(n)` را اعمال می‌کند و SQLiteِ تست‌ها نه (§۷)، پس برش در
    پایتون است. `getattr` چون تست‌ها شیءِ حداقلی (فقط `id`) می‌دهند.
    """
    username = (getattr(tg_user, "username", None) or "").strip() or None
    first = (getattr(tg_user, "first_name", None) or "").strip()
    last = (getattr(tg_user, "last_name", None) or "").strip()
    full = " ".join(x for x in (first, last) if x) or None
    return (username[:64] if username else None, full[:128] if full else None)


async def get_or_create_user(session, tg_user: TgUser) -> User:
    """کاربر را بخوان یا بساز — امن در برابرِ دو آپدیتِ هم‌زمانِ کاربرِ تازه.

    `SELECT` بعد `INSERT` یک check-then-act است: اولین پیامِ یک کاربرِ تازه اغلب
    با چند آپدیتِ هم‌زمان می‌رسد (آلبوم، فوروارد، دکمهٔ /start + پیام)، aiogram
    آن‌ها را موازی هندل می‌کند، هر دو `None` می‌بینند و دومی روی ستونِ یکتای
    `tg_user_id` با `IntegrityError` می‌میرد — یعنی همان پیامِ اولِ کاربر بی‌جواب
    می‌ماند. روی تعارض، ردیفِ برنده وجود دارد: rollback و دوباره بخوان.
    """
    username, full_name = _tg_names(tg_user)
    user = await _find_user(session, tg_user.id)
    if user is None:
        user = User(tg_user_id=tg_user.id, role="user",
                    username=username, full_name=full_name)
        session.add(user)
        user.last_seen = datetime.now(timezone.utc)
        try:
            await session.commit()
            return user
        except IntegrityError:
            await session.rollback()
            user = await _find_user(session, tg_user.id)
            if user is None:      # تعارض از جای دیگری بود — پنهانش نکن
                raise
    # فقط وقتی عوض شده بنویس؛ همان commitِ last_seen، پس رفت‌وبرگشتِ تازه ندارد.
    # یوزرنیمِ **برداشته‌شده** هم پاک می‌شود: یوزرنیمِ رهاشده در تلگرام به دیگری
    # می‌رسد، و نشان‌دادنِ نسخهٔ کهنه یعنی پنل کاربر را با آدمِ دیگری یکی بگیرد.
    # فقط شیءِ حداقلیِ تست (بی `username`) چیزی را پاک نمی‌کند.
    if hasattr(tg_user, "username") and user.username != username:
        user.username = username
    if hasattr(tg_user, "first_name") and user.full_name != full_name:
        user.full_name = full_name
    user.last_seen = datetime.now(timezone.utc)
    await session.commit()
    return user


class DataMiddleware(BaseMiddleware):
    """برای هر آپدیت: نشستِ DB باز می‌کند، کاربر را می‌سازد/می‌خواند، زبان را تزریق می‌کند."""

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        await textstore.refresh_if_stale()  # متن‌های ویرایش‌شدهٔ ادمین را بین‌پروسه‌ای تازه کن
        async with self.sessionmaker() as session:
            data["session"] = session
            tg_user: TgUser | None = data.get("event_from_user")
            user = None
            if tg_user is not None and not tg_user.is_bot:
                user = await get_or_create_user(session, tg_user)
            data["user"] = user
            data["lang"] = (user.lang if user and user.lang else settings.default_lang)
            is_admin = bool(tg_user and tg_user.id in settings.admin_id_set)
            data["is_admin"] = is_admin
            # کاربرِ بلاک‌شده: هیچ پاسخی نمی‌گیرد (ادمین هرگز بلاک نمی‌شود تا خودش را قفل نکند).
            if user is not None and user.is_blocked and not is_admin:
                return None
            return await handler(event, data)
