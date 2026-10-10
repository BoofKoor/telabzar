"""منطقِ خالصِ `app/pdftext.py`: ترتیبِ دیداری → منطقی، جهتِ پاراگراف، سطر و ستون.

ورودی‌ها **ترتیبِ دیداری**اند، همان‌طور که گلیف‌ها روی صفحه از چپ به راست
نشسته‌اند — شکلی که pdfplumber می‌دهد. هر حالت با قاعدهٔ UAX #9 دستی ساخته شده و
در داکس‌استرینگش آمده، تا تست به خودِ کدِ زیرِ آزمون تکیه نکند.
"""
from __future__ import annotations

from app import pdftext as X


def _vis(s: str) -> list[str]:
    return list(s)


# ── vis2log ──────────────────────────────────────────────────────
def test_the_lam_alef_ligature_is_one_unit_and_is_not_reversed_inside():
    """«سلام» روی صفحه: م، لا، س (چپ به راست). poppler جعبهٔ «لا» را بینِ دو حرفش
    تقسیم و بعد برعکس می‌کند → «سالم». گلیفِ یکپارچه برعکس نمی‌شود."""
    assert X.vis2log(["م", "لا", "س"], True) == "سلام"
    assert X.vis2log(["ا", "ل", "ا", "ب"], True) == "بالا"


def test_english_and_numbers_inside_an_rtl_paragraph():
    """منطقی: «عدد 12 و English.» در پاراگرافِ راست‌به‌چپ.
    سطح‌ها: عدد/و/فاصله‌ها/نقطه = ۱، «12» و «English» = ۲ → روی صفحه
    «.English و 12 ددع» (نقطه سمتِ چپ چون پایانِ پاراگرافِ R است)."""
    assert X.vis2log(_vis(".English و 12 ددع"), True) == "عدد 12 و English."


def test_persian_digits_stay_in_their_own_order():
    """رقمِ فارسی (EN) در جملهٔ فارسی چپ‌به‌راست نمایش داده می‌شود."""
    assert X.vis2log(_vis("۱۲۳۴ ددع"), True) == "عدد ۱۲۳۴"


def test_mirrored_parentheses_come_back():
    """منطقی «(با پرانتز)» همه سطحِ ۱: برعکس می‌شود و پرانتز آینه (L4) → روی صفحه
    «(زتنارپ اب)». بدونِ برگرداندنِ آینه «)با پرانتز(» درمی‌آمد (اندازه‌گیری‌شده روی Chrome)."""
    assert X.vis2log(_vis("(زتنارپ اب)"), True) == "(با پرانتز)"


def test_a_pure_ltr_line_is_untouched():
    assert X.vis2log(_vis("Hello (world) 12"), False) == "Hello (world) 12"


def test_a_persian_word_inside_an_ltr_paragraph():
    """پاراگرافِ چپ‌به‌راست با یک کلمهٔ فارسی: فقط همان کلمه برعکس می‌شود."""
    assert X.vis2log(_vis("a یسراف word"), False) == "a فارسی word"


# ── جهتِ پاراگراف ─────────────────────────────────────────────────
def test_block_rtl_reads_the_side_of_the_full_stop():
    """ترتیبِ دیداری: پاراگرافِ راست‌به‌چپ نقطه را **چپ** دارد، پاراگرافِ چپ‌به‌راستِ
    فارسی (خروجیِ LibreOffice از TXT) نقطه را **راست** — هر دو تمام‌فارسی."""
    assert X.block_rtl([_vis(".تسا نیا")]) is True
    assert X.block_rtl([_vis("تسا نیا.")]) is False
    assert X.block_rtl([_vis("Hello.")]) is False
    assert X.block_rtl([_vis("مالس")]) is True


def test_logical_rtl_is_the_majority_not_the_full_stop():
    """متنِ **منطقی** (TXT، خروجیِ tesseract): نقطهٔ پایانِ جملهٔ فارسی هم در انتهاست.
    `block_rtl` روی همین ورودی جملهٔ فارسی را چپ‌چین می‌کرد (اندازه‌گیری‌شده)."""
    line = "این یک فایل متنی فارسی است."
    assert X.logical_rtl(line) is True
    assert X.block_rtl([list(line)]) is False, "کنترل: اگر این عوض شد، تستِ بالا را دوباره بسنج"
    assert X.logical_rtl("Hello سلام world") is False
    assert X.logical_rtl("") is False


def test_txt_marks_only_the_lines_that_need_it():
    rlm, lrm = "‏", "‎"
    assert X._mark_dir("English اول", True) == rlm + "English اول"
    assert X._mark_dir("فارسی", True) == "فارسی"
    assert X._mark_dir("فارسی first", False) == lrm + "فارسی first"


# ── سطر از گلیف‌ها ───────────────────────────────────────────────
def _c(text, x0, x1, size=10.0, top=0.0, font="Vazirmatn"):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + size,
            "size": size, "fontname": font}


