"""کشِ دانلودِ آنی (file_id).

اولین‌بار که یک (لینک، کیفیت) دانلود و فرستاده می‌شود، file_idِ تلگرام ذخیره
می‌شود؛ دفعهٔ بعد همان لینک+کیفیت **آنی** با همان file_id فرستاده می‌شود — بدونِ
دانلودِ دوباره، با تامبنیل/زمانِ حفظ‌شده. کارتِ خروجی مثلِ همیشه ref و منوی عملیات دارد.
"""
from __future__ import annotations

import hashlib
import secrets

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from .cards import send_card, update_card
from .models import DownloadCache, File


def cache_key(url: str, selector: str) -> str:
    return hashlib.sha1(f"{url}\n{selector}".encode()).hexdigest()[:64]


async def get_cached(session: AsyncSession, url: str, selector: str) -> DownloadCache | None:
    return await session.get(DownloadCache, cache_key(url, selector))


async def put_cached(session: AsyncSession, url: str, selector: str, f: File) -> None:
    """فقط تک‌فایلِ ویدیو/صوت با file_id معتبر کش می‌شود (نه گالری)."""
    if not f.file_id or f.kind not in ("video", "audio"):
        return
    key = cache_key(url, selector)
    row = await session.get(DownloadCache, key)
    if row is None:
        session.add(DownloadCache(
            key=key, file_id=f.file_id, file_unique_id=f.file_unique_id, kind=f.kind,
            name=f.name, size=f.size, width=f.width, height=f.height, duration=f.duration,
        ))
    else:
        row.file_id, row.file_unique_id = f.file_id, f.file_unique_id
        row.kind, row.name, row.size = f.kind, f.name, f.size
        row.width, row.height, row.duration = f.width, f.height, f.duration
    await session.commit()


async def deliver_from_cache(bot: Bot, session: AsyncSession, chat_id: int, owner_id: int,
                             cache: DownloadCache, lang: str, anchor_mid: int | None = None) -> None:
    """کارتِ دانلودی را آنی از روی file_idِ کش‌شده می‌سازد و می‌فرستد.
    اگر anchor_mid بدهی (پیامِ منوی عکس)، درجا آن را به ویدیو تبدیل می‌کند."""
    f = File(
        ref=secrets.token_urlsafe(6)[:8], owner_id=owner_id,
        file_unique_id=cache.file_unique_id or "", file_id=cache.file_id,
        kind=cache.kind, mime=None, name=cache.name, size=cache.size,
        width=cache.width, height=cache.height, duration=cache.duration,
        changelog=[], source="dl",
    )
    session.add(f)
    await session.commit()
    if anchor_mid is not None:
        await update_card(bot, chat_id, anchor_mid, f, lang)  # عکسِ منو → ویدیو، درجا
    else:
        await send_card(bot, chat_id, f, lang)
