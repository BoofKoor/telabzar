"""پردازشِ فایل‌ها با ffmpeg و Pillow (اجرا در ورکر)."""
from __future__ import annotations

import asyncio
import json
import os
import zipfile

from PIL import Image

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
SEVENZ = "7z"


async def _run(cmd: list[str], timeout: float = 600) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
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


async def compress_audio(inp: str, out: str) -> None:
    await _run([FFMPEG, "-y", "-i", inp, "-vn", "-c:a", "libmp3lame", "-b:a", "128k", out])


async def convert_audio(inp: str, out: str, fmt: str) -> None:
    codec = _AUDIO_CODEC.get(fmt.lower(), [])
    await _run([FFMPEG, "-y", "-i", inp, "-vn", *codec, out])


# ── ویدیو (ffmpeg) ─────────────────────────────────────────────
async def compress_video(inp: str, out: str) -> None:
    await _run([
        FFMPEG, "-y", "-i", inp,
        "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out,
    ])


async def convert_video(inp: str, out: str, fmt: str) -> None:
    args = [FFMPEG, "-y", "-i", inp]
    if fmt.lower() == "mp4":
        args += [
            "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
            "-c:a", "aac", "-movflags", "+faststart",
        ]
    args.append(out)
    await _run(args)


# ── ویدیو → GIF (پالت دومرحله‌ای برای کیفیت؛ سقفِ ۱۰ ثانیه و عرضِ ۴۸۰) ─
async def video_to_gif(inp: str, out: str) -> None:
    vf = ("fps=12,scale=480:-1:flags=lanczos,split[s0][s1];"
          "[s0]palettegen[p];[s1][p]paletteuse")
    await _run([FFMPEG, "-y", "-i", inp, "-t", "10", "-vf", vf, "-loop", "0", out])
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


# ── سند → PDF (LibreOffice headless) ───────────────────────────
# نکته: soffice حتی وقتی فایلِ ورودی را نمی‌تواند باز کند با کدِ 0 خارج
# می‌شود؛ پس به‌جای اتکا به returncode، وجودِ خروجی را بررسی و در صورتِ
# نبودِ آن، stderr را در پیامِ خطا می‌آوریم تا اشکال‌زدایی ممکن باشد.
async def office_to_pdf(inp: str, outdir: str) -> str:
    profile = os.path.join(outdir, "_loprofile")
    proc = await asyncio.create_subprocess_exec(
        "soffice", "--headless", "--nologo", "--nofirststartwizard",
        "--nolockcheck", "--norestore",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to", "pdf", "--outdir", outdir, inp,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=240)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("PDF conversion timed out") from None

    base = os.path.splitext(os.path.basename(inp))[0]
    out = os.path.join(outdir, base + ".pdf")
    if os.path.exists(out):
        return out
    pdfs = [f for f in os.listdir(outdir) if f.lower().endswith(".pdf")]
    if pdfs:
        return os.path.join(outdir, pdfs[0])

    lines = [ln for ln in (err or b"").decode("utf-8", "ignore").splitlines() if ln.strip()]
    detail = " | ".join(lines[-3:]) if lines else "no output"
    raise RuntimeError("PDF conversion failed: " + detail)


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
