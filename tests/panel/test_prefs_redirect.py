"""فاز ۴ / موردِ ۲۸ — ریدایرکتِ باز در `/prefs` (بدونِ لاگین).

`_safe_back` سه شرط داشت (با `/` شروع شود، `//` نباشد، `\\` نداشته باشد) و هر سه
روی رشتهٔ **decodeشده** درست بودند — ولی مرورگر پیش از تفسیرِ URL، tab و خطِ
جدید را از وسطش حذف می‌کند (WHATWG URL، گامِ «remove all ASCII tab or newline»).
پس `to=/%09/evil.example` به `Location: /\\t/evil.example` می‌رسید و مرورگر آن را
`//evil.example` می‌خواند. و `/prefs` عمداً پشتِ لاگین نیست (صفحهٔ ورود هم سوییچِ
زبان دارد)، پس هر کسی می‌توانست لینکی روی دامنهٔ پنل بسازد که بیرون می‌برد.

ادعا روی **مقصدِ نهایی** است، نه روی رشتهٔ هدر: `_browser_target` همان دو گامِ
WHATWG را روی `Location` اجرا می‌کند و بعد نسبت به مبدأ resolve می‌کند.
"""
from __future__ import annotations

from urllib.parse import quote, urljoin, urlsplit

import pytest

BASE = "https://panel.example/"


def _browser_target(location: str) -> str:
    """مقصدی که مرورگر واقعاً به آن می‌رود (دو گامِ اولِ پارسرِ WHATWG + resolve)."""
    loc = location.strip("".join(chr(c) for c in range(0x21)))
    loc = "".join(c for c in loc if c not in "\t\n\r")
    return urljoin(BASE, loc)


async def _prefs(panel, to: str):
    r = await panel.client.get(f"/prefs?lang=en&to={quote(to, safe='')}",
                               allow_redirects=False)
    assert r.status == 302
    return r.headers["Location"]


@pytest.mark.parametrize("to", [
    "/\t/evil.example", "/\n/evil.example", "/\r/evil.example",
    "\t//evil.example", "/ /evil.example", "/\x00/evil.example",
], ids=["tab", "newline", "cr", "leading_tab", "space", "nul"])
async def test_a_control_character_cannot_smuggle_a_foreign_host(panel, to):
    loc = await _prefs(panel, to)
    assert urlsplit(_browser_target(loc)).netloc == "panel.example", \
        f"Location {loc!r} مرورگر را بیرون می‌برد"


@pytest.mark.parametrize("to", ["//evil.example", "/\\evil.example", "https://evil.example"],
                         ids=["proto_relative", "backslash", "absolute"])
async def test_the_old_guards_still_hold(panel, to):
    """کنترل: سه شرطِ قبلی سرِ جایشان‌اند."""
    assert urlsplit(_browser_target(await _prefs(panel, to))).netloc == "panel.example"


async def test_a_normal_back_path_is_kept(panel):
    """کنترل: رفع نباید بازگشتِ عادی به همان صفحه را بکشد."""
    assert await _prefs(panel, "/texts") == "/texts"
