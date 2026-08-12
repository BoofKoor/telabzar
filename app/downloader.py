"""موتورِ دانلود (اجرا در ورکرِ اختصاصیِ دانلود).

yt-dlp (ویدیو/صوت) + gallery-dl (گالریِ عکس). مسیریابیِ host→engine، probe با
‎-J برای منوی کیفیت، و دانلود با proxy/cookies/pot-provider. subprocess مثلِ
processing._run با قراردادِ progress/cancel/ProcessingCancelled.

نکته‌های نقدِ طراحی که اینجا رعایت شده‌اند:
- حجمِ probe اغلب برای DASH/HLS نامعلوم است → تخمین از filesize_approx یا tbr×dur
  (چکِ قطعیِ حجم روی دیسک در tasks_download قبل از آپلود انجام می‌شود).
- egress از پروکسیِ تمیزِ خودت (‎--proxy)، نه لزوماً WARP.
"""
from __future__ import annotations

import asyncio
import difflib
import ipaddress
import json
import logging
import math
import mimetypes
import os
import re
import shutil
import socket
import tempfile
import time
import unicodedata
from urllib.parse import unquote, urljoin, urlparse

from .exceptions import ProcessingCancelled

log = logging.getLogger("telabzar.downloader")

YTDLP = "yt-dlp"
GALLERY_DL = "gallery-dl"

_URL_RE = re.compile(r"https?://[^\s<>()]+", re.I)
# همهٔ پسوندهای رسانه‌ای (fallbackِ یافتنِ خروجی وقتی پسوندِ موردِانتظار پیدا نشد).
_MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v",
               ".mp3", ".m4a", ".opus", ".ogg", ".oga", ".wav", ".flac", ".aac")
_GALLERY_PLATFORMS = {"instagram", "pinterest"}
# پلتفرم‌های صوتیِ تک‌استریم: منوی کیفیت بی‌معنی است → همیشه quick-grab.
# spotify هم صوتی است (تطبیق روی یوتیوب) → بی‌منوی کیفیت.
AUDIO_PLATFORMS = {"soundcloud", "bandcamp", "spotify"}
# پلتفرم‌های استریمِ DRM‌دار که مستقیم دانلود نمی‌شوند → متادیتا از API + تطبیقِ یوتیوب.
_MATCH_PLATFORMS = {"spotify"}
# میزبان‌های داخلی که هرگز نباید دانلود شوند (دفاعِ پایهٔ SSRF)
_BLOCK_HOSTS = {"localhost", "metadata.google.internal", "169.254.169.254"}
_DNS_TTL = 60.0            # ثانیه — عمرِ کشِ resolve (درِ ورودی مسیرِ داغِ ربات است)
_DNS_TIMEOUT = 2.0         # ثانیه — بیش از این یعنی DNS جواب نمی‌دهد
_DNS_CACHE_MAX = 512
_dns_cache: dict[str, tuple[float, bool]] = {}   # host → (انقضا, مجاز؟)

# برچسبِ فارسیِ پلتفرم‌ها — منبعِ واحد (پنل، متریک، پیام‌ها از این می‌خوانند).
PLATFORM_LABELS = {
    "youtube": "یوتیوب", "instagram": "اینستاگرام", "twitter": "X / توییتر",
    "tiktok": "تیک‌تاک", "pinterest": "پینترست", "soundcloud": "ساندکلاود",
    "aparat": "آپارات", "vimeo": "ویمئو", "twitch": "توییچ",
    "dailymotion": "دیلی‌موشن", "bandcamp": "بندکمپ", "reddit": "ردیت",
    "streamable": "استریمبل", "spotify": "اسپاتیفای", "other": "عمومی / سایر",
}
# برچسبِ انگلیسیِ پلتفرم‌ها (برای پیامِ کاربرِ en).
PLATFORM_LABELS_EN = {
    "youtube": "YouTube", "instagram": "Instagram", "twitter": "X / Twitter",
    "tiktok": "TikTok", "pinterest": "Pinterest", "soundcloud": "SoundCloud",
    "aparat": "Aparat", "vimeo": "Vimeo", "twitch": "Twitch",
    "dailymotion": "Dailymotion", "bandcamp": "Bandcamp", "reddit": "Reddit",
    "streamable": "Streamable", "spotify": "Spotify", "other": "the site",
}
# پلتفرم‌های شناخته‌شده (برای متریکِ per-host؛ «other» شناخته‌شده نیست).
KNOWN_PLATFORMS = tuple(k for k in PLATFORM_LABELS if k != "other")


def platform_label(platform: str, lang: str = "fa") -> str:
    """نامِ خواناـیِ پلتفرم به زبانِ کاربر."""
    if lang == "en":
        return PLATFORM_LABELS_EN.get(platform, platform.title())
    return PLATFORM_LABELS.get(platform, platform)


def describe_link(url: str, platform: str, lang: str = "fa") -> str:
    """عبارتِ مشخصِ انسانی برای لینکِ شناسایی‌شده — بر پایهٔ مسیرِ URL (استوری/ریلز/…).

    فقط وقتی زیرنوع را اعلام می‌کند که URL صریح باشد؛ وگرنه فقط نامِ پلتفرم.
    مصرف‌کننده: پیامِ «… شناسایی شد» در همان لحظهٔ دریافتِ لینک.
    """
    fa = lang != "en"
    path = (urlparse(url).path or "").lower()
    if platform == "instagram":
        if "/stories/" in path or "/story/" in path:
            return "استوریِ اینستاگرام" if fa else "an Instagram story"
        if "/reel" in path:
            return "ریلزِ اینستاگرام" if fa else "an Instagram reel"
        if "/tv/" in path:
            return "ویدیوی اینستاگرام" if fa else "an Instagram video"
        if "/p/" in path:
            return "پستِ اینستاگرام" if fa else "an Instagram post"
        return "لینکِ اینستاگرام" if fa else "an Instagram link"
    if platform == "youtube":
        if "/shorts/" in path:
            return "شورتسِ یوتیوب" if fa else "a YouTube Short"
        if "/playlist" in path or "list=" in (urlparse(url).query or ""):
            return "پلی‌لیستِ یوتیوب" if fa else "a YouTube playlist"
        return "ویدیوی یوتیوب" if fa else "a YouTube video"
    if platform == "tiktok":
        return "ویدیوی تیک‌تاک" if fa else "a TikTok video"
    if platform == "pinterest":
        return "پینِ پینترست" if fa else "a Pinterest pin"
    if platform == "spotify":
        kind, _sid = spotify_id(url)
        if kind == "album":
            return "آلبومِ اسپاتیفای" if fa else "a Spotify album"
        if kind == "playlist":
            return "پلی‌لیستِ اسپاتیفای" if fa else "a Spotify playlist"
        return "آهنگِ اسپاتیفای" if fa else "a Spotify track"
    label = platform_label(platform, lang)
    if platform == "other":
        return "لینک" if fa else "a link"
    return f"لینکِ {label}" if fa else f"a {label} link"


# نشانه‌های خطای «ربات نیستی؟» یوتیوب — نیازمندِ کوکیِ لاگین‌شده (نه صرفاً pot-token).
_YT_BOTCHECK_HINTS = ("sign in to confirm", "confirm you're not a bot",
                       "confirm you are not a bot", "--cookies", "cookies-from-browser")


def is_youtube_botcheck(msg: str, platform: str | None = None) -> bool:
    """آیا خطا همان «Sign in to confirm you're not a bot»ِ یوتیوب است؟

    این خطا با IPِ دیتاسنتر حتی با pot-provider هم رخ می‌دهد؛ راهِ عملی، کوکیِ
    یوتیوب (youtube_*.txt) و/یا پروکسیِ تمیز است. پیامِ کاربرپسندِ مخصوص می‌خواهد.
    """
    if platform not in (None, "youtube"):
        return False
    low = (msg or "").lower()
    return any(h in low for h in _YT_BOTCHECK_HINTS)


def find_url(text: str | None) -> str | None:
    m = _URL_RE.search(text or "")
    if not m:
        return None
    return m.group(0).rstrip(".,);]")


def platform_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    if any(h in host for h in ("youtube.com", "youtu.be", "youtube-nocookie")):
        return "youtube"
    if "instagram.com" in host:
        return "instagram"
    if host in ("twitter.com", "x.com") or host.endswith((".twitter.com", ".x.com")):
        return "twitter"
    if "tiktok.com" in host:
        return "tiktok"
    if "pinterest." in host:
        return "pinterest"
    if "soundcloud.com" in host or "snd.sc" in host:
        return "soundcloud"
    if "aparat.com" in host:
        return "aparat"
    if "vimeo.com" in host:
        return "vimeo"
    if "twitch.tv" in host:
        return "twitch"
    if "dailymotion.com" in host or "dai.ly" in host:
        return "dailymotion"
    if "bandcamp.com" in host:
        return "bandcamp"
    if "reddit.com" in host or "redd.it" in host:
        return "reddit"
    if "streamable.com" in host:
        return "streamable"
    if "spotify.com" in host or host == "spotify":  # open.spotify.com و spotify: URI
        return "spotify"
    return "other"


def engine_for(url: str, platform: str | None = None) -> str:
    p = platform or platform_of(url)
    if p in _MATCH_PLATFORMS:
        return "spotify"       # متادیتا از API + تطبیقِ یوتیوب
    return "gallerydl" if p in _GALLERY_PLATFORMS else "ytdlp"


# محدوده‌هایی که `ipaddress` خصوصی نمی‌داند ولی عمومی هم نیستند.
# ‎100.64.0.0/10 = CGNATِ اپراتورها (RFC 6598) — تجهیزاتِ شبکه آن‌جا زندگی می‌کنند.
_EXTRA_INTERNAL_NETS = (ipaddress.ip_network("100.64.0.0/10"),)


def _addr_is_internal(addr: str) -> bool:
    """آیا این IP به شبکهٔ داخلی/خودِ ماشین می‌رسد؟"""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True                 # نفهمیدیم چیست → محافظه‌کارانه رد
    v4 = getattr(ip, "ipv4_mapped", None)
    if v4 is not None:
        ip = v4                     # ::ffff:127.0.0.1 → is_loopback برایش False است
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved \
            or ip.is_multicast or ip.is_unspecified:
        return True
    return any(ip.version == n.version and ip in n for n in _EXTRA_INTERNAL_NETS)


def _literal_addrs(host: str) -> list[str] | None:
    """اگر `host` خودش IPِ لفظی است آدرس‌هایش را بده، وگرنه None (یعنی نامِ دامنه).

    عمداً `AI_NUMERICHOST` و نه `ipaddress.ip_address`: معناشناسیِ libc همان است که
    خودِ اتصال به کار می‌برد و شکل‌های `127.1` / `2130706433` / `0x7f000001` /
    `017700000001` را هم می‌فهمد — دقیقاً همان‌هایی که `ip_address()` با ValueError
    رد می‌کرد و کد آن را «پس نامِ دامنه است → مجاز» می‌خواند.
    """
    try:
        info = socket.getaddrinfo(host, None, flags=socket.AI_NUMERICHOST)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    return [i[4][0] for i in info]


def is_safe_url(url: str) -> bool:
    """دفاعِ **نحویِ** SSRF (بدونِ DNS): فقط http(s)، ردِ لوپ‌بک/خصوصی/داخلی.

    ارزان و همگام است، پس هرجا (از جمله per-hopِ ریدایرکت) می‌شود صدایش زد. برای
    هاستی که **نام** است نه IPِ لفظی، این تابع چیزی نمی‌داند — `is_safe_url_resolved`
    را ببین.
    """
    try:
        p = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    if host in _BLOCK_HOSTS:
        return False
    addrs = _literal_addrs(host)
    if addrs is not None:
        return not any(_addr_is_internal(a) for a in addrs)
    return True     # نامِ میزبان است — قضاوتش کارِ is_safe_url_resolved


