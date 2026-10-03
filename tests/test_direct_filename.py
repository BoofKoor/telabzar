"""رگرسیونِ فرارِ مسیر از راهِ نامِ فایلِ دانلودِ مستقیم.

باگ: `downloader._safe_name` اول `split("/")[-1]` می‌زد و **بعد** unquote می‌کرد،
پس `filename*=UTF-8''%2Fetc%2Fcron.d%2Fx` از جداکردنِ مسیر رد می‌شد و بعد به
`/etc/cron.d/x` باز می‌شد — یک مسیرِ مطلق که در `os.path.join(workdir, name)`
کلِ workdir را دور می‌انداخت. چون کانتینرها root اجرا می‌شوند، یعنی نوشتنِ بایتِ
سرورِ مخرب روی هر فایلِ نوشتنی (اجرای کد). رفع: اول decode (با پاسِ تکراری برای
double-encoding) بعد جداکردنِ مسیر، و یک مهارِ realpath در `download_direct`.
"""
from __future__ import annotations

import asyncio
import os

import pytest
from aiohttp import web

from app import downloader as D


# ── لایهٔ واحد: `direct_filename`/`_safe_name` هرگز مسیر برنمی‌گردانند ──
@pytest.mark.parametrize("disp", [
    "attachment; filename*=UTF-8''%2Fetc%2Fcron.d%2Fx",   # مطلقِ percent-encoded
    "attachment; filename*=UTF-8''%2e%2e%2f%2e%2e%2fx",    # ../../ percent-encoded
    'attachment; filename="%2Fetc%2Fpasswd"',              # مطلق در فرمِ ساده
    'attachment; filename="..%5c..%5cwin.ini"',            # بک‌اسلشِ encoded (ویندوز)
    "attachment; filename*=UTF-8''%252fetc%252fpasswd",    # double-encoded
    'attachment; filename="sub/dir/evil.bin"',             # جداکنندهٔ لفظی
], ids=["abs-star", "dotdot-star", "abs-plain", "backslash", "double-enc", "literal-sep"])
def test_disposition_filename_is_never_a_path(disp):
    name = D.direct_filename("http://h/x", disp, "application/octet-stream")
    assert "/" not in name and "\\" not in name, name
    assert not os.path.isabs(name), name
    assert name not in ("", ".", "..")
    # join با workdir باید داخلِ workdir بماند
    wd = "/work/job"
    assert os.path.realpath(os.path.join(wd, name)).startswith(wd + os.sep)


@pytest.mark.parametrize("url", [
    "http://h/%2fetc%2fpasswd",           # مسیرِ encoded در URL
    "http://h/%252fetc%252fpasswd.bin",   # double-encoded در URL
    "http://h/a/b/../../../../etc/x.bin",
])
def test_url_path_filename_is_never_a_path(url):
    name = D.direct_filename(url, None, None)
    assert "/" not in name and "\\" not in name, name
    assert not os.path.isabs(name), name


# ── لایهٔ انتها‌به‌انتها: `download_direct` بیرونِ workdir نمی‌نویسد ──
def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def _run_server(body: bytes, disp: str):
    async def handler(_req):
        return web.Response(body=body, headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": disp,
        })
    app = web.Application()
    app.router.add_get("/x", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _free_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner, port


async def _attempt(tmp_path, monkeypatch, disp):
    # رزولورِ ضدِ SSRF را دور می‌زنیم تا بتوان به 127.0.0.1 وصل شد (هدفِ این تست
    # مسیرِ نوشتن است، نه SSRF — که تستِ خودش را دارد).
    monkeypatch.setattr(D, "_addr_is_internal", lambda h: False, raising=False)
    runner, port = await _run_server(b"MALICIOUS-BYTES", disp)
    workdir = str(tmp_path / "job")
    try:
        try:
            await D.download_direct(f"http://127.0.0.1:{port}/x", workdir,
                                    opts={}, max_bytes=10 * 1024 * 1024)
        except Exception:  # noqa: BLE001 — هر شکستی قابلِ قبول است، نوشتنِ بیرونی نه
            pass
    finally:
        await runner.cleanup()


def test_download_direct_never_escapes_workdir(tmp_path, monkeypatch):
    sentinel = tmp_path / "SENTINEL_OUTSIDE"
    assert not sentinel.exists()
    # نامی که به مسیرِ خواهرِ workdir اشاره می‌کند
    disp = ("attachment; filename*=UTF-8''"
            + "".join(f"%2f" if c == "/" else c
                      for c in f"..{os.sep}SENTINEL_OUTSIDE").replace(os.sep, "%2f"))
    asyncio.run(_attempt(tmp_path, monkeypatch, disp))
    # هیچ فایلی بیرونِ workdir ساخته نشده باشد
    outside = [p for p in tmp_path.iterdir() if p.name != "job"]
    assert outside == [], f"files written outside workdir: {outside}"
