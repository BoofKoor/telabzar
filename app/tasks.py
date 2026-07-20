"""تابعِ ARQ (ورکر): دانلود (مسیرِ لوکال) → پردازش → به‌روزرسانیِ درجای کارت → پاکسازی.

عملیاتِ رسانه‌ساز (تبدیل/فشرده/تغییرنام): کارت درجا با فایلِ جدید به‌روزرسانی می‌شود.
عملیاتِ بررسی (اسکن): فقط لاگِ تغییرات + کپشن عوض می‌شود (فایل دست‌نخورده).
ناموفق: کارت به منوی اصلی + هشدار برمی‌گردد (بدونِ بن‌بست).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile

from . import processing as P
from .filetypes import human_size
from .cards import message_media_id, set_card_note, update_card
from .config import settings
from .db import Sessionmaker
from .i18n import t
from .models import File, Job
from .security import ScanUnavailable, scan_file

log = logging.getLogger("telabzar.worker")


def _safe_stem(name: str | None, default: str = "file") -> str:
    stem = Path(name or default).stem or default
    stem = re.sub(r"[^\w.\-]+", "_", stem)[:60]
    return stem or default


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


async def _do_op(op: str, args: dict[str, Any], file: File, inpath: str, workdir: str, lang: str) -> dict[str, Any]:
    """پردازش → یا {path, filename, label} (رسانه‌ساز) یا {note_only, label} (بررسی)."""
    stem = _safe_stem(file.name)

    if op == "scan":
        try:
            status, name = await scan_file(inpath)
        except ScanUnavailable:
            return {"note_only": True, "label": t(lang, "cl_scan_unavailable")}
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
            await P.compress_video(inpath, out)
        elif file.kind == "audio":
            out = os.path.join(workdir, f"{stem}-min.mp3")
            await P.compress_audio(inpath, out)
        else:
            raise RuntimeError("compress not supported for this type")
        return {"path": out, "filename": os.path.basename(out), "label": t(lang, "cl_compress")}

    if op == "convert":
        fmt = (args.get("target") or "").lower()
        out = os.path.join(workdir, f"{stem}.{fmt}")
        if file.kind == "image":
            await P.convert_image(inpath, out, fmt)
        elif file.kind == "audio":
            await P.convert_audio(inpath, out, fmt)
        elif file.kind == "video":
            await P.convert_video(inpath, out, fmt)
        else:
            raise RuntimeError("convert not supported for this type")
        return {"path": out, "filename": f"{stem}.{fmt}", "label": t(lang, "cl_convert", fmt=fmt.upper())}

    if op == "zip":
        out = os.path.join(workdir, f"{stem}.zip")
        await P.make_zip(inpath, out, file.name or stem)
        return {"path": out, "filename": f"{stem}.zip", "label": t(lang, "cl_zip"), "kind": "archive"}

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

    if op == "to_gif":
        out = os.path.join(workdir, f"{stem}.gif")
        await P.video_to_gif(inpath, out)
        return {"send_media": {"as": "animation", "path": out, "filename": f"{stem}.gif"},
                "label": t(lang, "cl_gif")}

    if op == "thumb":
        out = os.path.join(workdir, f"{stem}-thumb.jpg")
        await P.video_thumbnail(inpath, out)
        return {"send_media": {"as": "photo", "path": out, "filename": f"{stem}.jpg"},
                "label": t(lang, "cl_thumb")}

    if op == "meta":
        m = await P.audio_metadata(inpath)
        tags, fmt, st = m["tags"], m["format"], m["stream"]
        rows: list[tuple[str, str]] = []
        for key in ("title", "artist", "album", "album_artist", "date", "genre", "track"):
            if tags.get(key):
                rows.append((key, str(tags[key])))
        dur = float(fmt.get("duration") or 0)
        if dur:
            rows.append(("duration", _fmt_dur(dur)))
        br = str(fmt.get("bit_rate") or "")
        if br.isdigit():
            rows.append(("bitrate", f"{int(br) // 1000} kbps"))
        if st.get("codec_name"):
            rows.append(("codec", str(st["codec_name"])))
        if st.get("sample_rate"):
            rows.append(("sample rate", f"{st['sample_rate']} Hz"))
        if st.get("channels"):
            rows.append(("channels", str(st["channels"])))
        lines = [t(lang, "meta_header")]
        if rows:
            lines += [f"• <b>{escape(k)}</b>: <code>{escape(v)}</code>" for k, v in rows]
        else:
            lines.append(t(lang, "meta_empty"))
        return {"note_only": True, "label": t(lang, "cl_meta"), "message": "\n".join(lines)}

    raise RuntimeError(f"unknown op: {op}")


async def run_op(ctx: dict, job_id: int, chat_id: int, card_mid: int, lang: str) -> None:
    bot: Bot = ctx["bot"]
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
            tg_file = await bot.get_file(file.file_id)
            inpath = tg_file.file_path
            if not inpath or not os.path.exists(inpath):
                # مسیر را در خطا بیاور تا ریشه فوراً معلوم شود:
                # نسبی → سرور local نیست؛ مطلق → مشکلِ mount یا پرمیشن/capability
                raise RuntimeError(f"input file not found on disk: {inpath or '(empty)'}"[:200])
            res = await _do_op(job.op, job.args or {}, file, inpath, workdir, lang)
        except Exception as exc:  # noqa: BLE001  — پردازش شکست خورد؛ فایل دست‌نخورده
            log.exception("job %s processing failed", job_id)
            job.status = "failed"
            job.error = str(exc)[:500]
            await set_card_note(bot, chat_id, card_mid, file, lang, note=_fail_note(lang, exc), keyboard=True)
        else:
            if res.get("send_media") is not None:
                # آرتیفکتِ رسانه‌ایِ جدا (GIF/تامبنیل) → پیامِ جدا؛ کارت دست‌نخورده
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
                    await set_card_note(bot, chat_id, card_mid, file, lang, keyboard=True)
                    job.status = "done"
                except Exception as exc:  # noqa: BLE001  — تحویل شکست خورد؛ بدونِ بن‌بست
                    log.exception("job %s artifact delivery failed", job_id)
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    await set_card_note(bot, chat_id, card_mid, file, lang, note=_fail_note(lang, exc), keyboard=True)
            elif res.get("files") is not None:
                # خروجیِ چندفایلی (استخراج) → هر کدام را جدا بفرست؛ کارت دست‌نخورده
                for p in res["files"]:
                    try:
                        await bot.send_document(chat_id, FSInputFile(p, filename=os.path.basename(p)))
                    except Exception:  # noqa: BLE001
                        log.warning("sending extracted file failed: %s", p)
                file.changelog = list(file.changelog or []) + [res["label"]]
                await set_card_note(bot, chat_id, card_mid, file, lang, keyboard=True)
                job.status = "done"
            elif res.get("message") is not None:
                # نتیجهٔ متنی (لیستِ آرشیو) → پیامِ جدا؛ کارت دست‌نخورده
                try:
                    await bot.send_message(chat_id, res["message"])
                except Exception:  # noqa: BLE001
                    log.warning("sending listing failed")
                file.changelog = list(file.changelog or []) + [res["label"]]
                await set_card_note(bot, chat_id, card_mid, file, lang, keyboard=True)
                job.status = "done"
            elif res.get("note_only"):
                # عملیاتِ بررسی (اسکن) → فقط لاگ + کپشن؛ رسانه دست‌نخورده
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
                try:
                    sent = await update_card(bot, chat_id, card_mid, file, lang, path=outpath)
                    fid, fuid = message_media_id(sent)
                    if fid:
                        file.file_id = fid
                    if fuid:
                        file.file_unique_id = fuid
                    job.status = "done"
                except Exception as exc:  # noqa: BLE001  — تحویل شکست خورد؛ فایل را برگردان
                    log.exception("job %s delivery failed", job_id)
                    file.name, file.size, file.kind, file.changelog = orig
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    await set_card_note(bot, chat_id, card_mid, file, lang, note=_fail_note(lang, exc), keyboard=True)
        finally:
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
            shutil.rmtree(workdir, ignore_errors=True)