async def is_safe_url_resolved(url: str, proxy: str | None = None) -> bool:
    """`is_safe_url` + resolveِ واقعیِ نام. درِ ورودیِ لینک این را صدا می‌زند.

    بدونِ این، `evil.example` با A-recordِ ۱۶۹٫۲۵۴٫۱۶۹٫۲۵۴ از فیلترِ نحوی رد می‌شد.
    `getaddrinfo` در thread می‌رود تا حلقهٔ رویدادِ ربات بند نیاید، و نتیجه
    `_DNS_TTL` ثانیه کش می‌شود (لینکِ تکراری دوباره DNS نمی‌زند).

    **شکستِ DNS همیشه رد است — با پروکسی یا بی‌پروکسی (تغییرِ فاز ۳ت).** قبلاً با
    پروکسیِ ست‌شده اجازه می‌داد، به این استدلال که «نام را پروکسی حل می‌کند و دیدِ
    محلیِ ما بی‌ربط است». آن استدلال فقط برای DNSِ افقِ‌تقسیم‌شده صادق است — پروکسیِ
    داخلی‌ای که نامی را ببیند که ما نمی‌بینیم — و خروجیِ ما بیرونی است و مستر یک VPS
    با DNSِ سالم. در مقابل، هزینه‌اش یک دورزدنِ واقعی بود: نامی که برای ما NXDOMAIN
    است ولی پروکسی حلش می‌کند، از درِ ورودی رد می‌شد — و در حالتِ پروکسی همین در
    **تنها** دفاع است، چون رزولورِ وتوکننده آن‌جا وصل نمی‌شود (`_direct_connector`).
    یعنی fail-open دقیقاً همان‌جا ضعیف بود که بیشترین اهمیت را داشت.
    """
    if not is_safe_url(url):
        return False
    host = (urlparse(url).hostname or "").lower()
    if _literal_addrs(host) is not None:
        return True                 # لفظی بود و is_safe_url همان‌جا تأییدش کرد
    now = time.monotonic()
    hit = _dns_cache.get(host)
    if hit is not None and hit[0] > now:
        return hit[1]
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM),
            timeout=_DNS_TIMEOUT)
        ok = not any(_addr_is_internal(i[4][0]) for i in info)
        if not ok:
            log.warning("blocked url: %s resolves to an internal address", host[:90])
    except (socket.gaierror, asyncio.TimeoutError, OSError, UnicodeError) as exc:
        ok = False
        log.warning("blocked url: dns lookup failed for %s (%s)", host[:90], exc)
    if len(_dns_cache) >= _DNS_CACHE_MAX:
        _dns_cache.clear()          # کشِ کوچک و بی‌اهمیت — پاکسازیِ ساده کافی است
    _dns_cache[host] = (now + _DNS_TTL, ok)
    return ok


def _safe_resolver():
    """رزولورِ aiohttp که آدرسِ داخلی را سرِ **اتصال** رد می‌کند.

    چرا رزولور و نه یک چکِ جدا: بینِ «چک کردیم» تا «وصل شدیم» پنجرهٔ TOCTOU هست
    (DNS rebinding — همان نام بارِ دوم IPِ دیگری بدهد). وقتی خودِ aiohttp با این
    رزولور وصل می‌شود، آدرسی که واقعاً به آن وصل می‌شویم همان است که وتو شده، و هر
    پرشِ ریدایرکت هم خودکار پوشش داده می‌شود.

    **نکته‌ای که باید بماند:** وقتی `proxy=` ست باشد، aiohttp نامِ *پروکسی* را حل
    می‌کند نه مقصد را — مقصد را پروکسی حل می‌کند و ما اصلاً نمی‌بینیمش. این آگاهانه
    پذیرفته است: پروکسیِ خروجیِ ادمین بیرونِ شبکهٔ داخلیِ مستر است، پس مسیرِ حمله
    به شبکهٔ داخلی از آن‌جا باز نمی‌شود. به همین دلیل `_direct_connector` وقتی
    پروکسی در کار است این رزولور را **اصلاً وصل نمی‌کند** — ببین آن‌جا.
    """
    import aiohttp

    class SafeResolver(aiohttp.DefaultResolver):
        async def resolve(self, host, port=0, family=socket.AF_INET):
            hosts = await super().resolve(host, port, family)
            if any(_addr_is_internal(h["host"]) for h in hosts):
                raise OSError(f"blocked url: {host[:90]} resolves to an internal address")
            return hosts

    return SafeResolver()


def _direct_connector(opts: dict):
    """کانکتورِ سشنِ موتورِ `direct` — سه حالت، هرکدام با دلیلِ خودش.

    **بدونِ پروکسی:** رزولورِ وتوکننده وصل می‌شود (بستنِ پنجرهٔ TOCTOU).

    **با پروکسیِ http(s):** بدونِ آن رزولور. aiohttp در حالتِ پروکسی نامِ
    *پروکسی* را حل می‌کند نه مقصد را، پس رزولور هیچ حفاظتی از مقصد نمی‌دهد و فقط
    می‌تواند خودِ پروکسی را بشکند — `http://squid:3128` (نامِ سرویسِ داکر) به
    ۱۷۲٫x حل می‌شود و «داخلی» شمرده می‌شد.

    **با پروکسیِ socks:** از `ProxyConnector` رد می‌شود. تا فاز ۳ت این‌جا
    `proxy=None` می‌رفت و موتورِ `direct` **بی‌صدا مستقیم** وصل می‌شد، یعنی از
    IPِ خودِ مستر — در حالی که مستندِ ما `socks5h` را توصیه می‌کرد. همان باگ.

    **رزولورِ وتوکننده در حالتِ socks قابلِ وصل نیست، و این را باید دانست:**
    `ProxyConnector.__init__` بی‌قیدوشرط `kwargs["resolver"] = NoResolver()`
    می‌کند (سنجیده روی ۰.۱۲.۰)، پس هر رزولوری که بدهیم **بی‌صدا** دور ریخته
    می‌شود. جایگزینی‌اش هم بررسی و رد شد: اگر IPِ تأییدشده را پین کنیم،
    python_socks همان را `server_hostname` می‌کند
    (`_stream.start_tls(hostname=dest_host)`) و اعتبارسنجیِ سرتیفیکیتِ هر هاستِ
    HTTPS می‌شکند. پس دفاع این‌جا **درِ ورودی** است — دقیقاً همان وضعی که برای
    پروکسیِ http(s) از قبل پذیرفته شده، نه سوراخِ تازه.
    """
    import aiohttp
    kind, url = _proxy_kind(opts.get("proxy"))
    if kind == "socks" and opts.get("direct_proxy", True):
        from aiohttp_socks import ProxyConnector
        return ProxyConnector.from_url(url, rdns=True)
    if kind == "http":
        return aiohttp.TCPConnector()
    return aiohttp.TCPConnector(resolver=_safe_resolver())


def _writable_cookie(cookie_path: str | None) -> str | None:
    """کپیِ نوشتنیِ فایلِ کوکی در temp و برگرداندنِ مسیرش (یا None اگر نشد/نبود).

    چرا لازم است: mountِ /cookies در ورکر فقط‌خواندنی است، ولی yt-dlp (و gallery-dl)
    کوکی‌جار را پس از رفرش به همان فایل برمی‌گردانند → OSError روی فایل‌سیستمِ
    فقط‌خواندنی. پس هر بار قبل از دادن کوکی به موتور، یک کپیِ نوشتنی می‌سازیم و write-back
    آنجا (بی‌ضرر) می‌افتد؛ فراخوان با _cleanup_cookie پاکش می‌کند.
    """
    if not cookie_path or not os.path.isfile(cookie_path):
        return None
    try:
        fd, tmp = tempfile.mkstemp(prefix="telabzar-ck-", suffix=".txt")
        os.close(fd)
        shutil.copyfile(cookie_path, tmp)
        return tmp
    except OSError:
        return None


def _cleanup_cookie(tmp_path: str | None) -> None:
    if tmp_path:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ── پرچم‌های مشترکِ yt-dlp (proxy / cookies / pot-provider) ─────
def _common_flags(opts: dict) -> list[str]:
    flags = ["--no-warnings", "--no-playlist"]
    if opts.get("proxy"):
        flags += ["--proxy", opts["proxy"]]
    if opts.get("user_agent"):   # هویتِ سشن: همان UA که اکانت با آن شناخته می‌شود
        flags += ["--user-agent", opts["user_agent"]]
    if opts.get("cookies"):
        flags += ["--cookies", opts["cookies"]]
    if opts.get("pot_provider"):
        flags += ["--extractor-args", f"youtubepot-bgutilhttp:base_url={opts['pot_provider']}"]
    return flags


def _est_mb(fmt: dict, duration: float | None) -> float | None:
    """تخمینِ حجم: filesize → filesize_approx → tbr×duration (برای DASH که حجم ندارد)."""
    sz = fmt.get("filesize") or fmt.get("filesize_approx")
    if sz:
        return round(sz / 1024 / 1024, 1)
    tbr = fmt.get("tbr")  # kbps
    if tbr and duration:
        return round(tbr * 1000 / 8 * duration / 1024 / 1024, 1)
    return None


_TARGET_HEIGHTS = (2160, 1440, 1080, 720, 480, 360)


# فیلدهایی که فیلترِ محتوای بزرگسال (`safety.check_meta`) می‌خوانَد. تا دیروز
# `normalize_probe` هیچ‌کدام را حمل نمی‌کرد، پس در فازِ probe شرطِ `age_limit>=18`
# — که ارزان‌ترین و قوی‌ترین سیگنالِ ماست — **هرگز** شلیک نمی‌کرد و لایهٔ ۲ عملاً
# به تطبیقِ کلیدواژه روی «عنوان» تقلیل پیدا می‌کرد.
_META_LIMITS = {"description": 2000, "tags": 40, "categories": 20}


def _carry_meta(data: dict) -> dict:
    """فیلدهای موردِ نیازِ `safety.check_meta` را (با سقفِ اندازه) از ‎-J بردار."""
    out: dict = {}
    for key in ("age_limit", "uploader", "channel"):
        if data.get(key) is not None:
            out[key] = data[key]
    desc = data.get("description")
    if desc:
        out["description"] = str(desc)[:_META_LIMITS["description"]]
    for key in ("tags", "categories"):
        val = data.get(key)
        if isinstance(val, (list, tuple)) and val:
            out[key] = [str(v) for v in val[:_META_LIMITS[key]]]
    return out


