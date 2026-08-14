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
import re
import time
from typing import NamedTuple

from . import settings_store
from .config import settings

log = logging.getLogger("telabzar.cookies")

_CK_SET = "ckfiles"        # ست نام‌های کوکی (آینه برای نود)
_CK_CONTENT = "ckfile:"    # ckfile:<name> → محتوا
_CK_META = "ckmeta:"       # ckmeta:<name> → JSON متادیتای اکانت
_CK_CD = "ckcd:"           # ckcd:<name> → کول‌داون (TTL)
_CK_ROT = "ckrot:"         # ckrot:<platform> → شمارندهٔ چرخش
#: `ckseen:<platform>` → «این سطل زمانی اکانت داشت». بی‌TTL و **هرگز پاک نمی‌شود**
#: (`del_meta` عمداً دست نمی‌زند). `ckrot` جایگزینش نیست: فقط وقتی زیاد می‌شود که
#: **دو یا چند** نامزدِ هم‌رتبه باشند، پس سطلی که همیشه یک اکانت داشت هرگز آن را
#: افزایش نمی‌دهد — سنجیده شد، و به همین دلیل سیگنالِ مشتق کنار گذاشته شد.
_CK_SEEN = "ckseen:"

# وضعیت‌ها (به‌ترتیبِ اولویتِ استفاده)
# `UNPROVEN` = آخرین اتفاقِ این اکانت یک **خطا** بود، نه یک موفقیت. لزوماً خراب
# نیست (شاید لینک بد بوده یا سایت پاسخ نداده)، ولی «سالم» نشان‌دادنش دروغ است:
# تنها چیزی که می‌دانیم این است که آخرین تلاش شکست خورد. این وضعیت اکانت را از
# چرخش خارج نمی‌کند، فقط بعد از اکانت‌های واقعاً موفق قرار می‌گیرد.
HEALTHY, SUSPECT, INVALID, COOLDOWN, DISABLED, FROZEN, UNPROVEN = (
    "healthy", "suspect", "invalid", "cooldown", "disabled", "frozen", "unproven")

_CK_USE = "ckuse:"         # ckuse:<name>:<yyyymmddHH> → مصرفِ ساعتی (سطلِ توکن)
_CK_LAST = "cklast:"       # cklast:<name> → زمانِ آخرین استفاده (فاصلهٔ حداقلی)
_CK_EXIT = "ckexit:"       # ckexit:<exit>:<platform>:<ok|fail>:<yyyymmdd>


# ── آمارِ هر خروجی (سشنِ مرده یا IPِ مسدود؟) ────────────────────
# آمارِ per-account به این سؤال جواب نمی‌دهد: وقتی **همهٔ** اکانت‌ها می‌افتند،
# مقصر معمولاً سشن‌ها نیستند بلکه IPی است که از آن بیرون می‌رویم. اینستاگرام IP
# را هویت می‌داند و رنجِ دیتاسنتر را می‌بندد. پس موفقیت/شکست را به تفکیکِ
# **خروجی** هم می‌شماریم تا پنل بتواند تفاوت را نشان دهد.
def _today_key() -> str:
    return time.strftime("%Y%m%d", time.gmtime())


def exit_label(node_id: str | None) -> str:
    return str(node_id or "") or "master"


async def note_exit(redis, node_id: str | None, platform: str, ok: bool) -> None:
    if redis is None or not platform:
        return
    try:
        k = (_CK_EXIT + exit_label(node_id) + ":" + platform
             + (":ok:" if ok else ":fail:") + _today_key())
        if await redis.incr(k) == 1:
            await redis.expire(k, 3 * 86400)
    except Exception:  # noqa: BLE001
        pass


_CK_EXIT_CD = "ckexitcd:"   # ckexitcd:<exit>:<platform> → خروجی موقتاً کنار گذاشته شد


async def cool_exit(redis, node_id: str | None, platform: str, seconds: int) -> None:
    """خروجی (نه اکانت) کنار گذاشته شود. وقتی IP مقصر است، کول‌داون‌دادن به
    اکانت‌ها دقیقاً اشتباهِ برعکس است — سشنِ سالم را از سرویس خارج می‌کند."""
    if redis is None or not platform or seconds <= 0:
        return
    try:
        await redis.set(f"{_CK_EXIT_CD}{exit_label(node_id)}:{platform}", "1", ex=seconds)
    except Exception:  # noqa: BLE001
        pass


async def exit_cooled(redis, node_id: str | None, platform: str) -> bool:
    if redis is None or not platform:
        return False
    try:
        return bool(await redis.exists(f"{_CK_EXIT_CD}{exit_label(node_id)}:{platform}"))
    except Exception:  # noqa: BLE001
        return False


