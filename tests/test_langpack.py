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
    ('{"foo":"bar"}', "texts"),
    ('{"telabzar_i18n":999,"texts":{"a":"b"}}', "نسخه"),
    ('{"telabzar_i18n":1}', "texts"),
    ('{"telabzar_i18n":1,"texts":{}}', "خالی"),
    ('{"telabzar_i18n":1,"texts":{"welcome":5}}', "غیرمتنی"),
    ('{"telabzar_i18n":1,"texts":["welcome"]}', "texts"),
], ids=["empty", "not-json", "array-root", "not-a-pack", "bad-version",
        "no-texts", "empty-texts", "non-string-value", "texts-not-object"])
def test_a_file_level_problem_says_what_is_wrong(raw, frag):
    """«not-a-pack» تا ۲۰۲۶-۱۰-۱۰ `{"texts":…}`ِ بی‌نشانگر بود؛ حالا آن پذیرفته می‌شود
    (پایین‌تر) و فقط شیئی که نه `texts` دارد نه هیچ کلیدِ متنِ ربات «فایلِ ما نیست»."""
    with pytest.raises(L.PackError, match=frag):
        L.parse_pack(raw)


# ── آنچه چت‌بات با فایل می‌کند (۲۰۲۶-۱۰-۱۰) ────────────────────────────────
# گزارشِ اپراتور: «نتوانستم JSONِ خودم را برای انگلیسی اضافه کنم». فایل را نداریم؛
# پس هر شکلِ رایجِ پاسخِ یک چت‌بات این‌جا یک مورد است، و پیش از رفع همه رد می‌شدند —
# بیشترشان با «JSONِ نامعتبر (خط ۱، ستون ۱)» در حالی که خودِ JSON سالم بود.
def _full(lang="es", source="fa") -> str:
    return L.build_pack(lang=lang, name="X", source=source, texts=_src())


@pytest.mark.parametrize("wrap", [
    "Here is the translated file:\n\n```json\n{0}\n```",
    "```json\n{0}\n```\nLet me know if you need anything else!",
    "Sure! Here it is:\n{0}\nI kept every key.",
    "I kept every {{placeholder}} exactly as it was:\n{0}",
    "Here: {1}",
    "```json {1}```",
], ids=["preamble-fence", "fence-epilogue", "prose-no-fence", "brace-in-prose",
        "same-line-minified", "one-line-fence"])
def test_a_reply_with_prose_around_the_json_is_read(wrap):
    """مدل تقریباً همیشه جمله‌ای پیش یا پس از فایل می‌نویسد، حتی وقتی گفته‌ایم «فقط JSON»."""
    raw = _full()
    mini = json.dumps(json.loads(raw), ensure_ascii=False)
    data = L.parse_pack(wrap.format(raw, mini))
    assert data["texts"] == json.loads(raw)["texts"]


def test_a_json_example_in_the_prose_does_not_beat_the_fenced_file():
    """لایهٔ «فنس مقدم است»، جدا از لایهٔ «اولِ خط» سنجیده می‌شود.

    بی فنس، اولین «{»ِ ابتدای خط یک شیءِ کاملِ **دیگر** است و همان برنده می‌شد؛ فایلِ
    واقعی داخلِ فنس است.
    """
    raw = 'The format looks like this:\n{"lang": "es"}\n\nAnd here is the file:\n```json\n' + _full() + "\n```"
    assert len(L.parse_pack(raw)["texts"]) == len(L.TEXT_KEYS)


def test_a_literal_line_break_inside_a_text_is_kept():
    """مدل گاهی به‌جای `\\n` خودِ خط را می‌شکند؛ JSONِ سخت‌گیر آن را رد می‌کرد."""
    src = _src()
    key = next(k for k, v in sorted(src.items()) if "\n" in v)
    raw = _full()
    enc = json.dumps(src[key], ensure_ascii=False)
    broken = raw.replace(enc, enc.replace("\\n", "\n"), 1)
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken)                       # پیش‌شرط: واقعاً JSONِ سخت‌گیر را می‌شکند
    assert L.parse_pack(broken)["texts"][key] == src[key]


@pytest.mark.parametrize("readme_comma", [False, True], ids=["after-texts", "after-texts-and-readme"])
def test_a_trailing_comma_is_forgiven_but_a_comma_in_or_between_texts_is_kept(readme_comma):
    """ویرگولِ آخر برداشته می‌شود — فقط بیرونِ رشته‌ها، و ویرگولِ میانِ دو رشته نه.

    `readme` یک فهرستِ رشته است. حالتِ «after-texts» همان است که تعمیر را می‌آزماید: ویرگولِ
    اضافه فقط پس از `texts` است، پس تعمیر روی کلِ متن می‌دود و فهرستِ **سالمِ** readme را هم
    می‌بیند — اگر ویرگولِ پیش از آخرین سطرش «آخرِ فهرست» خوانده شود، خودِ تعمیر JSON را
    می‌شکند.
    """
    body = json.loads(_full())
    key = sorted(body["texts"])[0]
    body["texts"][key] = "a, } b ,]"
    raw = json.dumps(body, ensure_ascii=False, indent=2)
    assert raw.rstrip().endswith("}\n}")
    raw = raw.rstrip()[:-len("}\n}")] + "},\n}"             # ویرگولِ اضافه پس از `texts`
    if readme_comma:
        assert raw.count('"\n  ],') == 1
        raw = raw.replace('"\n  ],', '",\n  ],', 1)         # و پس از آخرین سطرِ readme
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    data = L.parse_pack(raw)
    assert data["texts"][key] == "a, } b ,]"
    assert data["readme"] == body["readme"]