def normalize_probe(data: dict) -> dict:
    """خروجیِ ‎-J را به {title, duration, kind, options[], + متادیتای ایمنی} تمیز می‌کند."""
    duration = data.get("duration")
    formats = data.get("formats") or []
    # بیشترین tbr ویدیویی به‌ازای هر ارتفاع + یک صوتِ نماینده (برای تخمینِ merge)
    audio_tbr = max((f.get("tbr") or 0 for f in formats
                     if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")),
                    default=128.0) or 128.0
    heights = {f.get("height") for f in formats if f.get("height")}
    options: list[dict] = []
    for h in _TARGET_HEIGHTS:
        if not any(fh and fh >= h for fh in heights):
            continue
        vids = [f for f in formats if f.get("height") == h and f.get("vcodec") not in (None, "none")]
        if not vids:
            continue
        best = max(vids, key=lambda f: f.get("tbr") or 0)
        est = _est_mb({"tbr": (best.get("tbr") or 0) + audio_tbr,
                       "filesize": best.get("filesize")}, duration)
        options.append({"sel": str(h), "height": h,
                        "label": f"{h}p" + (f" · ~{est:g}MB" if est else ""), "est_mb": est})
    return {
        "title": data.get("title") or data.get("id") or "download",
        "duration": duration,
        "kind": "audio" if data.get("vcodec") in (None, "none") and not data.get("height") else "video",
        "thumbnail": data.get("thumbnail"),
        "options": options,
        **_carry_meta(data),
    }


def _stderr_summary(raw: bytes | str, limit: int = 300) -> str:
    """خلاصهٔ *مفیدِ* stderrِ yt-dlp/gallery-dl.

    نکته: وقتی yt-dlp خودش کرش می‌کند، stderr یک Traceback‌ِ پایتون است که خطِ
    اولش (`sys.exit(main())`) بی‌فایده است و خطای واقعی در *آخرین* خط می‌آید. پس:
    خطِ ERROR:‌ِ خودِ yt-dlp را ترجیح بده؛ اگر تریس‌بک بود آخرین خطِ استثنا را بردار؛
    وگرنه دو خطِ آخر. اینطوری پیامِ کاربر و لاگ به‌جای سرِ تریس‌بک، علتِ واقعی را نشان می‌دهد.
    """
    text = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else (raw or "")
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    err_lines = [ln for ln in lines if ln.lstrip().startswith("ERROR:")]
    if err_lines:
        return " ".join(err_lines[-1].split())[:limit]
    if any("Traceback (most recent call last)" in ln for ln in lines):
        for ln in reversed(lines):  # آخرین خطِ «SomeError: …» (نه خطِ File "…")
            s = ln.strip()
            if s and not s.startswith(("File \"", "Traceback", "During handling", "The above")):
                return " ".join(s.split())[:limit]
    return " ".join(" | ".join(lines[-2:]).split())[:limit]


async def probe(url: str, opts: dict, timeout: float = 120) -> dict:
    """اطلاعاتِ رسانه بدونِ دانلود (‎-J) → دیکشنریِ نرمال‌شده."""
    ck = _writable_cookie(opts.get("cookies"))  # /cookies فقط‌خواندنی → کپیِ نوشتنی
    if ck:
        opts = {**opts, "cookies": ck}
    try:
        cmd = [YTDLP, "-J", *_common_flags(opts), url]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError("probe timed out") from None
        if proc.returncode != 0:
            raise RuntimeError(f"probe failed: {_stderr_summary(err) or 'unknown'}")
        return normalize_probe(json.loads(out.decode("utf-8", "ignore") or "{}"))
    finally:
        _cleanup_cookie(ck)


def _selector_to_format(sel: str) -> str:
    if sel in ("best", ""):
        return "bv*+ba/b"
    if sel == "audio":
        return "ba/b"
    if sel.isdigit():
        return f"bv*[height<={sel}]+ba/b[height<={sel}]/b"
    return "bv*+ba/b"


# ترتیبِ انتخابِ فرمت برای **سازگاریِ تلگرام**: در همان رزولوشنی که کاربر خواسته،
# h264+aac در mp4 را ترجیح بده. یوتیوب تا ۱۰۸۰p همیشه h264 دارد؛ بدونِ این ترتیب
# VP9/AV1/Opus (یعنی webm) انتخابِ اولِ yt-dlp است و فایلِ غیرِmp4 درمی‌آید.
# `res` اول می‌آید تا کیفیتِ انتخابیِ کاربر قربانیِ کدک نشود.
_FORMAT_SORT = "res,vcodec:h264,acodec:aac,ext:mp4:m4a"


_OUT_TAIL_LINES = 40       # چند خطِ آخرِ stdout نگه داشته شود (تشخیص، نه لاگ)
# پیامِ خودِ yt-dlp وقتی `--match-filter` ویدیو را رد می‌کند. متنِ کامل بین نسخه‌ها
# فرق می‌کند (با/بدونِ پرانتزِ عبارتِ فیلتر)، ولی این تکه ثابت مانده است.
_MATCH_FILTER_MARK = "does not pass filter"


async def _run_dl(cmd: list[str], progress=None, cancel=None, timeout: float = 3000) -> str:
    """اجرای yt-dlp/gallery-dl با خواندنِ درصد از stdout و چکِ لغو.

    برمی‌گرداند: دُمِ کراندارِ stdout (فراخوان‌هایی که لازم ندارند نادیده‌اش می‌گیرند).

    لغو با **همان ناظرِ مشترکِ** `processing` انجام می‌شود، نه با چک روی هر خطِ
    stdout. importِ آن عمداً تنبل است (مثلِ `_ffprobe_video` پایین‌تر) تا این
    ماژول در زمانِ import به PIL گره نخورد.
    """
    from . import processing as _P     # تنبل — منبعِ یکتای ناظرِ لغو
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    err_chunks: list[bytes] = []
    out_tail: list[str] = []       # دُمِ کراندارِ stdout (برای تشخیصِ ردِ match-filter)

    async def _drain_err() -> None:
        async for raw in proc.stderr:  # type: ignore[union-attr]
            err_chunks.append(raw)

    async def _read_out() -> None:
        async for raw in proc.stdout:  # type: ignore[union-attr]
            line = raw.decode("utf-8", "ignore").strip()
            if line and not line.startswith("dl:"):
                out_tail.append(line[:300])
                if len(out_tail) > _OUT_TAIL_LINES:
                    del out_tail[0]
            if line.startswith("dl:") and progress is not None:
                m = re.search(r"([\d.]+)%", line)
                if m:
                    try:
                        await progress(float(m.group(1)))
                    except Exception:  # noqa: BLE001
                        pass

    watch = _P.start_cancel_watcher(proc, cancel)
    try:
        await asyncio.wait_for(asyncio.gather(_read_out(), _drain_err()), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("download timed out") from None
    except BaseException:
        # همان درسِ ۲-۲، ولی این‌جا گران‌تر: روی `job_timeout`ِ ARQ یا خاموشیِ
        # ورکر، yt-dlpِ یتیم **به دانلود ادامه می‌دهد** — پهنای‌باند می‌خورد و
        # مهم‌تر از آن سهمیهٔ همان اکانتِ کوکی را می‌سوزاند که گران‌ترین منبعِ
        # ماست، بی‌آنکه هیچ‌جا ثبت شود (جاب مرده، پس `mark_ok/mark_fail` هم
        # صدا زده نمی‌شود). عمداً `await proc.wait()` نمی‌زنیم — در مسیرِ لغو
        # خودِ آن await می‌تواند دوباره `CancelledError` بگیرد.
        if proc.returncode is None:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):   # از قبل مرده
                pass
        raise
    finally:
        watch.stop()
    await proc.wait()
    if watch.fired:
        raise ProcessingCancelled()
    if proc.returncode != 0:
        # دُمِ stdout روی خودِ استثنا سوار می‌شود (نه در متنِ پیام): متنِ خطای کاربر
        # عوض نمی‌شود، ولی فراخوان می‌تواند بفهمد yt-dlp چه گفته — مثلِ ردِ
        # match-filter که بسته به نسخه، هم با خروجیِ صفر می‌آید هم با ناصفر.
        exc = RuntimeError("download failed: "
                           + (_stderr_summary(b"".join(err_chunks)) or "unknown"))
        exc.stdout_tail = "\n".join(out_tail)  # type: ignore[attr-defined]
        raise exc
    return "\n".join(out_tail)


def _newest(workdir: str, exts: tuple[str, ...] | None = None) -> str | None:
    best, best_m = None, -1.0
    for root, _d, names in os.walk(workdir):
        for n in names:
            if n.endswith(".info.json") or n.endswith(".part"):
                continue
            if exts and not n.lower().endswith(exts):
                continue
            p = os.path.join(root, n)
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > best_m:
                best, best_m = p, m
    return best


async def _ffprobe_video(path: str) -> dict:
    """(width, height, duration) از ffprobe — برای پرکردنِ متادیتای ناقصِ yt-dlp
    (merge‌شدهٔ DASHِ یوتیوب گاهی width/height ندارد)."""
    from . import processing as _P  # منبعِ یکتای probe (اجتناب از دو پیاده‌سازی)
    return await _P.probe_media(path)


async def _ensure_mp4(path: str) -> str:
    """اگر خروجی mp4 نیست، **فقط کانتینر** را به mp4 بازبسته‌بندی کن (بدونِ انکودِ مجدد).

    چرا لازم است: `--merge-output-format mp4` تنها وقتی اثر دارد که yt-dlp دو استریم را
    merge کند. دو مسیر دورش می‌زنند و فایلِ غیرِmp4 می‌سازند:
      ۱) سلکتور به فایلِ **از پیش mux‌شده** برسد (شاخهٔ `/b`) — یوتیوب اغلب webm/VP9 می‌دهد
         و چون merge‌ای نیست، هیچ remuxی هم رخ نمی‌دهد.
      ۲) کدک‌ها با mp4 سازگار نباشند — yt-dlp خودش به **mkv** برمی‌گردد و فقط warn می‌دهد.
    تلگرام `sendVideo` را برای mp4 تضمین می‌کند؛ webm/mkv یا سند می‌شود یا بدونِ پیش‌نمایش.
    remux ارزان است (کپیِ استریم) و اگر شکست خورد، فایلِ اصلی دست‌نخورده برمی‌گردد.
    """
    if not path or os.path.splitext(path)[1].lower() == ".mp4" or not os.path.exists(path):
        return path
    out = os.path.splitext(path)[0] + ".remux.mp4"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", path, "-c", "copy", "-movflags", "+faststart", out,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), timeout=900)
    except Exception:  # noqa: BLE001
        proc = None
    if proc is not None and proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
        final = os.path.splitext(path)[0] + ".mp4"
        try:
            os.replace(out, final)
            os.remove(path)
            return final
        except OSError:
            return out
    try:
        if os.path.exists(out):
            os.remove(out)
    except OSError:
        pass
    log.warning("mp4 remux failed, sending original container: %s", os.path.basename(path))
    return path


async def download_ytdlp(url: str, workdir: str, selector: str, opts: dict,
                         progress=None, cancel=None) -> tuple[str, dict, str | None]:
    """دانلود با yt-dlp → (مسیرِ فایل, info dict, مسیرِ تامبنیل). info.json را می‌خوانَد."""
    ck = _writable_cookie(opts.get("cookies"))  # /cookies فقط‌خواندنی → کپیِ نوشتنی
    if ck:
        opts = {**opts, "cookies": ck}
    outtmpl = os.path.join(workdir, "%(title).80B [%(id)s].%(ext)s")
    audio_only = selector == "audio"
    cmd = [YTDLP, "--newline", "--progress-template", "dl:%(progress._percent_str)s",
           "--concurrent-fragments", "4",  # دانلودِ موازیِ قطعه‌های DASH → سریع‌تر
           "--write-info-json", "--write-thumbnail", "--convert-thumbnails", "jpg",
           "-o", outtmpl, "-f", _selector_to_format(selector)]
    if audio_only:
        cmd += ["-x", "--audio-format", "mp3"]
    else:
        # faststart = اتمِ moov جلوی فایل → استریمِ مرورگری بلافاصله شروع می‌شود (نه پس از دانلودِ کامل)
        cmd += ["-S", _FORMAT_SORT,          # h264/aac/mp4 را در همان رزولوشن ترجیح بده
                "--merge-output-format", "mp4",
                "--postprocessor-args", "Merger:-movflags +faststart"]
    cmd += ["--embed-metadata"]  # عنوان/هنرمند و… داخلِ فایل
    if opts.get("sponsorblock"):  # حذفِ اسپانسر/اینترو (یوتیوب)
        cmd += ["--sponsorblock-remove", opts["sponsorblock"]]
    if opts.get("subs") and not audio_only:  # زیرنویسِ خودکار (en+fa)
        cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*,fa.*", "--embed-subs"]
    if opts.get("max_mb"):
        cmd += ["--max-filesize", f"{int(opts['max_mb'])}M"]
    if opts.get("max_age_limit"):
        # گیتِ سنیِ پیش‌از‌دانلود، روی **همان** فراخوانی: yt-dlp بعد از استخراج و
        # قبل از کشیدنِ بایت‌های رسانه رد می‌کند → صفر رفت‌وبرگشتِ اضافه، صفر مصرفِ
        # اضافه از سهمیهٔ اکانت.
        # `<?` و نه `<`: مقایسهٔ عددیِ ساده روی فیلدِ **غایب** در yt-dlp False می‌دهد،
        # یعنی `age_limit<18` هر ویدیویی را که extractor برایش age_limit ست نکرده
        # (اکثریتِ قاطع) رد می‌کرد. `<?` غیبت را «قبول» معنی می‌کند.
        cmd += ["--match-filter", f"age_limit<?{int(opts['max_age_limit'])}"]
    cmd += [*_common_flags(opts), url]
    try:
        out_tail = await _run_dl(cmd, progress=progress, cancel=cancel,
                                 timeout=opts.get("timeout", 3000))
    except RuntimeError as exc:
        if opts.get("max_age_limit") and _MATCH_FILTER_MARK in (
                getattr(exc, "stdout_tail", "") + str(exc)).lower():
            raise AgeRestricted() from None
        raise
    finally:
        _cleanup_cookie(ck)

    # فایلِ رسانه را با پسوندِ رسانه پیدا کن (نه تامبنیلِ jpg)
    media_exts = ((".mp3", ".m4a", ".opus", ".ogg", ".wav")
                  if audio_only else (".mp4", ".mkv", ".webm", ".mov"))
    path = _newest(workdir, media_exts)
    if not path:
        # منبعِ فقط-صوت (مثلِ ساندکلاود) حتی با selectorِ ویدیویی فایلِ صوتی می‌دهد؛
        # هر رسانه‌ای که تولید شده را بردار تا «produced no file» بی‌خود رخ ندهد.
        path = _newest(workdir, _MEDIA_EXTS)
    if not path:
        # فایلی نیست و yt-dlp گفت «رد شد» → گیتِ سنی، نه شکستِ دانلود. (بسته به
        # نسخه، ردِ match-filter با کدِ خروجیِ صفر هم می‌آید و اینجا می‌نشیند.)
        if opts.get("max_age_limit") and _MATCH_FILTER_MARK in out_tail.lower():
            raise AgeRestricted()
        raise RuntimeError("download produced no file")
    thumb = _newest(workdir, (".jpg", ".jpeg"))
    info = {}
    infop = next((os.path.join(r, n) for r, _d, ns in os.walk(workdir)
                  for n in ns if n.endswith(".info.json")), None)
    if infop:
        try:
            with open(infop, encoding="utf-8") as fh:
                info = json.load(fh)
        except Exception:  # noqa: BLE001
            pass
    if not audio_only:
        # کانتینر را قطعی mp4 کن (تکـفایلِ webm یا mkvِ fallback هم پوشش داده شود)
        path = await _ensure_mp4(path)
        # متادیتای ناقصِ ویدیو را با ffprobe کامل کن (کارت + منوی کاهشِ حجم دقیق شود)
        if not (info.get("width") and info.get("height") and info.get("duration")):
            probed = await _ffprobe_video(path)
            for k in ("width", "height", "duration"):
                if not info.get(k) and probed.get(k):
                    info[k] = probed[k]
    return path, info, thumb


async def download_cobalt(url: str, workdir: str, cobalt_url: str, opts: dict,
                          progress=None, cancel=None) -> tuple[str, dict, str | None]:
    """Fallback: نمونهٔ self-hostedِ Cobalt وقتی extractorِ yt-dlp می‌شکند.
    API‌اش JSON POST است؛ پاسخِ tunnel/redirect یک فایل می‌دهد."""
    import aiohttp

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if opts.get("cobalt_key"):
        headers["Authorization"] = f"Api-Key {opts['cobalt_key']}"
    base = cobalt_url.rstrip("/")
    timeout = aiohttp.ClientTimeout(total=opts.get("timeout", 1800))
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.post(base + "/", json={"url": url}, headers=headers) as r:
            data = await r.json(content_type=None)
        status = data.get("status")
        if status not in ("tunnel", "redirect"):
            raise RuntimeError(f"cobalt: {data.get('error') or status or 'no media'}")
        file_url = data["url"]
        filename = data.get("filename") or "cobalt.mp4"
        out = os.path.join(workdir, os.path.basename(filename))
        async with sess.get(file_url) as fr:
            if fr.status != 200:
                raise RuntimeError(f"cobalt download HTTP {fr.status}")
            with open(out, "wb") as fh:
                async for chunk in fr.content.iter_chunked(1 << 16):
                    if cancel is not None and await cancel():
                        raise ProcessingCancelled()
                    fh.write(chunk)
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        raise RuntimeError("cobalt produced no file")
    if os.path.splitext(out)[1].lower() in (".webm", ".mkv", ".mov", ".m4v"):
        out = await _ensure_mp4(out)   # کوبالت هم گاهی webm می‌دهد
    return out, await _ffprobe_video(out), None


# ── Spotify: متادیتا از Web API + تطبیقِ صوت روی یوتیوب ─────────────
# اسپاتیفای DRM دارد؛ استریمِ واقعی دانلود نمی‌شود. مسیر: با client-credentials
# متادیتا بگیر (بی‌نیاز به لاگینِ کاربر) → بهترین تطبیق را روی یوتیوب دانلود کن →
# (اختیاری) تگ/کاور را با متادیتای اسپاتیفای بازنویسی کن.
_SPOTIFY_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[\w-]+/)?(track|album|playlist)/([A-Za-z0-9]+)")


