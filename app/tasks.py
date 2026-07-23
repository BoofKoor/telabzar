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

from . import processing as P
from . import settings_store
from . import textstore
from .cards import (
    _quality_label, message_media_id, meta_editor_view, move_card_below, progress_note,
    send_card, set_card_note, update_card,
)
from .config import settings
from .db import Sessionmaker
from .filetypes import human_size
from .i18n import t
from .keyboards import cancel_job_kb
from .models import File, Job
from .security import ScanUnavailable, scan_file

log = logging.getLogger("telabzar.worker")

# نگاشتِ عملیات → برچسبِ نوارِ پیشرفت
_PROGRESS_LABEL = {
    "compress": "pr_compress", "convert": "pr_convert",
    "to_gif": "pr_gif", "extract_audio": "pr_extract",
    "watermark": "pr_watermark", "trim": "pr_trim",
    "normalize": "pr_normalize", "speed": "pr_speed",
    "transcribe": "pr_transcribe", "scan": "pr_scan", "bg_remove": "pr_bg",
}


def _safe_stem(name: str | None, default: str = "file") -> str:
    stem = Path(name or default).stem or default
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


async def _convert_pdf(fmt: str, stem: str, inpath: str, workdir: str, lang: str) -> dict[str, Any]:
    """تبدیلِ PDF به docx (LibreOffice) / txt (pdftotext) / تصویرِ صفحات (pdftoppm)."""
    # کپی با نامِ .pdf تا ابزارها فرمت را درست بشناسند
    src = os.path.join(workdir, f"{stem}.pdf")
    shutil.copyfile(inpath, src)
    if fmt == "docx":
        out = await P.office_convert(src, workdir, "docx")
        return {"path": out, "filename": f"{stem}.docx", "label": t(lang, "cl_convert", fmt="DOCX"),
                "kind": "document"}
    if fmt == "txt":
        out = os.path.join(workdir, f"{stem}.txt")
        await P.pdf_to_text(src, out)
        return {"path": out, "filename": f"{stem}.txt", "label": t(lang, "cl_convert", fmt="TXT"),
                "kind": "document"}
    if fmt in ("jpg", "jpeg", "png"):
        files = await P.pdf_to_images(src, workdir, "png" if fmt == "png" else "jpg")
        return {"note_only": True, "label": t(lang, "cl_convert_pages", n=len(files)), "files": files}
    raise RuntimeError(f"unsupported pdf target: {fmt}")


