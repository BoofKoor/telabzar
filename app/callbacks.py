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