async def exit_stats(redis, platform: str | None = None) -> list[dict]:
    """[{exit, platform, ok, fail, rate, blocked}] برای امروز.

    `blocked=True` یعنی «هیچ موفقیتی نداشته و چند بار هم شکست خورده» — قوی‌ترین
    نشانه‌ای که از این‌جا می‌شود داد که مشکل از خودِ خروجی است نه از اکانت‌ها.
    """
    if redis is None:
        return []
    day, agg = _today_key(), {}
    try:
        async for key in redis.scan_iter(match=f"{_CK_EXIT}*:{day}", count=500):
            k = key if isinstance(key, str) else key.decode()
            parts = k[len(_CK_EXIT):].rsplit(":", 3)     # exit, platform, kind, day
            if len(parts) != 4:
                continue
            ex, plat, kind, _d = parts
            if platform and plat != platform:
                continue
            row = agg.setdefault((ex, plat), {"exit": ex, "platform": plat,
                                              "ok": 0, "fail": 0})
            try:
                row[kind] = int(await redis.get(k) or 0)
            except (ValueError, TypeError):
                pass
    except Exception:  # noqa: BLE001
        return []
    out = []
    for row in agg.values():
        total = row["ok"] + row["fail"]
        row["rate"] = round(row["ok"] * 100 / total) if total else 0
        row["blocked"] = row["ok"] == 0 and row["fail"] >= 3
        out.append(row)
    out.sort(key=lambda r: (r["platform"], r["exit"]))
    return out


# ── سهمیه و سرعت‌گیر (همه از پنل تنظیم‌شدنی) ─────────────────────
# این اعداد تا دیروز ثابت بودند. حالا `Limits` یک عکسِ فوریِ مقادیرِ زنده است:
# ریاضیِ خالص **همگام** می‌ماند (تستِ ساده، بدونِ Redis) و فقط `load_limits()`
# ناهمگام است. هر تابعی که `lim` نگیرد به پیش‌فرضِ env برمی‌گردد، پس مسیرهای
# قدیمی و تست‌ها دست‌نخورده کار می‌کنند.
class Limits(NamedTuple):
    caps: dict[str, int]   # پلتفرم → سقفِ استفادهٔ ساعتیِ هر اکانت (۰ = نامحدود)
    cap_default: int       # پلتفرمِ خارج از فهرست
    min_gap: int           # ثانیه، بینِ دو استفاده از یک اکانت
    warmup_days: int
    warmup_floor: float    # سهمِ روزِ اول (۰..۱)
    cooldown: int          # ثانیه — کول‌داونِ پایهٔ خطا (پلکانی)
    rate_cooldown: int     # ثانیه — استراحتِ محدودیتِ نرخ
    invalid_at: int        # خطای پشتِ‌هم تا «باطل»


def _limits_from(cap_ig: int, cap_yt: int, cap_tw: int, cap_tt: int, cap_def: int,
                 gap: int, wd: int, wpct: int, cd_min: int, rate_min: int,
                 invalid: int) -> Limits:
    return Limits(caps={"instagram": max(0, cap_ig), "youtube": max(0, cap_yt),
                        "twitter": max(0, cap_tw), "tiktok": max(0, cap_tt)},
                  cap_default=max(0, cap_def), min_gap=max(0, gap),
                  warmup_days=max(0, wd), warmup_floor=min(1.0, max(0.0, wpct / 100.0)),
                  cooldown=max(60, cd_min * 60), rate_cooldown=max(60, rate_min * 60),
                  invalid_at=max(1, invalid))


def default_limits() -> Limits:
    """پیش‌فرضِ env — وقتی settings_store در دسترس نیست (تست/بوت)."""
    s = settings
    return _limits_from(s.ck_cap_instagram, s.ck_cap_youtube, s.ck_cap_twitter,
                        s.ck_cap_tiktok, s.ck_cap_default, s.ck_min_gap_sec,
                        s.ck_warmup_days, s.ck_warmup_pct, s.ck_cooldown_min,
                        s.ck_rate_cooldown_min, s.ck_invalid_at)


async def load_limits() -> Limits:
    """مقادیرِ زندهٔ پنل. یک‌بار سرِ هر عملیات خوانده و پایین پاس داده می‌شود."""
    s, g = settings, settings_store.get_int
    return _limits_from(
        await g("ck_cap_instagram", s.ck_cap_instagram),
        await g("ck_cap_youtube", s.ck_cap_youtube),
        await g("ck_cap_twitter", s.ck_cap_twitter),
        await g("ck_cap_tiktok", s.ck_cap_tiktok),
        await g("ck_cap_default", s.ck_cap_default),
        await g("ck_min_gap_sec", s.ck_min_gap_sec),
        await g("ck_warmup_days", s.ck_warmup_days),
        await g("ck_warmup_pct", s.ck_warmup_pct),
        await g("ck_cooldown_min", s.ck_cooldown_min),
        await g("ck_rate_cooldown_min", s.ck_rate_cooldown_min),
        await g("ck_invalid_at", s.ck_invalid_at))


