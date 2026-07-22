"""کیبوردهای اینلاین."""
from __future__ import annotations

from aiogram.types import CopyTextButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .callbacks import Act, Cmp, Conv, Dl, Lang, Meta, Rot, Rsz, Spd, Tr, Wm
from .i18n import t

# رزولوشن‌های هدفِ کاهشِ حجمِ ویدیو → (ارتفاع, بیت‌ریتِ ویدیو kbps)
VIDEO_TARGETS: list[tuple[int, int]] = [
    (1080, 4000), (720, 2200), (480, 1100), (360, 600), (240, 350),
]
VIDEO_KBPS = {h: k for h, k in VIDEO_TARGETS}

# فیلدهای متنیِ قابلِ‌ویرایشِ متادیتای صوت → (کلیدِ ffmpeg, کلیدِ ترجمهٔ دکمه)
META_FIELDS: list[tuple[str, str]] = [
    ("title", "btn_f_title"), ("artist", "btn_f_artist"), ("album", "btn_f_album"),
    ("genre", "btn_f_genre"), ("date", "btn_f_year"),
]
# برچسبِ نمایشیِ هر فیلد (شاملِ کاور که ورودی‌اش عکس است)
FIELD_LABEL: dict[str, str] = {field: key for field, key in META_FIELDS}
FIELD_LABEL["cover"] = "btn_f_cover"

# نوع‌هایی که کلیدِ اولِ منویشان تمام‌عرض (ردیفِ جدا) نمایش داده می‌شود
FEATURED_TOP = {"audio", "video", "image"}

# عرض‌های هدفِ تغییرِ اندازهٔ تصویر (px)
IMAGE_RESIZE_WIDTHS = [1920, 1280, 800, 512]

# عملیاتِ مرتبط با هر نوعِ فایل (فقط کلیدهایی که برای آن نوع معنا دارند).
# ترتیب: عملیاتِ مختصِ نوع اول، بعد عمومی‌های مرتبط.
OPS_BY_KIND: dict[str, list[tuple[str, str]]] = {
    "image": [
        ("link", "btn_link"),
        ("ocr", "btn_ocr"), ("watermark", "btn_watermark"), ("img_pdf", "btn_to_pdf"),
        ("resize", "btn_resize"), ("rotate", "btn_rotate"), ("enhance", "btn_enhance"),
        ("compress", "btn_compress"), ("convert", "btn_convert"), ("bg_remove", "btn_bg_remove"),
        ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "video": [
        ("link", "btn_link_stream"),
        ("cover", "btn_cover_v"), ("compress", "btn_compress"), ("convert", "btn_convert"),
        ("watermark", "btn_watermark"), ("extract_audio", "btn_extract_audio"), ("to_gif", "btn_to_gif"),
        ("trim", "btn_trim"), ("vjoin", "btn_vjoin"), ("screenshot", "btn_screenshot"), ("mute", "btn_mute"),
        ("rename", "btn_rename"), ("zip", "btn_zip"),
    ],
    "audio": [
        ("meta", "btn_edit_music"),
        ("transcribe", "btn_transcribe"), ("trim", "btn_trim"), ("normalize", "btn_normalize"),
        ("speed", "btn_speed"), ("convert", "btn_convert"), ("compress", "btn_compress"),
        ("link", "btn_link"), ("zip", "btn_zip"),
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


def collapsed_kb(ref: str, lang: str) -> InlineKeyboardMarkup:
    """کیبوردِ جمع‌شده: فقط یک دکمهٔ «نمایش آپشن‌ها» (برای فایل‌های ارسالیِ لینک).
    زدنش منوی کامل را باز می‌کند (op=menu → همان هندلرِ بازگشت)."""
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_show_options"), callback_data=Act(op="menu", ref=ref))
    return b.as_markup()


def file_card_kb(ref: str, kind: str, lang: str, collapsible: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    ops = OPS_BY_KIND.get(kind, _DEFAULT_OPS)
    for op, key in ops:
        b.button(text=t(lang, key), callback_data=Act(op=op, ref=ref))
    # فایلِ لینک (collapsible): «بستن» منو را جمع می‌کند (نه حذفِ کارت)؛ وگرنه می‌بندد.
    b.button(text=t(lang, "btn_close"),
             callback_data=Act(op="collapse" if collapsible else "close", ref=ref))

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


def watermark_pos_kb(ref: str, lang: str) -> InlineKeyboardMarkup:
    """انتخابِ گوشهٔ واترمارک."""
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "wm_tl"), callback_data=Wm(ref=ref, pos="tl"))
    b.button(text=t(lang, "wm_tr"), callback_data=Wm(ref=ref, pos="tr"))
    b.button(text=t(lang, "wm_bl"), callback_data=Wm(ref=ref, pos="bl"))
    b.button(text=t(lang, "wm_br"), callback_data=Wm(ref=ref, pos="br"))
    b.button(text=t(lang, "btn_back"), callback_data=Act(op="menu", ref=ref))
    b.adjust(2, 2, 1)
    return b.as_markup()


def resize_menu_kb(ref: str, file, lang: str) -> InlineKeyboardMarkup:
    """منوی تغییرِ اندازهٔ تصویر: عرض‌های کوچک‌تر از فعلی + «نصف»."""
    b = InlineKeyboardBuilder()
    w = file.width or 0
    for tw in IMAGE_RESIZE_WIDTHS:
        if w and tw >= w:            # فقط کوچک‌تر از عرضِ فعلی
            continue
        b.button(text=f"↔️ {tw}px", callback_data=Rsz(ref=ref, w=str(tw)))
    b.button(text=t(lang, "btn_half"), callback_data=Rsz(ref=ref, w="half"))
    b.button(text=t(lang, "btn_back"), callback_data=Act(op="menu", ref=ref))
    b.adjust(2)
    return b.as_markup()


def rotate_menu_kb(ref: str, lang: str) -> InlineKeyboardMarkup:
    """منوی چرخش/آینهٔ تصویر."""
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "rot_ccw"), callback_data=Rot(ref=ref, mode="ccw"))
    b.button(text=t(lang, "rot_cw"), callback_data=Rot(ref=ref, mode="cw"))
    b.button(text=t(lang, "rot_180"), callback_data=Rot(ref=ref, mode="180"))
    b.button(text=t(lang, "rot_mirror"), callback_data=Rot(ref=ref, mode="mirror"))
    b.button(text=t(lang, "btn_back"), callback_data=Act(op="menu", ref=ref))
    b.adjust(2, 2, 1)
    return b.as_markup()


