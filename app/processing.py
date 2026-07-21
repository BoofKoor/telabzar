"""پردازشِ فایل‌ها با ffmpeg و Pillow (اجرا در ورکر)."""
from __future__ import annotations

import asyncio
import json
import os
import zipfile

from PIL import Image, ImageDraw, ImageFont

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
SEVENZ = "7z"

# فونت‌های کاندید برای واترمارکِ متنی (اولی فارسی/عربی، آخری فالبکِ لاتین)
_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/fonts-hosny-amiri/Amiri-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

# موقعیتِ واترمارک → عبارتِ overlay (حاشیهٔ ۲۴ پیکسل)
_WM_POS = {
    "tl": "24:24",
    "tr": "main_w-overlay_w-24:24",
    "bl": "24:main_h-overlay_h-24",
    "br": "main_w-overlay_w-24:main_h-overlay_h-24",
}


class ProcessingCancelled(Exception):
    """کاربر عملیات را وسطِ کار لغو کرد."""


async def _run(cmd: list[str], timeout: float = 1800, progress=None, duration: float | None = None,
               cancel=None) -> None:
    """اجرای ffmpeg. اگر progress و duration بدهی، از ‎-progress درصد را می‌خواند
    و progress(percent) را صدا می‌زند. اگر cancel بدهی، هر چند ثانیه چکش می‌کند و
    در صورتِ True فرایند را می‌کُشد (ProcessingCancelled)."""
    use_prog = progress is not None and bool(duration)
    if use_prog:
        cmd = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE if use_prog else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    if use_prog:
        err_chunks: list[bytes] = []
        cancelled = False

        async def _drain_stderr() -> None:
            async for raw in proc.stderr:  # type: ignore[union-attr]
                err_chunks.append(raw)

        async def _read_progress() -> None:
            nonlocal cancelled
            async for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.decode("utf-8", "ignore").strip()
                if line.startswith("out_time_us="):
                    val = line[12:]
                    if val.isdigit():
                        pct = min(99.0, int(val) / 1e6 / duration * 100)
                        try:
                            await progress(pct)
                        except Exception:  # noqa: BLE001
                            pass
                if cancel is not None and line.startswith("progress="):
                    try:
                        if await cancel():
                            cancelled = True
                            proc.kill()
                            return
                    except Exception:  # noqa: BLE001
                        pass

        try:
            await asyncio.wait_for(asyncio.gather(_read_progress(), _drain_stderr()), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError("processing timed out") from None
        await proc.wait()
        if cancelled:
            raise ProcessingCancelled()
        err = b"".join(err_chunks)
    else:
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError("processing timed out") from None

    if proc.returncode != 0:
        lines = [ln for ln in (err or b"").decode("utf-8", "ignore").splitlines() if ln.strip()]
        detail = " | ".join(lines[-3:]) if lines else "no stderr"
        # کدِ منفی = kill با سیگنال (‎-9 ≈ OOM killer — کمبودِ RAM)
        raise RuntimeError(f"ffmpeg failed (code {proc.returncode}): " + detail)


# ── تصویر (Pillow) ─────────────────────────────────────────────
def _flatten_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def _compress_image_sync(inp: str, out: str) -> None:
    _flatten_rgb(Image.open(inp)).save(out, "JPEG", quality=70, optimize=True)


def _convert_image_sync(inp: str, out: str, fmt: str) -> None:
    img = Image.open(inp)
    fmt = fmt.lower()
    if fmt in ("jpg", "jpeg"):
        _flatten_rgb(img).save(out, "JPEG", quality=90, optimize=True)
    elif fmt == "png":
        img.save(out, "PNG", optimize=True)
    elif fmt == "webp":
        img.save(out, "WEBP", quality=90)
    else:
        img.save(out)


async def compress_image(inp: str, out: str) -> None:
    await asyncio.to_thread(_compress_image_sync, inp, out)


async def convert_image(inp: str, out: str, fmt: str) -> None:
    await asyncio.to_thread(_convert_image_sync, inp, out, fmt)


# ── صوت (ffmpeg) ───────────────────────────────────────────────
# نکته: '-vn' کاورآرتِ جاسازی‌شده در MP3 را دراپ می‌کند تا تبدیل به
# ogg/m4a شکست نخورد.
_AUDIO_CODEC: dict[str, list[str]] = {
    "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
}


async def compress_audio(inp: str, out: str, progress=None, duration=None, cancel=None) -> None:
    await _run([FFMPEG, "-y", "-i", inp, "-vn", "-c:a", "libmp3lame", "-b:a", "128k", out],
               progress=progress, duration=duration, cancel=cancel)


async def convert_audio(inp: str, out: str, fmt: str, progress=None, duration=None, cancel=None) -> None:
    codec = _AUDIO_CODEC.get(fmt.lower(), [])
    await _run([FFMPEG, "-y", "-i", inp, "-vn", *codec, out], progress=progress, duration=duration, cancel=cancel)


async def extract_audio(inp: str, out: str, fmt: str = "mp3", progress=None, duration=None, cancel=None) -> None:
    """صدا را از ویدیو جدا می‌کند (بدونِ تصویر)."""
    codec = _AUDIO_CODEC.get(fmt.lower(), ["-c:a", "libmp3lame", "-b:a", "192k"])
    await _run([FFMPEG, "-y", "-i", inp, "-vn", *codec, out],
               progress=progress, duration=duration, cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("no audio track extracted")


# ── ویدیو (ffmpeg) ─────────────────────────────────────────────
async def compress_video(inp: str, out: str, height: int | None = None, kbps: int | None = None,
                         progress=None, duration=None, cancel=None) -> None:
    """فشرده‌سازی؛ اگر height بدهی به آن رزولوشن اسکیل می‌کند و اگر kbps بدهی
    نرخِ هدف را می‌گیرد (برای تخمینِ حجمِ دقیق‌تر)، وگرنه CRF."""
    args = [FFMPEG, "-y", "-i", inp]
    if height:
        # عرض را زوج نگه‌دار (نیازِ libx264)
        args += ["-vf", f"scale=-2:{height}"]
    if kbps:
        args += ["-c:v", "libx264", "-b:v", f"{kbps}k",
                 "-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 2}k", "-preset", "veryfast"]
    else:
        args += ["-c:v", "libx264", "-crf", "30", "-preset", "veryfast"]
    args += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
    await _run(args, progress=progress, duration=duration, cancel=cancel)


async def convert_video(inp: str, out: str, fmt: str, progress=None, duration=None, cancel=None) -> None:
    args = [FFMPEG, "-y", "-i", inp]
    if fmt.lower() == "mp4":
        args += [
            "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
            "-c:a", "aac", "-movflags", "+faststart",
        ]
    args.append(out)
    await _run(args, progress=progress, duration=duration, cancel=cancel)


# ── ویدیو → GIF (کم‌مصرف؛ پالت با max_colors محدود تا OOM/‏code -9 ندهد) ─
# نکته: '-t' قبل از '-i' فقط چند ثانیهٔ اول را decode می‌کند (حافظهٔ کمتر)؛
# max_colors + stats_mode=diff مصرفِ palettegen را پایین می‌آورد.
async def video_to_gif(inp: str, out: str, seconds: int = 6, width: int = 360, fps: int = 10,
                       progress=None, duration=None, cancel=None) -> None:
    vf = (f"fps={fps},scale={width}:-2:flags=lanczos,split[s0][s1];"
          f"[s0]palettegen=max_colors=64:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5")
    await _run([FFMPEG, "-y", "-t", str(seconds), "-i", inp, "-vf", vf, "-loop", "0", out],
               progress=progress, duration=duration, cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("GIF generation produced no output")


# ── تامبنیلِ ویدیو (فریمِ نماینده با فیلترِ thumbnail) ──────────
async def video_thumbnail(inp: str, out: str) -> None:
    await _run([
        FFMPEG, "-y", "-i", inp,
        "-vf", "thumbnail,scale=640:-1", "-frames:v", "1", "-q:v", "3", out,
    ])
    if not os.path.exists(out):
        raise RuntimeError("thumbnail extraction produced no output")


# ── واترمارک / برش / بی‌صدا / اسکرین‌شاتِ ویدیو ─────────────────
def _font_path() -> str | None:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _render_text_watermark_sync(text: str, out_png: str, video_h: int) -> None:
    """متن (فارسی/انگلیسی) را به PNGِ شفاف رِندر می‌کند — با شکل‌دهیِ درستِ فارسی."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        shaped = get_display(arabic_reshaper.reshape(text))
    except Exception:  # noqa: BLE001  — اگر کتابخانه‌ها نبودند، خامِ متن
        shaped = text
    size = max(18, int((video_h or 480) / 14))
    fp = _font_path()
    font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
    tmp = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    box = tmp.textbbox((0, 0), shaped, font=font)
    pad = max(8, size // 3)
    w, h = box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    ox, oy = pad - box[0], pad - box[1]
    dr.text((ox + 2, oy + 2), shaped, font=font, fill=(0, 0, 0, 150))   # سایه
    dr.text((ox, oy), shaped, font=font, fill=(255, 255, 255, 235))     # متن
    im.save(out_png)


async def render_text_watermark(text: str, out_png: str, video_h: int) -> None:
    await asyncio.to_thread(_render_text_watermark_sync, text, out_png, video_h)


async def watermark_video(inp: str, out: str, wm: str, position: str, scale_w: int | None = None,
                          progress=None, duration=None, cancel=None) -> None:
    pos = _WM_POS.get(position, _WM_POS["br"])
    if scale_w:  # لوگو را نسبت به عرضِ ویدیو کوچک کن
        fc = f"[1:v]scale={scale_w}:-1[wm];[0:v][wm]overlay={pos}"
    else:        # PNGِ متنی از قبل اندازه‌شده است
        fc = f"[0:v][1:v]overlay={pos}"
    await _run([
        FFMPEG, "-y", "-i", inp, "-i", wm, "-filter_complex", fc,
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-c:a", "copy", "-movflags", "+faststart", out,
    ], progress=progress, duration=duration, cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("watermark produced no output")


async def mute_video(inp: str, out: str) -> None:
    """صدا را حذف می‌کند (بدونِ رمزگذاریِ دوباره)."""
    await _run([FFMPEG, "-y", "-i", inp, "-c", "copy", "-an", "-movflags", "+faststart", out])
    if not os.path.exists(out):
        raise RuntimeError("mute produced no output")


async def trim_video(inp: str, out: str, start: float, end: float,
                     progress=None, cancel=None) -> None:
    """برشِ دقیق [start, end] با رمزگذاریِ دوباره."""
    await _run([
        FFMPEG, "-y", "-i", inp, "-ss", f"{start}", "-to", f"{end}",
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-c:a", "aac", "-movflags", "+faststart", out,
    ], progress=progress, duration=max(0.1, end - start), cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("trim produced no output")


async def screenshot_video(inp: str, out: str, ts: float) -> None:
    """فریمِ لحظهٔ ts را به‌صورتِ عکس می‌گیرد."""
    await _run([FFMPEG, "-y", "-ss", f"{ts}", "-i", inp, "-frames:v", "1", "-q:v", "2", out], timeout=120)
    if not os.path.exists(out):
        raise RuntimeError("screenshot produced no output")


# ── متادیتای صوت (ffprobe؛ بدونِ وابستگیِ جدید) ─────────────────
async def audio_metadata(inp: str) -> dict:
    """{'format': {...}, 'tags': {lower: value}, 'stream': {...}} از ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        FFPROBE, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", inp,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("cannot read metadata")
    data = json.loads(out.decode("utf-8", "ignore") or "{}")
    fmt = data.get("format", {}) or {}
    tags = {str(k).lower(): v for k, v in (fmt.get("tags") or {}).items()}
    stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        {},
    )
    return {"format": fmt, "tags": tags, "stream": stream}


# ── زیپ ────────────────────────────────────────────────────────
def _zip_sync(inp: str, out: str, arcname: str) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(inp, arcname=arcname)


async def make_zip(inp: str, out: str, arcname: str) -> None:
    await asyncio.to_thread(_zip_sync, inp, out, arcname)


def _zip_many_sync(members: list[tuple[str, str]], out: str) -> None:
    used: set[str] = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arcname in members:
            name = os.path.basename(arcname or path) or "file"
            base, ext = os.path.splitext(name)
            i = 1
            while name in used:  # جلوگیری از هم‌نامیِ اعضا
                name = f"{base}({i}){ext}"
                i += 1
            used.add(name)
            zf.write(path, arcname=name)


async def make_zip_many(members: list[tuple[str, str]], out: str) -> None:
    """members: [(path, arcname), …] → یک آرشیوِ zip."""
    await asyncio.to_thread(_zip_many_sync, members, out)


# ── نوشتنِ متادیتای صوت + کاور (ffmpeg؛ بدونِ رمزگذاریِ دوباره) ──
async def write_audio_metadata(inp: str, out: str, tags: dict[str, str],
                               cover_path: str | None = None) -> None:
    args = [FFMPEG, "-y", "-i", inp]
    if cover_path:
        # صوت از ورودیِ ۰، کاورِ جدید از ورودیِ ۱ (کاورِ قبلی دراپ می‌شود)
        args += [
            "-i", cover_path, "-map", "0:a", "-map", "1:0", "-c", "copy",
            "-id3v2_version", "3", "-disposition:v", "attached_pic",
            "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)",
        ]
    else:
        args += ["-map", "0", "-c", "copy"]
    for key, val in tags.items():
        args += ["-metadata", f"{key}={val}"]
    args.append(out)
    await _run(args)
    if not os.path.exists(out):
        raise RuntimeError("metadata write produced no output")


# ── تبدیلِ سند با LibreOffice headless (به PDF / DOCX / …) ──────
# نکته: soffice حتی وقتی فایلِ ورودی را نمی‌تواند باز کند با کدِ 0 خارج
# می‌شود؛ پس به‌جای اتکا به returncode، وجودِ خروجی را بررسی و در صورتِ
# نبودِ آن، stderr را در پیامِ خطا می‌آوریم تا اشکال‌زدایی ممکن باشد.
async def office_convert(inp: str, outdir: str, target: str) -> str:
    profile = os.path.join(outdir, "_loprofile")
    proc = await asyncio.create_subprocess_exec(
        "soffice", "--headless", "--nologo", "--nofirststartwizard",
        "--nolockcheck", "--norestore",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to", target, "--outdir", outdir, inp,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=240)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"{target} conversion timed out") from None

    base = os.path.splitext(os.path.basename(inp))[0]
    out = os.path.join(outdir, f"{base}.{target}")
    if os.path.exists(out):
        return out
    matches = [f for f in os.listdir(outdir) if f.lower().endswith(f".{target}")]
    if matches:
        return os.path.join(outdir, matches[0])

    lines = [ln for ln in (err or b"").decode("utf-8", "ignore").splitlines() if ln.strip()]
    detail = " | ".join(lines[-3:]) if lines else "no output"
    raise RuntimeError(f"{target} conversion failed: " + detail)


async def office_to_pdf(inp: str, outdir: str) -> str:
    return await office_convert(inp, outdir, "pdf")


# ── تبدیل و ادغامِ PDF (poppler-utils) ──────────────────────────
async def pdf_to_text(inp: str, out: str) -> None:
    await _run(["pdftotext", "-layout", inp, out], timeout=180)
    if not os.path.exists(out):
        raise RuntimeError("no text extracted from PDF")


async def pdf_to_images(inp: str, outdir: str, fmt: str = "jpg", max_pages: int = 100) -> list[str]:
    ext = "png" if fmt.lower() == "png" else "jpg"
    flag = "-png" if ext == "png" else "-jpeg"
    prefix = os.path.join(outdir, "page")
    # -l محدودیتِ صفحه (دفاع در برابرِ PDFهای خیلی بزرگ)
    await _run(["pdftoppm", flag, "-r", "150", "-l", str(max_pages), inp, prefix], timeout=300)
    files = sorted(
        os.path.join(outdir, f) for f in os.listdir(outdir)
        if f.startswith("page") and f.lower().endswith(f".{ext}")
    )
    if not files:
        raise RuntimeError("no pages rendered from PDF")
    return files


async def pdf_merge(inputs: list[str], out: str) -> None:
    if len(inputs) < 2:
        raise RuntimeError("need at least two PDFs to merge")
    await _run(["pdfunite", *inputs, out], timeout=300)
    if not os.path.exists(out):
        raise RuntimeError("PDF merge produced no output")


# ── آرشیو (7-Zip) ──────────────────────────────────────────────
async def archive_list(path: str) -> list[tuple[str, int]]:
    """(name, uncompressed_size) برای هر عضو (پوشه‌ها حذف)."""
    proc = await asyncio.create_subprocess_exec(
        SEVENZ, "l", "-ba", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("cannot read archive")
    entries: list[tuple[str, int]] = []
    for line in out.decode("utf-8", "ignore").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=5)
        if len(parts) < 6:
            continue
        attr, size, name = parts[2], parts[3], parts[5]
        if "D" in attr:  # پوشه
            continue
        try:
            sz = int(size)
        except ValueError:
            sz = 0
        entries.append((name, sz))
    return entries


async def archive_extract(path: str, outdir: str, max_files: int, max_bytes: int) -> list[str]:
    """با محافظِ پایه: قبل از استخراج، حجم/تعدادِ اعلام‌شده را چک می‌کند."""
    entries = await archive_list(path)
    if not entries:
        raise RuntimeError("archive is empty or unreadable")
    if len(entries) > max_files:
        raise RuntimeError(f"too many files: {len(entries)} > {max_files}")
    total = sum(sz for _, sz in entries)
    if total > max_bytes:
        raise RuntimeError(
            f"declared size too large: {total // (1024 * 1024)}MB > {max_bytes // (1024 * 1024)}MB"
        )

    exdir = os.path.join(outdir, "ex")
    os.makedirs(exdir, exist_ok=True)
    await _run([SEVENZ, "x", path, f"-o{exdir}", "-y", "-bd", "-bb0"], timeout=300)

    real_ex = os.path.realpath(exdir)
    files: list[str] = []
    for root, _dirs, names in os.walk(exdir):
        for n in names:
            p = os.path.join(root, n)
            if not os.path.realpath(p).startswith(real_ex):  # zip-slip guard
                continue
            files.append(p)
            if len(files) > max_files:
                raise RuntimeError("too many extracted files")
    return files
