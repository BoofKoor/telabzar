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
import ipaddress
import json
import os
import re
from urllib.parse import urlparse

from .exceptions import ProcessingCancelled

YTDLP = "yt-dlp"
GALLERY_DL = "gallery-dl"

_URL_RE = re.compile(r"https?://[^\s<>()]+", re.I)
# همهٔ پسوندهای رسانه‌ای (fallbackِ یافتنِ خروجی وقتی پسوندِ موردِانتظار پیدا نشد).
_MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v",
               ".mp3", ".m4a", ".opus", ".ogg", ".oga", ".wav", ".flac", ".aac")
_GALLERY_PLATFORMS = {"instagram", "pinterest"}
# پلتفرم‌های صوتیِ تک‌استریم: منوی کیفیت بی‌معنی است → همیشه quick-grab.
AUDIO_PLATFORMS = {"soundcloud", "bandcamp"}
# میزبان‌های داخلی که هرگز نباید دانلود شوند (دفاعِ پایهٔ SSRF)
_BLOCK_HOSTS = {"localhost", "metadata.google.internal", "169.254.169.254"}

# برچسبِ فارسیِ پلتفرم‌ها — منبعِ واحد (پنل، متریک، پیام‌ها از این می‌خوانند).
PLATFORM_LABELS = {
    "youtube": "یوتیوب", "instagram": "اینستاگرام", "twitter": "X / توییتر",
    "tiktok": "تیک‌تاک", "pinterest": "پینترست", "soundcloud": "ساندکلاود",
    "aparat": "آپارات", "vimeo": "ویمئو", "twitch": "توییچ",
    "dailymotion": "دیلی‌موشن", "bandcamp": "بندکمپ", "reddit": "ردیت",
    "streamable": "استریمبل", "other": "عمومی / سایر",
}
# برچسبِ انگلیسیِ پلتفرم‌ها (برای پیامِ کاربرِ en).
PLATFORM_LABELS_EN = {
    "youtube": "YouTube", "instagram": "Instagram", "twitter": "X / Twitter",
    "tiktok": "TikTok", "pinterest": "Pinterest", "soundcloud": "SoundCloud",
    "aparat": "Aparat", "vimeo": "Vimeo", "twitch": "Twitch",
    "dailymotion": "Dailymotion", "bandcamp": "Bandcamp", "reddit": "Reddit",
    "streamable": "Streamable", "other": "the site",
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
    return "other"


def engine_for(url: str, platform: str | None = None) -> str:
    return "gallerydl" if (platform or platform_of(url)) in _GALLERY_PLATFORMS else "ytdlp"


def is_safe_url(url: str) -> bool:
    """دفاعِ پایهٔ SSRF: فقط http(s)، ردِ لوپ‌بک/خصوصی/داخلی."""
    try:
        p = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    if host in _BLOCK_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        pass  # نامِ میزبان است نه IP — مجاز
    return True


# ── پرچم‌های مشترکِ yt-dlp (proxy / cookies / pot-provider) ─────
def _common_flags(opts: dict) -> list[str]:
    flags = ["--no-warnings", "--no-playlist"]
    if opts.get("proxy"):
        flags += ["--proxy", opts["proxy"]]
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


def normalize_probe(data: dict) -> dict:
    """خروجیِ ‎-J را به {title, duration, kind, options[]} تمیز می‌کند."""
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
    }


async def probe(url: str, opts: dict, timeout: float = 120) -> dict:
    """اطلاعاتِ رسانه بدونِ دانلود (‎-J) → دیکشنریِ نرمال‌شده."""
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
        detail = " ".join((err or b"").decode("utf-8", "ignore").split())[:200]
        raise RuntimeError(f"probe failed: {detail}")
    return normalize_probe(json.loads(out.decode("utf-8", "ignore") or "{}"))


def _selector_to_format(sel: str) -> str:
    if sel in ("best", ""):
        return "bv*+ba/b"
    if sel == "audio":
        return "ba/b"
    if sel.isdigit():
        return f"bv*[height<={sel}]+ba/b[height<={sel}]/b"
    return "bv*+ba/b"