AUDIO_SPEEDS = ["0.75", "1.25", "1.5", "2.0"]


def transcribe_menu_kb(ref: str, lang: str) -> InlineKeyboardMarkup:
    """انتخابِ خروجیِ رونویسی: متنِ ساده یا زیرنویسِ SRT."""
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_tr_text"), callback_data=Tr(ref=ref, mode="txt"))
    b.button(text=t(lang, "btn_tr_srt"), callback_data=Tr(ref=ref, mode="srt"))
    b.button(text=t(lang, "btn_back"), callback_data=Act(op="menu", ref=ref))
    b.adjust(2, 1)
    return b.as_markup()


def speed_menu_kb(ref: str, lang: str) -> InlineKeyboardMarkup:
    """انتخابِ ضریبِ سرعتِ صوت (بدونِ تغییرِ زیروبمی)."""
    b = InlineKeyboardBuilder()
    for r in AUDIO_SPEEDS:
        b.button(text=f"⏩ {r.rstrip('0').rstrip('.')}×", callback_data=Spd(ref=ref, rate=r))
    b.button(text=t(lang, "btn_back"), callback_data=Act(op="menu", ref=ref))
    b.adjust(2, 2, 1)
    return b.as_markup()


def cancel_job_kb(job_id: int, lang: str) -> InlineKeyboardMarkup:
    """دکمهٔ لغوِ یک جابِ در حالِ اجرا (ref = شناسهٔ جاب)."""
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_cancel_job"), callback_data=Act(op="canceljob", ref=str(job_id)))
    return b.as_markup()


