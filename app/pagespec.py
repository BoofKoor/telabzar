"""ورودیِ کاربر برای ابزارهای PDF: «کدام صفحه‌ها» (`1-3, 5, 8-` یا `۲ تا ۴ و ۷`) و رمز.

عمداً **بی‌وابستگی** است (مثلِ `dl_active.py`): روتر در پروسهٔ ربات نحو را
می‌سنجد تا کاربر همان لحظه «نامعتبر» بگیرد و در FSM بماند، ولی ایمیجِ ربات
Pillow/poppler ندارد و `pdftools` را نمی‌تواند import کند. تعدادِ صفحه‌ها فقط در
ورکر معلوم است، پس کار دو نیمه دارد: `parse` (نحو، در ربات) و `expand` (کران، در
ورکر روی تعدادِ واقعی). قاعدهٔ رمز (`check_password`) هم همین‌جاست تا ربات و ورکر
**یک** نسخه از آن داشته باشند، نه دو کپیِ دست‌نویس.

ترتیبِ کاربر حفظ می‌شود: «۳، ۱، ۲» یعنی همین ترتیب در خروجی — یعنی «جدا کردنِ
صفحات» رایگان «مرتب‌کردنِ صفحات» هم هست. بازهٔ برعکس («۵-۱») هم مجاز است.
"""
from __future__ import annotations

import re

from .panel_fmt import ascii_digits

#: سقفِ تعدادِ تکه‌ها و بزرگ‌ترین شماره — ورودیِ کاربر است و تا زیرفرایند می‌رود.
MAX_PARTS = 200
MAX_PAGE = 100_000

_LAST = {"آخر", "اخر", "last", "end", "z"}
_SPLIT = re.compile(r"[,،;+\s]+")
_RANGE = re.compile(r"^(\d+|آخر|اخر|last|end|z)?\s*(?:-|–|—|تا|to)\s*(\d+|آخر|اخر|last|end|z)?$")

#: «تا انتها» در یک بازه
OPEN = None


def _norm(spec: str) -> str:
    s = ascii_digits(spec or "").strip().lower()
    s = re.sub(r"\s+و\s+", ",", s)          # «۲ و ۵»
    # «۲ تا ۴» → «2-4» پیش از شکستن روی فاصله، وگرنه «تا» خودش یک تکه می‌شد
    s = re.sub(r"\s*(?:تا|to)\s*", "-", s)
    return re.sub(r"\s*[-–—]\s*", "-", s)


def _num(tok: str | None, *, empty) -> int | None:
    if tok is None or tok == "":
        return empty
    if tok in _LAST:
        return OPEN
    return int(tok)


def parse(spec: str) -> list[tuple[int, int | None]] | None:
    """متن → فهرستِ (از، تا) با `تا=None` یعنی «تا صفحهٔ آخر». نامعتبر → `None`.

    «آخر» به‌تنهایی هم یک تکه است: `(None, None)` نیست، بلکه بعداً در `expand`
    به شمارهٔ آخر تبدیل می‌شود — برای همین آن را `(0, None)` نگه می‌داریم.
    """
    s = _norm(spec)
    if not s:
        return None
    parts = [p for p in _SPLIT.split(s) if p]
    if not parts or len(parts) > MAX_PARTS:
        return None
    out: list[tuple[int, int | None]] = []
    for p in parts:
        if p.isdigit():
            n = int(p)
            if not 1 <= n <= MAX_PAGE:
                return None
            out.append((n, n))
            continue
        if p in _LAST:
            out.append((0, OPEN))       # «آخر» → در expand
            continue
        m = _RANGE.match(p)
        if not m or (m.group(1) is None and m.group(2) is None):
            return None
        a = _num(m.group(1), empty=1)
        b = _num(m.group(2), empty=OPEN)
        if a is OPEN:                   # «آخر-۳»
            a = 0
        for x in (a, b):
            if x is not None and x != 0 and not 1 <= x <= MAX_PAGE:
                return None
        out.append((a, b))
    return out


def expand(ranges: list[tuple[int, int | None]], n: int) -> list[int]:
    """بازه‌ها → شماره‌صفحه‌ها (۱-مبنا) با ترتیبِ کاربر و بدونِ تکرار.

    `ValueError(صفحه)` اگر شماره‌ای بیرونِ ۱..n باشد — پیامِ کاربر آن صفحه را
    نام می‌برد. `0` در `از` یعنی «آخر» (از `parse`).
    """
    pages: list[int] = []
    seen: set[int] = set()
    for a, b in ranges:
        lo = n if a == 0 else a
        hi = n if b is OPEN else b
        for x in (lo, hi):
            if not 1 <= x <= n:
                raise ValueError(x)
        step = 1 if hi >= lo else -1
        for p in range(lo, hi + step, step):
            if p not in seen:
                seen.add(p)
                pages.append(p)
    return pages


def label(pages: list[int]) -> str:
    """فهرستِ صفحه → برچسبِ فشرده برای نامِ فایل/لاگ: `[1,2,3,7]` → `1-3,7`."""
    if not pages:
        return ""
    parts: list[str] = []
    start = prev = pages[0]
    for p in pages[1:] + [None]:
        if p is not None and p == prev + 1:
            prev = p
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        if p is not None:
            start = prev = p
    return ",".join(parts)


# ── رمز ──────────────────────────────────────────────────────────
#: سقفِ طولِ رمز — AES-256 (R6) تا ۱۲۷ بایتِ UTF-8 را معنا می‌کند.
PASSWORD_MAX_BYTES = 127
#: رمز در Redis فقط تا وقتی که جاب برداشته شود؛ هرگز در جدولِ jobs (که پنل
#: نشانش می‌دهد) و هرگز روی خطِ فرمان. جاب فقط توکن را می‌برد.
PW_KEY = "pdfpw:{tok}"
PW_TTL = 900


def check_password(pw: str) -> bool:
    """رمزِ قابلِ‌قبول: ناتهی، تک‌خطی (فایلِ آرگومانِ qpdf خط‌به‌خط است)، زیرِ سقف."""
    return bool(pw) and "\n" not in pw and "\r" not in pw \
        and len(pw.encode("utf-8")) <= PASSWORD_MAX_BYTES
