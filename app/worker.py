"""تنظیماتِ ورکرِ ARQ. اجرا:  arq app.worker.WorkerSettings"""
from __future__ import annotations

import asyncio
import logging

from arq.connections import RedisSettings

from . import settings_store
from .bot import create_bot
from .config import settings
from .db import init_models
from .tasks import run_op
from .tasks_download import run_download

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("telabzar.worker")


async def startup(ctx: dict) -> None:
    for i in range(1, 16):
        try:
            await init_models()
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("worker: DB not ready (%s/15): %s", i, exc)
            await asyncio.sleep(3)
    # تایم‌اوتِ بلند: getFile (دانلودِ کامل از تلگرام) و آپلودِ نتیجه برای
    # فایل‌های بزرگ به‌راحتی از ۶۰ ثانیه می‌گذرد.
    ctx["bot"] = create_bot(request_timeout=600.0)
    settings_store.init_store(settings.redis_url)  # تنظیماتِ زمانِ‌اجرا (مثلِ whisper_model)
    from . import textstore
    await textstore.load()  # متن‌های override‌شدهٔ ادمین را پیش‌بارگذاری کن
    log.info("Worker ready.")


async def shutdown(ctx: dict) -> None:
    bot = ctx.get("bot")
    if bot is not None:
        await bot.session.close()


class WorkerSettings:
    functions = [run_op]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    job_timeout = 2000  # ویدیوی سنگین روی VPS ضعیف ممکن است طول بکشد (نوار+لغو داریم)
    keep_result = 3600


class DownloadWorkerSettings:
    """ورکرِ اختصاصیِ دانلود (صفِ جدا). دانلودهای طولانی، opهای سریعِ ربات را
    مسدود نمی‌کنند و تایم‌اوتِ جدای خودشان را دارند. این ورکر همان seedِ «نود»ِ
    آینده است: یک نود = همین ورکر روی IP تمیز که صفِ dl را برمی‌دارد."""

    functions = [run_download]
    queue_name = "arq:queue:dl"
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 3          # سقفِ سختِ هم‌زمانی (علاوه بر گاردِ runtimeِ dl_concurrency)
    job_timeout = 5400    # دانلودِ بزرگ ممکن است طول بکشد (۱.۵ ساعت)
    keep_result = 600
