"""فاز ۴ / موردِ ۳۴الف — متنِ کاربر در گزارشِ ادمین escape شود.

گزارشِ «🔞 محتوای غیرمجاز مسدود شد» با `parse_mode=HTML` به ادمین می‌رود و
`routers/download._reject` متنِ پیامِ کاربر را خام داخلِ `<code>` می‌گذاشت. نتیجه
دوتاست، هر دو بد: یا تلگرام پیام را با «can't parse entities» رد می‌کند و ادمین
**هیچ** گزارشی نمی‌گیرد (`except` بی‌صدا)، یا کاربر HTMLِ دلخواه — لینکِ فیشینگ
با متنِ بی‌خطر — داخلِ DMِ ادمین می‌کارد. `reason` هم از ورودی می‌آید
(`domain:<host>`؛ `urlparse` در hostname `<` را نگه می‌دارد).
"""
from __future__ import annotations

from datetime import datetime, timezone

from aiogram.types import Chat, Message, User as TgUser

from app import safety
from app.models import User
from app.routers import download as D
from tests.aiogram_double import ValidatingBot

PAYLOAD = '<a href="https://evil.example">بازبینیِ فوری</a> https://pornhub.com/x'


class _Bot(ValidatingBot):
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def _on(self, name, payload):
        if name == "send_message":
            self.sent.append((payload["chat_id"], payload["text"]))
        return Message(message_id=5, date=datetime.now(timezone.utc),
                       chat=Chat(id=1, type="private"), text="x")


def _admin_texts(bot) -> list[str]:
    return [t for cid, t in bot.sent if cid == 900]


async def test_the_users_text_is_escaped_in_the_admin_report(redis, monkeypatch):
    monkeypatch.setattr(D.settings, "admin_ids", "900")   # همان شیئی که safety می‌خواند
    bot = _Bot()
    msg = Message(message_id=3, date=datetime.now(timezone.utc),
                  chat=Chat(id=42, type="private"),
                  from_user=TgUser(id=42, is_bot=False, first_name="u"),
                  text=PAYLOAD).as_(bot)
    user = User(id=1, tg_user_id=42, role="user")
    pol = safety.Policy(notify=True)
    await D._reject(msg, redis, user, "fa", pol, safety.check_url("https://pornhub.com/x"))
    texts = _admin_texts(bot)
    assert texts, "ادمین گزارشی نگرفت"
    assert '<a href="https://evil.example">' not in texts[0], "HTMLِ کاربر خام به DMِ ادمین رسید"
    assert "&lt;a href" in texts[0]


async def test_the_reason_is_escaped(redis, monkeypatch):
    monkeypatch.setattr(D.settings, "admin_ids", "900")
    bot = _Bot()
    await safety.report_block(bot, redis, 42, "domain:a<b>x.example",
                              safety.Policy(notify=True), detail="")
    (text,) = _admin_texts(bot)
    assert "a&lt;b&gt;x.example" in text and "<b>x" not in text
