"""کیبوردهای اینلاین."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .callbacks import Act, Conv, Lang, Meta
from .i18n import t

# فیلدهای متنیِ قابلِ‌ویرایشِ متادیتای صوت → (کلیدِ ffmpeg, کلیدِ ترجمهٔ دکمه)
META_FIELDS: list[tuple[str, str]] = [
    ("title", "btn_f_title"), ("artist", "btn_f_artist"), ("album", "btn_f_album"),
    ("genre", "btn_f_genre"), ("date", "btn_f_year"),
]
# برچسبِ نمایشیِ هر فیلد (شاملِ کاور که ورودی‌اش عکس است)
FIELD_LABEL: dict[str, str] = {field: key for field, key in META_FIELDS}
FIELD_LABEL["cover"] = "btn_f_cover"

# نوع‌هایی که کلیدِ اولِ منویشان تمام‌عرض (ردیفِ جدا) نمایش داده می‌شود
FEATURED_TOP = {"audio"}

# عملیاتِ مرتبط با هر نوعِ فایل (فقط کلیدهایی که برای آن نوع معنا دارند).
# ترتیب: عملیاتِ مختصِ نوع اول، بعد عمومی‌های مرتبط.
OPS_BY_KIND: dict[str, list[tuple[str, str]]] = {
    "image": [
        ("bg_remove", "btn_bg_remove"), ("convert", "btn_convert"), ("compress", "btn_compress"),
        ("link", "btn_link"), ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "video": [
        ("to_gif", "btn_to_gif"), ("thumb", "btn_thumb"), ("convert", "btn_convert"),
        ("compress", "btn_compress"), ("link", "btn_link"), ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "audio": [
        ("meta", "btn_edit_music"), ("transcribe", "btn_transcribe"), ("convert", "btn_convert"),
        ("compress", "btn_compress"), ("link", "btn_link"), ("zip", "btn_zip"),
    ],
    "document": [
        ("to_pdf", "btn_to_pdf"), ("link", "btn_link"),
        ("scan", "btn_scan"), ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "pdf": [
        ("convert", "btn_convert"), ("merge", "btn_merge"), ("link", "btn_link"),
        ("scan", "btn_scan"), ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "archive": [
        ("list_zip", "btn_list"), ("extract", "btn_extract"), ("link", "btn_link"),
        ("scan", "btn_scan"), ("rename", "btn_rename"),
    ],
    # فایلِ نصبی/اجرایی (apk و مشابه): اسکن مقدم و برجسته
    "app": [
        ("scan", "btn_scan"), ("link", "btn_link"), ("zip", "btn_zip"), ("rename", "btn_rename"),
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
    "pdf": ["docx", "jpg", "txt"],
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

    featured = bool(ops) and kind in FEATURED_TOP  # کلیدِ اول تمام‌عرض
    rest = len(ops) - 1 if featured else len(ops)
    sizes: list[int] = [1] if featured else []
    sizes += [3] * (rest // 3)
    if rest % 3:
        sizes.append(rest % 3)
    sizes.append(1)  # «بستن» در ردیفِ خودش
    b.adjust(*sizes)
    return b.as_markup()


def cancel_kb(ref: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_cancel"), callback_data=Act(op="cancel", ref=ref))
    return b.as_markup()


def collect_kb(ref: str, lang: str, purpose: str) -> InlineKeyboardMarkup:
    """کیبوردِ جمع‌کردنِ فایل — دکمهٔ اجرا بسته به هدف (زیپ یا ادغامِ PDF)."""
    go_key = "btn_merge_go" if purpose == "merge" else "btn_zip_go"
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, go_key), callback_data=Act(op="collect_go", ref=ref))
    b.button(text=t(lang, "btn_cancel"), callback_data=Act(op="cancel", ref=ref))
    b.adjust(2)
    return b.as_markup()


def meta_edit_kb(ref: str, lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for field, key in META_FIELDS:
        b.button(text=t(lang, key), callback_data=Meta(ref=ref, field=field))
    b.button(text=t(lang, "btn_f_cover"), callback_data=Meta(ref=ref, field="cover"))
    b.button(text=t(lang, "btn_apply"), callback_data=Act(op="meta_apply", ref=ref))
    b.button(text=t(lang, "btn_cancel"), callback_data=Act(op="cancel", ref=ref))
    b.adjust(3, 3, 2)  # ۵ فیلد + کاور: ۳+۳ ، بعد اعمال+لغو
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
