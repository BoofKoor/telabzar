"""تابعِ ARQ که در ورکر اجرا می‌شود: دانلود (مسیرِ لوکال) → پردازش → تحویل → پاکسازی."""
from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile

from . import processing as P
from .config import settings
from .db import Sessionmaker
from .i18n import t
from .keyboards import file_card_kb
from .models import File, Job

log = logging.getLogger("telabzar.worker")


def _safe_stem(name: str | None, default: str = "file") -> str:
    stem = Path(name or default).stem or default
    stem = re.sub(r"[^\w.\-]+", "_", stem)[:60]
    return stem or default


def _send_as(kind: str) -> str:
    return {"video": "video", "audio": "audio"}.get(kind, "document")


async def _do_op(op: str, args: dict[str, Any], file: File, inpath: str, workdir: str) -> dict[str, str]:
    stem = _safe_stem(file.name)

    if op == "rename":
        new = (args.get("new_name") or "file").strip()
        new = re.sub(r"[\\/\x00]+", "_", new)[:120] or "file"
        if not Path(new).suffix and file.name and Path(file.name).suffix:
            new += Path(file.name).suffix
        return {"path": inpath, "filename": new, "send_as": _send_as(file.kind)}

    if op == "compress":
        if file.kind == "image":
            out = os.path.join(workdir, f"{stem}-min.jpg")
            await P.compress_image(inpath, out)
            return {"path": out, "filename": f"{stem}-min.jpg", "send_as": "document"}
        if file.kind == "video":
            out = os.path.join(workdir, f"{stem}-min.mp4")
            await P.compress_video(inpath, out)
            return {"path": out, "filename": f"{stem}-min.mp4", "send_as": "video"}
        if file.kind == "audio":
            out = os.path.join(workdir, f"{stem}-min.mp3")
            await P.compress_audio(inpath, out)
            return {"path": out, "filename": f"{stem}-min.mp3", "send_as": "audio"}
        raise RuntimeError("compress not supported for this type")

    if op == "convert":
        fmt = (args.get("target") or "").lower()
        out = os.path.join(workdir, f"{stem}.{fmt}")
        if file.kind == "image":
            await P.convert_image(inpath, out, fmt)
            return {"path": out, "filename": f"{stem}.{fmt}", "send_as": "document"}
        if file.kind in ("video", "audio"):
            await P.convert_av(inpath, out, fmt)
            if file.kind == "video" and fmt in ("mp4", "webm"):
                send = "video"
            elif file.kind == "audio" and fmt in ("mp3", "m4a", "ogg"):
                send = "audio"
            else:
                send = "document"
            return {"path": out, "filename": f"{stem}.{fmt}", "send_as": send}
        raise RuntimeError("convert not supported for this type")

    raise RuntimeError(f"unknown op: {op}")


async def _send_result(bot: Bot, chat_id: int, res: dict[str, str]) -> None:
    file = FSInputFile(res["path"], filename=res["filename"])
    send_as = res["send_as"]
    if send_as == "video":
        await bot.send_video(chat_id, file)
    elif send_as == "audio":
        await bot.send_audio(chat_id, file)
    else:
        await bot.send_document(chat_id, file)


async def _safe_edit(bot: Bot, chat_id: int, message_id: int, text: str, markup=None) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    except Exception:  # noqa: BLE001
        pass


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
        await _safe_edit(bot, chat_id, card_mid, t(lang, "processing"))

        try:
            os.makedirs(workdir, exist_ok=True)
            tg_file = await bot.get_file(file.file_id)
            inpath = tg_file.file_path
            if not inpath or not os.path.exists(inpath):
                raise RuntimeError("input file not found on disk")

            res = await _do_op(job.op, job.args or {}, file, inpath, workdir)
            await _send_result(bot, chat_id, res)

            job.status = "done"
            await _safe_edit(
                bot, chat_id, card_mid, t(lang, "done"),
                file_card_kb(file.ref, file.kind, lang),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            job.status = "failed"
            job.error = str(exc)[:500]
            await _safe_edit(bot, chat_id, card_mid, t(lang, "failed"))
        finally:
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
            shutil.rmtree(workdir, ignore_errors=True)
