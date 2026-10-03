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
import threading
import time
import unicodedata
from html import escape as _html_escape
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
    "porn", "xnxx", "xvideos", "xhamster", "hentai", "nsfw", "onlyfans",
    "brazzers", "javhd", "rule34", "camgirl", "sexcam", "sexchat", "sexvideo",
    "blowjob", "creampie", "cumshot", "handjob", "gangbang",
    "bukkake", "deepthroat", "bdsm", "nudes",
    "striptease", "stripcam", "18plus",
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
# زیررشته‌ای، ولی **فقط روی نامِ دامنه** — تا فاز ۴ این‌ها در `STRONG_TOKENS` بودند
# و در متنِ آزاد محتوای کاملاً متعارف را مسدود می‌کردند (همه اجراشده):
# «XXXTENTACION - SAD!» و فیلمِ «xXx: Return of Xander Cage» (xxx)، آلبومِ
# «Erotica»ِ مدونا (erotic)، «FUCK YOU»ِ CeeLo Green و هر ویدیوی رپی که متنِ آهنگ
# را در توضیحات دارد (fuck)، هشدارِ «contains nudity» زیرِ تریلرِ سینمایی
# (nudity)، پادکستِ «Boobs and Bones» (boobs)، و «MILF Money»ِ Rick and Morty
# (milf). **ردهٔ توکنِ کامل جواب نبود**: نیمی از این مثال‌ها خودشان توکنِ کامل‌اند
# («FUCK YOU»، «xXx:»، «contains nudity»). در نامِ دامنه اما بی‌ابهام‌اند و
# به‌هم‌چسبیده می‌آیند (`freexxxtube`, `milfhub`)، پس آن‌جا زیررشته‌ای می‌مانند.
# هزینهٔ آگاهانه: عنوانِ یک پستِ بزرگسال از دامنهٔ ناشناس دیگر با این‌ها گرفته
# نمی‌شود — لایهٔ دامنه، `age_limit`ِ yt-dlp و لایهٔ پیکسل هنوز پشتش هستند، در
# حالی که مثبتِ کاذبِ متن کاربرِ سالم را مسدود می‌کرد (و با `safety_strikes`
# روشن، بعد از چند آهنگ خودِ کاربر را).
HOST_STRONG_TOKENS: tuple[str, ...] = ("xxx", "fuck", "erotic", "nudity", "boobs", "milf")
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
    for s in STRONG_TOKENS + (HOST_STRONG_TOKENS if host else ()):
        if s in low:
            return s
    words = WORD_TOKENS | HOST_TOKENS if host else WORD_TOKENS
    hit = _tokens(low) & words
    return sorted(hit)[0] if hit else None


# جداکننده‌های برچسبِ دامنه که IDNA (و مرورگر/کتابخانهٔ اتصال) نقطه می‌خواند.
# U+3002 را NFKC به نقطه نمی‌برد، پس صریح نگاشت می‌شود.
_DOTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})


def norm_host(host: str | None) -> str:
    """یک شکلِ کانونیک برای هر نامِ دامنه، **پیش از هر مقایسه**.

    همان نامی را برمی‌گرداند که اتصالِ واقعی به آن می‌رسد. سه دورزدن که پیش از
    فاز ۴ از فیلترِ دامنه رد می‌شدند (اجراشده): نقطهٔ پایانی (`beeg.com.` — DNS آن
    را همان دامنه می‌داند ولی `==`/`endswith` نه)، حروفِ fullwidth
    (`ｃｈａｔｕｒｂａｔｅ.com` — کدکِ idna با nameprep به ASCII می‌بردش و اتصال
    همان‌جا می‌رود)، و punycode (`xn--…` — تا کلیدواژهٔ فارسی روی نامِ IDN هم
    کار کند، شکلِ یونیکد مقایسه می‌شود نه ASCII). `www.` هم همین‌جا برداشته
    می‌شود تا فهرستِ پنل و URL یک شکل داشته باشند.
    """
    h = unicodedata.normalize("NFKC", host or "").translate(_DOTS).lower().strip().rstrip(".")
    if "xn--" in h:
        try:
            h = h.encode("ascii").decode("idna").lower()
        except (UnicodeError, ValueError):
            pass                 # punycodeِ خراب: همان شکل بماند (برای مقایسه بی‌خطر)
    return h[4:] if h.startswith("www.") else h