def spotify_id(url: str) -> tuple[str | None, str | None]:
    m = _SPOTIFY_RE.search(url or "")
    return (m.group(1), m.group(2)) if m else (None, None)


async def _spotify_token(client_id: str, secret: str) -> str:
    import aiohttp
    async with aiohttp.ClientSession() as s:
        async with s.post("https://accounts.spotify.com/api/token",
                          data={"grant_type": "client_credentials"},
                          auth=aiohttp.BasicAuth(client_id, secret)) as r:
            if r.status != 200:
                raise RuntimeError(f"spotify auth failed (HTTP {r.status}) — کلیدها را چک کن")
            return (await r.json())["access_token"]


async def _spotify_get(url: str, token: str) -> dict:
    import aiohttp
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers={"Authorization": f"Bearer {token}"}) as r:
            if r.status != 200:
                raise RuntimeError(f"spotify API {r.status}")
            return await r.json()


def _track_meta(t: dict, album: dict | None = None) -> dict:
    album = album or t.get("album") or {}
    images = album.get("images") or []
    return {
        "title": t.get("name") or "",
        "artist": ", ".join(a["name"] for a in (t.get("artists") or []) if a.get("name")),
        "album": album.get("name") or "",
        "year": (album.get("release_date") or "")[:4],
        "cover_url": images[0]["url"] if images else None,
        "duration": round((t.get("duration_ms") or 0) / 1000) or None,  # مثلِ `_embed_track`
        "isrc": (t.get("external_ids") or {}).get("isrc"),
    }


async def _spotify_api_resolve(url: str, client_id: str, secret: str, max_tracks: int) -> dict:
    """مسیرِ رسمیِ API (نیازمندِ client id/secret) — کامل‌ترین متادیتا + پلی‌لیستِ کامل."""
    kind, sid = spotify_id(url)
    token = await _spotify_token(client_id, secret)
    tracks: list[dict] = []
    title = ""
    if kind == "track":
        t = await _spotify_get(f"https://api.spotify.com/v1/tracks/{sid}", token)
        title = t.get("name") or ""
        tracks = [_track_meta(t)]
    elif kind == "album":
        alb = await _spotify_get(f"https://api.spotify.com/v1/albums/{sid}", token)
        title = alb.get("name") or ""
        for it in (alb.get("tracks", {}).get("items") or [])[:max_tracks]:
            tracks.append(_track_meta(it, album=alb))  # آیتمِ آلبوم خودش album ندارد
    elif kind == "playlist":
        pl = await _spotify_get(f"https://api.spotify.com/v1/playlists/{sid}", token)
        title = pl.get("name") or ""
        for it in (pl.get("tracks", {}).get("items") or [])[:max_tracks]:
            tr = it.get("track") or {}
            if tr.get("name"):
                tracks.append(_track_meta(tr))
    return {"kind": kind, "title": title, "tracks": tracks[:max_tracks]}


# فیلدهایی که «این آبجکت واقعاً entity است» را می‌سازند. صرفِ داشتنِ عنوان کافی
# نیست (چند آبجکتِ تودرتو عنوان دارند)؛ اهمیتشان در امتیازدهیِ زیر است.
_ENTITY_FIELDS = ("artists", "subtitle", "duration", "trackList", "coverArt",
                  "visualIdentity", "releaseDate", "uri")


def _entity_score(obj: dict) -> int:
    """چقدر شبیهِ entityِ اصلی است؟ بالاتر = کامل‌تر."""
    if not (obj.get("title") or obj.get("name")) and obj.get("trackList") is None:
        return 0
    n = sum(1 for k in _ENTITY_FIELDS if obj.get(k) not in (None, "", [], {}))
    if not n:
        return 0
    if str(obj.get("type") or "").lower() in ("track", "album", "playlist", "episode"):
        n += 2                       # خودِ اسپاتیفای می‌گوید این چیست
    return n


def _find_spotify_entity(obj):
    """در JSONِ __NEXT_DATA__ دنبالِ entity می‌گردد و **کامل‌ترین** را برمی‌دارد.

    نسخهٔ قبلی شرطِ `trackList is not None or (title and coverArt)` داشت و
    **اولین** تطبیق را برمی‌گرداند. هر دو نیمه شکستند: اسکیمای امروزِ اسپاتیفای
    اصلاً `coverArt` ندارد (کاور زیرِ `visualIdentity.image[]` رفته)، پس برای یک
    ترک هیچ‌وقت چیزی پیدا نمی‌شد؛ و «اولینِ تطبیق» یعنی یک زیرآبجکتِ تصادفی که
    اتفاقاً عنوان دارد می‌توانست برندهٔ entityِ واقعی شود.

    حالا وابسته به هیچ کلیدِ منفردی نیست: نامزدها امتیاز می‌گیرند (تعدادِ
    فیلدهای معنی‌دار + پاداشِ `type`) و بیشینه برنده می‌شود؛ تساوی → اولی، تا
    نتیجه قطعی بماند.
    """
    best, best_score = None, 0

    def walk(o):
        nonlocal best, best_score
        if isinstance(o, dict):
            s = _entity_score(o)
            if s > best_score:
                best, best_score = o, s
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return best


def _embed_cover(entity: dict) -> str | None:
    """کاور: شکلِ امروزی `visualIdentity.image[]`، و شکلِ قدیمیِ `coverArt.sources[]`."""
    imgs = ((entity.get("visualIdentity") or {}).get("image")) or []
    if not imgs:
        imgs = ((entity.get("coverArt") or {}).get("sources")) or []
    if not imgs:
        return None
    # بزرگ‌ترین را بردار؛ اگر ابعاد نیامده بود (اسپاتیفای امروز صفر می‌دهد) آخری،
    # که همان قراردادِ قبلی برای `sources` بود.
    best = max(imgs, key=lambda i: int(i.get("maxWidth") or 0)) if any(
        int(i.get("maxWidth") or 0) for i in imgs if isinstance(i, dict)) else imgs[-1]
    return best.get("url") if isinstance(best, dict) else None


def _embed_year(entity: dict) -> str:
    """`releaseDate.isoString` (امروز) یا رشتهٔ تاریخ (قدیم) → سالِ چهاررقمی."""
    rd = entity.get("releaseDate")
    if isinstance(rd, dict):
        rd = rd.get("isoString") or rd.get("date") or ""
    return str(rd or "")[:4]


def _embed_track(title: str | None, subtitle, cover: str | None, dur_ms,
                 year: str = "") -> dict:
    """یک ترکِ یکدست. `dur_ms` **میلی‌ثانیه** است — اسپاتیفای ۳۱۰۹۷۳ می‌دهد یعنی ۵:۱۱.

    اگر روزی کسی این را ثانیه بخواند، همان عدد می‌شود ~۳٫۶ روز و گیتِ مدت
    (`_duration_reject`) **هر** نامزدی را رد می‌کند — خرابیِ بی‌صدا از همان جنسی
    که این پارسر را هفته‌ها مرده نگه داشت. تست واحدش را قفل می‌کند.
    """
    # دو شکل، **هر دو زنده**: لینکِ تک‌ترک آرایهٔ `[{"name": …}, …]` می‌دهد و
    # ترکِ داخلِ `trackList`ِ پلی‌لیست یک رشتهٔ ساده. هیچ‌کدام کهنه نیست.
    if isinstance(subtitle, list):
        subtitle = ", ".join(x.get("name", "") if isinstance(x, dict) else str(x) for x in subtitle)
    # `round` نه `int`: بریدن هر مدتی را تا یک ثانیه **کم** می‌کند (۳۱۰۹۷۳ms →
    # ۳۱۰ به‌جای ۳۱۱)، و آن یک ثانیه روی `_time_match` حدودِ ۱۰ واحد می‌ارزد،
    # یعنی تطبیقِ دقیق را بی‌دلیل جریمه می‌کند.
    return {"title": title or "", "artist": (subtitle or "").strip(), "album": "", "year": year,
            "cover_url": cover, "duration": round((dur_ms or 0) / 1000) or None, "isrc": None}


