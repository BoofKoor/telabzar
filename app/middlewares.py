"""میان‌افزارها: نشستِ DB + بارگذاریِ کاربر + تزریقِ زبان."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .config import settings
from .models import User


async def get_or_create_user(session, tg_user: TgUser) -> User:
    result = await session.execute(
        select(User).where(User.tg_user_id == tg_user.id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(tg_user_id=tg_user.id, role="user")
        session.add(user)
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