@pytest.mark.parametrize("cut", [
    lambda r: r[:len(r) // 2],
    lambda r: "Here you go:\n```json\n" + r[:len(r) // 2],
    lambda r: r[:r.index('": "', len(r) // 2) + 6],
    lambda r: r[:r.index('",\n', len(r) // 2) + 2],
], ids=["half", "unterminated-fence", "inside-a-string", "after-a-comma"])
def test_a_cut_off_reply_says_it_was_cut_off(cut):
    """۲۸۰ متن برای یک پاسخ زیاد است و مدل وسطِ کار قطع می‌کند؛ پیام باید همین را بگوید
    و راهِ بخش‌بخش را نشان دهد، نه «JSONِ نامعتبر» در خطی که ادمین نمی‌فهمد چرا."""
    with pytest.raises(L.PackError, match="ناقص") as e:
        L.parse_pack(cut(_full()))
    assert "ادغام" in str(e.value)


def test_a_broken_json_names_the_line_in_the_pasted_text():
    """شمارهٔ خط در **متنِ چسبانده‌شده**، با تکهٔ همان خط — نه در زیرمتنی که پارسر دید."""
    raw = _full().replace('",\n    "', '"\n    "', 1)      # یک ویرگولِ جاافتاده وسطِ فایل
    pasted = "Here is the file.\nIt is complete.\n```json\n" + raw + "\n```"
    with pytest.raises(L.PackError) as e:
        L.parse_pack(pasted)
    msg = str(e.value)
    at = pasted.index('"\n    "') + 1
    want = pasted.count("\n", 0, at) + 2                   # خطِ کلیدِ بعدی، همان‌جا که JSON می‌شکند
    assert f"خط {want}،" in msg, msg
    assert "ناقص" not in msg
    nxt = pasted[at + 1:].lstrip().split('"')[1]
    assert nxt[:30] in msg, "تکهٔ همان خط باید در پیام بیاید"


def test_the_error_comes_from_the_json_not_from_a_brace_in_the_prose():
    """خطا از تلاشی که **بیشترین پیشروی** را داشته: خودِ فایل، نه جملهٔ نثری که با «{» شروع شده."""
    raw = _full().replace('",\n    "', '"\n    "', 1)
    pasted = "{note}: the file follows\n" + raw
    with pytest.raises(L.PackError) as e:
        L.parse_pack(pasted)
    assert "خط 1،" not in str(e.value), str(e.value)


@pytest.mark.parametrize("make", [
    lambda t: {"texts": t},
    lambda t: dict(t),
    lambda t: {"lang": "es", "name": "X", "source": "fa", "readme": ["x"], **t},
], ids=["texts-only", "flat", "flat-with-envelope-fields"])
def test_a_pack_without_its_envelope_is_accepted(make):
    """«Reply with the JSON only» را مدل گاهی «فقط متن‌ها» می‌فهمد. بی‌خطر است: زبان را کدِ
    فرم تعیین می‌کند و هر کلید/متن جداگانه سنجیده می‌شود."""
    texts = _src()
    data = L.parse_pack(json.dumps(make(texts), ensure_ascii=False))
    assert data["texts"] == texts
    rv = L.review(data, source_texts=texts, current={})
    assert rv.ok, rv.errors[:3]


def test_the_version_may_arrive_as_a_string():
    raw = _full().replace('"telabzar_i18n": 1', '"telabzar_i18n": "1"', 1)
    assert '"telabzar_i18n": "1"' in raw
    assert len(L.parse_pack(raw)["texts"]) == len(L.TEXT_KEYS)


def test_the_error_list_can_be_copied_whole():
    """فهرستِ کپی‌شونده همهٔ خطاهاست، یکی در هر خط — نه سی‌تای اولی که صفحه نشان می‌داد."""
    keys = sorted(L.TEXT_KEYS)[:40]
    rv = _review(_pack(**{k: "<br>" for k in keys}))
    lines = rv.errors_text.splitlines()
    assert len(lines) == len(rv.errors) == 40
    assert {ln.split(":", 1)[0] for ln in lines} == set(keys)


def test_the_readme_steers_the_model_away_from_the_usual_breakages():
    body = json.loads(_full())
    joined = " ".join(body["readme"]).lower()
    for must in ("<br>", "markdown", "before or after", "several complete json parts"):
        assert must in joined, f"readme دربارهٔ «{must}» چیزی نمی‌گوید"


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
