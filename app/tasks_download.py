"""تابعِ ARQ برای دانلود (اجرا در ورکرِ اختصاصیِ `dl`).

دو فاز:
- probe: ‎-J → منوی کیفیت را روی پیامِ وضعیت می‌سازد (گزینه‌ها در Redis).
- fetch: دانلود → **چکِ قطعیِ حجم روی دیسک قبل از آپلود** → spawn به pipeline.

جابِ دانلود، رکوردِ File/Job از پیش ندارد؛ همه‌چیز با `ref` و پیامِ وضعیت
(status_mid) ردیابی می‌شود. لغو با کلیدِ Redis `cancel:dl:{ref}`.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timezone

from aiogram import Bot

from . import downloader as D
from . import processing as P
from . import settings_store
from .cards import message_media_id, send_card
from .config import settings
from .db import Sessionmaker
from .i18n import t
from .keyboards import download_cancel_kb, download_menu_kb
from .models import File

log = logging.getLogger("telabzar.dl")

_BAN_HINTS = ("login required", "rate-limit", "rate limit", "sign in", "checkpoint",
              "challenge", "not logged", "401", "403", "temporary ban")


class DownloadTooLarge(Exception):
    def __init__(self, size: int) -> None:
        self.size = size


class DownloadBusy(Exception):
    pass


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


async def _pick_cookies(redis, platform: str) -> str | None:
    """یک فایلِ کوکی از پوشه انتخاب می‌کند (چرخشِ اکانت؛ ردِ اکانت‌های cooldown‌شده)."""
    d = settings.cookies_dir
    if not d or not os.path.isdir(d):
        return None
    cands = sorted(glob.glob(os.path.join(d, "*.txt")))
    plat = [f for f in cands if platform in os.path.basename(f).lower()]
    pool = plat or cands
    if not pool:
        return None
    live = []
    for f in pool:
        on_cd = False
        if redis is not None:
            try:
                on_cd = bool(await redis.exists(f"ckcd:{os.path.basename(f)}"))
            except Exception:  # noqa: BLE001
                on_cd = False
        if not on_cd:
            live.append(f)
    live = live or pool
    idx = 0
    if redis is not None:
        try:
            idx = (await redis.incr(f"ckrot:{platform}")) % len(live)
        except Exception:  # noqa: BLE001
            idx = 0
    return live[idx]


async def _cooldown_cookie(redis, path: str | None, sec: int = 1800) -> None:
    if redis is not None and path:
        try:
            await redis.set(f"ckcd:{os.path.basename(path)}", "1", ex=sec)
        except Exception:  # noqa: BLE001
            pass


async def _metric(redis, platform: str, ok: bool) -> None:
    """شمارندهٔ نرخِ موفقیت/شکستِ per-platform (هشدارِ زودهنگام برای شکستنِ upstream)."""
    if redis is None:
        return
    key = f"dlstat:{platform}:{'ok' if ok else 'fail'}:{_today()}"
    try:
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, 172800)  # ۲ روز
    except Exception:  # noqa: BLE001
        pass


async def _opts(redis, platform: str) -> dict:
    return {
        "proxy": await settings_store.get_str("proxy_url", settings.proxy_url) or None,
        "pot_provider": settings.pot_provider_url or None,
        "cookies": await _pick_cookies(redis, platform),
        "max_mb": await settings_store.get_int("dl_max_size_mb", settings.dl_max_size_mb),
    }


async def _edit(bot: Bot, chat_id: int, mid: int, text: str, kb=None) -> None:
    try:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=mid, reply_markup=kb)
    except Exception:  # noqa: BLE001
        pass


def _kind_from_info(info: dict, path: str) -> str:
    if info.get("vcodec") not in (None, "none") or info.get("height"):
        return "video"
    if info.get("acodec") not in (None, "none"):
        return "audio"
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac"):
        return "audio"
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return "image"
    return "video"


async def _spawn(bot: Bot, chat_id: int, owner_id: int, path: str, name: str,
                 kind: str, info: dict, lang: str) -> None:
    """فایلِ دانلودی را وارد pipeline می‌کند (الگوی spawn) با source='dl'."""
    async with Sessionmaker() as s:
        f = File(
            ref=secrets.token_urlsafe(6)[:8], owner_id=owner_id, file_unique_id="", file_id="",
            kind=kind, mime=None, name=name,
            size=os.path.getsize(path) if os.path.exists(path) else None,
            width=info.get("width"), height=info.get("height"),
            duration=int(info["duration"]) if info.get("duration") else None,
            changelog=[], source="dl",
        )
        s.add(f)
        await s.commit()
        try:
            sent = await send_card(bot, chat_id, f, lang, path=path)
            fid, fuid = message_media_id(sent)
            if fid:
                f.file_id = fid
            if fuid:
                f.file_unique_id = fuid
        except Exception:  # noqa: BLE001
            log.exception("dl spawn-card send failed")
        await s.commit()


async def run_download(ctx: dict, payload: dict) -> None:
    bot: Bot = ctx["bot"]
    redis = ctx.get("redis")
    ref = payload["ref"]
    chat_id = payload["chat_id"]
    status_mid = payload["status_mid"]
    lang = payload["lang"]
    url = payload["url"]
    platform = payload["platform"]
    engine = payload["engine"]
    phase = payload["phase"]
    selector = payload.get("selector", "best")
    owner_id = payload["owner_id"]
    workdir = os.path.join(settings.work_dir, f"dl-{ref}")

    async def _cancelled() -> bool:
        if redis is None:
            return False
        try:
            return bool(await redis.exists(f"cancel:dl:{ref}"))
        except Exception:  # noqa: BLE001
            return False

    # ── فازِ probe: منوی کیفیت ──
    if phase == "probe":
        try:
            info = await D.probe(url, await _opts(redis, platform))
        except Exception as exc:  # noqa: BLE001
            await _metric(redis, platform, ok=False)
            await _edit(bot, chat_id, status_mid,
                        t(lang, "dl_probe_failed") + f"\n<code>{str(exc)[:120]}</code>")
            return
        opts = info.get("options") or []
        if redis is not None and opts:
            try:
                await redis.set(f"probe:{ref}", json.dumps(opts), ex=1800)
            except Exception:  # noqa: BLE001
                pass
        title = (info.get("title") or "")[:80]
        await _edit(bot, chat_id, status_mid,
                    t(lang, "dl_pick_quality", title=title),
                    kb=download_menu_kb(ref, opts, lang))
        return

    # ── فازِ fetch: دانلود + spawn ──
    cap = await settings_store.get_int("dl_concurrency", settings.dl_concurrency)
    active = 0
    if redis is not None:
        try:
            active = await redis.incr("dl:active")
        except Exception:  # noqa: BLE001
            active = 0
    try:
        if cap and active > cap:
            await _edit(bot, chat_id, status_mid, t(lang, "dl_busy"))
            return
        # گاردِ فضای دیسک
        min_free = await settings_store.get_int("dl_min_free_gb", settings.dl_min_free_gb)
        try:
            free = shutil.disk_usage(settings.work_dir).free
        except Exception:  # noqa: BLE001
            free = None
        if min_free and free is not None and free < min_free * 1024 ** 3:
            await _edit(bot, chat_id, status_mid, t(lang, "dl_no_disk"))
            return

        os.makedirs(workdir, exist_ok=True)
        opts = await _opts(redis, platform)
        cookie = opts.get("cookies")

        pstate = {"pct": -1}

        async def _progress(pct: float) -> None:
            ip = int(pct)
            if ip <= pstate["pct"]:
                return
            pstate["pct"] = ip
            await _edit(bot, chat_id, status_mid, t(lang, "dl_downloading", pct=ip),
                        kb=download_cancel_kb(ref, lang))

        try:
            if engine == "gallerydl":
                files = await D.download_gallerydl(url, workdir, opts, progress=_progress, cancel=_cancelled)
                paths = [(p, {}) for p in files]
            else:
                path, info = await D.download_ytdlp(url, workdir, selector, opts,
                                                    progress=_progress, cancel=_cancelled)
                paths = [(path, info)]
        except P.ProcessingCancelled:
            await _edit(bot, chat_id, status_mid, t(lang, "cancelled"))
            return
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if any(h in msg.lower() for h in _BAN_HINTS):
                await _cooldown_cookie(redis, cookie)
            await _metric(redis, platform, ok=False)
            await _edit(bot, chat_id, status_mid, t(lang, "dl_failed") + f"\n<code>{msg[:140]}</code>")
            return

        # چکِ قطعیِ حجم روی دیسک قبل از آپلود (نقدِ #۱: --max-filesize کافی نیست)
        max_mb = await settings_store.get_int("dl_max_size_mb", settings.dl_max_size_mb)
        total = sum(os.path.getsize(p) for p, _ in paths if os.path.exists(p))
        if max_mb and total > max_mb * 1024 * 1024:
            await _metric(redis, platform, ok=False)
            await _edit(bot, chat_id, status_mid,
                        t(lang, "dl_too_large", mb=round(total / 1024 / 1024), cap=max_mb))
            return

        # ثبتِ حجمِ روزانه (شمارشِ واقعی بعد از دانلود)
        if redis is not None:
            try:
                k = f"dlq:mb:{payload['tg_user_id']}:{_today()}"
                await redis.incrby(k, max(1, round(total / 1024 / 1024)))
                await redis.expire(k, 90000)
            except Exception:  # noqa: BLE001
                pass

        for p, info in paths:
            kind = _kind_from_info(info, p)
            name = os.path.basename(p)
            if kind == "image" and not info.get("width"):
                try:
                    from PIL import Image
                    with Image.open(p) as im:
                        info = {**info, "width": im.width, "height": im.height}
                except Exception:  # noqa: BLE001
                    pass
            await _spawn(bot, chat_id, owner_id, p, name, kind, info, lang)

        await _metric(redis, platform, ok=True)
        try:
            await bot.delete_message(chat_id, status_mid)  # کارت جایگزینش شد
        except Exception:  # noqa: BLE001
            pass
    finally:
        if redis is not None:
            try:
                await redis.decr("dl:active")
                await redis.delete(f"cancel:dl:{ref}")
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(workdir, ignore_errors=True)
