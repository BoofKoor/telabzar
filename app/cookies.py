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
HEALTHY, SUSPECT, INVALID, COOLDOWN, DISABLED, FROZEN = (
    "healthy", "suspect", "invalid", "cooldown", "disabled", "frozen")

_INVALID_AT = 3            # این تعداد خطای پشتِ‌هم = «باطل، نیازِ تعویض»
_COOLDOWN_SEC = 1800       # کول‌داونِ پایه (پلکانی می‌شود)
_RATE_COOLDOWN = 3600      # سرعت‌گیر: استراحتِ بلند، **بدونِ** ضربه به اکانت

# ── دسته‌بندیِ خطا ───────────────────────────────────────────────
# شمارندهٔ «۳ خطای پشتِ‌هم = باطل» خام بود: یک محدودیتِ نرخ (که یعنی *ما* تند رفتیم)
# با یک لاگین‌نداشتنِ واقعی یکی حساب می‌شد. حالا هر خطا دسته می‌گیرد و واکنش فرق می‌کند.
RATE_LIMIT, CHECKPOINT, LOGIN_REQUIRED, BOT_CHECK, UNRELATED = (
    "rate_limit", "checkpoint", "login_required", "bot_check", "unrelated")

_CLASS_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # ترتیب مهم است: خاص‌ترین اول. «چک‌پوینت» باید قبل از «لاگین» بیاید چون
    # پیامِ چک‌پوینت معمولاً کلمهٔ login را هم دارد.
    (CHECKPOINT, ("checkpoint", "challenge_required", "challenge required",
                  "two-factor", "two factor", "2fa", "verify your account",
                  "confirm your identity", "suspicious login", "account has been disabled")),
    (RATE_LIMIT, ("rate-limit", "rate limit", "ratelimit", "too many requests", "429",
                  "please wait a few minutes", "try again later", "temporarily blocked")),
    (BOT_CHECK, ("sign in to confirm", "confirm you\u2019re not a bot", "confirm you're not a bot",
                 "not a bot")),
    (LOGIN_REQUIRED, ("login required", "login_required", "not logged", "sign in",
                      "requires authentication", "unauthorized", "401", "403",
                      "login page", "session expired", "csrf")),
)


def classify_error(msg: str) -> str:
    """پیامِ خطای موتور → دستهٔ آن (برای واکنشِ درست به اکانت)."""
    low = " ".join((msg or "").split()).lower()
    if not low:
        return UNRELATED
    for cls, hints in _CLASS_HINTS:
        if any(h in low for h in hints):
            return cls
    return UNRELATED


def needs_human(cls: str) -> bool:
    """آیا این خطا بدونِ دخالتِ انسان حل نمی‌شود؟ (چک‌پوینت/۲FA/اکانتِ بسته)"""
    return cls == CHECKPOINT


def burns_account(cls: str) -> bool:
    """آیا این خطا واقعاً به اعتبارِ اکانت می‌خورد؟ محدودیتِ نرخ **نمی‌خورد**."""
    return cls in (CHECKPOINT, LOGIN_REQUIRED, BOT_CHECK)


# ── متادیتا ─────────────────────────────────────────────────────
def _blank_meta(name: str) -> dict:
    return {"label": os.path.splitext(name)[0], "platform": guess_platform(name),
            "added": int(time.time()), "last_ok": 0, "fail_streak": 0, "disabled": False,
            "frozen": False, "last_error": "", "last_error_at": 0}


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
    if meta.get("frozen"):     # چک‌پوینت خورده — تا دخالتِ انسان استفاده نمی‌شود
        return FROZEN
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
    meta["frozen"] = False        # دوباره جواب داد → از صفِ «نیازمندِ رسیدگی» خارج
    meta["last_error"] = ""
    await set_meta(redis, name, meta)
    try:
        await redis.delete(_CK_CD + name)
    except Exception:  # noqa: BLE001
        pass


async def mark_fail(redis, name: str | None, cooldown: bool = True,
                    error_class: str = "", message: str = "") -> dict:
    """خطا → واکنشِ **متناسب با دستهٔ آن**، نه یک شمارندهٔ واحد.

    - `rate_limit`: فقط استراحتِ بلند. ضربه‌ای به اکانت نمی‌خورد — اکانت سالم است،
      ما تند رفته‌ایم؛ اگر ضربه بزنیم اکانتِ سالم را دور می‌ریزیم.
    - `checkpoint`: **فریز** + علامتِ نیازمندِ انسان. تلاشِ خودکارِ بیشتر فقط وضع را بدتر می‌کند.
    - بقیه (لاگین/بات‌چک): شمارنده + کول‌داونِ پلکانی (۳۰د → ۱س → ۲س …).
    """
    if not name or redis is None:
        return {}
    meta = await get_meta(redis, name)
    meta["last_error"] = (error_class or "") + ((" · " + " ".join(message.split())[:120])
                                                if message else "")
    meta["last_error_at"] = int(time.time())

    if error_class == RATE_LIMIT:
        await set_meta(redis, name, meta)
        try:
            await redis.set(_CK_CD + name, "1", ex=_RATE_COOLDOWN)
        except Exception:  # noqa: BLE001
            pass
        return meta

    if error_class == CHECKPOINT:
        meta["frozen"] = True
        await set_meta(redis, name, meta)
        return meta

    meta["fail_streak"] = int(meta.get("fail_streak") or 0) + 1
    await set_meta(redis, name, meta)
    if cooldown:
        sec = min(_COOLDOWN_SEC * (2 ** (meta["fail_streak"] - 1)), 6 * 3600)
        try:
            await redis.set(_CK_CD + name, "1", ex=sec)
        except Exception:  # noqa: BLE001
            pass
    return meta


