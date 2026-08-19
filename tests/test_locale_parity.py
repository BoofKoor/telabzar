"""گاردِ پاریتیِ دو کاتالوگ — و اینکه چرا شکستش **خاموش** است.

CLAUDE.md §۷ می‌گوید «هر کلید باید در هر دو `locales/{fa,en}.py` باشد» و
۲۰۲۶-۰۸-۱۹ اندازه‌گیری شد که هست (۲۱۴ کلید، صفر یک‌طرفه). ولی آن یک
**اندازه‌گیریِ یک‌باره** بود نه نگهبان: تا امروز صفر assert در کلِ `tests/`
روی برابریِ مجموعهٔ کلیدها وجود داشت.

**چرا خاموش است** (اجراشده روی سورسِ همین ریپو):

    default_text('en', <کلیدی که فقط در fa هست>) → 'دکمهٔ نمونه'

کلیدِ یک‌طرفه خطا نمی‌دهد — از زنجیرهٔ `en → FALLBACK(en) → DEFAULT(fa)` رد
می‌شود و متنِ **فارسی** برمی‌گرداند. و چون `langpack.TEXT_KEYS` **اجتماعِ** دو
کاتالوگ است، آن کلید واردِ بستهٔ ترجمه هم می‌شود — یعنی بستهٔ
انگلیسی‌مبدأ متنِ فارسی را به مترجم می‌دهد. نه ربات می‌شکند، نه تستی قرمز
می‌شود، نه پنل چیزی می‌گوید.

سه ادعا، هر سه **کشف‌محور** روی کلِ کاتالوگ نه فهرستِ دستی — چون فهرستِ دستی
همان `_KNOWN_UNREACHABLE`ی است که §۷ ثبت کرده می‌پوسد.
"""
from __future__ import annotations

import re

from app.i18n import CATALOG
from app.langpack import TEXT_KEYS
from app.locales.en import MESSAGES as EN
from app.locales.fa import MESSAGES as FA
from app.textstore import _fields

#: توالیِ **نامِ تگ‌ها** به ترتیبِ ظهور. عمداً `_fields` را از `textstore` قرض
#: می‌گیریم و برای تگ‌ها هم یک الگوی واحد داریم، تا این فایل کپیِ دومِ
#: دست‌نویسِ قاعده‌ای نشود که صاحبش جای دیگری است.
_TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)")


def _tags(text: str) -> list[str]:
    return [f"{slash}{name.lower()}" for slash, name in _TAG_RE.findall(text)]


def test_the_two_catalogs_hold_exactly_the_same_keys():
    """کلیدِ یک‌طرفه = متنِ زبانِ اشتباه در بستهٔ ترجمه (توضیح در داکس‌استرینگ)."""
    only_fa = sorted(set(FA) - set(EN))
    only_en = sorted(set(EN) - set(FA))
    assert not only_fa, (
        f"{len(only_fa)} کلید فقط در fa هست و در en نیست: {only_fa}\n"
        "بستهٔ ترجمهٔ انگلیسی‌مبدأ برای این کلیدها متنِ **فارسی** export می‌کند."
    )
    assert not only_en, (
        f"{len(only_en)} کلید فقط در en هست و در fa نیست: {only_en}\n"
        "کاربرِ فارسی برای این کلیدها متنِ انگلیسی می‌بیند."
    )


def test_every_key_carries_the_same_placeholders_in_both_languages():
    """قراردادِ placeholder باید بینِ دو زبان یکی باشد.

    یک `{mb}`ِ جاافتاده در یک طرف یعنی یا `t()` بی‌صدا به پیش‌فرض برمی‌گردد
    (وقتی call site kwargs می‌دهد) یا براکتِ خام به کاربر می‌رسد (وقتی
    نمی‌دهد) — هر دو اندازه‌گیری‌شده و در §۷ ثبت.
    """
    bad = {k: (sorted(_fields(FA[k])), sorted(_fields(EN[k])))
           for k in sorted(set(FA) & set(EN))
           if _fields(FA[k]) != _fields(EN[k])}
    assert not bad, f"placeholderهای ناهمخوان (کلید: fa vs en): {bad}"


def test_every_key_carries_the_same_html_tags_in_both_languages():
    """تگِ جاافتاده/اضافه یعنی یک طرف مارک‌آپِ شکسته به تلگرام می‌فرستد."""
    bad = {k: (_tags(FA[k]), _tags(EN[k]))
           for k in sorted(set(FA) & set(EN))
           if _tags(FA[k]) != _tags(EN[k])}
    assert not bad, f"تگ‌های HTMLِ ناهمخوان (کلید: fa vs en): {bad}"


def test_the_new_phase_c_strings_reach_the_translation_pack():
    """قیدِ صریحِ فاز C: رشتهٔ تازهٔ ربات باید ترجمه‌پذیر باشد.

    `TEXT_KEYS` کشف‌محور است (اجتماعِ دو کاتالوگ)، پس این ادعا **مشتق** است نه
    مستقل — ولی همان چیزی است که قید می‌گوید، و اگر روزی `TEXT_KEYS` به یک
    فهرستِ دستی تبدیل شود این تست قرمز می‌شود نه بسته‌ها بی‌صدا ناقص.
    """
    for key in ("btn_settings", "btn_help", "btn_change_language",
                "settings_title", "help_text"):
        assert key in FA, f"{key} در کاتالوگِ fa نیست"
        assert key in EN, f"{key} در کاتالوگِ en نیست"
        assert key in TEXT_KEYS, f"{key} واردِ بستهٔ ترجمه نمی‌شود"


def test_the_help_text_needs_no_placeholder_and_fits_one_message():
    """صفر placeholder یک **تصمیم** است: هر placeholder یک راهِ اضافه برای ردشدنِ
    بستهٔ مترجم است (گاردِ `require_all_placeholders` فاز B) در ازای هیچ."""
    for cat in (FA, EN):
        assert _fields(cat["help_text"]) == set()
        assert len(cat["help_text"]) < 3900  # سقفِ امنِ textstore._MAX_LEN


def test_the_catalog_map_is_the_two_files_and_nothing_else():
    """کنترل: اگر کاتالوگِ سومی اضافه شود، این فایل دیگر همه را نمی‌سنجد."""
    assert set(CATALOG) == {"fa", "en"}
    assert CATALOG["fa"] is FA and CATALOG["en"] is EN
