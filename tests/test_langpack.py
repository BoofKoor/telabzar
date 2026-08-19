"""بستهٔ زبان — منطقِ خالصِ export/import.

عمداً در سوییتِ **اصلی** است، نه `tests/panel`: `langpack` هیچ وابستگیِ پنلی
ندارد، و قاعده‌ای که فقط در jobِ پنل تست شود نصفِ CI را بی‌پوشش می‌گذارد.
"""
from __future__ import annotations

import json
import string

import pytest

from app import langpack as L
from app import textstore
from app.i18n import CATALOG

_FMT = string.Formatter()


def _fields(s: str) -> set[str]:
    return {f.split(".")[0].split("[")[0] for _l, f, _s, _c in _FMT.parse(s) if f}


@pytest.fixture(autouse=True)
def clean_overrides(monkeypatch):
    monkeypatch.setattr(textstore, "_overrides", {})


def _src() -> dict[str, str]:
    return L.effective_texts("fa", {})


def _pack(**over) -> dict:
    src = _src()
    body = json.loads(L.build_pack(lang="es", name="Español", source="fa", texts=src))
    body["texts"].update(over)
    return body


def _review(pack: dict, current: dict | None = None) -> L.Review:
    return L.review(pack, source_texts=_src(), current=current or {})


# ── کدِ زبان: فرمت، نه طول ─────────────────────────────────────
@pytest.mark.parametrize("raw,want", [
    ("es", "es"), ("ES", "es"), ("de", "de"),
    ("pt-br", "pt-BR"), ("PT-BR", "pt-BR"),
    ("zh-hant-tw", "zh-Hant-TW"), ("sr-Latn-RS", "sr-Latn-RS"),
], ids=["es", "ES-upper", "de", "pt-br", "PT-BR-upper", "zh-hant-tw", "sr-Latn-RS"])
def test_a_real_language_tag_is_accepted_and_canonicalised(raw, want):
    """کدِ چندبخشی باید کار کند — قفل‌کردنِ دو کاراکتر یعنی مهاجرتِ بعدی."""
    assert L.normalize_code(raw) == want


@pytest.mark.parametrize("raw", ["", "  ", "x", "1a", "español", "e s", "es_MX", "-es", "es-"],
                         ids=["empty", "spaces", "one-letter", "digit", "non-ascii",
                              "inner-space", "underscore", "leading-dash", "trailing-dash"])
def test_a_malformed_language_tag_is_refused(raw):
    with pytest.raises(L.PackError):
        L.normalize_code(raw)


def test_case_only_variants_collapse_to_one_language():
    """بدونِ نرمال‌سازی، `pt-BR` و `pt-br` دو زبانِ جدا می‌شدند و ترجمه نصف می‌شد."""
    assert L.normalize_code("pt-br") == L.normalize_code("PT-br") == L.normalize_code("pt-BR")


def test_a_tag_longer_than_the_column_is_refused():
    """کرانِ طول زنده است، نه کدِ مرده: این تگ از الگو رد می‌شود ولی از ستون نه."""
    long_tag = "abc-defgh-ijklmnop"          # هر زیرتگ معتبر، جمعاً ۱۸ کاراکتر
    assert L._TAG_RE.match(long_tag), "پیش‌شرط: باید از الگو رد شود، وگرنه تست چیزِ دیگری می‌سنجد"
    assert len(long_tag) > L.MAX_CODE_LEN
    with pytest.raises(L.PackError, match=str(L.MAX_CODE_LEN)):
        L.normalize_code(long_tag)


# ── پاکت: ساخت و خواندن ───────────────────────────────────────
def test_the_pack_carries_every_text_key():
    body = json.loads(L.build_pack(lang="es", name="Español", source="fa", texts=_src()))
    assert set(body["texts"]) == set(L.TEXT_KEYS)
    assert len(L.TEXT_KEYS) == len(set(CATALOG["fa"]) | set(CATALOG["en"]))


def test_the_pack_carries_its_own_instructions():
    """دستورِ کار باید **همراهِ داده** سفر کند؛ مصرف‌کننده یک چت‌بات است."""
    body = json.loads(L.build_pack(lang="es", name="Español", source="fa", texts=_src()))
    joined = " ".join(body["readme"]).lower()
    for must in ("never change a key", "{placeholder}", "html", "complete file"):
        assert must.lower() in joined, f"readme دربارهٔ «{must}» چیزی نمی‌گوید"


@pytest.mark.parametrize("wrap", [
    "{0}", "```json\n{0}\n```", "```\n{0}\n```", "﻿{0}", "   {0}   \n\n",
], ids=["raw", "json-fence", "bare-fence", "bom", "padding"])
def test_parsing_survives_what_a_chat_reply_does_to_text(wrap):
    """مدل معمولاً داخلِ فنس می‌گذارد؛ کپی/پیست BOM و فاصله اضافه می‌کند."""
    raw = L.build_pack(lang="es", name="Español", source="fa", texts=_src())
    assert len(L.parse_pack(wrap.format(raw))["texts"]) == len(L.TEXT_KEYS)


