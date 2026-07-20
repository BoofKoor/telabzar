"""حالت‌های FSM."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Rename(StatesGroup):
    waiting_name = State()


class ZipCollect(StatesGroup):
    # کاربر «زیپ» زده؛ فایل‌های بعدی جمع می‌شوند تا با هم آرشیو شوند.
    collecting = State()


class MetaEdit(StatesGroup):
    choosing = State()        # انتخابِ فیلد برای ویرایش
    waiting_value = State()   # منتظرِ مقدارِ متنیِ فیلد
    waiting_cover = State()   # منتظرِ عکسِ کاور
