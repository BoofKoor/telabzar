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
# پلتفرم‌های شناخته‌شده (برای متریکِ per-host؛ «other» شناخته‌شده نیست).
KNOWN_PLATFORMS = tuple(k for k in PLATFORM_LABELS if k != "other")


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


async def download_gallerydl(url: str, workdir: str, opts: dict,
                             progress=None, cancel=None) -> list[str]:
    """دانلودِ گالری/کاروسل با gallery-dl → فهرستِ فایل‌ها."""
    cmd = [GALLERY_DL, "-D", workdir]
    if opts.get("proxy"):
        cmd += ["--proxy", opts["proxy"]]
    if opts.get("cookies"):
        cmd += ["--cookies", opts["cookies"]]
    cmd += [url]
    await _run_dl(cmd, progress=progress, cancel=cancel, timeout=opts.get("timeout", 1800))
    files = []
    for root, _d, names in os.walk(workdir):
        for n in names:
            if not n.endswith((".info.json", ".part")):
                files.append(os.path.join(root, n))
    if not files:
        raise RuntimeError("gallery download produced no files")
    return sorted(files)
