"""مترجمِ سادهٔ دوزبانه."""
from __future__ import annotations

from .locales.en import MESSAGES as EN
from .locales.fa import MESSAGES as FA

CATALOG: dict[str, dict[str, str]] = {"fa": FA, "en": EN}
DEFAULT = "fa"


def t(lang: str | None, key: str, **kwargs: object) -> str:
    catalog = CATALOG.get(lang or DEFAULT, FA)
    template = catalog.get(key) or FA.get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template
