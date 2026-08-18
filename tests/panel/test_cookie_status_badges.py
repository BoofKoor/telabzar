"""بجِ وضعیتِ اکانت در `/cookies` باید **دیده شود**، و شدتش درست باشد.

گاردِ کشف‌محورِ همسایه (`test_panel_css_classes`) می‌گوید «هر کلاس قاعده دارد».
این فایل ادعای مشخص‌ترِ محصولی را می‌سنجد: قاعده‌ای که به بجِ «باطل» و
«چک‌پوینت» می‌رسد واقعاً **رنگ** می‌دهد و آن رنگ با «سالم» یکی نیست. دوتا
ادعای متفاوت‌اند — می‌شود کلاس تعریف شده باشد و صرفاً `display:inline` بگیرد.

اندازه‌گیریِ پیش از رفع (Chromium روی همان صفحه): بجِ «باطل» و «فریز»
`rgba(0,0,0,0)` می‌گرفتند در حالی که «سالم» سبزِ پررنگ بود — سلسله‌مراتبِ بصریِ
وارونه. **تصحیحِ صورتِ مسئله:** «ادمین کوکیِ مرده را نمی‌بیند» اغراق بود؛
نقطهٔ ۹پیکسلیِ `.s-invalid` قرمز است و کار می‌کرد. چیزی که نامرئی بود *متنِ*
برچسب بود، و `test_the_status_dot_stayed_red` همان تفکیک را نگه می‌دارد.
"""
from __future__ import annotations

import re

from test_panel_css_classes import _fetch, classes_defined


def _rule_for(html: str, cls: str) -> str:
    """بدنهٔ قاعدهٔ `.<cls>{…}` از `<style>`های همان پاسخ — رشتهٔ خالی اگر نبود."""
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))
    hits = re.findall(r"\." + re.escape(cls) + r"\s*\{([^}]*)\}", css)
    return hits[-1] if hits else ""      # آخری برنده است، مثلِ خودِ مرورگر


def _badge_class(html: str, label: str) -> str:
    """کلاسِ بجی که متنِ `label` را حمل می‌کند."""
    m = re.search(r'class="badge ([\w-]*)"[^>]*>\s*' + re.escape(label), html)
    assert m, f"بجِ «{label}» در صفحه پیدا نشد"
    return m.group(1)


async def test_the_invalid_badge_is_actually_painted(seeded):
    html = await _fetch(seeded, "/cookies")
    rule = _rule_for(html, _badge_class(html, "باطل"))
    assert "background" in rule and "color" in rule, (
        f"بجِ «باطل» قاعده‌ای دارد که رنگ نمی‌دهد: {rule!r}")


async def test_the_frozen_badge_is_actually_painted(seeded):
    """چک‌پوینت هم‌ردهٔ باطل است — هر دو دخالتِ انسان می‌خواهند."""
    html = await _fetch(seeded, "/cookies")
    rule = _rule_for(html, _badge_class(html, "چک‌پوینت"))
    assert "background" in rule and "color" in rule


async def test_the_two_states_that_need_a_human_do_not_look_healthy(seeded):
    """ادعای واقعی «رنگ دارد» نیست، «رنگش با سالم فرق دارد» است."""
    html = await _fetch(seeded, "/cookies")
    ok = _rule_for(html, _badge_class(html, "سالم"))
    for label in ("باطل", "چک‌پوینت"):
        bad = _rule_for(html, _badge_class(html, label))
        assert bad and bad != ok, f"بجِ «{label}» عیناً مثلِ «سالم» رندر می‌شود"


async def test_the_healthy_badge_stays_green(seeded):
    """کنترلِ معکوس: رفع نباید حالتِ سالم را عوض کند."""
    html = await _fetch(seeded, "/cookies")
    assert _badge_class(html, "سالم") == "ok"
    assert "#ecfdf5" in _rule_for(html, "ok")


async def test_a_deliberately_disabled_account_is_grey(seeded):
    """«ادمین خودش خاموشش کرد» باید خنثی بماند — نه قرمز، نه نامرئی."""
    html = await _fetch(seeded, "/cookies")
    assert _badge_class(html, "غیرفعال") == "dim"
    assert "background" in _rule_for(html, "dim")


async def test_an_unknown_status_does_not_look_like_a_deliberate_one(panel, monkeypatch):
    """شاخهٔ **پیش‌فرضِ** `_badge_of` — همان که تا امروز به `mute`ِ تعریف‌نشده می‌رفت.

    وضعیتِ ناشناخته کاشتنی نیست (از روی متا محاسبه می‌شود)، پس `status_of`
    وصله می‌خورد. و ادعا دوتاست، نه یکی: بج باید **رنگ** بگیرد، و آن رنگ نباید
    همان خاکستریِ «غیرفعال» باشد — وگرنه «نمی‌دانم این چیست» و «ادمین عمداً
    خاموشش کرد» یک شکل دیده می‌شوند، که همان ردهٔ «حالتِ ناشناخته بی‌صدا شبیهِ
    حالتِ عادی» است.
    """
    from app import cookies as ck

    async def _unknown(*_a, **_kw):
        return "some_status_from_the_future"

    monkeypatch.setattr(ck, "status_of", _unknown)
    (await _seed_one(panel))
    html = await _fetch(panel, "/cookies")

    assert "some_status_from_the_future" in html, "وضعیتِ ناشناخته اصلاً رندر نشد"
    cls = _badge_class(html, "some_status_from_the_future")
    assert cls in classes_defined(html), f"کلاسِ «{cls}» هیچ قاعده‌ای ندارد"
    rule = _rule_for(html, cls)
    assert "background" in rule and "color" in rule
    assert rule != _rule_for(html, "dim"), (
        "وضعیتِ ناشناخته عیناً مثلِ «غیرفعال» رندر می‌شود — دو معنیِ متفاوت، یک ظاهر")


async def test_the_unproven_status_dot_is_visible(seeded):
    """`.s-unproven` از روزِ اول در ردیفِ نقطه‌ها جا افتاده بود."""
    html = await _fetch(seeded, "/cookies")
    assert "s-unproven" in html
    assert "background" in _rule_for(html, "s-unproven")


async def test_the_status_dot_stayed_red(seeded):
    """کنترلِ معکوس، و تصحیحِ ثبت‌شدهٔ صورتِ مسئله.

    نقطهٔ «باطل» **قبل از رفع هم** قرمز بود؛ ادعای «کوکیِ مرده کاملاً نامرئی
    است» غلط بود و این تست نگه‌داری‌اش می‌کند.
    """
    html = await _fetch(seeded, "/cookies")
    assert "#dc2626" in _rule_for(html, "s-invalid")


async def _seed_one(panel):
    """یک اکانتِ تنها — کافی است، چون ادعا دربارهٔ شاخهٔ رندر است نه استخر."""
    import time

    from app import cookies as ck

    name = "cookies_future.txt"
    import os
    with open(os.path.join(panel.aw.settings.cookies_dir, name), "w", encoding="utf-8") as fh:
        fh.write("# Netscape HTTP Cookie File\n")
    await ck.set_meta(panel.redis, name, {"platform": "instagram", "label": "future",
                                          "added": int(time.time()), "last_ok": 0,
                                          "fail_streak": 0})
