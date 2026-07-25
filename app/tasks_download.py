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

from . import cookies as ck
from . import dl_cache
from . import downloader as D
from . import processing as P
from . import settings_store
from . import textstore
from .cards import message_media_id, progress_note, send_card, update_card
from .config import settings
from .db import Sessionmaker
from .i18n import t
from .keyboards import cookie_attention_kb, download_cancel_kb, download_menu_kb
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


def _is_cookie_error(msg: str, platform: str | None = None) -> bool:
    """آیا این خطا «کوکی‌محور» است (لاگین/بن/بات‌چک) و ارزشِ تلاش با اکانتِ دیگر را دارد؟
    خطاهای غیرِکوکی (ویدیوی خصوصی، ۴۰۴، حجم/مدت) نباید استخر را بسوزانند."""
    low = (msg or "").lower()
    if D.is_youtube_botcheck(msg, platform):
        return True
    return any(h in low for h in _BAN_HINTS) or any(h in low for h in _LOGIN_HINTS)


# یوتیوب بدونِ لاگین ~۳۰۰ ویدیو در ساعت می‌دهد (با لاگین ~۲۰۰۰). پس چسباندنِ کوکی به
# **هر** دانلود فقط اکانت را می‌سوزاند بدونِ اینکه لازم باشد. این پلتفرم‌ها اول ناشناس
# تلاش می‌شوند و کوکی تنها وقتی می‌آید که خودِ سرویس بخواهد.
_ANON_FIRST = {"youtube", "spotify", "tiktok", "pinterest", "other"}


def _anon_first(platform: str) -> bool:
    return platform in _ANON_FIRST


def _cookie_platform(platform: str) -> str:
    """اسپاتیفای دانلودِ واقعی را از یوتیوب می‌گیرد → کوکیِ یوتیوب لازم است، نه اسپاتیفای."""
    return "youtube" if platform == "spotify" else platform


async def _next_cookie(redis, platform: str, workdir: str | None,
                       tried: set[str]) -> tuple[str | None, str | None]:
    """(نامِ اکانت, مسیرِ فایل) برای تلاشِ بعدی — یا (None, None) اگر کوکیِ دیگری نماند.

    استخر (اولویت/کول‌داون/سهمیه/پینِ خروجی) در `app/cookies.py` است؛ این‌جا فقط
    materialize می‌شود. `node_id` = خروجیِ فعلیِ این ورکر، تا اکانت همیشه از همان
    IP بیرون برود که به آن پین شده.
    """
    name = await ck.pick(redis, _cookie_platform(platform), exclude=tried,
                         node_id=settings.node_id or "")
    if not name:
        return None, None
    path = await ck.materialize(redis, name, workdir)
    if not path:            # محتوا در دسترس نبود → همین را رد کن و بعدی را بگیر
        tried.add(name)
        return await _next_cookie(redis, platform, workdir, tried)
    await ck.note_use(redis, name)   # سطلِ ساعتی + مهرِ فاصلهٔ حداقلی
    return name, path


async def _alert_if_low(redis, bot, platform: str) -> None:
    """اگر اکانت‌های قابلِ‌استفادهٔ این پلتفرم زیرِ آستانه رفت، به ادمین‌ها خبر بده
    (ضدِ‌اسپم: هر پلتفرم حداکثر هر ۶ ساعت یک‌بار)."""
    if redis is None:
        return
    try:
        thr = await settings_store.get_int("cookie_alert_min", settings.cookie_alert_min)
        if thr <= 0:
            return
        left = await ck.healthy_count(redis, platform)
        if left >= thr:
            return
        if not await redis.set(f"ckalert:{platform}", "1", ex=6 * 3600, nx=True):
            return  # تازه خبر داده‌ایم
        label = D.platform_label(platform, "fa")
        text = (f"🍪 <b>هشدارِ کوکی</b>\n\nاکانت‌های سالمِ «{label}»: <b>{left}</b> "
                f"(آستانه: {thr}).\nاز پنل → کوکی‌ها یک کوکیِ تازه بچسبان."
                if left else
                f"🔴 <b>هیچ کوکیِ سالمی برای «{label}» نمانده</b>\n\n"
                f"دانلودِ این پلتفرم تا افزودنِ کوکیِ تازه کار نمی‌کند.")
        for aid in settings.admin_id_set:
            try:
                await bot.send_message(aid, text)
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        log.debug("cookie alert skipped: %s", exc)


