"""پیلِ وضعیتِ اکانت در `/cookies` باید **دیده شود**، و شدتش درست باشد.

گاردِ کشف‌محورِ همسایه (`test_panel_css_classes`) می‌گوید «هر کلاس قاعده دارد».
این فایل ادعای مشخص‌ترِ محصولی را می‌سنجد: قاعده‌ای که به پیلِ «باطل» و «فریز»
می‌رسد واقعاً **رنگ** می‌دهد و آن رنگ با «سالم» یکی نیست — می‌شود کلاس تعریف
شده باشد و صرفاً `display:inline` بگیرد.

پیشینه: پنلِ قدیم بجِ «باطل» و «فریز» را بی‌رنگ (`rgba(0,0,0,0)`) رندر می‌کرد در
حالی که «سالم» سبزِ پررنگ بود — سلسله‌مراتبِ بصریِ وارونه، دقیقاً روی دو وضعیتی که
دخالتِ انسان می‌خواهند. از بازطراحیِ ۲۰۲۶-۱۰ وضعیت یک «پیل» است
(`<span class="pill <شدت>">`) و رنگش از توکن‌های `panel.css` می‌آید.
"""
from __future__ import annotations

import re

from test_panel_css_classes import _fetch, stylesheet


def _rule_for(html: str, cls: str) -> str:
    """بدنهٔ قاعدهٔ `.pill.<cls>{…}` از استایل‌شیتِ پیوندشدهٔ همان پاسخ."""
    hits = re.findall(r"\.pill\." + re.escape(cls) + r"\s*\{([^}]*)\}", stylesheet(html))
    return hits[-1] if hits else ""      # آخری برنده است، مثلِ خودِ مرورگر


def _pill_class(html: str, label: str) -> str:
    """شدتِ پیلی که متنِ `label` را حمل می‌کند — در **مارک‌آپ**، نه در CSS."""
    # آیکون دقیقاً **یک** `<svg>` است: `.*?` با `re.S` می‌توانست تا `</svg>`ِ پیلِ
    # بعدی کش بیاید و شدتِ پیلِ اشتباه را برگرداند (نسخهٔ اول دقیقاً همین را کرد).
    m = re.search(r'class="pill ([\w-]+)">(?:<svg[^>]*>(?:(?!</svg>).)*</svg>)?\s*'
                  + re.escape(label) + r"\s*</span>", html, re.S)
    assert m, f"پیلِ «{label}» در صفحه پیدا نشد"
    return m.group(1)


def _label(status: str) -> str:
    from app.panel_i18n import pt
    return pt("fa", f"ck.{status}")


async def test_the_invalid_pill_is_actually_painted(seeded):
    html = await _fetch(seeded, "/cookies")
    rule = _rule_for(html, _pill_class(html, _label("invalid")))
    assert "background" in rule and "color" in rule, f"پیلِ «باطل» رنگ نمی‌دهد: {rule!r}"


async def test_the_frozen_pill_is_actually_painted(seeded):
    """چک‌پوینت هم‌ردهٔ باطل است — هر دو دخالتِ انسان می‌خواهند."""
    html = await _fetch(seeded, "/cookies")
    rule = _rule_for(html, _pill_class(html, _label("frozen")))
    assert "background" in rule and "color" in rule


async def test_the_two_states_that_need_a_human_do_not_look_healthy(seeded):
    """ادعای واقعی «رنگ دارد» نیست، «رنگش با سالم فرق دارد» است."""
    html = await _fetch(seeded, "/cookies")
    ok = _pill_class(html, _label("healthy"))
    for status in ("invalid", "frozen"):
        cls = _pill_class(html, _label(status))
        assert cls != ok and _rule_for(html, cls) != _rule_for(html, ok), \
            f"پیلِ «{_label(status)}» عیناً مثلِ «سالم» رندر می‌شود"


async def test_the_healthy_pill_stays_green(seeded):
    """کنترلِ معکوس: رنگِ «سالم» از توکنِ وضعیتِ سالم می‌آید، نه hexِ دستی."""
    html = await _fetch(seeded, "/cookies")
    assert _pill_class(html, _label("healthy")) == "good"
    assert "var(--good" in _rule_for(html, "good")


async def test_a_deliberately_disabled_account_is_grey(seeded):
    """«ادمین خودش خاموشش کرد» باید خنثی بماند — نه قرمز، نه نامرئی."""
    html = await _fetch(seeded, "/cookies")
    assert _pill_class(html, _label("disabled")) == "neutral"
    assert "background" in _rule_for(html, "neutral")


async def test_an_unknown_status_does_not_look_like_a_deliberate_one(panel, monkeypatch):
    """شاخهٔ **پیش‌فرضِ** `Fmt.ck_pill`.

    وضعیتِ ناشناخته کاشتنی نیست (از روی متا محاسبه می‌شود)، پس `status_of`
    وصله می‌خورد. دو ادعا: پیل **رنگ** بگیرد، و آن رنگ همان خاکستریِ «غیرفعال»
    نباشد — وگرنه «نمی‌دانم این چیست» و «ادمین عمداً خاموشش کرد» یک شکل‌اند.
    """
    from app import cookies as ck

    async def _unknown(*_a, **_kw):
        return "some_status_from_the_future"

    monkeypatch.setattr(ck, "status_of", _unknown)
    await _seed_one(panel)
    html = await _fetch(panel, "/cookies")

    cls = _pill_class(html, "some_status_from_the_future")
    rule = _rule_for(html, cls)
    assert "background" in rule and "color" in rule
    assert cls != "neutral" and rule != _rule_for(html, "neutral"), (
        "وضعیتِ ناشناخته عیناً مثلِ «غیرفعال» رندر می‌شود — دو معنیِ متفاوت، یک ظاهر")


async def test_every_seeded_status_paints_a_pill_on_a_real_row(seeded):
    """کشف‌محور: هر وضعیتی که کاشته شده باید پیلِ رنگیِ خودش را روی ردیف بگذارد.

    وضعیتِ هشتمی که فردا اضافه شود هم گرفته می‌شود، بدونِ یک خط تغییر در این فایل.
    """
    from app import cookies as ck

    html = await _fetch(seeded, "/cookies")
    # همان منبعی که خودِ هندلر می‌خواند، نه یک بازسازیِ دست‌نویس از وضعیت‌ها.
    accs = await ck.accounts(seeded.redis)
    assert len(accs) >= 7, f"پیش‌شرط: هر هفت وضعیت کاشته شده باشد، {len(accs)} بود"
    for status in {a["status"] for a in accs}:
        cls = _pill_class(html, _label(status))
        assert "background" in _rule_for(html, cls), f"«{status}» → «{cls}» رنگ نمی‌دهد"


async def _seed_one(panel):
    """یک اکانتِ تنها — کافی است، چون ادعا دربارهٔ شاخهٔ رندر است نه استخر."""
    import os
    import time

    from app import cookies as ck

    name = "cookies_future.txt"
    with open(os.path.join(panel.aw.settings.cookies_dir, name), "w", encoding="utf-8") as fh:
        fh.write("# Netscape HTTP Cookie File\n")
    await ck.set_meta(panel.redis, name, {"platform": "instagram", "label": "future",
                                          "added": int(time.time()), "last_ok": 0,
                                          "fail_streak": 0})
