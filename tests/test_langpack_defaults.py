"""فاز ۴ / موردِ ۱۵ — import مقدارِ برابر با پیش‌فرض را override نکند.

`review` هر کلیدِ معتبری را در `entries` می‌گذاشت و پنل همه را می‌نوشت. پس یک
رفت‌وبرگشتِ ساده — export و بعد import بدونِ هیچ تغییری — ۲۱۴ ردیفِ
`text_overrides` می‌ساخت که مقدارشان دقیقاً پیش‌فرض بود. نتیجه بی‌صدا و دائمی
است: override برنده است، پس هر اصلاحِ بعدیِ `locales/*.py` دیگر به کاربر
نمی‌رسید.

منطقِ خالص این‌جا (سوییتِ اصلی)؛ اتصالش در پنل در `tests/panel/test_langs_defaults.py`.
"""
from __future__ import annotations

import json

import pytest

from app import langpack as L
from app import textstore
from app.i18n import DEFAULT, default_text


@pytest.fixture(autouse=True)
def clean_overrides(monkeypatch):
    monkeypatch.setattr(textstore, "_overrides", {})


def _pack(lang: str, texts: dict[str, str]) -> dict:
    return json.loads(L.build_pack(lang=lang, name=lang, source=DEFAULT, texts=texts))


def _review(lang: str, pack: dict) -> L.Review:
    return L.review(pack,
                    source_texts=L.effective_texts(DEFAULT, {}),
                    current=L.effective_texts(lang, {}),
                    defaults=L.effective_texts(lang, {}))


def test_an_unchanged_round_trip_overrides_nothing():
    rv = _review(DEFAULT, _pack(DEFAULT, L.effective_texts(DEFAULT, {})))
    assert rv.ok
    assert rv.overrides == {}, f"{len(rv.overrides)} کلید پیش‌فرض را منجمد می‌کردند"
    assert sorted(rv.defaulted) == sorted(L.TEXT_KEYS)


def test_only_the_edited_keys_are_overrides():
    texts = L.effective_texts(DEFAULT, {})
    k1, k2 = L.TEXT_KEYS[0], L.TEXT_KEYS[1]
    texts[k1] = "EDITED " + texts[k1]
    rv = _review(DEFAULT, _pack(DEFAULT, texts))
    assert set(rv.overrides) == {k1}
    assert k2 in rv.defaulted


def test_an_added_language_does_not_store_its_english_fallback():
    """برای زبانِ افزوده پیش‌فرض همان انگلیسی است (زنجیرهٔ fallback)."""
    key = L.TEXT_KEYS[0]
    texts = {k: "ES " + v for k, v in L.effective_texts(DEFAULT, {}).items()}
    texts[key] = default_text("es", key)                    # ترجمه‌نشده، به انگلیسی
    rv = _review("es", _pack("es", texts))
    assert key not in rv.overrides
    assert len(rv.overrides) == len(L.TEXT_KEYS) - 1


def test_without_defaults_review_keeps_its_old_contract():
    """کنترل: فراخوانِ بی‌`defaults` همهٔ ورودی‌ها را override می‌داند (سازگاری)."""
    pack = _pack(DEFAULT, L.effective_texts(DEFAULT, {}))
    rv = L.review(pack, source_texts=L.effective_texts(DEFAULT, {}),
                  current=L.effective_texts(DEFAULT, {}))
    assert len(rv.overrides) == len(L.TEXT_KEYS)