async def _alert_checkpoint(redis, bot, name: str, platform: str, msg: str) -> None:
    """اکانت چک‌پوینت/۲FA خورد → این با تلاشِ خودکار حل نمی‌شود؛ ادمین را صدا بزن.

    پیام سه دکمه دارد و ادمین می‌تواند کوکیِ تازه را **همان‌جا در تلگرام** بچسباند
    (بدونِ بازکردنِ پنل) — همان «جایی که انسان وارد عمل می‌شود».
    """
    if redis is None:
        return
    try:
        if not await redis.set(f"ckcheck:{name}", "1", ex=6 * 3600, nx=True):
            return                                  # تازه خبر داده‌ایم
        meta = await ck.get_meta(redis, name)
        label = escape(str(meta.get("label") or name))
        # نامِ فایل می‌تواند سقفِ ۶۴ بایتِ callback را بشکند → توکنِ کوتاه در Redis
        tok = secrets.token_urlsafe(6)[:8]
        await redis.set(f"cktok:{tok}", name, ex=7 * 86400)
        text = (f"🛑 <b>اکانت نیازِ رسیدگی دارد</b>\n\n"
                f"پلتفرم: {D.platform_label(platform, 'fa')}\n"
                f"اکانت: <b>{label}</b>\n"
                f"دلیل: چک‌پوینت/تأییدِ هویت — با تلاشِ دوباره حل نمی‌شود.\n"
                f"<code>{escape(' '.join((msg or '').split())[:160])}</code>\n\n"
                f"تا رسیدگی، این اکانت کنار گذاشته شد و بقیه کار می‌کنند.")
        for aid in settings.admin_id_set:
            try:
                await bot.send_message(aid, text, reply_markup=cookie_attention_kb(tok))
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        log.debug("checkpoint alert skipped: %s", exc)


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


async def _opts(redis, platform: str, workdir: str | None = None,
                cookie_path: str | None = None, identity: dict | None = None) -> dict:
    """گزینه‌های موتور. کوکی **صریح** پاس داده می‌شود (انتخابش با حلقهٔ تلاش در
    `run_download` است تا بتواند روی خطا کوکیِ بعدی را امتحان کند).

    `identity` = متادیتای همان اکانت. پروکسی و User-Agentِ اختصاصیِ اکانت (اگر ست
    شده باشند) جای مقادیرِ عمومی را می‌گیرند: یک سشن باید همیشه از یک IP و با یک
    UA دیده شود، وگرنه خودِ ناسازگاری سیگنالِ تشخیص می‌شود.
    """
    pot_on = await settings_store.get_bool("dl_pot_enabled", settings.dl_pot_enabled)
    ident = identity or {}
    return {
        "proxy": (ident.get("proxy")
                  or await settings_store.get_str("proxy_url", settings.proxy_url) or None),
        "user_agent": ident.get("user_agent") or None,
        "pot_provider": (settings.pot_provider_url or None) if pot_on else None,
        "cookies": cookie_path,
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
                         caption: str | None, lang: str) -> list[dict]:
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
        return []
    cap_text = D.clean_caption(caption)  # تضمینِ بدونِ‌هشتگ + سقفِ ۱۰۲۴ (idempotent)
    cap = escape(cap_text) if cap_text else None  # parse_mode=HTML → کپشنِ کاربر escape شود
    items: list[dict] = []
    for gi in range(0, len(media), 10):  # سقفِ ۱۰ آیتم در هر media group
        batch = media[gi:gi + 10]
        b = MediaGroupBuilder(caption=cap if gi == 0 else None)
        for p in batch:
            if p.lower().endswith(_ALBUM_VID):
                b.add_video(media=FSInputFile(p))
            else:
                b.add_photo(media=FSInputFile(p))
        try:
            sent = await bot.send_media_group(chat_id, media=b.build())
            items += dl_cache.collect_album_items(sent)   # برای کشِ کاروسل
        except Exception:  # noqa: BLE001
            log.exception("album send failed (batch starting %d)", gi)
    return items


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


