"""نقطه اجرا: اول سوکتِ وبهوک را بالا می‌آوریم (گوش می‌دهد)، بعد وبهوک را ثبت می‌کنیم.

این ترتیب مهم است: اگر وبهوک قبل از گوش‌دادنِ سوکت ثبت شود، سرورِ محلی هنگام
تحویلِ آپدیت‌ها Connection refused می‌گیرد و می‌تواند به بن‌بست منجر شود.
"""
from __future__ import annotations

import asyncio
import logging
import signal

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


async def _init_arq(dp: Dispatcher) -> None:
    try:
        dp.workflow_data["arq_pool"] = await asyncio.wait_for(
            create_pool(RedisSettings.from_dsn(settings.redis_url)), timeout=15
        )
        log.info("ARQ pool ready.")
    except Exception as exc:  # noqa: BLE001
        log.error("ARQ pool init failed (operations unavailable until fixed): %s", exc)


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


async def _serve() -> None:
    bot = create_bot()
    dp = create_dispatcher()

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=settings.webhook_secret
    ).register(app, path=settings.webhook_path)
    setup_application(app, dp, bot=bot)

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/healthz", health)

    # ۱) سوکت را بالا بیاور تا گوش بدهد — قبل از هر کار دیگری
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.web_port)
    await site.start()
    log.info("HTTP server listening on :%s", settings.web_port)

    # ۲) کارهای راه‌اندازی — حالا که سوکت آماده است
    await _wait_db()
    await _init_arq(dp)
    # وبهوک را با تایم‌اوت ثبت کن (سوکت از قبل گوش می‌دهد → تحویل موفق می‌شود)
    try:
        await asyncio.wait_for(_register_webhook(bot, dp), timeout=90)
    except asyncio.TimeoutError:
        log.error("webhook registration timed out")
    try:
        await asyncio.wait_for(_set_commands(bot), timeout=15)
    except asyncio.TimeoutError:
        log.warning("set_my_commands timed out")
    log.info("Startup complete.")

    # ۳) تا سیگنالِ توقف بمان
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()

    # ۴) خاموشیِ تمیز
    log.info("Shutting down…")
    pool = dp.workflow_data.get("arq_pool")
    if pool is not None:
        try:
            await pool.aclose()
        except Exception:  # noqa: BLE001
            pass
    try:
        await bot.delete_webhook()
    except Exception:  # noqa: BLE001
        pass
    await runner.cleanup()
    await bot.session.close()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