async def _do_op(bot: Bot, op: str, args: dict[str, Any], file: File, inpath: str, workdir: str,
                 lang: str, progress=None, cancel=None) -> dict[str, Any]:
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
        else:
            raise RuntimeError("compress not supported for this type")
        label = t(lang, "cl_tiny") if args.get("tiny") else t(lang, "cl_compress")
        return {"path": out, "filename": os.path.basename(out), "label": label}

    if op == "convert":
        fmt = (args.get("target") or "").lower()
        if file.kind == "pdf":
            return await _convert_pdf(fmt, stem, inpath, workdir, lang)
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
        members = args.get("members") or []
        paths: list[str] = []
        for m in members:
            fid = m.get("file_id")
            if not fid:
                continue
            p = await _localize(bot, fid, workdir)
            if not p:
                raise RuntimeError(f"member not found: {m.get('name') or fid}")
            paths.append(p)
        if len(paths) < 2:
            raise RuntimeError("need at least two PDFs to merge")
        out = os.path.join(workdir, "merged.pdf")
        await P.pdf_merge(paths, out)
        return {"path": out, "filename": "merged.pdf", "label": t(lang, "cl_merge", n=len(paths)), "kind": "pdf"}

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

    if op == "zip":
        out = os.path.join(workdir, f"{stem}.zip")
        await P.make_zip(inpath, out, file.name or stem)
        return {"path": out, "filename": f"{stem}.zip", "label": t(lang, "cl_zip"), "kind": "archive"}

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
        ext = os.path.splitext(file.name or "audio.mp3")[1] or ".mp3"
        out = os.path.join(workdir, f"{stem}{ext}")
        await P.write_audio_metadata(inpath, out, tags, cover_path=cover_path)
        return {"path": out, "filename": f"{stem}{ext}", "label": t(lang, "cl_meta_edit"),
                "kind": "audio", "new_meta": tags}

    if op == "to_pdf":
        src = os.path.join(workdir, os.path.basename(file.name or "input"))
        shutil.copyfile(inpath, src)
        out = await P.office_to_pdf(src, workdir)
        return {"path": out, "filename": f"{stem}.pdf", "label": t(lang, "cl_topdf"), "kind": "document"}

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

    if op == "thumb":
        out = os.path.join(workdir, f"{stem}-thumb.jpg")
        await P.video_thumbnail(inpath, out)
        return {"send_media": {"as": "photo", "path": out, "filename": f"{stem}.jpg"},
                "label": t(lang, "cl_thumb")}

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
        await P.mute_video(inpath, out)
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
        text = (await P.transcribe_audio(inpath, model, mode)).strip()
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
        rate = float(args.get("rate", 1.0)) or 1.0
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
        await P.remove_background(inpath, out)
        return {"send_media": {"as": "document", "path": out, "filename": f"{stem}-nobg.png"},
                "label": t(lang, "cl_bg_remove")}

    if op == "images_to_pdf":
        members = args.get("members") or []
        paths: list[str] = []
        for m in members:
            fid = m.get("file_id")
            if not fid:
                continue
            p = await _localize(bot, fid, workdir)
            if not p:
                raise RuntimeError(f"member not found: {m.get('name') or fid}")
            paths.append(p)
        if not paths:
            raise RuntimeError("no images for PDF")
        out = os.path.join(workdir, f"{stem}.pdf")
        await P.images_to_pdf(paths, out)
        return {"path": out, "filename": f"{stem}.pdf",
                "label": t(lang, "cl_img_pdf", n=len(paths)), "kind": "pdf"}

    raise RuntimeError(f"unknown op: {op}")


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
                                   progress=_on_progress, cancel=_should_cancel)
            finally:
                ticker.cancel()
                try:
                    await ticker
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        except P.ProcessingCancelled:
            log.info("job %s cancelled by user", job_id)
            job.status = "cancelled"
            await set_card_note(bot, chat_id, card_mid, file, lang, note=t(lang, "cancelled"), keyboard=True)
        except Exception as exc:  # noqa: BLE001  — پردازش شکست خورد؛ فایل دست‌نخورده
            log.exception("job %s processing failed", job_id)
            job.status = "failed"
            job.error = str(exc)[:500]
            await set_card_note(bot, chat_id, card_mid, file, lang, note=_fail_note(lang, exc), keyboard=True)
        else:
            if res.get("spawn") is not None:
                # عملیاتی که یک فایلِ جدید می‌زاید (استخراجِ صدا) → کارتِ مستقلِ جدید
                sp = res["spawn"]
                p = sp["path"]
                newf = File(
                    ref=secrets.token_urlsafe(6)[:8], owner_id=file.owner_id,
                    file_unique_id="", file_id="", kind=sp["kind"], mime=None,
                    name=sp["name"], size=os.path.getsize(p) if os.path.exists(p) else None,
                    changelog=[],
                )
                session.add(newf)
                await session.commit()
                try:
                    sent = await send_card(bot, chat_id, newf, lang, path=p)
                    fid, fuid = message_media_id(sent)
                    if fid:
                        newf.file_id = fid
                    if fuid:
                        newf.file_unique_id = fuid
                except Exception:  # noqa: BLE001
                    log.exception("job %s spawn-card send failed", job_id)
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
                        await bot.send_animation(chat_id, src)
                    elif sm["as"] == "photo":
                        await bot.send_photo(chat_id, src)
                    else:
                        await bot.send_document(chat_id, src)
                    file.changelog = list(file.changelog or []) + [res["label"]]
                    await move_card_below(bot, chat_id, card_mid, file, lang)
                    job.status = "done"
                except Exception as exc:  # noqa: BLE001  — تحویل شکست خورد؛ بدونِ بن‌بست
                    log.exception("job %s artifact delivery failed", job_id)
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    await set_card_note(bot, chat_id, card_mid, file, lang, note=_fail_note(lang, exc), keyboard=True)
            elif res.get("files") is not None:
                # خروجیِ چندفایلی (استخراج) → فایل‌ها بالا، کارتِ تازه پایین (چت تمیز)
                for p in res["files"]:
                    try:
                        await bot.send_document(chat_id, FSInputFile(p, filename=os.path.basename(p)))
                    except Exception:  # noqa: BLE001
                        log.warning("sending extracted file failed: %s", p)
                file.changelog = list(file.changelog or []) + [res["label"]]
                await move_card_below(bot, chat_id, card_mid, file, lang)
                job.status = "done"
            elif res.get("message") is not None:
                # نتیجهٔ متنی (لیستِ آرشیو) → پیام بالا، کارتِ تازه پایین
                try:
                    await bot.send_message(chat_id, res["message"])
                except Exception:  # noqa: BLE001
                    log.warning("sending listing failed")
                file.changelog = list(file.changelog or []) + [res["label"]]
                await move_card_below(bot, chat_id, card_mid, file, lang)
                job.status = "done"
            elif res.get("note_only"):
                # عملیاتِ بررسی (اسکن) → فقط لاگ + کپشن؛ رسانه دست‌نخورده، درجا
                file.changelog = list(file.changelog or []) + [res["label"]]
                await set_card_note(bot, chat_id, card_mid, file, lang, keyboard=True)
                job.status = "done"
            else:
                # عملیاتِ رسانه‌ساز → فیلدهای فایل را عوض کن و کارت را درجا به‌روزرسانی کن
                orig = (file.name, file.size, file.kind, list(file.changelog or []))
                outpath = res["path"]
                file.name = res["filename"]
                if res.get("kind"):
                    file.kind = res["kind"]
                if os.path.exists(outpath):
                    file.size = os.path.getsize(outpath)
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
                    sent = await update_card(bot, chat_id, card_mid, file, lang, path=outpath, thumb=thumb)
                    fid, fuid = message_media_id(sent)
                    if fid:
                        file.file_id = fid
                    if fuid:
                        file.file_unique_id = fuid
                    if res.get("new_meta"):  # متادیتای فعلی را با تگ‌های نوشته‌شده به‌روز کن
                        file.meta = {**(file.meta or {}), **res["new_meta"]}
                    job.status = "done"
                except Exception as exc:  # noqa: BLE001  — تحویل شکست خورد؛ فایل را برگردان
                    log.exception("job %s delivery failed", job_id)
                    file.name, file.size, file.kind, file.changelog = orig
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
