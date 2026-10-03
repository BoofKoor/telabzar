"""فاز ۴ / موردِ ۲۴ — خطای ClamAV «آلوده» گزارش نشود.

`_scan_sync` هر پاسخِ غیرِ `OK` را به `tasks` می‌داد و `tasks` هرچه `OK` نبود را
«⚠️ آلوده — {name}» می‌خواند. پس وقتی clamd خودش خطا می‌داد
(`stream: Can't allocate memory ERROR`)، کاربر برای فایلِ سالم «آلوده — Can't
allocate memory» می‌گرفت. و روی پاسخِ خالی `instream` مقدارِ `None` برمی‌گرداند
(نه استثنا) و `None.get` بیرونِ `try` با `AttributeError` جاب را می‌کشت.

`clamd` فقط در ایمیجِ ورکر است، پس کتابخانه با ماژولِ جعلی جایگزین می‌شود — ولی
شکلِ خروجی‌ها **عیناً** همان است که `clamd` 1.0.2 می‌سازد (`instream`، خط‌های
۱۹۵–۲۰۲): `{"stream": (status, reason)}`، و `None` وقتی پاسخ خالی است. ادعا از
مسیرِ واقعیِ `tasks._do_op` گرفته می‌شود، یعنی همان برچسبی که کاربر می‌بیند.
"""
from __future__ import annotations

import sys
import types

import pytest

from app import tasks as T
from app.i18n import t
from app.models import File

UNAVAILABLE = t("fa", "cl_scan_unavailable")
INFECTED_PREFIX = t("fa", "cl_scan_infected", name="").rstrip()
CLEAN = t("fa", "cl_scan_clean")


def _install(monkeypatch, reply=None, raises: Exception | None = None):
    class ClamdNetworkSocket:
        def __init__(self, host=None, port=None, timeout=None):
            pass

        def instream(self, fh):
            fh.read()
            if raises is not None:
                raise raises
            return reply

    monkeypatch.setitem(sys.modules, "clamd",
                        types.SimpleNamespace(ClamdNetworkSocket=ClamdNetworkSocket))


async def _scan_label(tmp_path) -> str:
    p = tmp_path / "doc.bin"
    p.write_bytes(b"hello")
    f = File(ref="r", owner_id=1, file_unique_id="u", file_id="F", kind="document",
             name="doc.bin")
    res = await T._do_op(None, "scan", {}, f, str(p), str(tmp_path), "fa")
    assert res.get("note_only")
    return res["label"]


@pytest.mark.parametrize("reply", [
    {"stream": ("ERROR", "Can't allocate memory")},
    {"stream": ("ERROR", None)},
    {},
    None,                                   # پاسخِ خالیِ clamd
], ids=["clamd_error", "bare_error", "empty_dict", "empty_reply"])
async def test_a_clamd_failure_is_not_reported_as_infected(tmp_path, monkeypatch, reply):
    _install(monkeypatch, reply)
    label = await _scan_label(tmp_path)
    assert label.startswith(UNAVAILABLE), label
    assert INFECTED_PREFIX not in label, f"خطای اسکنر «آلوده» گزارش شد: {label}"


async def test_the_clamd_reason_reaches_the_note(tmp_path, monkeypatch):
    _install(monkeypatch, {"stream": ("ERROR", "Can't allocate memory")})
    assert "Can't allocate memory" in await _scan_label(tmp_path)


async def test_a_real_detection_is_still_infected(tmp_path, monkeypatch):
    """کنترل: رفع نباید یافتهٔ واقعی را خاموش کند."""
    _install(monkeypatch, {"stream": ("FOUND", "Eicar-Test-Signature")})
    label = await _scan_label(tmp_path)
    assert label.startswith(INFECTED_PREFIX) and "Eicar-Test-Signature" in label


async def test_a_clean_file_is_clean(tmp_path, monkeypatch):
    _install(monkeypatch, {"stream": ("OK", None)})
    assert await _scan_label(tmp_path) == CLEAN


async def test_a_connection_error_is_unavailable(tmp_path, monkeypatch):
    """کنترل: مسیرِ اتصال از قبل درست بود و باید بماند."""
    _install(monkeypatch, raises=ConnectionError("Error connecting to clamav:3310"))
    assert (await _scan_label(tmp_path)).startswith(UNAVAILABLE)
