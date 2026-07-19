"""ساختِ متنِ کارتِ فایل."""
from __future__ import annotations

from .filetypes import human_size
from .i18n import t
from .models import File


def card_text(file: File, lang: str) -> str:
    return t(
        lang,
        f"detected_{file.kind}",
        name=file.name or "—",
        size=human_size(file.size),
    )
