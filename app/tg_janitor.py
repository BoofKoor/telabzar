"""پاک‌سازیِ خودکارِ پوشهٔ سرورِ محلیِ Bot API (`tg-bot-api-data`).

سرورِ محلیِ تلگرام هر فایلی را که یک‌بار `getFile` شده در
`<dir>/<token>/<type>/` نگه می‌دارد و **هیچ‌وقت پاک نمی‌کند**. ربات هم زیاد
`getFile` می‌زند: هر ویدیو/عکسِ آپلودی برای فیلترِ محتوا (`tasks.run_screen`)،
هر ورودیِ عملیات (`tasks._localize`)، و هر لینکِ `/dl` و `/s` (`gateway`). پس
این پوشه بی‌انتها بزرگ می‌شود. اندازه‌گیریِ تولید (۲۰۲۶-۱۰-۰۴): **۱۰۵ ویدیو و
۹۴٫۷ گیگابایت در یک روز**، دیسکِ ۱۱۷ گیگی را پر کرد و هم‌زمان Postgres و Redis
و خودِ `local-bot-api` از کار افتادند — یعنی ربات کاملاً خاموش شد.

دو قاعده، هر `INTERVAL` ثانیه:

1. **سن:** فایلِ رسانهٔ قدیمی‌تر از `tg_files_max_age_hours` پاک می‌شود (۰ = خاموش).
2. **کفِ فضای آزاد:** اگر فضای آزادِ همان دیسک زیرِ `tg_files_min_free_gb` بود،
   قدیمی‌ترین فایل‌ها یکی‌یکی پاک می‌شوند تا به کف برسد (۰ = خاموش). این قاعده
   برای جهشِ ناگهانیِ مصرف است، که قاعدهٔ سن به‌تنهایی جلویش را نمی‌گیرد.

چه چیزی **هرگز** پاک نمی‌شود:

* فایل‌های خودِ پوشهٔ ربات (`<dir>/<token>/td.binlog` و هر فایلِ هم‌سطحش) — نشستِ
  ورودِ ربات آن‌جاست. فقط فایل‌های **داخلِ زیرپوشه‌ها** (`videos/`, `documents/`,
  `temp/`, …) نامزدند.
* هر فایلی که در `GUARD_SEC` اخیر نوشته شده — دانلودِ در جریان یا فایلی که همین
  الان کاری رویش اجرا می‌شود.
* لینکِ نمادین، و هر نامی که شبیهِ دیتابیس/binlog است.

پاک‌کردن امن است چون فایل همچنان روی سرورهای تلگرام هست: TDLib (زیرِ سرورِ
محلی) فایلِ محلیِ گم‌شده را در `getFile`ِ بعدی دوباره دانلود می‌کند. یعنی هزینهٔ
پاک‌کردنِ فایلی که هنوز لازم است یک دانلودِ دوباره است، نه خطا.

**عمداً به Postgres/Redis وابسته نیست:** وقتی دیسک پر است Postgres خودش
`unhealthy` است و Redis نوشتن را قفل کرده (`MISCONF`) — دقیقاً همان لحظه‌ای که این
سرویس بیشترین لزوم را دارد. پس خواندنِ تنظیمات کران‌دار است و روی هر خطا به
پیش‌فرض‌های `config` برمی‌گردد، و در compose هم `depends_on` ندارد.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import stat
import time
from dataclasses import dataclass

from . import settings_store
from .config import settings

log = logging.getLogger("telabzar.janitor")

ROOT = os.environ.get("TG_API_DIR", "/var/lib/telegram-bot-api")
INTERVAL = 300          # ثانیه بینِ دو دور
GUARD_SEC = 30 * 60     # فایلِ نوشته‌شده در این بازه هرگز پاک نمی‌شود
_SETTINGS_TIMEOUT = 5   # خواندنِ تنظیمات نباید یک دور را گیر بیندازد
_GB = 1024 ** 3


@dataclass
class Sweep:
    """نتیجهٔ یک دور: چند فایل و چند بایت پاک شد، و فضای آزادِ بعدش."""
    files: int = 0
    bytes: int = 0
    free_after: int = 0


def _protected(name: str) -> bool:
    n = name.lower()
    return n.endswith(".binlog") or ".sqlite" in n or n.endswith(".db")


def _candidates(root: str) -> list[tuple[float, int, str]]:
    """(mtime, حجم, مسیر) برای هر فایلِ رسانه — فقط داخلِ زیرپوشه‌های پوشهٔ ربات.

    `root/<token>/<type>/file` یعنی پوشهٔ والد دست‌کم دو سطح زیرِ `root` است؛
    فایل‌های خودِ `root` و خودِ `root/<token>` (جایی که `td.binlog` است) کنار
    می‌روند. `os.walk` لینکِ نمادین را دنبال نمی‌کند و `lstat` لینک را رد می‌کند.
    """
    out: list[tuple[float, int, str]] = []
    for dirpath, _dirs, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth < 2:
            continue
        for name in files:
            if _protected(name):
                continue
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                out.append((st.st_mtime, st.st_size, path))
    return out


def _free_bytes(root: str) -> int:
    return shutil.disk_usage(root).free


def _remove(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def sweep(root: str, max_age_hours: int, min_free_gb: int, *,
          now: float | None = None, free_fn=None) -> Sweep:
    """یک دورِ پاک‌سازی. همگام — در thread اجرا می‌شود."""
    free_fn = free_fn or _free_bytes
    res = Sweep()
    if not os.path.isdir(root):
        return res
    now = time.time() if now is None else now
    guard = now - GUARD_SEC
    files = _candidates(root)
    kept: list[tuple[float, int, str]] = []

    if max_age_hours > 0:
        cutoff = min(now - max_age_hours * 3600, guard)
        for mtime, size, path in files:
            if mtime < cutoff and _remove(path):
                res.files += 1
                res.bytes += size
            else:
                kept.append((mtime, size, path))
    else:
        kept = files

    if min_free_gb > 0:
        floor = min_free_gb * _GB
        if free_fn(root) < floor:
            for mtime, size, path in sorted(kept):       # قدیمی‌ترین اول
                if mtime >= guard:
                    break                                # بقیه همه تازه‌ترند
                if _remove(path):
                    res.files += 1
                    res.bytes += size
                    if free_fn(root) >= floor:
                        break

    try:
        res.free_after = free_fn(root)
    except OSError:
        res.free_after = 0
    return res


async def _setting(key: str, default: int) -> int:
    """تنظیمِ زمانِ‌اجرا، یا پیش‌فرض روی **هر** خطا/کندی (دیسکِ پر = DB/Redisِ خراب)."""
    try:
        return await asyncio.wait_for(settings_store.get_int(key, default), _SETTINGS_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        log.warning("janitor: reading %s failed (%s) — using default %s", key, exc, default)
        return default


async def run_once(root: str = ROOT) -> Sweep:
    age = await _setting("tg_files_max_age_hours", settings.tg_files_max_age_hours)
    floor = await _setting("tg_files_min_free_gb", settings.tg_files_min_free_gb)
    res = await asyncio.to_thread(sweep, root, age, floor)
    if res.files:
        log.info("janitor: removed %d files (%.1f GB); free now %.1f GB",
                 res.files, res.bytes / _GB, res.free_after / _GB)
    return res


async def run_forever(root: str = ROOT, interval: int = INTERVAL) -> None:
    try:
        settings_store.init_store(settings.redis_url)
    except Exception as exc:  # noqa: BLE001 — بدونِ Redis هم با پیش‌فرض‌ها کار می‌کند
        log.warning("janitor: settings store unavailable (%s) — defaults only", exc)
    log.info("janitor: watching %s every %ds", root, interval)
    while True:
        try:
            await run_once(root)
        except Exception:  # noqa: BLE001 — یک دورِ خراب نباید سرویس را بکشد
            log.exception("janitor: sweep failed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_forever())