async def unfreeze(redis, name: str) -> None:
    """ادمین رسیدگی کرد → از صفِ «نیازمندِ انسان» خارج شود."""
    meta = await get_meta(redis, name)
    meta["frozen"] = False
    meta["fail_streak"] = 0
    await set_meta(redis, name, meta)
    try:
        await redis.delete(_CK_CD + name)
    except Exception:  # noqa: BLE001
        pass


async def needs_attention(redis) -> list[dict]:
    """اکانت‌هایی که منتظرِ دخالتِ انسان‌اند (صفِ رسیدگی در پنل + هشدار)."""
    return [a for a in await accounts(redis) if a["status"] in (FROZEN, INVALID)]


# ── ورودیِ کوکی (پیست) ───────────────────────────────────────────
# این‌ها از پنل به این‌جا منتقل شدند چون **رباتْ هم** باید بتواند کوکی را بپذیرد
# (ادمین در پاسخِ هشدارِ چک‌پوینت، کوکیِ تازه را داخلِ تلگرام می‌چسباند). پنل
# فرآیندِ aiohttp/jinja است و رباتْ نباید به آن وابسته شود.
_REQUIRED_COOKIE = {"instagram": ("sessionid",), "youtube": ("LOGIN_INFO",),
                    "twitter": ("auth_token",), "tiktok": ("sessionid",)}


def _looks_like_cookiejar(text: str) -> bool:
    """اعتبارسنجیِ سبک: هدرِ Netscape یا خطوطِ tab-جدا (domain\\tflag\\t...)."""
    head = text.lstrip()[:200].lower()
    if head.startswith("# netscape") or "# http cookie file" in head:
        return True
    for line in text.splitlines():
        if line and not line.startswith("#") and line.count("\t") >= 5:
            return True
    return False

def _json_to_netscape(text: str) -> str | None:
    """خروجیِ JSONِ افزونه‌ها (Cookie-Editor / EditThisCookie) را به cookies.txtِ
    Netscape تبدیل می‌کند تا کاربر لازم نباشد فرمت را دستی عوض کند."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict):  # بعضی خروجی‌ها آرایه را می‌پیچند
        for key in ("cookies", "Request Cookies", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return None
    lines = ["# Netscape HTTP Cookie File", "# ساخته‌شده از خروجیِ JSON توسطِ پنلِ تل‌ابزار"]
    used = False
    for c in data:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        domain = c.get("domain") or c.get("host")
        if not name or not domain:
            continue
        value = c.get("value", "") or ""
        path = c.get("path") or "/"
        secure = bool(c.get("secure"))
        host_only = c.get("hostOnly")
        if host_only is None:
            host_only = not str(domain).startswith(".")
        include_sub = not host_only
        if include_sub and not str(domain).startswith("."):
            domain = "." + str(domain)
        exp = c.get("expirationDate") or c.get("expires") or c.get("expiry") or 0
        try:
            exp = max(0, int(float(exp)))
        except (TypeError, ValueError):
            exp = 0
        lines.append("\t".join([
            str(domain), "TRUE" if include_sub else "FALSE", str(path),
            "TRUE" if secure else "FALSE", str(exp), str(name), str(value),
        ]))
        used = True
    return "\n".join(lines) + "\n" if used else None

def _normalize_cookie_text(text: str) -> tuple[str | None, str]:
    """(متنِ Netscape یا None, پیامِ خطا). JSONِ افزونه‌ها هم پذیرفته می‌شود."""
    # BOM/کاراکترهای صفرعرض هنگامِ کپی‌پیست از فایل یا مرورگر می‌آیند و JSON را می‌شکنند
    text = (text or "").replace("﻿", "").replace("​", "").replace("‎", "").strip()
    if not text:
        return None, "چیزی چسبانده نشد."
    if len(text) > 512 * 1024:
        return None, "متن خیلی بزرگ است."
    if _looks_like_cookiejar(text):
        return text, ""
    converted = _json_to_netscape(text)
    if converted:
        return converted, ""
    return None, "نه cookies.txt (Netscape) است نه JSONِ معتبرِ کوکی."

def _check_required(text: str, platform: str) -> str:
    """پیامِ خطا اگر کوکیِ کلیدیِ آن پلتفرم در متن نباشد (وگرنه رشتهٔ خالی)."""
    need = _REQUIRED_COOKIE.get(platform)
    if not need:
        return ""
    if any(n in text for n in need):
        return ""
    return (f"کوکیِ «{need[0]}» در متن پیدا نشد — مطمئن شو از اکانتِ لاگین‌شده "
            f"و برای دامنهٔ درست کپی کرده‌ای.")

async def _save_cookie(redis, name: str, text: str) -> str:
    """نوشتن روی دیسکِ مستر + آینهٔ Redis. پیامِ خطا یا رشتهٔ خالی."""
    dest = os.path.join(settings.cookies_dir, name)
    try:
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(dest, 0o600)  # best-effort
    except OSError:
        return "ذخیره نشد."
    except Exception:  # noqa: BLE001
        pass
    await _mirror_cookie(redis, name, text)  # تا نودها هم ببینند
    return ""

async def _mirror_cookie(redis, name: str, content: str) -> None:
    try:
        await redis.sadd(_CK_SET, name)
        await redis.set(_CK_CONTENT + name, content)
    except Exception:  # noqa: BLE001
        pass

async def _unmirror_cookie(redis, name: str) -> None:
    try:
        await redis.srem(_CK_SET, name)
        await redis.delete(_CK_CONTENT + name)
    except Exception:  # noqa: BLE001
        pass