def parse_domains(raw: str) -> frozenset[str]:
    """متنِ پنل (خط/کاما/فاصله) → مجموعهٔ دامنه‌های نرمال‌شده — با همان `norm_host`ِ URL."""
    out = set()
    for part in re.split(r"[\s,;]+", (raw or "").strip()):
        part = part.strip()
        if not part:
            continue
        if "//" in part:                       # کاربر URL کامل چسبانده
            part = urlparse(part).hostname or ""
        part = norm_host(part.strip("."))
        if part:
            out.add(part)
    return frozenset(out)


def _host_matches(host: str, domains: frozenset[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def check_url(url: str, block: frozenset[str] = frozenset(),
              allow: frozenset[str] = frozenset()) -> str | None:
    """دلیلِ مسدودی یا None. `allow` بر همه‌چیز مقدم است (رفعِ مثبتِ کاذب)."""
    host = norm_host(urlparse(url).hostname)
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
_detector_lock = threading.Lock()


def _get_detector():
    """مدل یک‌بار برای کلِ پروسه بار می‌شود (بارگذاری گران است، اجرا ارزان).

    قفل لازم است چون این تابع از **thread** صدا زده می‌شود: `_detect_sync` داخلِ
    `asyncio.to_thread` اجرا می‌شود و ورکر `max_jobs=4` دارد، پس روی ورکرِ
    تازه‌ری‌استارت‌شده چهار جابِ هم‌زمان می‌توانستند هم‌زمان چهار `NudeDetector`
    بسازند — سه‌تایشان بلافاصله زباله می‌شدند، ولی هزینهٔ بارگذاری و جهشِ حافظه
    (هر نمونه ~۸۱ مگابایت، اندازه‌گیریِ ۲۰۲۶-۰۸-۱۰) واقعی بود. دقیقاً همان
    لحظه‌ای رخ می‌دهد که بیشترین احتمال را دارد: بعد از هر `telabzar update`.

    الگوی double-checked: چکِ اولِ بدونِ قفل مسیرِ داغ را ارزان نگه می‌دارد
    (پس از بارگذاری هیچ جابی قفل نمی‌گیرد) و چکِ دومِ داخلِ قفل مسابقه را می‌بندد.
    """
    global _detector, _detector_failed
    if _detector is not None or _detector_failed:
        return _detector
    with _detector_lock:
        if _detector is not None or _detector_failed:   # کسی جلوتر بارش کرد
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


# بالاتر از این تعدادِ پیکسل، تصویر مستقیم به NudeNet/OpenCV داده نمی‌شود، چون
# `cv2.imread` کلِ تصویر را decode می‌کند و بعد NudeNet کپیِ padded می‌سازد — یک
# PNGِ ۱٫۲مگابایتیِ ۲۰۰۰۰² حدود ۳٫۵ گیگ RAM می‌گیرد و آلبومِ چنین فایل‌هایی روی
# `max_jobs` ورکر را OOM می‌کند. تا این سقف مستقیم decode می‌شود (~۱۰۰MB)، بالاتر
# اول با Pillow کوچک می‌شود، و اگر آن‌قدر بزرگ باشد که Pillow هم نتواند امن
# decodeش کند، اسکن رد می‌شود (fail-open، هم‌راستا با طراحیِ فیلتر).
_MAX_SCAN_PIXELS = 12_000_000     # ~۱۲ مگاپیکسل


def _image_dims(path: str) -> tuple[int, int] | None:
    """ابعادِ تصویر از هدر (بدونِ decodeِ کامل). None اگر Pillow نبود/خطا داد."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 — Pillow در این محیط نیست
        return None
    try:
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:  # noqa: BLE001
        return None


def _downscale_image(path: str, workdir: str) -> str | None:
    """تصویرِ بزرگ را به ≤۱۲۸۰px کوچک و در یک فایلِ موقت ذخیره می‌کند.

    None اگر Pillow نبود یا تصویر آن‌قدر بزرگ باشد که decodeِ امن ممکن نباشد
    (گاردِ bombِ خودِ Pillow raise می‌کند) — آن‌وقت فراخواننده اسکن را رد می‌کند.
    """
    try:
        from PIL import Image, ImageOps
    except Exception:  # noqa: BLE001
        return None
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((1280, 1280))
            dst = os.path.join(workdir, f"nsfw-sc-{secrets.token_hex(3)}.jpg")
            im.convert("RGB").save(dst, "JPEG", quality=85)
            return dst
    except Exception as exc:  # noqa: BLE001 — از جمله DecompressionBombError
        log.warning("image downscale failed (%s) — scan skipped", str(exc)[:120])
        return None


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
        wd = workdir or os.path.dirname(path) or "."
        dims = _image_dims(path)
        if dims and dims[0] * dims[1] > _MAX_SCAN_PIXELS:
            # بزرگ‌تر از آن که مستقیم decode شود: اول کوچکش کن، وگرنه رد کن.
            small = _downscale_image(path, wd)
            if small:
                targets, tmp = [small], [small]
            else:
                log.warning("image too large to scan safely (%dx%d) — skipped",
                            dims[0], dims[1])
                return False, 0.0, ""          # fail-open
        else:
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
_HIT = "nsfw:hit:"      # قدیمی (رشته‌ای، تا فاز ۴) — فقط برای جمعِ صفحهٔ سلامت تا انقضا
_STRIKES = "nsfw:strikes:"   # nsfw:strikes:<tg_user_id> → ZSETِ مهرِ زمانِ هر تخلف
STRIKE_WINDOW = 30 * 86400


async def note_block(redis, tg_user_id: int, policy: Policy) -> int:
    """یک تخلف را بشمار و تعدادِ کلِ اخیر را برگردان (۰ اگر Redis نبود)."""
    if redis is None or not tg_user_id:
        return 0
    # **پنجرهٔ لغزانِ واقعی، نه شمارنده با TTLِ تمدیدشونده.** فرمِ قبلی `INCR` و
    # بعد `EXPIRE 30d` روی **هر** تخلف بود، پس هر تخلفِ تازه عمرِ همهٔ قبلی‌ها را
    # تمدید می‌کرد: کاربری که هر سه هفته یک مثبتِ کاذب می‌خورد شمارنده‌اش هرگز صفر
    # نمی‌شد و با `safety_strikes` روشن سرانجام خودکار مسدود می‌شد — در حالی که
    # گزارشِ ادمین «تخلف‌های ۳۰ روزِ اخیر» می‌نوشت. حالا هر تخلف مهرِ زمانِ خودش را
    # دارد و فقط آن‌هایی شمرده می‌شوند که واقعاً در ۳۰ روزِ اخیرند.
    try:
        k = _STRIKES + str(tg_user_id)
        now = time.time()
        pipe = redis.pipeline()
        pipe.zadd(k, {f"{now:.6f}:{secrets.token_hex(3)}": now})
        pipe.zremrangebyscore(k, "-inf", now - STRIKE_WINDOW)
        pipe.zcard(k)
        pipe.expire(k, STRIKE_WINDOW)
        res = await pipe.execute()
        return int(res[2])
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
        # `reason` از ورودیِ کاربر ساخته می‌شود (`domain:<host>`؛ و `urlparse` در
        # hostname کاراکترِ `<` را نگه می‌دارد)، پس escape لازم است. `detail` را
        # فراخوان می‌سازد و مسئولِ escapeِ بخشِ کاربریِ آن است (هر چهار فراخوان).
        text = (f"🔞 <b>محتوای غیرمجاز مسدود شد</b>\n\n"
                f"کاربر: <code>{tg_user_id}</code>\n"
                f"دلیل: <code>{_html_escape(reason)}</code>\n"
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
        cutoff = time.time() - STRIKE_WINDOW
        async for k in redis.scan_iter(match=_STRIKES + "*", count=500):
            total += int(await redis.zcount(k, cutoff, "+inf"))
        async for k in redis.scan_iter(match=_HIT + "*", count=500):   # کلیدهای پیش از فاز ۴
            total += int(await redis.get(k) or 0)
        return total
    except Exception:  # noqa: BLE001
        return 0
