"""هر صفحهٔ پنل با داده رندر می‌شود، در هر دو زبان، و هیچ کلیدِ متنی جا نمی‌ماند.

`pt()` برای کلیدِ ناشناخته **خودِ کلید** را برمی‌گرداند (عمدی: جاافتادگی دیده
شود نه بی‌صدا فارسی). پس جاافتادنِ یک ردیف خطا نمی‌دهد؛ فقط `ck.mirror.gap`
روی صفحه چاپ می‌شود. این تست همان را در متنِ **دیدنیِ** هر صفحه می‌گردد.
"""
from __future__ import annotations

import re

import pytest
from pagefacts import page_text

from app.panel_i18n import STRINGS

#: هر صفحهٔ GET، به‌علاوهٔ حالت‌هایی که شاخهٔ دیگری از قالب را رندر می‌کنند
#: (دیالوگِ بازِ سرورساید، فیلتر، جست‌وجو، برگه‌ها).
PAGES = (
    "/", "/?r=7d", "/?r=30d", "/?r=90d",
    "/activity", "/activity?tab=ops", "/activity?tab=log", "/activity?tab=dl&st=failed",
    "/reports", "/reports?r=24h", "/reports?r=all",
    "/users", "/users?st=blocked", "/users?q=901&sort=files",
    "/cookies", "/cookies?dlg=ck-add",
    "/nodes", "/nodes?dlg=nd-add",
    "/system",
    "/texts", "/texts?edited=1", "/texts?q=zzzz-nothing",
    "/buttons", "/buttons?kind=audio",
    "/langs", "/langs?dlg=lng-import",
    "/settings", "/settings?q=proxy", "/settings?q=zzzz-nothing",
    "/search?q=se", "/search?q=x", "/search",
    # برگه‌های کشویی، هم صفحهٔ کامل (بی‌JS) هم فرگمنت (با JS). شناسه‌ها از ترتیبِ
    # درجِ `seeded` می‌آیند: کاربرِ ۱ = ۹۰۱ · دانلودِ ۱ موفق، ۵ ناموفق، ۷ از کش،
    # ۸ ردشده · جابِ ۲ ناموفق، ۳ در صف.
    "/users?open=1", "/users?open=2&frag=1",
    "/activity?dl=1", "/activity?dl=5", "/activity?dl=7&frag=1", "/activity?dl=8&frag=1",
    "/activity?tab=ops&job=2", "/activity?job=3&frag=1",
)

#: خودِ برگه — نه `class="sheet-host"`ِ پوسته که روی **هر** صفحه هست (پیشوندِ
#: مشترک یک‌بار همین ادعا را بی‌قیدوشرط صادق کرده بود).
_SHEET = '<aside class="sheet" role="dialog"'

_PREFIXES = sorted({k.split(".")[0] for k in STRINGS}, key=len, reverse=True)
_KEYLIKE = re.compile(r"(?<![\w.])(?:" + "|".join(map(re.escape, _PREFIXES))
                      + r")\.[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*(?![\w.])")


def leaked_keys(html: str) -> list[str]:
    """کلیدهای متنی‌ای که خام روی صفحه آمده‌اند (یعنی ردیفشان نیست)."""
    return sorted({m for m in _KEYLIKE.findall(page_text(html)) if m not in STRINGS})


def test_leak_detector_sees_a_raw_key():
    # کنترلِ منفی: آشکارساز باید کلیدِ جاافتاده را ببیند و متنِ عادی را نه.
    assert leaked_keys("<p>ck.no_such_key</p>") == ["ck.no_such_key"]
    assert leaked_keys("<p>youtube.com · 1.2 GB · v2026.8.19</p>") == []
    assert leaked_keys('<style>.ck.mirror{}</style><p data-x="ck.bad">ok</p>') == []


@pytest.mark.parametrize("lang", ["fa", "en"])
@pytest.mark.parametrize("path", PAGES, ids=[p.replace("/", "_").replace("?", "-").replace("=", "-")
                                             .replace("&", "-") or "root" for p in PAGES])
async def test_page_renders(seeded, path, lang):
    cookies = {**seeded.cookies, "tab_lang": lang}
    r = await seeded.client.get(path, cookies=cookies, allow_redirects=False)
    body = await r.text()
    assert r.status == 200, (path, r.status, body[:600])
    assert r.content_type == "text/html"
    if "frag=1" in path:        # فرگمنت پوسته ندارد، فقط خودِ برگه
        assert "<html" not in body and _SHEET in body, path
    else:
        assert f'<html lang="{lang}"' in body
    if "open=" in path or "dl=" in path or "job=" in path:
        assert _SHEET in body, f"{path} برگه را رندر نکرد"
    assert leaked_keys(body) == [], (path, lang)


@pytest.mark.parametrize("path", ["/users?open=99999&frag=1", "/activity?dl=99999&frag=1",
                                  "/activity?job=99999&frag=1"])
async def test_a_missing_sheet_fragment_is_a_404(seeded, path):
    """فرگمنتِ ناموجود ۴۰۴ است، نه صفحهٔ خالیِ ۲۰۰ که JS آن را برگه بپندارد."""
    r = await seeded.client.get(path, cookies=seeded.cookies, allow_redirects=False)
    assert r.status == 404


@pytest.mark.parametrize("lang", ["fa", "en"])
async def test_login_renders_signed_out(panel, lang):
    r = await panel.client.get("/login", cookies={"tab_lang": lang})
    body = await r.text()
    assert r.status == 200
    assert 'action="/auth/request"' in body
    assert leaked_keys(body) == []


@pytest.mark.parametrize("path", ["/users", "/activity", "/activity?tab=ops"])
async def test_the_sheet_marker_is_absent_without_a_sheet(seeded, path):
    """کنترلِ منفیِ `_SHEET`: بدونِ `open`/`dl`/`job` برگه‌ای نیست — وگرنه ادعای بالا تهی است."""
    r = await seeded.client.get(path, cookies=seeded.cookies)
    assert _SHEET not in await r.text()
