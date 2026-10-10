"""ابزارهای PDF در ورکر: باز/تعمیر، صفحه‌ها، ادغام، فشرده‌سازی، رمز، رندر، OCR، عکس→PDF.

**هر عملیاتِ PDF از `prepare` شروع می‌شود**، و این یک قاعده است نه بهینه‌سازی.
بیشترِ PDFهای واقعی (صورت‌حسابِ بانک، کتابِ الکترونیکی، خروجیِ اسکنر) با «رمزِ
مالک» قفل‌اند: بی‌رمز باز می‌شوند ولی `pdfunite` با «Could not merge encrypted
files» ادغامشان را رد می‌کرد و کاربر یک خطای خامِ انگلیسی می‌گرفت. `qpdf --decrypt`
آن قفل را بی‌رمز برمی‌دارد، فایلِ آسیب‌دیده را تعمیر می‌کند، و ورودیِ هر ابزارِ
بعدی را یک PDFِ **واقعی** می‌کند — که برای Ghostscript مهم است: Ghostscript نوعِ
فایل را از محتوا تشخیص می‌دهد و فایلی با پسوندِ `.pdf` که PostScript است را
**اجرا** می‌کند. فایلی که رمزِ کاربر دارد همین‌جا با پیامِ روشن («اول رمز را
بردار») متوقف می‌شود، نه وسطِ سومین ابزار.

هر زیرفرایند از `_capture` رد می‌شود که همان دو قاعدهٔ پروژه را دارد: `kill_orphan`
روی لغوِ جاب، و `start_cancel_watcher` برای دکمهٔ لغو (`processing`).

خطای کاربرپسند `UserFacingError` است (کلیدِ locale)، نه `RuntimeError`ِ خام —
`run_op` آن را به زبانِ کاربر نشان می‌دهد.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import shutil
import zipfile

from PIL import Image

from . import processing as P
from .pagespec import check_password
from .exceptions import ProcessingCancelled, ProcessingTimeout, UserFacingError

log = logging.getLogger("telabzar.pdf")

QPDF = "qpdf"
GS = "gs"
PDFTOPPM = "pdftoppm"
PDFINFO = "pdfinfo"
TESSERACT = "tesseract"

#: سقفِ صفحه‌هایی که به تصویر تبدیل می‌شوند (هر صفحه یک فایل).
RENDER_MAX_PAGES = 100
#: بیشتر از این تعداد فایل → یک ZIP به‌جای آلبوم. هر آلبوم ده پیام است و
#: فرستادنِ صد پیامِ پشتِ‌هم به سقفِ نرخِ تلگرام (۴۲۹) می‌خورد.
ALBUM_MAX_FILES = 20


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def is_pdf(path: str) -> bool:
    """سرِ فایل `%PDF-` دارد؟ (طبقِ مشخصه در ۱۰۲۴ بایتِ اول، نه حتماً بایتِ صفر.)"""
    try:
        with open(path, "rb") as fh:
            return b"%PDF-" in fh.read(1024)
    except OSError:
        return False


def _tail(err: bytes, n: int = 3) -> str:
    lines = [ln.strip() for ln in (err or b"").decode("utf-8", "ignore").splitlines() if ln.strip()]
    return " | ".join(lines[-n:])[:300]


async def _capture(cmd: list[str], *, timeout: float = 300.0, cancel=None) -> tuple[int, bytes, bytes]:
    """اجرای یک ابزار با خروجیِ گرفته‌شده؛ لغو و تایم‌اوت فرایند را یتیم نمی‌گذارند."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    watch = P.start_cancel_watcher(proc, cancel)
    try:
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            P.kill_orphan(proc)
            raise ProcessingTimeout(f"{os.path.basename(cmd[0])} timed out") from None
    except BaseException:
        P.kill_orphan(proc)        # CancelledError از job_timeout / خاموشیِ ورکر
        raise
    finally:
        watch.stop()
    if watch.fired:
        raise ProcessingCancelled()
    return proc.returncode, out or b"", err or b""


