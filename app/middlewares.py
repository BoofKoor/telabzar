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


async def get_or_create_user(session, tg_user: TgUser) -> User:
    """کاربر را بخوان یا بساز — امن در برابرِ دو آپدیتِ هم‌زمانِ کاربرِ تازه.

    `SELECT` بعد `INSERT` یک check-then-act است: اولین پیامِ یک کاربرِ تازه اغلب
    با چند آپدیتِ هم‌زمان می‌رسد (آلبوم، فوروارد، دکمهٔ /start + پیام)، aiogram
    آن‌ها را موازی هندل می‌کند، هر دو `None` می‌بینند و دومی روی ستونِ یکتای
    `tg_user_id` با `IntegrityError` می‌میرد — یعنی همان پیامِ اولِ کاربر بی‌جواب
    می‌ماند. روی تعارض، ردیفِ برنده وجود دارد: rollback و دوباره بخوان.
    """
    user = await _find_user(session, tg_user.id)
    if user is None:
        user = User(tg_user_id=tg_user.id, role="user")
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