def hourly_cap(platform: str, lim: Limits | None = None) -> int:
    """۰ = نامحدود (ادمین عمداً سرعت‌گیر را برداشته)."""
    lim = lim or default_limits()
    return lim.caps.get(platform, lim.cap_default)


def warmup_factor(added_ts: int, now: int | None = None, lim: Limits | None = None) -> float:
    """ضریبِ ظرفیت بر اساسِ سنِ اکانت (کف → ۱٫۰ طیِ `warmup_days` روز).

    اکانتِ نویی که ناگهان پرمصرف شود، خودش الگویی است که تشخیص داده می‌شود.
    """
    lim = lim or default_limits()
    if not added_ts or lim.warmup_days <= 0:
        return 1.0
    age_days = max(0.0, ((now or int(time.time())) - int(added_ts)) / 86400.0)
    if age_days >= lim.warmup_days:
        return 1.0
    return lim.warmup_floor + (1.0 - lim.warmup_floor) * (age_days / lim.warmup_days)


def budget_of(meta: dict, now: int | None = None, lim: Limits | None = None) -> int:
    """سقفِ مجازِ این ساعت برای این اکانت (ظرفیتِ پلتفرم × ضریبِ گرم‌شدن).

    ۰ یعنی «بی‌نهایت» — سرعت‌گیر از پنل خاموش شده.
    """
    lim = lim or default_limits()
    cap = hourly_cap(str(meta.get("platform") or ""), lim)
    if cap <= 0:
        return 0
    return max(1, int(cap * warmup_factor(int(meta.get("added") or 0), now, lim)))


def _hour_key(name: str, now: int | None = None) -> str:
    return _CK_USE + name + ":" + time.strftime("%Y%m%d%H", time.gmtime(now or time.time()))


async def usage(redis, name: str, now: int | None = None) -> int:
    """مصرفِ این ساعتِ اکانت."""
    if redis is None:
        return 0
    try:
        return int(await redis.get(_hour_key(name, now)) or 0)
    except Exception:  # noqa: BLE001
        return 0


async def note_use(redis, name: str | None) -> None:
    """اکانت تحویل داده شد → فقط مهرِ زمان (برای فاصلهٔ حداقلی).

    سطلِ ساعتی این‌جا زیاد **نمی‌شود**: سرِ تحویل هنوز نمی‌دانیم این تلاش واقعاً
    مصرف شد یا خروجی جلوی راه را گرفت. با `note_spend` بعد از معلوم‌شدنِ نتیجه
    شمرده می‌شود — وگرنه یک خروجیِ مسدود در دو درخواست سهمیهٔ کلِ استخر را می‌خورد.
    """
    if not name or redis is None:
        return
    try:
        await redis.set(_CK_LAST + name, str(int(time.time())), ex=3600)
    except Exception:  # noqa: BLE001
        pass


async def note_spend(redis, name: str | None) -> None:
    """تلاش واقعاً به‌حسابِ اکانت خورد (موفق، یا شکستی که تقصیرِ خودش بود)."""
    if not name or redis is None:
        return
    try:
        k = _hour_key(name)
        if await redis.incr(k) == 1:
            await redis.expire(k, 7200)
    except Exception:  # noqa: BLE001
        pass


def over_budget(meta: dict, used: int, last: int, now: int,
                lim: Limits | None = None) -> bool:
    """نسخهٔ **همگام**: سهمیهٔ ساعتی تمام شده یا خیلی زود دوباره صدا زده می‌شود؟

    مثلِ `hourly_cap`/`budget_of`، ریاضی عمداً sync است و ورودی‌هایش یک‌بار
    دسته‌ای خوانده می‌شوند — همان الگویی که `Limits` برایش ساخته شد: تنها بخشِ
    ناهمگام یک‌بار در هر عملیات اجرا می‌شود، نه یک‌بار به‌ازای هر اکانت.
    """
    lim = lim or default_limits()
    cap = budget_of(meta, now, lim)
    if cap and used >= cap:
        return True
    if lim.min_gap <= 0:
        return False
    return bool(last and now - last < lim.min_gap)


async def _over_budget(redis, name: str, meta: dict, now: int,
                       lim: Limits | None = None) -> bool:
    """پوششِ تکیِ `over_budget` — برای فراخوان‌هایی که دسته‌ای نمی‌خوانند."""
    lim = lim or default_limits()
    try:
        last = int(await redis.get(_CK_LAST + name) or 0)
    except Exception:  # noqa: BLE001
        last = 0
    return over_budget(meta, await usage(redis, name, now), last, now, lim)