def _ok(rc: int, out_path: str) -> bool:
    """qpdf با کدِ ۳ یعنی «انجام شد ولی هشدار داشت» (مثلاً فایلِ تعمیرشده)."""
    return rc in (0, 3) and os.path.exists(out_path) and os.path.getsize(out_path) > 0


def _secret_file(workdir: str, name: str, lines: list[str]) -> str:
    """رمز روی خطِ فرمان نمی‌آید (در `ps`ِ کانتینر و هر لاگِ فرمانی دیده می‌شد)؛
    در فایلی با مجوزِ ۰۶۰۰ داخلِ workdir می‌نشیند که آخرِ جاب پاک می‌شود."""
    path = os.path.join(workdir, f".{name}-{secrets.token_hex(4)}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


# ── ورودی: باز، تعمیر، قفلِ مالک ─────────────────────────────────
async def prepare(src: str, workdir: str, *, password: str | None = None, cancel=None) -> str:
    """PDFِ کاربر → نسخهٔ بی‌قفل و تعمیرشده در workdir (یا خودِ ورودی اگر qpdf نیست).

    `pdf_needs_password` = رمزِ کاربر دارد و رمزی داده نشده؛ `pdf_wrong_password` =
    رمز داده شد و غلط بود؛ `pdf_not_pdf` = اصلاً PDF نیست.
    """
    if not is_pdf(src):
        raise UserFacingError("pdf_not_pdf")
    if not have(QPDF):
        return src
    out = os.path.join(workdir, f"_pdf-{secrets.token_hex(4)}.pdf")
    cmd = [QPDF, "--decrypt"]
    if password is not None:
        cmd.append("--password-file=" + _secret_file(workdir, "pw", [password]))
    cmd += [src, out]
    rc, _, err = await _capture(cmd, timeout=300, cancel=cancel)
    if _ok(rc, out):
        return out
    text = err.decode("utf-8", "ignore").lower()
    if "invalid password" in text:
        raise UserFacingError("pdf_wrong_password" if password is not None else "pdf_needs_password")
    raise UserFacingError("pdf_damaged", detail=_tail(err))


async def is_encrypted(path: str, cancel=None) -> bool:
    """`--is-encrypted` رمز لازم ندارد: صفر = رمزدار، دو = بی‌رمز."""
    rc, _, _ = await _capture([QPDF, "--is-encrypted", path], timeout=60, cancel=cancel)
    return rc == 0


async def page_count(path: str, cancel=None) -> int:
    rc, out, err = await _capture([QPDF, "--show-npages", path], timeout=120, cancel=cancel)
    try:
        n = int(out.decode().strip())
    except ValueError:
        raise UserFacingError("pdf_damaged", detail=_tail(err)) from None
    if rc not in (0, 3) or n < 1:
        raise UserFacingError("pdf_damaged", detail=_tail(err))
    return n


# ── صفحه‌ها ──────────────────────────────────────────────────────
async def select_pages(src: str, pages: list[int], out: str, cancel=None) -> None:
    """فقط این صفحه‌ها، **به همین ترتیب** (حذف و جدا کردن و مرتب‌کردن یک مسیرند)."""
    if not pages:
        raise UserFacingError("pdf_pages_empty")
    rc, _, err = await _capture(
        [QPDF, "--empty", "--pages", src, ",".join(map(str, pages)), "--", out],
        timeout=300, cancel=cancel)
    if not _ok(rc, out):
        raise RuntimeError(f"qpdf failed: {_tail(err)}")


async def rotate(src: str, out: str, angle: int, cancel=None) -> None:
    """چرخشِ همهٔ صفحه‌ها؛ نسبی به چرخشِ فعلی (`+90` روی صفحهٔ از قبل چرخیده)."""
    if angle not in (90, 180, 270):
        raise ValueError(f"bad angle: {angle}")
    spec = "-90" if angle == 270 else f"+{angle}"
    rc, _, err = await _capture([QPDF, src, out, f"--rotate={spec}"], timeout=300, cancel=cancel)
    if not _ok(rc, out):
        raise RuntimeError(f"qpdf failed: {_tail(err)}")


async def split(src: str, outdir: str, stem: str, cancel=None) -> list[str]:
    """هر صفحه یک PDF؛ نام‌ها با شمارهٔ صفرپرشده، پس مرتب‌سازیِ رشته‌ای درست است."""
    os.makedirs(outdir, exist_ok=True)
    rc, _, err = await _capture(
        [QPDF, "--split-pages", src, os.path.join(outdir, f"{stem}-%d.pdf")],
        timeout=600, cancel=cancel)
    files = sorted(os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith(".pdf"))
    if rc not in (0, 3) or not files:
        raise RuntimeError(f"qpdf failed: {_tail(err)}")
    return files


async def merge(inputs: list[str], out: str, cancel=None) -> None:
    """ادغام با qpdf (ورودی‌ها از قبل `prepare` شده‌اند، پس قفلِ مالک مانع نیست)."""
    if len(inputs) < 2:
        raise UserFacingError("merge_need_more")
    rc, _, err = await _capture([QPDF, "--empty", "--pages", *inputs, "--", out],
                                timeout=600, cancel=cancel)
    if not _ok(rc, out):
        raise RuntimeError(f"qpdf failed: {_tail(err)}")


# ── رمز ──────────────────────────────────────────────────────────
async def lock(src: str, out: str, password: str, workdir: str, cancel=None) -> None:
    """AES-256 با رمزِ کاربر. رمزِ مالک تصادفی است: qpdf رمزِ یکسان را «ناامن»
    می‌داند، و کاربر برای باز کردن/برداشتنِ رمز فقط همان رمزِ خودش را لازم دارد."""
    if not check_password(password):
        raise UserFacingError("pdf_pw_bad")
    owner = secrets.token_urlsafe(24)
    args = _secret_file(workdir, "enc", ["--encrypt", password, owner, "256", "--"])
    rc, _, err = await _capture([QPDF, f"@{args}", src, out], timeout=300, cancel=cancel)
    if not _ok(rc, out):
        raise RuntimeError(f"qpdf failed: {_tail(err)}")


# ── فشرده‌سازی ───────────────────────────────────────────────────
_GS_LEVEL = {
    # «معمولی»: تصویرها ۱۵۰dpi — متن و جدول‌ها کاملاً خوانا می‌مانند.
    "normal": ["-dPDFSETTINGS=/ebook"],
    # «زیاد»: ۹۶dpi برای رنگی/خاکستری. `/screen`ِ خام ۷۲dpi است که اسکنِ متنی را
    # ناخوانا می‌کند؛ تصویرِ سیاه‌وسفید (اسکنِ تک‌رنگ) ۳۰۰ می‌ماند چون فشرده‌سازیِ
    # بی‌اتلافِ آن‌ها با کاهشِ dpi تقریباً چیزی نمی‌خرد و فقط ناخواناتر می‌شود.
    #
    # فیلترِ JPEG **اجباری** است و این از اندازه‌گیری آمد نه سلیقه: با رزولوشنِ
    # دستی، انتخاب‌گرِ خودکارِ Ghostscript روی صفحهٔ اسکن‌شده Flate برداشت و
    # خروجیِ «زیاد» (۲٫۰ مگ) از «معمولی» (۰٫۵ مگ) **بزرگ‌تر** شد. کسی که «حداکثر
    # فشرده» را می‌زند آرتیفکتِ JPEG روی نمودار را پذیرفته؛ «معمولی» انتخابِ
    # خودکار را نگه می‌دارد.
    "strong": ["-dPDFSETTINGS=/ebook",
               "-dColorImageResolution=96", "-dGrayImageResolution=96",
               "-dMonoImageResolution=300",
               "-dAutoFilterColorImages=false", "-dColorImageFilter=/DCTEncode",
               "-dAutoFilterGrayImages=false", "-dGrayImageFilter=/DCTEncode"],
}
#: خروجیِ کمتر از ۵٪ کوچک‌تر «بی‌فایده» است — کارت را با فایلی که فقط کیفیتش را
#: از دست داده عوض نمی‌کنیم.
MIN_GAIN = 0.95


async def compress(src: str, workdir: str, level: str, cancel=None) -> str | None:
    """کوچک‌ترین نسخه از Ghostscript (بااتلاف) و qpdf (بی‌اتلاف)، یا `None` اگر هیچ‌کدام
    حداقل ۵٪ کم نکرد. `src` باید خروجیِ `prepare` باشد (نه فایلِ خامِ کاربر)."""
    if level not in _GS_LEVEL:
        raise ValueError(f"bad level: {level}")
    orig = os.path.getsize(src)
    cands: list[str] = []
    if have(GS):
        gs_out = os.path.join(workdir, "_gs.pdf")
        cmd = [GS, "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
               "-dCompatibilityLevel=1.5", *_GS_LEVEL[level],
               "-dDetectDuplicateImages=true", "-dAutoRotatePages=/None",
               f"-sOutputFile={gs_out}", src]
        rc, _, err = await _capture(cmd, timeout=1200, cancel=cancel)
        if rc == 0 and os.path.exists(gs_out) and os.path.getsize(gs_out) > 0:
            cands.append(gs_out)
        else:
            log.warning("ghostscript compress failed (code %s): %s", rc, _tail(err))
    if have(QPDF):
        q_out = os.path.join(workdir, "_qpdf.pdf")
        rc, _, err = await _capture(
            [QPDF, "--object-streams=generate", "--compress-streams=y", "--recompress-flate",
             "--compression-level=9", src, q_out], timeout=600, cancel=cancel)
        if _ok(rc, q_out):
            cands.append(q_out)
    if not cands:
        raise RuntimeError("no PDF compressor produced output")
    best = min(cands, key=os.path.getsize)
    return best if os.path.getsize(best) <= orig * MIN_GAIN else None


# ── رندرِ صفحه‌ها ────────────────────────────────────────────────
async def render_pages(src: str, outdir: str, fmt: str, *, n_pages: int,
                       max_pages: int = RENDER_MAX_PAGES, dpi: int = 150,
                       cancel=None) -> list[str]:
    """صفحه‌ها → تصویر در یک پوشهٔ **اختصاصی** (نه workdir، که فایل‌های دیگری هم دارد)."""
    os.makedirs(outdir, exist_ok=True)
    last = min(n_pages, max_pages)
    cmd = [PDFTOPPM, "-r", str(dpi), "-f", "1", "-l", str(last)]
    cmd += ["-png"] if fmt == "png" else ["-jpeg", "-jpegopt", "quality=90"]
    cmd += [src, os.path.join(outdir, "page")]
    rc, _, err = await _capture(cmd, timeout=900, cancel=cancel)
    files = sorted(os.path.join(outdir, f) for f in os.listdir(outdir)
                   if f.startswith("page") and f.endswith((".png", ".jpg")))
    if rc != 0 or not files:
        raise RuntimeError(f"pdftoppm failed (code {rc}): {_tail(err)}")
    return files


async def page_size(src: str, page: int, cancel=None) -> tuple[float, float] | None:
    """اندازهٔ صفحه (pt) از `pdfinfo` — همان MediaBox که pdftoppm بی‌`-cropbox` رندر
    می‌کند. خوانده نشد → `None` (رندر با همان dpiِ خواسته‌شده می‌رود)."""
    if not have(PDFINFO):
        return None
    rc, out, _ = await _capture([PDFINFO, "-f", str(page), "-l", str(page), src],
                                timeout=60, cancel=cancel)
    m = re.search(rb"Page\s+%d size:\s+([\d.]+) x ([\d.]+)" % page, out)
    return (float(m[1]), float(m[2])) if m else None


def fit_dpi(size: tuple[float, float] | None, dpi: int, max_px: int) -> int:
    """dpi‌ای که ضلعِ بلندِ صفحه از `max_px` پیکسل نگذرد — هرگز **بیشتر** از `dpi`.

    PDFی که از عکس ساخته شده (اسکنِ گوشی، PILِ پیش‌فرض) اندازهٔ صفحه‌اش پیکسل است نه
    اینچ: ۲۴۸۰×۳۵۰۸ pt یعنی ۳۴×۴۹ اینچ. همان صفحه در ۳۰۰dpi یک تصویرِ ۱۵۱ مگاپیکسلی
    بود که tesseract با **۱٫۶ گیگابایت** حافظه و ۲۸ ثانیه می‌خواندش (اندازه‌گیری‌شده) —
    سی صفحه یعنی بیش از ربع ساعت یا OOMِ ورکر، در حالی که عکسِ مبدأ خودش ۲۴۸۰ پیکسل
    است و dpiِ بیشتر هیچ جزئیاتی اضافه نمی‌کند.
    """
    long_pt = max(size) if size else 0.0
    if long_pt <= 0:
        return dpi
    return max(1, min(dpi, int(max_px * 72 / long_pt)))


async def render_page(src: str, page: int, out_base: str, *, dpi: int, gray: bool = False,
                      max_px: int | None = None, cancel=None) -> str:
    """یک صفحه → `<out_base>.png`. با `max_px` ضلعِ بلند از آن نمی‌گذرد (`fit_dpi`)."""
    if max_px:
        dpi = fit_dpi(await page_size(src, page, cancel=cancel), dpi, max_px)
    cmd = [PDFTOPPM, "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", "-singlefile"]
    if gray:
        cmd.append("-gray")
    rc, _, err = await _capture(cmd + [src, out_base], timeout=300, cancel=cancel)
    out = out_base + ".png"
    if rc != 0 or not os.path.exists(out):
        raise RuntimeError(f"pdftoppm failed (code {rc}): {_tail(err)}")
    return out


def zip_files(paths: list[str], out: str) -> None:
    """بی‌فشرده‌سازی (`STORED`): JPEG/PNG/PDF از قبل فشرده‌اند و deflate فقط CPU می‌خورد."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for p in paths:
            z.write(p, os.path.basename(p))


# ── OCR ──────────────────────────────────────────────────────────
OCR_DPI = 300
#: سقفِ ضلعِ بلندِ تصویرِ OCR (پیکسل): A4 در ۳۰۰dpi ۳۵۰۸ است و A3 در ۲۵۴dpi همین؛ صفحه‌ای
#: که بیش از این بخواهد اندازه‌اش پیکسل است نه کاغذ (`fit_dpi`).
OCR_MAX_PX = 4200


async def ocr_png(png: str, cancel=None, langs: str = "fas+eng") -> str:
    """tesseract روی یک تصویر. نبودِ بستهٔ زبانِ فارسی → انگلیسیِ تنها (مثلِ `ocr_image`)."""
    rc, out, err = await _capture([TESSERACT, png, "stdout", "-l", langs], timeout=300, cancel=cancel)
    if rc != 0 and langs != "eng":
        rc, out, err = await _capture([TESSERACT, png, "stdout", "-l", "eng"],
                                      timeout=300, cancel=cancel)
    if rc != 0:
        raise RuntimeError(f"tesseract failed (code {rc}): {_tail(err)}")
    return out.decode("utf-8", "ignore")


async def ocr_pages(src: str, workdir: str, pages: list[int], cancel=None,
                    progress=None) -> list[str | None]:
    """متنِ هر صفحه (به همان ترتیب). صفحه‌ها یکی‌یکی رندر می‌شوند و PNGِ هر صفحه
    بلافاصله پاک می‌شود: یک A4 در ۳۰۰dpi حدودِ ۹ مگاپیکسل است و صد صفحهٔ هم‌زمان
    روی دیسک یعنی گیگابایت.

    صفحه‌ای که رندر یا OCRش شکست بخورد (ابزار خطا داد، تایم‌اوت، کشته‌شدن) `None`
    می‌گیرد و بقیه ادامه می‌دهند — یک صفحهٔ عجیب نباید تبدیلِ سی‌صفحه‌ای را بکشد؛ در
    Word همان صفحه عکس می‌شود. اگر **هیچ** صفحه‌ای خوانده نشد مشکل از سیستم است نه از
    یک صفحه، پس خطای آخر بالا می‌رود.
    """
    if not have(TESSERACT):
        raise UserFacingError("pdf_ocr_unavailable")
    texts: list[str | None] = []
    last_err: RuntimeError | None = None
    for i, p in enumerate(pages):
        png = None
        try:
            png = await render_page(src, p, os.path.join(workdir, f"_ocr-{p}"), dpi=OCR_DPI,
                                    gray=True, max_px=OCR_MAX_PX, cancel=cancel)
            texts.append(await ocr_png(png, cancel=cancel))
        except UserFacingError:
            raise
        except RuntimeError as e:      # ProcessingTimeout هم RuntimeError است؛ لغو نه
            log.warning("ocr failed on page %s", p, exc_info=True)
            texts.append(None)
            last_err = e
        finally:
            if png:
                try:
                    os.remove(png)
                except OSError:
                    pass
        if progress is not None:
            try:
                await progress((i + 1) / len(pages) * 100)
            except Exception:  # noqa: BLE001
                pass
    if last_err is not None and all(x is None for x in texts):
        raise last_err
    return texts


_BIDI_MARKS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def tidy_ocr(text: str) -> str:
    """خروجیِ tesseract: خطوطِ خالیِ پشتِ‌هم یکی، فاصلهٔ انتهای خط برداشته، و
    نشانه‌های جهتی که tesseract دورِ هر کلمهٔ انگلیسی می‌گذارد حذف (جهت را خروجی
    خودش تعیین می‌کند؛ در Word این نشانه‌ها فقط جای مکان‌نما را گیج می‌کنند)."""
    text = _BIDI_MARKS.sub("", text or "")
    lines = [ln.rstrip() for ln in text.replace("\f", "\n").splitlines()]
    out: list[str] = []
    for ln in lines:
        if not ln and (not out or not out[-1]):
            continue
        out.append(ln)
    return "\n".join(out).strip()


# ── عکس‌ها → PDF ─────────────────────────────────────────────────
A4 = (595.276, 841.89)
#: حاشیهٔ صفحهٔ A4 (pt) — ۸ میلی‌متر: کاغذِ چاپی لبهٔ ناچاپ دارد، و عکسِ سند
#: بی‌حاشیه روی صفحه بریده دیده می‌شود.
A4_MARGIN = 22.7
#: حالتِ «اندازهٔ عکس»: هر پیکسل در ۱۵۰dpi — عکسِ ۱۲۸۰پیکسلیِ تلگرام ≈ عرضِ A4.
FIT_DPI = 150
#: عکسی که باید دوباره انکود شود، بیش از این ضلع کوچک می‌شود (حافظه و حجم).
REENCODE_MAX_SIDE = 3000


def _pdf_image(path: str, workdir: str, idx: int) -> tuple[str, int, int, str]:
    """(مسیرِ JPEG, عرض, ارتفاع, فضای رنگ) برای جاسازی در PDF.

    JPEGِ RGB/خاکستریِ بی‌چرخش **عیناً** جاسازی می‌شود (DCTDecode) — بدونِ این،
    هر عکسِ ازپیش‌فشرده یک‌بار دیگر انکود می‌شد (نسخهٔ Pillow با کیفیتِ ۷۵) و
    کیفیت می‌باخت. هر چیزِ دیگری (PNG، WebP، CMYK، JPEGِ دارای تگِ چرخش) یک‌بار با
    کیفیتِ ۹۲ انکود می‌شود، با چرخشِ EXIF اعمال‌شده (`processing._upright`).
    """
    with Image.open(path) as im:
        fmt, mode, size = im.format, im.mode, im.size
        try:
            orient = im.getexif().get(0x0112, 1)
        except Exception:  # noqa: BLE001
            orient = 1
    if fmt == "JPEG" and mode in ("RGB", "L") and orient in (1, None):
        return path, size[0], size[1], "DeviceRGB" if mode == "RGB" else "DeviceGray"
    img = P._upright(path)
    if img.mode in ("L", "LA", "1"):
        img = P._flatten_rgb(img).convert("L") if img.mode == "LA" else img.convert("L")
    else:
        img = P._flatten_rgb(img)
    if max(img.size) > REENCODE_MAX_SIDE:
        r = REENCODE_MAX_SIDE / max(img.size)
        img = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.LANCZOS)
    out = os.path.join(workdir, f"_imgpdf-{idx}.jpg")
    img.save(out, "JPEG", quality=92, optimize=True)
    return out, img.width, img.height, "DeviceGray" if img.mode == "L" else "DeviceRGB"


def _page_box(w: int, h: int, mode: str) -> tuple[float, float, float, float, float, float]:
    """(عرضِ صفحه, ارتفاعِ صفحه, x, y, عرضِ تصویر, ارتفاعِ تصویر) به pt."""
    if mode == "fit":
        pw, ph = w * 72 / FIT_DPI, h * 72 / FIT_DPI
        return pw, ph, 0.0, 0.0, pw, ph
    pw, ph = (A4[1], A4[0]) if w > h else A4       # جهتِ صفحه از جهتِ عکس
    s = min((pw - 2 * A4_MARGIN) / w, (ph - 2 * A4_MARGIN) / h)
    dw, dh = w * s, h * s
    return pw, ph, (pw - dw) / 2, (ph - dh) / 2, dw, dh


def _write_images_pdf(units: list[tuple[str, int, int, str]], out: str, mode: str) -> None:
    """یک PDFِ ۱.۴ِ کمینه: هر عکس یک صفحه. جریانِ JPEG تکه‌تکه از دیسک کپی می‌شود
    (نه کلِ عکس‌ها در حافظه) — مجموعه سقفِ تعداد ندارد."""
    n = len(units)
    offsets: dict[int, int] = {}
    with open(out, "wb") as f:
        def obj(num: int, body: bytes) -> None:
            offsets[num] = f.tell()
            f.write(b"%d 0 obj\n" % num + body + b"\nendobj\n")

        f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{3 + 3 * i} 0 R" for i in range(n))
        obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
        for i, (path, w, h, cs) in enumerate(units):
            pno, ino, cno = 3 + 3 * i, 4 + 3 * i, 5 + 3 * i
            pw, ph, x, y, dw, dh = _page_box(w, h, mode)
            obj(pno, (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw:.3f} {ph:.3f}] "
                      f"/Resources << /XObject << /Im0 {ino} 0 R >> /ProcSet [/PDF /ImageB /ImageC] >> "
                      f"/Contents {cno} 0 R >>").encode())
            length = os.path.getsize(path)
            offsets[ino] = f.tell()
            f.write((f"{ino} 0 obj\n<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
                     f"/ColorSpace /{cs} /BitsPerComponent 8 /Filter /DCTDecode /Length {length} >>\n"
                     "stream\n").encode())
            with open(path, "rb") as src:
                shutil.copyfileobj(src, f, 1 << 20)
            f.write(b"\nendstream\nendobj\n")
            content = f"q {dw:.3f} 0 0 {dh:.3f} {x:.3f} {y:.3f} cm /Im0 Do Q".encode()
            obj(cno, b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        total = 3 + 3 * n
        xref = f.tell()
        f.write(b"xref\n0 %d\n0000000000 65535 f \n" % total)
        for k in range(1, total):
            f.write(b"%010d 00000 n \n" % offsets[k])
        f.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (total, xref))


def _images_to_pdf_sync(paths: list[str], out: str, mode: str, workdir: str) -> None:
    if not paths:
        raise RuntimeError("no images for PDF")
    units = [_pdf_image(p, workdir, i) for i, p in enumerate(paths)]
    _write_images_pdf(units, out, mode)


async def images_to_pdf(paths: list[str], out: str, *, mode: str = "a4", workdir: str) -> None:
    """چند عکس → یک PDF؛ `mode` = `a4` (صفحهٔ A4 با جهتِ خودکار) یا `fit` (اندازهٔ عکس)."""
    if mode not in ("a4", "fit"):
        raise ValueError(f"bad mode: {mode}")
    await asyncio.to_thread(_images_to_pdf_sync, paths, out, mode, workdir)
    if not os.path.exists(out):
        raise RuntimeError("PDF build produced no output")


# ── برچسبِ خوانا برای نامِ فایل ─────────────────────────────────
def safe_tag(s: str) -> str:
    """برای «‎-p1-3» در نامِ فایل: فقط رقم، خط‌تیره و ویرگول؛ بلند → بریده."""
    s = re.sub(r"[^0-9,\-]", "", s or "").replace(",", "_")
    return s[:24].rstrip("_-")
