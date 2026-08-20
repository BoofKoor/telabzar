"""نامِ فیلدهای فرمِ کنسول باید با چیزی که هندلر می‌خواند یکی باشد.

**چرا این گارد وجود دارد: سه باگ را گرفت که بازخوانی نگرفته بود.** فرم‌های
کنسول به هندلرهای **موجودِ** Jinja پست می‌کنند، و یک نامِ فیلدِ غلط شکستِ
کاملاً خاموش می‌دهد — POST می‌رود، ۳۰۲ برمی‌گردد، صفحهٔ نتیجه می‌آید، و
**هیچ اتفاقی نمی‌افتد**. همان «بنرِ سبز روی کاری که انجام نشد» که §۷ چهار
نمونه‌اش را ثبت کرده، این‌بار از سمتِ فرستنده.

سه موردِ واقعی (۲۰۲۶-۰۸-۲۰): `/users/block` شناسهٔ تلگرام می‌فرستاد در
حالی که هندلر **کلیدِ اصلی** می‌خواهد؛ `/cookies/add` فیلد را `text` نامیده
بود و هندلر `content` می‌خواند؛ `/langs/delete` فیلد را `lang` نامیده بود و
هندلر `code`. هیچ‌کدام تستِ موجودی را قرمز نمی‌کردند.

پس ادعا **کشف‌محور** است: هر `<form action="…">` در `panel/app` پیدا می‌شود،
هندلرش از جدولِ روتِ `admin_web` درمی‌آید، و نامِ فیلدها مقایسه می‌شود.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PANEL_APP = ROOT / "panel" / "app"
ADMIN = ROOT / "app" / "admin_web.py"

#: فیلدهایی که هندلر می‌خواند ولی فرم لازم نیست بفرستد، با دلیل.
#:
#: `page`/`q` حالتِ صفحه‌بندی‌اند و نبودشان یعنی «صفحهٔ اول»؛ `confirm` گامِ
#: **دومِ** جریانِ import است (REVIEW اول دیف را نشان می‌دهد)؛ `name` نامِ
#: نمایشیِ اختیاریِ زبان است که به `pack["name"]` برمی‌گردد.
_OPTIONAL = {"page", "q", "back", "to", "confirm", "name", "ret"}


def _handler_fields() -> dict[str, set[str]]:
    """مسیرِ POST → مجموعهٔ نامِ فیلدهایی که هندلرش می‌خواند."""
    src = ADMIN.read_text(encoding="utf-8")
    bodies: dict[str, str] = {}
    for m in re.finditer(r"^async def (\w+)\(request: web\.Request\).*?(?=^async def |\Z)", src, re.S | re.M):
        bodies[m.group(1)] = m.group(0)

    out: dict[str, set[str]] = {}
    for path, fn in re.findall(r'add_post\(\s*"([^"]+)"\s*,\s*(\w+)\)', src):
        body = bodies.get(fn, "")
        fields = set(re.findall(r'form\.get\(\s*[\'"]([\w]+)[\'"]', body))
        # فیلدهای per-op مثلِ `f"text_{op}"` — پیشوند نگه داشته می‌شود.
        fields |= {f"{p}_*" for p in re.findall(r'form\.get\(f"(\w+)_\{', body)}
        out[path] = fields
    return out


def _form_fields() -> dict[str, set[str]]:
    """مسیرِ `action` → مجموعهٔ نامی که فرمِ کنسول می‌فرستد."""
    out: dict[str, set[str]] = {}
    for f in PANEL_APP.rglob("page.tsx"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r'action="(/[^"]+)"(.*?)</form>', text, re.S):
            path, body = m.group(1), m.group(2)
            names = set(re.findall(r'name="([\w]+)"', body))
            names |= {f"{p}_*" for p in re.findall(r'name=\{`(\w+)_\$\{', body)}
            out.setdefault(path, set()).update(names)
    return out


def test_the_parsers_actually_find_something():
    """کنترلِ ضدِتوخالی: مجموعهٔ تهی هر ادعای زیر را بی‌معنا می‌کند."""
    forms, handlers = _form_fields(), _handler_fields()
    assert len(forms) >= 8, sorted(forms)
    assert len(handlers) >= 10, sorted(handlers)
    assert any(v for v in forms.values()), "هیچ نامِ فیلدی پیدا نشد"


def test_every_console_form_posts_to_a_real_route(panel):
    """`action` باید یک روتِ POSTِ ثبت‌شده باشد، نه یک آرزو."""
    routes = {r.resource.canonical for r in panel.client.app.router.routes() if r.resource}
    missing = [p for p in _form_fields() if p not in routes]
    assert not missing, f"این مسیرها POST ندارند: {missing}"


def test_no_form_sends_a_field_its_handler_never_reads():
    """جهتِ خطرناک — و همانی که سه بار افتاد.

    فیلدی که هندلر نمی‌خواندش یعنی کنش بی‌صدا هیچ کاری نمی‌کند: POST موفق
    است، ۳۰۲ می‌آید، و حالت عوض نمی‌شود.
    """
    handlers = _handler_fields()
    problems = []
    for path, sent in sorted(_form_fields().items()):
        want = handlers.get(path, set())
        for field in sorted(sent - want):
            problems.append(f"{path} می‌فرستد «{field}» ولی هندلرش نمی‌خواند")
    assert not problems, "\n".join(problems)


def test_no_form_omits_a_field_its_handler_requires():
    """جهتِ برگشت، با استثناهای **نام‌برده و مستند** نه یک فهرستِ باز."""
    forms = _form_fields()
    problems = []
    for path, want in sorted(_handler_fields().items()):
        if path not in forms:      # کنسول هنوز این فرم را ندارد
            continue
        for field in sorted(want - forms[path] - _OPTIONAL):
            problems.append(f"{path} فیلدِ «{field}» را نمی‌فرستد")
    assert not problems, "\n".join(problems)
