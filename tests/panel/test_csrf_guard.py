"""فاز ۲ِ ممیزی — POSTِ میان‌سایتی به پنل رد شود.

تنها دفاعِ قبلی `SameSite=Lax`ِ کوکیِ نشست بود. Lax مرزش **site** است نه
**origin**: گیت‌وی (`DOMAIN:8443`) و پنل (`DOMAIN:2083`) یک هاست‌اند، پس از دیدِ
مرورگر هم‌سایت‌اند و کوکی همراهِ هر POSTی که از صفحه‌ای روی گیت‌وی بیاید
فرستاده می‌شد. `Sec-Fetch-Site` همین تفاوت را می‌بیند (`same-site` در برابرِ
`same-origin`) و `Origin` هم پورت را دارد.

ادعاها روی **اثر**اند نه کدِ وضعیت: «۴۰۳ برگشت» با «کاربر بلاک نشد» یکی نیست،
و درسِ `test_console_forms` همین بود — ۳۰۲ چیزی دربارهٔ کنش نمی‌گوید.
"""
from __future__ import annotations

import pytest

from app.models import User


async def _victim(panel) -> int:
    async with panel.aw.Sessionmaker() as s:
        u = User(tg_user_id=777, role="user")
        s.add(u)
        await s.commit()
        return u.id


async def _block(panel, uid: int, headers: dict):
    return await panel.client.post("/users/block", cookies=panel.cookies,
                                   data={"id": str(uid), "action": "block"},
                                   headers=headers, allow_redirects=False)


async def _is_blocked(panel, uid: int) -> bool:
    async with panel.aw.Sessionmaker() as s:
        return bool((await s.get(User, uid)).is_blocked)


@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "same-site"},                 # صفحه‌ای روی گیت‌وی، همان هاست
    {"Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://evil.example"},
    {"Origin": "null"},                              # iframeِ sandbox / data:
], ids=["same-site", "cross-site", "foreign-origin", "null-origin"])
async def test_a_cross_site_post_does_not_act(panel, headers):
    uid = await _victim(panel)
    r = await _block(panel, uid, headers)
    assert r.status == 403
    assert not await _is_blocked(panel, uid), "درخواستِ میان‌سایتی کاربر را بلاک کرد"


async def test_the_gateway_port_is_another_origin(panel):
    """همان هاست با پورتِ دیگر (گیت‌وی) — دقیقاً حالتی که Lax نمی‌گرفت."""
    uid = await _victim(panel)
    host = panel.client.server.host
    r = await _block(panel, uid, {"Origin": f"https://{host}:8443"})
    assert r.status == 403
    assert not await _is_blocked(panel, uid)


@pytest.mark.parametrize("kind", ["sec-fetch", "origin", "no-headers"])
async def test_a_same_origin_post_still_works(panel, kind):
    """کنترل: فرمِ خودِ پنل، و کلاینتِ غیرمرورگری (بی‌هدر)، همچنان کار می‌کنند."""
    uid = await _victim(panel)
    netloc = f"{panel.client.server.host}:{panel.client.server.port}"
    headers = {"sec-fetch": {"Sec-Fetch-Site": "same-origin"},
               "origin": {"Origin": f"http://{netloc}"},
               "no-headers": {}}[kind]
    r = await _block(panel, uid, headers)
    assert r.status == 302
    assert await _is_blocked(panel, uid)


async def test_the_public_admin_base_is_accepted_behind_a_proxy(panel, monkeypatch):
    """پشتِ پروکسیِ معکوس `Host` داخلی است و `Origin` دامنهٔ عمومی."""
    monkeypatch.setattr(panel.aw.settings, "admin_base", "https://panel.example.com:2083")
    uid = await _victim(panel)
    r = await _block(panel, uid, {"Origin": "https://panel.example.com:2083"})
    assert r.status == 302
    assert await _is_blocked(panel, uid)


async def test_the_node_installer_is_exempt(panel):
    """`/node/join` را نصب‌کننده با curl صدا می‌زند؛ گارد نباید جلویش بایستد."""
    r = await panel.client.post("/node/join", json={"token": "x", "pubkey": "y"},
                                headers={"Origin": "https://evil.example"})
    assert r.status != 403


async def test_the_refusal_carries_the_hardening_headers(panel):
    uid = await _victim(panel)
    r = await _block(panel, uid, {"Sec-Fetch-Site": "cross-site"})
    assert r.headers.get("X-Frame-Options") == "DENY"
