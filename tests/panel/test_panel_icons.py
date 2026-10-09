"""هر نامِ آیکونی که پنل به کار می‌برد باید در اسپرایت (`app/static/icons.svg`) باشد.

آیکونِ ناموجود خطا نمی‌دهد: `<use href="…#i-nope">` بی‌صدا **هیچ** رسم نمی‌کند و یک
جای خالیِ ۱۶ پیکسلی می‌ماند — همان ردهٔ کلاسِ CSSِ تعریف‌نشده. و چون اسپرایت فقط
آیکون‌هایی را دارد که ساختش انتخاب کرده (نه کلِ Lucide)، افزودنِ `ic('foo')` بی‌آنکه
`foo` به اسپرایت برود محتمل‌ترین خطای بعدی است.

دو لایه، چون هیچ‌کدام به‌تنهایی کافی نیست:

* **رندرشده** — هر `#i-…`ِ همهٔ صفحه‌ها (با داده و بی‌داده). آیکونِ پویا (`ic(x.icon)`)
  فقط این‌جا دیده می‌شود.
* **ایستا** — نام‌های لفظی در قالب‌ها، `panel.js` و نقشه‌های پایتونی، چون شاخه‌ای که
  در هیچ fixtureی رندر نشود از لایهٔ اول رد می‌شود. نقشه‌های `*_ICON`/`*_PILL` با AST
  **کشف** می‌شوند، نه فهرستِ دستی.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest
from test_pages_render import PAGES

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "app"
SPRITE = APP / "static" / "icons.svg"
_USE = re.compile(r"#i-([a-z0-9-]+)")


def sprite_ids() -> set[str]:
    return set(re.findall(r'<symbol[^>]*\bid="i-([a-z0-9-]+)"', SPRITE.read_text(encoding="utf-8")))


# ── لایهٔ ایستا ──────────────────────────────────────────────────────────────
_TPL_IC = re.compile(r"""\b(?:ic|m\.empty)\(\s*'([a-z0-9-]+)'""")
_JS_IC = re.compile(r"""\bic\(\s*(?:[\w.]+\s*\|\|\s*)?'([a-z0-9-]+)'""")
_JS_TERNARY = re.compile(r"""#i-\$\{[^}]*\?\s*'([a-z0-9-]+)'\s*:\s*'([a-z0-9-]+)'\s*\}""")


def template_icons() -> dict[str, set[str]]:
    return {p.name: set(_TPL_IC.findall(p.read_text(encoding="utf-8")))
            for p in (APP / "templates").glob("*.html")}


def js_icons() -> set[str]:
    src = (APP / "static" / "js" / "panel.js").read_text(encoding="utf-8")
    out = set(_JS_IC.findall(src))
    for a, b in _JS_TERNARY.findall(src):
        out |= {a, b}
    return out


def _icon_of(map_name: str, node: ast.AST) -> list[str]:
    """نامِ آیکون از یک مقدارِ نقشه: `_PILL` = (کلاس, آیکون, …) · `_ICON` = آیکون یا (آیکون, رنگ)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Tuple) and node.elts:
        i = 1 if map_name.endswith("_PILL") else 0
        el = node.elts[i] if len(node.elts) > i else None
        if isinstance(el, ast.Constant) and isinstance(el.value, str):
            return [el.value]
    return []


def python_icons(path: pathlib.Path) -> tuple[set[str], set[str]]:
    """(نام‌ها, نامِ نقشه‌های کشف‌شده) — از AST، بی‌import."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    maps: set[str] = set()
    for node in ast.walk(tree):
        # ۱) هر dictِ لفظی با کلیدِ "icon"
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "icon" \
                        and isinstance(v, ast.Constant) and isinstance(v.value, str):
                    names.add(v.value)
        # ۲) نقشه‌های سطحِ ماژول `*_ICON` / `*_PILL`
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Dict):
            n = node.targets[0].id
            if n.endswith(("_ICON", "_PILL")):
                maps.add(n)
                for v in node.value.values:
                    names.update(_icon_of(n, v))
        # ۳) پیش‌فرضِ `.get(…, default)` روی همان نقشه‌ها
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and len(node.args) == 2:
            owner = node.func.value
            on = owner.id if isinstance(owner, ast.Name) else owner.attr if isinstance(owner, ast.Attribute) else ""
            if on.endswith(("_ICON", "_PILL")):
                names.update(_icon_of(on, node.args[1]))
        # ۴) `ic("…")` در خودِ پایتون
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ic" \
                and node.args and isinstance(node.args[0], ast.Constant):
            names.add(node.args[0].value)
    # رشتهٔ تهی یعنی «بی‌آیکون» (`_delta`): قالب‌ها `{% if x.icon %}` دارند.
    names.discard("")
    return names, maps


_PY = ("admin_web.py", "panel_data.py", "panel_settings.py")


def test_the_sprite_is_not_empty():
    """ضدِتوخالی: اسپرایتِ خالی هر ادعای «زیرمجموعه است» را بی‌معنا می‌کند."""
    assert len(sprite_ids()) >= 100


def test_the_static_discovery_finds_what_it_should():
    """کنترلِ منفی برای کشف: هر چهار شکلِ پایتونی و هر دو شکلِ JS."""
    src = ('X_ICON = {"a": "map-one", "b": ("map-two", "t1")}\n'
           'Y_PILL = {"a": ("good", "pill-one", "k")}\n'
           'def f():\n'
           '    d = {"icon": "dict-one"}\n'
           '    X_ICON.get(k, ("default-one", "t0")); Y_PILL.get(k, ("bad", "default-two"))\n'
           '    return ic("call-one")\n')
    p = ROOT / "tests" / "panel" / "__icons_probe.py"
    try:
        p.write_text(src, encoding="utf-8")
        names, maps = python_icons(p)
    finally:
        p.unlink()
    assert names == {"map-one", "map-two", "pill-one", "dict-one", "default-one", "default-two",
                     "call-one"}
    assert maps == {"X_ICON", "Y_PILL"}
    assert set(_JS_IC.findall("ic(icon || 'from-or') + ic('plain', 'ic-14')")) == {"from-or", "plain"}
    assert _JS_TERNARY.findall("`${S()}#i-${dark ? 'sun' : 'moon'}`") == [("sun", "moon")]


def test_the_known_icon_maps_are_still_discovered():
    """اگر نقشه‌ای تغییرِ نام دهد، کشف باید همچنان ببیندش — وگرنه این فایل بی‌صدا کور می‌شود."""
    _n, maps = python_icons(APP / "admin_web.py")
    assert {"_OP_ICON", "_JOB_PILL", "_DL_PILL", "_CK_PILL", "_LOG_ICON", "_ROLE_ICON"} <= maps
    _n, maps = python_icons(APP / "panel_data.py")
    assert {"PLAT_ICON", "KIND_ICON"} <= maps


@pytest.mark.parametrize("name", _PY)
def test_every_python_icon_exists(name):
    names, _maps = python_icons(APP / name)
    assert names, f"{name}: هیچ آیکونی کشف نشد"
    missing = sorted(names - sprite_ids())
    assert not missing, f"{name} از آیکون‌هایی استفاده می‌کند که در اسپرایت نیستند: {missing}"


def test_every_template_icon_exists():
    ids = sprite_ids()
    missing = {k: sorted(v - ids) for k, v in template_icons().items() if v - ids}
    assert not missing, f"آیکونِ ناموجود در قالب‌ها: {missing}"


def test_every_js_icon_exists():
    found = js_icons()
    assert {"circle-check", "sun", "moon"} <= found, found
    assert not sorted(found - sprite_ids())


def test_the_nav_and_settings_icons_exist():
    """دو منبعِ ساخت‌یافته که با AST به‌شکلِ «icon» دیده نمی‌شوند (تاپل/کلیدِ دیگر)."""
    from app import admin_web as aw
    from app import panel_settings as PS

    nav = {icon for _g, items in aw.NAV for _k, _h, icon, _t in items}
    secs = {s["icon"] for s in PS.SECTIONS}
    samples = {v[0] for v in aw._KIND_SAMPLE.values()}
    assert not sorted((nav | secs | samples) - sprite_ids())


# ── لایهٔ رندرشده ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", PAGES)
async def test_every_icon_a_page_renders_exists(seeded, path):
    html = await (await seeded.client.get(path, cookies=seeded.cookies)).text()
    used = set(_USE.findall(html))
    assert used, f"{path} هیچ آیکونی رندر نکرد"
    assert not sorted(used - sprite_ids()), path


async def test_every_icon_the_empty_panel_renders_exists(panel):
    for path in ("/", "/activity", "/reports", "/cookies", "/nodes", "/system", "/users"):
        html = await (await panel.client.get(path, cookies=panel.cookies)).text()
        assert not sorted(set(_USE.findall(html)) - sprite_ids()), path


def test_the_rendered_check_can_fail():
    """کنترلِ منفی: نامی که در اسپرایت نیست باید گزارش شود."""
    html = '<svg><use href="/static/icons.svg?v=1#i-circle-check"></use></svg><use href="#i-no-such-icon">'
    assert set(_USE.findall(html)) - sprite_ids() == {"no-such-icon"}
