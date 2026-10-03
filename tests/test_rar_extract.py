"""فاز ۳ / موردِ ۲۵ — RARِ واقعی استخراج شود، و خطای ابزار نامِ خودش را ببرد.

7-Zipِ دبیان/اوبونتو (`+dfsg`) کدک‌های RAR را به‌خاطرِ مجوزِ unRAR ندارد: فهرستِ
سرآیند را می‌خواند ولی هر عضوِ **فشرده** را با «Unsupported Method» رد می‌کند،
یعنی تقریباً هر RARی که کاربر می‌فرستد. `unrar-free` در `docker/worker.Dockerfile`
نصب بود و هیچ‌جا صدا زده نمی‌شد.

فیکسچرِ فشرده (`rar5-solid.rar`) از مجموعهٔ تستِ پروژهٔ `rarfile` است (مجوزِ ISC،
© Marko Kreen) — ساختنِ RARِ فشرده بدونِ `rar`ِ تجاری ممکن نیست. آرشیوهای خصمانه
اما **همین‌جا** ساخته می‌شوند (RAR4ِ stored، چند ده خط) تا نام‌هایشان دقیقاً
همان چیزی باشد که تست ادعا می‌کند.
"""
from __future__ import annotations

import ast
import base64
import inspect
import os
import shutil
import struct
import sys
import zlib

import pytest

from app import processing as P

_HAS = bool(shutil.which(P.UNRAR)) and bool(shutil.which(P.SEVENZ))
needs_unrar = pytest.mark.skipif(not _HAS, reason="unrar-free و 7z روی PATH لازم‌اند")

# rarfile 4.5 · test/files/rar5-solid.rar — دو عضوِ فشرده، هرکدام ۲۰۴۸ بایت «000…».
RAR5_SOLID = base64.b64decode(
    "UmFyIRoHAQAJ78hvCwEFBwQGAQGAgIAA3vVwchwCAroABIAQtoMCoua3xYAbAQpzdGVzdDEudHh0"
    "waw3REQj+iP2l/1iU1G+TJGBQQKMwQN5XL9Ho6otoDaT3aBYAEACANRQBHb2xH8y6p8ypcTM14Pf"
    "ABDoLYkcAgKNAASAELaDAqLmt8XAGwEKc3Rlc3QyLnR4dEUVCmABAAgD37f79vwdd1ZRAwUEAA==")
_EXPECTED = "".join(f"{i:03d}\n" for i in range(512))


def _hdr(htype: int, flags: int, body: bytes) -> bytes:
    tail = struct.pack("<BHH", htype, flags, 7 + len(body)) + body
    return struct.pack("<H", zlib.crc32(tail) & 0xFFFF) + tail


def rar4_stored(members: list[tuple[str, bytes]]) -> bytes:
    """RAR 1.5–4.x با روشِ stored (0x30): نشانگر، سرآیندِ آرشیو، سرآیندِ هر فایل، پایان."""
    out = b"Rar!\x1a\x07\x00" + _hdr(0x73, 0, struct.pack("<HI", 0, 0))
    for name, data in members:
        nb = name.encode()
        body = struct.pack("<IIBIIBBHI", len(data), len(data), 3, zlib.crc32(data),
                           0x5A6B0000, 20, 0x30, len(nb), 0o100644) + nb
        out += _hdr(0x74, 0x8000, body) + data
    return out + _hdr(0x7B, 0x4000, b"")


def test_the_unrar_gate_is_not_dead_weight():
    """همان شکلِ `test_the_7z_gate_is_not_dead_weight`: با AST، تعدادِ تست‌های گیت‌خورده."""
    tree = ast.parse(inspect.getsource(sys.modules[__name__]))
    gated = [n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
             and any(isinstance(d, ast.Name) and d.id == "needs_unrar" for d in n.decorator_list)]
    assert len(gated) >= 3, gated


