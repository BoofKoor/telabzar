"""پردازشِ فایل‌ها با ffmpeg و Pillow (اجرا در ورکر)."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import math
import os
import re
import signal
import threading
import zipfile

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from .config import settings
from .exceptions import ProcessingCancelled, ProcessingTimeout, UserFacingError  # re-export (P.ProcessingCancelled)

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# فاصلهٔ پرسشِ «لغو شد؟» در `_run`. کوتاه‌تر یعنی واکنشِ سریع‌تر به دکمهٔ لغو،
# بلندتر یعنی فشارِ کمترِ Redis؛ ۲ ثانیه برای یک دکمه به‌قدرِ کافی زنده است.
_CANCEL_POLL = 2.0


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
# 7-Zipِ دبیان/اوبونتو (`+dfsg`) کدک‌های RAR را به‌خاطرِ مجوزِ unRAR ندارد: فهرستِ
# سرآیند را می‌خواند ولی هر عضوِ فشرده را با «Unsupported Method» رد می‌کند —
# یعنی تقریباً هر RARِ واقعی. `unrar-free` (روی libarchive) در ایمیجِ ورکر بود و
# صدا زده نمی‌شد.
UNRAR = "unrar-free"
_RAR_MAGIC = b"Rar!\x1a\x07"

# هر ویدیویی که برای **تحویل** دوباره رمزگذاری می‌شود: 4:2:0ِ ۸بیتی با ابعادِ زوج.
# بدونِ `format=yuv420p`، ffmpeg فرمتِ پیکسلِ منبع را نگه می‌دارد، پس HEVCِ ۱۰بیتیِ
# آیفون یا انیمه بعد از برش/تبدیل H.264ِ «High 10» می‌شد (و webm، VP9ِ Profile 2)
# که بیشترِ پخش‌کننده‌ها — از جمله خودِ تلگرامِ موبایل — نمی‌خوانندش. `-pix_fmt`ِ
# خالی کافی نیست: libx264 روی 4:2:0 با عرض/ارتفاعِ فرد خطا می‌دهد («width not
# divisible by 2») در حالی که منبعِ ۴:۴:۴ِ فرد پیش از این رفع انکود می‌شد؛ پس
# `scale` یک پیکسلِ اضافه را می‌اندازد. `compress_video` همین را از راهِ
# `_video_encoder_args` (و `scale=-2:h`) دارد و `concat_videos` در `vf`ِ خودش.
_DELIVERY_VF = "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"

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


async def stop_task(task) -> None:
    """تسکِ کمکی (ticker و مانندش) را ببند، **بدونِ بلعیدنِ لغوِ خودِ جاب**.

    `await task` بعد از `task.cancel()` می‌تواند به دو دلیلِ کاملاً متفاوت
    `CancelledError` بدهد و کد نمی‌تواند از روی خودِ استثنا تشخیصشان دهد:
    (۱) همان تسکی که خودمان لغو کردیم — باید بلعیده شود؛
    (۲) **خودِ جاب** در همان لحظه لغو شده (`job_timeout`ِ ARQ یا خاموشیِ ورکر) —
    باید بالا برود.

    فرمِ قبلی هر دو را می‌بلعید. در حالتِ رایج بی‌ضرر بود، چون لغو معمولاً وسطِ
    خودِ کار می‌افتد و `finally` فقط از کنارش رد می‌شود؛ ولی اگر لغو **دقیقاً حین
    انتظار برای ticker** برسد گم می‌شد و جاب بعد از دستورِ توقف ادامه می‌داد. آن
    پنجره واقعی است چون ticker هر چند ثانیه یک فراخوانیِ HTTPِ تلگرام می‌زند، و
    سرِ خاموشیِ ورکر همهٔ جاب‌ها هم‌زمان داخلِ همان پنجره‌اند.

    تشخیص با `Task.cancelling()` است (پایتون ۳.۱۱+): اگر تسکِ جاری خودش درخواستِ
    لغوِ معلق دارد، لغو مالِ ما نیست. `gather(..., return_exceptions=True)` و
    «cancel بدونِ await» هر دو امتحان و رد شدند — هر دو هم می‌بلعند.
    """
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling() > 0:
            raise                    # لغو مالِ خودِ جاب است، نه ticker
    except Exception:  # noqa: BLE001 — تسکِ کمکیِ خراب نباید جاب را بشکند
        pass


class CancelWatch:
    """وضعیتِ ناظرِ لغو. `fired` یعنی **خودِ ما** فرایند را کشتیم (نه شکستِ عادی)."""

    __slots__ = ("fired", "task")

    def __init__(self) -> None:
        self.fired = False
        self.task: asyncio.Task | None = None

    def stop(self) -> None:
        """در `finally` صدا زده شود، وگرنه ناظر از خودِ جاب عمر می‌کند."""
        if self.task is not None:
            self.task.cancel()
            self.task = None


def kill_orphan(proc) -> None:
    """در `except BaseException` صدا زده شود: فرایندِ زنده را بکُش، بعد raise.

    **مکانیزمِ یکتای «یتیم نگذار» برای هر چهار زیرفرایندِ پروژه** — ffmpeg در
    `_run`، و در `downloader`: `_run_dl` (دانلود)، `probe` (فازِ probe) و
    `_yt_search_candidates` (مسیرِ تطبیقِ اسپاتیفای/اپل)؛ و از فاز ۴ remuxِ
    `_ensure_mp4` هم، که پنجمین مسیر با همان باگ بود؛ و از کارِ PDF (۲۰۲۶-۱۰)
    `_tesseract`، هر ابزارِ `pdftools._capture` (qpdf/gs/poppler/tesseract)، و
    `office_convert` که «فرایندش» یک گروه است (`_ProcGroup`). مثلِ
    `start_cancel_watcher` عمداً یک پیاده‌سازی است: چهار کپیِ دست‌نویس از یک
    قاعدهٔ ایمنی سرانجام واگرا می‌شوند، و این‌جا از قبل واگرا شده بودند — دو تا
    رفع را گرفتند و دو تا نه.

    محرکِ واقعی `CancelledError` است: `job_timeout`ِ ARQ یا **خاموشیِ ورکر**،
    یعنی هر `telabzar update`. بدونِ این، `finally` فقط ناظر را می‌بندد نه خودِ
    فرایند را.

    عمداً `await proc.wait()` **نمی‌زند**: در مسیرِ لغو خودِ آن await می‌تواند
    دوباره `CancelledError` بگیرد و رفع را بی‌اثر کند. SIGKILL فرایند را
    می‌کُشد و child watcherِ asyncio درویش می‌کند — چیزی که اهمیت دارد پروسهٔ
    **زنده** است، نه zombieِ لحظه‌ای.
    """
    if proc.returncode is None:
        try:
            proc.kill()
        except (ProcessLookupError, OSError):   # از قبل مرده
            pass


def start_cancel_watcher(proc, cancel) -> CancelWatch:
    """هر `_CANCEL_POLL` ثانیه لغو را می‌پرسد و در صورتِ True فرایند را می‌کُشد.

    **مکانیزمِ یکتای لغو برای هر دو زیرفرایندِ پروژه** — ffmpeg در `_run` و
    yt-dlp/gallery-dl در `downloader._run_dl`. عمداً یک پیاده‌سازی است، چون دو
    نسخهٔ دست‌نویسِ یک قاعده سرانجام واگرا می‌شوند (همان درسی که `remove_cookie_file`
    ثبت کرد).

    چرا چکِ لغو **نباید** سوارِ حلقهٔ خواندنِ خروجی شود — دو شکستِ متقارن:
      • حلقه ممکن است **اصلاً اجرا نشود**: `_run` بدونِ progress، یا yt-dlpی که
        اتصالش هنگ کرده و هیچ خطی نمی‌دهد. آن‌وقت دکمهٔ لغو تا تایم‌اوت بی‌اثر
        است — و تایم‌اوتِ دانلود ۳۰۰۰ ثانیه است.
      • حلقه ممکن است **خیلی زیاد** اجرا شود: yt-dlp با `--newline` و
        `--concurrent-fragments 4` ده‌ها خط در ثانیه می‌دهد و هر خط یک
        `EXISTS`ِ Redis می‌شد — که روی نودِ دانلود یک رفت‌وبرگشتِ WireGuard است.
    """
    watch = CancelWatch()
    if cancel is None:
        return watch

    async def _loop() -> None:
        while True:
            await asyncio.sleep(_CANCEL_POLL)
            try:
                if await cancel():
                    watch.fired = True
                    proc.kill()
                    return
            except Exception:  # noqa: BLE001 — خطای چک نباید کار را بشکند
                pass

    watch.task = asyncio.create_task(_loop())
    return watch


async def _run(cmd: list[str], timeout: float = 1800, progress=None, duration: float | None = None,
               cancel=None) -> None:
    """اجرای ffmpeg. اگر progress و duration بدهی، از ‎-progress درصد را می‌خواند
    و progress(percent) را صدا می‌زند.

    **cancel مستقل از progress کار می‌کند.** قبلاً چکِ لغو داخلِ خوانندهٔ
    `-progress` بود، پس هر فراخوانی که progress/duration نمی‌داد — مثلِ حلقهٔ
    نرمال‌سازیِ `concat_videos` که طولانی‌ترین بخشِ کار است — دکمهٔ لغو را
    بی‌اثر می‌کرد. حالا یک ناظرِ جدا هر `_CANCEL_POLL` ثانیه می‌پرسد و در هر دو
    شاخه اجرا می‌شود؛ در `finally` هم کنسل می‌شود تا از خودِ جاب عمر نکند.
    """
    use_prog = progress is not None and bool(duration)
    if use_prog:
        cmd = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE if use_prog else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    watch = start_cancel_watcher(proc, cancel)
    try:
        if use_prog:
            err_chunks: list[bytes] = []

            async def _drain_stderr() -> None:
                async for raw in proc.stderr:  # type: ignore[union-attr]
                    err_chunks.append(raw)

            async def _read_progress() -> None:
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

            try:
                await asyncio.wait_for(
                    asyncio.gather(_read_progress(), _drain_stderr()), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise ProcessingTimeout("processing timed out") from None
            await proc.wait()
            err = b"".join(err_chunks)
        else:
            try:
                _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise ProcessingTimeout("processing timed out") from None
    except BaseException:
        # هر خروجِ غیرعادی — به‌ویژه `CancelledError` از `job_timeout`ِ ARQ یا
        # خاموشیِ ورکر — وگرنه ffmpeg **یتیم** می‌ماند و تا آخر CPU می‌سوزاند.
        # `finally` تنها ناظر را می‌بست، نه خودِ فرایند را؛ بازتولید شد: بعد از
        # `task.cancel()` یک پروسهٔ ffmpeg زنده باقی می‌ماند. («چرا بدونِ
        # `await proc.wait()`» در داکس‌استرینگِ `kill_orphan`.)
        kill_orphan(proc)
        raise
    finally:
        watch.stop()

    if watch.fired:
        raise ProcessingCancelled()

    if proc.returncode != 0:
        lines = [ln for ln in (err or b"").decode("utf-8", "ignore").splitlines() if ln.strip()]
        detail = " | ".join(lines[-3:]) if lines else "no stderr"
        # کدِ منفی = kill با سیگنال (‎-9 ≈ OOM killer — کمبودِ RAM)
        # نامِ ابزارِ واقعی، نه «ffmpeg» برای همه: `_run` فرمانِ pdftotext/pdftoppm/
        # pdfunite را هم اجرا می‌کند و کاربر برای PDFِ خراب «ffmpeg failed» می‌دید.
        tool = os.path.basename(cmd[0]) or "process"
        raise RuntimeError(f"{tool} failed (code {proc.returncode}): " + detail)


# ── تصویر (Pillow) ─────────────────────────────────────────────
def _flatten_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def _upright(path: str) -> Image.Image:
    """تصویر با چرخشِ EXIF اعمال‌شده — تنها درِ ورودیِ Pillow در این ماژول.

    دوربینِ موبایل پیکسل‌ها را به همان جهتِ سنسور ذخیره می‌کند و جهتِ درست را فقط
    در تگِ `Orientation` می‌نویسد. ذخیرهٔ دوبارهٔ Pillow آن تگ را **نمی‌برد**، پس
    بدونِ اعمالِ آن پیش از ذخیره، عکسِ عمودی بعد از فشرده‌سازی/تبدیل کج می‌شد
    (اندازه‌گیری‌شده: ۴۰×۲۰ به‌جای ۲۰×۴۰). `resize`/`rotate`/`enhance` از قبل
    `exif_transpose` داشتند و `compress`/`convert`/`bg_remove`/لوگوی واترمارک نه —
    همان دو نسخهٔ دست‌نویسی که §۷ می‌گوید واگرا می‌شوند؛ گاردِ تستی هر
    `Image.open`ِ دیگری را در این ماژول می‌گیرد.
    """
    return _to_8bit(ImageOps.exif_transpose(Image.open(path)))


_SIXTEEN = ("I;16", "I;16L", "I;16B", "I;16N", "I")


def _to_8bit(img: Image.Image) -> Image.Image:
    """حالت‌هایی که هیچ مسیرِ ذخیره‌ای درست حملشان نمی‌کند، همین‌جا ۸ بیتی/RGB می‌شوند.

    دو شکستِ اندازه‌گیری‌شده پیش از فاز ۴ (روی Pillowِ واقعی):
    * **CMYK** (JPEGِ چاپی/فتوشاپ): `save(..., "PNG")` با «cannot write mode CMYK as
      PNG» می‌ترکید — تبدیل به PNG و هر چرخش/اندازه‌ای که خروجیِ PNG داشت شکست.
    * **۱۶ بیتی** (PNGِ خاکستریِ علمی/اسکنر، `I;16`): `convert("RGB")` مقدار را در
      ۲۵۵ **می‌بُرد** نه مقیاس، پس خروجیِ JPEG تقریباً یکسره سفید بود. حالا با
      بیشینهٔ واقعیِ بازه مقیاس می‌شود (۶۵۵۳۵ برای ۱۶ بیت؛ اگر تصویر فقط ۰..۲۵۵ را
      استفاده کرده باشد دست‌نخورده می‌ماند).
    """
    if img.mode == "CMYK":
        return img.convert("RGB")
    if img.mode in _SIXTEEN:
        img = img.convert("I")
        hi = img.getextrema()[1] or 0
        if hi > 255:
            k = 255 / (65535 if hi <= 65535 else hi)
            img = img.point(lambda v: v * k)
        return img.convert("L")
    return img


def _alpha_of(img: Image.Image) -> Image.Image | None:
    """کانالِ شفافیت اگر تصویر واقعاً دارد، وگرنه None."""
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        return img.convert("RGBA").getchannel("A")
    return None


def _compress_image_sync(inp: str, out: str) -> None:
    _flatten_rgb(_upright(inp)).save(out, "JPEG", quality=70, optimize=True)


def _convert_image_sync(inp: str, out: str, fmt: str) -> None:
    img = _upright(inp)
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
    img = _upright(inp)
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
    img = _upright(inp)
    img = ImageOps.mirror(img) if mode == "mirror" else img.transpose(_ROTATE.get(mode, Image.ROTATE_270))
    _save_image(img, out)


async def rotate_image(inp: str, out: str, mode: str) -> None:
    await asyncio.to_thread(_rotate_image_sync, inp, out, mode)


def _enhance_image_sync(inp: str, out: str) -> None:
    # آلفا جدا نگه داشته و بعد برگردانده می‌شود: `convert("RGB")`ِ خالی شفافیت را
    # دور می‌ریخت و پیکسل‌های شفاف (که RGBشان معمولاً صفر است) **سیاه** می‌شدند —
    # «بهبود» روی یک لوگوی PNG پس‌زمینهٔ سیاه می‌ساخت. JPEG همچنان روی سفید مسطح
    # می‌شود (`_save_image`).
    src = _upright(inp)
    alpha = _alpha_of(src)
    img = src.convert("RGB")
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Sharpness(img).enhance(1.6)
    if alpha is not None:
        img.putalpha(alpha)
    _save_image(img, out)


async def enhance_image(inp: str, out: str) -> None:
    """بهبودِ خودکار: کنتراستِ خودکار + کمی رنگ و شارپ."""
    await asyncio.to_thread(_enhance_image_sync, inp, out)


def _watermark_image_sync(inp: str, out: str, wm_path: str, position: str, is_logo: bool) -> None:
    base = _upright(inp).convert("RGBA")
    wm = _upright(wm_path).convert("RGBA")
    if is_logo:  # لوگو را کوچک/استاندارد کن + کمی محو (شفاف)
        tw = max(48, base.width // 7)
        th = max(1, round(wm.height * tw / wm.width))
        wm = wm.resize((tw, th), Image.LANCZOS)
        alpha = wm.split()[3].point(lambda a: int(a * 0.65))  # ~۶۵٪ کدری
        wm.putalpha(alpha)
    m = max(12, base.width // 50)
    x = m if position in ("tl", "bl") else base.width - wm.width - m
    y = m if position in ("tl", "tr") else base.height - wm.height - m
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.paste(wm, (max(0, x), max(0, y)), wm)
    _save_image(Image.alpha_composite(base, layer), out)


async def watermark_image(inp: str, out: str, wm_path: str, position: str, is_logo: bool = False) -> None:
    await asyncio.to_thread(_watermark_image_sync, inp, out, wm_path, position, is_logo)


# ── OCR: استخراجِ متن (tesseract؛ فارسی + انگلیسی) ──────────────
async def _tesseract(png: str, lang: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "tesseract", png, "stdout", "-l", lang,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            kill_orphan(proc)
            raise RuntimeError("OCR timed out") from None
    except BaseException:
        kill_orphan(proc)   # لغوِ جاب (job_timeout/خاموشی) — tesseract را یتیم نگذار
        raise
    if proc.returncode != 0:
        detail = " ".join((err or b"").decode("utf-8", "ignore").split())[:160]
        raise RuntimeError(f"OCR failed: {detail}")
    return out.decode("utf-8", "ignore")


async def ocr_image(inp: str, workdir: str, langs: str = "fas+eng") -> str:
    """متنِ تصویر را می‌خواند؛ اگر بستهٔ فارسی نبود، به انگلیسیِ تنها برمی‌گردد."""
    png = os.path.join(workdir, "_ocr_in.png")
    await asyncio.to_thread(
        lambda: _upright(inp).convert("RGB").save(png, "PNG")
    )
    try:
        return await _tesseract(png, langs)
    except RuntimeError:
        return await _tesseract(png, "eng")


# ── کارِ سنگینِ درون‌پروسه‌ای (Whisper/rembg) ─────────────────────
# این دو مدل در **thread** اجرا می‌شوند نه زیرفرایند (تا مدلِ بارگذاری‌شده کش
# بماند)، و thread را نمی‌شود کشت. پیش از فاز ۳ `async with sem: await to_thread()`
# بود: لغوِ جاب (`job_timeout`، خاموشی، یا لغو در صف) فقط `await` را رها می‌کرد،
# پس `async with` قفل را **آزاد** می‌کرد در حالی که thread هنوز می‌دوید — جابِ
# بعدی Whisperِ دوم را کنارش راه می‌انداخت (همان RAMی که قفل برای نگه‌داشتنش بود)
# و دکمهٔ لغو هم چون هیچ‌کس `cancel` را نمی‌پرسید بی‌اثر بود.
#
# حالا قفل به **پایانِ خودِ thread** گره خورده (callbackِ `concurrent.futures`)،
# نه به `await`، و `stop` یک `threading.Event` است که کارِ thread بینِ قطعه‌ها
# می‌پرسد. Whisper قطعه‌به‌قطعه تولید می‌کند (`segments` یک generator است) پس
# لغو در مرزِ قطعهٔ بعدی اثر می‌کند؛ rembg یک فراخوانیِ یکپارچه است و قفل را تا
# پایانِ همان فراخوانی نگه می‌دارد — کوتاه است و مهم این است که دوتا نشوند.
_HEAVY_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="heavy")


class _Stopped(Exception):
    """thread به `stop` رسید و کارش را نیمه‌کاره رها کرد."""


async def _exclusive(sem: asyncio.Semaphore, fn, *args, cancel=None):
    """`fn(*args, stop)` را در thread اجرا می‌کند و `sem` را تا **پایانِ thread** نگه می‌دارد."""
    loop = asyncio.get_running_loop()
    stop = threading.Event()
    await sem.acquire()
    try:
        cf = _HEAVY_POOL.submit(fn, *args, stop)
    except BaseException:
        sem.release()
        raise

    def _release(_f) -> None:
        try:
            loop.call_soon_threadsafe(sem.release)
        except RuntimeError:          # لوپ بسته شده (خاموشیِ ورکر) — قفلی نمانده که مهم باشد
            pass

    cf.add_done_callback(_release)
    fut = asyncio.wrap_future(cf)
    try:
        while True:
            done, _ = await asyncio.wait({fut}, timeout=_CANCEL_POLL)
            if done:
                return fut.result()
            if cancel is not None and await cancel():
                stop.set()
                raise ProcessingCancelled()
    except BaseException:
        stop.set()                    # لغوِ جاب هم thread را در مرزِ بعدی متوقف کند
        # نتیجهٔ رهاشده را «خوانده» علامت بزن، وگرنه asyncio برای `_Stopped`ِ بعدی
        # «Future exception was never retrieved» در لاگ می‌نویسد.
        fut.add_done_callback(lambda f: f.cancelled() or f.exception())
        raise


# ── حذفِ پس‌زمینه (rembg؛ RAM‌بر → قفلِ هم‌زمانیِ ۱) ────────────
_BG_SEM = asyncio.Semaphore(1)


def _remove_bg_sync(inp: str, out: str, stop: threading.Event | None = None) -> None:
    from rembg import remove  # ورودِ تنبل: فقط ورکر این وابستگی را دارد

    res = remove(_upright(inp).convert("RGBA"))
    if stop is not None and stop.is_set():
        raise _Stopped()              # لغو شد — نتیجه‌ای که کسی منتظرش نیست را ننویس
    res.save(out, "PNG")


async def remove_background(inp: str, out: str, cancel=None) -> None:
    # هم‌زمان فقط یکی (مصرفِ حافظهٔ مدل بالاست) — تا پایانِ **thread**، نه تا لغو.
    await _exclusive(_BG_SEM, _remove_bg_sync, inp, out, cancel=cancel)
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


def _transcribe_sync(inp: str, model_size: str, mode: str,
                     stop: threading.Event | None = None) -> str:
    from faster_whisper import WhisperModel  # ورودِ تنبل: فقط ورکر این وابستگی را دارد

    model = _WHISPER_MODELS.get(model_size)
    if model is None:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        _WHISPER_MODELS[model_size] = model
    segments, _info = model.transcribe(inp, vad_filter=True)  # تشخیصِ خودکارِ زبان
    done: list = []
    for seg in segments:              # generator: کارِ واقعی همین‌جا قطعه‌به‌قطعه است
        if stop is not None and stop.is_set():
            raise _Stopped()
        done.append(seg)
    if mode == "srt":
        lines: list[str] = []
        for i, seg in enumerate(done, 1):
            lines += [str(i), f"{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}", seg.text.strip(), ""]
        return "\n".join(lines)
    return " ".join(seg.text.strip() for seg in done).strip()


async def transcribe_audio(inp: str, model_size: str = "base", mode: str = "txt",
                           cancel=None) -> str:
    """متنِ گفتارِ صوت را برمی‌گرداند (mode=txt) یا زیرنویسِ SRT (mode=srt)."""
    # رونویسیِ هم‌زمان فقط یکی — تا پایانِ **thread** (`_exclusive`).
    return await _exclusive(_ASR_SEM, _transcribe_sync, inp, model_size, mode, cancel=cancel)


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


async def _media_seconds(path: str) -> float | None:
    """مدتِ **اعشاری** از ffprobe؛ `None` اگر خوانده نشد (آن‌وقت چکی نمی‌شود)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            FFPROBE, "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        val = float((out or b"").decode("utf-8", "ignore").strip())
    except Exception:  # noqa: BLE001
        return None
    return val if val > 0 and math.isfinite(val) else None


