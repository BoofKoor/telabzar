"""دادهٔ callback تایپ‌دار (زیرِ سقفِ ۶۴ بایتِ تلگرام)."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class Lang(CallbackData, prefix="lang"):
    code: str


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
