"""دو قاعدهٔ قالب که شکستشان بی‌صداست — یکی امنیتی، یکی ۵۰۰ِ دیررس.

**۱ — هیچ `|safe`ی در قالب‌ها نیست.** autoescape روشن است و هر داده‌ای که از کاربر،
پیام‌های تلگرام، متنِ خطای موتور یا نامِ فایل می‌آید از قالب رد می‌شود. HTMLِ امن
فقط از `Markup`ِ **پایتونی** می‌آید (`ic`، `dots`، `Fmt.iso`) که ورودی‌اش را خودش
escape می‌کند؛ `|safe` در قالب یعنی آن تصمیم به جایی رفته که بازبینی نمی‌بیندش.

**۲ — کلیدِ dictی که همنامِ متدِ dict است با `.` خوانده نمی‌شود.** در Jinja،
`e.items` اول **ویژگیِ پایتونی** را می‌گیرد، پس روی dict به `dict.items` (متد)
می‌رسد نه به کلیدِ `"items"`. اجراشده در همین بازطراحی: برگهٔ دانلودِ **موفق**
(که کلیدِ `items` دارد) با `TypeError` ۵۰۰ می‌داد، و برگهٔ ناموفق — که تست‌ها اول
دیدند — نه. رفع `e['items']` است؛ این گارد کپیِ بعدی را می‌گیرد. فراخوانیِ واقعیِ
متد (`x.get('k')`، `d.items()`) مجاز است: فقط **بی‌فراخوانی** ممنوع است.
"""
from __future__ import annotations

import pathlib

import pytest
from jinja2 import nodes

ROOT = pathlib.Path(__file__).resolve().parents[2]
TPL = ROOT / "app" / "templates"
#: متدهای dict — از خودِ `dict` کشف می‌شود نه فهرستِ دستی.
DICT_METHODS = frozenset(n for n in dir(dict) if not n.startswith("_"))


def _env():
    from app import admin_web as aw
    return aw.ENV


def uncalled_dict_methods(source: str) -> list[str]:
    """`x.items`/`x.keys`/… که **فراخوانی نشده‌اند** — یعنی داده خوانده شده نه متد."""
    tree = _env().parse(source)
    called = {id(c.node) for c in tree.find_all(nodes.Call)}
    return sorted({g.attr for g in tree.find_all(nodes.Getattr)
                   if g.attr in DICT_METHODS and id(g) not in called})


def has_safe_filter(source: str) -> bool:
    tree = _env().parse(source)
    return any(f.name == "safe" for f in tree.find_all(nodes.Filter))


def _templates():
    return sorted(TPL.glob("*.html"))


def test_the_dict_method_list_is_discovered():
    assert {"items", "keys", "values", "get", "pop", "update"} <= DICT_METHODS


def test_the_checkers_can_fail():
    """کنترلِ منفی: هر دو چکر باید شکلِ بد را بگیرند و شکلِ درست را نه."""
    assert uncalled_dict_methods("{% for x in e.items %}{{ x }}{% endfor %}") == ["items"]
    assert uncalled_dict_methods("{{ g.values }}") == ["values"]
    assert uncalled_dict_methods("{% for k, v in d.items() %}{% endfor %}{{ x.get('k') }}"
                                 "{{ e['items'] }}") == []
    assert has_safe_filter("{{ x|safe }}") and has_safe_filter("{{ (a ~ b)|safe }}")
    assert not has_safe_filter("{{ x|e }}{{ y|tojson }}")


@pytest.mark.parametrize("path", _templates(), ids=lambda p: p.name)
def test_no_template_reads_a_dict_key_named_like_a_dict_method(path):
    bad = uncalled_dict_methods(path.read_text(encoding="utf-8"))
    assert not bad, (f"{path.name} این‌ها را با نقطه می‌خواند: {bad} — روی dict متد برمی‌گردد "
                     f"نه کلید؛ از `x['{bad[0]}']` استفاده کن.")


@pytest.mark.parametrize("path", _templates(), ids=lambda p: p.name)
def test_no_template_marks_data_as_safe(path):
    assert not has_safe_filter(path.read_text(encoding="utf-8")), (
        f"{path.name} از `|safe` استفاده می‌کند — HTMLِ امن باید از `Markup`ِ پایتونی بیاید")


def test_the_scan_covers_every_template():
    """ضدِتوخالی: پارامتریِ روی کشفِ تهی بی‌صدا ناپدید می‌شود."""
    assert len(_templates()) >= 15