async def _check_trim_range(inp: str, start: float) -> None:
    """برشی که بعد از پایانِ فایل شروع شود خطاست، نه «فایلِ خالی».

    ffmpeg روی `-ss` بیرون از فایل با کدِ صفر خارج می‌شود و یک کانتینرِ **بی‌محتوا**
    می‌نویسد (اندازه‌گیری‌شده: ۲۶۲ بایت برای mp4، ۶۷۱ برای mp3)، پس `os.path.exists`
    صادق بود و جاب «انجام شد» می‌گرفت. چکِ خروجی ممکن نیست — همان فایلِ خالی گاهی
    ۰٫۰۱۸ ثانیه primingِ AAC دارد و از یک برشِ واقعیِ کوتاه جدا نمی‌شود — پس **ورودی**
    سنجیده می‌شود. روترِ برش همین را با مدتِ (صحیحِ) تلگرام زودتر و به زبانِ کاربر
    می‌گوید؛ این‌جا تورِ دقیق برای وقتی است که مدتِ کارت نامعلوم است.
    """
    total = await _media_seconds(inp)
    if total is not None and start >= total:
        raise RuntimeError(f"trim range starts after the end of the file ({total:.1f}s)")


async def trim_audio(inp: str, out: str, start: float, end: float,
                     progress=None, cancel=None) -> None:
    """برشِ بازهٔ [start, end] از صوت (خروجیِ mp3)."""
    await _check_trim_range(inp, start)
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