# ── دسته‌بندیِ خطا ───────────────────────────────────────────────
# شمارندهٔ «۳ خطای پشتِ‌هم = باطل» خام بود: یک محدودیتِ نرخ (که یعنی *ما* تند رفتیم)
# با یک لاگین‌نداشتنِ واقعی یکی حساب می‌شد. حالا هر خطا دسته می‌گیرد و واکنش فرق می‌کند.
RATE_LIMIT, CHECKPOINT, LOGIN_REQUIRED, BOT_CHECK, TRANSIENT, UNRELATED = (
    "rate_limit", "checkpoint", "login_required", "bot_check", "transient", "unrelated")

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
    # «redirect to home page»/«redirect to login page» = پاسخِ gallery-dl وقتی سشنِ
    # اینستاگرام دیگر معتبر نیست؛ کلمهٔ login در اولی نیست ولی دقیقاً همان معنا را دارد.
    (LOGIN_REQUIRED, ("login required", "login_required", "not logged", "sign in",
                      "requires authentication", "unauthorized", "401", "403",
                      "login page", "redirect to home page", "session expired", "csrf")),
    # پاسخِ بی‌معنا از سرور: بدنهٔ خالی یا HTML به‌جای JSON. اینستاگرام وقتی سشن/IP
    # را قبول ندارد اغلب همین را می‌دهد (نه پیامِ لاگین)، **ولی** همین خطا وقتی
    # هم می‌آید که خودِ extractor با تغییرِ سایت عقب افتاده باشد. پس مبهم است:
    # اکانتِ بعدی را امتحان کن، اما هیچ اکانتی را مقصر ندان.
    (TRANSIENT, ("jsondecodeerror", "failed to parse json", "unable to parse json",
                 "expecting value: line 1 column 1", "empty response",
                 "unexpected error occurred", "connection reset", "read timed out",
                 "remote end closed connection")),
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
    """آیا این خطا واقعاً به اعتبارِ اکانت می‌خورد؟

    محدودیتِ نرخ **نمی‌خورد** (ما تند رفته‌ایم، نه اکانت خراب است) و خطای
    `transient` هم نه (پاسخِ بی‌معنای سرور می‌تواند اصلاً ربطی به اکانت نداشته باشد).
    """
    return cls in (CHECKPOINT, LOGIN_REQUIRED, BOT_CHECK)


# ── متادیتا ─────────────────────────────────────────────────────
def _blank_meta(name: str) -> dict:
    return {"label": os.path.splitext(name)[0], "platform": guess_platform(name),
            "added": int(time.time()), "last_ok": 0, "fail_streak": 0, "disabled": False,
            "frozen": False, "last_error": "", "last_error_at": 0,
            # هویتِ سشن: کوکی همیشه با همین خروجی و همین UA استفاده می‌شود
            "node_id": "", "proxy": "", "user_agent": ""}


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
        # ردِ ماندگارِ «این سطل زمانی اکانت داشت». این‌جا نوشته می‌شود و نه در
        # مسیرِ افزودنِ پنل، چون `set_meta` تنها نقطه‌ای است که پلتفرمِ **صریح**
        # را می‌بیند: نامِ فایل قابلِ‌اتکا نیست (اکانتِ «other» با برچسبِ
        # «youtube-backup» فایلش `cookies_youtube-backup.txt` می‌شود و
        # `guess_platform` سطلِ اشتباه را علامت می‌زند)، و `admin_web` هم در
        # محیطِ تست قابلِ import نیست.
        if meta.get("platform"):
            await redis.set(_CK_SEEN + str(meta["platform"]), "1")
    except Exception as exc:  # noqa: BLE001
        log.debug("cookie meta write failed: %s", exc)


async def del_meta(redis, name: str) -> None:
    if redis is None:
        return
    try:
        await redis.delete(_CK_META + name)
        await redis.delete(_CK_CD + name)
        # `_CK_SEEN` عمداً **پاک نمی‌شود** — تمامِ ارزشش همین است. بدونش
        # «هرگز پر نشده» و «پر بوده و خالی شده» هر دو `total == 0` می‌خوانند، و
        # آن‌وقت حذفِ اکانت‌های مردهٔ اینستاگرام هشدارِ واقعی را خاموش می‌کند.
    except Exception:  # noqa: BLE001
        pass


async def mark_seen(redis, platform: str) -> None:
    """«این سطل زمانی اکانت داشت» — ماندگار، بی‌TTL، هرگز پاک‌نشدنی."""
    if redis is None or not platform:
        return
    try:
        await redis.set(_CK_SEEN + platform, "1")
    except Exception:  # noqa: BLE001
        pass