def reference_is_blind(track: dict) -> bool:
    """مرجعی که نه هنرمند دارد نه مدت — یعنی matcher فقط روی نام قضاوت می‌کند.

    آن‌وقت **هر دو** گیت خاموش‌اند (`_artist_match` روی مرجعِ بی‌هنرمند `None`
    می‌دهد و شرطِ گیت `am is not None`ست؛ `_duration_reject` هر دو مدت را لازم
    دارد) و نامزدهای هم‌نام امتیازِ **دقیقاً یکسان** می‌گیرند، پس برنده صرفاً
    اولین نفرِ فهرست است. مصرف‌کنندهٔ کاربری‌اش رفعِ آستانه/هشدار است.
    """
    return not (track.get("artist") or "").strip() and not track.get("duration")


def _parse_spotify_embed(html: str, kind: str, max_tracks: int) -> dict | None:
    """JSONِ __NEXT_DATA__ی صفحهٔ embed → {kind, title, tracks[]} (خالص، تست‌پذیر)."""
    # الگو عمداً `(.*?)` است نه `(\{.*?\})`: فرمِ قبلی `}` را **بلافاصله** پیش از
    # `</script>` می‌خواست، پس یک newline یا تورفتگی کلِ پارس را ساکت می‌شکست.
    # این یکی همان فرمی است که روی صفحهٔ واقعی جواب داد.
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html or "", re.S)
    if not m:
        return None
    try:
        entity = _find_spotify_entity(json.loads(m.group(1).strip()))
    except (ValueError, KeyError):
        return None
    if not entity:
        return None
    title = entity.get("title") or entity.get("name") or ""
    tl = entity.get("trackList") or []
    # **`subtitle` سه معنا دارد، بسته به اینکه کجا باشد** — و یکی‌شان تله است:
    #   ترکِ داخلِ `trackList` → هنرمند (شکلِ زنده)
    #   entityِ سطحِ پلی‌لیست  → **مالکِ پلی‌لیست** (مثلاً «Spotify»)
    #   entityِ ترکِ قدیمی    → هنرمند (شکلِ کهنه)
    # شاخهٔ تک‌ترک روی `not tl` می‌افتاد نه روی `kind`، پس یک پلی‌لیستِ خالی یا
    # هر پلی‌لیستی که فهرستش خوانده نشود، **یک ترکِ ساختگی** می‌ساخت با نامِ
    # پلی‌لیست و هنرمندِ «Spotify» — و `reference_is_blind` هم نمی‌گرفتش، چون
    # «Spotify» هنرمندِ ناتهی است. سنجیده شد: خروجی `('Persian Essentials',
    # 'Spotify', None)` بود، یعنی جست‌وجوی یوتیوب برای «Spotify Persian
    # Essentials» و دانلودِ هرچه برگردد — بی‌صدا.
    etype = str(entity.get("type") or "").lower()
    if (kind in ("playlist", "album") or etype in ("playlist", "album")) and not tl:
        return None      # مجموعه‌ای که فهرستش خوانده نشد، «یک ترک» نیست
    if kind == "track" or not tl:
        # لینکِ **تک‌ترک**: هنرمند در `artists: [{name}]` است.
        artists = entity.get("subtitle") or entity.get("artists")
        tracks = [_embed_track(title, artists, _embed_cover(entity),
                               entity.get("duration"), _embed_year(entity))]
    else:
        # مسیرِ آلبوم/پلی‌لیست — **تأییدشده روی اسکیمای امروز** (دامپِ ۲۰۲۶-۰۸-۱۲،
        # پلی‌لیستِ ۱۰۰تایی). این شاخه هیچ‌وقت نشکسته بود؛ فقط لینکِ تک‌ترک خراب بود.
        #
        # ⚠ **`subtitle` کدِ کهنه نیست — شکلِ زندهٔ همین مسیر است.** دو مسیر دو شکلِ
        # متفاوت دارند و هر دو فعلی‌اند: ترکِ تکی `artists[].name` (آرایه) می‌دهد و
        # ترکِ داخلِ `trackList` یک `subtitle`ِ **رشته‌ای**. هر «پاکسازیِ کدِ کهنه»
        # که `subtitle` را بردارد، پلی‌لیست‌ها را می‌شکند.
        #
        # ترک‌های داخلِ `trackList` کاورِ اختصاصی ندارند، پس کاورِ سطحِ مجموعه
        # به همه‌شان می‌رسد. `playabilityReason` (مثلاً `COUNTRY_RESTRICTED`) هم
        # آن‌جا هست و برای ما بی‌اثر است، چون فایل را از یوتیوب می‌گیریم.
        alb_cover = _embed_cover(entity)
        alb_year = _embed_year(entity)
        tracks = [_embed_track(it.get("title") or it.get("name"),
                               it.get("subtitle") or it.get("artists"),
                               _embed_cover(it) or alb_cover,
                               it.get("duration"), _embed_year(it) or alb_year)
                  for it in tl[:max_tracks]]
    tracks = [t for t in tracks if t["title"]]
    if not tracks:
        return None
    return {"kind": kind, "title": title, "tracks": tracks[:max_tracks]}


# هدرهای مرورگرِ واقعی — open.spotify.com به درخواستِ غیرِمرورگری اغلب 403 می‌دهد.
_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _http_proxy(proxy: str | None) -> str | None:
    """پارامترِ `proxy=`ِ خودِ درخواست فقط http(s) را می‌فهمد (نه socks).

    socks از **کانکتور** می‌رود، نه از این‌جا — `_direct_connector` را ببین.
    """
    return proxy if proxy and proxy.startswith(("http://", "https://")) else None


_SOCKS_SCHEMES = ("socks5://", "socks5h://", "socks4://", "socks4a://")


def _proxy_kind(proxy: str | None) -> tuple[str, str | None]:
    """(نوع، آدرسِ نرمال‌شده) — `http` / `socks` / `""` برای هیچ‌کدام.

    `socks5h://` به `socks5://` بازنویسی می‌شود چون python_socks اسکیمِ `socks5h`
    را نمی‌شناسد (`ValueError: Invalid scheme component: socks5h`، سنجیده‌شده).
    این **تغییرِ رفتار نیست**: معنیِ `h` یعنی DNS سمتِ پروکسی، و در python_socks
    همان پیش‌فرضِ `socks5` هم هست (`if rdns is None: rdns = True`). ما هم صریح
    `rdns=True` می‌دهیم. توجه: این با curl فرق دارد، که در آن `socks5://` یعنی
    DNSِ محلی — پس توصیهٔ `socks5h` در مستنداتِ ما درست بوده و می‌ماند.
    """
    if not proxy:
        return "", None
    if proxy.startswith(("http://", "https://")):
        return "http", proxy
    if proxy.startswith(_SOCKS_SCHEMES):
        if proxy.startswith("socks5h://"):
            proxy = "socks5://" + proxy[len("socks5h://"):]
        return "socks", proxy
    return "", None                 # اسکیمِ ناشناخته — مثلِ قبل نادیده گرفته می‌شود


# ── موتورِ «فایلِ مستقیم» (لینکِ دانلودِ گیت‌هاب/APK/PDF/…) ──────────
# yt-dlp برای این‌ها ساخته نشده: روی یک لینکِ امضاشدهٔ blob با نامِ GUIDدار و کوئریِ
# بلند، سرِ نوشتنِ فایلِ متادیتا می‌شکند. هرچه «صفحه» نیست را خودمان استریم می‌کنیم.
class DirectTooLarge(Exception):
    """فایلِ مستقیم از سقفِ مجاز بزرگ‌تر است (قبل یا حینِ دانلود کشف می‌شود)."""

    def __init__(self, size: int, cap_bytes: int) -> None:
        super().__init__(f"direct file too large: {size} > {cap_bytes}")
        self.size, self.cap_bytes = size, cap_bytes


class AgeRestricted(Exception):
    """خودِ yt-dlp با `--match-filter` رد کرد: محتوا سنی است.

    این رد **بعد از استخراج و قبل از کشیدنِ بایت‌های رسانه** رخ می‌دهد، پس نه
    رفت‌وبرگشتِ اضافه‌ای دارد و نه یک مصرفِ اضافه از سهمیهٔ اکانتِ کوکی (گران‌ترین
    منبعِ ما). چرخشِ اکانت هم برایش بی‌معنی است — اکانتِ دیگر همین را می‌گیرد.
    """


_DIRECT_HOPS = 5           # سقفِ ریدایرکت (هر پرش دوباره SSRF-چک می‌شود)
_DIRECT_CHUNK = 256 * 1024
# نوعِ محتواهایی که «صفحه/فید» هستند نه فایل → همان مسیرِ قبلی (yt-dlp)
_PAGE_TYPES = ("text/html", "application/xhtml", "text/plain", "text/xml",
               "application/json", "application/xml", "application/rss+xml",
               "application/atom+xml", "application/javascript")
# مانیفستِ استریم: فایل نیست، فهرستِ قطعه است → حتماً yt-dlp
_MANIFEST_TYPES = ("application/vnd.apple.mpegurl", "application/x-mpegurl",
                   "application/dash+xml")
_DIRECT_EXTS = (
    ".apk", ".ipa", ".exe", ".msi", ".dmg", ".deb", ".rpm", ".appimage",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2", ".tgz",
    ".pdf", ".epub", ".mobi", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".srt", ".vtt", ".iso", ".img", ".bin", ".jar",
    ".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi",
    ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac", ".aac",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".heic",
)


def _url_ext(url: str) -> str:
    return os.path.splitext(unquote(urlparse(url).path or ""))[1].lower()


def has_file_ext(url: str) -> bool:
    """آیا خودِ مسیرِ URL به پسوندِ فایلِ شناخته‌شده ختم می‌شود؟ (چارهٔ HEADِ ناموفق)"""
    return _url_ext(url) in _DIRECT_EXTS


_CD_STAR_RE = re.compile(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", re.I)
_CD_PLAIN_RE = re.compile(r'filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)', re.I)


def _safe_name(name: str) -> str:
    """نامِ فایلِ امن: بدونِ مسیر، بدونِ کاراکترِ کنترلی، با سقفِ طول."""
    name = unquote((name or "").strip().strip('"').replace("\\", "/").split("/")[-1])
    name = re.sub(r'[\x00-\x1f<>:"|?*]+', "", name).strip(" .")
    if len(name) > 120:                       # پسوند را نگه دار، تنه را کوتاه کن
        stem, ext = os.path.splitext(name)
        name = stem[:120 - len(ext)] + ext
    return name


def direct_filename(url: str, disposition: str | None, content_type: str | None) -> str:
    """نامِ فایل: اول Content-Disposition، بعد مسیرِ URL، در آخر از نوعِ محتوا."""
    for rx in (_CD_STAR_RE, _CD_PLAIN_RE):
        m = rx.search(disposition or "")
        if m:
            got = _safe_name(next(g for g in m.groups() if g))
            if got:
                return got
    got = _safe_name(os.path.basename(unquote(urlparse(url).path or "")))
    if got and os.path.splitext(got)[1]:
        return got
    ct = (content_type or "").split(";")[0].strip().lower()
    ext = mimetypes.guess_extension(ct) if ct else None
    return (got or "download") + (ext or ".bin")


def is_direct_response(content_type: str | None, disposition: str | None, url: str) -> bool:
    """آیا این پاسخ یک **فایل** است (نه صفحهٔ HTML و نه مانیفستِ استریم)؟"""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _MANIFEST_TYPES:
        return False                                  # m3u8/mpd → کارِ yt-dlp
    if "attachment" in (disposition or "").lower():
        return True                                   # سرور خودش گفته «دانلود کن»
    if not ct:
        return has_file_ext(url)
    if ct.startswith(_PAGE_TYPES):
        return False
    return True                                       # application/* , video/* , image/* …


def _direct_headers(opts: dict) -> dict:
    h = dict(_BROWSER_HEADERS)
    h["Accept"] = "*/*"
    if opts.get("user_agent"):
        h["User-Agent"] = opts["user_agent"]
    return h


async def _follow(sess, method: str, url: str, proxy: str | None):
    """ریدایرکت را **دستی** دنبال کن تا هر پرش هم از فیلترِ SSRF رد شود.

    aiohttp با allow_redirects خودش پرش‌ها را نشان نمی‌دهد، و یک ریدایرکت به
    ۱۶۹٫۲۵۴٫۱۶۹٫۲۵۴ دقیقاً همان چیزی است که is_safe_url جلویش را می‌گیرد.

    این چکِ نحوی پیش‌فیلترِ ارزان است؛ حرفِ آخر با `_safe_resolver()` روی کانکتورِ
    سشن است که هنگامِ **اتصال** وتو می‌کند (پس نامِ دامنه و rebinding را هم می‌گیرد).
    """
    for _ in range(_DIRECT_HOPS):
        if not is_safe_url(url):
            raise RuntimeError(f"blocked url: {url[:120]}")
        resp = await sess.request(method, url, proxy=proxy, allow_redirects=False)
        if resp.status in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
            nxt = urljoin(str(resp.url), resp.headers["Location"])
            resp.release()
            url = nxt
            continue
        return resp
    raise RuntimeError("too many redirects")


async def probe_direct(url: str, opts: dict | None = None) -> dict | None:
    """HEADِ سبک: آیا این لینک فایلِ مستقیم است؟ → {is_file, size, filename, …}

    HEAD بدنه را مصرف نمی‌کند (مهم برای لینکِ امضاشدهٔ یک‌بارمصرف). اگر سرور HEAD
    را نپذیرفت، به پسوندِ خودِ URL برمی‌گردیم — بدترین حالتش رفتارِ امروز است.
    """
    import aiohttp
    opts = opts or {}
    try:
        timeout = aiohttp.ClientTimeout(total=15)   # HEAD است؛ بیش از این یعنی سرور نمی‌دهد
        async with aiohttp.ClientSession(headers=_direct_headers(opts), timeout=timeout,
                                         connector=_direct_connector(opts)) as sess:
            resp = await _follow(sess, "HEAD", url, _http_proxy(opts.get("proxy")))
            try:
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}")
                ct = resp.headers.get("Content-Type")
                cd = resp.headers.get("Content-Disposition")
                try:
                    size = int(resp.headers.get("Content-Length") or 0)
                except ValueError:
                    size = 0
                return {"is_file": is_direct_response(ct, cd, str(resp.url)),
                        "size": size, "content_type": ct,
                        "filename": direct_filename(str(resp.url), cd, ct),
                        "url": str(resp.url)}
            finally:
                resp.release()
    except Exception as exc:  # noqa: BLE001 — HEAD اختیاری است، شکستش کشنده نیست
        log.debug("direct probe failed for %s: %s", url[:90], exc)
        if not has_file_ext(url):
            return None                      # نمی‌دانیم → همان مسیرِ امروز (yt-dlp)
        return {"is_file": True, "size": 0, "content_type": None,
                "filename": direct_filename(url, None, None), "url": url}


