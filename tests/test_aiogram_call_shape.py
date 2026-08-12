"""گاردِ شکلِ فراخوانیِ aiogram — `edit_message_*` باید kwarg صدا زده شود.

باگی که این گارد از آن آمد سه هفته زنده بود و هیچ‌کس ندید. `edit_message_text`
و `edit_message_caption` تنها متدهایی‌اند که `business_connection_id` را **قبل**
از `chat_id` دارند:

    send_message           (chat_id, text, business_connection_id, …)   ← شهودی
    delete_message         (chat_id, message_id, …)                      ← شهودی
    edit_message_text      (text, business_connection_id, chat_id, …)    ← تله
    edit_message_caption   (business_connection_id, chat_id, …)          ← تله

پس `edit_message_text(text, chat_id, mid)` که کاملاً طبیعی به‌نظر می‌رسد،
`chat_id` را در `business_connection_id` می‌گذارد و pydantic یک
`ValidationError` می‌دهد — که در هر دو محلِ فراخوانی داخلِ `except Exception`
بلعیده می‌شد. نتیجه: tickerِ غربالگری هیچ‌وقت شلیک نکرد، و پیامِ «محتوای
غیرمجاز» هرگز به کاربر نرسید.

گارد عمداً روی **همهٔ** متدهای مستعد است، نه فقط دوتای امروز، و از خودِ امضای
`aiogram.Bot` کشفشان می‌کند — نه از فهرستِ دستی.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

from aiogram import Bot

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def _trap_methods() -> set[str]:
    """متدهایی که پارامترِ دومشان `chat_id` **نیست** → فراخوانیِ موضعی خطرناک است."""
    traps = set()
    for name in dir(Bot):
        if name.startswith("_"):
            continue
        fn = getattr(Bot, name, None)
        if not callable(fn):
            continue
        try:
            params = [p for p in inspect.signature(fn).parameters][1:]
        except (TypeError, ValueError):
            continue
        if params[:1] == ["chat_id"]:
            continue                      # اولین پارامتر chat_id است → شهودی
        if "chat_id" in params[:4]:
            traps.add(name)               # chat_id هست ولی اولْ نیست → تله
    return traps


def test_the_trap_list_really_contains_the_edit_methods():
    """ضدِ vacuous: اگر کشف خراب شود، گاردِ پایین بی‌معنا می‌شود."""
    traps = _trap_methods()
    assert "edit_message_text" in traps
    assert "edit_message_caption" in traps
    assert "send_message" not in traps, "send_message شهودی است و نباید تله شمرده شود"
    assert "delete_message" not in traps


def _positional_calls_to(traps: set[str]) -> list[str]:
    """فراخوانی‌هایی از متدهای تله‌دار که آرگومانِ **موضعی** دارند."""
    bad: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in traps or not node.args:
                continue
            bad.append(f"{path.relative_to(ROOT)}:{node.lineno} → "
                       f"{node.func.attr}() با {len(node.args)} آرگومانِ موضعی")
    return bad


def test_edit_methods_are_never_called_positionally():
    bad = _positional_calls_to(_trap_methods())
    assert not bad, (
        "این متدها `business_connection_id` را قبل از `chat_id` دارند، پس آرگومانِ "
        "موضعی در جای غلط می‌نشیند و در زمانِ اجرا `ValidationError` می‌دهد — که "
        "معمولاً داخلِ یک `except` بلعیده می‌شود و بی‌صدا می‌ماند:\n  "
        + "\n  ".join(bad))


def test_the_analyzer_actually_sees_calls():
    """ضدِ vacuous: مطمئن شو تحلیلگر واقعاً فراخوانی‌ها را پیدا می‌کند."""
    found = 0
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("edit_message_text", "edit_message_caption"):
                found += 1
    assert found >= 3, f"فقط {found} فراخوانی پیدا شد — تحلیلگر شکسته است"