SPEED_MIN, SPEED_MAX = 0.25, 4.0


def _atempo_chain(rate: float) -> str:
    """atempo فقط ۰٫۵–۲٫۰ را می‌پذیرد؛ برای خارج از بازه زنجیره می‌سازد.

    اعتبارسنجیِ بازه اینجا **اجباری** است، نه محضِ ادب: هر دو حلقهٔ زیر روی ورودیِ
    نامعتبر واگرا می‌شوند (`rate=0` → `0/0.5 = 0` تا ابد؛ منفی → `-1,-2,-4,…`؛
    `inf` → `inf/2 = inf`) و چون این تابع **همگام** است و قبل از هر `await` صدا زده
    می‌شود، `job_timeout`ِ ARQ (که asyncio-محور است) نمی‌تواند شلیک کند — یعنی کلِ
    پروسهٔ ورکر قفل می‌شود و `parts` تا OOM رشد می‌کند.
    """
    if not math.isfinite(rate) or not (SPEED_MIN <= rate <= SPEED_MAX):
        raise ValueError(f"speed rate out of range ({SPEED_MIN}–{SPEED_MAX}): {rate}")
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
    except ProcessingTimeout:
        raise      # وقت کم آمد، نه اینکه انکودر خراب باشد → اجرای دومِ کامل ممنوع
    except RuntimeError:
        # انکودِ سخت‌افزاری شکست خورد (GPU نیست/اشتباه پیکربندی شده) → با x264 دوباره
        if enc != "x264":
            await _run(build("x264"), progress=progress, duration=duration, cancel=cancel)
        else:
            raise


