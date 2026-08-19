"""زنجیرهٔ fallbackِ `t()` — و اینکه ۲۰۲۶-۰۸-۱۹ کدام حلقه‌اش عوض شد.

**رفتارِ پیش از این:** هر کلیدی که برای زبانِ درخواستی ترجمه نشده بود به
**فارسی** می‌افتاد (`CATALOG.get(lang, FA)`). برای دو زبانِ داخلی بی‌اثر بود —
هر دو کاتالوگِ کامل دارند و پاریتی‌شان دقیق است (اندازه‌گیری‌شده: ۲۱۴ کلید،
صفر کلیدِ یک‌طرفه). ولی از وقتی زبانِ **افزوده** ممکن شد، آن حلقه معنیِ عملی
پیدا کرد: اسپانیاییِ ۹۰٪ برای یک اسپانیایی‌زبان می‌شد «۹۰٪ اسپانیایی + ۱۰٪
فارسی» — و فارسی برای مخاطبی که خطش را نمی‌خواند از انگلیسی بی‌فایده‌تر است.

پس زنجیره حالا **کاتالوگِ خودِ زبان → `FALLBACK` (en) → `DEFAULT` (fa) → خودِ
کلید** است. این فایل هر چهار حلقه را جدا پین می‌کند، چون هیچ‌کدام از بیرون
دیدنی نیست: عوض‌شدنشان نه خطا می‌دهد نه تست را می‌شکند، فقط زبانِ خروجی را
بی‌صدا عوض می‌کند.
"""
from __future__ import annotations

import pytest

from app import textstore
from app.i18n import CATALOG, DEFAULT, FALLBACK, default_text, t
from app.locales.en import MESSAGES as EN
from app.locales.fa import MESSAGES as FA


@pytest.fixture(autouse=True)
def clean_overrides(monkeypatch):
    """`_overrides` سطحِ ماژول است و بینِ تست‌ها زنده می‌ماند."""
    monkeypatch.setattr(textstore, "_overrides", {})


def test_an_untranslated_key_falls_back_to_english_not_persian():
    """قلبِ تغییر: زبانی که این کلید را ندارد، **انگلیسی** می‌گیرد نه فارسی."""
    textstore._overrides[("es", "welcome")] = "¡Hola!"
    assert t("es", "welcome") == "¡Hola!"          # ترجمه‌شده
    assert t("es", "btn_convert") == EN["btn_convert"]  # ترجمه‌نشده → انگلیسی
    assert t("es", "btn_convert") != FA["btn_convert"]


def test_the_two_builtin_languages_still_answer_from_their_own_catalog():
    """کنترل: تغییرِ fallback نباید هیچ‌کدام از دو زبانِ داخلی را تکان دهد."""
    for key in ("btn_convert", "welcome", "limit_quota"):
        assert t("fa", key) == FA[key]
        assert t("en", key) == EN[key]


def test_no_language_falls_back_to_the_raw_key_while_the_catalog_is_complete():
    """حلقهٔ آخر (`or key`) فقط برای کلیدِ ناموجود است، نه برای زبانِ ناشناخته."""
    assert default_text("es", "nope_not_a_key") == "nope_not_a_key"
    assert default_text("es", "welcome") == EN["welcome"]


def test_the_default_language_is_the_last_resort_before_the_key():
    """اگر روزی کلیدی فقط در فارسی باشد، به آن می‌افتد نه به نامِ کلید.

    امروز غیرقابلِ‌دسترس است (پاریتی دقیق است)، پس با یک کاتالوگِ **ناقص‌شده**
    سنجیده می‌شود — وگرنه این حلقه یک شاخهٔ تست‌نشده می‌ماند.
    """
    key = "welcome"
    trimmed = {k: v for k, v in EN.items() if k != key}
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(CATALOG, FALLBACK, trimmed)
        assert default_text("es", key) == FA[key]


def test_lang_none_uses_the_default_language():
    assert t(None, "btn_convert") == FA["btn_convert"]
    assert DEFAULT == "fa" and FALLBACK == "en"


def test_a_broken_override_falls_back_to_the_same_chain():
    """override با placeholderِ غلط → پیش‌فرضِ **همان زنجیره** (انگلیسی برای es)."""
    import string

    fmt = string.Formatter()
    def fields(s):
        return {f.split(".")[0].split("[")[0] for _l, f, _s, _c in fmt.parse(s) if f}

    key = next(k for k, v in FA.items() if fields(v) == {"mb"})
    textstore._overrides[("es", key)] = "Demasiado grande: {tamano} MB"
    assert t("es", key, mb=100) == EN[key].format(mb=100)


def test_the_panel_and_the_bot_share_one_fallback_chain():
    """`admin_web._text_default` باید همان `i18n.default_text` باشد، نه کپیِ دوم.

    دو کپیِ دست‌نویسِ یک قاعده واگرا می‌شوند و هیچ‌کدام دیگری را خبر نمی‌کند —
    این‌جا واگرایی یعنی صفحهٔ `/texts` «پیش‌فرض» را فارسی نشان دهد در حالی که
    ربات انگلیسی می‌فرستد. AST خوانده می‌شود نه import، چون `admin_web` روی
    رانرِ اصلی نصب نیست.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "app" / "admin_web.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_text_default")
    calls = {n.func.id for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "default_text" in calls, (
        "`_text_default` دیگر به `i18n.default_text` واگذار نمی‌کند — "
        "یعنی زنجیرهٔ fallback دو پیاده‌سازی دارد.")