async def was_stocked(redis, platform: str) -> bool:
    """آیا این سطل **زمانی** اکانت داشته؟

    تنها ردِ ماندگارِ آن، چون حذفِ اکانت هم فایل را می‌برد هم متا را. سه حالتی که
    مصرف‌کننده‌ها (`_alert_if_low`, `_warn_cookieless`) از هم جدا می‌کنند:
    «۰ از ۰ و هرگز پر نشده» = عادی و ساکت · «۰ از ۰ ولی زمانی پر بوده» = یک
    قابلیت از کار افتاده · «۰ از N» = استخرِ سوخته.

    محدودیتِ شناخته‌شده: اگر Redis از صفر ساخته شود این رد می‌رود. آن حالت روی
    مستر بی‌اثر است تا وقتی فایلی روی دیسک مانده باشد (`list_names` دیسک را
    مقدم می‌داند، پس `total > 0`)؛ فقط «حذف شد **و بعد** Redis پاک شد» دوباره
    ساکت می‌شود — یک شکستِ دوگانه، نه مسیرِ عادی.
    """
    if redis is None or not platform:
        return False
    try:
        return bool(await redis.exists(_CK_SEEN + platform))
    except Exception:  # noqa: BLE001
        return False


# ── فهرستِ نام‌ها (مستر: دیسک · نود: آینهٔ Redis) ────────────────
async def list_names(redis) -> tuple[list[str], bool]:
    """(نام‌ها, محلی‌بودن). محلی=True یعنی مستر (فایل روی دیسک).

    نکتهٔ ظریف: شاخهٔ دیسک فقط وقتی برنده است که **واقعاً فایلی پیدا کند**. اگر
    `COOKIES_DIR` روی نود ست شده باشد ولی خالی/اشتباه باشد، صرفِ «وجود داشتنِ
    پوشه» باعث می‌شد فهرست خالی برگردد و آینهٔ Redis اصلاً خوانده نشود — یعنی نود
    هیچ اکانتی نمی‌دید و دانلود بی‌کوکی می‌رفت، بی‌آنکه جایی ثبت شود.
    """
    d = settings.cookies_dir
    if d and os.path.isdir(d):
        local = sorted(os.path.basename(f) for f in glob.glob(os.path.join(d, "*.txt")))
        if local:
            return local, True
    names: list[str] = []
    if redis is not None:
        try:
            raw = await redis.smembers(_CK_SET)
            names = sorted((n if isinstance(n, str) else n.decode()) for n in raw)
        except Exception:  # noqa: BLE001
            names = []
    return names, False


async def status_of(redis, name: str, meta: dict | None = None,
                    lim: Limits | None = None, cooldown: int | None = None) -> str:
    """وضعیتِ اکانت. `cooldown` = ثانیهٔ باقی‌مانده اگر از قبل خوانده شده باشد
    (مسیرِ دسته‌ای)؛ `None` یعنی خودت از Redis بپرس (مسیرِ تکیِ قدیمی)."""
    meta = meta if meta is not None else await get_meta(redis, name)
    if meta.get("disabled"):
        return DISABLED
    if meta.get("frozen"):     # چک‌پوینت خورده — تا دخالتِ انسان استفاده نمی‌شود
        return FROZEN
    if cooldown is not None:
        if cooldown > 0:
            return COOLDOWN
    elif redis is not None:
        try:
            if await redis.exists(_CK_CD + name):
                return COOLDOWN
        except Exception:  # noqa: BLE001
            pass
    fs = int(meta.get("fail_streak") or 0)
    if fs >= (lim or default_limits()).invalid_at:
        return INVALID
    if fs > 0:
        return SUSPECT
    # شمارنده صفر است — ولی اگر آخرین اتفاق یک خطا بوده (نه موفقیت)، «سالم» گفتن
    # گمراه‌کننده است. این‌طور خطاها (transient/بی‌ربط) عمداً شمارنده بالا نمی‌برند،
    # پس بدونِ این بررسی برای همیشه سبز می‌مانند حتی وقتی هیچ دانلودی موفق نیست.
    if int(meta.get("last_error_at") or 0) > int(meta.get("last_ok") or 0):
        return UNPROVEN
    return HEALTHY


async def _mget(redis, keys: list[str]) -> list:
    """یک رفت‌وبرگشت به‌جای N تا. روی خطا فهرستِ None برمی‌گرداند (رفتارِ قبلی)."""
    if redis is None or not keys:
        return [None] * len(keys)
    try:
        return list(await redis.mget(keys))
    except Exception:  # noqa: BLE001
        return [None] * len(keys)


def _int(v) -> int:
    """مقدارِ Redis → عدد، با ۰ روی هر چیزِ نامعتبر.

    نسخهٔ تکی (`usage`) کلِ خواندن را در try داشت، پس یک مقدارِ خرابِ کلید فقط
    ۰ می‌داد؛ در مسیرِ دسته‌ای همان `int()` بیرونِ try می‌افتاد و `pick()` را
    می‌ترکاند. تفاوتِ ریزی که با جابه‌جاییِ خواندن‌ها به‌راحتی جا می‌ماند.
    """
    try:
        return int(v or 0)
    except (ValueError, TypeError):
        return 0


