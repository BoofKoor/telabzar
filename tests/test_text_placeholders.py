"""فاز ۴ / موردِ ۳۲ — placeholderِ متن فقط `{نام}`؛ نه صفت، نه اندیس، نه format-spec.

`validate` فقط نامِ ریشه را با پیش‌فرض مقایسه می‌کرد (`n.__class__` → `n`)، پس:

* `{name.__class__}` پذیرفته و به کاربر `<class 'str'>` نشان داده می‌شد؛
* `{size[0]}` روی عدد `TypeError` می‌داد و `t()` فقط `KeyError/IndexError/
  ValueError` را می‌گرفت → خودِ هندلر می‌ترکید؛
* `{name:>200000000}` هر بار ۲۰۰ مگابایت می‌ساخت، روی پیامی که به هر کاربر می‌رسد.

ورودیِ واقعیِ این‌ها پنلِ `/texts` و — مهم‌تر — **بستهٔ زبانِ import‌شده** است، یعنی
خروجیِ یک مترجمِ ماشینی. دو لایه، هرکدام جدا سنجیده می‌شود (§۶): ردِ هنگامِ نوشتن
(`validate`، و از آن‌جا `langpack.review`) و ردِ هنگامِ رندر برای override‌های
**ازپیش‌ذخیره‌شده** (`i18n._fmt`).
"""
from __future__ import annotations

import json
import time

import pytest

from app import langpack as L
from app import textstore
from app.i18n import DEFAULT, default_text, t

KEY = "detected_document"          # پیش‌فرض: … <code>{name}</code> · {size} …
DEFAULT_FA = default_text("fa", KEY)

UNSAFE = {
    "attr": "سند {name.__class__} · {size}",
    "index": "سند {name} · {size[0]}",
    "spec_width": "سند {name:>200000000} · {size}",
    "conversion": "سند {name!r} · {size}",
    "positional": "سند {} · {size}",
    "nested_spec": "سند {name:{size}} · {size}",
}


@pytest.fixture(autouse=True)
def clean_overrides(monkeypatch):
    monkeypatch.setattr(textstore, "_overrides", {})


@pytest.mark.parametrize("key", sorted(UNSAFE), ids=sorted(UNSAFE))
def test_validate_rejects_anything_but_a_bare_name(key):
    assert textstore.validate(DEFAULT_FA, UNSAFE[key]), f"{UNSAFE[key]!r} پذیرفته شد"


def test_validate_still_accepts_a_normal_edit():
    """کنترل."""
    assert textstore.validate(DEFAULT_FA, "📄 سند: {name} ({size})") is None


@pytest.mark.parametrize("key", sorted(UNSAFE), ids=sorted(UNSAFE))
def test_a_stored_unsafe_override_falls_back_to_the_default(key):
    """override‌ای که پیش از رفع نوشته شده: رندر نه می‌ترکد، نه نشت می‌دهد، نه منفجر می‌شود."""
    textstore._overrides[("fa", KEY)] = UNSAFE[key]
    t0 = time.monotonic()
    out = t("fa", KEY, name="a.pdf", size=1234)
    assert time.monotonic() - t0 < 1
    assert out == DEFAULT_FA.format(name="a.pdf", size=1234)
    assert "class" not in out and len(out) < 1000


def test_a_valid_override_still_renders():
    """کنترل: لایهٔ رندر نباید override‌های درست را هم دور بریزد."""
    textstore._overrides[("fa", KEY)] = "📄 {name} — {size}"
    assert t("fa", KEY, name="a.pdf", size=1234) == "📄 a.pdf — 1234"


def test_a_language_pack_with_a_format_spec_is_rejected_per_key():
    src = L.effective_texts(DEFAULT, {})
    texts = dict(src)
    texts[KEY] = "DOC {name:>200000000} {size}"
    pack = json.loads(L.build_pack(lang="es", name="es", source=DEFAULT, texts=texts))
    rv = L.review(pack, source_texts=src, current=L.effective_texts("es", {}))
    assert KEY in dict(rv.errors), "بستهٔ زبان با format-spec از import رد نشد"
