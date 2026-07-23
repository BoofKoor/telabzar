"""تابعِ ARQ برای دانلود (اجرا در ورکرِ اختصاصیِ `dl`).

دو فاز:
- probe: ‎-J → منوی کیفیت را روی پیامِ وضعیت می‌سازد (گزینه‌ها در Redis).
- fetch: دانلود → **چکِ قطعیِ حجم روی دیسک قبل از آپلود** → spawn به pipeline.

جابِ دانلود، رکوردِ File/Job از پیش ندارد؛ همه‌چیز با `ref` و پیامِ وضعیت
(status_mid) ردیابی می‌شود. لغو با کلیدِ Redis `cancel:dl:{ref}`.
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import re
import secrets
import shutil
import time
from datetime import datetime, timezone
from html import escape

from aiogram import Bot
from aiogram.types import (
    FSInputFile, InputMediaPhoto, InputMediaVideo, InputRichBlockParagraph,
    InputRichBlockPhoto, InputRichBlockSlideshow, InputRichBlockVideo, InputRichMessage,
)
from aiogram.utils.media_group import MediaGroupBuilder

from . import dl_cache
from . import downloader as D
from . import processing as P
from . import settings_store
from . import textstore
from .cards import message_media_id, progress_note, send_card, update_card
from .config import settings
from .db import Sessionmaker
from .i18n import t
from .keyboards import download_cancel_kb, download_menu_kb
from .models import File

log = logging.getLogger("telabzar.dl")

_BAN_HINTS = ("login required", "rate-limit", "rate limit", "sign in", "checkpoint",
              "challenge", "not logged", "401", "403", "temporary ban", "login page")
_LOGIN_HINTS = ("login", "not logged", "sign in", "account", "checkpoint", "challenge")


class DownloadTooLarge(Exception):
    def __init__(self, size: int) -> None:
        self.size = size


class DownloadBusy(Exception):
    pass


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


# کوکی‌ها به Redis آینه می‌شوند (کلیدها) تا نودِ دانلود — که دیسکِ کوکیِ مستر را ندارد —
# هم بتواند آن‌ها را بخواند. پنل موقعِ آپلود/حذف این‌ها را می‌نویسد/پاک می‌کند.
_CK_SET = "ckfiles"          # ست نام‌های فایلِ کوکی
_CK_CONTENT = "ckfile:"      # ckfile:<name> → محتوای کوکی


async def _cookie_names(redis, platform: str) -> tuple[list[str], bool]:
    """نام‌های کوکیِ این پلتفرم + آیا منبع دیسکِ محلی است (True = مستر) یا آینهٔ Redis
    (False = نود که دیسکِ کوکی ندارد). فقط کوکیِ همان پلتفرم (نه fallback به همه)."""
    d = settings.cookies_dir
    if d and os.path.isdir(d):
        names = [os.path.basename(f) for f in sorted(glob.glob(os.path.join(d, "*.txt")))]
        local = True
    else:
        names, local = [], False
        if redis is not None:
            try:
                raw = await redis.smembers(_CK_SET)
                names = sorted((n if isinstance(n, str) else n.decode()) for n in raw)
            except Exception:  # noqa: BLE001
                names = []
    return [n for n in names if platform in n.lower()], local


async def _pick_cookies(redis, platform: str, workdir: str | None = None) -> str | None:
    """یک کوکیِ این پلتفرم را به‌صورتِ **مسیرِ فایل** برمی‌گرداند. روی مستر از دیسکِ محلی؛
    روی نود از آینهٔ Redis (محتوا را در `workdir` فایلِ موقت می‌کند). چرخشِ اکانت + cooldown
    (Redisِ مشترک، کلیدِ `ckcd:<name>`/`ckrot:<platform>`) در هر دو حالت یکسان کار می‌کند."""
    pool, local = await _cookie_names(redis, platform)
    if not pool:
        return None
    live = []
    for n in pool:
        on_cd = False
        if redis is not None:
            try:
                on_cd = bool(await redis.exists(f"ckcd:{n}"))
            except Exception:  # noqa: BLE001
                on_cd = False
        if not on_cd:
            live.append(n)
    live = live or pool
    idx = 0
    if redis is not None:
        try:
            idx = (await redis.incr(f"ckrot:{platform}")) % len(live)
        except Exception:  # noqa: BLE001
            idx = 0
    name = live[idx]
    if local:
        return os.path.join(settings.cookies_dir, name)
    # نود: محتوا را از آینهٔ Redis بگیر و در workdir بنویس (با workdir پاک می‌شود)
    if redis is None or not workdir:
        return None
    try:
        content = await redis.get(_CK_CONTENT + name)
    except Exception:  # noqa: BLE001
        content = None
    if not content:
        return None
    try:
        ckdir = os.path.join(workdir, "ck")
        os.makedirs(ckdir, exist_ok=True)
        path = os.path.join(ckdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content if isinstance(content, str) else content.decode("utf-8", "replace"))
        return path
    except OSError:
        return None


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


async def _opts(redis, platform: str, workdir: str | None = None) -> dict:
    pot_on = await settings_store.get_bool("dl_pot_enabled", settings.dl_pot_enabled)
    # اسپاتیفای دانلودِ واقعی را از یوتیوب می‌گیرد → کوکیِ یوتیوب لازم است، نه اسپاتیفای
    cookie_platform = "youtube" if platform == "spotify" else platform
    return {
        "proxy": await settings_store.get_str("proxy_url", settings.proxy_url) or None,
        "pot_provider": (settings.pot_provider_url or None) if pot_on else None,
        "cookies": await _pick_cookies(redis, cookie_platform, workdir),
        "max_mb": await settings_store.get_int("dl_max_size_mb", settings.dl_max_size_mb),
        "sponsorblock": await settings_store.get_str("dl_sponsorblock", settings.dl_sponsorblock) or None,
        "subs": await settings_store.get_bool("dl_subs", settings.dl_subs),
        "cobalt_key": settings.cobalt_api_key or None,
        "spotify_client_id": await settings_store.get_str("spotify_client_id", settings.spotify_client_id),
        "spotify_client_secret": await settings_store.get_str("spotify_client_secret", settings.spotify_client_secret),
        "spotify_max_tracks": await settings_store.get_int("spotify_max_tracks", settings.spotify_max_tracks),
        "spotify_source": await settings_store.get_str("spotify_source", settings.spotify_source),
        "spotify_match_min": await settings_store.get_int("spotify_match_min", settings.spotify_match_min),
        "spotify_yt_fallback": await settings_store.get_bool("spotify_yt_fallback", settings.spotify_yt_fallback),
    }


async def _edit(bot: Bot, chat_id: int, mid: int, text: str, kb=None) -> None:
    """پیامِ وضعیت را ویرایش می‌کند — چه متنی باشد چه رسانه‌ای (عکسِ منو)."""
    try:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=mid, reply_markup=kb)
        return
    except Exception:  # noqa: BLE001
        pass
    try:  # لنگرگاه عکس است → کپشن را ویرایش کن
        await bot.edit_message_caption(chat_id=chat_id, message_id=mid, caption=text, reply_markup=kb)
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


def _prep_thumb(src: str | None) -> str | None:
    """تامبنیل را به JPEGِ ≤۳۲۰px می‌کند (سقفِ تلگرام) تا send_video ردش نکند."""
    if not src or not os.path.exists(src):
        return None
    try:
        from PIL import Image
        out = src + ".thumb.jpg"
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((320, 320))
            im.save(out, "JPEG", quality=80)
        return out
    except Exception:  # noqa: BLE001
        return None


_ALBUM_IMG = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".bmp")
_ALBUM_VID = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


async def _deliver_album(bot: Bot, chat_id: int, owner_id: int, files: list[str],
                         caption: str | None, lang: str) -> None:
    """پستِ چند‌تاییِ گالری (کاروسلِ اینستاگرام) → آلبومِ سوایپ‌شدنیِ تلگرام.

    کپشنِ پست (بدونِ هشتگ) روی آیتمِ اول؛ عکس و ویدیو در همان آلبوم؛ بدونِ دکمه/کارت
    (media group اصلاً reply_markup نمی‌پذیرد → با «کلیدها را لیست نکن» جور است).
    کاروسلِ بیش از ۱۰ آیتم به چند آلبومِ پشتِ‌سرِ‌هم شکسته می‌شود.
    """
    media = [f for f in files
             if os.path.isfile(f) and os.path.getsize(f) > 0
             and f.lower().endswith(_ALBUM_IMG + _ALBUM_VID)]
    if len(media) < 2:  # کمتر از ۲ رسانه → آلبوم بی‌معنی؛ برگرد به کارتِ معمولی
        for p in media:
            kind = "video" if p.lower().endswith(_ALBUM_VID) else "image"
            await _spawn(bot, chat_id, owner_id, p, os.path.basename(p), kind, {}, lang)
        return
    cap_text = D.clean_caption(caption)  # تضمینِ بدونِ‌هشتگ + سقفِ ۱۰۲۴ (idempotent)
    cap = escape(cap_text) if cap_text else None  # parse_mode=HTML → کپشنِ کاربر escape شود
    for gi in range(0, len(media), 10):  # سقفِ ۱۰ آیتم در هر media group
        batch = media[gi:gi + 10]
        b = MediaGroupBuilder(caption=cap if gi == 0 else None)
        for p in batch:
            if p.lower().endswith(_ALBUM_VID):
                b.add_video(media=FSInputFile(p))
            else:
                b.add_photo(media=FSInputFile(p))
        try:
            await bot.send_media_group(chat_id, media=b.build())
        except Exception:  # noqa: BLE001
            log.exception("album send failed (batch starting %d)", gi)


async def _deliver_rich_post(bot: Bot, chat_id: int, owner_id: int, files: list[str],
                             caption: str | None, lang: str) -> None:
    """پستِ چند‌تایی → Rich Message (Bot API 10.1): پاراگرافِ کپشن + Slideshowِ
    ورق‌زدنیِ عکس/ویدیو (تا ۵۰ رسانه در یک پست). آپلودِ محلی، بدونِ دکمه.

    خطا را بالا می‌دهد تا فراخوان به آلبوم fallback کند (سرور/کلاینتِ قدیمی).
    متنِ پاراگراف plain rich است (نه HTML) → نیازی به escape نیست.
    """
    media = [f for f in files
             if os.path.isfile(f) and os.path.getsize(f) > 0
             and f.lower().endswith(_ALBUM_IMG + _ALBUM_VID)]
    if len(media) < 2:  # کمتر از ۲ رسانه → کارتِ معمولی (مثلِ آلبوم)
        for p in media:
            kind = "video" if p.lower().endswith(_ALBUM_VID) else "image"
            await _spawn(bot, chat_id, owner_id, p, os.path.basename(p), kind, {}, lang)
        return
    slides: list = []
    for p in media[:50]:  # سقفِ رسانهٔ Rich Message
        if p.lower().endswith(_ALBUM_VID):
            slides.append(InputRichBlockVideo(video=InputMediaVideo(media=FSInputFile(p))))
        else:
            slides.append(InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(p))))
    blocks: list = []
    cap = D.clean_caption(caption)
    if cap:
        blocks.append(InputRichBlockParagraph(text=cap))
    blocks.append(InputRichBlockSlideshow(blocks=slides))
    await bot.send_rich_message(chat_id, rich_message=InputRichMessage(blocks=blocks))


async def _spawn(bot: Bot, chat_id: int, owner_id: int, path: str, name: str,
                 kind: str, info: dict, lang: str, thumb_path: str | None = None) -> None:
    """فایلِ دانلودی را وارد pipeline می‌کند (الگوی spawn) با source='dl'."""
    thumb = None
    if kind == "video" and thumb_path:
        prepped = _prep_thumb(thumb_path)
        if prepped:
            thumb = FSInputFile(prepped)
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
            sent = await send_card(bot, chat_id, f, lang, path=path, thumb=thumb)
            fid, fuid = message_media_id(sent)
            if fid:
                f.file_id = fid
            if fuid:
                f.file_unique_id = fuid
        except Exception:  # noqa: BLE001
            log.exception("dl spawn-card send failed")
        await s.commit()


async def _deliver_single(bot: Bot, chat_id: int, anchor_mid: int, owner_id: int, p: str,
                          name: str, kind: str, info: dict, lang: str, thumb_path: str | None,
                          url: str, selector: str) -> None:
    """تک‌فایل را **درجا** روی پیامِ لنگرگاه تحویل می‌دهد (عکسِ منو → ویدیو) و
    file_id را برای دفعهٔ بعد کش می‌کند. اگر لنگرگاه متنی بود، update_card خودش
    کارتِ تازه می‌فرستد و قدیمی را پاک می‌کند."""
    thumb = None
    if kind == "video" and thumb_path:
        prepped = _prep_thumb(thumb_path)
        if prepped:
            thumb = FSInputFile(prepped)
    async with Sessionmaker() as s:
        f = File(
            ref=secrets.token_urlsafe(6)[:8], owner_id=owner_id, file_unique_id="", file_id="",
            kind=kind, mime=None, name=name,
            size=os.path.getsize(p) if os.path.exists(p) else None,
            width=info.get("width"), height=info.get("height"),
            duration=int(info["duration"]) if info.get("duration") else None,
            changelog=[], source="dl",
        )
        s.add(f)
        await s.commit()
        try:
            sent = await update_card(bot, chat_id, anchor_mid, f, lang, path=p, thumb=thumb)
            fid, fuid = message_media_id(sent)
            if fid:
                f.file_id = fid
            if fuid:
                f.file_unique_id = fuid
            await s.commit()
            await dl_cache.put_cached(s, url, selector, f)  # دفعهٔ بعد آنی
        except Exception:  # noqa: BLE001
            log.exception("dl in-place delivery failed")


_SP_NAME_RE = re.compile(r'[\\/:*?"<>|\x00]+')


async def _apply_spotify_meta(
        paths: list[tuple[str, dict, str | None]]) -> list[tuple[str, dict, str | None]]:
    """کلیدِ متادیتا روشن → تگ/کاورِ نهایی را با متادیتای اسپاتیفای بازنویسی می‌کند.

    خروجی: مسیرِ تازهٔ تگ‌خورده با نامِ «هنرمند - آهنگ». اگر نشد، فایلِ اصلی
    (متادیتای یوتیوب) نگه داشته می‌شود. تلگرام عنوان/هنرمند/کاور را از همین تگ می‌خواند.
    """
    out: list[tuple[str, dict, str | None]] = []
    for path, info, thumb in paths:
        sp = (info or {}).get("sp") or {}
        tags: dict[str, str] = {}
        for src, dst in (("title", "title"), ("artist", "artist"), ("album", "album"), ("year", "date")):
            if sp.get(src):
                tags[dst] = sp[src]
        if not tags:
            out.append((path, info, thumb))
            continue
        stem = _SP_NAME_RE.sub("_", f"{sp.get('artist', '')} - {sp.get('title', '')}".strip(" -"))[:100] or "track"
        newp = os.path.join(os.path.dirname(path), stem + os.path.splitext(path)[1])
        if os.path.abspath(newp) == os.path.abspath(path):
            newp = os.path.join(os.path.dirname(path), stem + ".sp" + os.path.splitext(path)[1])
        try:
            await P.write_audio_metadata(path, newp, tags, cover_path=sp.get("cover_path"))
            out.append((newp, info, thumb))
        except Exception:  # noqa: BLE001
            log.warning("spotify meta write failed for %s", path)
            out.append((path, info, thumb))
    return out


async def run_download(ctx: dict, payload: dict) -> None:
    bot: Bot = ctx["bot"]
    await textstore.refresh_if_stale()  # متن‌های ادمین‌ویرایش‌شده تازه بمانند
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
        await _edit(bot, chat_id, status_mid, t(lang, "dl_probing"))
        try:
            info = await D.probe(url, await _opts(redis, platform, workdir))
        except Exception as exc:  # noqa: BLE001
            await _metric(redis, platform, ok=False)
            msg = str(exc)
            if D.is_youtube_botcheck(msg, platform):
                await _edit(bot, chat_id, status_mid, t(lang, "dl_youtube_botcheck"))
            else:
                await _edit(bot, chat_id, status_mid,
                            t(lang, "dl_probe_failed") + f"\n<code>{escape(msg[:280])}</code>")
            return
        cap_min = await settings_store.get_int("dl_max_duration_min", settings.dl_max_duration_min)
        if cap_min > 0 and (info.get("duration") or 0) > cap_min * 60:
            await _edit(bot, chat_id, status_mid, t(lang, "dl_too_long", min=cap_min))
            return
        opts = info.get("options") or []
        if redis is not None and opts:
            try:
                await redis.set(f"probe:{ref}", json.dumps(opts), ex=1800)
            except Exception:  # noqa: BLE001
                pass
        title = (info.get("title") or "")[:80]
        caption = t(lang, "dl_pick_quality", title=title)
        kb = download_menu_kb(ref, opts, lang)
        thumb_url = info.get("thumbnail")
        # منو را روی عکسِ تامبنیل بفرست تا هنگامِ انتخاب، همان پیام درجا به ویدیو
        # تبدیل شود (editMessageMedia فقط روی پیامِ رسانه‌ای کار می‌کند، نه متن).
        if thumb_url:
            try:
                await bot.send_photo(chat_id, thumb_url, caption=caption, reply_markup=kb)
                try:
                    await bot.delete_message(chat_id, status_mid)
                except Exception:  # noqa: BLE001
                    pass
                return
            except Exception:  # noqa: BLE001
                pass  # تامبنیل نشد → منوی متنی
        await _edit(bot, chat_id, status_mid, caption, kb=kb)
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
        opts = await _opts(redis, platform, workdir)
        cookie = opts.get("cookies")  # مسیرِ اصلی؛ برای cooldown/متریک نگه‌داری می‌شود
        # نکته: کپیِ نوشتنیِ کوکی (چون /cookies فقط‌خواندنی است و yt-dlp کوکی‌جار را
        # برمی‌گرداند) حالا درونِ خودِ موتور انجام می‌شود — probe و download_ytdlp و
        # download_gallerydl هرکدام یک کپیِ نوشتنیِ موقت می‌سازند و پاک می‌کنند.

        # ── روایتِ زنده‌ی مراحل: اسپینرِ چرخان + درصد/زمانِ سپری‌شده ──
        # تیک‌زنِ پس‌زمینه هیچ‌وقت «قفل‌شده» به‌نظر نمی‌رسد — چه yt-dlp که درصد می‌دهد،
        # چه gallery-dl که نمی‌دهد (فقط اسپینر + زمان). نزدیکِ پایان → «لحظه‌های آخر».
        plabel = D.platform_label(platform, lang)
        # اسپاتیفای دانلودِ واقعی ندارد؛ روی یوتیوب تطبیق می‌دهد → برچسبِ گویاتر
        fetch_label = t(lang, "dl_matching") if engine == "spotify" else t(lang, "dl_fetching")
        narr = {"label": fetch_label, "pct": None, "eta": None}
        nstart = time.monotonic()

        async def _progress(pct: float) -> None:
            ip = int(pct)
            narr["pct"] = ip
            elapsed = time.monotonic() - nstart
            narr["eta"] = (elapsed / ip * (100 - ip)) if ip > 3 else None
            narr["label"] = t(lang, "dl_almost") if ip >= 92 else fetch_label

        async def _ticker() -> None:
            tick = 0
            while True:
                await asyncio.sleep(3.0)
                tick += 1
                try:
                    await _edit(bot, chat_id, status_mid,
                                progress_note(narr["label"], narr["pct"], narr["eta"],
                                              time.monotonic() - nstart, tick),
                                kb=download_cancel_kb(ref, lang))
                except Exception:  # noqa: BLE001
                    pass

        # فیدبکِ فوری قبل از اولین تیک تا فاصله‌ای بی‌وضعیت نمانَد
        await _edit(bot, chat_id, status_mid,
                    progress_note(t(lang, "dl_preparing"), None, None, 0, 0),
                    kb=download_cancel_kb(ref, lang))
        ticker = asyncio.create_task(_ticker())

        async def _stop_ticker() -> None:
            ticker.cancel()
            try:
                await ticker
            except BaseException:  # noqa: BLE001
                pass

        gallery_caption = None
        try:
            if engine == "gallerydl":
                files, gallery_caption = await D.download_gallerydl(
                    url, workdir, opts, progress=_progress, cancel=_cancelled)
                paths = [(p, {}, None) for p in files]
            elif engine == "spotify":
                # متادیتا از اسپاتیفای + تطبیق روی یوتیوب؛ کلیدِ متادیتا تعیین می‌کند تگ/کاورِ
                # نهایی از اسپاتیفای باشد (روشن) یا از یوتیوب بماند (پیش‌فرض/خاموش).
                paths = await D.download_spotify(url, workdir, opts,
                                                 progress=_progress, cancel=_cancelled)
                if await settings_store.get_bool("spotify_meta", settings.spotify_meta):
                    paths = await _apply_spotify_meta(paths)
            else:
                try:
                    path, info, thumb = await D.download_ytdlp(url, workdir, selector, opts,
                                                               progress=_progress, cancel=_cancelled)
                except P.ProcessingCancelled:
                    raise
                except Exception as ytdlp_exc:  # noqa: BLE001
                    # پلاگینِ pot-provider گاهی خودِ yt-dlp را می‌اندازد (تریس‌بکِ پایتون، نه خطای
                    # تمیز — مثلاً ناسازگاریِ نسخهٔ پلاگین با سرورِ pot). یک‌بار بدونِ pot دوباره
                    # تلاش کن: هم خطای واقعی (bot-check) تمیز بیرون می‌آید، هم اگر فقط pot خراب
                    # بوده، دانلود (به‌ویژه وقتی کوکیِ یوتیوب هست) موفق می‌شود.
                    retried = False
                    if opts.get("pot_provider"):
                        log.info("yt-dlp failed with pot-provider (%s); retrying without pot",
                                 str(ytdlp_exc)[:140])
                        try:
                            path, info, thumb = await D.download_ytdlp(
                                url, workdir, selector, {**opts, "pot_provider": None},
                                progress=_progress, cancel=_cancelled)
                            retried = True
                        except P.ProcessingCancelled:
                            raise
                        except Exception as exc2:  # noqa: BLE001
                            ytdlp_exc = exc2  # خطای تمیزِ بدونِ pot را به مسیرِ پایین بده
                    if not retried:
                        # fallback به Cobalt فقط روی شکستِ extractor (نه login/ban که کوکی می‌خواهد)
                        cobalt = settings.cobalt_url
                        if cobalt and not any(h in str(ytdlp_exc).lower() for h in _LOGIN_HINTS):
                            log.info("yt-dlp failed, trying cobalt: %s", str(ytdlp_exc)[:100])
                            path, info, thumb = await D.download_cobalt(url, workdir, cobalt, opts,
                                                                        progress=_progress, cancel=_cancelled)
                        else:
                            # صریح، نه `raise` خالی — چون ytdlp_exc را به خطای تمیزِ بدونِ pot
                            # عوض کرده‌ایم و raiseِ خالی خطای اصلیِ تریس‌بک را دوباره پرت می‌کند.
                            raise ytdlp_exc
                paths = [(path, info, thumb)]
        except P.ProcessingCancelled:
            await _stop_ticker()
            await _edit(bot, chat_id, status_mid, t(lang, "cancelled"))
            return
        except Exception as exc:  # noqa: BLE001
            await _stop_ticker()
            msg = str(exc)
            low = msg.lower()
            if any(h in low for h in _BAN_HINTS):
                await _cooldown_cookie(redis, cookie)
            await _metric(redis, platform, ok=False)
            if platform == "spotify" and D.is_youtube_botcheck(msg, "youtube"):
                # تطبیقِ اسپاتیفای از یوتیوب دانلود می‌کند؛ اگر یوتیوب bot-check داد، راهنمای کوکی
                await _edit(bot, chat_id, status_mid, t(lang, "dl_youtube_botcheck"))
            elif platform == "spotify" and any(
                    k in low for k in ("spotify", "could not read link", "no youtube", "no tracks", "blocked")):
                await _edit(bot, chat_id, status_mid,
                            t(lang, "dl_spotify_setup") + f"\n<code>{escape(msg[:200])}</code>")
            elif D.is_youtube_botcheck(msg, platform):
                await _edit(bot, chat_id, status_mid, t(lang, "dl_youtube_botcheck"))
            elif any(h in low for h in _LOGIN_HINTS):
                await _edit(bot, chat_id, status_mid, t(lang, "dl_need_cookies", platform=plabel))
            else:
                await _edit(bot, chat_id, status_mid,
                            t(lang, "dl_failed") + f"\n<code>{escape(msg[:280])}</code>")
            return
        await _stop_ticker()

        # سقفِ مدت (backstopِ quick-grab که probe نکرده) — قبل از آپلود
        cap_min = await settings_store.get_int("dl_max_duration_min", settings.dl_max_duration_min)
        if cap_min > 0:
            longest = max((int(i.get("duration") or 0) for _p, i, _t in paths), default=0)
            if longest > cap_min * 60:
                await _edit(bot, chat_id, status_mid, t(lang, "dl_too_long", min=cap_min))
                return

        # چکِ قطعیِ حجم روی دیسک قبل از آپلود (نقدِ #۱: --max-filesize کافی نیست)
        max_mb = await settings_store.get_int("dl_max_size_mb", settings.dl_max_size_mb)
        total = sum(os.path.getsize(p) for p, _i, _t in paths if os.path.exists(p))
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

        # مرحلهٔ پایانی: در حالِ ارسال به کاربر (آپلود به سرورِ لوکالِ Bot API)
        await _edit(bot, chat_id, status_mid, t(lang, "dl_uploading"))

        if engine == "gallerydl" and len(paths) > 1:
            # پستِ چند‌تایی (کاروسل) → Rich Message (مقاله‌ایِ ورق‌زدنی) یا آلبوم
            media_paths = [p for p, _i, _t in paths]
            delivered = False
            if await settings_store.get_bool("dl_rich_posts", settings.dl_rich_posts):
                try:
                    await _deliver_rich_post(bot, chat_id, owner_id, media_paths, gallery_caption, lang)
                    delivered = True
                except Exception as exc:  # noqa: BLE001
                    log.warning("rich post failed (%s); fallback به آلبوم", str(exc)[:120])
            if not delivered:
                await _deliver_album(bot, chat_id, owner_id, media_paths, gallery_caption, lang)
            try:
                await bot.delete_message(chat_id, status_mid)
            except Exception:  # noqa: BLE001
                pass
        elif engine != "gallerydl" and len(paths) == 1:
            # تک‌فایل → تحویلِ درجا روی همان پیامِ لنگرگاه + کش
            p, info, thumb = paths[0]
            await _deliver_single(bot, chat_id, status_mid, owner_id, p, os.path.basename(p),
                                  _kind_from_info(info, p), info, lang, thumb, url, selector)
        else:
            # تک‌عکسیِ گالری یا حالتِ نادرِ دیگر → کارتِ جدا برای هرکدام + حذفِ لنگرگاه
            for p, info, thumb in paths:
                kind = _kind_from_info(info, p)
                name = os.path.basename(p)
                if kind == "image" and not info.get("width"):
                    try:
                        from PIL import Image
                        with Image.open(p) as im:
                            info = {**info, "width": im.width, "height": im.height}
                    except Exception:  # noqa: BLE001
                        pass
                await _spawn(bot, chat_id, owner_id, p, name, kind, info, lang, thumb_path=thumb)
            try:
                await bot.delete_message(chat_id, status_mid)  # کارت‌ها جایگزینش شدند
            except Exception:  # noqa: BLE001
                pass

        await _metric(redis, platform, ok=True)
    finally:
        if redis is not None:
            try:
                await redis.decr("dl:active")
                await redis.delete(f"cancel:dl:{ref}")
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(workdir, ignore_errors=True)
        if settings.node_role:  # مشاهده‌پذیری: کارِ انجام‌شدهٔ این نودِ دانلود را بشمار
            from . import nodes
            nodes.note_job_done()
