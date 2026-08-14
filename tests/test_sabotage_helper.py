"""خودِ ابزارِ سابوتاژ هم باید سابوتاژ‌پذیر باشد، وگرنه یک گاردِ بی‌اثرِ دیگر است.

سه ادعا، و اولی همانی است که ابزار برایش ساخته شد: اگر رشتهٔ هدف پیدا نشود، این
باید **بیفتد** — چون تنها فرقِ «تست‌ها نگرفتند» با «خرابکاری اصلاً اعمال نشد»
همین است، و هر دو از بیرون «سبز» دیده می‌شوند.
"""
from __future__ import annotations

import pytest

from tests.sabotage import SabotageError, patch_source, sabotage

_SRC = "def f():\n    return 1\n"


def test_a_pattern_that_is_not_there_raises(tmp_path):
    """دو باری که این در ریپو اتفاق افتاد دقیقاً همین بود."""
    p = tmp_path / "m.py"
    p.write_text(_SRC)

    with pytest.raises(SabotageError):
        patch_source(p, "return 2", "return 3")

    assert p.read_text() == _SRC, "فایل نباید دست بخورد"


def test_a_pattern_that_matches_twice_raises(tmp_path):
    """`trim_video`/`trim_audio`: خطِ فرمانشان یکی شد و سابوتاژ به دومی خورد."""
    p = tmp_path / "m.py"
    p.write_text("x = 1\ny = 1\n")

    with pytest.raises(SabotageError):
        patch_source(p, "= 1", "= 2")

    assert p.read_text() == "x = 1\ny = 1\n"


def test_the_source_is_restored_even_when_the_body_raises(tmp_path):
    """اجرای نیمه‌کاره نباید درخت را کثیف بگذارد."""
    p = tmp_path / "m.py"
    p.write_text(_SRC)

    with pytest.raises(RuntimeError):
        with sabotage(p, "return 1", "return 2") as target:
            assert "return 2" in target.read_text(), "خرابکاری باید واقعاً اعمال شود"
            raise RuntimeError("pytest failed")

    assert p.read_text() == _SRC
