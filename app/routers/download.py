"""درِ ورودیِ دانلود: کاربر لینک می‌فرستد → دانلود → همان pipeline.

بین `ops` و `files` ثبت می‌شود: هندلرهای متنیِ ops حالت‌محورند (اگر کاربر وسطِ
یک FSM لینک بفرستد، آن‌جا می‌ماند)، و اگر حالتی فعال نباشد لینک اینجا گرفته می‌شود
تا به fallback‌ِ «یک فایل بفرست» نرسد.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from arq import ArqRedis

from .. import settings_store
from ..callbacks import Dl
from ..config import settings
from ..downloader import engine_for, find_url, is_safe_url, platform_of
from ..i18n import t
from ..models import User

router = Router(name="download")

_DL_QUEUE = "arq:queue:dl"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


async def _resolve_ux(platform: str) -> str:
    per = await settings_store.get_str(f"dl_ux_{platform}", "")
    if per in ("probe", "quick"):
        return per
    ux = await settings_store.get_str("dl_default_ux", settings.dl_default_ux)
    return ux if ux in ("probe", "quick") else "quick"


async def _precheck(pool: ArqRedis, uid: int, lang: str) -> str | None:
    """سقفِ تعداد/کول‌داونِ دانلود. پیامِ خطا یا None."""
    cd = await settings_store.get_int("dl_cooldown_sec", settings.dl_cooldown_sec)
    if cd > 0:
        try:
            if await pool.exists(f"dlq:cd:{uid}"):
                return t(lang, "dl_cooldown")
        except Exception:  # noqa: BLE001
            pass
    cnt = await settings_store.get_int("dl_daily_count", settings.dl_daily_count)
    if cnt > 0:
        try:
            raw = await pool.get(f"dlq:cnt:{uid}:{_today()}")
            if isinstance(raw, bytes):
                raw = raw.decode()
            used = int(raw) if raw else 0
            if used >= cnt:
                return t(lang, "dl_daily_limit")
        except Exception:  # noqa: BLE001
            pass
    return None


async def _charge(pool: ArqRedis, uid: int) -> None:
    """شمارشِ یک دانلودِ منظور‌شده + ستِ کول‌داون."""
    try:
        k = f"dlq:cnt:{uid}:{_today()}"
        await pool.incr(k)
        await pool.expire(k, 90000)
        cd = await settings_store.get_int("dl_cooldown_sec", settings.dl_cooldown_sec)
        if cd > 0:
            await pool.set(f"dlq:cd:{uid}", "1", ex=cd)
    except Exception:  # noqa: BLE001
        pass


@router.message(F.text.regexp(r"https?://"))
async def on_link(message: Message, lang: str, arq_pool: ArqRedis, user: User | None) -> None:
    if not await settings_store.get_bool("downloader_enabled", settings.downloader_enabled):
        return  # کلیدِ خاموشیِ دانلودر
    url = find_url(message.text)
    if not url:
        return
    if not is_safe_url(url):
        await message.reply(t(lang, "dl_bad_link"))
        return
    uid = user.tg_user_id if user else 0
    owner_id = user.id if user else 0
    block = await _precheck(arq_pool, uid, lang)
    if block:
        await message.reply(block)
        return

    platform = platform_of(url)
    engine = engine_for(url, platform)
    ref = secrets.token_urlsafe(6)[:8]
    # زمینهٔ دانلود را برای فازِ pick/cancel نگه دار
    ctx = {"url": url, "platform": platform, "engine": engine,
           "owner_id": owner_id, "tg_user_id": uid}
    try:
        await arq_pool.set(f"dlctx:{ref}", json.dumps(ctx), ex=1800)
    except Exception:  # noqa: BLE001
        pass

    status = await message.answer(t(lang, "dl_reading"))
    try:
        await message.delete()  # لینک را پاک کن تا چت تمیز بماند
    except Exception:  # noqa: BLE001
        pass

    ux = await _resolve_ux(platform)
    base = {"ref": ref, "chat_id": message.chat.id, "status_mid": status.message_id,
            "lang": lang, "url": url, "platform": platform, "engine": engine,
            "owner_id": owner_id, "tg_user_id": uid}

    if ux == "probe" and engine == "ytdlp":
        await arq_pool.enqueue_job("run_download", {**base, "phase": "probe"}, _queue_name=_DL_QUEUE)
    else:  # quick-grab: بهترین کیفیت
        await _charge(arq_pool, uid)
        await arq_pool.enqueue_job(
            "run_download", {**base, "phase": "fetch", "selector": "best"}, _queue_name=_DL_QUEUE)


@router.callback_query(Dl.filter())
async def on_dl_pick(cq: CallbackQuery, callback_data: Dl, lang: str,
                     arq_pool: ArqRedis, user: User | None) -> None:
    ref, sel = callback_data.ref, callback_data.sel
    if sel == "cancel":
        try:
            await arq_pool.set(f"cancel:dl:{ref}", "1", ex=1200)
        except Exception:  # noqa: BLE001
            pass
        if isinstance(cq.message, Message):
            try:
                await cq.message.edit_text(t(lang, "cancelled"))
            except Exception:  # noqa: BLE001
                pass
        await cq.answer(t(lang, "cancelling"))
        return

    raw = None
    try:
        raw = await arq_pool.get(f"dlctx:{ref}")
    except Exception:  # noqa: BLE001
        raw = None
    if not raw or not isinstance(cq.message, Message):
        await cq.answer(t(lang, "dl_expired"), show_alert=True)
        return
    ctx = json.loads(raw)
    uid = ctx.get("tg_user_id", 0)
    block = await _precheck(arq_pool, uid, lang)
    if block:
        await cq.answer(block, show_alert=True)
        return
    await _charge(arq_pool, uid)
    payload = {"ref": ref, "chat_id": cq.message.chat.id, "status_mid": cq.message.message_id,
               "lang": lang, "url": ctx["url"], "platform": ctx["platform"],
               "engine": ctx["engine"], "owner_id": ctx["owner_id"], "tg_user_id": uid,
               "phase": "fetch", "selector": sel}
    await arq_pool.enqueue_job("run_download", payload, _queue_name=_DL_QUEUE)
    await cq.answer()
