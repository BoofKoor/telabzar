"""پردازشِ فایل‌ها با ffmpeg و Pillow (اجرا در ورکر)."""
from __future__ import annotations

import asyncio

from PIL import Image

FFMPEG = "ffmpeg"


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
        detail = " | ".join(lines[-3:]) if lines else "unknown error"
        raise RuntimeError("ffmpeg failed: " + detail)


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
