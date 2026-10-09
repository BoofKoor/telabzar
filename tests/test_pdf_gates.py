"""نگهبانِ گیت‌های PDF (`tests/pdfgates.py`) — همان دو نیمهٔ قاعدهٔ `needs_7z`.

گیتی که هیچ تستی پشتش نیست از هیچ‌چیز محافظت نمی‌کند، و این بی‌صداست: تستِ
پاک‌شده یا دکوراتورِ جاافتاده هیچ چیزی را قرمز نمی‌کند. شمارش **با AST** است، نه
رشته — نسخهٔ رشته‌ایِ گاردِ 7z نامِ دکوراتور را در داکس‌استرینگِ خودش می‌شمرد.
نیمهٔ دیگر (اینکه ابزارها واقعاً روی رانر هستند) گامِ «prove PDF tools» در workflow است.
"""
from __future__ import annotations

import ast
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent

#: کف‌ها کمتر از شمارِ امروزند، تا افزودن آزاد و حذفِ دسته‌جمعی قرمز باشد.
FLOORS = {"needs_pdf_tools": 15, "needs_pdf_text": 8, "needs_ocr_fas": 1}


def _decorated() -> dict[str, int]:
    count = dict.fromkeys(FLOORS, 0)
    for path in HERE.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if isinstance(d, ast.Name) and d.id in count:
                    count[d.id] += 1
    return count


def test_every_pdf_gate_still_gates_something():
    got = _decorated()
    low = {k: v for k, v in got.items() if v < FLOORS[k]}
    assert not low, f"گیتِ PDF بی‌تست شد یا تست‌ها رفتند: {low} (کف: {FLOORS})"


def test_the_ci_runner_installs_and_proves_the_pdf_tools():
    """از `run`ِ گام‌ها خوانده می‌شود نه از متنِ خام — کامنتِ YAML که نامِ بسته را
    می‌برد نصب نمی‌کند (همان تلهٔ «گارد توضیحاتِ خودش را می‌خواند»، §۶)."""
    import yaml

    wf = yaml.safe_load((HERE.parent / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["pytest"]["steps"]
    words = set(re.split(r"[\s;\\]+", " ".join(str(s.get("run", "")) for s in steps)))
    for pkg in ("poppler-utils", "qpdf", "ghostscript", "tesseract-ocr", "tesseract-ocr-fas"):
        assert pkg in words, f"CI بستهٔ {pkg} را نصب نمی‌کند — تست‌های گیت‌شده آن‌جا skip می‌شوند"
    prove = [s for s in steps if s.get("name") == "prove PDF tools are present"]
    assert prove and "tesseract --list-langs" in prove[0]["run"]
