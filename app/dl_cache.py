"""کشِ دانلودِ آنی (file_id).

اولین‌بار که یک (لینک، کیفیت) دانلود و فرستاده می‌شود، file_idِ تلگرام ذخیره
می‌شود؛ دفعهٔ بعد همان لینک+کیفیت **آنی** فرستاده می‌شود — بدونِ دانلودِ دوباره،
با تامبنیل/زمان/کپشنِ حفظ‌شده. کارتِ خروجی مثلِ همیشه ref و منوی عملیات دارد.

سه نکتهٔ طراحی:
- فقط **file_id** ذخیره می‌شود، نه بایت‌ها. تحویلِ مجدد آنی است و صفر پهنای‌باند و
  صفر دیسک مصرف می‌کند؛ نگه‌داشتنِ خودِ فایل‌ها هیچ سودِ سرعتی اضافه نمی‌کرد.
- کلید روی **URLِ نرمال‌شده** است (`_cache_url`)، وگرنه چهار شکلِ مختلفِ یک ویدیوی
  یوتیوب چهار ردیفِ جدا می‌ساختند و کش تقریباً هیچ‌وقت اصابت نمی‌کرد.
- کش فقط یک بهینه‌سازی است: اگر file_id باطل شده باشد ردیف پاک می‌شود و صداکننده
  به مسیرِ دانلودِ عادی برمی‌گردد (`deliver_from_cache` مقدارِ False می‌دهد).
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from html import escape
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputMediaPhoto, InputMediaVideo
from sqlalchemy.ext.asyncio import AsyncSession

from .cards import message_media_id, send_card, update_card
# `_MATCH_PLATFORMS` تنها منبعِ «هدف را ما انتخاب می‌کنیم» است (`downloader.py:53`)
# و `engine_for` هم از همان می‌خواند — فهرستِ دومی این‌جا ساخته نمی‌شود، وگرنه دو
# کپیِ دست‌نویس واگرا می‌شدند. حلقهٔ import نیست: `downloader` هیچ ارجاعی به
# `dl_cache` ندارد (تست `test_no_import_cycle` همین را نگه می‌دارد).
from .downloader import _MATCH_PLATFORMS, platform_of, spotify_id
from .models import DownloadCache, File

log = logging.getLogger("telabzar.dlcache")

# شناسهٔ محتوا برای پلتفرم‌های اصلی → همهٔ شکل‌های URL به یک کلید می‌رسند
_YT_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|embed/|live/|v/))"
    r"([A-Za-z0-9_-]{11})")
_IG_RE = re.compile(r"instagram\.com/(?:[^/]+/)?(?:p|reels?|tv)/([A-Za-z0-9_-]+)")
_X_RE = re.compile(r"(?:twitter|x)\.com/[^/]+/status/(\d+)")
_TT_RE = re.compile(r"tiktok\.com/@[^/]+/video/(\d+)")

# پارامترهای «به‌اشتراک‌گذاری/ترکینگ» که محتوا را عوض نمی‌کنند. عمداً فهرستِ **بسته**:
# پارامترِ ناشناخته حفظ می‌شود، چون بدترین حالتِ نگه‌داشتن یک miss است ولی بدترین
# حالتِ حذفِ اشتباه، تحویلِ فایلِ **غلط** است.
_DROP_PARAMS = {
    "si", "igsh", "igshid", "fbclid", "gclid", "feature", "ref", "ref_src", "ref_url",
    "s", "t", "_r", "_t", "is_from_webapp", "sender_device", "share_app_id",
    "share_link_id", "spm", "source",
}


def _cache_url(url: str) -> str:
    """URL → شناسهٔ محتواییِ پایدار (برای کلیدِ کش)."""
    u = (url or "").strip()
    for prefix, rx in (("yt", _YT_RE), ("ig", _IG_RE), ("x", _X_RE), ("tt", _TT_RE)):
        m = rx.search(u)
        if m:
            return f"{prefix}:{m.group(1)}"
    # اسپاتیفای: شناسهٔ ترک/آلبوم/پلی‌لیست محتوا را کامل تعیین می‌کند، پس مسیرِ
    # زبانی و کوئری بی‌اهمیت‌اند — همان استدلالِ `yt:`/`ig:` بالا. از `spotify_id`
    # استفاده می‌شود نه الگوی تازه، تا دو کپی واگرا نشوند.
    #
    # **چه چیزی را رفع می‌کند، اندازه‌گیری‌شده:** `intl-fa/track/X` و
    # `intl-de/track/X` امروز کلیدِ **متفاوتی** از `track/X` می‌گیرند، و
    # اسپاتیفای همین مسیرِ زبانی را به کاربرِ غیرِانگلیسی می‌دهد؛ و پارامترهای
    # اشتراکِ ناشناخته مثلِ `?go=1&nd=1` هم کلید را جدا می‌کردند. سه کلید → یک کلید.
    #
    # **چه چیزی را رفع نمی‌کند، چون خراب نبود:** `?si=…` که اپِ اسپاتیفای موقعِ
    # Copy link می‌گذارد از قبل درست کش می‌شد — `si` عضوِ `_DROP_PARAMS` است، پس
    # هر توکنِ تصادفی به یک کلید می‌رسید. فرضِ «کشِ اسپاتیفای هرگز hit نمی‌خورد»
    # با اجرا رد شد.
    kind, sid = spotify_id(u)
    if kind and sid:
        return f"sp:{kind}:{sid}"   # kind را نگه می‌دارد تا ترک و پلی‌لیست قاتی نشوند
    try:
        p = urlsplit(u)
    except ValueError:
        return u.lower()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
          if k.lower() not in _DROP_PARAMS and not k.lower().startswith("utm_")]
    query = "&".join(f"{k}={v}" for k, v in sorted(qs))
    path = p.path.rstrip("/") or "/"
    return urlunsplit(("", host, path, query, ""))  # اسکیم و فرگمنت بی‌اهمیت‌اند


# نسخهٔ منطقِ **تطبیق**. فقط برای پلتفرم‌هایی که هدف را خودمان انتخاب می‌کنیم
# (`downloader._MATCH_PLATFORMS`) واردِ کلید می‌شود. بالا بردنش ردیف‌های آن
# پلتفرم‌ها را کنار می‌گذارد بدونِ اینکه به بقیهٔ کش دست بزند.
#
# **چرا سراسری نیست:** کش `file_id` نگه می‌دارد نه بایت، پس ردیفِ کهنه پهنای‌باند
# خرج نمی‌کند — فایلِ **غلط** تحویل می‌دهد. و برای لینکِ یوتیوب چیزی برای غلط
# بودن نیست: شناسهٔ کش‌شده دقیقاً همان است که URL نام می‌برد و هیچ تصمیمی از ما
# در آن نیست. نسخهٔ سراسری ردیف‌های سالم را برای مشکلی که هرگز نداشتند دور
# می‌ریخت.
#
# **بالا بردنش دستی است، و یک تست جلوی کهنه‌شدنش را می‌گیرد:**
# `tests/test_spotify_match_fingerprint.py` رفتارِ ماچر **و** خروجیِ پارسر را
# روی فیکسچرِ ثابت هش می‌کند و پین نگه می‌دارد، پس هر تغییری که جواب را عوض کند
# تست را می‌شکند و نویسنده مجبور می‌شود آگاهانه این عدد را ببرد بالا.
_MATCH_VERSION = 1


def _we_choose_the_target(url: str) -> bool:
    """این پلتفرم را ما به یوتیوب تطبیق می‌دهیم (یعنی جواب به منطقِ ما بند است)؟"""
    return platform_of(url or "") in _MATCH_PLATFORMS


def cache_key(url: str, selector: str) -> str:
    base = f"{_cache_url(url)}\n{selector}"
    if _we_choose_the_target(url):
        base = f"{base}\nm{_MATCH_VERSION}"
    return hashlib.sha1(base.encode()).hexdigest()[:64]


def _legacy_key(url: str, selector: str) -> str:
    """کلیدِ نسخهٔ قبل (URLِ خام) — تا کشِ موجود با این تغییر بی‌ارزش نشود."""
    return hashlib.sha1(f"{url}\n{selector}".encode()).hexdigest()[:64]


async def get_cached(session: AsyncSession, url: str, selector: str) -> DownloadCache | None:
    """ردیفِ کش برای این (لینک، کیفیت) — با مهاجرتِ خودکارِ کلیدهای قدیمی."""
    key = cache_key(url, selector)
    row = await session.get(DownloadCache, key)
    if row is not None:
        return row
    # **برای پلتفرم‌های تطبیقی fallbackِ legacy رد می‌شود، وگرنه کلِ نسخه‌دارکردن
    # بی‌اثر است.** اندازه‌گیری‌شده: برای URLِ اسپاتیفای `cache_key` و
    # `_legacy_key` **از قبل** متفاوت‌اند (`_cache_url` اسکیم را می‌ریزد)، پس
    # مسیر این بود: کلیدِ نسخه‌دار → miss → اصابت روی ردیفِ خامِ کهنه → مهاجرت
    # به کلیدِ نو → همان جوابِ غلط، این‌بار زیرِ کلیدِ تازه. یعنی بمپِ نسخه صفر
    # اثر داشت و بدتر: ردیفِ کهنه را «تازه» می‌کرد.
    if _we_choose_the_target(url):
        return None
    old = _legacy_key(url, selector)
    if old == key:
        return None
    row = await session.get(DownloadCache, old)
    if row is None:
        return None
    # اصابتِ کلیدِ قدیمی → همان داده را زیرِ کلیدِ نرمال‌شده هم بنویس (یک‌بار)
    session.add(DownloadCache(
        key=key, file_id=row.file_id, file_unique_id=row.file_unique_id, kind=row.kind,
        name=row.name, size=row.size, width=row.width, height=row.height,
        duration=row.duration, post_caption=row.post_caption, platform=row.platform,
        items=row.items, hits=row.hits or 0,
    ))
    await session.commit()
    return row


async def _upsert(session: AsyncSession, url: str, selector: str, **vals) -> None:
    key = cache_key(url, selector)
    row = await session.get(DownloadCache, key)
    if row is None:
        session.add(DownloadCache(key=key, **vals))
    else:
        for k, v in vals.items():
            setattr(row, k, v)
    await session.commit()


async def put_cached(session: AsyncSession, url: str, selector: str, f: File) -> None:
    """تک‌فایل را کش کن — **هر نوعی** (ویدیو، صوت، عکس، سند، PDF، آرشیو)."""
    if not f.file_id:
        return
    await _upsert(session, url, selector, file_id=f.file_id, file_unique_id=f.file_unique_id,
                  kind=f.kind, name=f.name, size=f.size, width=f.width, height=f.height,
                  duration=f.duration, post_caption=f.post_caption, platform=f.platform,
                  items=None)


async def put_album_cached(session: AsyncSession, url: str, selector: str, items: list[dict],
                           caption: str | None = None, platform: str | None = None) -> None:
    """کاروسل/آلبوم را کش کن: فهرستِ مرتبِ file_idها در یک ردیف."""
    items = [i for i in (items or []) if i.get("file_id")]
    if len(items) < 2:
        return
    first = items[0]
    await _upsert(session, url, selector, file_id=first["file_id"],
                  file_unique_id=first.get("file_unique_id"), kind=first.get("kind") or "image",
                  name=None, size=sum(int(i.get("size") or 0) for i in items) or None,
                  width=None, height=None, duration=None,
                  post_caption=caption, platform=platform, items=items)


def _media_for(item: dict, caption: str | None = None):
    """آیتمِ کش‌شده → InputMedia با file_id (بدونِ آپلودِ دوباره).

    کپشن باید سرِ **ساخت** داده شود؛ مدل‌های InputMedia در aiogram frozen‌اند.
    """
    cls = InputMediaVideo if (item.get("kind") == "video") else InputMediaPhoto
    return cls(media=item["file_id"], caption=caption) if caption else cls(media=item["file_id"])


async def _drop(session: AsyncSession, cache: DownloadCache, why: str) -> None:
    log.warning("dropping stale cache row (%s): %s", cache.kind, why)
    try:
        await session.delete(cache)
        await session.commit()
    except Exception:  # noqa: BLE001
        pass


async def deliver_from_cache(bot: Bot, session: AsyncSession, chat_id: int, owner_id: int,
                             cache: DownloadCache, lang: str,
                             anchor_mid: int | None = None) -> bool:
    """تحویلِ آنی از کش. True = تحویل شد · False = file_id باطل بود و ردیف پاک شد
    (صداکننده باید به دانلودِ عادی برگردد؛ کش هرگز نباید دانلود را بشکند)."""
    if cache.items:
        return await _deliver_album_cached(bot, session, chat_id, cache)
    f = File(
        ref=secrets.token_urlsafe(6)[:8], owner_id=owner_id,
        file_unique_id=cache.file_unique_id or "", file_id=cache.file_id,
        kind=cache.kind, mime=None, name=cache.name, size=cache.size,
        width=cache.width, height=cache.height, duration=cache.duration,
        changelog=[], source="dl", post_caption=cache.post_caption, platform=cache.platform,
    )
    session.add(f)
    await session.commit()
    try:
        if anchor_mid is not None:
            await update_card(bot, chat_id, anchor_mid, f, lang)  # لنگرگاه → فایل، درجا
        else:
            await send_card(bot, chat_id, f, lang)
    except TelegramBadRequest as exc:
        await session.delete(f)
        await _drop(session, cache, str(exc)[:120])
        return False
    cache.hits = (cache.hits or 0) + 1   # سودِ کش قابلِ‌سنجش شود (صفحهٔ آمار)
    await session.commit()
    return True


async def _deliver_album_cached(bot: Bot, session: AsyncSession, chat_id: int,
                                cache: DownloadCache) -> bool:
    """کاروسلِ کش‌شده → همان آلبومِ تلگرام، از روی file_idها."""
    items = list(cache.items or [])
    # parse_mode=HTML است و متنِ پست خام ذخیره می‌شود → مثلِ مسیرِ آلبومِ تازه escape شود
    cap = escape(cache.post_caption) if cache.post_caption else None
    try:
        for gi in range(0, len(items), 10):        # سقفِ ۱۰ آیتم در هر media group
            chunk = items[gi:gi + 10]
            batch = [_media_for(it, cap if (gi == 0 and n == 0) else None)
                     for n, it in enumerate(chunk)]
            await bot.send_media_group(chat_id, media=batch)
    except TelegramBadRequest as exc:
        await _drop(session, cache, str(exc)[:120])
        return False
    cache.hits = (cache.hits or 0) + 1
    await session.commit()
    return True


def collect_album_items(messages) -> list[dict]:
    """پیام‌های ارسال‌شدهٔ آلبوم → آیتم‌های قابلِ‌کش (file_id + نوع + حجم)."""
    items: list[dict] = []
    for msg in messages or []:
        fid, fuid = message_media_id(msg)
        if not fid:
            continue
        kind = "video" if getattr(msg, "video", None) else "image"
        obj = getattr(msg, "video", None) or (msg.photo[-1] if getattr(msg, "photo", None) else None)
        items.append({"file_id": fid, "file_unique_id": fuid, "kind": kind,
                      "size": getattr(obj, "file_size", None) if obj is not None else None})
    return items