async def get_metas(redis, names: list[str]) -> dict[str, dict]:
    """متای همهٔ اکانت‌ها با **یک** `MGET` (به‌جای یک `GET` برای هرکدام)."""
    out = {n: _blank_meta(n) for n in names}
    for n, raw in zip(names, await _mget(redis, [_CK_META + n for n in names])):
        if raw:
            try:
                out[n].update(json.loads(raw))
            except (ValueError, TypeError):
                pass
    return out


async def cooldowns(redis, names: list[str]) -> dict[str, int]:
    """نامِ اکانت → ثانیهٔ باقی‌ماندهٔ کول‌داون (۰ = نیست)، با **یک** pipeline.

    `TTL` روی کلیدِ نبوده `-2` می‌دهد، پس همین یک فرمان جای **هر دو**ی
    `EXISTS` (برای وضعیت) و `TTL` (برای نمایشِ پنل) را می‌گیرد.
    """
    if redis is None or not names:
        return {n: 0 for n in names}
    try:
        pipe = redis.pipeline()
        for n in names:
            pipe.ttl(_CK_CD + n)
        res = await pipe.execute()
    except Exception:  # noqa: BLE001
        return {n: 0 for n in names}
    return {n: (t if isinstance(t, int) and t > 0 else 0) for n, t in zip(names, res)}


async def accounts(redis, platform: str | None = None,
                   lim: Limits | None = None) -> list[dict]:
    """همهٔ اکانت‌ها با وضعیت (برای پنل). اگر platform داده شود، فیلتر می‌شود.

    خواندن‌ها **دسته‌ای‌اند**: قبلاً به‌ازای هر اکانت یک `GET` متا + یک `EXISTS`
    کول‌داون (+ یک `TTL` اگر در کول‌داون بود) می‌رفت. روی مستر بی‌اهمیت بود، ولی
    روی نودِ دانلود هرکدام یک رفت‌وبرگشتِ WireGuard است و `pick()` داخلِ حلقهٔ
    چرخشِ کوکی صدا زده می‌شود، پس ضرب می‌شد.
    """
    lim = lim or await load_limits()
    names, _local = await list_names(redis)
    metas = await get_metas(redis, names)
    if platform:
        names = [n for n in names if metas[n].get("platform") == platform]
    cds = await cooldowns(redis, names)
    out: list[dict] = []
    for n in names:
        meta = metas[n]
        st = await status_of(redis, n, meta, lim, cooldown=cds.get(n, 0))
        out.append({**meta, "name": n, "status": st,
                    "cooldown": cds.get(n, 0) if st == COOLDOWN else 0})
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


#: وضعیت‌هایی که یعنی «هنوز قابلِ استفاده». `UNPROVEN` این‌جاست چون آخرین خطایش
#: ضربه‌ای به اکانت نزده — اگر بیرونش بگذاریم، یک شکستِ بی‌تقصیر هشدارِ الکیِ
#: «کوکیِ سالم کم است» می‌فرستد و شمارشِ پنل هم بی‌جهت می‌افتد.
USABLE = (HEALTHY, UNPROVEN, SUSPECT)


async def pool_counts(redis, platform: str) -> tuple[int, int]:
    """(کلِ اکانت‌های این پلتفرم, قابلِ‌استفاده‌ها) — با **یک** پیمایش.

    تفکیکِ این دو عدد باربر است و `healthy_count` به‌تنهایی گمش می‌کند:
    «۰ از ۳» یعنی استخر سوخته و باید داد زد؛ «۰ از ۰» یعنی کسی این سطل را پر
    نکرده، که برای بیشترِ سطل‌ها **حالتِ عادی** است — از ۱۴ سطلی که یک دانلود
    می‌تواند بخواهد، پنل فقط ۶ تا را پیشنهاد می‌دهد. هرکس فقط عددِ دوم را ببیند
    این دو را یکی می‌کند، و هشدارِ «کوکیِ سالم نمانده» را برای سطلی می‌فرستد که
    هیچ‌وقت کوکی نداشته.

    یک `accounts()` می‌خواند نه دو تا: روی نودِ دانلود هر پیمایش یک دسته
    رفت‌وبرگشتِ WireGuard است.
    """
    accts = await accounts(redis, platform)
    return len(accts), sum(1 for a in accts if a["status"] in USABLE)


async def healthy_count(redis, platform: str) -> int:
    return (await pool_counts(redis, platform))[1]


# ── انتخابِ کوکی برای یک تلاش ───────────────────────────────────
# «خطای اخیر» بعد از سالم می‌آید ولی قبل از مشکوک: هنوز هیچ ضربه‌ای نخورده.
_USE_ORDER = (HEALTHY, UNPROVEN, SUSPECT, INVALID)  # کول‌داون/غیرفعال هرگز


