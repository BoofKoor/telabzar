"""حالت‌های FSM."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Rename(StatesGroup):
    waiting_name = State()


class Collect(StatesGroup):
    # جمع‌کردنِ فایل‌های بعدی برای یک عملیاتِ گروهی (زیپ یا ادغامِ PDF).
    # هدف (purpose) در دادهٔ state نگه‌داری می‌شود.
    collecting = State()


class MetaEdit(StatesGroup):
    choosing = State()        # انتخابِ فیلد برای ویرایش
    waiting_value = State()   # منتظرِ مقدارِ متنیِ فیلد
    waiting_cover = State()   # منتظرِ عکسِ کاور


class SetCover(StatesGroup):
    waiting = State()         # منتظرِ عکسِ کاورِ ویدیو
