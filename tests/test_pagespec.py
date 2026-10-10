"""`app/pagespec.py` — نحوِ «کدام صفحه‌ها» و قاعدهٔ رمز (هر دو در ربات و ورکر).

خالص و بی‌وابستگی، پس این تست‌ها روی هر محیطی می‌دوند.
"""
from __future__ import annotations

import pytest

from app import pagespec as S


@pytest.mark.parametrize("spec,n,want", [
    ("1-3, 5, 8-", 10, [1, 2, 3, 5, 8, 9, 10]),
    ("۲ تا ۴ و ۷", 10, [2, 3, 4, 7]),          # رقمِ فارسی + «تا» + «و»
    ("٣،١", 5, [3, 1]),                         # رقمِ عربی + ویرگولِ فارسی، ترتیبِ کاربر
    ("5-1", 6, [5, 4, 3, 2, 1]),                # بازهٔ برعکس = مرتب‌سازیِ معکوس
    ("آخر", 9, [9]),
    ("-3", 9, [1, 2, 3]),
    ("1-3 2-4", 9, [1, 2, 3, 4]),               # تکرار حذف، ترتیبِ اولین دیدن
    ("last", 4, [4]),
], ids=["mixed", "persian-ta", "arabic-comma", "reverse", "last-fa", "open-start",
        "dedupe", "last-en"])
def test_parse_and_expand(spec, n, want):
    ranges = S.parse(spec)
    assert ranges is not None, spec
    assert S.expand(ranges, n) == want


@pytest.mark.parametrize("spec", ["", "  ", "abc", "1-2-3", "0", "-", "1,,x",
                                  "1" + ",1" * S.MAX_PARTS, str(S.MAX_PAGE + 1)],
                         ids=["empty", "blank", "words", "double-dash", "zero", "dash",
                              "garbage", "too-many", "too-big"])
def test_bad_specs_are_refused_in_the_bot(spec):
    assert S.parse(spec) is None


def test_a_page_past_the_end_names_the_page():
    """کران فقط در ورکر معلوم است؛ پیامِ کاربر همان صفحه را نام می‌برد."""
    with pytest.raises(ValueError) as exc:
        S.expand(S.parse("2, 12"), 10)
    assert exc.value.args[0] == 12


def test_label_is_compact_and_keeps_order():
    assert S.label([1, 2, 3, 7, 9, 10]) == "1-3,7,9-10"
    assert S.label([3, 1, 2]) == "3,1-2"
    assert S.label([]) == ""


@pytest.mark.parametrize("pw,ok", [
    ("سلام123", True),
    ("x", True),
    ("", False),
    ("two\nlines", False),         # فایلِ آرگومانِ qpdf خط‌به‌خط است
    ("cr\rhere", False),
    ("ب" * 63, True),              # ۱۲۶ بایت
    ("ب" * 64, False),             # ۱۲۸ بایت > ۱۲۷
], ids=["persian", "short", "empty", "newline", "cr", "126-bytes", "128-bytes"])
def test_password_rule(pw, ok):
    assert S.check_password(pw) is ok
