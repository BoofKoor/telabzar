"""تابعِ ARQ (ورکر): دانلود (مسیرِ لوکال) → پردازش → به‌روزرسانیِ درجای کارت → پاکسازی.

عملیاتِ رسانه‌ساز (تبدیل/فشرده/تغییرنام): کارت درجا با فایلِ جدید به‌روزرسانی می‌شود.
عملیاتِ بررسی (اسکن): فقط لاگِ تغییرات + کپشن عوض می‌شود (فایل دست‌نخورده).
ناموفق: کارت به منوی اصلی + هشدار برمی‌گردد (بدونِ بن‌بست).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import shutil
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile

from . import history as H
from . import pagespec
from . import pdftext
from . import pdftools
from . import processing as P
from . import settings_store
from . import textstore
from .cards import (
    _quality_label, message_media_id, message_media_mime, meta_editor_view, move_card_below, progress_note,
    send_card, set_card_note, update_card,
)
from .config import settings
from .db import Sessionmaker
from .exceptions import UserFacingError
from .filetypes import human_size
from .i18n import t
from .keyboards import AUDIO_SPEEDS, cancel_job_kb
from .models import File, Job
from .security import ScanUnavailable, scan_file

log = logging.getLogger("telabzar.worker")

# یادداشتِ «در حالِ بررسی» در `run_screen`: چقدر صبر کنیم تا **اولین** به‌روزرسانی،
# و بعدش هر چند ثانیه. تأخیرِ اولیه از عددِ واقعی آمده نه از حس: غربالگریِ یک فایلِ
# کوچک ~۱٫۴ ثانیه طول می‌کشد (اندازه‌گیریِ ۲۰۲۶-۰۸-۱۰)، پس ۴ ثانیه با حاشیهٔ ~۳
# برابر یعنی آپلودهای عادی **هیچ** ویرایشی نمی‌گیرند و رگبارِ آلبوم به سقفِ نرخِ
# تلگرام نزدیک نمی‌شود؛ در عوض ویدیوی بزرگ که تنها `get_file`ش ۱۰٫۳ ثانیه است،
# اولین بازخورد را خیلی زودتر از پایانِ کار می‌گیرد.
_SCREEN_NOTE_DELAY = 4.0
_SCREEN_NOTE_EVERY = 5.0

# نگاشتِ عملیات → برچسبِ نوارِ پیشرفت
_PROGRESS_LABEL = {
    "compress": "pr_compress", "convert": "pr_convert",
    "to_gif": "pr_gif", "extract_audio": "pr_extract",
    "watermark": "pr_watermark", "trim": "pr_trim",
    "normalize": "pr_normalize", "speed": "pr_speed",
    "transcribe": "pr_transcribe", "scan": "pr_scan", "bg_remove": "pr_bg",
    "pdf_select": "pr_pdf", "pdf_rotate": "pr_pdf", "pdf_split": "pr_pdf",
    "pdf_lock": "pr_pdf", "pdf_unlock": "pr_pdf", "pdf_merge": "pr_pdf",
    "images_to_pdf": "pr_pdf", "to_pdf": "pr_pdf",
}


_REAL_EXT = re.compile(r"\.[A-Za-z0-9]{1,5}")


def _safe_stem(name: str | None, default: str = "file") -> str:
    """نامِ فایل بدونِ پسوند، امن برای مسیر.

    فقط پسوندِ **واقعی** برداشته می‌شود. `Path.stem` هر چیزی بعد از آخرین نقطه
    را پسوند می‌داند، پس عنوانِ بی‌پسوندی مثلِ «Mr. Brightside» یا «Track 01. Intro»
    به «Mr»/«Track 01» کوتاه می‌شد.
    """
    name = os.path.basename(name or "") or default
    base, ext = os.path.splitext(name)
    stem = base if (base and _REAL_EXT.fullmatch(ext)) else name
    stem = re.sub(r"[^\w.\-]+", "_", stem)[:60]
    return stem or default


def _img_ext(name: str | None, default: str = ".jpg") -> str:
    """پسوندِ تصویرِ خروجی — پسوندِ اصلی را نگه می‌دارد وگرنه پیش‌فرض."""
    ext = (os.path.splitext(name or "")[1] or default).lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp") else default


def _fmt_dur(seconds: float) -> str:
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fail_note(lang: str, exc: Exception) -> str:
    """پیامِ شکست + دلیلِ کوتاهِ escape‌شده — تا کاربر (و ما) بدانیم چرا."""
    reason = " ".join(str(exc).split())[:160]
    note = t(lang, "failed")
    if reason:
        note += f"\n<code>{escape(reason)}</code>"
    return note


def _user_note(lang: str, exc: UserFacingError) -> str:
    """پیامِ خودِ خطا به زبانِ کاربر؛ دلیلِ فنی (اگر هست) کوچک زیرش."""
    note = t(lang, exc.key, **exc.kw)
    if exc.detail:
        note += f"\n<code>{escape(' '.join(str(exc.detail).split())[:160])}</code>"
    return note


async def _card_below(bot: Bot, chat_id: int, card_mid: int, file: File, lang: str) -> None:
    """کارت را زیرِ خروجی ببر؛ اگر نشد همان‌جا به‌روزش کن.

    این گام بعد از تحویلِ **موفقِ** خروجی است و فقط آرایشِ چت است. پیش از فاز
    ۲ِ ممیزی بی‌گارد صدا زده می‌شد: یک خطای شبکه در `send_card` از شاخهٔ `else`ِ
    `run_op` بیرون می‌زد، `finally` جاب را با وضعیتِ **`running`** و
    `finished_at`ِ ست‌شده commit می‌کرد، و کاربر کارتی بی‌منو داشت.
    """
    try:
        await move_card_below(bot, chat_id, card_mid, file, lang, collapsed=False)
    except Exception:  # noqa: BLE001
        log.warning("moving the card below the output failed; updating in place",
                    exc_info=True)
        await set_card_note(bot, chat_id, card_mid, file, lang, keyboard=True)


#: کلیدهای نتیجهٔ `_do_op` که بایتِ تازه‌ای به تلگرام می‌فرستند. هر کلیدِ دیگری
#: (`editor`, `message`, `note_only`) فقط متن است و آپلودی ندارد.
_BYTE_KEYS = ("path", "spawn", "send_media", "files")


def _outgoing_paths(res: dict[str, Any]) -> list[str]:
    """مسیرهایی که این نتیجه قرار است به‌عنوان **بایت** بفرستد.

    تنها جایی که «کدام شکلِ خروجی آپلود می‌شود» نوشته شده. شکلِ تازه‌ای که به
    `_do_op` اضافه شود و این‌جا خوانده نشود، از گیتِ حجم رد می‌شود — برای همین
    مجموعهٔ شکل‌ها با یک تستِ کشف‌محور پین شده (`tests/test_upload_ceiling.py`)
    و افزودنِ شکلِ پنجم آن تست را قرمز می‌کند.
    """
    out: list[str] = []
    if res.get("path"):
        out.append(res["path"])
    if res.get("spawn"):
        out.append(res["spawn"]["path"])
    if res.get("send_media"):
        out.append(res["send_media"]["path"])
    out.extend(res.get("files") or [])
    return out


def _too_big_to_send(paths: list[str]) -> int | None:
    """حجمِ اولین خروجی‌ای که از سقفِ آپلود رد می‌کند (مگابایت)، وگرنه `None`.

    سقف **سیاست نیست، حدِ پلتفرم است** — سرورِ محلیِ Bot API دانلود را بی‌سقف
    می‌کند ولی آپلود را تا `UPLOAD_CEILING_MB` (`docs/telegram-api.md`). پس نه
    کلیدِ تنظیمات دارد و نه ادمین می‌تواند خاموشش کند؛ خاموش‌کردنش صرفاً یعنی
    برگشتن به شکستِ بعد از کار.
    مقایسه روی **بایت** است و گرد کردن فقط برای نمایش، وگرنه فایلِ دقیقاً روی
    مرز به گردکردن باج می‌دهد. هر آیتم جدا سنجیده می‌شود نه مجموع، چون شاخهٔ
    `files` هر فایل را با یک `send_document`ِ مستقل می‌فرستد.
    """
    limit = settings_store.UPLOAD_CEILING_MB * 1024 * 1024
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        size = os.path.getsize(p)
        if size > limit:
            return round(size / 1024 / 1024)
    return None


async def _refresh_media_meta(file: File, path: str) -> None:
    """ابعاد/مدتِ رکوردِ File را از **خروجیِ تازه** بازخوانی کن.

    تلگرام مقادیرِ `duration/width/height` را همان‌طور که ما می‌فرستیم نمایش می‌دهد و
    خودش فایل را نمی‌سنجد؛ پس اگر بعد از برش/سرعت/فشرده‌سازی/تبدیل/چسباندن این‌ها را
    به‌روز نکنیم، ویدیو با زمان و کیفیتِ **فایلِ قبلی** نشان داده می‌شود.
    """
    if not path or not os.path.exists(path):
        return
    if file.kind in ("video", "audio"):
        meta = await P.probe_media(path)
        file.duration = meta.get("duration")
        if file.kind == "video":
            file.width, file.height = meta.get("width"), meta.get("height")
        else:
            file.width = file.height = None
    elif file.kind == "image":
        try:
            from PIL import Image
            with Image.open(path) as im:
                file.width, file.height = im.width, im.height
        except Exception:  # noqa: BLE001
            pass
        file.duration = None


async def _localize(bot: Bot, file_id: str, workdir: str, subdir: str = "in") -> str | None:
    """مسیرِ محلیِ فایل را برمی‌گرداند تا پردازش رویش کار کند.

    مستر (هم‌مکان با Bot API، `is_local=True`): `get_file().file_path` خودش مسیرِ
    روی دیسکِ مشترک است → همان برگردانده می‌شود (بدونِ کپی/دانلود).
    نودِ راه‌دور (`is_local=False`): فایل روی دیسکِ محلی نیست؛ روی HTTP از Bot API
    (روی WireGuard) در `workdir` دانلود و مسیرِ محلی برگردانده می‌شود. None اگر نشد.
    این تنها نقطه‌ای است که ورودیِ راه‌دور را ممکن می‌کند؛ خروجی از قبل با آپلودِ
    multipart (FSInputFile) کار می‌کند."""
    try:
        tg = await bot.get_file(file_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("get_file failed for %s: %s", file_id, exc)
        return None
    p = tg.file_path
    if not p:
        return None
    if os.path.exists(p):  # مستر: مسیرِ دیسکِ مشترک، مستقیم
        return p
    # نود: دانلودِ راه‌دور در زیرشاخهٔ workdir (نامِ یکتا با پیشوندِ file_id تا اعضای
    # هم‌نام قاطی نشوند)
    dst_dir = os.path.join(workdir, subdir)
    os.makedirs(dst_dir, exist_ok=True)
    dest = os.path.join(dst_dir, f"{file_id[:16]}_{os.path.basename(p)}")
    try:
        await bot.download_file(p, destination=dest, timeout=600)
    except Exception as exc:  # noqa: BLE001
        log.warning("remote localize download failed for %s: %s", file_id, exc)
        return None
    return dest if os.path.exists(dest) else None


def _many_files(paths: list[str], stem: str, workdir: str, label: str) -> dict[str, Any]:
    """چند فایلِ خروجی → آلبوم (تا `ALBUM_MAX_FILES`) یا یک ZIP.

    آلبومِ تلگرام حداکثر ده سند است؛ صد صفحه یعنی ده آلبومِ پشتِ‌هم و برخورد با
    سقفِ نرخ (۴۲۹)، و کاربر هم صد فایل را یکی‌یکی ذخیره نمی‌کند. بالای سقف یک ZIP.
    """
    if len(paths) > pdftools.ALBUM_MAX_FILES:
        out = os.path.join(workdir, f"{stem}-pages.zip")
        pdftools.zip_files(paths, out)
        return {"files": [out], "label": label}
    return {"files": paths, "album": len(paths) > 1, "label": label}


def _named_pages(files: list[str], stem: str) -> list[str]:
    """`page-07.jpg`ِ pdftoppm → `<نام>-7.jpg`، تا فایل‌ها بیرون از ZIP هم معلوم باشند."""
    out: list[str] = []
    for f in files:
        m = re.search(r"-(\d+)\.(\w+)$", os.path.basename(f))
        if not m:
            out.append(f)
            continue
        dst = os.path.join(os.path.dirname(f), f"{stem}-{int(m.group(1))}.{m.group(2)}")
        os.replace(f, dst)
        out.append(dst)
    return out


async def _convert_pdf(fmt: str, stem: str, inpath: str, workdir: str, lang: str,
                       progress=None, cancel=None) -> dict[str, Any]:
    """PDF → Word / متن / تصویرِ صفحه‌ها.

    Word و متن از `pdftext` می‌آیند، نه LibreOffice و نه `pdftotext`ِ خام: LibreOffice
    **فیلترِ خروجیِ PDF→DOCX ندارد** (`no export filter`؛ PDF را در Draw باز می‌کند)
    و poppler لیگاتورِ «لا» را برعکس باز می‌کند («سلام» → «سالم») — شرحِ کامل در
    داکس‌استرینگِ `pdftext`. صفحهٔ اسکن‌شده با OCR خوانده می‌شود، تا سقفِ ادمین.

    خروجی کارتِ **تازه** است (`spawn`) و PDF سرِ جایش می‌ماند: Word و TXT سندِ
    دیگری‌اند، نه نسخهٔ ویرایش‌شدهٔ همین فایل.
    """
    src = await pdftools.prepare(inpath, workdir, cancel=cancel)
    if fmt in ("docx", "txt"):
        word = fmt == "docx"
        ocr_max = await settings_store.get_int("pdf_ocr_max_pages", settings.pdf_ocr_max_pages)
        doc = await pdftext.extract(
            src, workdir, max_pages=pdftext.DOCX_MAX_PAGES if word else pdftext.TXT_MAX_PAGES,
            ocr_max_pages=ocr_max, want_images=word, cancel=cancel, progress=progress)
        extras: list[str] = []
        if doc.ocr_pages:
            extras.append(t(lang, "cl_pdf_ocr_pages", n=doc.ocr_pages))
        if doc.total > len(doc.pages):
            extras.append(t(lang, "cl_pdf_first_pages", n=len(doc.pages), total=doc.total))
        label = " · ".join([t(lang, "cl_convert", fmt=fmt.upper()), *extras])
        if word:
            await pdftext.render_images(src, workdir, doc, cancel=cancel)
            out = os.path.join(workdir, f"{stem}.docx")
            await asyncio.to_thread(pdftext.to_docx, doc, out)
            return {"spawn": {"path": out, "name": f"{stem}.docx", "kind": "document"},
                    "label": label}
        if not pdftext.has_text(doc):
            # صفحهٔ بی‌متن که از سقفِ OCR جا ماند با «اصلاً متن ندارد» یکی نیست
            raise UserFacingError("pdf_no_text_ocr_limit" if doc.ocr_skipped else "pdf_no_text",
                                  n=doc.ocr_skipped)
        out = os.path.join(workdir, f"{stem}.txt")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(pdftext.to_text(doc))
        return {"spawn": {"path": out, "name": f"{stem}.txt", "kind": "document"}, "label": label}
    if fmt in ("jpg", "png"):
        n = await pdftools.page_count(src, cancel=cancel)
        files = await pdftools.render_pages(src, os.path.join(workdir, "pages"), fmt,
                                            n_pages=n, cancel=cancel)
        files = _named_pages(files, stem)
        label = t(lang, "cl_convert_pages", n=len(files))
        if n > len(files):
            label += " · " + t(lang, "cl_pdf_first_pages", n=len(files), total=n)
        return _many_files(files, stem, workdir, label)
    raise RuntimeError(f"unsupported pdf target: {fmt}")


#: پسوندهایی که LibreOffice واقعاً باز می‌کند. هر چیزِ دیگری («سند» در تلگرام یعنی
#: هر فایلی که عکس/ویدیو/صوت نیست — `.exe` و `.bin` هم) به‌جای خطای خامِ
#: «source file could not be loaded» پیامِ روشن می‌گیرد.
_OFFICE_EXTS = {
    ".doc", ".docx", ".docm", ".dot", ".dotx", ".odt", ".ott", ".rtf", ".wps", ".wpd",
    ".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv",
    ".ppt", ".pptx", ".pps", ".ppsx", ".odp", ".odg",
    ".html", ".htm", ".xhtml", ".txt", ".md",
}
#: وقتی نامِ فایل پسوند ندارد (تلگرام گاهی «file» می‌فرستد) پسوند از mime می‌آید —
#: LibreOffice قالب را از پسوند حدس می‌زند و بی‌پسوند باز نمی‌کند.
_OFFICE_EXT_BY_MIME = {
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/rtf": ".rtf", "text/rtf": ".rtf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "text/csv": ".csv",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "text/html": ".html", "text/plain": ".txt", "text/markdown": ".md",
}


async def _office_to_pdf(file: File, inpath: str, workdir: str, stem: str, cancel=None) -> str:
    """سند → PDF. متنِ ساده از Word رد می‌شود تا جهتِ هر پاراگراف درست باشد
    (`pdftext.text_to_docx`)؛ بقیه مستقیم به LibreOffice."""
    ext = os.path.splitext(file.name or "")[1].lower()
    if not ext:
        ext = _OFFICE_EXT_BY_MIME.get((file.mime or "").split(";")[0].strip().lower(), "")
    if ext not in _OFFICE_EXTS:
        # پسوند از نامِ فایلِ کاربر می‌آید و پیام HTML است: `a.<b>` نباید تگ شود
        raise UserFacingError("to_pdf_unsupported", ext=escape(ext[:12]) or "?")
    conv = os.path.join(workdir, "lo")
    os.makedirs(conv, exist_ok=True)
    if ext in (".txt", ".md"):
        text = pdftext.read_text_file(inpath)
        if not text.strip():
            raise UserFacingError("to_pdf_empty")
        src = os.path.join(conv, f"{stem}.docx")
        await asyncio.to_thread(pdftext.text_to_docx, text, src)
    else:
        src = os.path.join(conv, f"{stem}{ext}")
        shutil.copyfile(inpath, src)
    return await P.office_convert(src, conv, "pdf", cancel=cancel)


async def _pdf_members(bot: Bot, args: dict[str, Any], workdir: str, cancel=None) -> list[str]:
    """اعضای ادغام → PDFهای آمادهٔ qpdf. قفلِ مالک بی‌صدا برداشته می‌شود؛ عضوِ رمزدار
    نامِ خودش را در پیام می‌آورد (کاربر باید بداند **کدام** فایل)."""
    paths: list[str] = []
    for i, m in enumerate(args.get("members") or []):
        fid = m.get("file_id")
        if not fid:
            continue
        p = await _localize(bot, fid, workdir, subdir=f"m{i}")
        if not p:
            raise RuntimeError(f"member not found: {m.get('name') or fid}")
        sub = os.path.join(workdir, f"m{i}")
        os.makedirs(sub, exist_ok=True)
        try:
            paths.append(await pdftools.prepare(p, sub, cancel=cancel))
        except UserFacingError as exc:
            if exc.key in ("pdf_needs_password", "pdf_not_pdf", "pdf_damaged"):
                raise UserFacingError(f"{exc.key}_member", detail=exc.detail,
                                      name=escape(str(m.get("name") or "?"))[:60]) from None
            raise
    return paths


async def _password(redis, args: dict[str, Any]) -> str:
    """رمزِ کاربر از Redis — یک‌بارمصرف (`GETDEL`)، تا بعد از جاب جایی نماند."""
    tok = str(args.get("tok") or "")
    pw = None
    if redis is not None and tok:
        try:
            raw = await redis.getdel(pagespec.PW_KEY.format(tok=tok))
            pw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        except Exception:  # noqa: BLE001
            pw = None
    if not pw:
        raise UserFacingError("pdf_pw_expired")
    return pw


async def _do_op(bot: Bot, op: str, args: dict[str, Any], file: File, inpath: str, workdir: str,
                 lang: str, progress=None, cancel=None, redis=None) -> dict[str, Any]:
    """پردازش → یا {path, filename, label} (رسانه‌ساز) یا {note_only, label} (بررسی)."""
    stem = _safe_stem(file.name)
    dur = file.duration
    # اگر مدت نامعلوم بود (ویدیوی سند/دانلودیِ بی‌متادیتا)، ffprobe کن تا نوارِ پیشرفت
    # واقعاً کار کند (وگرنه پردازش «قفل‌شده» به‌نظر می‌رسد).
    if not dur and file.kind in ("video", "audio"):
        dur = await P.probe_duration(inpath)

    if op == "scan":
        try:
            status, name = await scan_file(inpath)
        except ScanUnavailable as exc:
            reason = " ".join(str(exc).split())[:120]
            label = t(lang, "cl_scan_unavailable")
            return {"note_only": True, "label": f"{label} — {reason}" if reason else label}
        if status == "OK":
            return {"note_only": True, "label": t(lang, "cl_scan_clean")}
        return {"note_only": True, "label": t(lang, "cl_scan_infected", name=name or "?")}

    if op == "rename":
        new = re.sub(r"[\\/\x00]+", "_", (args.get("new_name") or "file").strip())[:120] or "file"
        if not Path(new).suffix and file.name and Path(file.name).suffix:
            new += Path(file.name).suffix
        return {"path": inpath, "filename": new, "label": t(lang, "cl_rename", name=new)}

    if op == "compress":
        if file.kind == "image":
            out = os.path.join(workdir, f"{stem}-min.jpg")
            await P.compress_image(inpath, out)
        elif file.kind == "video":
            out = os.path.join(workdir, f"{stem}-min.mp4")
            enc = await settings_store.get_str("video_encoder", settings.video_encoder)
            spd = await settings_store.get_str("compress_speed", settings.compress_speed)
            if args.get("tiny"):  # حالتِ «خیلی کم‌حجم» (کلاس/جلسه)
                target = await settings_store.get_int("compress_tiny_target_mb",
                                                      settings.compress_tiny_target_mb)
                th = await settings_store.get_int("compress_tiny_height", settings.compress_tiny_height)
                await P.compress_video_tiny(inpath, out, duration=dur, target_mb=target, height=th,
                                            encoder=enc, speed=spd, progress=progress, cancel=cancel)
            else:
                await P.compress_video(inpath, out, height=args.get("height"), kbps=args.get("kbps"),
                                       progress=progress, duration=dur, cancel=cancel,
                                       encoder=enc, speed=spd)
        elif file.kind == "audio":
            out = os.path.join(workdir, f"{stem}-min.mp3")
            await P.compress_audio(inpath, out, progress=progress, duration=dur, cancel=cancel)
        elif file.kind == "pdf":
            level = "strong" if args.get("level") == "strong" else "normal"
            src = await pdftools.prepare(inpath, workdir, cancel=cancel)
            best = await pdftools.compress(src, workdir, level, cancel=cancel)
            if best is None:
                # کمتر از ۵٪ کوچک‌تر نشد: کارت را با فایلی که فقط کیفیت باخته عوض نکن
                return {"note_only": True, "label": t(lang, "cl_pdf_no_gain")}
            out = os.path.join(workdir, f"{stem}-min.pdf")
            os.replace(best, out)
            label = t(lang, "cl_pdf_compress", before=human_size(os.path.getsize(src)),
                      after=human_size(os.path.getsize(out)))
            return {"path": out, "filename": os.path.basename(out), "label": label, "kind": "pdf"}
        else:
            raise RuntimeError("compress not supported for this type")
        label = t(lang, "cl_tiny") if args.get("tiny") else t(lang, "cl_compress")
        return {"path": out, "filename": os.path.basename(out), "label": label}

    if op == "convert":
        fmt = (args.get("target") or "").lower()
        if file.kind == "pdf":
            return await _convert_pdf(fmt, stem, inpath, workdir, lang,
                                      progress=progress, cancel=cancel)
        out = os.path.join(workdir, f"{stem}.{fmt}")
        if file.kind == "image":
            await P.convert_image(inpath, out, fmt)
        elif file.kind == "audio":
            await P.convert_audio(inpath, out, fmt, progress=progress, duration=dur, cancel=cancel)
        elif file.kind == "video":
            await P.convert_video(inpath, out, fmt, progress=progress, duration=dur, cancel=cancel)
        else:
            raise RuntimeError("convert not supported for this type")
        return {"path": out, "filename": f"{stem}.{fmt}", "label": t(lang, "cl_convert", fmt=fmt.upper())}

    if op == "pdf_merge":
        paths = await _pdf_members(bot, args, workdir, cancel=cancel)
        out = os.path.join(workdir, f"{stem}-merged.pdf")
        await pdftools.merge(paths, out, cancel=cancel)
        # کارتِ تازه: پیش از این PDFِ ادغام‌شده جای **اولین** PDF را می‌گرفت و آن
        # فایل از چت «ناپدید» می‌شد.
        return {"spawn": {"path": out, "name": f"{stem}-merged.pdf", "kind": "pdf"},
                "label": t(lang, "cl_merge", n=len(paths))}

    if op == "pdf_select":
        mode = "delete" if args.get("mode") == "delete" else "keep"
        ranges = pagespec.parse(str(args.get("spec") or ""))
        if ranges is None:
            raise UserFacingError("pdf_pages_bad")
        src = await pdftools.prepare(inpath, workdir, cancel=cancel)
        n = await pdftools.page_count(src, cancel=cancel)
        try:
            pages = pagespec.expand(ranges, n)
        except ValueError as exc:
            raise UserFacingError("pdf_page_out_of_range", page=exc.args[0], n=n) from None
        if mode == "delete":
            drop = set(pages)
            keep = [p for p in range(1, n + 1) if p not in drop]
            if not keep:
                raise UserFacingError("pdf_delete_all")
            out = os.path.join(workdir, f"{stem}.pdf")
            await pdftools.select_pages(src, keep, out, cancel=cancel)
            return {"path": out, "filename": f"{stem}.pdf", "kind": "pdf",
                    "label": t(lang, "cl_pdf_deleted", pages=pagespec.label(sorted(drop)))}
        tag = pdftools.safe_tag(pagespec.label(pages))
        out = os.path.join(workdir, f"{stem}-p{tag}.pdf")
        await pdftools.select_pages(src, pages, out, cancel=cancel)
        return {"spawn": {"path": out, "name": os.path.basename(out), "kind": "pdf"},
                "label": t(lang, "cl_pdf_extracted", pages=pagespec.label(pages))}

    if op == "pdf_rotate":
        angle = int(args.get("angle") or 0)
        if angle not in (90, 180, 270):
            raise ValueError(f"unsupported angle: {angle}")
        src = await pdftools.prepare(inpath, workdir, cancel=cancel)
        out = os.path.join(workdir, f"{stem}.pdf")
        await pdftools.rotate(src, out, angle, cancel=cancel)
        return {"path": out, "filename": f"{stem}.pdf", "kind": "pdf",
                "label": t(lang, "cl_pdf_rotated", deg=angle)}

    if op == "pdf_split":
        src = await pdftools.prepare(inpath, workdir, cancel=cancel)
        n = await pdftools.page_count(src, cancel=cancel)
        if n < 2:
            raise UserFacingError("pdf_split_single")
        files = await pdftools.split(src, os.path.join(workdir, "split"), stem, cancel=cancel)
        return _many_files(files, stem, workdir, t(lang, "cl_pdf_split", n=len(files)))

    if op == "pdf_lock":
        pw = await _password(redis, args)
        src = await pdftools.prepare(inpath, workdir, cancel=cancel)
        out = os.path.join(workdir, f"{stem}.pdf")
        await pdftools.lock(src, out, pw, workdir, cancel=cancel)
        return {"path": out, "filename": f"{stem}.pdf", "kind": "pdf", "label": t(lang, "cl_pdf_locked")}

    if op == "pdf_unlock":
        pw = await _password(redis, args)
        try:
            # بی‌رمزِ کاربر (فقط محدودیتِ چاپ/کپیِ «مالک»): رمز لازم نیست و هر
            # چیزی که کاربر فرستاده کافی است — قفلِ مالک بی‌رمز برداشته می‌شود.
            src = await pdftools.prepare(inpath, workdir, cancel=cancel)
        except UserFacingError as exc:
            if exc.key != "pdf_needs_password":
                raise
            src = await pdftools.prepare(inpath, workdir, password=pw, cancel=cancel)
        else:
            if not await pdftools.is_encrypted(inpath, cancel=cancel):
                return {"note_only": True, "label": t(lang, "cl_pdf_not_locked")}
        out = os.path.join(workdir, f"{stem}.pdf")
        shutil.copyfile(src, out)   # نه replace: بی qpdf، `src` خودِ فایلِ دیسکِ Bot API است
        return {"path": out, "filename": f"{stem}.pdf", "kind": "pdf", "label": t(lang, "cl_pdf_unlocked")}

    if op == "video_concat":
        members = args.get("members") or []
        paths = []
        for m in members:
            fid = m.get("file_id")
            if not fid:
                continue
            p = await _localize(bot, fid, workdir)
            if not p:
                raise RuntimeError(f"member not found: {m.get('name') or fid}")
            paths.append(p)
        if len(paths) < 2:
            raise RuntimeError("need at least two videos to join")
        out = os.path.join(workdir, f"{stem}-joined.mp4")
        await P.concat_videos(paths, out, width=file.width, height=file.height,
                              progress=progress, cancel=cancel)
        return {"path": out, "filename": f"{stem}-joined.mp4",
                "label": t(lang, "cl_vjoin", n=len(paths)), "kind": "video"}

    if op == "zip_many":
        members = args.get("members") or []
        downloaded: list[tuple[str, str]] = []
        for m in members:
            fid = m.get("file_id")
            if not fid:
                continue
            p = await _localize(bot, fid, workdir)
            if not p:
                raise RuntimeError(f"member not found: {m.get('name') or fid}")
            downloaded.append((p, m.get("name") or os.path.basename(p)))
        if not downloaded:
            raise RuntimeError("no files to zip")
        out = os.path.join(workdir, "archive.zip")
        await P.make_zip_many(downloaded, out)
        return {"path": out, "filename": "archive.zip",
                "label": t(lang, "cl_zip_many", n=len(downloaded)), "kind": "archive"}

    if op == "meta_read":
        m = await P.audio_metadata(inpath)
        tags = m.get("tags", {})
        cur = {k: str(tags[k])[:120] for k in ("title", "artist", "album", "genre", "date") if tags.get(k)}
        return {"editor": cur}

    if op == "meta_write":
        tags = {k: str(v) for k, v in (args.get("tags") or {}).items() if v}
        cover_path = None
        cover_id = args.get("cover_id")
        if cover_id:
            cp = await _localize(bot, cover_id, workdir)
            if cp:
                cover_path = cp
        if not tags and not cover_path:
            raise RuntimeError("no metadata to write")
        # پسوند را `write_audio_metadata` از کدکِ واقعی تعیین می‌کند، نه از نام.
        out = await P.write_audio_metadata(inpath, os.path.join(workdir, stem), tags,
                                           cover_path=cover_path, cancel=cancel)
        return {"path": out, "filename": stem + os.path.splitext(out)[1],
                "label": t(lang, "cl_meta_edit"), "kind": "audio", "new_meta": tags}

    if op == "to_pdf":
        out = await _office_to_pdf(file, inpath, workdir, stem, cancel=cancel)
        # کارتِ تازه با نوعِ **pdf** (پیش از این `document` بود: کارتِ خروجی منوی سند
        # را نشان می‌داد و PDFِ تازه هیچ ابزارِ PDFی نداشت)، و سندِ اصلی سرِ جایش.
        return {"spawn": {"path": out, "name": f"{stem}.pdf", "kind": "pdf"},
                "label": t(lang, "cl_topdf")}

    if op == "list_zip":
        entries = await P.archive_list(inpath)
        lines = [t(lang, "list_header", n=len(entries))]
        for name, sz in entries[:60]:
            lines.append(f"• {escape(name)}  <code>{human_size(sz)}</code>")
        if len(entries) > 60:
            lines.append(f"… (+{len(entries) - 60})")
        return {"note_only": True, "label": t(lang, "cl_list", n=len(entries)), "message": "\n".join(lines)}

    if op == "extract":
        files = await P.archive_extract(
            inpath, workdir, settings.max_extract_files, settings.max_extract_mb * 1024 * 1024
        )
        return {"note_only": True, "label": t(lang, "cl_extract", n=len(files)), "files": files}

    if op == "extract_audio":
        out = os.path.join(workdir, f"{stem}.mp3")
        await P.extract_audio(inpath, out, "mp3", progress=progress, duration=dur, cancel=cancel)
        return {"spawn": {"path": out, "name": f"{stem}.mp3", "kind": "audio"},
                "label": t(lang, "cl_extract_audio")}

    if op == "to_gif":
        out = os.path.join(workdir, f"{stem}.gif")
        await P.video_to_gif(inpath, out, progress=progress, duration=min(dur or 6, 6), cancel=cancel)
        return {"send_media": {"as": "animation", "path": out, "filename": f"{stem}.gif"},
                "label": t(lang, "cl_gif")}

    if op == "watermark" and file.kind == "image":
        pos = args.get("pos", "br")
        out = os.path.join(workdir, f"{stem}-wm{_img_ext(file.name)}")
        if args.get("text"):
            wm = os.path.join(workdir, "wm.png")
            await P.render_text_watermark(args["text"], wm, file.height or 720)
            await P.watermark_image(inpath, out, wm, pos, is_logo=False)
        elif args.get("logo"):
            lp = await _localize(bot, args["logo"], workdir)
            if not lp:
                raise RuntimeError("logo not found")
            await P.watermark_image(inpath, out, lp, pos, is_logo=True)
        else:
            raise RuntimeError("no watermark content")
        return {"path": out, "filename": os.path.basename(out), "label": t(lang, "cl_watermark")}

    if op == "watermark":
        pos = args.get("pos", "br")
        out = os.path.join(workdir, f"{stem}-wm.mp4")
        if args.get("text"):
            wm = os.path.join(workdir, "wm.png")
            await P.render_text_watermark(args["text"], wm, file.height or 480)
            await P.watermark_video(inpath, out, wm, pos, progress=progress, duration=dur, cancel=cancel)
        elif args.get("logo"):
            lp = await _localize(bot, args["logo"], workdir)
            if not lp:
                raise RuntimeError("logo not found")
            scale_w = max(64, (file.width or 640) // 7)  # کوچک‌تر/استاندارد
            await P.watermark_video(inpath, out, lp, pos, scale_w=scale_w, opacity=0.65,
                                    progress=progress, duration=dur, cancel=cancel)
        else:
            raise RuntimeError("no watermark content")
        return {"path": out, "filename": f"{stem}.mp4", "label": t(lang, "cl_watermark")}

    if op == "mute":
        out = os.path.join(workdir, f"{stem}-mute.mp4")
        await P.mute_video(inpath, out, cancel=cancel)
        return {"path": out, "filename": f"{stem}.mp4", "label": t(lang, "cl_mute")}

    if op == "trim":
        start, end = float(args.get("start", 0)), float(args.get("end", 0))
        if file.kind == "audio":
            out = os.path.join(workdir, f"{stem}-cut.mp3")
            await P.trim_audio(inpath, out, start, end, progress=progress, cancel=cancel)
            return {"path": out, "filename": f"{stem}-cut.mp3", "label": t(lang, "cl_trim"), "kind": "audio"}
        out = os.path.join(workdir, f"{stem}-cut.mp4")
        await P.trim_video(inpath, out, start, end, progress=progress, cancel=cancel)
        return {"path": out, "filename": f"{stem}-cut.mp4", "label": t(lang, "cl_trim")}

    if op == "screenshot":
        out = os.path.join(workdir, f"{stem}-shot.jpg")
        await P.screenshot_video(inpath, out, float(args.get("ts", 0)))
        return {"send_media": {"as": "photo", "path": out, "filename": f"{stem}.jpg"},
                "label": t(lang, "cl_screenshot")}

    if op == "transcribe":
        mode = "srt" if args.get("mode") == "srt" else "txt"
        model = await settings_store.get_str("whisper_model", settings.whisper_model)
        text = (await P.transcribe_audio(inpath, model, mode, cancel=cancel)).strip()
        if not text:
            return {"note_only": True, "label": t(lang, "asr_empty")}
        if mode == "srt":  # زیرنویس همیشه به‌صورتِ فایلِ .srt
            srt = os.path.join(workdir, f"{stem}.srt")
            with open(srt, "w", encoding="utf-8") as fh:
                fh.write(text)
            return {"files": [srt], "label": t(lang, "cl_transcribe_srt")}
        if len(text) > 3000:  # متنِ بلند → فایلِ txt
            txt = os.path.join(workdir, f"{stem}-transcript.txt")
            with open(txt, "w", encoding="utf-8") as fh:
                fh.write(text)
            return {"files": [txt], "label": t(lang, "cl_transcribe")}
        return {"message": f"{t(lang, 'asr_header')}\n<blockquote expandable>{escape(text)}</blockquote>",
                "label": t(lang, "cl_transcribe")}

    if op == "normalize":
        out = os.path.join(workdir, f"{stem}-norm.mp3")
        await P.normalize_audio(inpath, out, progress=progress, duration=dur, cancel=cancel)
        return {"path": out, "filename": f"{stem}.mp3", "label": t(lang, "cl_normalize"), "kind": "audio"}

    if op == "speed":
        # `rate` از callbackِ کاربر می‌آید (رشتهٔ آزاد)، پس فقط ضریب‌هایی که خودِ
        # ربات پیشنهاد داده پذیرفته می‌شوند. بدونِ این، `rate="-1"` یا `"1e999"`
        # حلقهٔ همگامِ `_atempo_chain` را واگرا می‌کرد و کلِ ورکر را می‌خواباند.
        raw = str(args.get("rate", "1"))
        if raw not in AUDIO_SPEEDS:
            raise ValueError(f"unsupported speed rate: {raw[:20]}")
        rate = float(raw)
        out = os.path.join(workdir, f"{stem}-x{args.get('rate', '1')}.mp3")
        await P.speed_audio(inpath, out, rate, progress=progress, duration=dur, cancel=cancel)
        return {"path": out, "filename": os.path.basename(out),
                "label": t(lang, "cl_speed", rate=str(args.get("rate", "1")).rstrip("0").rstrip(".")),
                "kind": "audio"}

    if op == "ocr":
        text = (await P.ocr_image(inpath, workdir)).strip()
        if not text:
            return {"note_only": True, "label": t(lang, "ocr_empty")}
        if len(text) > 3000:  # متنِ بلند → فایلِ txt (سقفِ پیامِ تلگرام)
            txt = os.path.join(workdir, f"{stem}-ocr.txt")
            with open(txt, "w", encoding="utf-8") as fh:
                fh.write(text)
            return {"files": [txt], "label": t(lang, "cl_ocr")}
        body = escape(text)
        return {"message": f"{t(lang, 'ocr_header')}\n<blockquote expandable>{body}</blockquote>",
                "label": t(lang, "cl_ocr")}

    if op == "resize":
        out = os.path.join(workdir, f"{stem}-resized{_img_ext(file.name)}")
        w = await P.resize_image(inpath, out, args.get("w", "half"))
        return {"path": out, "filename": os.path.basename(out), "label": t(lang, "cl_resize", w=w)}

    if op == "rotate":
        out = os.path.join(workdir, f"{stem}-rot{_img_ext(file.name)}")
        await P.rotate_image(inpath, out, args.get("mode", "cw"))
        return {"path": out, "filename": os.path.basename(out), "label": t(lang, "cl_rotate")}

    if op == "enhance":
        out = os.path.join(workdir, f"{stem}-hd{_img_ext(file.name)}")
        await P.enhance_image(inpath, out)
        return {"path": out, "filename": os.path.basename(out), "label": t(lang, "cl_enhance")}

    if op == "bg_remove":
        # خروجی PNGِ شفاف است؛ به‌صورتِ «سند» تحویل می‌دهیم تا آلفا حفظ شود
        # (کارتِ عکس آن را به JPEG تخت می‌کرد).
        out = os.path.join(workdir, f"{stem}-nobg.png")
        await P.remove_background(inpath, out, cancel=cancel)
        return {"send_media": {"as": "document", "path": out, "filename": f"{stem}-nobg.png"},
                "label": t(lang, "cl_bg_remove")}

    if op == "images_to_pdf":
        members = args.get("members") or []
        paths: list[str] = []
        for i, m in enumerate(members):
            fid = m.get("file_id")
            if not fid:
                continue
            p = await _localize(bot, fid, workdir, subdir=f"m{i}")
            if not p:
                raise RuntimeError(f"member not found: {m.get('name') or fid}")
            paths.append(p)
        if not paths:
            raise RuntimeError("no images for PDF")
        mode = "fit" if args.get("mode") == "fit" else "a4"
        out = os.path.join(workdir, f"{stem}.pdf")
        await pdftools.images_to_pdf(paths, out, mode=mode, workdir=workdir)
        return {"spawn": {"path": out, "name": f"{stem}.pdf", "kind": "pdf"},
                "label": t(lang, "cl_img_pdf", n=len(paths))}

    raise RuntimeError(f"unknown op: {op}")


async def _send_files(bot: Bot, chat_id: int, paths: list[str], *,
                      album: bool, sent: list | None = None) -> tuple[int, Exception | None]:
    """فایل‌ها → چت. `(تعدادِ نرسیده, آخرین خطا)`. `sent` اگر داده شود پیام‌های
    رسیده را به ترتیب جمع می‌کند — تاریخچه از همان‌ها `file_id` برمی‌دارد.

    با `album` ده‌تا‌ده‌تا یک آلبومِ سند (صفحه‌های PDF، هر صفحه یک PDF) — بیست
    پیامِ پشتِ‌هم هم چت را می‌پوشاند و هم به سقفِ نرخ نزدیک می‌شود. آلبومی که
    رد شود (۴۰۰، یا ۴۲۹ دو بار) فایل‌به‌فایل فرستاده می‌شود: شکستِ گروه نباید ده
    فایل را با هم ببرد. بدونِ `album` همان رفتارِ قبلی: هر فایل یک پیام.
    """
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.types import InputMediaDocument

    failed_n, last_exc = 0, None

    async def one(p: str) -> None:
        nonlocal failed_n, last_exc
        try:
            msg = await bot.send_document(chat_id, FSInputFile(p, filename=os.path.basename(p)))
            if sent is not None:
                sent.append(msg)
        except Exception as exc:  # noqa: BLE001
            failed_n, last_exc = failed_n + 1, exc
            log.warning("sending output file failed: %s", p)

    if not album or len(paths) < 2:
        for p in paths:
            await one(p)
        return failed_n, last_exc
    for i in range(0, len(paths), 10):
        chunk = paths[i:i + 10]
        if len(chunk) == 1:
            await one(chunk[0])
            continue
        media = [InputMediaDocument(media=FSInputFile(p, filename=os.path.basename(p)))
                 for p in chunk]
        for attempt in (1, 2):
            try:
                msgs = await bot.send_media_group(chat_id, media)
                if sent is not None and isinstance(msgs, list):
                    sent.extend(msgs)
                break
            except TelegramRetryAfter as exc:
                if attempt == 1:
                    await asyncio.sleep(min(float(exc.retry_after), 30.0))
                    continue
                log.warning("album rate-limited twice; sending one by one")
            except Exception:  # noqa: BLE001
                log.warning("album send failed; sending one by one", exc_info=True)
            for p in chunk:
                await one(p)
            break
    return failed_n, last_exc


async def run_op(ctx: dict, job_id: int, chat_id: int, card_mid: int, lang: str) -> None:
    bot: Bot = ctx["bot"]
    await textstore.refresh_if_stale()  # متن‌های ادمین‌ویرایش‌شده تازه بمانند
    workdir = os.path.join(settings.work_dir, str(job_id))

    async with Sessionmaker() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        file = await session.get(File, job.file_id)
        if file is None:
            job.status = "failed"
            job.error = "file record missing"
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
            return

        job.status = "running"
        await session.commit()
        # خروجیِ تازه‌ای که رسید (پیام‌ها، نام‌ها) — بعد از commitِ جاب به تاریخچه می‌رود.
        remember: tuple[list, list | None] | None = None

        try:
            os.makedirs(workdir, exist_ok=True)
            # مستر: مسیرِ دیسکِ مشترک · نود: دانلودِ راه‌دور روی HTTP (رجوع به _localize)
            inpath = await _localize(bot, file.file_id, workdir)
            if not inpath:
                # نسبی/دانلودِ ناموفق → یا سرور local نیست، یا mount/پرمیشن/دسترسیِ نود
                raise RuntimeError("input file not available (disk miss / remote download failed)")

            # وضعیتِ زنده: یک «تیک‌زن» پس‌زمینه هر ~۴ ثانیه کارت را به‌روز می‌کند —
            # همیشه اسپینرِ چرخان + زمانِ سپری‌شده (و درصد اگر معلوم باشد). اینطوری هیچ
            # عملیاتی «قفل‌شده» به‌نظر نمی‌رسد، حتی آن‌هایی که درصد نمی‌دهند (اسکن/رونویسی).
            plabel = t(lang, _PROGRESS_LABEL.get(job.op, "processing"))
            # کاهشِ حجمِ ویدیو → کیفیتِ تشخیص‌داده‌شده را در برچسب فاش کن (۴۸۰p/۷۲۰p…)
            if job.op == "compress" and file.kind == "video":
                q = _quality_label(file.width, file.height)
                if q:
                    plabel = f"{plabel} · {q}"
            # آیا این عملیات درصدِ زنده می‌دهد؟ اگر بله ابتدا فازِ «سنجش» و با رسیدنِ اولین
            # درصد سوییچ به برچسبِ کار؛ اگر نه، از همان اول برچسبِ کار (اسپینر زنده است).
            reports_pct = (
                (job.op in ("compress", "convert") and file.kind in ("video", "audio"))
                or (job.op in ("to_gif", "extract_audio", "watermark") and file.kind == "video")
                or (job.op in ("normalize", "speed") and file.kind == "audio")
                or (job.op == "trim" and file.kind in ("audio", "video"))
            )
            pstate = {"pct": None, "eta": None,
                      "label": t(lang, "pr_analyzing") if reports_pct else plabel}
            pstart = time.monotonic()
            cancel_kb = cancel_job_kb(job_id, lang)
            redis = ctx.get("redis")

            async def _on_progress(pct: float) -> None:
                pstate["pct"] = pct
                elapsed = time.monotonic() - pstart
                pstate["eta"] = (elapsed / pct * (100 - pct)) if pct > 3 else None
                pstate["label"] = t(lang, "pr_almost") if pct >= 95 else plabel

            async def _ticker() -> None:
                tick = 0
                while True:
                    await asyncio.sleep(4.0)
                    tick += 1
                    # ایمنی: عملیاتِ درصددار که چند ثانیه درصدی نداد از «سنجش» به کار برود
                    if reports_pct and pstate["pct"] is None and tick >= 2:
                        pstate["label"] = plabel
                    try:
                        await set_card_note(
                            bot, chat_id, card_mid, file, lang,
                            note=progress_note(pstate["label"], pstate["pct"], pstate["eta"],
                                               time.monotonic() - pstart, tick),
                            keyboard=cancel_kb)
                    except Exception:  # noqa: BLE001
                        pass

            async def _should_cancel() -> bool:
                if redis is None:
                    return False
                try:
                    return bool(await redis.exists(f"cancel:{job_id}"))
                except Exception:  # noqa: BLE001
                    return False

            # فیدبکِ فوری (قبل از اولین تیک) تا کاربر بداند کار شروع شد
            try:
                await set_card_note(bot, chat_id, card_mid, file, lang,
                                    note=progress_note(pstate["label"], None, None, 0, 0),
                                    keyboard=cancel_kb)
            except Exception:  # noqa: BLE001
                pass

            ticker = asyncio.create_task(_ticker())
            try:
                res = await _do_op(bot, job.op, job.args or {}, file, inpath, workdir, lang,
                                   progress=_on_progress, cancel=_should_cancel, redis=redis)
            finally:
                await P.stop_task(ticker)   # لغوِ خودِ جاب را نمی‌بلعد
        except P.ProcessingCancelled:
            log.info("job %s cancelled by user", job_id)
            job.status = "cancelled"
            await set_card_note(bot, chat_id, card_mid, file, lang, note=t(lang, "cancelled"), keyboard=True)
        except UserFacingError as exc:
            # شکستی که پیامِ خودش را دارد («این PDF رمز دارد»…): نه traceback در لاگ و
            # نه دُمِ خامِ انگلیسیِ ابزار. `job.error` همان کلید است تا صفحهٔ آمار
            # همهٔ نمونه‌ها را یک ردیف بشمارد.
            log.info("job %s refused: %s", job_id, exc.key)
            job.status = "failed"
            job.error = exc.key[:500]
            await set_card_note(bot, chat_id, card_mid, file, lang, note=_user_note(lang, exc), keyboard=True)
        except Exception as exc:  # noqa: BLE001  — پردازش شکست خورد؛ فایل دست‌نخورده
            log.exception("job %s processing failed", job_id)
            job.status = "failed"
            job.error = str(exc)[:500]
            await set_card_note(bot, chat_id, card_mid, file, lang, note=_fail_note(lang, exc), keyboard=True)
        else:
            # ── پرتگاهِ آپلود ────────────────────────────────────────────
            # دریافت سقف ندارد (سرورِ محلیِ Bot API) ولی آپلود دارد، پس عملیاتی
            # که خروجیِ تازه می‌سازد می‌تواند کارش را **تمام کند** و بعد سرِ
            # ارسال بشکند: کاربر منتظر مانده، CPU و دیسک خرج شده، و چیزی که
            # می‌گیرد یک خطای خامِ انگلیسی است.
            #
            # گیت عمداً **یکی** است و پیش از کلِ زنجیرهٔ تحویل می‌نشیند، نه چهار
            # چکِ پراکنده در چهار شاخه. سه چیز را رایگان می‌دهد که نسخهٔ پراکنده
            # نمی‌داد: پیش از دست‌خوردنِ فیلدهای `file` اجرا می‌شود (پس rollback
            # لازم ندارد)، پیش از `session.add(newf)`ِ شاخهٔ spawn (پس ردیفِ
            # یتیمِ `files` با `file_id=""` ساخته نمی‌شود)، و یک نقطهٔ واحد برای
            # گارد.
            #
            # چرا بعد از تولید و نه پیش از آن: رابطهٔ ورودی→خروجی به op بستگی
            # دارد. `compress` کوچک می‌کند، `convert` می‌تواند **بزرگ** کند،
            # `rename` عیناً همان حجم را می‌دهد. تنها عددِ قطعی روی دیسک است.
            oversize_mb = _too_big_to_send(_outgoing_paths(res))
            if oversize_mb is not None:
                cap = settings_store.UPLOAD_CEILING_MB
                log.warning("job %s output %sMB exceeds the %sMB upload ceiling",
                            job_id, oversize_mb, cap)
                job.status = "failed"
                # عمداً **بدونِ** حجمِ خروجی: صفحهٔ آمار خطاها را با متنِ دقیقشان
                # گروه می‌کند (`admin_web`, حلقهٔ `err_rows`)، پس عددِ متغیر یعنی
                # هر ردِ حجمی یک کلیدِ یکتا با شمارِ ۱ — و این کلاس هرگز در
                # «پرتکرارترین خطاها» بالا نمی‌آید. عدد آن‌جایی می‌ماند که به
                # آن نیاز است: پیامِ کاربر و خطِ لاگ (که job_id هم دارد).
                job.error = f"output exceeds the {cap}MB upload limit"
                # `file` دست‌نخورده است (هیچ فیلدی هنوز عوض نشده) و changelog هم
                # چیزی ادعا نمی‌کند — کارت همان فایلِ اصلی را نگه می‌دارد.
                await set_card_note(bot, chat_id, card_mid, file, lang,
                                    note=t(lang, "op_too_large", mb=oversize_mb, cap=cap),
                                    keyboard=True)
            elif res.get("spawn") is not None:
                # عملیاتی که یک فایلِ جدید می‌زاید (استخراجِ صدا) → کارتِ مستقلِ جدید
                sp = res["spawn"]
                p = sp["path"]
                newf = File(
                    ref=secrets.token_urlsafe(6)[:8], owner_id=file.owner_id,
                    file_unique_id="", file_id="", kind=sp["kind"], mime=None,
                    name=sp["name"], size=os.path.getsize(p) if os.path.exists(p) else None,
                    # «op» = زادهٔ یک عملیات — نه آپلودِ کاربر، نه دانلود. بدونِ این
                    # برچسب پنل این ردیف‌ها را «آپلود» می‌شمرد.
                    changelog=[], source="op",
                )
                await _refresh_media_meta(newf, p)  # مدت/ابعاد از خودِ فایل (وگرنه ۰:۰۰)
                # ردیف **پیش از** ارسال commit می‌شود تا دکمه‌های کارتِ تازه از همان
                # لحظه کار کنند (هندلرها با `ref` دنبالِ ردیف می‌گردند).
                session.add(newf)
                await session.commit()
                try:
                    thumb = None
                    if newf.kind == "video":
                        poster = os.path.join(workdir, "spawn-poster.jpg")
                        if await P.video_poster(p, poster):
                            thumb = FSInputFile(poster)
                    sent = await send_card(bot, chat_id, newf, lang, path=p, thumb=thumb)
                    fid, fuid = message_media_id(sent)
                    if fid:
                        newf.file_id = fid
                    if fuid:
                        newf.file_unique_id = fuid
                    newf.mime = message_media_mime(sent, newf.name)
                except Exception as exc:  # noqa: BLE001
                    # پیش از فاز ۲ِ ممیزی این‌جا فقط لاگ می‌شد و جاب `done` می‌گرفت،
                    # برچسب در changelog می‌نشست و ردیفِ `files` با `file_id=""` یتیم
                    # می‌ماند — موفقیتِ کاذب برای فایلی که هرگز نرسید.
                    log.exception("job %s spawn-card send failed", job_id)
                    await session.delete(newf)
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    await set_card_note(bot, chat_id, card_mid, file, lang,
                                        note=_fail_note(lang, exc), keyboard=True)
                else:
                    file.changelog = list(file.changelog or []) + [res["label"]]
                    await set_card_note(bot, chat_id, card_mid, file, lang, keyboard=True)
                    job.status = "done"
            elif res.get("editor") is not None:
                # خواندنِ متادیتای فعلی → ذخیره روی فایل و رندرِ ویرایشگر درجا
                file.meta = res["editor"]
                caption, kb = meta_editor_view(file, lang, {})
                try:
                    await bot.edit_message_caption(chat_id=chat_id, message_id=card_mid,
                                                   caption=caption, reply_markup=kb)
                except Exception:  # noqa: BLE001
                    log.warning("meta_read caption update failed")
                job.status = "done"
            elif res.get("send_media") is not None:
                # آرتیفکتِ رسانه‌ایِ جدا (GIF/تامبنیل) → خروجی بالا، کارتِ تازه پایین
                sm = res["send_media"]
                p = sm["path"]
                src = FSInputFile(p, filename=sm.get("filename") or os.path.basename(p))
                try:
                    if sm["as"] == "animation":
                        out_msg = await bot.send_animation(chat_id, src)
                    elif sm["as"] == "photo":
                        out_msg = await bot.send_photo(chat_id, src)
                    else:
                        out_msg = await bot.send_document(chat_id, src)
                except Exception as exc:  # noqa: BLE001  — تحویل شکست خورد؛ بدونِ بن‌بست
                    log.exception("job %s artifact delivery failed", job_id)
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    await set_card_note(bot, chat_id, card_mid, file, lang, note=_fail_note(lang, exc), keyboard=True)
                else:
                    # جابه‌جاییِ کارت بیرونِ `try`: خروجی رسیده، پس شکستِ آرایشِ چت
                    # نباید جاب را «ناموفق» بخواند.
                    file.changelog = list(file.changelog or []) + [res["label"]]
                    await _card_below(bot, chat_id, card_mid, file, lang)
                    job.status = "done"
                    remember = ([out_msg], [sm.get("filename")])
            elif res.get("files") is not None:
                # خروجیِ چندفایلی (استخراج) → فایل‌ها بالا، کارتِ تازه پایین (چت تمیز)
                # هر فایل جدا فرستاده می‌شود و شکستِ یکی بقیه را متوقف نمی‌کند؛ ولی
                # جاب فقط وقتی `done` است که **همه** رسیده باشند. پیش از فاز ۲ِ ممیزی
                # شکست‌ها فقط لاگ می‌شدند و جاب حتی با صفر فایلِ رسیده `done` می‌گرفت.
                out_msgs: list = []
                failed_n, last_exc = await _send_files(bot, chat_id, res["files"],
                                                       album=bool(res.get("album")),
                                                       sent=out_msgs)
                if failed_n:
                    total_n = len(res["files"])
                    job.status = "failed"
                    job.error = f"{failed_n} of {total_n} files not sent: {last_exc}"[:500]
                    await set_card_note(
                        bot, chat_id, card_mid, file, lang, keyboard=True,
                        note=_fail_note(lang, RuntimeError(
                            f"{failed_n}/{total_n} not sent: {last_exc}")))
                else:
                    file.changelog = list(file.changelog or []) + [res["label"]]
                    await _card_below(bot, chat_id, card_mid, file, lang)
                    job.status = "done"
                    remember = (out_msgs, None)
            elif res.get("message") is not None:
                # نتیجهٔ متنی (لیستِ آرشیو) → پیام بالا، کارتِ تازه پایین
                try:
                    await bot.send_message(chat_id, res["message"])
                except Exception as exc:  # noqa: BLE001
                    log.warning("sending listing failed")
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    await set_card_note(bot, chat_id, card_mid, file, lang,
                                        note=_fail_note(lang, exc), keyboard=True)
                else:
                    file.changelog = list(file.changelog or []) + [res["label"]]
                    await _card_below(bot, chat_id, card_mid, file, lang)
                    job.status = "done"
            elif res.get("note_only"):
                # عملیاتِ بررسی (اسکن) → فقط لاگ + کپشن؛ رسانه دست‌نخورده، درجا
                file.changelog = list(file.changelog or []) + [res["label"]]
                await set_card_note(bot, chat_id, card_mid, file, lang, keyboard=True)
                job.status = "done"
            else:
                # عملیاتِ رسانه‌ساز → فیلدهای فایل را عوض کن و کارت را درجا به‌روزرسانی کن
                orig = (file.name, file.size, file.kind, list(file.changelog or []),
                        file.width, file.height, file.duration, file.mime)
                # نسخهٔ پیش از این عملیات — برای «نسخه‌های قبلی»ِ تاریخچه. بی این، فایلِ
                # اصل برای همیشه می‌رفت: پیامِ آپلودی پاک شده و ردیف بازنویسی می‌شود.
                # برخلافِ ردیف‌های تاریخچه (`remember`) عمداً در **همان** تراکنشِ
                # بازنویسی است: جدا، `file_id` می‌توانست عوض شود و نسخهٔ اصل ثبت نشود.
                # خطرش هم کم است — همهٔ مقدارها از خودِ ردیفِ `File` با همان عرضِ ستون‌اند.
                before = dict(file_id=file.file_id, file_unique_id=file.file_unique_id,
                              kind=file.kind, mime=file.mime, name=file.name, size=file.size,
                              width=file.width, height=file.height, duration=file.duration,
                              changelog=list(file.changelog or []))
                outpath = res["path"]
                file.name = res["filename"]
                if res.get("kind"):
                    file.kind = res["kind"]
                if os.path.exists(outpath):
                    file.size = os.path.getsize(outpath)
                # ابعاد/مدتِ **خروجی** را از خودِ فایل بخوان. تلگرام هرچه بدهیم باور می‌کند،
                # پس بدونِ این، برش/سرعت/فشرده‌سازی زمان و کیفیتِ فایلِ قبلی را نشان می‌دهد
                # (ویدیوی ۳۰ ثانیه‌ایِ برش‌خورده با زمانِ ۱۰:۰۰ اصل).
                await _refresh_media_meta(file, outpath)
                file.changelog = list(file.changelog or []) + [res["label"]]
                # مرحلهٔ آپلود را برای فایلِ سنگین (ویدیو/صوت) نشان بده — آپلود به سرورِ
                # لوکالِ Bot API طول می‌کشد و بدونِ این «قفل‌شده» به‌نظر می‌رسد.
                if file.kind in ("video", "audio"):
                    try:
                        await set_card_note(bot, chat_id, card_mid, file, lang,
                                            note=progress_note(t(lang, "pr_uploading"),
                                                               None, None, None, 0),
                                            keyboard=False)
                    except Exception:  # noqa: BLE001
                        pass
                # کاورِ ویدیو بعد از پردازش نپرد: یک پوسترِ ≤۳۲۰px بساز و به‌عنوان تامبنیل بده
                thumb = None
                if file.kind == "video" and os.path.exists(outpath):
                    poster = os.path.join(workdir, "poster.jpg")
                    if await P.video_poster(outpath, poster):
                        thumb = FSInputFile(poster)
                try:
                    sent = await update_card(bot, chat_id, card_mid, file, lang, path=outpath,
                                         thumb=thumb, collapsed=False)
                    fid, fuid = message_media_id(sent)
                    if fid:
                        file.file_id = fid
                    if fuid:
                        file.file_unique_id = fuid
                    # mime همان بایت‌های تازه: بدونِ این، گیت‌وی PDFِ تبدیل‌شده به TXT را
                    # هنوز با `application/pdf` سرو می‌کرد (موردِ ۱۴).
                    file.mime = message_media_mime(sent, file.name)
                    if res.get("new_meta"):  # متادیتای فعلی را با تگ‌های نوشته‌شده به‌روز کن
                        file.meta = {**(file.meta or {}), **res["new_meta"]}
                    job.status = "done"
                    if fid and fid != before["file_id"]:
                        session.add(H.version_row(file.id, **before))
                    H.touch(file)
                except Exception as exc:  # noqa: BLE001  — تحویل شکست خورد؛ فایل را برگردان
                    log.exception("job %s delivery failed", job_id)
                    (file.name, file.size, file.kind, file.changelog,
                     file.width, file.height, file.duration, file.mime) = orig
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    await set_card_note(bot, chat_id, card_mid, file, lang, note=_fail_note(lang, exc), keyboard=True)
        finally:
            redis = ctx.get("redis")
            if redis is not None:
                try:
                    await redis.delete(f"cancel:{job_id}")  # پرچمِ لغو را پاک کن
                except Exception:  # noqa: BLE001
                    pass
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
            shutil.rmtree(workdir, ignore_errors=True)
            if settings.node_role:  # مشاهده‌پذیری: کارِ انجام‌شدهٔ این نود را بشمار
                from . import nodes
                nodes.note_job_done()
        if remember is not None:
            # تاریخچه **بعد از** commitِ جاب و در نشستِ خودش (`record_safely` خطا را
            # می‌بلعد): ردیفِ تاریخچه‌ای که به هر دلیلی نوشته نشود نباید وضعیتِ جابی را
            # که خروجی‌اش رسیده بشکند — در همان تراکنش، یک خطای DB جاب را `running` جا
            # می‌گذاشت. بهایش این است که اگر پروسه دقیقاً بینِ دو commit بمیرد، یک خروجی
            # در تاریخچه نمی‌آید؛ بهترین‌تلاش است، مثلِ مسیرِ دانلود.
            msgs, names = remember
            await H.record_safely(file.owner_id, H.infos_of(msgs), source="op", names=names)


async def run_screen(ctx: dict, payload: dict) -> None:
    """گیتِ محتوای بزرگسال برای **فایلِ آپلودیِ کاربر** — قبل از ساختنِ کارت.

    چرا در ورکر و نه در ربات: بارگذاری/اجرای مدل کارِ CPU است و نباید حلقهٔ
    long-pollingِ ربات را بگیرد.

    چرا **قبل** از کارت و نه بعدش — و مکانیزمش را دقیق بگوییم چون آیندگان روی
    همین تصمیم می‌گیرند: کارتِ فایلِ آپلودی با **`file_id`** فرستاده می‌شود
    (`cards.py:188`)، یعنی تلگرام سمتِ خودش کپی می‌کند و رباتْ **هیچ بایتی
    آپلود نمی‌کند**. پس ریسک پهنای‌باند نیست، **انتساب** است: پیامی که آن محتوا
    را دارد از حسابِ ربات فرستاده شده و از دیدِ مدیریتِ تلگرام ربات آن را پست
    کرده. همین کافی است که گیت قبل از کارت باشد نه بعدش.

    هر شکستی (مدل نبود، دانلود نشد) = «مجاز»، چون فیلتر نباید سرویس را بخورد.
    """
    from . import safety
    bot: Bot = ctx["bot"]
    await textstore.refresh_if_stale()
    file_id_row, chat_id = payload["file_id_row"], payload["chat_id"]
    note_mid, lang = payload.get("note_mid"), payload["lang"]
    tg_user_id = payload.get("tg_user_id") or 0
    workdir = os.path.join(settings.work_dir, f"scr-{secrets.token_urlsafe(6)[:8]}")

    async def _drop_note() -> None:
        if note_mid:
            try:
                await bot.delete_message(chat_id, note_mid)
            except Exception:  # noqa: BLE001
                pass

    phase = "fetch"
    started = time.monotonic()

    async def _ticker() -> None:
        """برچسبِ فاز + ثانیهٔ سپری‌شده روی همان یادداشتِ «در حالِ بررسی».

        **تأخیرِ اولیه عمدی است.** اندازه‌گیری: فایلِ کوچک در ~۱٫۴ ثانیه کامل
        غربال می‌شود، پس ticker از ثانیهٔ صفر یعنی اکثریتِ مطلقِ آپلودها یک
        ویرایشِ بی‌فایده می‌گیرند — و در رگبارِ آلبوم (ده آپلودِ هم‌زمان) به
        سقفِ نرخِ تلگرام نزدیک می‌شویم. با `_SCREEN_NOTE_DELAY` فایل‌های سریع
        **هیچ** ویرایشی نمی‌گیرند و فقط موردی که واقعاً کند است پیشرفت می‌بیند.

        **درصد نمی‌سازیم.** تقسیمِ زمان اندازه‌گیری شده است: دریافتِ فایل ۱۰٫۳
        ثانیه، استخراجِ فریم ۱٫۱، استنتاج ۰٫۳ — یعنی کار عملاً یک انتظارِ شبکه
        است و شمارندهٔ فریم یا درصدِ ساختگی چیزی به کاربر نمی‌گوید. فقط
        «کجاییم» و «چقدر گذشته».
        """
        await asyncio.sleep(_SCREEN_NOTE_DELAY)
        while True:
            try:
                # kwarg، نه موضعی: پارامترِ **دومِ** `edit_message_text` در aiogram
                # `business_connection_id` است نه `chat_id` (بی‌شباهت به بقیهٔ
                # متدها). فرمِ موضعی یک `ValidationError` می‌دهد که همین `except`
                # می‌بلعدش — یعنی ticker بی‌صدا هیچ‌وقت شلیک نمی‌کرد.
                await bot.edit_message_text(
                    text=t(lang, f"nsfw_phase_{phase}", s=int(time.monotonic() - started)),
                    chat_id=chat_id, message_id=note_mid)
            except Exception:  # noqa: BLE001 — ویرایشِ ناموفق نباید غربالگری را بشکند
                pass
            await asyncio.sleep(_SCREEN_NOTE_EVERY)

    why, pol, ticker = "", None, None
    try:
        async with Sessionmaker() as session:
            file = await session.get(File, file_id_row)
        if file is None:
            await _drop_note()
            return
        pol = await safety.load_policy()
        if pol.enabled and pol.scan_pixels:
            os.makedirs(workdir, exist_ok=True)
            if note_mid:
                ticker = asyncio.create_task(_ticker())
            local = await _localize(bot, file.file_id, workdir)
            if local:
                phase = "scan"
                hit, score, label = await safety.scan_file(
                    local, file.kind, pol.threshold, pol.frames, workdir)
                if hit:
                    why = f"pixel:{label}:{score:.2f}"
    except Exception:  # noqa: BLE001
        log.warning("screen failed for file row %s", file_id_row, exc_info=True)
    finally:
        # پاک‌سازیِ دیسک اول: `stop_task` می‌تواند لغوِ خودِ جاب را بالا بدهد
        # (درسِ ۲-۷)، و آن‌وقت خطِ بعدی اجرا نمی‌شد.
        shutil.rmtree(workdir, ignore_errors=True)
        await P.stop_task(ticker)     # لغوِ خودِ جاب را نمی‌بلعد

    if not why:                       # پاک است → همان کارتِ همیشگی
        await _drop_note()
        async with Sessionmaker() as session:
            file = await session.get(File, file_id_row)
            if file is not None:
                await send_card(bot, chat_id, file, lang)
                # تا این‌جا در تاریخچه پنهان بود (`routers/files.py`): تاریخچه فقط چیزی
                # را دوباره می‌فرستد که ربات خودش فرستاده، نه آپلودِ غربال‌نشده.
                H.release_after_screen(file)
                await session.commit()
        return

    log.info("nsfw blocked upload (%s) from %s", why, tg_user_id)
    async with Sessionmaker() as session:   # ردیفِ فایل نباید بماند
        file = await session.get(File, file_id_row)
        if file is not None:
            await session.delete(file)
            await session.commit()
    # کاربر **باید** بفهمد چرا فایلش ناپدید شد. تا امروز نمی‌فهمید: فراخوانیِ
    # موضعیِ زیر همیشه `ValidationError` می‌داد (پارامترِ دومِ aiogram
    # `business_connection_id` است)، `except` می‌گرفتش، یادداشت پاک می‌شد و
    # شاخهٔ `else` هم اجرا نمی‌شد چون `note_mid` وجود دارد — یعنی حذفِ بی‌صدای
    # فایل بدونِ هیچ توضیحی. حالا ویرایش fallback به ارسال دارد.
    blocked = t(lang, "nsfw_blocked")
    told = False
    if note_mid:
        try:
            await bot.edit_message_text(text=blocked, chat_id=chat_id, message_id=note_mid)
            told = True
        except Exception:  # noqa: BLE001
            await _drop_note()
    if not told:
        try:
            await bot.send_message(chat_id, blocked)
        except Exception:  # noqa: BLE001
            log.warning("could not tell %s their upload was blocked", tg_user_id)
    banned = await safety.report_block(bot, ctx.get("redis"), tg_user_id, why, pol,
                                       detail=f"فایلِ آپلودی · {file_id_row}")
    if banned:
        try:
            await bot.send_message(chat_id, t(lang, "nsfw_user_blocked"))
        except Exception:  # noqa: BLE001
            pass
