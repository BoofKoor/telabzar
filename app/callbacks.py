"""دادهٔ callback تایپ‌دار (زیرِ سقفِ ۶۴ بایتِ تلگرام)."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class Lang(CallbackData, prefix="lang"):
    """انتخابِ زبان. **عمداً تک‌فیلدی می‌ماند.**

    وسوسه این است که یک فیلدِ `src` اضافه شود تا «انتخابِ اول» از «تغییر از
    تنظیمات» جدا شود. اندازه‌گیری‌شده روی aiogram 3.30 که چرا نه: `unpack`
    سخت‌گیر است و مقدارِ پیش‌فرضِ پایتونی نجاتش نمی‌دهد —

        Lang2.unpack('lang:fa') → TypeError: takes 2 arguments but 1 were given

    یعنی هر کاربری که لحظهٔ استقرار یک منوی زبانِ بی‌جواب روی صفحه دارد، ضربه
    می‌زند و **هیچ هندلری جور نمی‌شود** (دکمه می‌چرخد و هیچ). به‌جایش آن تفکیک
    از **حالت** مشتق می‌شود: `routers/start.py` نگاه می‌کند `user.lang` پیش از
    نوشتن تهی بود یا نه.
    """

    code: str


class Nav(CallbackData, prefix="nv"):
    """پیمایشِ منوهای کاربر (خوش‌آمد ↔ تنظیمات ↔ آموزش ↔ انتخابِ زبان).

    یک فیلد، تا افزودنِ مقصدِ تازه یک ردیف در `keyboards.HOME_ITEMS` /
    `SETTINGS_ITEMS` باشد و نه یک کلاسِ تازه. `nv:settings` = ۱۱ بایت.
    """

    to: str  # home | settings | lang | help


class Act(CallbackData, prefix="act"):
    op: str
    ref: str


class Conv(CallbackData, prefix="cv"):
    ref: str
    fmt: str


class Meta(CallbackData, prefix="mt"):
    ref: str
    field: str


class Cmp(CallbackData, prefix="cmp"):
    ref: str
    res: str  # ارتفاعِ هدف («720») یا «same»


class Wm(CallbackData, prefix="wm"):
    ref: str
    pos: str  # tl | tr | bl | br


class Rsz(CallbackData, prefix="rsz"):
    ref: str
    w: str  # عرضِ هدف («۸۰۰») یا «half»


class Rot(CallbackData, prefix="rot"):
    ref: str
    mode: str  # cw | ccw | 180 | mirror


class Spd(CallbackData, prefix="spd"):
    ref: str
    rate: str  # 0.75 | 1.25 | 1.5 | 2.0


class Tr(CallbackData, prefix="tr"):
    ref: str
    mode: str  # txt | srt


class Dl(CallbackData, prefix="dl"):
    ref: str
    sel: str  # توکنِ کوتاهِ کیفیت (best/audio/شاخصِ فرمت) یا cancel


class Ck(CallbackData, prefix="ck"):
    """اقدامِ ادمین روی اکانتِ کوکیِ نیازمندِ رسیدگی. `tok` = توکنِ کوتاهِ Redis
    (نامِ فایل می‌تواند بلند باشد و سقفِ ۶۴ بایتِ callback را بشکند)."""

    act: str   # paste | off | del
    tok: str
