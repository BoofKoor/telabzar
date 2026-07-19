"""اسکنِ بدافزار با ClamAV (پروتکلِ INSTREAM — استریمِ فایل، بدون بارگذاریِ کامل در حافظه)."""
from __future__ import annotations

import asyncio

from .config import settings


class ScanUnavailable(RuntimeError):
    """clamd در دسترس نیست یا خطای پروتکل (نه یعنی فایل آلوده است)."""


def _scan_sync(path: str) -> tuple[str, str | None]:
    import clamd

    try:
        cd = clamd.ClamdNetworkSocket(
            host=settings.clamav_host, port=settings.clamav_port, timeout=300
        )
        with open(path, "rb") as fh:
            result = cd.instream(fh)
    except Exception as exc:  # noqa: BLE001  — اتصال/پروتکل/سقف‌حجم → «در دسترس نیست»
        raise ScanUnavailable(str(exc)) from exc
    # result مثلِ {"stream": ("OK", None)} یا {"stream": ("FOUND", "Virus-Name")}
    status, name = result.get("stream", ("ERROR", None))
    return status, name


async def scan_file(path: str) -> tuple[str, str | None]:
    """(status, name) — status: OK | FOUND. در خطای اتصال، ScanUnavailable می‌دهد."""
    return await asyncio.to_thread(_scan_sync, path)