def test_libreoffice_zwnj_is_a_zero_advance_space_between_joining_letters():
    """LO نیم‌فاصله را با گلیفِ «فاصله»ای می‌نویسد که پیشروی ندارد و روی حرفِ بعدی
    می‌افتد. «پی‌دی» روی صفحه: ی، د، [فاصله]، ی، پ."""
    chars = [_c("ی", 10, 14), _c("د", 14, 18), _c(" ", 18, 20), _c("ی", 18, 22), _c("پ", 22, 26)]
    units, _, _ = X.line_units(chars)
    assert "‌" in units and " " not in units


def test_a_real_word_gap_is_a_space():
    chars = [_c("a", 0, 5), _c("b", 5, 10), _c("c", 20, 25)]
    units, _, _ = X.line_units(chars)
    assert "".join(units) == "ab c"


def test_a_diacritic_attaches_to_its_letter():
    """فتحه جعبه‌ای درونِ حرفِ پایه دارد؛ اگر واحدِ جدا بماند بعد از برگرداندن
    پیش از حرفش می‌نشیند."""
    chars = [_c("ب", 10, 16), _c("َ", 12, 14), _c("ک", 16, 22)]
    units, _, _ = X.line_units(chars)
    assert units == ["بَ", "ک"]


def test_presentation_forms_are_normalized():
    """pdfplumber گاهی فرمِ نمایشی می‌دهد («ﻼ» = لیگاتورِ لا)."""
    units, _, _ = X.line_units([_c("ﻼ", 0, 8)])
    assert units == ["لا"]


def test_fake_bold_duplicates_are_dropped_in_linear_time():
    a = _c("x", 0.0, 5.0)
    b = dict(a, x0=0.2, x1=5.2)          # همان حرف، کسرِ نقطه جابه‌جا
    c = _c("y", 5.0, 10.0)
    assert X.dedupe([a, b, c]) == [a, c]


# ── ستون‌های راست‌به‌چپ ─────────────────────────────────────────
def _ln(x0, x1, y, text, flow=0):
    ln = X.Line(x0, y, x1, y + 12, flow=flow, words=text.split(),
                word_w=[len(w) * 5.0 for w in text.split()])
    ln.units = list(text)
    return ln


def test_rtl_columns_are_read_right_first():
    """poppler ستون‌ها را از چپ می‌خواند؛ نوارِ فارسیِ دوستونه از **راست**."""
    left = [_ln(50, 250, 100 + 14 * i, "تسا پچ نوتس") for i in range(4)]
    right = [_ln(300, 500, 100 + 14 * i, "تسا تسار نوتس") for i in range(4)]
    out = X._rtl_column_order(left + right)
    assert out[:4] == right and out[4:] == left
    assert len({ln.flow for ln in right}) == 1 and right[0].flow != left[0].flow


def test_ltr_columns_keep_popplers_order():
    left = [_ln(50, 250, 100 + 14 * i, "left column") for i in range(4)]
    right = [_ln(300, 500, 100 + 14 * i, "right column") for i in range(4)]
    assert X._rtl_column_order(left + right) == left + right


def test_a_single_rtl_column_is_not_reordered():
    """صفحهٔ تک‌ستونهٔ فارسی: ترتیبِ poppler درست است و بازچینی فقط پاراگراف را می‌شکست."""
    col = [_ln(50, 500, 100 + 14 * i, "یسراف نتم کی") for i in range(8)]
    assert X._rtl_column_order(col) == col


# ── پاراگراف ────────────────────────────────────────────────────
def test_a_short_last_line_ends_the_paragraph():
    """سطرِ کوتاه یعنی کلمهٔ اولِ سطرِ بعد جا می‌شد و باز هم شکسته شده."""
    page = X.Page(1, 600, 800)
    page.lines = [_ln(50, 500, 100, "one two three four five six seven eight"),
                  _ln(50, 200, 114, "end here."),
                  _ln(50, 500, 128, "next paragraph starts and runs long enough")]
    paras = X.group(page)
    assert [len(p.lines) for p in paras] == [2, 1]


def test_a_vertical_gap_ends_the_paragraph():
    page = X.Page(1, 600, 800)
    page.lines = [_ln(50, 500, 100, "a b c d e f g h i j k"),
                  _ln(50, 500, 140, "a b c d e f g h i j k")]
    assert len(X.group(page)) == 2


def test_wrapped_lines_stay_one_paragraph():
    page = X.Page(1, 600, 800)
    page.lines = [_ln(50, 500, 100, "a b c d e f g h i j k"),
                  _ln(50, 498, 114, "a b c d e f g h i j k"),
                  _ln(50, 300, 128, "last")]
    assert [len(p.lines) for p in X.group(page)] == [3]


def test_hyphenated_english_is_joined_for_word():
    p = X.Para([_ln(0, 100, 0, "exam-"), _ln(0, 100, 14, "ple text")])
    for ln in p.lines:
        ln.text = "".join(ln.units)
    assert p.joined() == "example text"
