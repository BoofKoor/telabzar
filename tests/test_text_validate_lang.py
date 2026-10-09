"""`textstore.validate(…, lang=)` — خطای اعتبارسنجی به زبانِ پنل (۲۰۲۶-۱۰-۰۹).

پنلِ انگلیسی خطای ذخیرهٔ یک متن را فارسی می‌دید، چون همهٔ پیام‌ها در `validate`
هاردکدِ فارسی بودند. حالا هر پیام دو شکل دارد (`_MSG`) و پنل زبانِ خودش را می‌دهد؛
ربات، `/admin` و ورودِ بستهٔ زبان همان پیش‌فرضِ فارسی را می‌گیرند — رفتارشان عوض نشد.
"""
from __future__ import annotations

import string

import pytest

from app import textstore

DEFAULT = "📄 سند: {name}"

#: (ورودی, require_all) → کدِ پیامی که باید بدهد — هر شاخهٔ دسترس‌پذیرِ `validate`.
CASES = {
    "empty": ("   ", False),
    "long": ("x" * (textstore._MAX_LEN + 1), False),
    "syntax": ("سند {", False),
    "unsafe": ("سند {name.attr}", False),
    "unknown": ("سند {zzz}", False),
    "gone": ("سند", True),
    "tag": ("سند <div>{name}</div>", False),
    "mismatch": ("<b><i>{name}</b></i>", False),
    "unclosed": ("<b>{name}", False),
}


def _expect(lang: str, code: str, value: str) -> str:
    """پیامِ مورد انتظار، با همان پارامترهایی که `validate` به قالب می‌دهد."""
    kw = {"long": {"n": textstore._MAX_LEN}, "unsafe": {"bad": textstore.unsafe_placeholder(value)},
          "unknown": {"names": "{zzz}"}, "gone": {"names": "{name}"}, "tag": {"tag": "<div>"},
          "mismatch": {"tag": "</b>"}, "unclosed": {"tag": "<b>"}}.get(code, {})
    return textstore._msg(lang, code, **kw)


@pytest.mark.parametrize("code", sorted(CASES), ids=sorted(CASES))
def test_every_message_speaks_the_requested_language(code):
    value, strict = CASES[code]
    fa = textstore.validate(DEFAULT, value, require_all_placeholders=strict)
    en = textstore.validate(DEFAULT, value, require_all_placeholders=strict, lang="en")
    assert fa == _expect("fa", code, value), fa
    assert en == _expect("en", code, value), en
    assert fa != en
    assert not any("؀" <= c <= "ۿ" for c in en.replace(value, "")), en


def test_the_default_language_is_still_persian():
    """ربات، `/admin` و بستهٔ زبان `lang` نمی‌دهند — باید همان پیامِ فارسیِ قبلی را بگیرند."""
    assert textstore.validate(DEFAULT, "<div>x</div>") == "تگِ غیرمجاز: <div>"


def test_a_valid_text_passes_in_both_languages():
    for lang in ("fa", "en"):
        assert textstore.validate(DEFAULT, "سند: <b>{name}</b>", lang=lang) is None


def test_every_message_pair_has_the_same_fields():
    """دو زبانِ یک پیام باید همان پارامترها را بخواهند، وگرنه یکی سرِ `format` می‌ترکد."""
    fields = lambda s: {f for _l, f, _s, _c in string.Formatter().parse(s) if f}  # noqa: E731
    for code, (fa, en) in textstore._MSG.items():
        assert fields(fa) == fields(en), code
