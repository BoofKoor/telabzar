"""باتِ جعلی که **شکلِ واقعیِ APIِ aiogram را تحمیل می‌کند**، نه شکلِ دلبخواهِ خودش.

درسی که این ماژول از آن آمد: یک ماک که امضای خودش را تعریف می‌کند، اختلافِ
شکلِ فراخوانی با APIِ واقعی را **پنهان** می‌کند و تست را بی‌صدا vacuous.

مشخصاً: `FakeBot.edit_message_text(self, text, chat_id=None, message_id=None)`
یک فراخوانیِ موضعیِ `(text, chat_id, message_id)` را خوشحال می‌پذیرد — ولی
پارامترِ **دومِ** `Bot.edit_message_text` در aiogram `business_connection_id`
است، پس همان فراخوانی در تولید یک `ValidationError` می‌دهد. تست سبز بود، قابلیت
در تولید هرگز کار نکرد.

راه‌حل: آرگومان‌ها دقیقاً با **امضای خودِ `aiogram.Bot`** bind می‌شوند و بعد
همان شیءِ متدی که aiogram می‌ساخت ساخته می‌شود — یعنی اعتبارسنجیِ pydantic
واقعاً اجرا می‌شود. فراخوانیِ بدشکل این‌جا هم دقیقاً مثلِ تولید می‌ترکد.

نکتهٔ ریز که این تله را ساخت: فقط `edit_message_text` و `edit_message_caption`
`business_connection_id` را **قبل** از `chat_id` دارند. `send_message`,
`delete_message`, `send_photo/document/video` همه شهودی‌اند، و همین ناهماهنگی
باعث می‌شود چشم خطا را نبیند.
"""
from __future__ import annotations

import inspect
from typing import Any

from aiogram import Bot, methods

# نامِ متدِ Bot → مدلی که aiogram برای همان فراخوانی می‌سازد.
_METHOD_MODEL = {
    "send_message": methods.SendMessage,
    "send_photo": methods.SendPhoto,
    "send_document": methods.SendDocument,
    "send_video": methods.SendVideo,
    "edit_message_text": methods.EditMessageText,
    "edit_message_caption": methods.EditMessageCaption,
    "delete_message": methods.DeleteMessage,
    "answer_callback_query": methods.AnswerCallbackQuery,
}


def bind_like_aiogram(name: str, args: tuple, kwargs: dict) -> dict[str, Any]:
    """آرگومان‌ها را مثلِ خودِ aiogram bind و اعتبارسنجی می‌کند؛ payload را می‌دهد.

    اگر فراخوانی بدشکل باشد (موضعیِ اشتباه، نوعِ غلط، پارامترِ ناشناخته) همان
    استثنایی بالا می‌آید که در تولید می‌آمد — `TypeError` از bind یا
    `ValidationError` از pydantic.
    """
    real = getattr(Bot, name)
    bound = inspect.signature(real).bind(None, *args, **kwargs)   # None به‌جای self
    bound.apply_defaults()
    data = dict(bound.arguments)
    data.pop("self", None)

    model = _METHOD_MODEL.get(name)
    if model is None:                       # متدی که هنوز نگاشت نشده
        raise AssertionError(f"aiogram_double: مدلِ {name} را به _METHOD_MODEL اضافه کن")
    fields = set(model.model_fields)
    payload = {k: v for k, v in data.items() if k in fields and v is not None}
    model(**payload)                        # ← همان اعتبارسنجی‌ای که تولید می‌کند
    return payload


class ValidatingBot:
    """پایهٔ باتِ جعلی. هر متد قبل از ثبت، فراخوانی را اعتبارسنجی می‌کند.

    زیرکلاس‌ها `_on(name, payload)` را override می‌کنند تا چیزی را که لازم دارند
    نگه دارند؛ اعتبارسنجی همیشه اتفاق می‌افتد و دور زدنی نیست.
    """

    def _on(self, name: str, payload: dict[str, Any]) -> Any:  # noqa: ARG002
        return True

    async def send_message(self, *a, **kw):
        return self._on("send_message", bind_like_aiogram("send_message", a, kw))

    async def edit_message_text(self, *a, **kw):
        return self._on("edit_message_text", bind_like_aiogram("edit_message_text", a, kw))

    async def edit_message_caption(self, *a, **kw):
        return self._on("edit_message_caption", bind_like_aiogram("edit_message_caption", a, kw))

    async def delete_message(self, *a, **kw):
        return self._on("delete_message", bind_like_aiogram("delete_message", a, kw))