def download_menu_kb(ref: str, options: list[dict], lang: str) -> InlineKeyboardMarkup:
    """منوی کیفیتِ دانلود: بهترین/صوت + ارتفاع‌های موجود (با تخمینِ حجم)."""
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_dl_best"), callback_data=Dl(ref=ref, sel="best"))
    b.button(text=t(lang, "btn_dl_audio"), callback_data=Dl(ref=ref, sel="audio"))
    opts = options[:6]
    for o in opts:
        b.button(text=f"🔻 {o['label']}", callback_data=Dl(ref=ref, sel=str(o["sel"])))
    b.button(text=t(lang, "btn_cancel"), callback_data=Dl(ref=ref, sel="cancel"))
    n = len(opts)
    sizes = [2] + [2] * (n // 2) + ([1] if n % 2 else []) + [1]
    b.adjust(*sizes)
    return b.as_markup()


def download_cancel_kb(ref: str, lang: str) -> InlineKeyboardMarkup:
    """دکمهٔ لغوِ دانلودِ در حالِ اجرا (ref = توکنِ دانلود)."""
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_cancel_job"), callback_data=Dl(ref=ref, sel="cancel"))
    return b.as_markup()


def link_menu_kb(ref: str, lang: str, dl_url: str, stream_url: str, streamable: bool) -> InlineKeyboardMarkup:
    """زیرمنوی لینک: دانلود/پخش (URL) + کپیِ لینک (CopyTextButton) + بازگشت."""
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_dl"), url=dl_url)
    if streamable:
        b.button(text=t(lang, "btn_stream"), url=stream_url)
    b.button(text=t(lang, "btn_copy_link"), copy_text=CopyTextButton(text=dl_url))
    b.button(text=t(lang, "btn_back"), callback_data=Act(op="menu", ref=ref))
    b.adjust(2, 1, 1) if streamable else b.adjust(1, 1, 1)
    return b.as_markup()


def collect_kb(ref: str, lang: str, purpose: str) -> InlineKeyboardMarkup:
    """کیبوردِ جمع‌کردنِ فایل — دکمهٔ اجرا بسته به هدف (زیپ / ادغامِ PDF / عکس‌ها به PDF)."""
    go_key = {"merge": "btn_merge_go", "img_pdf": "btn_img_pdf_go",
              "vjoin": "btn_vjoin_go"}.get(purpose, "btn_zip_go")
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


def _est_mb(kbps: int, duration: int | None) -> float | None:
    if not duration:
        return None
    return round((kbps + 128) * duration / 8 / 1024, 1)


def source_kbps(file) -> float | None:
    """بیت‌ریتِ تقریبیِ منبع (kbps) از حجم و مدت. None اگر یکی نامعلوم بود."""
    if not file.size or not file.duration:
        return None
    return file.size * 8 / file.duration / 1024


def effective_kbps(target_kbps: int, file) -> int:
    """بیت‌ریتِ مؤثرِ خروجی: هرگز از منبع بالاتر نرود (وگرنه «کاهش» حجم را زیاد می‌کند).
    سقف ≈ ۸۵٪ بیت‌ریتِ منبع منهای صدای تقریبی؛ کف ۲۰۰kbps."""
    src = source_kbps(file)
    if not src:
        return target_kbps
    cap = max(200, int(src * 0.85) - 128)
    return min(target_kbps, cap)


def compress_menu_kb(ref: str, file, lang: str) -> InlineKeyboardMarkup:
    """منوی کاهشِ حجمِ ویدیو: فقط رزولوشن‌هایی که **واقعاً** حجم را کم می‌کنند.

    تخمین بر اساسِ بیت‌ریتِ مؤثر (سقف‌شده زیر منبع) است، نه بیت‌ریتِ ثابت — پس دیگر
    گزینه‌ای که خروجی‌اش از فایلِ فعلی بزرگ‌تر شود نشان داده نمی‌شود. اگر حجم/مدت را
    ندانیم (مثلِ ویدیوی سند)، فقط گزینهٔ رزولوشن بدونِ عددِ حجمِ گمراه‌کننده می‌آید.
    """
    b = InlineKeyboardBuilder()
    h, dur = file.height or 0, file.duration or 0
    src = source_kbps(file)
    cur_mb = file.size / 1024 / 1024 if file.size else None
    for th, kbps in VIDEO_TARGETS:
        if h and th >= h:            # فقط پایین‌تر از رزولوشنِ فعلی
            continue
        eff = effective_kbps(kbps, file)
        est = _est_mb(eff, dur)
        # منبع را می‌دانیم ولی این گزینه واقعاً کم نمی‌کند → نشانش نده
        if src and est and cur_mb and est >= cur_mb * 0.95:
            continue
        label = f"🔻 {th}p" + (f"  ·  ~{est:g}MB" if (est and src) else "")
        b.button(text=label, callback_data=Cmp(ref=ref, res=str(th)))
    if dur and dur >= 300:  # ویدیوی بلند (کلاس/جلسه) → حالتِ فوق‌فشرده
        b.button(text=t(lang, "btn_tiny"), callback_data=Cmp(ref=ref, res="tiny"))
    b.button(text=t(lang, "btn_same_res"), callback_data=Cmp(ref=ref, res="same"))
    b.button(text=t(lang, "btn_back"), callback_data=Act(op="menu", ref=ref))
    b.adjust(1)  # هر گزینه یک ردیف (با تخمینِ حجم خواناتر)
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
