"""مترجمِ سادهٔ دوزبانه (+ لایهٔ overrideِ زمانِ‌اجرا از textstore)."""
from __future__ import annotations

from . import textstore
from .locales.en import MESSAGES as EN
from .locales.fa import MESSAGES as FA

CATALOG: dict[str, dict[str, str]] = {"fa": FA, "en": EN}
DEFAULT = "fa"


def _fmt(template: str, kwargs: dict) -> str | None:
    """فرمت با kwargs؛ None اگر شکست (تا بتوان به پیش‌فرض برگشت)."""
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return None


def t(lang: str | None, key: str, **kwargs: object) -> str:
    lang = lang or DEFAULT
    default = CATALOG.get(lang, FA).get(key) or FA.get(key) or key
    override = textstore.get_override(lang, key)  # None = از پیش‌فرض استفاده کن
    if override is not None:
        out = _fmt(override, kwargs)
        if out is not None:
            return out  # override معتبر بود
        # override شکست → بی‌صدا به پیش‌فرض برگرد (ربات هیچ‌وقت کرش نکند)
    return _fmt(default, kwargs) or default