async def _media_meta(path: str, kind: str, info: dict,
                      thumb_path: str | None) -> tuple[str, dict, str | None]:
    """درِ ورودیِ **همهٔ** فایل‌های دانلودی به pipeline → (مسیرِ نهایی, info کامل, تامبنیل).

    سه تضمین، مستقل از موتور (yt-dlp / gallery-dl / cobalt / spotify):
      ۱) ویدیو همیشه در کانتینرِ **mp4** تحویل می‌شود (تلگرام فقط mp4 را تضمین می‌کند).
      ۲) ابعاد/مدت از خودِ فایل خوانده می‌شود — gallery-dl (اینستاگرام/توییتر) هیچ info
         برنمی‌گرداند و yt-dlp هم گاهی ناقص است؛ بدونِ این، زمانِ ۰:۰۰ نمایش داده می‌شود.
      ۳) اگر تامبنیل نداریم، پوسترِ ≤۳۲۰px از خودِ ویدیو ساخته می‌شود (کاور).
    """
    if kind == "video":
        path = await D._ensure_mp4(path)
    if kind in ("video", "audio") and not (
            info.get("duration") and (kind == "audio" or (info.get("width") and info.get("height")))):
        probed = await P.probe_media(path)
        if probed:
            info = {**info, **{k: v for k, v in probed.items() if not info.get(k)}}
    if kind == "image" and not info.get("width"):
        try:
            from PIL import Image
            with Image.open(path) as im:
                info = {**info, "width": im.width, "height": im.height}
        except Exception:  # noqa: BLE001
            pass
    if kind == "video" and not thumb_path:
        poster = os.path.join(os.path.dirname(path) or ".", f"poster-{secrets.token_hex(4)}.jpg")
        if await P.video_poster(path, poster):
            thumb_path = poster
    return path, info, thumb_path


def _post_text(info: dict, gallery_caption: str | None) -> str | None:
    """متنِ اصلیِ پستِ مبدأ برای حالتِ **جمع‌شدهٔ** کارت — خام و بدونِ HTML.

    اینستاگرام/توییتر: کپشنِ پست از سایدکارِ gallery-dl (تا امروز فقط آلبوم از آن
    استفاده می‌کرد و برای تک‌فایل دور ریخته می‌شد).
    یوتیوب: عنوان + کانال + توضیحات.
    `clean_caption` هشتگ‌ها را حذف، خطوطِ اضافه را جمع و روی سقفِ ۱۰۲۴ کاراکترِ
    تلگرام برش می‌زند. escape سرِ رندر انجام می‌شود (`cards.post_view`).
    """
    if gallery_caption:
        return D.clean_caption(gallery_caption)
    lines: list[str] = []
    title = (info.get("title") or "").strip()
    if title:
        lines.append(title)
    who = (info.get("uploader") or info.get("channel") or "").strip()
    if who and who != title:
        lines.append(who)
    desc = (info.get("description") or "").strip()
    if desc and desc != title:
        lines += ["", desc]
    return D.clean_caption("\n".join(lines)) if lines else None


async def _spawn(bot: Bot, chat_id: int, owner_id: int, path: str, name: str,
                 kind: str, info: dict, lang: str, thumb_path: str | None = None,
                 post_caption: str | None = None, platform: str | None = None,
                 url: str | None = None, selector: str | None = None) -> None:
    """فایلِ دانلودی را وارد pipeline می‌کند (الگوی spawn) با source='dl'.
    url/selector اگر داده شوند، نتیجه کش می‌شود (مسیرِ gallery-dl از این‌جا می‌آید)."""
    path, info, thumb_path = await _media_meta(path, kind, info, thumb_path)
    name = os.path.basename(path)   # remux ممکن است پسوند را به mp4 عوض کرده باشد
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
            changelog=[], source="dl", post_caption=post_caption, platform=platform,
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
            if url and f.file_id:
                await dl_cache.put_cached(s, url, selector or "best", f)  # دفعهٔ بعد آنی
        except Exception:  # noqa: BLE001
            log.exception("dl spawn-card send failed")
        await s.commit()


