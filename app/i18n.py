"""مترجمِ چندزبانه (+ لایهٔ overrideِ زمانِ‌اجرا از textstore).

دو **کاتالوگِ کد** داریم (fa, en) و هر تعداد زبانِ **افزوده‌شده** که کاتالوگ
ندارند و فقط از راهِ `text_overrides` زندگی می‌کنند (پنل ← `/langs`). `t()`
هیچ عضویت‌سنجی‌ای نمی‌کند: هر کدِ زبانی که override داشته باشد کار می‌کند.
"""
from __future__ import annotations

from . import textstore
from .locales.en import MESSAGES as EN
from .locales.fa import MESSAGES as FA

CATALOG: dict[str, dict[str, str]] = {"fa": FA, "en": EN}
DEFAULT = "fa"

#: زبانی که یک کلیدِ **ترجمه‌نشده** به آن می‌افتد. عمداً `en` است نه `fa`:
#: یک زبانِ ۹۰٪‌ترجمه‌شده باید ۱۰٪ انگلیسی نشان دهد، نه ۱۰٪ فارسی — برای
#: مخاطبی که فارسی نمی‌خواند، فارسی از انگلیسی بی‌فایده‌تر است.
#: **این رفتار ۲۰۲۶-۰۸-۱۹ عوض شد**؛ پیش از آن هر کلیدِ غایب به فارسی می‌افتاد.
FALLBACK = "en"

#: نامِ نمایشیِ زبان‌های **داخلی** (آن‌هایی که کاتالوگِ کد دارند). زبان‌های
#: افزوده نامشان در جدولِ `languages` است. یک نقشه، نه سه کپی در سه قالب.
BUILTIN_NAMES: dict[str, str] = {"fa": "فارسی", "en": "English"}


def default_text(lang: str | None, key: str) -> str:
    """متنِ **پیش‌فرضِ** یک کلید برای یک زبان (بی‌اعتنا به override).

    زنجیره: کاتالوگِ خودِ زبان → `FALLBACK` → `DEFAULT` → خودِ کلید.

    تنها پیاده‌سازیِ این قاعده است و پنل هم از همین استفاده می‌کند
    (`admin_web._text_default`)، چون دو کپیِ دست‌نویسِ یک قاعده واگرا می‌شوند
    و هیچ‌کدام دیگری را خبر نمی‌کند — همان الگوی `remove_cookie_file`.
    """
    return (
        CATALOG.get(lang or DEFAULT, {}).get(key)
        or CATALOG[FALLBACK].get(key)
        or CATALOG[DEFAULT].get(key)
        or key
    )


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
    default = default_text(lang, key)
    override = textstore.get_override(lang, key)  # None = از پیش‌فرض استفاده کن
    if override is not None:
        out = _fmt(override, kwargs)
        if out is not None:
            return out  # override معتبر بود
        # override شکست → بی‌صدا به پیش‌فرض برگرد (ربات هیچ‌وقت کرش نکند)
    return _fmt(default, kwargs) or default