async def _run_dl(cmd: list[str], progress=None, cancel=None, timeout: float = 3000) -> None:
    """اجرای yt-dlp/gallery-dl با خواندنِ درصد از stdout و چکِ لغو."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    err_chunks: list[bytes] = []
    cancelled = False

    async def _drain_err() -> None:
        async for raw in proc.stderr:  # type: ignore[union-attr]
            err_chunks.append(raw)

    async def _read_out() -> None:
        nonlocal cancelled
        async for raw in proc.stdout:  # type: ignore[union-attr]
            line = raw.decode("utf-8", "ignore").strip()
            if line.startswith("dl:") and progress is not None:
                m = re.search(r"([\d.]+)%", line)
                if m:
                    try:
                        await progress(float(m.group(1)))
                    except Exception:  # noqa: BLE001
                        pass
            if cancel is not None:
                try:
                    if await cancel():
                        cancelled = True
                        proc.kill()
                        return
                except Exception:  # noqa: BLE001
                    pass

    try:
        await asyncio.wait_for(asyncio.gather(_read_out(), _drain_err()), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("download timed out") from None
    await proc.wait()
    if cancelled:
        raise ProcessingCancelled()
    if proc.returncode != 0:
        lines = [ln for ln in b"".join(err_chunks).decode("utf-8", "ignore").splitlines() if ln.strip()]
        raise RuntimeError("download failed: " + (" | ".join(lines[-2:]) or "unknown"))


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
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height:format=duration", "-of", "json", path]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        data = json.loads(out or b"{}")
    except Exception:  # noqa: BLE001
        return {}
    st = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    res: dict = {}
    if st.get("width"):
        res["width"] = int(st["width"])
    if st.get("height"):
        res["height"] = int(st["height"])
    try:
        if fmt.get("duration"):
            res["duration"] = int(float(fmt["duration"]))
    except (TypeError, ValueError):
        pass
    return res


async def download_ytdlp(url: str, workdir: str, selector: str, opts: dict,
                         progress=None, cancel=None) -> tuple[str, dict, str | None]:
    """دانلود با yt-dlp → (مسیرِ فایل, info dict, مسیرِ تامبنیل). info.json را می‌خوانَد."""
    outtmpl = os.path.join(workdir, "%(title).80B [%(id)s].%(ext)s")
    audio_only = selector == "audio"
    cmd = [YTDLP, "--newline", "--progress-template", "dl:%(progress._percent_str)s",
           "--concurrent-fragments", "4",  # دانلودِ موازیِ قطعه‌های DASH → سریع‌تر
           "--write-info-json", "--write-thumbnail", "--convert-thumbnails", "jpg",
           "-o", outtmpl, "-f", _selector_to_format(selector)]
    if audio_only:
        cmd += ["-x", "--audio-format", "mp3"]
    else:
        cmd += ["--merge-output-format", "mp4"]
    cmd += ["--embed-metadata"]  # عنوان/هنرمند و… داخلِ فایل
    if opts.get("sponsorblock"):  # حذفِ اسپانسر/اینترو (یوتیوب)
        cmd += ["--sponsorblock-remove", opts["sponsorblock"]]
    if opts.get("subs") and not audio_only:  # زیرنویسِ خودکار (en+fa)
        cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*,fa.*", "--embed-subs"]
    if opts.get("max_mb"):
        cmd += ["--max-filesize", f"{int(opts['max_mb'])}M"]
    cmd += [*_common_flags(opts), url]
    await _run_dl(cmd, progress=progress, cancel=cancel, timeout=opts.get("timeout", 3000))

    # فایلِ رسانه را با پسوندِ رسانه پیدا کن (نه تامبنیلِ jpg)
    media_exts = ((".mp3", ".m4a", ".opus", ".ogg", ".wav")
                  if audio_only else (".mp4", ".mkv", ".webm", ".mov"))
    path = _newest(workdir, media_exts)
    if not path:
        # منبعِ فقط-صوت (مثلِ ساندکلاود) حتی با selectorِ ویدیویی فایلِ صوتی می‌دهد؛
        # هر رسانه‌ای که تولید شده را بردار تا «produced no file» بی‌خود رخ ندهد.
        path = _newest(workdir, _MEDIA_EXTS)
    if not path:
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
    # متادیتای ناقصِ ویدیو را با ffprobe کامل کن (کارت + منوی کاهشِ حجم دقیق شود)
    if not audio_only and not (info.get("width") and info.get("height") and info.get("duration")):
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
    return out, {}, None


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
    """دانلودِ گالری/کاروسل با gallery-dl → (فهرستِ فایل‌ها, کپشنِ پست بدونِ هشتگ)."""
    cmd = [GALLERY_DL, "-D", workdir, "--write-metadata"]  # سایدکارِ .json برای کپشن
    if opts.get("proxy"):
        cmd += ["--proxy", opts["proxy"]]
    if opts.get("cookies"):
        cmd += ["--cookies", opts["cookies"]]
    cmd += [url]
    await _run_dl(cmd, progress=progress, cancel=cancel, timeout=opts.get("timeout", 1800))
    files = []
    for root, _d, names in os.walk(workdir):
        for n in names:
            if not n.endswith((".json", ".part")):  # .json = سایدکارِ متادیتا (رسانه نیست)
                files.append(os.path.join(root, n))
    if not files:
        raise RuntimeError("gallery download produced no files")
    return sorted(files), _gallery_caption(workdir)
