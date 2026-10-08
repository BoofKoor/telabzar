"""لاگِ ماندگارِ پایانِ دانلودها — جدولِ `download_events`.

تا این ماژول، تاریخچهٔ دانلود فقط دو جا بود و هیچ‌کدام کافی نبود: ردیفِ `File`
(فقط موفق‌ها، چون دانلودِ شکست‌خورده فایلی نمی‌سازد) و شمارنده‌های `dlstat:*`
(دو روز عمر، بدونِ کاربر و بدونِ علت). پس «چرا دیروز دانلودهای اینستاگرامِ این
کاربر افتاد» سؤالِ بی‌جوابی بود. یک ردیف به‌ازای هر **پایان**ِ یک جابِ دانلود:

* `start(payload)` رکوردِ آغازین را می‌سازد (کاربر، پلتفرم، لینک، فاز).
* `settle(ev, outcome, …)` نتیجه را می‌نشاند — **اولین نتیجه برنده است**، پس
  شاخه‌ای که دیرتر می‌رسد (مثلاً `finally`ِ بیرونی) نتیجهٔ دقیقِ داخلی را با
  «crash» بازنویسی نمی‌کند.
* `record(ev)` می‌نویسد؛ ev بدونِ نتیجه (منوی کیفیت که هنوز pick نشده) نوشته
  نمی‌شود — جابِ fetchِ بعدی نتیجهٔ واقعی را ثبت می‌کند.

**نوشتن بهترین‌تلاش است و هرگز دانلود را نمی‌شکند**: هر خطا بلعیده می‌شود، زمان با
`WRITE_TIMEOUT` کران دارد، و فقط **اولین** شکستِ هر پروسه یک WARNING می‌دهد (Postgresِ
خوابیده نباید لاگ را با یک خط به‌ازای هر دانلود پر کند). مسیرِ لغو `record_soon` را
صدا می‌زند که منتظر نمی‌ماند، چون await کردن وسطِ لغوِ جاب همان «لغوِ خودت را
ببلع»ی است که §۷ ثبت کرده.

`outcome`:
    ok         فایل به کاربر رسید (از کش هم: `cached=True`)
    fail       سرویس نتوانست (موتور، شبکه، ارسال)
    blocked    سیاستِ محتوا رد کرد — شکستِ سرویس نیست
    refused    سقف/حجم/مدت/شلوغی/فضای دیسک — شکستِ سرویس نیست
    cancelled  کاربر لغو کرد
"""
from __future__ import annotations

import asyncio
import logging
import time

from .db import Sessionmaker
from .models import DownloadEvent

log = logging.getLogger("telabzar.dl_events")

OK, FAIL, BLOCKED, REFUSED, CANCELLED = "ok", "fail", "blocked", "refused", "cancelled"
OUTCOMES = (OK, FAIL, BLOCKED, REFUSED, CANCELLED)

#: سقفِ زمانِ یک نوشتن. کاربر منتظرش نیست (بعد از تحویل است)، ولی جاب هم نباید
#: پشتِ یک Postgresِ گیرکرده بماند.
WRITE_TIMEOUT = 5.0

#: ستون‌های قابلِ‌نوشتن — از خودِ مدل، نه فهرستِ دستی؛ کلیدِ ناشناخته دور ریخته می‌شود.
_COLS = frozenset(c.name for c in DownloadEvent.__table__.columns) - {"id", "created_at"}

#: عرضِ ستون‌های رشته‌ای، از خودِ مدل. Postgres طول را اعمال می‌کند و SQLiteِ تست‌ها نه
#: (§۷)، پس برش در پایتون است — وگرنه یک لینکِ بلند کلِ ردیف را می‌انداخت.
_LIMITS = {c.name: c.type.length for c in DownloadEvent.__table__.columns
           if getattr(c.type, "length", None)}

_pending: set[asyncio.Task] = set()
_warned = False


def start(payload: dict) -> dict:
    """رکوردِ آغازینِ یک جاب، از payloadی که روتر صف کرده."""
    return {
        "owner_id": payload.get("owner_id"),
        "tg_user_id": payload.get("tg_user_id"),
        "platform": payload.get("platform"),
        "url": payload.get("url"),
        "selector": payload.get("selector"),
        "engine": payload.get("engine"),
        "phase": payload.get("phase"),
        "_t0": time.monotonic(),
    }


def settle(ev: dict | None, outcome: str, error_class: str | None = None,
           error: str | None = None, **fields) -> None:
    """نتیجه را بنشان — **فقط اگر هنوز ننشسته باشد**.

    چرا «اولین برنده است»: `run_download` شاخه‌های تودرتو دارد و لایهٔ بیرونی روی هر
    استثنای فرارکرده «crash» می‌نشاند؛ اگر آخرین برنده بود، ردِ دقیقِ «حجم زیاد است»
    که درست پیش از یک استثنای بعدی نشسته بود با «crash» بازنویسی می‌شد.
    """
    if ev is None or ev.get("outcome"):
        return
    ev["outcome"] = outcome
    if error_class:
        ev["error_class"] = error_class
    if error:
        ev["error"] = error
    for k, v in fields.items():
        if v is not None:
            ev[k] = v


def row(ev: dict | None) -> dict | None:
    """ev → آرگومان‌های `DownloadEvent`؛ `None` یعنی چیزی برای ثبت نیست."""
    if not ev or ev.get("outcome") not in OUTCOMES:
        return None
    out = {k: v for k, v in ev.items() if k in _COLS and v is not None}
    t0 = ev.get("_t0")
    if t0 is not None and "took_ms" not in out:
        out["took_ms"] = max(0, int((time.monotonic() - t0) * 1000))
    for k, n in _LIMITS.items():
        if isinstance(out.get(k), str):
            out[k] = out[k][:n]
    out.setdefault("cached", False)
    return out


async def _write(kw: dict) -> None:
    async with Sessionmaker() as s:
        s.add(DownloadEvent(**kw))
        await s.commit()


async def _record_kw(kw: dict) -> None:
    global _warned
    try:
        await asyncio.wait_for(_write(kw), WRITE_TIMEOUT)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        if not _warned:
            _warned = True
            log.warning("download event not recorded (%s: %s); further failures at debug",
                        type(exc).__name__, str(exc)[:160])
        else:
            log.debug("download event not recorded: %s", exc)


async def record(ev: dict | None) -> None:
    """ev را بنویس (بهترین‌تلاش، کران‌دار). هرگز raise نمی‌کند جز لغوِ خودِ جاب."""
    kw = row(ev)
    if kw is not None:
        await _record_kw(kw)


def record_soon(ev: dict | None) -> None:
    """بدونِ انتظار بنویس — برای مسیرِ لغو، که await در آن لغو را می‌بلعد یا قطع می‌شود.

    مرجعِ قوی در `_pending` نگه داشته می‌شود، وگرنه asyncio تسکِ بی‌مرجع را
    می‌تواند وسطِ کار جمع کند.
    """
    kw = row(ev)
    if kw is None:
        return
    try:
        task = asyncio.get_running_loop().create_task(_record_kw(kw))
    except RuntimeError:
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)
