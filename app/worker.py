"""تنظیماتِ ورکرِ ARQ. اجرا:  arq app.worker.WorkerSettings"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from arq.connections import RedisSettings

from . import settings_store
from .bot import create_bot
from .config import settings
from .db import init_models
from .tasks import run_op, run_screen
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
    if settings.node_role:  # این پروسه یک نود است → heartbeat به رجیستریِ مستر بزن
        ctx["hb_task"] = asyncio.create_task(_node_heartbeat())
    log.info("Worker ready%s.", f" (node: {settings.node_role})" if settings.node_role else "")


async def startup_dl(ctx: dict) -> None:
    """startupِ ورکرِ دانلود + گزارشِ نسخهٔ موتورها برای صفحهٔ سلامت.

    پنل روی مستر است و gallery-dl/yt-dlp ندارد، پس نمی‌تواند خودش نسخه را بگیرد؛
    ولی وقتی اینستاگرام «پاسخِ نامعتبر» می‌دهد اولین سؤالِ ادمین همین است که موتور
    عقب افتاده یا سشن مرده. نسخه فقط با rebuild عوض می‌شود، پس یک‌بار سرِ استارت کافی است.
    """
    await startup(ctx)
    try:
        from . import downloader as D
        store = settings_store.get_store()
        vers = await D.engine_versions()
        who = settings.node_id or settings.node_role or "master"
        await store.r.set(f"dlver:{who}", json.dumps(
            {"who": who, "at": int(time.time()), **vers}), ex=30 * 86400)
        log.info("engine versions (%s): %s", who, vers)
    except Exception:  # noqa: BLE001 — تشخیص است، نباید استارتِ ورکر را بشکند
        log.debug("engine version report failed", exc_info=True)


async def startup_master(ctx: dict) -> None:
    """startupِ ورکرِ اصلیِ مستر + یک reaper که جاب‌های یتیمِ نودِ آفلاین را برمی‌گرداند."""
    await startup(ctx)
    if not settings.node_role:  # فقط روی مستر (نه روی نودها)
        ctx["reaper"] = asyncio.create_task(_reaper())


async def _node_heartbeat() -> None:
    """هر ~۲۰ ثانیه وضعیتِ نود را در Redisِ مستر ثبت می‌کند (پنل از رویش نودها را نشان می‌دهد)."""
    from . import nodes
    store = settings_store.get_store()
    nid = settings.node_id or settings.node_role
    while True:
        try:
            depth = await store.r.zcard(nodes.ROLES.get(settings.node_role, {}).get("queue", ""))
        except Exception:  # noqa: BLE001
            depth = 0
        await nodes.write_heartbeat(store.r, nid, {
            "name": settings.node_name or nid, "role": settings.node_role,
            "ver": "1", "load": depth, "done": nodes.jobs_done()})
        await asyncio.sleep(20)


async def _reaper() -> None:
    """هر ~۳۰ ثانیه: اگر نودِ processing زنده نیست، جاب‌های ماندهٔ صفِ proc را به صفِ
    مستر برمی‌گرداند تا معلق نمانند (بستنِ حفرهٔ N2: نودی که وسطِ کار می‌افتد)."""
    from . import nodes
    store = settings_store.get_store()
    while True:
        await asyncio.sleep(30)
        try:
            n = await nodes.reap_orphan_jobs(store.r)
            if n:
                log.warning("reaped %d orphan proc-job(s) → master queue", n)
        except Exception:  # noqa: BLE001
            pass


async def shutdown(ctx: dict) -> None:
    for key in ("hb_task", "reaper"):
        task = ctx.get(key)
        if task is not None:
            task.cancel()
    bot = ctx.get("bot")
    if bot is not None:
        await bot.session.close()


def _flatten_settings(cls: type) -> type:
    """صفاتِ ارث‌بری‌شده را در `__dict__`ِ **خودِ** کلاس کپی می‌کند.

    arq برای ساختِ ورکر `get_kwargs` را صدا می‌زند و آن‌جا فقط
    `settings_cls.__dict__` را می‌خواند (`arq/worker.py:889` در نسخهٔ ۰.۲۸) —
    و `__dict__` صفاتِ **ارث‌بری‌شده را ندارد**. پس یک
    `class X(WorkerSettings)`ِ ساده هیچ‌کدام از صفاتِ پدر را به arq نمی‌رساند:
    `functions` می‌افتد و ورکر با «at least one function or cron_job must be
    registered» (`arq/worker.py:236`) در حلقهٔ کرش می‌افتد، و — بی‌صداتر و
    بدتر — `redis_settings` هم می‌افتد، یعنی حتی اگر `functions` را دستی وصله
    کنی ورکر به `localhost:6379` وصل می‌شود نه به Redisِ ما.

    پس **هر** کلاسِ تنظیماتِ ARQ که از کلاسِ دیگری ارث می‌برد باید این دکوراتور
    را داشته باشد. مقادیرِ خودِ کلاس برنده‌اند (کپی فقط برای نامی انجام می‌شود
    که در `__dict__`ِ خودش نیست). `tests/test_worker_settings.py` این قاعده را
    برای هر کلاسی که در این ماژول تعریف شود تضمین می‌کند.
    """
    for name in dir(cls):
        if not name.startswith("_") and name not in cls.__dict__:
            setattr(cls, name, getattr(cls, name))
    return cls


class WorkerSettings:
    functions = [run_op, run_screen]
    on_startup = startup_master
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    job_timeout = 2000  # ویدیوی سنگین روی VPS ضعیف ممکن است طول بکشد (نوار+لغو داریم)
    keep_result = 3600


@_flatten_settings
class ProcessingWorkerSettings(WorkerSettings):
    """ورکرِ پردازش روی صفِ اختصاصی `arq:queue:proc` (فاز N2 / نودِ پردازش).

    همان `run_op` است، فقط روی صفِ جدا. نودِ processing این را اجرا می‌کند و opهای
    سنگینِ CPU (که `ops._enqueue` وقتی نودی زنده باشد به این صف می‌فرستد) را برمی‌دارد.
    ورودی را از HTTPِ Bot API می‌گیرد و خروجی را multipart آپلود می‌کند (چون روی نود
    ربات با `is_local=False` ساخته می‌شود؛ رجوع به `tasks._localize`). روی مستر لازم
    نیست اجرا شود — اگر نودی نباشد، جاب‌ها اصلاً به این صف نمی‌روند."""

    queue_name = "arq:queue:proc"
    max_jobs = 2  # نودِ پردازش معمولاً یک‌کاره است؛ سقفِ محافظه‌کار


class DownloadWorkerSettings:
    """ورکرِ اختصاصیِ دانلود (صفِ جدا). دانلودهای طولانی، opهای سریعِ ربات را
    مسدود نمی‌کنند و تایم‌اوتِ جدای خودشان را دارند. این ورکر همان seedِ «نود»ِ
    آینده است: یک نود = همین ورکر روی IP تمیز که صفِ dl را برمی‌دارد."""

    functions = [run_download]
    queue_name = "arq:queue:dl"
    on_startup = startup_dl
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 3          # سقفِ سختِ هم‌زمانی (علاوه بر گاردِ runtimeِ dl_concurrency)
    job_timeout = 5400    # دانلودِ بزرگ ممکن است طول بکشد (۱.۵ ساعت)
    keep_result = 600


@_flatten_settings
class MasterDownloadWorkerSettings(DownloadWorkerSettings):
    """ورکرِ دانلودِ **مستر** روی صفِ جدا `arq:queue:dl:master`.

    وقتی یک نودِ دانلود آنلاین است، `download.py` جاب‌ها را به `arq:queue:dl` می‌فرستد که
    **فقط نود** برش می‌دارد (IPِ تمیز) — پس دانلودها روی مستر (IPِ دیتاسنترِ فلگ‌شده) نمی‌افتند
    و «یکی‌درمیان»‌شدنِ بات‌چکِ یوتیوب از بین می‌رود. نودی نباشد → `download.py` به همین صف
    می‌فرستد و مستر همه را برمی‌دارد (fallback). اگر نود وسطِ کار بیفتد، reaper جاب‌های ماندهٔ
    `arq:queue:dl` را به این صف برمی‌گرداند. نود دست‌نخورده می‌ماند (همان `DownloadWorkerSettings`
    روی `arq:queue:dl`) — پس نیازی به نصبِ دوبارهٔ نود نیست."""

    queue_name = "arq:queue:dl:master"
