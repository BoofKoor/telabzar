"""حالت‌های FSM."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Rename(StatesGroup):
    waiting_name = State()