def _tiny_plan(duration: float | None, target_mb: int, height: int) -> tuple[int, int, int]:
    """(video_kbps, audio_kbps, height) برای حالتِ خیلی کم‌حجم بر پایهٔ هدفِ حجم/مدت.

    بودجهٔ کل = target_mb×۸۱۹۲÷مدت. صدا ~۳۰٪ (کفِ ۲۴، سقفِ ۴۸، مونو). ویدیو = بقیه،
    کف ۴۸ و سقف ۹۰۰. بیت‌ریتِ ویدیوی خیلی‌کم → اُفتِ خودکار به ۳۶۰p (تمیزتر از ۴۸۰p).
    """
    total = int(target_mb * 8192 / duration) if duration and duration > 0 else 200
    audio = int(min(48, max(24, total * 0.30)))
    video = max(48, min(900, total - audio))
    if video < 70 and height > 360:
        height = 360
    return video, audio, height


async def compress_video_tiny(inp: str, out: str, duration: float | None = None,
                              target_mb: int = 250, height: int = 480,
                              encoder: str | None = None, speed: str | None = None,
                              progress=None, cancel=None) -> None:
    """حالتِ «خیلی کم‌حجم» برای کلاس/جلسه: ویدیوی ۳ساعت‌ونیمهٔ ۷۲۰p → ~۲۵۰MB.

    اهرم‌ها: کوچک‌سازی به ۴۸۰p (اُفتِ خودکار به ۳۶۰p در بیت‌ریتِ خیلی‌کم) + کپِ ۱۵fps +
    صدای مونوی کم‌بیت + بیت‌ریتِ ویدیوی هدف‌محورِ کران‌دار (capped-CRF: کیفیت وقتی صحنه
    ثابت است، سقف وقتی حرکت دارد) + GOPِ بزرگ (محتوای ثابتِ کلاس فشرده‌تر می‌شود).

    NVENC-ready: با encoder='nvenc' دیکود+انکودِ سخت‌افزاری (‎-hwaccel cuda) تا همان کار
    در ~۵ دقیقه تمام شود؛ روی CPU با x264 (کندتر) و در صورتِ شکستِ nvenc خودکار fallback.
    """
    v_kbps, a_kbps, h = _tiny_plan(duration, target_mb, height)
    preset = _resolve_preset(speed)
    gop = 150  # کلیدفریم هر ~۱۰ثانیه در ۱۵fps

    def build_x264() -> list[str]:
        return [
            FFMPEG, "-y", "-i", inp,
            "-vf", f"fps=15,scale=-2:{h}",
            "-c:v", "libx264", "-preset", preset, "-crf", "28",
            "-maxrate", f"{v_kbps}k", "-bufsize", f"{v_kbps * 2}k",
            "-pix_fmt", "yuv420p", "-g", str(gop),
            "-c:a", "aac", "-ac", "1", "-b:a", f"{a_kbps}k",
            "-movflags", "+faststart", out,
        ]

    def build_nvenc() -> list[str]:
        return [
            FFMPEG, "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", inp,
            "-vf", f"scale_cuda=-2:{h},fps=15",
            "-c:v", "h264_nvenc", "-preset", _NVENC_PRESET.get(preset, "p4"),
            "-rc", "vbr", "-cq", "30", "-b:v", f"{v_kbps}k",
            "-maxrate", f"{int(v_kbps * 1.5)}k", "-bufsize", f"{v_kbps * 2}k",
            "-pix_fmt", "yuv420p", "-g", str(gop),
            "-c:a", "aac", "-ac", "1", "-b:a", f"{a_kbps}k",
            "-movflags", "+faststart", out,
        ]

    enc = (encoder or settings.video_encoder or "x264").lower()
    try:
        await _run(build_nvenc() if enc == "nvenc" else build_x264(),
                   progress=progress, duration=duration, cancel=cancel)
    except ProcessingCancelled:
        raise
    except ProcessingTimeout:
        raise      # همان دلیلِ compress_video: تایم‌اوت fallback نمی‌گیرد
    except RuntimeError:
        if enc == "nvenc":  # GPU نبود/اشتباه → با x264 (نرم‌افزاری) دوباره
            await _run(build_x264(), progress=progress, duration=duration, cancel=cancel)
        else:
            raise