async def download_direct(url: str, workdir: str, opts: dict | None = None,
                          max_bytes: int = 0, progress=None,
                          cancel=None) -> tuple[str, dict]:
    """فایل را مستقیم استریم کن → (مسیر, info). سقف در **دو** لایه اعمال می‌شود.

    Content-Length پیش از شروع بررسی می‌شود (رد کردنِ ارزان)، ولی چون سرور ممکن است
    اصلاً ندهد یا دروغ بگوید، شمارشِ واقعیِ بایت‌ها هم حین دانلود سقف را اعمال می‌کند
    و فایلِ نیمه‌کاره پاک می‌شود.
    """
    import aiohttp
    opts = opts or {}
    os.makedirs(workdir, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)
    async with aiohttp.ClientSession(headers=_direct_headers(opts), timeout=timeout,
                                     connector=_direct_connector(opts)) as sess:
        resp = await _follow(sess, "GET", url, _http_proxy(opts.get("proxy")))
        try:
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status} for {urlparse(url).hostname}")
            ct = resp.headers.get("Content-Type")
            cd = resp.headers.get("Content-Disposition")
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except ValueError:
                total = 0
            if max_bytes and total > max_bytes:
                raise DirectTooLarge(total, max_bytes)
            name = direct_filename(str(resp.url), cd, ct)
            out = os.path.join(workdir, name)
            got, last_pct = 0, -1
            with open(out, "wb") as fh:
                async for chunk in resp.content.iter_chunked(_DIRECT_CHUNK):
                    if cancel is not None and await cancel():
                        fh.close()
                        os.remove(out)
                        raise ProcessingCancelled()
                    got += len(chunk)
                    if max_bytes and got > max_bytes:
                        fh.close()
                        os.remove(out)
                        raise DirectTooLarge(got, max_bytes)
                    fh.write(chunk)
                    if progress is not None and total:
                        pct = min(99, int(got * 100 / total))
                        if pct != last_pct:      # فقط سرِ تغییرِ درصد، نه هر ۲۵۶ کیلوبایت
                            last_pct = pct
                            await progress(float(pct))
        finally:
            resp.release()
    from .filetypes import _document_kind
    # عمداً بدونِ title: کارت برای فایل باید نمای فنی بدهد، نه «کپشنِ پست»
    return out, {"kind": _document_kind((ct or "").split(";")[0].strip() or None, name),
                 "filesize": got, "direct": True}


async def _spotify_scrape(url: str, max_tracks: int, proxy: str | None = None) -> dict:
    """بدونِ credential: از صفحهٔ عمومیِ embedِ اسپاتیفای متادیتا را می‌خواند (بی‌لاگین).

    منبعِ اصلی: JSONِ __NEXT_DATA__ (نام/هنرمند/کاور/مدت). اگر ساختار عوض شده بود،
    fallback به oEmbedِ رسمی. اگر اسپاتیفای درخواست را بلاک کرد (403 روی IPِ دیتاسنتر)،
    خطای گویا می‌دهد تا کاربر بداند باید credential (APIِ رسمی) بگذارد.
    """
    import aiohttp
    kind, sid = spotify_id(url)
    px = _http_proxy(proxy)
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(headers=_BROWSER_HEADERS, timeout=timeout) as s:
        async with s.get(f"https://open.spotify.com/embed/{kind}/{sid}", proxy=px) as r:
            embed_status = r.status
            html = await r.text() if r.status == 200 else ""
    parsed = _parse_spotify_embed(html, kind, max_tracks)
    if parsed:
        blind = [t["title"] for t in parsed["tracks"] if reference_is_blind(t)]
        if blind:
            log.warning("spotify embed parsed but %d/%d track(s) have neither artist nor "
                        "duration — the matcher will rank on title alone: %s",
                        len(blind), len(parsed["tracks"]), ", ".join(blind[:3]))
        return parsed
    # fallback: oEmbedِ رسمی (عنوان + کاور).
    # **WARNING نه INFO، عمداً.** این مسیر فقط عنوان و کاور می‌دهد: نه هنرمند، نه
    # مدت — یعنی matcher کور می‌شود و نامزدهای هم‌نام امتیازِ یکسان می‌گیرند. تا
    # امروز این تنزل بی‌صدا بود و پارسر هفته‌ها مرده ماند بی‌آنکه چیزی خطا بدهد،
    # چون «مسیرِ جایگزین موفق شد». هر بار که این خط را دیدی یعنی اسکیمای اسپاتیفای
    # عوض شده و `_parse_spotify_embed` باید به‌روز شود.
    log.warning("spotify: __NEXT_DATA__ parse failed for %s — falling back to oEmbed "
                "(title only, no artist/duration). The embed schema has likely changed; "
                "run tools/spotify_embed_dump.py and update _parse_spotify_embed.", url)
    async with aiohttp.ClientSession(headers=_BROWSER_HEADERS, timeout=timeout) as s:
        async with s.get(f"https://open.spotify.com/oembed?url={url}", proxy=px) as r:
            if r.status != 200:
                raise RuntimeError(
                    f"spotify blocked the request (embed HTTP {embed_status}, oembed HTTP {r.status}) "
                    "— set Client ID/Secret in the panel")
            d = await r.json(content_type=None)
    if not d.get("title"):
        raise RuntimeError("spotify: could not read link metadata")
    return {"kind": kind, "title": d["title"],
            "tracks": [{"title": d["title"], "artist": "", "album": "", "year": "",
                        "cover_url": d.get("thumbnail_url"), "duration": None, "isrc": None}]}


async def spotify_resolve(url: str, client_id: str = "", secret: str = "", max_tracks: int = 20,
                          proxy: str | None = None) -> dict:
    """لینکِ اسپاتیفای → {kind, title, tracks[]}. با credential از APIِ رسمی (پایدار روی
    سرور)، وگرنه از صفحهٔ عمومیِ embed (که ممکن است IPِ دیتاسنتر را 403 کند)."""
    kind, _sid = spotify_id(url)
    if not kind:
        raise RuntimeError("unsupported spotify link")
    if client_id and secret:
        try:
            return await _spotify_api_resolve(url, client_id, secret, max_tracks)
        except Exception as exc:  # noqa: BLE001  — API خطا داد → برگرد به اسکرَیپِ عمومی
            log.info("spotify API failed (%s); falling back to public embed", str(exc)[:120])
    return await _spotify_scrape(url, max_tracks, proxy=proxy)


async def _fetch_cover(url: str | None, dest_dir: str) -> str | None:
    if not url:
        return None
    import aiohttp
    try:
        out = os.path.join(dest_dir, "cover.jpg")
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                if r.status != 200:
                    return None
                data = await r.read()
        with open(out, "wb") as fh:
            fh.write(data)
        return out
    except Exception:  # noqa: BLE001
        return None


# کلمه‌های نسخهٔ «نادرست» (لایو/کاور/ریمیکس/…) — اگر در عنوانِ خودِ ترکِ اسپاتیفای نباشند جریمه.
_BAD_KW = ("live", "cover", "remix", "sped up", "slowed", "reverb", "karaoke", "instrumental",
           "8d", "concert", "acoustic", "tribute", "parody", "reaction", "nightcore", "mashup",
           "extended mix", "radio edit", "performance", "unplugged", "session")

# کلمه‌های نویز که هنگامِ نرمال‌سازیِ عنوان حذف می‌شوند (تا تطبیقِ fuzzy واقعی‌تر شود).
_NOISE_RE = re.compile(
    r"\b(official|audio|video|lyric|lyrics|visualizer|hd|hq|mv|m/v|4k|"
    r"remaster(?:ed)?|full|album|track|version|feat|ft|featuring|prod)\b", re.I)
_PAREN_RE = re.compile(r"[\(\[\{][^)\]\}]*[\)\]\}]")     # (feat. X) [Official Video] {…}
_FEAT_RE = re.compile(r"\b(?:feat|ft|featuring|with)\.?\s.*$", re.I)  # دنبالهٔ «feat …»
# جداکنندهٔ نامِ هنرمندان. **مرزِ کلمه روی هر سه شاخهٔ feat/ft/featuring اجباری است**:
# بدونش `ft` هرجای نام بیفتد می‌بُرد و «Daft Punk» → ['Da','Punk'] می‌شد (و
# Taylor Swift / Kraftwerk / Deftones / Soft Cell / Shaft / …). `\b`ِ **جلو** تنها
# کافی نیست — «Feature Films» را می‌شکند — پس هر دو طرف بسته است؛ `\.?` بعد از
# `\b` می‌آید تا «feat.» همچنان جدا شود. سه شاخهٔ دیگر (`x`/`vs`/`and`) از اول
# `\b` داشتند، که همین ناهماهنگی باعث شد به چشم نیاید.
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|/|;|\bx\b|\bvs\b|\band\b|\bfeat\b\.?|\bft\b\.?|\bfeaturing\b)\s*", re.I)


def _cand_url(c: dict) -> str | None:
    v = c.get("id") or c.get("url") or ""
    if not v:
        return None
    return v if v.startswith("http") else f"https://www.youtube.com/watch?v={v}"


def _norm(s: str | None) -> str:
    """نرمال‌سازیِ عنوان/نام برای تطبیقِ fuzzy: NFKC + casefold + حذفِ براکت/نویز/نگارش.

    یونی‌کد را نگه می‌دارد (برای عنوان‌های فارسی)، فقط علائم را حذف می‌کند.
    """
    s = unicodedata.normalize("NFKC", s or "").casefold().strip()
    s = _PAREN_RE.sub(" ", s)
    s = _FEAT_RE.sub(" ", s)
    s = _NOISE_RE.sub(" ", s)
    s = re.sub(r"[^\w\s]", " ", s)  # \w یونی‌کدی است → حروفِ فارسی می‌مانند
    return " ".join(s.split())


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