@pytest.mark.parametrize("raw,frag", [
    ("", "چسبانده"),
    ("not json at all", "JSON"),
    ("[1,2]", "شیء"),
    ('{"texts":{"a":"b"}}', "telabzar_i18n"),
    ('{"telabzar_i18n":999,"texts":{"a":"b"}}', "نسخه"),
    ('{"telabzar_i18n":1}', "texts"),
    ('{"telabzar_i18n":1,"texts":{}}', "خالی"),
    ('{"telabzar_i18n":1,"texts":{"welcome":5}}', "غیرمتنی"),
], ids=["empty", "not-json", "array-root", "no-marker", "bad-version",
        "no-texts", "empty-texts", "non-string-value"])
def test_a_file_level_problem_says_what_is_wrong(raw, frag):
    with pytest.raises(L.PackError, match=frag):
        L.parse_pack(raw)


# ── سنجشِ ورودی ───────────────────────────────────────────────
def test_a_clean_translation_is_accepted_whole():
    rv = _review(_pack(**{k: "ES " + v for k, v in _src().items()}))
    assert rv.ok and not rv.errors
    assert len(rv.entries) == len(L.TEXT_KEYS)
    assert rv.coverage == 100 and rv.untouched == 0


def test_an_unknown_key_is_named_and_blocks_the_whole_pack():
    rv = _review(_pack(not_a_real_key="x"))
    assert not rv.ok
    assert rv.unknown == ["not_a_real_key"]
    assert any(k == "not_a_real_key" for k, _ in rv.errors)


def test_an_extra_placeholder_is_refused():
    key = next(k for k, v in _src().items() if _fields(v))
    rv = _review(_pack(**{key: "{no_such_field}"}))
    assert not rv.ok
    assert any(k == key and "ناشناخته" in why for k, why in rv.errors)


def test_a_dropped_placeholder_is_refused_even_though_the_editor_allows_it():
    """شکافِ اندازه‌گیری‌شده: `validate()` پایه، حذفِ placeholder را **می‌پذیرد**.

    برای ویرایشِ دستی عمدی است؛ برای فایلی که یک مترجمِ ماشینی ساخته نه — و
    شکستش کاملاً خاموش است: متن سالم می‌ماند و فقط عدد هرگز به کاربر نمی‌رسد.
    """
    key = next(k for k, v in _src().items() if _fields(v))
    plain = "sin ningun marcador"
    assert textstore.validate(_src()[key], plain) is None, (
        "پیش‌شرط: قاعدهٔ پایه باید این را بپذیرد، وگرنه تست شکافِ دیگری را می‌سنجد")
    rv = _review(_pack(**{key: plain}))
    assert not rv.ok
    assert any(k == key and "جاافتاده" in why for k, why in rv.errors)


def test_forbidden_html_is_refused():
    rv = _review(_pack(welcome="<script>alert(1)</script>"))
    assert not rv.ok
    assert any(k == "welcome" and "غیرمجاز" in why for k, why in rv.errors)


def test_nothing_is_accepted_when_anything_fails():
    """اتمیک بودن، به‌عنوان یک واقعیتِ دادهٔ `Review`، نه فقط رفتارِ هندلر."""
    rv = _review(_pack(**{**{k: "ES " + v for k, v in _src().items()},
                          "welcome": "<script>x</script>"}))
    assert not rv.ok and rv.errors


def test_a_partial_pack_reports_what_it_does_not_cover():
    src = _src()
    half = dict(list(src.items())[:100])
    body = json.loads(L.build_pack(lang="es", name="Español", source="fa", texts=half))
    rv = _review(body)
    assert rv.ok
    assert len(rv.entries) == 100
    assert rv.untouched == len(L.TEXT_KEYS) - 100
    assert rv.coverage == 100 * 100 // len(L.TEXT_KEYS)


def test_an_untranslated_value_is_counted_not_refused():
    """متنی که عیناً مبدأ است خطا نیست — ولی باید شمرده و گفته شود."""
    src = _src()
    body = _pack(**{k: "ES " + v for k, v in src.items()})
    keep = sorted(src)[0]
    body["texts"][keep] = src[keep]
    rv = _review(body)
    assert rv.ok
    assert rv.untranslated == [keep]


def test_the_changed_and_same_counts_describe_the_write():
    """عددی که تأییدِ زبانِ پیش‌فرض رویش بنا شده."""
    src = _src()
    current = {k: "old" for k in L.TEXT_KEYS}
    body = _pack(**{k: "ES " + v for k, v in src.items()})
    keep = sorted(src)[0]
    body["texts"][keep] = "old"                 # این یکی عوض نمی‌شود
    rv = _review(body, current=current)
    assert rv.same == 1 and rv.changed == len(L.TEXT_KEYS) - 1


def test_the_placeholder_contract_comes_from_the_source_text_not_the_catalog():
    """اگر ادمین متنِ مبدأ را ساده کرده باشد، ترجمهٔ ساده هم باید قبول شود.

    سنجیدن در برابرِ کاتالوگِ کد، یک ترجمهٔ **درست** را رد می‌کرد.
    """
    key = next(k for k, v in CATALOG["fa"].items() if _fields(v))
    trimmed_source = {**_src(), key: "بدونِ هیچ نشانه‌ای"}
    body = _pack(**{key: "sin marcador"})
    rv = L.review(body, source_texts=trimmed_source, current={})
    assert rv.ok, rv.errors
    assert rv.entries[key] == "sin marcador"