async def convert_video(inp: str, out: str, fmt: str, progress=None, duration=None, cancel=None) -> None:
    # `vf` برای **هر** فرمت، نه فقط mp4: mkv همان libx264ِ پیش‌فرض را می‌گیرد و
    # webm همان VP9 را — هر دو با منبعِ ۱۰بیتی خروجیِ ۱۰بیتی می‌دادند.
    args = [FFMPEG, "-y", "-i", inp, "-vf", _DELIVERY_VF]
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
# نکته: `video_thumbnail` با opِ `thumb` حذف شد — تنها فراخوانش همان شاخه بود.
# نیازِ داخلی (کاورِ خودکارِ دانلود) را `video_poster` می‌دهد که همان فیلترِ
# `thumbnail` را دارد، فقط در ≤۳۲۰px و best-effort.
async def video_poster(inp: str, out: str) -> bool:
    """یک فریمِ نماینده در ≤۳۲۰px (سقفِ تامبنیلِ تلگرام) — best-effort، بدونِ خطا."""
    try:
        await _run([
            FFMPEG, "-y", "-i", inp,
            "-vf", "thumbnail,scale=w=320:h=320:force_original_aspect_ratio=decrease",
            "-frames:v", "1", "-q:v", "4", out,
        ], timeout=60)
        return os.path.exists(out) and os.path.getsize(out) > 0
    except Exception:  # noqa: BLE001
        return False


