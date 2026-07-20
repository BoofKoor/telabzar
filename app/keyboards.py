"""کیبوردهای اینلاین."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .callbacks import Act, Conv, Lang
from .i18n import t

# عملیاتِ مرتبط با هر نوعِ فایل (فقط کلیدهایی که برای آن نوع معنا دارند).
# ترتیب: عملیاتِ مختصِ نوع اول، بعد عمومی‌های مرتبط.
OPS_BY_KIND: dict[str, list[tuple[str, str]]] = {
    "image": [
        ("bg_remove", "btn_bg_remove"), ("convert", "btn_convert"),
        ("compress", "btn_compress"), ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "video": [
        ("to_gif", "btn_to_gif"), ("thumb", "btn_thumb"), ("convert", "btn_convert"),
        ("compress", "btn_compress"), ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "audio": [
        ("meta", "btn_meta"), ("transcribe", "btn_transcribe"), ("convert", "btn_convert"),
        ("compress", "btn_compress"), ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "document": [
        ("to_pdf", "btn_to_pdf"), ("convert", "btn_convert"), ("compress", "btn_compress"),
        ("scan", "btn_scan"), ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "archive": [
        ("list_zip", "btn_list"), ("extract", "btn_extract"),
        ("scan", "btn_scan"), ("rename", "btn_rename"),
    ],
    # فایلِ نصبی/اجرایی (apk و مشابه): اسکن مقدم و برجسته
    "app": [
        ("scan", "btn_scan"), ("zip", "btn_zip"), ("rename", "btn_rename"),
    ],
}
_DEFAULT_OPS: list[tuple[str, str]] = [
    ("convert", "btn_convert"), ("compress", "btn_compress"),
    ("rename", "btn_rename"), ("scan", "btn_scan"), ("zip", "btn_zip"),
]

# عملیاتی که در M2 واقعاً کار می‌کنند
COMPRESSIBLE = {"image", "video", "audio"}
CONVERT_FORMATS: dict[str, list[str]] = {
    "image": ["jpg", "png", "webp"],
    "video": ["mp4", "webm", "mkv"],
    "audio": ["mp3", "m4a", "ogg", "wav"],
}
CONVERTIBLE = set(CONVERT_FORMATS)


def lang_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="فارسی 🇮🇷", callback_data=Lang(code="fa"))
    b.button(text="English 🇬🇧", callback_data=Lang(code="en"))
    b.adjust(2)
    return b.as_markup()


def file_card_kb(ref: str, kind: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    ops = OPS_BY_KIND.get(kind, _DEFAULT_OPS)
    for op, key in ops:
        b.button(text=t(lang, key), callback_data=Act(op=op, ref=ref))
    b.button(text=t(lang, "btn_close"), callback_data=Act(op="close", ref=ref))

    n = len(ops)
    sizes = [3] * (n // 3)
    if n % 3:
        sizes.append(n % 3)
    sizes.append(1)  # «بستن» در ردیفِ خودش
    b.adjust(*sizes)
    return b.as_markup()


def cancel_kb(ref: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_cancel"), callback_data=Act(op="cancel", ref=ref))
    return b.as_markup()


def convert_menu_kb(ref: str, kind: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    fmts = CONVERT_FORMATS.get(kind, [])
    for fmt in fmts:
        b.button(text=fmt.upper(), callback_data=Conv(ref=ref, fmt=fmt))
    b.button(text=t(lang, "btn_back"), callback_data=Act(op="menu", ref=ref))

    sizes = [3] * (len(fmts) // 3)
    if len(fmts) % 3:
        sizes.append(len(fmts) % 3)
    sizes.append(1)  # بازگشت
    b.adjust(*sizes)
    return b.as_markup()