def _cand_dur(cand: dict) -> int | None:
    d = cand.get("duration_seconds") or cand.get("duration")
    try:
        return int(d) if d else None
    except (TypeError, ValueError):
        return None


def _cand_artists(cand: dict) -> list[str]:
    """نامِ هنرمند(ها)ی نامزد: از YT Music لیستِ artists، از ytsearch کانالِ «X - Topic»/VEVO."""
    a = cand.get("artists")
    if isinstance(a, list) and a:
        return [x.get("name") if isinstance(x, dict) else str(x) for x in a if x]
    chan = cand.get("channel") or cand.get("uploader") or ""
    chan = re.sub(r"\s*-\s*topic\s*$", "", chan, flags=re.I)
    chan = re.sub(r"vevo\s*$", "", chan, flags=re.I).strip()
    return [chan] if chan else []


def _track_artists(track: dict) -> list[str]:
    return [x.strip() for x in _ARTIST_SPLIT_RE.split(track.get("artist") or "") if x.strip()]


def _name_match(track: dict, cand: dict) -> float:
    """تطبیقِ نامِ ترک با عنوانِ نامزد؛ هم «Title» (YT Music) هم «Artist - Title» (یوتیوب)."""
    ct = _norm(cand.get("title"))
    plain = _ratio(_norm(track.get("title")), ct)
    enriched = _ratio(_norm(f"{track.get('artist','')} {track.get('title','')}"), ct)
    return max(plain, enriched)


def _artist_match(track: dict, cand: dict) -> float | None:
    """میانگینِ وزن‌دارِ تطبیقِ هنرمندان (هنرمندِ اصلی مهم‌تر). None اگر شواهدی نبود."""
    ta = _track_artists(track)
    ca = _cand_artists(cand)
    if not ta:
        return None
    if not ca:  # نامزد نامِ هنرمند نداشت → دستِ‌کم حضورِ نامِ هنرمند در عنوان را بسنج
        ct = _norm(cand.get("title"))
        return max(_ratio(_norm(a), ct) for a in ta) if ct else None
    nc = [_norm(x) for x in ca if x]
    if not nc:
        return None
    scores = [max(_ratio(_norm(a), c) for c in nc) for a in ta]
    main = scores[0]
    rest = scores[1:]
    return main * 0.6 + (sum(rest) / len(rest)) * 0.4 if rest else main


def _album_match(track: dict, cand: dict) -> float | None:
    ta = track.get("album")
    ca = cand.get("album")
    if isinstance(ca, dict):
        ca = ca.get("name")
    if not ta or not ca:
        return None
    return _ratio(_norm(ta), _norm(str(ca)))


def _time_match(cand_dur: int | None, target_dur: int | None) -> float | None:
    """کاهشِ نماییِ اختلافِ مدت → ۰..۱۰۰ (روشِ spotDL). None اگر یکی نامعلوم بود."""
    if not cand_dur or not target_dur:
        return None
    return math.exp(-0.1 * abs(cand_dur - target_dur)) * 100.0


# امتیازِ مدت وقتی مدتِ نامزد را **نمی‌دانیم**. تا امروز مؤلفه از میانگینِ وزن‌دار
# حذف می‌شد و بقیه دوباره نرمال می‌شدند — یعنی «نمی‌دانم» دقیقاً مثلِ «مدتِ کاملاً
# درست» امتیاز می‌گرفت (هر دو ۱۰۶٫۰۰) و از نامزدی که ۳ ثانیه اختلاف داشت (۹۹٫۰۰)
# جلو می‌زد. عدد **۵۰ = وسطِ بازهٔ خروجیِ `_time_match`** است، یعنی نه پاداش نه
# جریمه؛ روی منحنیِ خودِ `_time_match` معادلِ **۶٫۹ ثانیه** اختلاف است
# (`-ln(0.5)/0.1`) — که خوش‌اقبالانه جایی می‌افتد بینِ «همان ضبط با مسترِ متفاوت»
# (۰..۳ ثانیه) و «نسخهٔ دیگر: لایو/اکستندد» (۲۰+ ثانیه). عمداً **جریمه نیست**:
# جریمه ادعای «نبودنِ مدت مشکوک است» را دارد که شاهدی برایش نداریم.
_TIME_UNKNOWN = 50.0


def _duration_reject(cand: dict, track: dict) -> bool:
    """گیتِ سختِ مدت: اختلافِ زیاد = نسخهٔ دیگر (لایو/اکستندد/رادیو-ادیت) → رد."""
    td = track.get("duration")
    cd = _cand_dur(cand)
    if not td or not cd:
        return False
    diff = abs(cd - td)
    return diff > 30 and diff / td > 0.15


def _match_score(cand: dict, track: dict) -> float:
    """امتیازِ ترکیبیِ ۰..۱۰۰+ (وزن‌دار) + بونوس/جریمه. بالاتر = تطبیقِ بهتر."""
    name = _name_match(track, cand)
    artist = _artist_match(track, cand)
    tscore = _time_match(_cand_dur(cand), track.get("duration"))
    if tscore is None and track.get("duration") and not _cand_dur(cand):
        # مدتِ ترک را داریم ولی مدتِ نامزد را نه → مقدارِ خنثی، نه حذفِ مؤلفه.
        #
        # ولی اگر مدتِ **خودِ ترک** نامعلوم باشد، عمداً به حذفِ مؤلفه برمی‌گردیم.
        # دلیلش رتبه‌بندی **نیست** — آن‌جا هر دو راه یکی‌اند، چون وقتی همهٔ
        # نامزدها یک وزن دارند تزریقِ ۵۰ تبدیلی یکنواست. دلیل **مقایسه‌پذیریِ
        # امتیاز بینِ ترک‌هاست**: `spotify_match_min` یک عددِ سراسری است که روی
        # همهٔ ترک‌ها اعمال می‌شود، پس اگر مقیاسِ امتیاز از ترکی به ترکِ دیگر
        # جابه‌جا شود، آستانه دیگر یک چیزِ ثابت را نمی‌سنجد و کالیبره‌کردنش
        # بی‌معنا می‌شود. تزریقِ ۵۰ وقتی هیچ اطلاعاتی نداریم دقیقاً همین کار را
        # می‌کند: امتیازها را به سمتِ ۵۰ جمع می‌کند و ترکِ بی‌مدت را روی مقیاسی
        # متفاوت از بقیه می‌برد.
        tscore = _TIME_UNKNOWN
    album = _album_match(track, cand)
    parts: list[tuple[float, float]] = [(name, 0.40)]
    if artist is not None:
        parts.append((artist, 0.25))
    if tscore is not None:
        parts.append((tscore, 0.27))
    if album is not None:
        parts.append((album, 0.08))
    tot = sum(w for _, w in parts)
    score = sum(v * w for v, w in parts) / tot if tot else 0.0
    # جریمهٔ کلمه‌های نسخهٔ نادرست (اگر خودِ ترک آن کلمه را ندارد)
    ct = _norm(cand.get("title"))
    tt = _norm(track.get("title"))
    for kw in _BAD_KW:
        if kw in ct and kw not in tt:
            score -= 12
    if cand.get("art_track"):   # نتیجهٔ فیلترِ «songs» = Art Trackِ رسمی
        score += 6
    # از سرچِ ISRC آمده = تطبیقِ قطعی. **در تولید هرگز شلیک نمی‌کند** و عمداً
    # نگه داشته شده: ISRC فقط از APIِ رسمیِ اسپاتیفای می‌آید و آن مسیر برای ما
    # بسته است (بولتِ «The Spotify Web API is closed to us» در §۷). صفر هزینه
    # دارد و اگر روزی کسی credential داشت کار می‌کند — ولی هیچ طراحی‌ای نباید
    # رویش حساب کند؛ امروز قوی‌ترین سیگنالِ باقی‌مانده `art_track`ِ +۶ است.
    if cand.get("isrc_hit"):
        score += 20
    return score


def _explicit_artist(cand: dict) -> bool:
    """نامزد فهرستِ صریحِ هنرمند دارد (YT Music) یا فقط از کانال حدس زده شده (ytsearch)؟"""
    return bool(isinstance(cand.get("artists"), list) and cand.get("artists"))


