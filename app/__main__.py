"""نقطهٔ اجرا: سرورِ وبهوکِ aiohttp + ثبتِ وبهوک روی local-bot-api."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from arq import create_pool
from arq.connections import RedisSettings

from .bot import create_bot, create_dispatcher
from .config import settings
from .db import init_models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("telabzar")


async def _wait_db(attempts: int = 15, delay: float = 3.0) -> None:
    for i in range(1, attempts + 1):
        try:
            await init_models()
            log.info("Database ready.")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("DB not ready (%s/%s): %s", i, attempts, exc)
            await asyncio.sleep(delay)
    log.error("Database still not ready; continuing (will retry on demand).")


async def _register_webhook(bot: Bot, dp: Dispatcher, attempts: int = 20, delay: float = 3.0) -> None:
    allowed = dp.resolve_used_update_types()
    for i in range(1, attempts + 1):
        try:
            await bot.set_webhook(
                url=settings.webhook_url,
                secret_token=settings.webhook_secret,
                allowed_updates=allowed,
                drop_pending_updates=True,
            )
            log.info("Webhook registered → %s", settings.webhook_url)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("set_webhook failed (%s/%s): %s", i, attempts, exc)
            await asyncio.sleep(delay)
    log.error("Could not register webhook after retries.")


async def _set_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands([BotCommand(command="start", description="شروع / Start")])
    except Exception as exc:  # noqa: BLE001
        log.warning("set_my_commands failed: %s", exc)


def main() -> None:
    bot = create_bot()
    dp = create_dispatcher()

    async def on_startup(bot: Bot) -> None:
        await _wait_db()
        # استخرِ ARQ برای صف‌گذاریِ جاب‌ها → به هندلرها تزریق می‌شود
        dp.workflow_data["arq_pool"] = await create_pool(
            RedisSettings.from_dsn(settings.redis_url)
        )
        await _register_webhook(bot, dp)
        await _set_commands(bot)

    async def on_shutdown(bot: Bot) -> None:
        pool = dp.workflow_data.get("arq_pool")
        if pool is not None:
            await pool.aclose()
        try:
            await bot.delete_webhook()
        except Exception:  # noqa: BLE001
            pass

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=settings.webhook_secret
    ).register(app, path=settings.webhook_path)
    setup_application(app, dp, bot=bot)

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/healthz", health)

    log.info("Starting Telabzar bot (webhook) on :%s", settings.web_port)
    web.run_app(app, host="0.0.0.0", port=settings.web_port, print=None)


if __name__ == "__main__":
    main()
