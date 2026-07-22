"""پردازشِ فایل‌ها با ffmpeg و Pillow (اجرا در ورکر)."""
from __future__ import annotations

import asyncio
import json
import os
import zipfile

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from .config import settings
from .exceptions import ProcessingCancelled  # re-export (P.ProcessingCancelled)

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


# سرعت/کیفیتِ فشرده‌سازی (از پنل) → پریستِ ffmpeg. کندتر = فایلِ کوچک‌تر ولی زمانِ بیشتر.
_SPEED_PRESET = {"fast": "veryfast", "balanced": "medium", "quality": "slow"}
# معادلِ پریستِ NVENC (p1 تندترین … p7 کندترین).
_NVENC_PRESET = {"veryfast": "p2", "medium": "p4", "slow": "p6"}


def _resolve_preset(speed: str | None) -> str:
    return _SPEED_PRESET.get((speed or settings.compress_speed or "fast").lower(), "veryfast")


def _video_encoder_args(kbps: int | None, crf: int, encoder: str | None = None,
                        preset: str = "veryfast") -> list[str]:
    """آرگومان‌های انکودِ h264.

    پیش‌فرض libx264 با **کنترلِ کیفیتِ محدودشده (VBV)**: CRF (کفِ کیفیت) + سقفِ بیت‌ریت
    → خروجیِ کوچک‌تر از ABRِ خالص با همان سرعت، و حجم همچنان کران‌دارِ زیرِ سقف.
    `-pix_fmt yuv420p` هم سازگاریِ همه‌جا و انکودِ سریع‌ترِ منبعِ ۱۰‌بیتی/4:4:4 را می‌دهد.
    preset = پریستِ ffmpeg (از سرعت/کیفیتِ پنل). encoder='nvenc' (GPU) بسیار سریع‌تر است.
    """
    enc = (encoder or settings.video_encoder or "x264").lower()
    if enc == "nvenc":
        a = ["-c:v", "h264_nvenc", "-preset", _NVENC_PRESET.get(preset, "p4"), "-pix_fmt", "yuv420p"]
        if kbps:
            a += ["-rc", "vbr", "-cq", str(crf), "-b:v", f"{kbps}k",
                  "-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 2}k"]
        else:
            a += ["-rc", "vbr", "-cq", str(crf + 6)]
        return a
    a = ["-c:v", "libx264", "-preset", preset, "-pix_fmt", "yuv420p"]
    if kbps:
        a += ["-crf", str(crf), "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k"]
    else:
        a += ["-crf", str(crf + 6)]
    return a
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


# ── جعبه‌ابزارِ تصویر: اندازه/چرخش/بهبود/واترمارک/به‌PDF (Pillow) ─
def _save_image(img: Image.Image, out: str) -> None:
    """ذخیره بر اساسِ پسوندِ خروجی (jpg مسطح‌شده؛ png/webp با آلفا)."""
    ext = os.path.splitext(out)[1].lower()
    if ext in (".jpg", ".jpeg"):
        _flatten_rgb(img).save(out, "JPEG", quality=90, optimize=True)
    elif ext == ".webp":
        img.save(out, "WEBP", quality=90)
    else:
        img.save(out, "PNG", optimize=True)


def _resize_image_sync(inp: str, out: str, target) -> int:
    img = ImageOps.exif_transpose(Image.open(inp))
    w, h = img.size
    nw = max(1, w // 2) if target == "half" else int(target)
    nw = min(nw, w)  # هرگز بزرگ‌نمایی نکن
    nh = max(1, round(h * nw / w))
    _save_image(img.resize((nw, nh), Image.LANCZOS), out)
    return nw


async def resize_image(inp: str, out: str, target) -> int:
    """تغییرِ اندازه به عرضِ target (px) یا «half»؛ عرضِ نهایی را برمی‌گرداند."""
    return await asyncio.to_thread(_resize_image_sync, inp, out, target)


_ROTATE = {"cw": Image.ROTATE_270, "ccw": Image.ROTATE_90, "180": Image.ROTATE_180}


def _rotate_image_sync(inp: str, out: str, mode: str) -> None:
    img = ImageOps.exif_transpose(Image.open(inp))
    img = ImageOps.mirror(img) if mode == "mirror" else img.transpose(_ROTATE.get(mode, Image.ROTATE_270))
    _save_image(img, out)


async def rotate_image(inp: str, out: str, mode: str) -> None:
    await asyncio.to_thread(_rotate_image_sync, inp, out, mode)


def _enhance_image_sync(inp: str, out: str) -> None:
    img = ImageOps.exif_transpose(Image.open(inp)).convert("RGB")
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.6)
    _save_image(img, out)


