"""گیت‌های تست‌های PDF: ابزارهای واقعی (poppler/qpdf/Ghostscript/tesseract) و
کتابخانه‌های پایتونی (pdfplumber/python-docx).

**واقعی، نه ماک** — باگ‌هایی که `app/pdftext.py` برایشان نوشته شده (لیگاتورِ «لا»ِ
برعکسِ poppler، نیم‌فاصلهٔ LibreOffice) فقط با خودِ ابزارها بازتولید می‌شوند. CI
همهٔ این‌ها را نصب و حضورشان را ثابت می‌کند (`.github/workflows/tests.yml`)، و
`test_pdf_gates_are_not_dead_weight` می‌گوید هر گیت چیزی برای گیت‌کردن دارد — همان
دو نیمهٔ قاعدهٔ `needs_7z` (§۶).
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess

import pytest

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "pdf"


def _has_libs() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in ("pdfplumber", "docx"))


def _has_fas() -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "fas" in out.split()


HAS_TOOLS = all(shutil.which(x) for x in ("qpdf", "gs", "pdftoppm", "pdftotext"))

needs_pdf_tools = pytest.mark.skipif(not HAS_TOOLS, reason="qpdf/gs/poppler روی PATH لازم است")
needs_pdf_text = pytest.mark.skipif(not (HAS_TOOLS and _has_libs()),
                                    reason="poppler + pdfplumber + python-docx لازم است")
needs_ocr_fas = pytest.mark.skipif(not (HAS_TOOLS and _has_libs() and _has_fas()),
                                   reason="tesseract با بستهٔ فارسی لازم است")