async def pick(redis, platform: str, exclude: set[str] | None = None,
               node_id: str | None = None, ignore_budget: bool = False,
               lim: Limits | None = None) -> str | None:
    """نامِ کوکیِ بعدیِ قابلِ‌استفاده برای این پلتفرم (یا None اگر چیزی نماند).

    اولویت: سالم → مشکوک → باطل (آخرین چاره؛ بهتر از هیچ). غیرفعال/کول‌داون/فریز رد
    می‌شوند، و اکانتی که سهمیهٔ ساعتی‌اش تمام شده یا تازه استفاده شده هم رد می‌شود
    (سرعت‌گیر — فشارِ ۲× یعنی سوختنِ ۴×).

    `node_id`: خروجیِ فعلی. اکانتی که به **همین** خروجی پین شده مقدم است؛ اکانتِ
    پین‌شده به خروجیِ دیگر اصلاً برداشته نمی‌شود، چون اینستاگرام IP را هویت می‌داند و
    جابه‌جاییِ IPِ یک سشن سریع‌ترین راهِ چک‌پوینت است.
    اگر همه سهمیه‌شان تمام باشد، `ignore_budget=True` آخرین تلاش را ممکن می‌کند.
    """
    exclude = exclude or set()
    lim = lim or await load_limits()   # یک‌بار برای کلِ انتخاب (نه per-account)
    now = int(time.time())
    pool = await accounts(redis, platform, lim)

    # نامزدها را **قبل** از خواندنِ سهمیه فیلتر کن، بعد مصرف/آخرین‌استفادهٔ همان‌ها
    # را با دو `MGET` بگیر. قبلاً به‌ازای هر اکانت دو `GET` جدا می‌رفت.
    cands = [a for a in pool
             if a["name"] not in exclude
             and a["status"] not in (COOLDOWN, DISABLED, FROZEN)
             and a["status"] in _USE_ORDER
             and not (str(a.get("node_id") or "") and node_id
                      and str(a.get("node_id")) != node_id)]
    used: dict[str, int] = {}
    lasts: dict[str, int] = {}
    if cands and not ignore_budget:
        cnames = [a["name"] for a in cands]
        for n, v in zip(cnames, await _mget(redis, [_hour_key(n, now) for n in cnames])):
            used[n] = _int(v)
        for n, v in zip(cnames, await _mget(redis, [_CK_LAST + n for n in cnames])):
            lasts[n] = _int(v)

    ranked: list[tuple[int, int, int, str]] = []
    for a in cands:
        pinned = str(a.get("node_id") or "")
        rank = _USE_ORDER.index(a["status"])
        if not ignore_budget and over_budget(a, used.get(a["name"], 0),
                                             lasts.get(a["name"], 0), now, lim):
            continue
        # اکانتِ پین‌شده به همین خروجی مقدم است (هویتِ پایدار = عمرِ بیشتر)
        affinity = 0 if (pinned and pinned == node_id) else 1
        ranked.append((affinity, rank, int(a.get("last_ok") or 0), a["name"]))
    if not ranked:
        # همه سهمیه‌شان پر است؟ یک‌بار بدونِ سرعت‌گیر تلاش کن تا کاربر بی‌جواب نماند
        if not ignore_budget:
            return await pick(redis, platform, exclude, node_id, True, lim)
        return None
    ranked.sort()
    # هم‌رتبه‌ها را چرخشی انتخاب کن. بدونِ این، وقتی همهٔ اکانت‌ها تازه‌اند
    # (`last_ok=0`) مرتب‌سازی به **نام** می‌افتد و همیشه یک اکانتِ ثابت قربانیِ
    # اولین تلاش می‌شود — `_CK_ROT` برای همین ساخته شده بود ولی استفاده نمی‌شد.
    top = [r for r in ranked if r[:3] == ranked[0][:3]]
    if len(top) > 1:
        try:
            rot = int(await redis.incr(_CK_ROT + platform))
        except Exception:  # noqa: BLE001
            rot = 0
        return top[rot % len(top)][3]
    return ranked[0][3]