async def enhance_image(inp: str, out: str) -> None:
    """بهبودِ خودکار: کنتراستِ خودکار + کمی رنگ و شارپ."""
    await asyncio.to_thread(_enhance_image_sync, inp, out)


def _watermark_image_sync(inp: str, out: str, wm_path: str, position: str, is_logo: bool) -> None:
    base = ImageOps.exif_transpose(Image.open(inp)).convert("RGBA")
    wm = Image.open(wm_path).convert("RGBA")
    if is_logo:  # لوگو را نسبت به عرضِ تصویر کوچک کن
        tw = max(60, base.width // 5)
        th = max(1, round(wm.height * tw / wm.width))
        wm = wm.resize((tw, th), Image.LANCZOS)
    m = max(12, base.width // 50)
    x = m if position in ("tl", "bl") else base.width - wm.width - m
    y = m if position in ("tl", "tr") else base.height - wm.height - m
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.paste(wm, (max(0, x), max(0, y)), wm)
    _save_image(Image.alpha_composite(base, layer), out)


async def watermark_image(inp: str, out: str, wm_path: str, position: str, is_logo: bool = False) -> None:
    await asyncio.to_thread(_watermark_image_sync, inp, out, wm_path, position, is_logo)


def _images_to_pdf_sync(paths: list[str], out: str, max_side: int = 2000) -> None:
    pages: list[Image.Image] = []
    for p in paths:
        img = _flatten_rgb(ImageOps.exif_transpose(Image.open(p)))
        if max(img.size) > max_side:  # صفحاتِ خیلی بزرگ را کوچک کن (مصرفِ حافظه)
            r = max_side / max(img.size)
            img = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.LANCZOS)
        pages.append(img)
    if not pages:
        raise RuntimeError("no images for PDF")
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:])


async def images_to_pdf(paths: list[str], out: str) -> None:
    """چند تصویر → یک PDFِ چندصفحه‌ای (هر تصویر یک صفحه)."""
    await asyncio.to_thread(_images_to_pdf_sync, paths, out)
    if not os.path.exists(out):
        raise RuntimeError("PDF build produced no output")


