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


# ── خواندنِ نتیجهٔ اجرا ────────────────────────────────────────────
def _verdict(stdout: str, expect: str | None) -> tuple[bool, str]:
    """`_run_case` را با یک خروجیِ ساختگیِ pytest صدا می‌زند.

    ادعا دربارهٔ **خواندنِ خروجی** است، نه دربارهٔ اجرای زیرفرایند؛ پس فقط
    `subprocess.run` جایگزین می‌شود و بقیهٔ مسیر — از جمله خودِ `sabotage()` که
    فایل را عوض و برمی‌گرداند — واقعی می‌ماند. الگو عمداً روی همین فایل و روی
    رشته‌ای است که دقیقاً یک بار می‌آید، وگرنه `SabotageError` می‌گیریم.
    """
    import subprocess
    from types import SimpleNamespace
    from unittest.mock import patch

    from tests import sabotage as S

    case = {"path": __file__, "old": _MARKER, "new": _MARKER + " ",
            "target": "tests/nonexistent.py", "expect": expect}
    with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout=stdout)):
        return S._run_case(case)


#: رشته‌ای که فقط یک بار در این فایل می‌آید — هدفِ بی‌ضررِ `_verdict`.
_MARKER = "# sabotage-self-test-anchor"


_SUMMARY = "=========================== short test summary info ============================"


def _pytest_out(*summary: str, body: str = "", tail: str = "1 failed in 0.10s") -> str:
    """خروجیِ واقع‌نمای `pytest -q`: بدنه، بعد بخشِ خلاصه، بعد خطِ پایانی.

    شکلش مهم است، چون `_run_case` عمداً فقط **بخشِ خلاصه** را می‌خواند؛
    فیکسچری که این ساختار را نداشته باشد، ادعای دیگری می‌سنجد.
    """
    parts = [body] if body else []
    if summary:
        parts += [_SUMMARY, *summary]
    parts.append(tail)
    return "\n".join(parts) + "\n"


def test_a_target_that_cannot_even_run_is_not_reported_as_not_caught():
    """«اجرا نشد» حالتِ سومی است، نه «نگرفت» — و این تفکیک با اجرا پیدا شد.

    موردی که به `tests/panel/` اشاره می‌کند، از venvی بدونِ jinja2/cryptography
    صفر خطِ `FAILED` می‌دهد و ۳۱ خطِ `ERROR`. نسخهٔ قبلی این را «سابوتاژ
    نگرفت» می‌خواند — یعنی دقیقاً همان برداشتی که §۷ می‌گوید باعث می‌شود کسی
    یک تستِ سالم را ضعیف بخواند و پاکش کند.
    """
    ok, detail = _verdict(
        _pytest_out("ERROR tests/panel/test_save_failures.py::test_x - ModuleNotFoundError",
                    tail="1 error in 0.10s"),
        expect="test_x")
    assert ok is False
    assert "بی‌اعتبار" in detail, f"باید بی‌اعتباری را نام ببرد: {detail}"


def test_a_log_line_starting_with_error_is_not_a_collection_error():
    """و همان چک نباید روی **لاگِ خودِ تست** شلیک کند.

    نسخهٔ اولِ این رفع ابتدای خط را می‌سنجید و سه اجرای کاملاً سالمِ دفترچه را
    «هدف اجرا نشد» خواند، چون `caplog` خطی مثلِ
    `ERROR    telabzar.dl:tasks_download.py:201 cookieless attempt on …` چاپ
    می‌کند. خلاصهٔ pytest تنها گرامرِ قابلِ اتکاست؛ بقیهٔ stdout payload است.
    """
    ok, detail = _verdict(
        _pytest_out("FAILED tests/t.py::test_x - assert 1 == 2",
                    body="ERROR    telabzar.dl:tasks_download.py:201 cookieless attempt"),
        expect="test_x")
    assert ok is True, f"لاگِ تست نباید «اجرا نشد» خوانده شود: {detail}"


def test_an_empty_run_is_not_reported_as_a_clean_reverse_control():
    """کنترلِ معکوس روی هدفی که هیچ تستی اجرا نکرده بی‌معناست.

    بدونِ این، `expect=None` روی یک هدفِ عوض‌شده **سبز** می‌شود: «هیچ‌چیز
    نیفتاد» صادق است، ولی چون چیزی هم اجرا نشده.
    """
    ok, detail = _verdict("no tests ran in 0.01s\n", expect=None)
    assert ok is False
    assert "بی‌اعتبار" in detail, f"باید بی‌اعتباری را نام ببرد: {detail}"


def test_the_empty_run_check_does_not_fire_on_test_content():
    """«اجرا نشد» هم باید از خطِ خلاصه بیاید، نه از هر جای خروجی.

    نسخهٔ اولِ همین رفع زیررشته‌ای بود و تستی که این عبارت را به‌عنوان ورودی
    می‌دهد آن را در تریس‌بکِ خودش چاپ می‌کند — پس یک اجرای کاملاً سالم
    «هدف خالی بود» خوانده می‌شد. خودِ دفترچه سرِ اولین اجرا گرفتش.
    """
    ok, detail = _verdict(
        _pytest_out('FAILED tests/t.py::test_x - AssertionError',
                    body='    _verdict("no tests ran in 0.01s")'),
        expect="test_x")
    assert ok is True, f"اجرای سالم نباید «خالی» خوانده شود: {detail}"


def test_a_genuine_miss_is_still_reported_as_a_miss():
    """کنترلِ معکوس: اجرای سالمی که ادعا را نمی‌اندازد باید «نگرفت» بماند.

    وگرنه رفعِ بالا هر شکستی را به «بی‌اعتبار» ترجمه می‌کرد و ابزار دیگر
    کارِ اصلی‌اش را نمی‌کرد.
    """
    ok, detail = _verdict("5 passed in 1.00s\n", expect="test_x")
    assert ok is False
    assert "بی‌اعتبار" not in detail and "expected test_x to fail" in detail


def test_a_caught_sabotage_is_still_reported_as_caught():
    ok, _ = _verdict(_pytest_out("FAILED tests/t.py::test_x - assert 1 == 2"),
                     expect="test_x")
    assert ok is True
