"""ساختِ Bot و Dispatcher."""
from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from .config import settings
from .db import Sessionmaker
from .middlewares import DataMiddleware
from .routers import files, start


def create_bot() -> Bot:
    session = AiohttpSession(
        api=TelegramAPIServer.from_base(settings.local_api_base, is_local=True)
    )
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    dp.include_router(start.router)
    dp.include_router(files.router)

    data_mw = DataMiddleware(Sessionmaker)
    dp.message.outer_middleware(data_mw)
    dp.callback_query.outer_middleware(data_mw)

    return dp
