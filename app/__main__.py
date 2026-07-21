"""نقطه اجرا: long-polling در برابرِ سرورِ محلیِ Bot API.

polling (نه webhook) انتخاب شد چون ربات اتصالِ رو‌به‌بیرون به local-bot-api می‌زند
و به تغییرِ IP کانتینر (هنگام بازساخت) حساس نیست.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from arq import create_pool
from arq.connections import RedisSettings

from . import settings_store
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


async def _set_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands([BotCommand(command="start", description="شروع / Start")])
    except Exception as exc:  # noqa: BLE001
        log.warning("set_my_commands failed: %s", exc)


async def _run() -> None:
    bot = create_bot()
    dp = create_dispatcher()

    await _wait_db()
    settings_store.init_store(settings.redis_url)  # تنظیماتِ زمانِ‌اجرا (سقف‌ها و…)
    await _init_arq(dp)
    await _set_commands(bot)

    # polling و webhook متقابلاً منحصربه‌فردند → هر وبهوکِ قبلی را پاک کن
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("delete_webhook failed: %s", exc)

    log.info("Starting long-polling…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        pool = dp.workflow_data.get("arq_pool")
        if pool is not None:
            try:
                await pool.aclose()
            except Exception:  # noqa: BLE001
                pass
        await bot.session.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
