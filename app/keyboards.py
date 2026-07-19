"""کیبوردهای اینلاین."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .callbacks import Act, Conv, Lang
from .i18n import t

# عملیاتِ مختصِ هر نوع: (op, ترجمه‌کلید)
TYPE_OPS: dict[str, list[tuple[str, str]]] = {
    "audio": [("meta", "btn_meta"), ("transcribe", "btn_transcribe")],
    "image": [("bg_remove", "btn_bg_remove")],
    "video": [("to_gif", "btn_to_gif")],
    "document": [("to_pdf", "btn_to_pdf")],
    "archive": [("list_zip", "btn_list"), ("extract", "btn_extract")],
}

# عملیاتِ عمومی روی همهٔ فایل‌ها
GENERAL_OPS: list[tuple[str, str]] = [
    ("convert", "btn_convert"),
    ("compress", "btn_compress"),
    ("rename", "btn_rename"),
    ("thumb", "btn_thumb"),
    ("zip", "btn_zip"),
    ("scan", "btn_scan"),
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
    sizes: list[int] = []

    type_ops = TYPE_OPS.get(kind, [])
    for op, key in type_ops:
        b.button(text=t(lang, key), callback_data=Act(op=op, ref=ref))
    if type_ops:
        sizes.append(len(type_ops))

    for op, key in GENERAL_OPS:
        b.button(text=t(lang, key), callback_data=Act(op=op, ref=ref))
    sizes += [3, 3]  # شش عملیاتِ عمومی در دو ردیفِ سه‌تایی

    b.button(text=t(lang, "btn_close"), callback_data=Act(op="close", ref=ref))
    sizes.append(1)

    b.adjust(*sizes)
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
