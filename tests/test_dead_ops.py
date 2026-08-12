"""فاز ۳الف / موردِ ۸ — هیچ شاخهٔ opِ مرده‌ای در `_do_op` نماند.

`if op == "zip"` در `tasks.py` هرگز اجرا نمی‌شد: دکمهٔ «زیپ» به فلوِ جمع‌کردن
می‌رود و `op_collect_go` همیشه `zip_many` را صف می‌کند، حتی برای یک فایل.
`processing.make_zip` هم تنها فراخوانش همان شاخه بود، پس آن هم مرده بود.

گارد عمداً **کشف‌محور** است نه «چک کن رشتهٔ zip نباشد»: چیزی که ارزش دارد،
گرفتنِ شاخهٔ مردهٔ **بعدی** است. همین گارد سرِ نوشتنش یک موردِ دوم پیدا کرد
(`thumb` — پایینِ همین فایل).
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _handled_ops() -> set[str]:
    """opهایی که `_do_op` برایشان شاخه دارد."""
    tree = ast.parse((ROOT / "app" / "tasks.py").read_text())
    ops: set[str] = set()
    for fn in ast.walk(tree):
        if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == "_do_op"):
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Compare)
                    and isinstance(node.left, ast.Name) and node.left.id == "op"):
                continue
            for operator, comparator in zip(node.ops, node.comparators):
                if isinstance(operator, ast.Eq) and isinstance(comparator, ast.Constant):
                    ops.add(comparator.value)
                elif isinstance(operator, ast.In) and isinstance(
                        comparator, (ast.Set, ast.Tuple, ast.List)):
                    ops.update(e.value for e in comparator.elts
                               if isinstance(e, ast.Constant))
    assert ops, "هیچ شاخهٔ opی پیدا نشد — تحلیلگر شکسته، نه کد"
    return ops


def _enqueueable_ops() -> set[str]:
    """opهایی که واقعاً می‌توانند از `routers/ops.py` صف شوند.

    سه درِ ورودی هست و **هر سه** باید شمرده شوند؛ نسخهٔ اولِ همین تحلیل
    `_queue_quiet` را جا انداخته بود و `meta_read` را به‌غلط «مرده» نشان داد.
    """
    tree = ast.parse((ROOT / "app" / "routers" / "ops.py").read_text())
    ops: set[str] = set()
    for node in ast.walk(tree):
        # ۱) آرگومانِ رشته‌ایِ صریح به سه تابعِ صف‌کننده
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("_start", "_enqueue", "_queue_quiet"):
            ops.update(a.value for a in node.args
                       if isinstance(a, ast.Constant) and isinstance(a.value, str))
        # ۲) مجموعه‌های opِ سطحِ ماژول که به `callback_data.op` راه می‌دهند
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("_DIRECT_OPS", "_IMG_OPS"):
                    ops.update(e.value for e in getattr(node.value, "elts", [])
                               if isinstance(e, ast.Constant))
        # ۳) نگاشتِ purpose→op در `op_collect_go` (مقادیر + پیش‌فرضِ .get)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and isinstance(node.func.value, ast.Dict):
            ops.update(v.value for v in node.func.value.values
                       if isinstance(v, ast.Constant))
            ops.update(a.value for a in node.args[1:]
                       if isinstance(a, ast.Constant) and isinstance(a.value, str))
    assert ops, "هیچ opِ صف‌شدنی پیدا نشد — تحلیلگر شکسته، نه کد"
    return ops


# opهایی که هندلر دارند ولی امروز از هیچ مسیری صف نمی‌شوند، و **آگاهانه** سرِ
# جایشان مانده‌اند. این فهرست باید کوتاه بماند و هر ورودی‌اش دلیل داشته باشد.
#
# امروز **تهی** است: `thumb` — تنها ورودیِ تاریخیِ این فهرست — حذف شد، چون
# افزونهٔ `screenshot` بود (هر دو یک JPG به کاربر می‌دهند؛ تفاوت فقط در انتخابِ
# فریم بود: زمانِ انتخابیِ کاربر در برابرِ فریمِ نمایندهٔ خودکار) و منوی ویدیو
# از قبل ۱۱ دکمه داشت. با `cover` اشتباه گرفته نشود — آن جهتِ عکس است (عکس
# می‌گیرد و `file.cover_id` را ست می‌کند) و دست‌نخورده مانده.
_KNOWN_UNREACHABLE: set[str] = set()


def test_no_dead_op_branch_in_do_op():
    dead = _handled_ops() - _enqueueable_ops()
    assert dead == _KNOWN_UNREACHABLE, (
        f"مجموعهٔ opهای بی‌مسیر عوض شده.\n"
        f"  الان: {sorted(dead)}\n"
        f"  انتظار: {sorted(_KNOWN_UNREACHABLE)}\n"
        "اگر تازه است → شاخهٔ مرده اضافه شده (حذفش کن).\n"
        "اگر کم شده → درست شد؛ از _KNOWN_UNREACHABLE برش دار."
    )


def test_the_zip_branch_and_its_only_callee_are_gone():
    """رگرسیونِ مستقیمِ موردِ ۸ (تستِ بالا کلی است؛ این یکی صریح)."""
    tasks_src = (ROOT / "app" / "tasks.py").read_text()
    assert 'op == "zip"' not in tasks_src, "شاخهٔ مردهٔ zip برگشته"
    assert "zip_many" in tasks_src, "مسیرِ زندهٔ zip_many نباید حذف شود"

    proc_src = (ROOT / "app" / "processing.py").read_text()
    assert "async def make_zip(" not in proc_src, "make_zipِ بی‌مصرف برگشته"
    assert "async def make_zip_many(" in proc_src, "make_zip_many باید بماند"


def test_the_analyzer_sees_the_live_ops():
    """ضدِ vacuous: اگر تحلیلگر خراب شود هر دو مجموعه تهی و تست بی‌معنا می‌شود."""
    handled, enqueueable = _handled_ops(), _enqueueable_ops()
    for op in ("compress", "rename", "zip_many", "trim"):
        assert op in handled, f"{op} باید هندلر داشته باشد"
        assert op in enqueueable, f"{op} باید صف‌شدنی باشد"
    # و `zip` دیگر نه هندلر دارد نه مسیر
    assert "zip" not in handled
