"""‏`.dockerignore` نباید چیزی را که یک Dockerfile COPY می‌کند بیرون بگذارد.

**چرا این گارد و نه یک بازخوانی:** حذفِ اشتباه از زمینهٔ build همان شکلی از
خرابی است که §۷ برای `node/install.sh` ثبت کرده — تست‌ها از ریشهٔ ریپو
می‌دوند و فایل را می‌بینند، پس **CI سبز می‌ماند** در حالی که ایمیج آن را
ندارد و پنل در تولید ۵۰۰ می‌دهد. یعنی شکستِ خاموش، و تنها نشانه‌اش استقرار.

دو جهت بسته می‌شود:

* هرچه Dockerfileها COPY می‌کنند باید در زمینه بماند (جهتِ خطرناک).
* سنگین‌های شناخته‌شده باید بیرون بمانند (جهتِ حجم/درستی — بدونشان
  `COPY panel ./` همان `node_modules`ی را که `npm ci` نصب کرده بازنویسی
  می‌کند).
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
IGNORE = ROOT / ".dockerignore"
DOCKERFILES = sorted((ROOT / "docker").glob("*.Dockerfile"))


def _patterns() -> list[str]:
    """الگوهای واقعی — کامنت و خطِ خالی دور ریخته می‌شوند.

    §۶ ثبت کرده که هر گاردی که متن اسکن می‌کند سرانجام **توضیحاتِ خودش** را
    می‌خواند؛ این فایل کامنتِ فارسیِ مفصلی دارد که نامِ همین مسیرها را
    می‌برد.
    """
    out = []
    for line in IGNORE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _copied_sources() -> set[str]:
    """مسیرهایی که Dockerfileها از **زمینه** برمی‌دارند.

    `COPY --from=…` کنار گذاشته می‌شود: منبعش یک مرحلهٔ دیگر است نه زمینه،
    پس `.dockerignore` اصلاً رویش اثر ندارد.
    """
    srcs: set[str] = set()
    for df in DOCKERFILES:
        for line in df.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*(?:COPY|ADD)\s+(.*)$", line)
            if not m or "--from=" in line:
                continue
            parts = m.group(1).split()
            # آخرین جزء مقصد است؛ بقیه منبع.
            for src in parts[:-1]:
                if not src.startswith("--"):
                    srcs.add(src)
    return srcs


def test_the_parser_actually_finds_the_copies():
    """کنترلِ ضدِتوخالی: مجموعهٔ تهی هر ادعای زیر را بی‌معنا می‌کند."""
    assert DOCKERFILES, "هیچ Dockerfileی پیدا نشد"
    assert len(_copied_sources()) >= 5, _copied_sources()


def test_the_comment_stripper_is_not_decorative():
    """کامنت‌های خودِ فایل نباید به‌عنوان الگو شمرده شوند."""
    pats = _patterns()
    assert not [p for p in pats if p.startswith("#")]
    # فایل عمداً نثرِ توضیحی دارد؛ اگر دور ریخته نشود، تعدادِ الگو می‌جهد.
    raw = len(IGNORE.read_text(encoding="utf-8").splitlines())
    assert len(pats) < raw


def test_nothing_a_dockerfile_copies_is_excluded():
    """جهتِ خطرناک — حذفِ اشتباه، ایمیجِ ناقص، و CIِ سبز."""
    excluded = set(_patterns())
    clashes = []
    for src in _copied_sources():
        head = src.split("/")[0].rstrip("/")
        if head in excluded or src.rstrip("/") in excluded:
            clashes.append(src)
    assert not clashes, f"این‌ها COPY می‌شوند ولی از زمینه بیرون‌اند: {clashes}"


def test_the_heavy_build_output_is_excluded():
    """جهتِ حجم/درستی.

    بدونِ این، `COPY panel ./` همان `node_modules`ی را که `npm ci` تازه از
    روی lockfile نصب کرده با نسخهٔ محلیِ ماشینِ builder بازنویسی می‌کند.
    """
    pats = set(_patterns())
    for need in ("panel/node_modules", "panel/.next", "app/static/console", ".git"):
        assert need in pats, f"{need} باید از زمینهٔ build بیرون باشد"


def test_the_console_build_output_is_supplied_by_the_node_stage():
    """`app/static/console` بیرون است، پس باید از مرحلهٔ Node بیاید — وگرنه
    ایمیج اصلاً کنسول ندارد و `/console` ۵۰۳ می‌دهد."""
    admin = (ROOT / "docker" / "admin.Dockerfile").read_text(encoding="utf-8")
    assert "--from=console" in admin
    assert "app/static/console" in admin