@needs_unrar
async def test_a_compressed_rar_extracts(tmp_path):
    """پیش از رفع: `7z x` با «Unsupported Method» و کدِ ۲ → «extract failed»."""
    arc = tmp_path / "in.rar"
    arc.write_bytes(RAR5_SOLID)
    files = await P.archive_extract(str(arc), str(tmp_path / "w"), 100, 10 << 20)
    assert sorted(os.path.basename(f) for f in files) == ["stest1.txt", "stest2.txt"]
    for f in files:
        with open(f, encoding="ascii") as fh:
            assert fh.read() == _EXPECTED


@needs_unrar
async def test_a_compressed_rar_lists(tmp_path):
    arc = tmp_path / "in.rar"
    arc.write_bytes(RAR5_SOLID)
    assert await P.archive_list(str(arc)) == [("stest1.txt", 2048), ("stest2.txt", 2048)]


@needs_unrar
@pytest.mark.parametrize("name", ["../escape.txt", "a/../../escape.txt", "ABS"],
                         ids=["dotdot", "nested-dotdot", "absolute"])
async def test_a_hostile_rar_cannot_write_outside(tmp_path, name):
    """پینِ رفتارِ خودِ `unrar-free` — گاردِ بعدیِ `archive_extract` فقط فهرست را
    فیلتر می‌کند و جلوی نوشتن را نمی‌گیرد (همان استدلالِ پینِ 7z در فاز ۲الف)."""
    outside = tmp_path / "escape.txt"
    if name == "ABS":
        name = str(outside)
    arc = tmp_path / "evil.rar"
    arc.write_bytes(rar4_stored([(name, b"pwned\n"), ("ok.txt", b"fine\n")]))
    work = tmp_path / "deep" / "w"
    work.mkdir(parents=True)
    try:
        await P.archive_extract(str(arc), str(work), 100, 10 << 20)
    except RuntimeError:
        pass                                     # ردِ کلِ آرشیو هم پذیرفته است
    assert not outside.exists(), "unrar-free بیرون از پوشهٔ استخراج نوشت"
    assert not (tmp_path / "deep" / "escape.txt").exists()


@needs_unrar
async def test_a_7z_archive_still_goes_through_7z(tmp_path, monkeypatch):
    """کنترل: فقط RAR مسیرش عوض شد؛ zip همان 7z است."""
    import zipfile
    arc = tmp_path / "a.zip"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("x.txt", "hi")
    monkeypatch.setattr(P, "UNRAR", "/nonexistent/unrar")
    files = await P.archive_extract(str(arc), str(tmp_path / "w"), 100, 10 << 20)
    assert [os.path.basename(f) for f in files] == ["x.txt"]


def test_the_unrar_listing_parser():
    """خروجیِ واقعیِ `unrar-free -t` (۰٫۱٫۳)، با پوشه و نامِ فاصله‌دار — بی‌نیاز به باینری."""
    out = (
        "\nunrar-free 0.1.3  Copyright (C) 2004  Ben Asselstine, Jeroen Dekkers\n\n\n"
        "RAR archive /x/a.rar\n\nPathname/Comment\n"
        "                  Size   Date   Time     Attr\n"
        "----------------------------------------------\n"
        " sub/with space/long fn.txt\n"
        "                     8 20-07-20 18:02   .....A\n"
        " sub/dir1\n"
        "                     0 20-07-20 18:01   .D....\n"
        " 1234\n"
        "                  2048 12-06-11 12:53   .....A\n"
        "----------------------------------------------\n"
        "    3             2056\n")
    assert P._parse_unrar_list(out) == [("sub/with space/long fn.txt", 8), ("1234", 2048)]


async def test_a_failing_tool_is_named_in_the_error():
    """`_run` فرمانِ pdftotext/pdftoppm/pdfunite را هم اجرا می‌کند؛ پیش از رفع هر
    شکستی «ffmpeg failed» نوشته می‌شد."""
    with pytest.raises(RuntimeError) as exc:
        await P._run([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30)
    msg = str(exc.value)
    assert msg.startswith(f"{os.path.basename(sys.executable)} failed (code 3)"), msg
    assert "ffmpeg" not in msg
