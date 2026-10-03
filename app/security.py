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
    # این تابع **تنها** خوانندهٔ پاسخِ clamd است و فقط دو وضعیتِ قطعی بیرون می‌دهد.
    # شکلِ پاسخ از سورسِ `clamd` 1.0.2 (`instream`): `{"stream": (status, reason)}`،
    # و روی پاسخِ **خالی** `None` — نه استثنا. پیش از فاز ۴ دو چیز غلط بود:
    #   • `None.get` → `AttributeError` **بیرونِ** `try` → جاب با خطای عمومی می‌مرد.
    #   • `("ERROR", "Can't allocate memory")` (یا پیش‌فرضِ `ERROR` وقتی کلید نبود)
    #     به `tasks` می‌رسید که هرچه `OK` نبود را «آلوده — {name}» می‌خواند: کاربر
    #     برای فایلِ سالم «آلوده — Can't allocate memory» می‌گرفت.
    # پس هرچه `OK`/`FOUND` نیست «اسکن در دسترس نیست» است، نه حکم دربارهٔ فایل.
    status, name = next(iter((result or {}).values()), (None, None))
    if status not in ("OK", "FOUND"):
        raise ScanUnavailable(name or status or "empty response from clamd")
    return status, name


async def scan_file(path: str) -> tuple[str, str | None]:
    """(status, name) — status **فقط** OK | FOUND. هر چیزِ دیگر (اتصال، پروتکل،
    پاسخِ خالی، `ERROR`ِ خودِ clamd) `ScanUnavailable` می‌دهد."""
    return await asyncio.to_thread(_scan_sync, path)
