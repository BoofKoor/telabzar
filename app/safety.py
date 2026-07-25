"""فیلترِ محتوای بزرگسال — سه لایه، از ارزان به گران.

چرا سه لایه و نه یک مدل: هر لایه چیزی را می‌گیرد که لایهٔ بعد نمی‌تواند، و
ترتیبشان تعیین می‌کند چقدر منابع خرج شود.

۱) **دامنه** (`check_url`) — قبل از هر بایت دانلود. مهم‌ترین لایه است: مسیرِ
   واقعیِ بن‌شدنِ ربات این است که خودش پورن را دانلود و **آپلود** کند.
۲) **متادیتا** (`check_meta`) — `age_limit`ی که خودِ yt-dlp می‌دهد، به‌علاوهٔ
   کلیدواژه در عنوان/توضیحات/تگ. رایگان است و قبل از دانلود جواب می‌دهد.
۳) **پیکسل** (`scan_file`) — NudeNet روی onnxruntime. تنها لایه‌ای که فایلِ
   آپلودیِ کاربر را می‌بیند، ولی گران‌ترین است، پس آخر می‌آید.

قاعدهٔ مثبتِ کاذب: NudeNet برچسبِ ریزدانه می‌دهد، پس **فقط کلاس‌های صریح** را
مسدود می‌کنیم (اندام جنسی/سینهٔ برهنه/باسنِ برهنه). شکم، پا، زیربغل و صورت
هرگز مسدودکننده نیستند — وگرنه عکسِ ساحل و ورزش هم رد می‌شد.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from urllib.parse import unquote, urlparse

log = logging.getLogger("telabzar.safety")

# ── لایهٔ ۱: دامنه ───────────────────────────────────────────────
# فهرستِ پایه، عمداً کوتاه و فقط سایت‌های بزرگ و بی‌ابهام. ادمین از پنل
# (`safety_block_domains`) هرچه لازم بود اضافه می‌کند.
BASE_DOMAINS: frozenset[str] = frozenset({
    "pornhub.com", "xvideos.com", "xnxx.com", "xhamster.com", "redtube.com",
    "youporn.com", "tube8.com", "spankbang.com", "eporner.com", "txxx.com",
    "beeg.com", "hqporner.com", "porntrex.com", "hclips.com", "upornia.com",
    "onlyfans.com", "fansly.com", "manyvids.com", "chaturbate.com",
    "stripchat.com", "bongacams.com", "cam4.com", "myfreecams.com",
    "livejasmin.com", "brazzers.com", "bangbros.com", "naughtyamerica.com",
    "realitykings.com", "adulttime.com", "nutaku.net", "rule34.xxx",
    "e-hentai.org", "nhentai.net", "hanime.tv", "hentaihaven.xxx",
    "motherless.com", "fapello.com", "erome.com", "sxyprn.com", "javhd.com",
})
# TLDهایی که خودشان اعلامِ بزرگسال‌بودن‌اند
ADULT_TLDS: tuple[str, ...] = (".xxx", ".porn", ".sex", ".adult", ".sexy", ".cam")
# دو ردهٔ کلیدواژه، چون یک قاعده هر دو طرف را خراب می‌کند:
#
# STRONG = هرجای رشته پیدا شود کافی است. دامنه‌های بزرگسال کلمه‌ها را می‌چسبانند
#   (`freeporn-tube`, `xxxtube1`, `myhentai`)، پس تطبیقِ «توکنِ کامل» ردشان می‌کند.
#   این‌ها آن‌قدر بی‌ابهام‌اند که زیررشته‌بودنشان خطر ندارد.
# WORD = فقط به‌صورتِ توکنِ کامل. این‌ها داخلِ کلمه‌های کاملاً سالم ظاهر می‌شوند و
#   زیررشته‌گرفتنشان فاجعهٔ مثبتِ کاذب است: sex→esse‌x/sussex/middlesex/unisex،
#   anal→analysis/analytics/canal، cum→cumbria/document، cock→cocktail/peacock،
#   dick→dickens، hardcore→hardcoregaming101.
STRONG_TOKENS: tuple[str, ...] = (
    "porn", "xxx", "xnxx", "xvideos", "xhamster", "hentai", "nsfw", "onlyfans",
    "brazzers", "javhd", "rule34", "camgirl", "sexcam", "sexchat", "sexvideo",
    "milf", "blowjob", "creampie", "cumshot", "handjob", "gangbang",
    "bukkake", "deepthroat", "bdsm", "nudes", "nudity", "boobs",
    "fuck", "erotic", "striptease", "stripcam", "18plus",
    "پورن", "شهوانی",
)
WORD_TOKENS: frozenset[str] = frozenset({
    "sex", "anal", "cum", "cock", "dick", "tits", "titty", "nude",
    "hardcore", "fetish", "incest", "orgy", "playboy", "stripper",
    "porno", "pornos", "camgirls", "nsfw18",
    # این‌ها هم زیررشتهٔ کلمه‌های سالم‌اند: pussy⊂pussycat (گروهِ موسیقی)،
    # sexo⊂sexology، و در فارسی سکس⊂سوسکس/اسکس.
    "pussy", "sexo",
    "سکس", "سکسی", "برهنه", "شهوت", "لخت",
})
# فقط روی **نامِ دامنه**. این کلمه‌ها در متنِ آزاد مبهم‌اند («Ford Escorts»،
# «adult education»، «escort vehicle») ولی داخلِ یک هاست عملاً بی‌ابهام‌اند.
HOST_TOKENS: frozenset[str] = frozenset({
    "escort", "escorts", "hookup", "hookups", "adultvideo", "adulttime",
    "adultfilm", "camsex", "livesex",
})
_TOKEN_SPLIT = re.compile(r"[^0-9a-z؀-ۿ]+")


def _tokens(text: str) -> set[str]:
    return {p for p in _TOKEN_SPLIT.split((text or "").lower()) if p}


def _match(text: str, host: bool = False) -> str | None:
    """اولین نشانهٔ پیداشده، یا None. STRONG زیررشته‌ای، WORD توکنِ کامل.

    `host=True` ردهٔ سومِ مخصوصِ دامنه را هم اضافه می‌کند (کلمه‌هایی که در متنِ
    آزاد مبهم‌اند ولی در نامِ دامنه نه).
    """
    low = (text or "").lower()
    if not low:
        return None
    for s in STRONG_TOKENS:
        if s in low:
            return s
    words = WORD_TOKENS | HOST_TOKENS if host else WORD_TOKENS
    hit = _tokens(low) & words
    return sorted(hit)[0] if hit else None


def parse_domains(raw: str) -> frozenset[str]:
    """متنِ پنل (خط/کاما/فاصله) → مجموعهٔ دامنه‌های نرمال‌شده."""
    out = set()
    for part in re.split(r"[\s,;]+", (raw or "").strip().lower()):
        part = part.strip().strip(".")
        if not part:
            continue
        if "//" in part:                       # کاربر URL کامل چسبانده
            part = (urlparse(part).hostname or "").lower()
        if part.startswith("www."):
            part = part[4:]
        if part:
            out.add(part)
    return frozenset(out)


def _host_matches(host: str, domains: frozenset[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def check_url(url: str, block: frozenset[str] = frozenset(),
              allow: frozenset[str] = frozenset()) -> str | None:
    """دلیلِ مسدودی یا None. `allow` بر همه‌چیز مقدم است (رفعِ مثبتِ کاذب)."""
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    if not host:
        return None
    if allow and _host_matches(host, allow):
        return None
    if _host_matches(host, BASE_DOMAINS) or (block and _host_matches(host, block)):
        return f"domain:{host}"
    if host.endswith(ADULT_TLDS):
        return f"tld:{host}"
    hit = _match(host, host=True)
    if hit:
        return f"host-word:{hit}"
    hit = _match(unquote(urlparse(url).path or ""))
    if hit:
        return f"path-word:{hit}"
    return None


# ── لایهٔ ۲: متادیتا ─────────────────────────────────────────────
def check_text(text: str | None) -> str | None:
    """عنوان/توضیحات/کپشن/نامِ فایل — همان دو ردهٔ کلیدواژه."""
    hit = _match(text or "")
    return f"text-word:{hit}" if hit else None


def check_meta(info: dict | None) -> str | None:
    """`age_limit`ِ خودِ yt-dlp + کلیدواژه در عنوان/توضیحات/تگ/دسته."""
    info = info or {}
    try:
        if int(info.get("age_limit") or 0) >= 18:
            return "age_limit:18"
    except (TypeError, ValueError):
        pass
    parts = [str(info.get("title") or ""), str(info.get("description") or "")[:2000],
             str(info.get("uploader") or ""), str(info.get("channel") or "")]
    for key in ("tags", "categories"):
        val = info.get(key)
        if isinstance(val, (list, tuple)):
            parts += [str(v) for v in val[:40]]
    return check_text(" ".join(parts))


# ── لایهٔ ۳: پیکسل (NudeNet روی onnxruntime) ─────────────────────
# فقط این کلاس‌ها مسدود می‌کنند. صورت/شکم/پا/زیربغل و هر «covered»ی عمداً
# بیرون‌اند — کلیدِ اصلیِ کم‌کردنِ مثبتِ کاذب همین فهرست است.
EXPLICIT_LABELS: frozenset[str] = frozenset({
    "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED", "BUTTOCKS_EXPOSED",
})
SCANNABLE_KINDS = ("image", "video")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic", ".heif")

_detector = None
_detector_failed = False


def _get_detector():
    """مدل یک‌بار برای کلِ پروسه بار می‌شود (بارگذاری گران است، اجرا ارزان)."""
    global _detector, _detector_failed
    if _detector is not None or _detector_failed:
        return _detector
    try:
        from nudenet import NudeDetector
        _detector = NudeDetector()
        log.info("nudenet detector loaded")
    except Exception as exc:  # noqa: BLE001
        _detector_failed = True     # نبودِ مدل نباید هر فایل را کند/خطا کند
        log.warning("nudenet unavailable (%s) — pixel layer disabled", str(exc)[:160])
    return _detector


def available() -> bool:
    return _get_detector() is not None


def _detect_sync(paths: list[str], threshold: float) -> tuple[float, str]:
    """(بیشترین امتیازِ کلاسِ صریح, برچسب) — همگام، برای اجرا در thread."""
    det = _get_detector()
    if det is None:
        return 0.0, ""
    best, label = 0.0, ""
    for p in paths:
        try:
            for d in det.detect(p) or []:
                if d.get("class") in EXPLICIT_LABELS and float(d.get("score") or 0) > best:
                    best, label = float(d["score"]), str(d["class"])
            if best >= threshold:
                break               # یک فریمِ قطعی کافی است، بقیه را نخوان
        except Exception as exc:  # noqa: BLE001
            log.debug("nudenet detect failed on %s: %s", os.path.basename(p), exc)
    return best, label


async def _video_frames(path: str, workdir: str, count: int) -> list[str]:
    """چند فریمِ پخش‌شده در طولِ ویدیو (نه فقط ابتدا — تیزرِ سالم رایج است)."""
    from . import processing as P
    dur = 0.0
    try:
        dur = float((await P.probe_media(path) or {}).get("duration") or 0)
    except Exception:  # noqa: BLE001
        dur = 0.0
    count = max(1, count)
    if dur <= 1:
        stamps = [0.0]
    else:                            # از ۵٪ تا ۹۵٪، تا ابتدا/انتهای سیاه نیفتد
        step = (dur * 0.9) / count
        stamps = [dur * 0.05 + step * (i + 0.5) for i in range(count)]
    out: list[str] = []
    for i, ts in enumerate(stamps):
        dst = os.path.join(workdir, f"nsfw-{secrets.token_hex(3)}-{i}.jpg")
        cmd = ["ffmpeg", "-nostdin", "-y", "-ss", f"{ts:.2f}", "-i", path,
               "-frames:v", "1", "-vf", "scale='min(640,iw)':-2", dst]
        try:
            await P._run(cmd, timeout=60)
        except Exception as exc:  # noqa: BLE001
            log.debug("frame grab failed at %.1fs: %s", ts, exc)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            out.append(dst)
    return out


async def scan_file(path: str, kind: str, threshold: float = 0.55,
                    frames: int = 5, workdir: str | None = None) -> tuple[bool, float, str]:
    """(مسدود؟, امتیاز, برچسب). هر شکستی → «مسدود نیست» (فیلتر نباید سرویس را بخورد)."""
    if kind not in SCANNABLE_KINDS or not os.path.exists(path):
        return False, 0.0, ""
    if not available():
        return False, 0.0, ""
    if kind == "image" or path.lower().endswith(_IMAGE_EXTS):
        targets, tmp = [path], []
    else:
        wd = workdir or os.path.dirname(path) or "."
        tmp = await _video_frames(path, wd, frames)
        targets = tmp
    if not targets:
        return False, 0.0, ""
    try:
        score, label = await asyncio.to_thread(_detect_sync, targets, threshold)
    except Exception as exc:  # noqa: BLE001
        log.warning("nsfw scan failed: %s", str(exc)[:160])
        return False, 0.0, ""
    finally:
        for f in tmp:
            try:
                os.remove(f)
            except OSError:
                pass
    return score >= threshold, score, label


# ── پیکربندیِ زمانِ‌اجرا (یک‌بار خوانده و پایین پاس داده می‌شود) ──
class Policy:
    """عکسِ فوریِ تنظیماتِ پنل — مثلِ `cookies.Limits`، تا خواندنِ تنظیمات
    یک‌بار سرِ هر عملیات باشد نه یک‌بار برای هر فایل."""

    __slots__ = ("enabled", "scan_pixels", "threshold", "frames", "block", "allow",
                 "notify", "strikes")

    def __init__(self, enabled=True, scan_pixels=True, threshold=0.55, frames=5,
                 block=frozenset(), allow=frozenset(), notify=False, strikes=0):
        self.enabled, self.scan_pixels = enabled, scan_pixels
        self.threshold, self.frames = threshold, frames
        self.block, self.allow = block, allow
        self.notify, self.strikes = notify, strikes


async def load_policy() -> Policy:
    from . import settings_store
    from .config import settings
    return Policy(
        enabled=await settings_store.get_bool("safety_enabled", settings.safety_enabled),
        scan_pixels=await settings_store.get_bool("safety_scan_pixels",
                                                  settings.safety_scan_pixels),
        threshold=max(1, await settings_store.get_int(
            "safety_threshold", settings.safety_threshold)) / 100.0,
        frames=await settings_store.get_int("safety_video_frames",
                                            settings.safety_video_frames),
        block=parse_domains(await settings_store.get_str("safety_block_domains", "")),
        allow=parse_domains(await settings_store.get_str("safety_allow_domains", "")),
        notify=await settings_store.get_bool("safety_notify_admin",
                                             settings.safety_notify_admin),
        strikes=await settings_store.get_int("safety_strikes", settings.safety_strikes),
    )


# ── شمارشِ تخلف (و مسدودسازیِ خودکارِ کاربرِ مصر) ────────────────
_HIT = "nsfw:hit:"      # nsfw:hit:<tg_user_id> → شمارندهٔ ۳۰ روزه


async def note_block(redis, tg_user_id: int, policy: Policy) -> int:
    """یک تخلف را بشمار و تعدادِ کلِ اخیر را برگردان (۰ اگر Redis نبود)."""
    if redis is None or not tg_user_id:
        return 0
    try:
        k = _HIT + str(tg_user_id)
        n = await redis.incr(k)
        await redis.expire(k, 30 * 86400)
        return int(n)
    except Exception:  # noqa: BLE001
        return 0


async def report_block(bot, redis, tg_user_id: int, reason: str, policy: Policy,
                       detail: str = "") -> bool:
    """پیامدهای یک مسدودی: شمارش، گزارشِ ادمین، و مسدودیِ خودکارِ کاربرِ مصر.

    خروجی: آیا کاربر همین حالا مسدود شد؟ (تا فراخوان بتواند خبر بدهد)
    همهٔ مسیرها best-effort‌اند — شکستِ گزارش نباید مانعِ مسدودکردنِ خودِ محتوا شود.
    """
    n = await note_block(redis, tg_user_id, policy)
    if policy.notify and bot is not None:
        from .config import settings
        text = (f"🔞 <b>محتوای غیرمجاز مسدود شد</b>\n\n"
                f"کاربر: <code>{tg_user_id}</code>\n"
                f"دلیل: <code>{reason}</code>\n"
                f"{detail}\n"
                f"تخلف‌های ۳۰ روزِ اخیرِ این کاربر: <b>{n or '?'}</b>")
        for aid in settings.admin_id_set:
            try:
                await bot.send_message(aid, text)
            except Exception:  # noqa: BLE001
                pass
    if policy.strikes and n and n >= policy.strikes:
        from sqlalchemy import select
        from .db import Sessionmaker
        from .models import User
        try:
            async with Sessionmaker() as s:
                row = (await s.execute(
                    select(User).where(User.tg_user_id == tg_user_id))).scalar_one_or_none()
                if row is not None and not row.is_blocked:
                    row.is_blocked = True
                    await s.commit()
                    log.warning("user %s auto-blocked after %s nsfw hits", tg_user_id, n)
                    return True
        except Exception:  # noqa: BLE001
            log.warning("auto-block failed for %s", tg_user_id, exc_info=True)
    return False


async def blocked_total(redis) -> int:
    """جمعِ تخلف‌های شمارش‌شده (برای صفحهٔ سلامت)."""
    if redis is None:
        return 0
    try:
        total = 0
        async for k in redis.scan_iter(match=_HIT + "*", count=500):
            total += int(await redis.get(k) or 0)
        return total
    except Exception:  # noqa: BLE001
        return 0