# ── OCR: استخراجِ متن (tesseract؛ فارسی + انگلیسی) ──────────────
async def _tesseract(png: str, lang: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "tesseract", png, "stdout", "-l", lang,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("OCR timed out") from None
    if proc.returncode != 0:
        detail = " ".join((err or b"").decode("utf-8", "ignore").split())[:160]
        raise RuntimeError(f"OCR failed: {detail}")
    return out.decode("utf-8", "ignore")


async def ocr_image(inp: str, workdir: str, langs: str = "fas+eng") -> str:
    """متنِ تصویر را می‌خواند؛ اگر بستهٔ فارسی نبود، به انگلیسیِ تنها برمی‌گردد."""
    png = os.path.join(workdir, "_ocr_in.png")
    await asyncio.to_thread(
        lambda: ImageOps.exif_transpose(Image.open(inp)).convert("RGB").save(png, "PNG")
    )
    try:
        return await _tesseract(png, langs)
    except RuntimeError:
        return await _tesseract(png, "eng")


# ── حذفِ پس‌زمینه (rembg؛ RAM‌بر → قفلِ هم‌زمانیِ ۱) ────────────
_BG_SEM = asyncio.Semaphore(1)


def _remove_bg_sync(inp: str, out: str) -> None:
    from rembg import remove  # ورودِ تنبل: فقط ورکر این وابستگی را دارد

    with Image.open(inp) as im:
        res = remove(im.convert("RGBA"))
    res.save(out, "PNG")


async def remove_background(inp: str, out: str) -> None:
    async with _BG_SEM:  # هم‌زمان فقط یکی (مصرفِ حافظهٔ مدل بالاست)
        await asyncio.to_thread(_remove_bg_sync, inp, out)
    if not os.path.exists(out):
        raise RuntimeError("background removal produced no output")


# ── رونویسیِ صوت (faster-whisper؛ CPU/RAM‌بر → قفلِ هم‌زمانیِ ۱) ──
_ASR_SEM = asyncio.Semaphore(1)
_WHISPER_MODELS: dict[str, object] = {}  # کشِ مدلِ بارگذاری‌شده به‌ازای هر اندازه


def _srt_ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _transcribe_sync(inp: str, model_size: str, mode: str) -> str:
    from faster_whisper import WhisperModel  # ورودِ تنبل: فقط ورکر این وابستگی را دارد

    model = _WHISPER_MODELS.get(model_size)
    if model is None:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        _WHISPER_MODELS[model_size] = model
    segments, _info = model.transcribe(inp, vad_filter=True)  # تشخیصِ خودکارِ زبان
    if mode == "srt":
        lines: list[str] = []
        for i, seg in enumerate(segments, 1):
            lines += [str(i), f"{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}", seg.text.strip(), ""]
        return "\n".join(lines)
    return " ".join(seg.text.strip() for seg in segments).strip()


async def transcribe_audio(inp: str, model_size: str = "base", mode: str = "txt") -> str:
    """متنِ گفتارِ صوت را برمی‌گرداند (mode=txt) یا زیرنویسِ SRT (mode=srt)."""
    async with _ASR_SEM:  # رونویسیِ هم‌زمان فقط یکی
        return await asyncio.to_thread(_transcribe_sync, inp, model_size, mode)


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


async def trim_audio(inp: str, out: str, start: float, end: float,
                     progress=None, cancel=None) -> None:
    """برشِ بازهٔ [start, end] از صوت (خروجیِ mp3)."""
    await _run([FFMPEG, "-y", "-ss", f"{start}", "-to", f"{end}", "-i", inp,
                "-vn", "-c:a", "libmp3lame", "-b:a", "192k", out],
               progress=progress, duration=max(0.1, end - start), cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("audio trim produced no output")


async def normalize_audio(inp: str, out: str, progress=None, duration=None, cancel=None) -> None:
    """یکسان‌سازیِ بلندی (EBU R128 loudnorm) — برای ضبط‌های کم/پرصدا."""
    await _run([FFMPEG, "-y", "-i", inp, "-vn", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a", "libmp3lame", "-b:a", "192k", out],
               progress=progress, duration=duration, cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("normalize produced no output")


def _atempo_chain(rate: float) -> str:
    """atempo فقط ۰٫۵–۲٫۰ را می‌پذیرد؛ برای خارج از بازه زنجیره می‌سازد."""
    parts: list[str] = []
    r = rate
    while r > 2.0:
        parts.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        parts.append("atempo=0.5")
        r /= 0.5
    parts.append(f"atempo={r:.4f}")
    return ",".join(parts)


async def speed_audio(inp: str, out: str, rate: float, progress=None, duration=None, cancel=None) -> None:
    """تغییرِ سرعت با حفظِ زیروبمی (atempo)."""
    out_dur = (duration / rate) if duration else None
    await _run([FFMPEG, "-y", "-i", inp, "-vn", "-af", _atempo_chain(rate),
                "-c:a", "libmp3lame", "-b:a", "192k", out],
               progress=progress, duration=out_dur, cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("speed change produced no output")


# ── ویدیو (ffmpeg) ─────────────────────────────────────────────
async def compress_video(inp: str, out: str, height: int | None = None, kbps: int | None = None,
                         progress=None, duration=None, cancel=None,
                         encoder: str | None = None, speed: str | None = None) -> None:
    """فشرده‌سازیِ سریع و بهینه. height → اسکیلِ رزولوشن؛ kbps → سقفِ بیت‌ریت (VBV با
    کفِ CRF: خروجیِ کوچک‌ترِ کران‌دار)، وگرنه CRFِ خالص. encoder/speed از پنل می‌آیند
    (پیش‌فرض از env). انکودِ سخت‌افزاری (nvenc) اگر شکست بخورد خودکار به x264 برمی‌گردد."""
    enc = (encoder or settings.video_encoder or "x264").lower()
    preset = _resolve_preset(speed)

    def build(e: str) -> list[str]:
        args = [FFMPEG, "-y", "-i", inp]
        if height:
            args += ["-vf", f"scale=-2:{height}"]  # عرض را زوج نگه‌دار (نیازِ libx264)
        args += _video_encoder_args(kbps, 23, e, preset)
        args += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
        return args

    try:
        await _run(build(enc), progress=progress, duration=duration, cancel=cancel)
    except ProcessingCancelled:
        raise
    except RuntimeError:
        # انکودِ سخت‌افزاری شکست خورد (GPU نیست/اشتباه پیکربندی شده) → با x264 دوباره
        if enc != "x264":
            await _run(build("x264"), progress=progress, duration=duration, cancel=cancel)
        else:
            raise


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
