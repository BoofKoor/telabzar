"""Build `app/static/icons.svg`, the admin panel's icon sprite, from Lucide.

Usage (dev machine, not the server):

    npm pack lucide-static@1.47.0 && tar xzf lucide-static-1.47.0.tgz
    python tools/panel_icons.py package/icons

Which icons go in is **discovered**, not listed by hand: every string literal in
the panel's templates, its Python modules and `panel.js` that is the name of a
Lucide icon, plus every `#i-<name>` reference. A hand-written list is the shape
that rots (a new `ic('…')` with no symbol renders as an empty box and nothing
fails), so the list is rebuilt from the code each time, and
`tests/panel/test_panel_icons.py` fails when the code names an icon the
committed sprite does not have — i.e. when this script was not re-run.

A literal that happens to equal an icon name but is not used as one ("type",
"list", …) adds one unused symbol; that costs a few hundred bytes in a file that
is served gzipped and cached for a year, which is cheaper than a second list.

Lucide is ISC-licensed; the licence asks for its notice in every copy, so the
sprite carries it.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
OUT = APP / "static" / "icons.svg"
PY_SOURCES = ("admin_web.py", "panel_data.py", "panel_settings.py")
JS_SOURCES = ("static/js/panel.js",)
SVG_NS = "http://www.w3.org/2000/svg"
#: Lucide's own drawing elements; anything else in a source file is not copied.
SHAPES = {"path", "circle", "rect", "line", "polyline", "polygon", "ellipse"}

_QUOTED = re.compile(r"""['"]([a-z0-9]+(?:-[a-z0-9]+)*)['"]""")
_HREF = re.compile(r"#i-([a-z0-9]+(?:-[a-z0-9]+)*)")

LICENSE = """Icons: Lucide (https://lucide.dev), lucide-static v{version}.
ISC License. Copyright (c) Lucide Icons and Contributors.
Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.
THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER
RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT,
NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE
USE OR PERFORMANCE OF THIS SOFTWARE.
Built by tools/panel_icons.py from the names the panel code uses; do not edit by hand."""


def candidates() -> set[str]:
    """Every icon-shaped name the panel code mentions (a superset; filtered by Lucide)."""
    names: set[str] = set()
    for tp in sorted((APP / "templates").glob("*.html")):
        src = tp.read_text(encoding="utf-8")
        names |= set(_QUOTED.findall(src)) | set(_HREF.findall(src))
    for rel in JS_SOURCES:
        src = (APP / rel).read_text(encoding="utf-8")
        names |= set(_QUOTED.findall(src)) | set(_HREF.findall(src))
    for rel in PY_SOURCES:
        tree = ast.parse((APP / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
    return names


def symbol(name: str, svg_path: pathlib.Path) -> str:
    tree = ET.parse(svg_path)
    parts = []
    for el in tree.getroot():
        tag = el.tag.split("}")[-1]
        if tag not in SHAPES:
            continue
        attrs = "".join(f' {k}="{v}"' for k, v in el.attrib.items() if k not in ("class",))
        parts.append(f"<{tag}{attrs}/>")
    return f'<symbol id="i-{name}" viewBox="0 0 24 24">{"".join(parts)}</symbol>'


def build(icons_dir: pathlib.Path) -> tuple[str, list[str]]:
    available = {p.stem: p for p in icons_dir.glob("*.svg")}
    if not available:
        raise SystemExit(f"no *.svg in {icons_dir} — pass lucide-static's icons/ folder")
    pkg = icons_dir.parent / "package.json"
    version = json.loads(pkg.read_text())["version"] if pkg.is_file() else "?"
    names = sorted(n for n in candidates() if n in available)
    body = "\n".join(symbol(n, available[n]) for n in names)
    text = (f"<!--\n{LICENSE.format(version=version)}\n-->\n"
            f'<svg xmlns="{SVG_NS}" style="display:none">\n{body}\n</svg>\n')
    return text, names


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[0])
        print("usage: python tools/panel_icons.py <lucide-static>/icons")
        return 2
    text, names = build(pathlib.Path(argv[1]))
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(names)} icons, {len(text.encode())} bytes")
    print(" ".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