def _rank_candidates(candidates: list[dict], track: dict) -> list[tuple[float, dict]]:
    """نامزدها را می‌سنجد و از بهترین به بدترین مرتب می‌کند؛ گیت‌های سختِ نام/مدت/هنرمند.

    گیتِ هنرمند فقط وقتی نامزد فهرستِ صریحِ هنرمند دارد اعمال می‌شود (تا «خوانندهٔ
    اشتباه» رد شود)؛ برای نتایجِ ytsearch که هنرمند از کانال حدس زده شده، اعمال نمی‌شود.
    """
    scored: list[tuple[float, dict]] = []
    for c in candidates:
        if not _cand_url(c):
            continue
        if _name_match(track, c) < 45:   # عنوان آشکارا ربطی ندارد
            continue
        if _duration_reject(c, track):   # طولِ آشکارا متفاوت (لایو/اکستندد)
            continue
        am = _artist_match(track, c)
        if _explicit_artist(c) and am is not None and am < 40:  # صراحتاً خوانندهٔ دیگری
            continue
        scored.append((_match_score(c, track), c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


# `_pick_best_match` این‌جا بود و **هیچ فراخوانی نداشت** — `download_spotify` همان
# منطق را درجا نوشته. حذف شد تا دو نسخه از یک قاعده واگرا نشوند (همان دلیلِ
# حذفِ `zip` و `thumb` در فاز ۳).


async def _yt_search_candidates(query: str, opts: dict, limit: int = 6, timeout: float = 60) -> list[dict]:
    """جست‌وجوی مسطحِ یوتیوب → فهرستِ نامزدها (id/title/duration/channel) بدونِ دانلود."""
    ck = _writable_cookie(opts.get("cookies"))
    flags = ["--flat-playlist", "-J", "--no-warnings"]
    if opts.get("proxy"):
        flags += ["--proxy", opts["proxy"]]
    if opts.get("user_agent"):   # هویتِ سشن: همان UA که اکانت با آن شناخته می‌شود
        flags += ["--user-agent", opts["user_agent"]]
    if ck or opts.get("cookies"):
        flags += ["--cookies", ck or opts["cookies"]]
    cmd = [YTDLP, *flags, f"ytsearch{limit}:{query}"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return []
    finally:
        _cleanup_cookie(ck)
    if proc.returncode != 0:
        return []
    try:
        return (json.loads(out.decode("utf-8", "ignore") or "{}").get("entries")) or []
    except ValueError:
        return []


# ── YouTube Music (ytmusicapi): سرچِ کاتالوگِ «songs» = ضبطِ رسمی، نه لایو/کاور ──
_YTM_CACHE: dict[str, object] = {}


def _get_ytmusic(proxy: str | None):
    """کلاینتِ YTMusic (بی‌لاگین) با کشِ سطحِ‌پروسه؛ روی خطا از کش حذف می‌شود."""
    key = proxy or ""
    cli = _YTM_CACHE.get(key)
    if cli is None:
        from ytmusicapi import YTMusic  # importِ تنبل (وابستگیِ ورکرِ دانلود)
        px = {"http": proxy, "https": proxy} if proxy else None
        cli = YTMusic(proxies=px)
        _YTM_CACHE[key] = cli
    return cli


def _norm_ytm(item: dict, filt: str) -> dict:
    """آیتمِ ytmusicapi → نامزدِ یکدست (id/title/artists/album/duration/art_track)."""
    album = item.get("album")
    if isinstance(album, dict):
        album = album.get("name")
    return {
        "id": item.get("videoId"),
        "title": item.get("title"),
        "artists": [a.get("name") for a in (item.get("artists") or []) if isinstance(a, dict) and a.get("name")],
        "album": album,
        "duration_seconds": item.get("duration_seconds"),
        "art_track": filt == "songs",
        "source": "ytmusic",
    }


async def _ytmusic_search(query: str, filt: str, proxy: str | None,
                          limit: int = 6, timeout: float = 20) -> list[dict]:
    """سرچِ YouTube Music (sync → to_thread). خطا/تایم‌اوت → لیستِ خالی (fallback بالادست)."""
    def _run() -> list[dict]:
        try:
            return _get_ytmusic(proxy).search(query, filter=filt, limit=limit) or []
        except Exception as exc:  # noqa: BLE001  — بلاک/۴۲۹/ساختارِ عوض‌شده → کشِ کلاینت را تازه کن
            log.info("ytmusic search failed (%s): %s", filt, str(exc)[:120])
            _YTM_CACHE.pop(proxy or "", None)
            return []
    try:
        raw = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
    except asyncio.TimeoutError:
        return []
    out = [_norm_ytm(x, filt) for x in raw if isinstance(x, dict) and x.get("videoId")]
    return out


async def _gather_candidates(track: dict, opts: dict, source: str) -> list[dict]:
    """نامزدهای یک ترک: YT Music (ISRC→songs→videos)، و در صورتِ کم‌بودن + استخرِ ytsearch.

    استخرِ ytsearch همیشه وقتی YT Music کم/خالی بود اضافه می‌شود (نه فقط وقتی صفر است)
    تا امتیازده روی مجموعهٔ بزرگ‌تری انتخاب کند و هیچ‌وقت به «گرفتنِ خامِ نتیجهٔ اول»
    نیفتیم — که علتِ فرستادنِ آهنگ/خوانندهٔ اشتباه بود.
    """
    query = " ".join(p for p in (track.get("artist"), track.get("title")) if p).strip()
    proxy = opts.get("proxy")
    cands: list[dict] = []
    if source != "youtube":  # پیش‌فرض: YouTube Music
        # تلاشِ اول: تطبیقِ قطعی با ISRC (روشِ spotDL). **در تولید هرگز اجرا
        # نمی‌شود** — ISRC فقط از APIِ رسمی می‌آید و مسیرِ embed همیشه `None`
        # می‌دهد (`_embed_track`). نگه داشته شده چون هزینه‌اش صفر است؛ ببین
        # بولتِ «The Spotify Web API is closed to us» در §۷.
        isrc = track.get("isrc")
        if isrc:
            for h in await _ytmusic_search(isrc, "songs", proxy, limit=3):
                h["isrc_hit"] = True
                cands.append(h)
        cands += await _ytmusic_search(query, "songs", proxy)
        if len(cands) < 3:  # کاتالوگِ songs کم بود → ویدیوهای موزیک را هم بگیر
            cands += await _ytmusic_search(query, "videos", proxy)
    # اگر YT Music خالی/کم بود (یا source=youtube)، استخرِ ytsearch را هم ضمیمه کن
    if len(cands) < 3:
        cands += await _yt_search_candidates(query, opts)
    return cands


async def download_spotify(url: str, workdir: str, opts: dict,
                           progress=None, cancel=None) -> list[tuple[str, dict, str | None]]:
    """هر ترکِ اسپاتیفای را با تطبیق روی یوتیوب دانلود می‌کند → لیستِ (path, info, thumb).

    info['sp'] متادیتای اسپاتیفای (title/artist/album/year/cover_path) را حمل می‌کند تا
    tasks_download در صورتِ روشن‌بودنِ کلیدِ متادیتا، تگ/کاور را بازنویسی کند.
    کوکی/پروکسی/pot از opts همان مالِ یوتیوب است (دانلودِ واقعی از یوتیوب انجام می‌شود).
    """
    # credential اختیاری است: با آن از API (کامل‌تر)، بدونِ آن از صفحهٔ عمومیِ embed.
    cid = opts.get("spotify_client_id") or ""
    secret = opts.get("spotify_client_secret") or ""
    max_tracks = int(opts.get("spotify_max_tracks") or 20)
    resolved = await spotify_resolve(url, cid, secret, max_tracks, proxy=opts.get("proxy"))
    tracks = resolved["tracks"]
    if not tracks:
        raise RuntimeError("spotify: no tracks found")
    source = (opts.get("spotify_source") or "ytmusic").lower()
    try:
        min_score = float(opts.get("spotify_match_min") or 55)
    except (TypeError, ValueError):
        min_score = 55.0
    yt_fallback = opts.get("spotify_yt_fallback", True)
    n = len(tracks)
    results: list[tuple[str, dict, str | None]] = []
    last_err: Exception | None = None
    dropped = age_blocked = 0        # برای نام‌بردنِ علتِ درست وقتی چیزی نمی‌ماند
    for i, tr in enumerate(tracks):
        if cancel is not None and await cancel():
            raise ProcessingCancelled()
        tdir = os.path.join(workdir, f"t{i}")
        os.makedirs(tdir, exist_ok=True)
        query = " ".join(p for p in (tr.get("artist"), tr.get("title")) if p).strip()
        # نامزدها را از کاتالوگِ «songs»ی YouTube Music (+ استخرِ ytsearch) بگیر و با امتیازِ
        # fuzzyِ وزن‌دار (نام/هنرمند/آلبوم/مدت) رتبه بده؛ بهترینِ بالای آستانه را بردار.
        candidates = await _gather_candidates(tr, opts, source)
        ranked = _rank_candidates(candidates, tr)
        best = ranked[0][1] if ranked and ranked[0][0] >= min_score else None
        if best is None and yt_fallback and ranked:
            best = ranked[0][1]  # بهترینِ موجود (حتی زیرِ آستانه) — بهتر از گرفتنِ خامِ اول
        target = _cand_url(best) if best else None
        if not target:  # نه نامزدی رد شد نه چیزی برای fallback ماند
            if not yt_fallback:  # این ترک را رد کن، اشتباه نفرست
                last_err = RuntimeError(f"no confident match: {query}")
                dropped += 1
                continue
            target = f"ytsearch1:{query}"  # آخرین‌چاره (وقتی هیچ نامزدی نبود)

        async def _p(pct: float, _i=i) -> None:  # پیشرفتِ کلی روی همهٔ ترک‌ها
            if progress is not None:
                await progress((_i * 100 + pct) / n)

        try:
            path, yinfo, _thumb = await download_ytdlp(target, tdir, "audio", opts,
                                                       progress=_p, cancel=cancel)
        except ProcessingCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            # pot-provider می‌تواند yt-dlp را بیندازد → یک‌بار بدونِ pot؛ وگرنه این ترک را رد کن
            if opts.get("pot_provider") and not isinstance(exc, AgeRestricted):
                try:
                    path, yinfo, _thumb = await download_ytdlp(
                        target, tdir, "audio", {**opts, "pot_provider": None}, progress=_p, cancel=cancel)
                except ProcessingCancelled:
                    raise
                except Exception as exc2:  # noqa: BLE001
                    last_err = exc2
                    dropped += 1
                    age_blocked += isinstance(exc2, AgeRestricted)
                    continue
            else:
                dropped += 1
                age_blocked += isinstance(exc, AgeRestricted)
                continue
        cover_path = await _fetch_cover(tr.get("cover_url"), tdir)
        info = {"duration": tr.get("duration") or yinfo.get("duration"),
                "sp": {**tr, "cover_path": cover_path}}
        results.append((path, info, None))
    if not results:
        # اگر **همهٔ** ترک‌های افتاده را گیتِ سنی انداخته، علت را درست نام ببر.
        # `run_download` این استثنا را به پیامِ «محتوای غیرمجاز» نگاشت می‌کند؛
        # بدونِ این، کاربر «no YouTube match» می‌گرفت که علت را اشتباه می‌گوید.
        # شرط عمداً «همهٔ افتاده‌ها» است نه «همهٔ ترک‌ها»: اگر یکی سنی بود و یکی
        # نامزد نداشت، پیامِ عمومی همچنان درست‌تر است.
        if age_blocked and age_blocked == dropped:
            raise AgeRestricted(f"spotify: all {age_blocked} track(s) are age-restricted")
        # علتِ واقعیِ شکستِ دانلودِ یوتیوب را بالا بده (bot-check/pot/…) تا تشخیص ممکن شود
        raise RuntimeError("spotify: no YouTube match — "
                           + (str(last_err)[:220] if last_err else "search returned nothing"))
    return results


_HASHTAG_RE = re.compile(r"#[^\s#]+")


def clean_caption(text: str | None) -> str | None:
    """کپشنِ پست را تمیز می‌کند: حذفِ هشتگ‌ها، جمعِ فاصله/خطوطِ اضافی، سقفِ ۱۰۲۴ کاراکترِ تلگرام."""
    text = _HASHTAG_RE.sub("", text or "")
    text = "\n".join(ln.rstrip() for ln in text.splitlines())
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return None
    if len(text) > 1024:
        text = text[:1023].rstrip() + "…"
    return text


def _gallery_caption(workdir: str) -> str | None:
    """کپشنِ پست را از سایدکارِ متادیتای gallery-dl می‌خواند (فیلدِ description)."""
    for root, _d, names in os.walk(workdir):
        for n in sorted(names):
            if not n.endswith(".json"):
                continue
            try:
                with open(os.path.join(root, n), encoding="utf-8") as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            for key in ("description", "caption", "content", "title"):
                val = meta.get(key)
                if isinstance(val, str) and val.strip():
                    return clean_caption(val)
    return None


async def download_gallerydl(url: str, workdir: str, opts: dict,
                             progress=None, cancel=None) -> tuple[list[str], str | None]:
    """دانلودِ گالری/کاروسل با gallery-dl → (فهرستِ فایل‌ها, کپشنِ پست بدونِ هشتگ).

    خروجی در زیرشاخهٔ اختصاصیِ `gl/` نوشته و **فقط از همان‌جا** جمع می‌شود. چرا: روی
    نودِ دانلود، `cookies.materialize()` کوکی را داخلِ `workdir/ck/` می‌نویسد و پیمایشِ
    کلِ workdir آن را به‌عنوان یک فایلِ دانلودشده برمی‌داشت → یک ریلزِ **تکی** دو فایل
    به‌نظر می‌رسید و به شاخهٔ «آلبوم» می‌رفت (بدونِ کارت و بدونِ کپشنِ پست).
    """
    # کوکی را در temp (بیرونِ workdir) کپی کن: هم /cookies فقط‌خواندنی است، هم اگر داخلِ
    # workdir بگذاریم، جمع‌کنندهٔ فایل‌ها اشتباهی آن را به‌عنوان رسانه برمی‌داشت.
    ck = _writable_cookie(opts.get("cookies"))
    outdir = os.path.join(workdir, "gl")
    os.makedirs(outdir, exist_ok=True)
    cmd = [GALLERY_DL, "-D", outdir, "--write-metadata"]  # سایدکارِ .json برای کپشن
    if opts.get("proxy"):
        cmd += ["--proxy", opts["proxy"]]
    if opts.get("user_agent"):   # هویتِ سشن: UAِ ثابتِ همان اکانت
        cmd += ["--user-agent", opts["user_agent"]]
    cookie_arg = ck or opts.get("cookies")
    if cookie_arg:
        cmd += ["--cookies", cookie_arg]
    cmd += [url]
    try:
        await _run_dl(cmd, progress=progress, cancel=cancel, timeout=opts.get("timeout", 1800))
    finally:
        _cleanup_cookie(ck)
    files = []
    for root, _d, names in os.walk(outdir):
        for n in names:
            if not n.endswith((".json", ".part")):  # .json = سایدکارِ متادیتا (رسانه نیست)
                files.append(os.path.join(root, n))
    if not files:
        raise RuntimeError("gallery download produced no files")
    return sorted(files), _gallery_caption(outdir)


# ── نسخهٔ موتورها (تشخیصِ «سشن مرده» در برابر «موتور عقب افتاده») ──
# وقتی اینستاگرام JSONDecodeError می‌دهد، دو علتِ کاملاً متفاوت ممکن است: سشن
# دیگر معتبر نیست، یا gallery-dl با تغییرِ سایت عقب افتاده. پنل روی مستر است و
# gallery-dl ندارد، پس خودِ ورکرِ دانلود نسخه‌ها را گزارش می‌کند.
async def engine_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, cmd in (("gallery-dl", [GALLERY_DL, "--version"]),
                      ("yt-dlp", [YTDLP, "--version"])):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            out[name] = (raw or b"").decode(errors="replace").strip().splitlines()[0][:40]
        except Exception as exc:  # noqa: BLE001 — تشخیص است، نه مسیرِ حیاتی
            log.debug("version probe failed for %s: %s", name, exc)
            out[name] = ""
    return out
