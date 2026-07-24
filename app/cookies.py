"""استخرِ کوکیِ اکانت‌ها — منبعِ واحدِ حقیقت برای پنل و ورکرِ دانلود.

مدلِ ذخیره‌سازی (هماهنگ با معماریِ نود):
- **محتوا** روی دیسکِ مستر (`cookies_dir/<name>.txt`) و **آینه در Redis** (`ckfiles` +
  `ckfile:<name>`) تا نودِ دانلود — که دیسکِ کوکی ندارد — هم بخواندشان.
- **متادیتای اکانت** در Redis (`ckmeta:<name>`): برچسب، پلتفرم، آخرین موفقیت، تعدادِ
  خطای پشتِ‌هم، غیرفعال. حالتِ نرم است؛ اگر پاک شود از رویِ فایل‌ها بازساخته می‌شود.
- **کول‌داون** در Redis (`ckcd:<name>`, TTL) — همان کلیدِ قبلی.

قاعدهٔ طلایی (خواستهٔ صریح): وقتی یک کوکی خطا داد، دانلود باید **با کوکیِ بعدی**
دوباره تلاش کند؛ فقط اگر **هیچ کوکیِ قابلِ‌استفاده‌ای نماند** به کاربر خطا بدهیم.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import time

from .config import settings

log = logging.getLogger("telabzar.cookies")

_CK_SET = "ckfiles"        # ست نام‌های کوکی (آینه برای نود)
_CK_CONTENT = "ckfile:"    # ckfile:<name> → محتوا
_CK_META = "ckmeta:"       # ckmeta:<name> → JSON متادیتای اکانت
_CK_CD = "ckcd:"           # ckcd:<name> → کول‌داون (TTL)
_CK_ROT = "ckrot:"         # ckrot:<platform> → شمارندهٔ چرخش

# وضعیت‌ها (به‌ترتیبِ اولویتِ استفاده)
HEALTHY, SUSPECT, INVALID, COOLDOWN, DISABLED = (
    "healthy", "suspect", "invalid", "cooldown", "disabled")

_INVALID_AT = 3            # این تعداد خطای پشتِ‌هم = «باطل، نیازِ تعویض»
_COOLDOWN_SEC = 1800       # کول‌داونِ پایه (پلکانی می‌شود)


# ── متادیتا ─────────────────────────────────────────────────────
def _blank_meta(name: str) -> dict:
    return {"label": os.path.splitext(name)[0], "platform": guess_platform(name),
            "added": int(time.time()), "last_ok": 0, "fail_streak": 0, "disabled": False}


def guess_platform(name: str) -> str:
    low = (name or "").lower()
    for key in ("instagram", "twitter", "tiktok", "youtube", "pinterest"):
        if key in low:
            return key
    return "other"


async def get_meta(redis, name: str) -> dict:
    meta = _blank_meta(name)
    if redis is None:
        return meta
    try:
        raw = await redis.get(_CK_META + name)
        if raw:
            meta.update(json.loads(raw))
    except Exception:  # noqa: BLE001
        pass
    return meta


async def set_meta(redis, name: str, meta: dict) -> None:
    if redis is None:
        return
    try:
        await redis.set(_CK_META + name, json.dumps(meta))
    except Exception as exc:  # noqa: BLE001
        log.debug("cookie meta write failed: %s", exc)


async def del_meta(redis, name: str) -> None:
    if redis is None:
        return
    try:
        await redis.delete(_CK_META + name)
        await redis.delete(_CK_CD + name)
    except Exception:  # noqa: BLE001
        pass


# ── فهرستِ نام‌ها (مستر: دیسک · نود: آینهٔ Redis) ────────────────
async def list_names(redis) -> tuple[list[str], bool]:
    """(نام‌ها, محلی‌بودن). محلی=True یعنی مستر (فایل روی دیسک)."""
    d = settings.cookies_dir
    if d and os.path.isdir(d):
        return sorted(os.path.basename(f) for f in glob.glob(os.path.join(d, "*.txt"))), True
    names: list[str] = []
    if redis is not None:
        try:
            raw = await redis.smembers(_CK_SET)
            names = sorted((n if isinstance(n, str) else n.decode()) for n in raw)
        except Exception:  # noqa: BLE001
            names = []
    return names, False


async def status_of(redis, name: str, meta: dict | None = None) -> str:
    meta = meta if meta is not None else await get_meta(redis, name)
    if meta.get("disabled"):
        return DISABLED
    if redis is not None:
        try:
            if await redis.exists(_CK_CD + name):
                return COOLDOWN
        except Exception:  # noqa: BLE001
            pass
    fs = int(meta.get("fail_streak") or 0)
    if fs >= _INVALID_AT:
        return INVALID
    return SUSPECT if fs > 0 else HEALTHY


async def accounts(redis, platform: str | None = None) -> list[dict]:
    """همهٔ اکانت‌ها با وضعیت (برای پنل). اگر platform داده شود، فیلتر می‌شود."""
    names, _local = await list_names(redis)
    out: list[dict] = []
    for n in names:
        meta = await get_meta(redis, n)
        if platform and meta.get("platform") != platform:
            continue
        st = await status_of(redis, n, meta)
        cd = 0
        if redis is not None and st == COOLDOWN:
            try:
                ttl = await redis.ttl(_CK_CD + n)
                cd = ttl if ttl and ttl > 0 else 0
            except Exception:  # noqa: BLE001
                cd = 0
        out.append({**meta, "name": n, "status": st, "cooldown": cd})
    return out


async def pool_summary(redis) -> dict[str, dict]:
    """platform → {healthy, suspect, invalid, cooldown, disabled, total}."""
    agg: dict[str, dict] = {}
    for a in await accounts(redis):
        p = a.get("platform") or "other"
        d = agg.setdefault(p, {"healthy": 0, "suspect": 0, "invalid": 0,
                               "cooldown": 0, "disabled": 0, "total": 0})
        d[a["status"]] = d.get(a["status"], 0) + 1
        d["total"] += 1
    return agg


async def healthy_count(redis, platform: str) -> int:
    return sum(1 for a in await accounts(redis, platform)
               if a["status"] in (HEALTHY, SUSPECT))


# ── انتخابِ کوکی برای یک تلاش ───────────────────────────────────
_USE_ORDER = (HEALTHY, SUSPECT, INVALID)  # کول‌داون/غیرفعال هرگز


async def pick(redis, platform: str, exclude: set[str] | None = None) -> str | None:
    """نامِ کوکیِ بعدیِ قابلِ‌استفاده برای این پلتفرم (یا None اگر چیزی نماند).

    اولویت: سالم → مشکوک → باطل (آخرین چاره؛ بهتر از هیچ). غیرفعال و کول‌داون رد
    می‌شوند. بینِ هم‌رتبه‌ها، **کم‌استفاده‌ترین** (قدیمی‌ترین `last_ok`) انتخاب می‌شود تا
    بار پخش شود و اکانت‌ها یکنواخت بسوزند."""
    exclude = exclude or set()
    ranked: list[tuple[int, int, str]] = []
    for a in await accounts(redis, platform):
        if a["name"] in exclude or a["status"] in (COOLDOWN, DISABLED):
            continue
        try:
            rank = _USE_ORDER.index(a["status"])
        except ValueError:
            continue
        ranked.append((rank, int(a.get("last_ok") or 0), a["name"]))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


async def materialize(redis, name: str, workdir: str | None) -> str | None:
    """نامِ کوکی → مسیرِ فایلِ قابلِ‌استفاده. مستر: مسیرِ دیسک. نود: از آینهٔ Redis در
    workdir می‌نویسد (با workdir پاک می‌شود)."""
    d = settings.cookies_dir
    if d and os.path.isdir(d):
        p = os.path.join(d, name)
        return p if os.path.exists(p) else None
    if redis is None or not workdir:
        return None
    try:
        content = await redis.get(_CK_CONTENT + name)
    except Exception:  # noqa: BLE001
        content = None
    if not content:
        return None
    try:
        ckdir = os.path.join(workdir, "ck")
        os.makedirs(ckdir, exist_ok=True)
        path = os.path.join(ckdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content if isinstance(content, str) else content.decode("utf-8", "replace"))
        return path
    except OSError:
        return None


# ── ثبتِ نتیجه (سلامتِ رایگان از رویِ دانلودهای واقعی) ───────────
async def mark_ok(redis, name: str | None) -> None:
    """موفقیت → صفرکردنِ خطاها + ثبتِ زمان (اکانت دوباره «سالم» می‌شود)."""
    if not name or redis is None:
        return
    meta = await get_meta(redis, name)
    meta["fail_streak"] = 0
    meta["last_ok"] = int(time.time())
    await set_meta(redis, name, meta)
    try:
        await redis.delete(_CK_CD + name)
    except Exception:  # noqa: BLE001
        pass


async def mark_fail(redis, name: str | None, cooldown: bool = True) -> dict:
    """خطای کوکی‌محور → افزایشِ خطا + کول‌داونِ **پلکانی** (۳۰د → ۱س → ۲س …)."""
    if not name or redis is None:
        return {}
    meta = await get_meta(redis, name)
    meta["fail_streak"] = int(meta.get("fail_streak") or 0) + 1
    await set_meta(redis, name, meta)
    if cooldown:
        sec = min(_COOLDOWN_SEC * (2 ** (meta["fail_streak"] - 1)), 6 * 3600)
        try:
            await redis.set(_CK_CD + name, "1", ex=sec)
        except Exception:  # noqa: BLE001
            pass
    return meta