async def probe_media(path: str) -> dict:
    """(width, height, duration) واقعیِ فایل از ffprobe — منبعِ یکتای متادیتای رسانه.

    تلگرام هرچه ما بدهیم را باور می‌کند؛ پس بعد از **هر** عملیاتی که مدت یا ابعاد را
    عوض می‌کند (برش/سرعت/فشرده‌سازی/تبدیل/چسباندن) و برای **هر** فایلِ دانلودی که
    متادیتا همراهش نیامده، باید از خودِ فایل خوانده شود؛ وگرنه زمان/کیفیتِ اشتباه
    نمایش داده می‌شود. برای صوت فقط duration برمی‌گردد (استریمِ ویدیو ندارد).
    """
    cmd = [FFPROBE, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height:format=duration", "-of", "json", path]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        data = json.loads(out or b"{}")
    except Exception:  # noqa: BLE001
        return {}
    st = (data.get("streams") or [{}])[0] or {}
    fmt = data.get("format") or {}
    res: dict = {}
    if st.get("width"):
        res["width"] = int(st["width"])
    if st.get("height"):
        res["height"] = int(st["height"])
    try:
        if fmt.get("duration"):
            dur = int(float(fmt["duration"]))
            if dur > 0:
                res["duration"] = dur
    except (TypeError, ValueError):
        pass
    return res


async def probe_duration(path: str) -> int | None:
    """مدتِ رسانه با ffprobe (ثانیه) — برای نوارِ پیشرفت وقتی متادیتا ندارد."""
    try:
        proc = await asyncio.create_subprocess_exec(
            FFPROBE, "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        val = int(float((out or b"").decode("utf-8", "ignore").strip() or 0))
        return val or None
    except Exception:  # noqa: BLE001
        return None


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
    size = max(14, int((video_h or 480) / 18))  # کوچک‌تر/استانداردتر
    fp = _font_path()
    font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
    tmp = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    box = tmp.textbbox((0, 0), shaped, font=font)
    pad = max(8, size // 3)
    w, h = box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    ox, oy = pad - box[0], pad - box[1]
    dr.text((ox + 2, oy + 2), shaped, font=font, fill=(0, 0, 0, 90))    # سایهٔ ملایم‌تر
    dr.text((ox, oy), shaped, font=font, fill=(255, 255, 255, 175))     # متنِ کمی محو
    im.save(out_png)


async def render_text_watermark(text: str, out_png: str, video_h: int) -> None:
    await asyncio.to_thread(_render_text_watermark_sync, text, out_png, video_h)


async def watermark_video(inp: str, out: str, wm: str, position: str, scale_w: int | None = None,
                          opacity: float = 1.0, progress=None, duration=None, cancel=None) -> None:
    pos = _WM_POS.get(position, _WM_POS["br"])
    if scale_w:  # لوگو را کوچک کن + کمی محو (شفاف)
        fade = f",format=rgba,colorchannelmixer=aa={opacity}" if opacity < 1 else ""
        fc = f"[1:v]scale={scale_w}:-1{fade}[wm];[0:v][wm]overlay={pos}"
    else:        # PNGِ متنی از قبل اندازه‌شده/محو است
        fc = f"[0:v][1:v]overlay={pos}"
    fc += f",{_DELIVERY_VF}"
    await _run([
        FFMPEG, "-y", "-i", inp, "-i", wm, "-filter_complex", fc,
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-c:a", "copy", "-movflags", "+faststart", out,
    ], progress=progress, duration=duration, cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("watermark produced no output")


async def mute_video(inp: str, out: str, cancel=None) -> None:
    """صدا را حذف می‌کند (بدونِ رمزگذاریِ دوباره).

    `-c copy` است پس معمولاً سریع، ولی روی فایلِ نزدیک به سقفِ ۲ گیگ همچنان
    ثانیه‌ها طول می‌کشد — و بدونِ پاس‌دادنِ `cancel` دکمهٔ لغو بی‌اثر بود.
    """
    await _run([FFMPEG, "-y", "-i", inp, "-c", "copy", "-an", "-movflags", "+faststart", out],
               cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("mute produced no output")


async def _has_audio(path: str) -> bool:
    """آیا فایل استریمِ صوتی دارد؟ (برای نرمال‌سازیِ concat)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
            "-of", "csv=p=0", path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        return bool(out.strip())
    except Exception:  # noqa: BLE001
        return False


async def concat_videos(paths: list[str], out: str, width: int | None = None, height: int | None = None,
                        progress=None, duration=None, cancel=None) -> None:
    """چند ویدیو را پشتِ‌هم به یک ویدیو می‌چسباند (به ترتیب).

    ورودی‌ها فرمت/رزولوشن/فریم‌ریتِ متفاوت دارند؛ پس هرکدام اول به پارامترِ یکسان
    نرمال می‌شود (scale+pad به ابعادِ ویدیوی اصلی، ۳۰fps، yuv420p، AACِ استریو ۴۴٫۱،
    و اگر صدا نداشت سکوت) بعد با concat demuxer بی‌رمزگذاریِ دوباره به‌هم وصل می‌شوند.
    """
    W = int(width) if width else 1280
    H = int(height) if height else 720
    W += W % 2  # ابعادِ زوج برای libx264
    H += H % 2
    wd = os.path.dirname(out) or "."
    norm: list[str] = []
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p")
    for i, p in enumerate(paths):
        n = os.path.join(wd, f"vj-norm-{i}.mp4")
        has_a = await _has_audio(p)
        cmd = [FFMPEG, "-y", "-i", p]
        if not has_a:  # ورودیِ بی‌صدا → سکوت تا concat یکدست بماند
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        cmd += ["-vf", vf, "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
                "-c:a", "aac", "-ar", "44100", "-ac", "2"]
        if not has_a:
            cmd += ["-map", "0:v", "-map", "1:a", "-shortest"]
        cmd += [n]
        await _run(cmd, cancel=cancel)
        norm.append(n)
    listf = os.path.join(wd, "vj-list.txt")
    with open(listf, "w", encoding="utf-8") as fh:
        for n in norm:
            fh.write(f"file '{os.path.abspath(n)}'\n")
    await _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", listf,
                "-c", "copy", "-movflags", "+faststart", out],
               progress=progress, duration=duration, cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("video concat produced no output")


async def trim_video(inp: str, out: str, start: float, end: float,
                     progress=None, cancel=None) -> None:
    """برشِ دقیق [start, end] با رمزگذاریِ دوباره.

    `-ss`/`-to` **قبل از** `-i` می‌آیند (سیکِ ورودی)، مثلِ `trim_audio`. با سیکِ
    خروجی (بعد از `-i`) ffmpeg همهٔ فریم‌های پیش از `start` را دیکود و دور
    می‌ریزد، پس هزینه با فاصلهٔ برش از ابتدای فایل بالا می‌رود: روی یک منبعِ
    ۱۸۰ ثانیه‌ای، برشِ [۱۷۰،۱۷۴] ‏۱٫۴۷ ثانیه می‌گرفت و با این فرم ۰٫۳۰ ثانیه.
    دقت از دست نمی‌رود — ffmpeg مدرن از کی‌فریمِ پیش از `start` دیکود می‌کند و
    فریم‌های اضافه را دور می‌ریزد؛ فریمِ اولِ خروجی در هر دو فرم بیت‌به‌بیت یکی است.

    **هر دو باید قبل از `-i` باشند، نه فقط `-ss`.** اگر `-to` بعد از `-i` بماند
    گزینهٔ *خروجی* می‌شود و چون سیکِ ورودی تایم‌استمپ‌ها را صفر می‌کند، `-to end`
    یعنی «تا ثانیهٔ end از خروجی» نه «تا ثانیهٔ end از منبع» — برشِ [۳،۷] به‌جای
    ۴ ثانیه، ۷ ثانیه می‌دهد.
    """
    await _check_trim_range(inp, start)
    await _run([
        FFMPEG, "-y", "-ss", f"{start}", "-to", f"{end}", "-i", inp, "-vf", _DELIVERY_VF,
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-c:a", "aac", "-movflags", "+faststart", out,
    ], progress=progress, duration=max(0.1, end - start), cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("trim produced no output")


async def screenshot_video(inp: str, out: str, ts: float) -> None:
    """فریمِ لحظهٔ ts را به‌صورتِ عکس می‌گیرد (seekِ سریع؛ اگر فریمی نداد، seekِ دقیق)."""
    await _run([FFMPEG, "-y", "-ss", f"{ts}", "-i", inp, "-frames:v", "1", "-q:v", "2", out], timeout=120)
    if not os.path.exists(out):  # ts احتمالاً از مدت گذشته یا کیفریم نبود → seekِ دقیقِ خروجی
        await _run([FFMPEG, "-y", "-i", inp, "-ss", f"{ts}", "-frames:v", "1", "-q:v", "2", out], timeout=300)
    if not os.path.exists(out):  # هنوز نشد → فریمِ اول
        await _run([FFMPEG, "-y", "-i", inp, "-frames:v", "1", "-q:v", "2", out], timeout=120)
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
# نکته: `make_zip`ِ تک‌فایلی حذف شد (فاز ۳الف، موردِ ۸) — دکمهٔ «زیپ» به فلوِ
# جمع‌کردن می‌رود و همیشه `zip_many` را صف می‌کند، حتی برای یک فایل.
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


# ── نوشتنِ متادیتای صوت + کاور (ffmpeg؛ تا جای ممکن بدونِ رمزگذاریِ دوباره) ──
# کدک → (پسوندِ ظرفی که آن کدک را بی‌تغییر نگه می‌دارد، آیا کاور می‌پذیرد).
# ظرف از **کدکِ واقعی** انتخاب می‌شود نه از نامِ فایل: پیش از فاز ۳ پسوند از
# `file.name` می‌آمد و `-c copy` می‌خورد، پس voice noteِ بی‌نام (Opus) و AACِ
# بی‌نام به `.mp3` کپی می‌شدند («Exactly one MP3 audio stream is required»)، و نامی
# مثلِ «Mr. Brightside» پسوندِ «. Brightside» می‌ساخت که ffmpeg برایش ظرفی پیدا
# نمی‌کند — هر سه اجراشده.
_META_CONTAINER: dict[str, tuple[str, bool]] = {
    "mp3": (".mp3", True),
    "aac": (".m4a", True),
    "alac": (".m4a", True),
    "flac": (".flac", True),
    "opus": (".ogg", False),     # ظرفِ ogg کاورِ تصویری نمی‌پذیرد
    "vorbis": (".ogg", False),
}


async def _audio_codec(path: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            FFPROBE, "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name", "-of", "csv=p=0", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
    except Exception:  # noqa: BLE001
        return None
    return (out or b"").decode("utf-8", "ignore").strip().lower() or None


async def _meta_plan(inp: str, want_cover: bool) -> tuple[str, list[str] | None]:
    """(پسوندِ خروجی، آرگومانِ رمزگذاریِ صوت یا `None` = کپیِ بی‌تغییر).

    رمزگذاریِ دوباره فقط وقتی است که کپی ممکن نیست: کدکِ ناشناخته، یا کاوری که
    ظرفِ آن کدک نمی‌پذیرد. منبعِ بی‌اتلاف (PCM) به flac می‌رود نه mp3، چون
    «ویرایشِ تگ» نباید بی‌صدا کیفیت را کم کند.
    """
    codec = await _audio_codec(inp)
    if codec in _META_CONTAINER:
        ext, holds_cover = _META_CONTAINER[codec]
        if holds_cover or not want_cover:
            return ext, None
    if codec and codec.startswith("pcm_"):
        if not want_cover:
            return ".wav", None
        return ".flac", ["-c:a", "flac"]
    return ".mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]


async def write_audio_metadata(inp: str, out_base: str, tags: dict[str, str],
                               cover_path: str | None = None, cancel=None) -> str:
    """تگ (و کاور) را می‌نویسد و **مسیرِ نهایی** را برمی‌گرداند.

    `out_base` مسیرِ بی‌پسوند است؛ پسوند را `_meta_plan` از کدک تعیین می‌کند، پس
    فراخوان نمی‌تواند دوباره پسوند را از نام حدس بزند. اگر مسیرِ نهایی همان ورودی
    باشد، `.tagged` می‌گیرد — ffmpeg با `-y` روی فایلی که هم‌زمان می‌خواند می‌نویسد.
    """
    ext, encode = await _meta_plan(inp, bool(cover_path))
    out = out_base + ext
    if os.path.abspath(out) == os.path.abspath(inp):
        out = out_base + ".tagged" + ext
    args = [FFMPEG, "-y", "-i", inp]
    if cover_path:
        # صوت از ورودیِ ۰، کاورِ جدید از ورودیِ ۱ (کاورِ قبلی دراپ می‌شود)
        args += ["-i", cover_path, "-map", "0:a:0", "-map", "1:0"]
        args += [*encode, "-c:v", "copy"] if encode else ["-c", "copy"]
        args += ["-disposition:v", "attached_pic",
                 "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    elif encode:
        args += ["-map", "0:a:0", *encode]
    else:
        args += ["-map", "0", "-c", "copy"]
    if ext == ".mp3":
        args += ["-id3v2_version", "3"]
    for key, val in tags.items():
        args += ["-metadata", f"{key}={val}"]
    args.append(out)
    await _run(args, cancel=cancel)
    if not os.path.exists(out):
        raise RuntimeError("metadata write produced no output")
    return out


# ── تبدیلِ سند با LibreOffice headless (سند → PDF) ─────────────
# نکته: soffice حتی وقتی فایلِ ورودی را نمی‌تواند باز کند با کدِ 0 خارج
# می‌شود؛ پس به‌جای اتکا به returncode، وجودِ خروجی را بررسی و در صورتِ
# نبودِ آن، stderr را در پیامِ خطا می‌آوریم تا اشکال‌زدایی ممکن باشد.
#
# **و `soffice` یک فرایند نیست، یک درخت است:** اسکریپتِ `soffice` → `oosplash` →
# `soffice.bin`. `proc.kill()` فقط اسکریپت را می‌کشد و `soffice.bin` — که کارِ
# واقعی را می‌کند و صدها مگابایت حافظه دارد — یتیم می‌ماند (اندازه‌گیری‌شده). پس
# فرایند در **گروهِ خودش** شروع می‌شود و کشتن کلِ گروه را می‌کشد.
class _ProcGroup:
    """پوستهٔ `proc` برای `kill_orphan`/`start_cancel_watcher`: `kill()` کلِ گروه را
    می‌کشد. همان دو مکانیزمِ یکتای پروژه، فقط با «کشتن»ِ گسترده‌تر."""

    __slots__ = ("proc",)

    def __init__(self, proc) -> None:
        self.proc = proc

    @property
    def returncode(self):
        return self.proc.returncode

    def kill(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


async def office_convert(inp: str, outdir: str, target: str, cancel=None) -> str:
    profile = os.path.join(outdir, "_loprofile")
    proc = await asyncio.create_subprocess_exec(
        "soffice", "--headless", "--nologo", "--nofirststartwizard",
        "--nolockcheck", "--norestore",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to", target, "--outdir", outdir, inp,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    group = _ProcGroup(proc)
    watch = start_cancel_watcher(group, cancel)
    try:
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=240)
        except asyncio.TimeoutError:
            group.kill()
            raise ProcessingTimeout(f"{target} conversion timed out") from None
    except BaseException:
        group.kill()      # لغوِ جاب: soffice.bin هم، نه فقط اسکریپت
        raise
    finally:
        watch.stop()
        group.kill()      # باقی‌ماندهٔ گروه (اگر چیزی ماند) — گروهِ خالی بی‌اثر است
    if watch.fired:
        raise ProcessingCancelled()

    base = os.path.splitext(os.path.basename(inp))[0]
    out = os.path.join(outdir, f"{base}.{target}")
    if os.path.exists(out):
        return out
    matches = [f for f in os.listdir(outdir) if f.lower().endswith(f".{target}")]
    if matches:
        return os.path.join(outdir, matches[0])

    lines = [ln for ln in (err or b"").decode("utf-8", "ignore").splitlines() if ln.strip()]
    detail = " | ".join(lines[-3:]) if lines else "no output"
    raise UserFacingError("office_failed", detail=detail[:300])


# ── آرشیو (7-Zip) ──────────────────────────────────────────────
def _is_rar(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(len(_RAR_MAGIC)) == _RAR_MAGIC
    except OSError:
        return False


def _parse_unrar_list(text: str) -> list[tuple[str, int]]:
    """خروجیِ `unrar-free -t`: خطِ نام (با یک فاصلهٔ آغازین) و زیرش خطِ «حجم تاریخ
    زمان ویژگی». پوشه‌ها ویژگیِ `D` دارند و حذف می‌شوند."""
    lines = text.splitlines()
    seps = [i for i, ln in enumerate(lines) if ln.startswith("-----")]
    if len(seps) < 2:
        return []
    entries: list[tuple[str, int]] = []
    name: str | None = None
    for ln in lines[seps[0] + 1:seps[1]]:
        m = re.fullmatch(r"\s+(\d+)\s+\S+\s+\S+\s+(\S+)\s*", ln)
        if m and name is not None:
            if "D" not in m.group(2):
                entries.append((name, int(m.group(1))))
            name = None
        elif ln.strip():
            name = ln[1:] if ln.startswith(" ") else ln
    return entries


async def archive_list(path: str) -> list[tuple[str, int]]:
    """(name, uncompressed_size) برای هر عضو (پوشه‌ها حذف)."""
    if _is_rar(path):
        proc = await asyncio.create_subprocess_exec(
            UNRAR, "-t", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        entries = _parse_unrar_list(out.decode("utf-8", "ignore"))
        if proc.returncode != 0 or not entries:
            why = err.decode("utf-8", "ignore").strip().splitlines()[-1:] or ["cannot read archive"]
            raise RuntimeError(f"cannot read RAR archive: {why[0][:160]}")
        return entries
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


def _dir_size(d: str) -> int:
    """مجموعِ حجمِ فایل‌های روی دیسکِ یک درخت (بدونِ دنبال‌کردنِ symlink)."""
    total = 0
    for root, _dirs, names in os.walk(d):
        for n in names:
            try:
                total += os.lstat(os.path.join(root, n)).st_size
            except OSError:
                pass
    return total


async def _extract_capped(path: str, exdir: str, max_bytes: int) -> None:
    """`7z x` را اجرا می‌کند و اگر حجمِ روی دیسک از `max_bytes` رد کرد، می‌کُشدش.

    سقفِ **حین استخراج** تنها محافظِ واقعیِ بمبِ آرشیو است: فهرستِ `7z l`
    ناقص/قابلِ‌جعل است (در `.7z`ِ solid فایل‌های بعدِ اولی ستونِ حجمِ خالی دارند
    و از پارس رد می‌شوند؛ حجمِ `.gz` از تریلری می‌آید که مهاجم می‌نویسد)، پس چکِ
    پیش از استخراج صرفاً یک خروجِ زودهنگامِ ارزان است نه مرز. این‌جا بایتِ
    واقعیِ نوشته‌شده شمرده می‌شود.
    """
    if _is_rar(path):
        # همان سقف و همان kill، فقط ابزارِ دیگر. `unrar-free` نامِ `..`دار را رد
        # می‌کند، مسیرِ مطلق را زیرِ مقصد می‌نشاند و symlink نمی‌سازد —
        # `tests/test_rar_extract.py` همین را پین می‌کند، مثلِ پینِ 7z در فاز ۲الف.
        cmd = [UNRAR, "-x", "-f", path, exdir.rstrip(os.sep) + os.sep]
    else:
        cmd = [SEVENZ, "x", path, f"-o{exdir}", "-y", "-bd", "-bb0"]
    os.makedirs(exdir, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        while True:
            try:
                await asyncio.wait_for(proc.wait(), timeout=0.5)
                break                                   # تمام شد
            except asyncio.TimeoutError:
                if _dir_size(exdir) > max_bytes:        # از بودجه رد شد → بکُش
                    kill_orphan(proc)
                    raise RuntimeError(
                        f"extracted size exceeds {max_bytes // (1024 * 1024)}MB")
        if _dir_size(exdir) > max_bytes:                # یک چکِ پایانی
            raise RuntimeError(f"extracted size exceeds {max_bytes // (1024 * 1024)}MB")
        if proc.returncode != 0:
            err = b""
            try:
                err = (await proc.stderr.read()) if proc.stderr else b""
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"extract failed: {err.decode('utf-8', 'ignore')[:200]}")
    except BaseException:
        kill_orphan(proc)                               # لغو/تایم‌اوت: یتیم نگذار
        raise


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
    # سقفِ **حین استخراج** (مرزِ واقعی) — چکِ بالا فقط خروجِ زودهنگام بود.
    await _extract_capped(path, exdir, max_bytes)

    # مرزِ مسیر، نه پیشوندِ رشته‌ای: `startswith(real_ex)` برای `<outdir>/exfil`
    # هم صادق است چون پیشوندِ `<outdir>/ex` را دارد. با افزودنِ جداکننده مرز واقعی
    # سنجیده می‌شود. (استخراج قبلاً انجام شده، پس این فیلترِ فهرستِ خروجی است نه
    # جلوگیری از نوشتن — امروز `7z x` خودش `../`، symlink و مسیرِ مطلق را خنثی
    # می‌کند و `tests/test_phase2a.py` همان رفتار را پین کرده است.)
    real_ex = os.path.realpath(exdir)
    inside = real_ex + os.sep
    files: list[str] = []
    for root, _dirs, names in os.walk(exdir):
        for n in names:
            p = os.path.join(root, n)
            if not os.path.realpath(p).startswith(inside):  # zip-slip guard
                continue
            files.append(p)
            if len(files) > max_files:
                raise RuntimeError("too many extracted files")
    return files
