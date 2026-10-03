"""فاز ۴ / موردِ ۳۳ — کوکیِ بریده‌شده «✅ دوباره واردِ چرخش شد» نگیرد.

خروجیِ Cookie-Editor برای یک اکانتِ واقعی از ۴۰۹۶ کاراکتر رد می‌شود و کلاینتِ
تلگرام آن را چند پیام می‌کند؛ `cookie_paste` فقط تکهٔ اول را می‌دید. اگر کوکیِ
کلیدی (`sessionid`) در همان تکه بود، اعتبارسنجی رد می‌شد و ربات اکانتِ نیمه‌کاره
را به چرخش برمی‌گرداند. حالا پیامِ هم‌اندازهٔ سقف ذخیره نمی‌شود و همان کوکی به‌صورتِ
فایلِ ‎.txt‎ پذیرفته می‌شود.

هندلرهای واقعی با `Message`ِ واقعیِ aiogram روی `ValidatingBot`؛ Redisِ واقعیِ
درون‌حافظه‌ای و دیسکِ واقعی (`cookies_dir` روی `tmp_path`).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from aiogram.types import Chat, Document, Message, User as TgUser

from app import cookies as ck
from app.routers import admin as A
from tests.aiogram_double import ValidatingBot

ADMIN = 777
NAME = "ig_main.txt"


def _netscape(n_lines: int) -> str:
    """کوکیِ Netscapeِ اینستاگرام با `sessionid` در **ابتدای** متن (بدترین حالت)."""
    rows = ["# Netscape HTTP Cookie File",
            ".instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tSESSION123"]
    rows += [f".instagram.com\tTRUE\t/\tTRUE\t1999999999\tc{i:04d}\t{'v' * 40}"
             for i in range(n_lines)]
    return "\n".join(rows) + "\n"


class _Bot(ValidatingBot):
    def __init__(self, payload: bytes = b"") -> None:
        self.calls: list[tuple[str, dict]] = []
        self.payload = payload

    def _on(self, name, payload):
        self.calls.append((name, payload))
        return Message(message_id=99, date=datetime.now(timezone.utc),
                       chat=Chat(id=ADMIN, type="private"), text="ok")

    async def download(self, file, destination=None, **kw):   # noqa: ARG002
        return io.BytesIO(self.payload)

    def replies(self) -> list[str]:
        return [p.get("text", "") for n, p in self.calls if n == "send_message"]


def _msg(bot, **kw) -> Message:
    return Message(message_id=7, date=datetime.now(timezone.utc),
                   chat=Chat(id=ADMIN, type="private"),
                   from_user=TgUser(id=ADMIN, is_bot=False, first_name="a"), **kw).as_(bot)


@pytest.fixture
async def waiting(redis, tmp_path, monkeypatch):
    monkeypatch.setattr(ck.settings, "cookies_dir", str(tmp_path))
    await ck.set_meta(redis, NAME, {"platform": "instagram", "label": "main"})
    await redis.set(A._CK_WAIT + str(ADMIN), NAME, ex=1800)
    return tmp_path


async def test_a_paste_at_the_telegram_limit_is_not_saved(waiting, redis):
    text = _netscape(200)[:4096]                     # همان چیزی که کلاینت به ربات می‌دهد
    assert "sessionid" in text and len(text) == 4096
    bot = _Bot()
    await A.cookie_paste(_msg(bot, text=text), True, redis)
    assert not (waiting / NAME).exists(), "کوکیِ بریده‌شده ذخیره شد"
    assert not any("✅" in r for r in bot.replies()), bot.replies()
    assert await redis.get(A._CK_WAIT + str(ADMIN)) == NAME, "انتظار باید برای فایل باقی بماند"


async def test_the_limit_is_counted_in_utf16_units(waiting, redis):
    """تلگرام UTF-16 می‌شمارد: ایموجیِ خارج از BMP دو واحد است."""
    text2 = _netscape(200)[:4094] + "😀"             # ۴۰۹۵ کاراکتر ولی ۴۰۹۶ واحد
    assert len(text2) < 4096 <= len(text2.encode("utf-16-le")) // 2
    bot = _Bot()
    await A.cookie_paste(_msg(bot, text=text2), True, redis)
    assert not (waiting / NAME).exists()


async def test_a_short_paste_still_works(waiting, redis):
    """کنترل: پیستِ معمولی همان مسیرِ قبلی."""
    bot = _Bot()
    await A.cookie_paste(_msg(bot, text=_netscape(5)), True, redis)
    assert (waiting / NAME).read_text() == _netscape(5).strip()
    assert any("✅" in r for r in bot.replies())


async def test_a_long_cookie_is_accepted_as_a_file(waiting, redis):
    full = _netscape(200)
    assert len(full) > 4096
    bot = _Bot(full.encode())
    doc = Document(file_id="DOC", file_unique_id="u", file_name="cookies.txt",
                   file_size=len(full))
    await A.cookie_file(_msg(bot, document=doc), True, redis)
    assert (waiting / NAME).read_text() == full.strip(), "فایلِ کوکی کامل ذخیره نشد"
    assert any("✅" in r for r in bot.replies())
    assert await redis.get(A._CK_WAIT + str(ADMIN)) is None


async def test_a_document_without_a_pending_paste_passes_through(redis):
    """کنترل: سندِ عادی (یا از غیرِادمین) به روترهای بعدی برسد."""
    from aiogram.dispatcher.event.bases import SkipHandler
    doc = Document(file_id="DOC", file_unique_id="u", file_name="a.pdf", file_size=10)
    with pytest.raises(SkipHandler):
        await A.cookie_file(_msg(_Bot(), document=doc), True, redis)
    with pytest.raises(SkipHandler):
        await A.cookie_file(_msg(_Bot(), document=doc), False, redis)
