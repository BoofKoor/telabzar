"""رگرسیونِ بمبِ آرشیو: سقفِ حجم باید **حین استخراج** اعمال شود.

باگ: `archive_extract` فقط مجموعِ `7z l` را پیش از استخراج چک می‌کرد، و آن فهرست
ناقص/قابلِ‌جعل است (`.7z`ِ solid فایل‌های بعدِ اولی را با ستونِ حجمِ خالی نشان
می‌دهد و پارس ردشان می‌کند؛ حجمِ `.gz` از تریلری می‌آید که مهاجم می‌نویسد). بعد
`7z x` بدونِ سقفِ بایت می‌نوشت → پرشدنِ دیسکِ مشترکِ Postgres/Redis. رفع:
`_extract_capped` حجمِ روی دیسک را حین استخراج می‌پاید و از سقف که رد شد فرایند
را می‌کُشد.

این‌جا به‌جای 7zِ واقعی (که در این محیط نیست) یک «استخراج‌کنندهٔ» کُندِ جعلی
جای `SEVENZ` می‌نشیند که مدام بایت در خروجی می‌نویسد — پس آنچه سنجیده می‌شود
خودِ سازوکارِ سقف است.
"""
from __future__ import annotations

import asyncio
import os
import stat
import sys
import textwrap

import pytest

from app import processing as P


_FAKE = textwrap.dedent("""\
    #!%s
    import os, sys, time
    outdir = next((a[2:] for a in sys.argv if a.startswith('-o')), '.')
    os.makedirs(outdir, exist_ok=True)
    # نوشتنِ پیوستهٔ بایت تا جایی که یا کشته شویم یا به سقفِ بزرگ برسیم
    with open(os.path.join(outdir, 'bomb.bin'), 'wb') as f:
        for _ in range(2000):            # تا ~2GB اگر کسی جلوش را نگیرد
            f.write(b'\\0' * (1024 * 1024))
            f.flush()
            time.sleep(0.02)
""" % sys.executable)


@pytest.fixture
def fake_sevenz(tmp_path, monkeypatch):
    script = tmp_path / "fake7z"
    script.write_text(_FAKE)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setattr(P, "SEVENZ", str(script))
    return script


def _run_drained(coro_fn):
    """مثلِ asyncio.run، ولی پیش از بستنِ لوپ یک لحظه صبر می‌کند تا transportِ
    فرایندِ کشته‌شده reap شود (kill_orphan عمداً await نمی‌کند؛ در ورکرِ واقعی
    لوپ می‌ماند و خودش درویش می‌کند — این‌جا فقط نویزِ هشدارِ تست را می‌گیرد)."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coro_fn())
        loop.run_until_complete(asyncio.sleep(0.15))
    finally:
        loop.close()


def test_extraction_is_killed_when_it_exceeds_the_cap(tmp_path, fake_sevenz):
    exdir = str(tmp_path / "ex")
    cap = 10 * 1024 * 1024        # 10MB

    async def go():
        with pytest.raises(RuntimeError, match="exceeds"):
            await P._extract_capped("archive.7z", exdir, cap)

    _run_drained(go)
    # فرایند کشته شده و حجمِ روی دیسک نباید خیلی از سقف رد شده باشد (نه گیگابایت‌ها)
    size = P._dir_size(exdir)
    assert size < cap + 50 * 1024 * 1024, f"wrote {size} bytes before kill"


def test_small_extraction_completes(tmp_path, monkeypatch):
    # استخراجِ کوچک (زیرِ سقف) باید عادی تمام شود
    small = textwrap.dedent("""\
        #!%s
        import os, sys
        outdir = next((a[2:] for a in sys.argv if a.startswith('-o')), '.')
        os.makedirs(outdir, exist_ok=True)
        open(os.path.join(outdir, 'ok.txt'), 'wb').write(b'x' * 1024)
    """ % sys.executable)
    script = tmp_path / "small7z"
    script.write_text(small)
    script.chmod(0o755)
    monkeypatch.setattr(P, "SEVENZ", str(script))
    exdir = str(tmp_path / "ex")

    async def go():
        await P._extract_capped("a.7z", exdir, 10 * 1024 * 1024)

    _run_drained(go)
    assert os.path.exists(os.path.join(exdir, "ok.txt"))