async def _deliver_single(bot: Bot, chat_id: int, anchor_mid: int, owner_id: int, p: str,
                          name: str, kind: str, info: dict, lang: str, thumb_path: str | None,
                          url: str, selector: str, post_caption: str | None = None,
                          platform: str | None = None) -> None:
    """تک‌فایل را **درجا** روی پیامِ لنگرگاه تحویل می‌دهد (عکسِ منو → ویدیو) و
    file_id را برای دفعهٔ بعد کش می‌کند. اگر لنگرگاه متنی بود، update_card خودش
    کارتِ تازه می‌فرستد و قدیمی را پاک می‌کند."""
    p, info, thumb_path = await _media_meta(p, kind, info, thumb_path)
    name = os.path.basename(p)      # remux ممکن است پسوند را به mp4 عوض کرده باشد
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
            changelog=[], source="dl", post_caption=post_caption, platform=platform,
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
        # مثلِ fetch: اگر کوکی خطا داد، کوکیِ بعدی امتحان می‌شود.
        info, msg, tried = None, "", set()
        while True:
            cname, cpath = await _next_cookie(redis, platform, workdir, tried)
            try:
                info = await D.probe(url, await _opts(redis, platform, workdir, cpath))
                await ck.mark_ok(redis, cname)
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if cname and _is_cookie_error(msg, platform):
                    await ck.mark_fail(redis, cname)
                    tried.add(cname)
                    await _alert_if_low(redis, bot, _cookie_platform(platform))
                    if await ck.pick(redis, _cookie_platform(platform), exclude=tried):
                        log.info("probe: cookie %s failed, trying next", cname)
                        continue
                break
        if info is None:
            shutil.rmtree(workdir, ignore_errors=True)  # کوکیِ materialize‌شدهٔ نود
            await _metric(redis, platform, ok=False)
            if D.is_youtube_botcheck(msg, platform):
                await _edit(bot, chat_id, status_mid, t(lang, "dl_youtube_botcheck"))
            else:
                await _edit(bot, chat_id, status_mid,
                            t(lang, "dl_probe_failed") + f"\n<code>{escape(msg[:280])}</code>")
            return
        shutil.rmtree(workdir, ignore_errors=True)  # probe چیزی نگه نمی‌دارد
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
        # نکته: کوکی داخلِ «حلقهٔ تلاش» پایین انتخاب می‌شود (تا روی خطا اکانتِ بعدی
        # امتحان شود). کپیِ نوشتنیِ کوکی (چون /cookies فقط‌خواندنی است و yt-dlp کوکی‌جار را
        # برمی‌گرداند) درونِ خودِ موتور انجام می‌شود — probe/download_ytdlp/download_gallerydl
        # هرکدام یک کپیِ نوشتنیِ موقت می‌سازند و پاک می‌کنند.

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
        # ── حلقهٔ تلاش با چرخشِ اکانت ──
        # اگر کوکیِ فعلی خطای لاگین/بن داد، اکانت را علامت‌دار و **با کوکیِ بعدی** دوباره
        # تلاش می‌کنیم. فقط وقتی هیچ کوکیِ قابلِ‌استفاده‌ای نماند به کاربر خطا می‌دهیم.
        paths, dl_err, tried = None, None, set()
        # پاسِ اول **ناشناس** برای پلتفرم‌هایی که بدونِ لاگین جواب می‌دهند (یوتیوب و…):
        # کوکی فقط وقتی می‌آید که خودِ سرویس بخواهد → اکانت‌ها بی‌دلیل نمی‌سوزند.
        anon = (_anon_first(platform)
                and await settings_store.get_bool("dl_cookie_when_needed",
                                                  settings.dl_cookie_when_needed))
        while True:
            if anon:
                cookie_name, cookie_path = None, None
            else:
                cookie_name, cookie_path = await _next_cookie(redis, platform, workdir, tried)
            ident = await ck.get_meta(redis, cookie_name) if cookie_name else None
            opts = await _opts(redis, platform, workdir, cookie_path, identity=ident)
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
                await ck.mark_ok(redis, cookie_name)   # این اکانت سالم است
                break
            except P.ProcessingCancelled:
                await _stop_ticker()
                await _edit(bot, chat_id, status_mid, t(lang, "cancelled"))
                return
            except Exception as exc:  # noqa: BLE001
                dl_err = exc
                cls = ck.classify_error(str(exc))
                if anon:
                    # ناشناس نشد → حالا (و فقط حالا) سراغِ کوکی برو. هیچ اکانتی مقصر نیست.
                    anon = False
                    if cls != ck.UNRELATED and await ck.pick(redis, _cookie_platform(platform)):
                        log.info("anonymous attempt failed (%s); retrying with a cookie", cls)
                        continue
                    break
                if cookie_name and _is_cookie_error(str(exc), platform):
                    # واکنش به **دستهٔ** خطا: محدودیتِ نرخ ضربه نمی‌زند، چک‌پوینت فریز می‌کند
                    await ck.mark_fail(redis, cookie_name, error_class=cls, message=str(exc))
                    if ck.needs_human(cls):
                        await _alert_checkpoint(redis, bot, cookie_name,
                                                _cookie_platform(platform), str(exc))
                    tried.add(cookie_name)
                    await _alert_if_low(redis, bot, _cookie_platform(platform))
                    if await ck.pick(redis, _cookie_platform(platform), exclude=tried):
                        log.info("cookie %s failed (%s); retrying with next account",
                                 cookie_name, str(exc)[:90])
                        # نیمه‌کاره‌های تلاشِ قبلی را پاک کن تا با خروجیِ تلاشِ بعدی قاطی نشود
                        for _n in os.listdir(workdir):
                            if _n != "ck":
                                _p = os.path.join(workdir, _n)
                                shutil.rmtree(_p, ignore_errors=True) if os.path.isdir(_p) \
                                    else os.remove(_p)
                        await _edit(bot, chat_id, status_mid,
                                    progress_note(t(lang, "dl_retry_account"), None, None,
                                                  time.monotonic() - nstart, 0),
                                    kb=download_cancel_kb(ref, lang))
                        continue      # ← کوکیِ بعدی
                break                 # کوکیِ دیگری نمانده (یا خطا کوکی‌محور نبود)

        if paths is None:
            await _stop_ticker()
            msg = str(dl_err) if dl_err else "download failed"
            low = msg.lower()
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
                items = await _deliver_album(bot, chat_id, owner_id, media_paths,
                                             gallery_caption, lang)
                if items:   # کاروسل هم کش می‌شود → بارِ بعد آنی، بدونِ دانلود
                    try:
                        async with Sessionmaker() as cs:
                            await dl_cache.put_album_cached(
                                cs, url, selector, items,
                                caption=D.clean_caption(gallery_caption), platform=platform)
                    except Exception:  # noqa: BLE001
                        log.warning("album cache write failed", exc_info=True)
            try:
                await bot.delete_message(chat_id, status_mid)
            except Exception:  # noqa: BLE001
                pass
        elif engine != "gallerydl" and len(paths) == 1:
            # تک‌فایل → تحویلِ درجا روی همان پیامِ لنگرگاه + کش
            p, info, thumb = paths[0]
            await _deliver_single(bot, chat_id, status_mid, owner_id, p, os.path.basename(p),
                                  _kind_from_info(info, p), info, lang, thumb, url, selector,
                                  post_caption=_post_text(info, gallery_caption),
                                  platform=platform)
        else:
            # تک‌عکسیِ گالری یا حالتِ نادرِ دیگر → کارتِ جدا برای هرکدام + حذفِ لنگرگاه
            for p, info, thumb in paths:
                # ابعاد/مدت/کاور را خودِ _spawn از فایل کامل می‌کند (_media_meta)
                await _spawn(bot, chat_id, owner_id, p, os.path.basename(p),
                             _kind_from_info(info, p), info, lang, thumb_path=thumb,
                             post_caption=_post_text(info, gallery_caption),
                             platform=platform,
                             # تک‌فایلِ گالری (ریلز/عکسِ تکی) هم کش شود
                             url=url if len(paths) == 1 else None, selector=selector)
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