async def materialize(redis, name: str, workdir: str | None) -> str | None:
    """نامِ کوکی → مسیرِ فایلِ قابلِ‌استفاده. مستر: مسیرِ دیسک. نود: از آینهٔ Redis در
    workdir می‌نویسد (با workdir پاک می‌شود)."""
    d = settings.cookies_dir
    if d and os.path.isdir(d):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
        # روی دیسک نبود → به‌جای تسلیم، آینهٔ Redis را امتحان کن. وگرنه یک
        # COOKIES_DIRِ اشتباه/خالی روی نود همهٔ اکانت‌ها را نامرئی می‌کند.
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
                    error_class: str = "", message: str = "",
                    lim: Limits | None = None) -> dict:
    """خطا → واکنشِ **متناسب با دستهٔ آن**، نه یک شمارندهٔ واحد.

    - `rate_limit`: فقط استراحتِ بلند. ضربه‌ای به اکانت نمی‌خورد — اکانت سالم است،
      ما تند رفته‌ایم؛ اگر ضربه بزنیم اکانتِ سالم را دور می‌ریزیم.
    - `checkpoint`: **فریز** + علامتِ نیازمندِ انسان. تلاشِ خودکارِ بیشتر فقط وضع را بدتر می‌کند.
    - `transient`/`unrelated`: فقط **ثبت** می‌شود (`last_error`). نه شمارنده، نه کول‌داون.
    - لاگین/بات‌چک: شمارنده + کول‌داونِ پلکانی (۳۰د → ۱س → ۲س …).

    چون دسته‌های بی‌ضربه هم این‌جا ثبت می‌شوند، این تابع را می‌شود برای **هر**
    شکستی صدا زد؛ همین است که پنل را از «همیشه سالم» بیرون می‌آورد.
    """
    if not name or redis is None:
        return {}
    lim = lim or await load_limits()
    meta = await get_meta(redis, name)
    meta["last_error"] = (error_class or "") + ((" · " + " ".join(message.split())[:120])
                                                if message else "")
    meta["last_error_at"] = int(time.time())

    if error_class == RATE_LIMIT:
        await set_meta(redis, name, meta)
        try:
            await redis.set(_CK_CD + name, "1", ex=lim.rate_cooldown)
        except Exception:  # noqa: BLE001
            pass
        return meta

    if error_class and not burns_account(error_class):
        # transient/unrelated: فقط ثبت می‌شود تا در پنل دیده شود. نه شمارنده، نه
        # کول‌داون — اگر علت سمتِ سایت یا خودِ لینک باشد، کول‌داون‌دادن یعنی کلِ
        # استخر را برای مشکلی که ربطی به اکانت‌ها ندارد از دور خارج کرده‌ایم.
        # وضعیت با همین ثبت به «خطای اخیر» می‌رود (status_of)، پس نامرئی نمی‌ماند.
        await set_meta(redis, name, meta)
        return meta

    if error_class == CHECKPOINT:
        meta["frozen"] = True
        await set_meta(redis, name, meta)
        return meta

    meta["fail_streak"] = int(meta.get("fail_streak") or 0) + 1
    await set_meta(redis, name, meta)
    if cooldown:
        sec = min(lim.cooldown * (2 ** (meta["fail_streak"] - 1)), 6 * 3600)
        try:
            await redis.set(_CK_CD + name, "1", ex=sec)
        except Exception:  # noqa: BLE001
            pass
    return meta


async def unfreeze(redis, name: str) -> None:
    """ادمین رسیدگی کرد → از صفِ «نیازمندِ انسان» خارج شود.

    خطای قبلی هم پاک می‌شود: وقتی ادمین صریحاً می‌گوید «درستش کردم»، نگه‌داشتنِ
    «آخرین تلاش ناموفق» فقط گمراه‌کننده است — از این‌جا به بعد باید با نتیجهٔ
    تلاشِ **بعدی** قضاوت شود، نه با خطای منقضی‌شده.
    """
    meta = await get_meta(redis, name)
    meta["frozen"] = False
    meta["fail_streak"] = 0
    meta["last_error"] = ""
    meta["last_error_at"] = 0
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

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str | None:
    """نامِ فایل را به یک basenameِ امنِ `.txt` تبدیل می‌کند (بدونِ traversal)."""
    base = os.path.basename((name or "").strip())
    base = _SAFE_NAME.sub("_", base).strip("._")
    if not base:
        return None
    if not base.lower().endswith(".txt"):
        base += ".txt"
    return base


def cookie_path(name: str) -> str | None:
    """مسیرِ فایلِ کوکی داخلِ `cookies_dir` — یا `None` اگر از پوشه بیرون بزند.

    این‌جا (نه در پنل) زندگی می‌کند چون **هر دو** مسیرِ حذف به آن نیاز دارند: پنل
    و هندلرِ تلگرامیِ ادمین. پنل هر دو گارد را داشت و دوقلوی رباتی‌اش هیچ‌کدام را،
    و چون دو نسخهٔ دست‌نویس بودند خیلی راحت از هم واگرا شدند. `routers/admin.py`
    هم نمی‌تواند از `admin_web` import کند — ایمیجِ ربات jinja2/cryptography ندارد.

    دو لایه عمدی است: `safe_name()` نام را بی‌ضرر می‌کند، و مقایسهٔ مسیرِ مطلق
    تضمین می‌کند نتیجه واقعاً داخلِ همان پوشه است حتی اگر روزی نام‌سازی عوض شود.
    """
    if not settings.cookies_dir:
        return None
    base = safe_name(name)
    if not base:
        return None
    root = os.path.abspath(settings.cookies_dir)
    path = os.path.abspath(os.path.join(root, base))
    return path if os.path.dirname(path) == root else None


def remove_cookie_file(name: str) -> None:
    """فایلِ کوکی را امن حذف کن (بی‌صدا اگر نبود یا نام نامعتبر بود)."""
    path = cookie_path(name)
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


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

