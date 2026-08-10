"""فاز ۲الف — موارد ۲-۸، ۲-۹، ۲-۱۰، ۲-۱۱.

هر کدام روی سورسِ پیش از رفع باید fail شود.
"""
from __future__ import annotations

import ast
import asyncio
import gc
import inspect
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from app import cookies as ck
from app import processing as P

REPO = Path(__file__).resolve().parents[1]


# ── ۲-۸: استخراجِ آرشیو ─────────────────────────────────────────
_HAS_7Z = any(os.access(os.path.join(d, "7z"), os.X_OK)
              for d in os.environ.get("PATH", "").split(os.pathsep) if d)
needs_7z = pytest.mark.skipif(not _HAS_7Z, reason="7z روی PATH لازم است")


def test_the_guard_checks_a_path_boundary_not_a_string_prefix():
    """`startswith(real_ex)` برای `<outdir>/exfil` هم صادق بود.

    این ایرادِ واقعیِ ۲-۸ است (نه zip-slip، که 7z خودش می‌بندد): مسیرِ خواهرِ
    `ex` که با همان حروف شروع شود از گارد رد می‌شد.
    """
    src = inspect.getsource(P.archive_extract)
    assert "startswith(inside)" in src, "گارد باید مرزِ مسیر را بسنجد نه پیشوند را"
    assert "os.sep" in src, "مرز باید با جداکنندهٔ مسیر ساخته شود"

    # و خودِ منطق: exfil نباید داخلِ ex حساب شود
    real_ex, inside = "/w/ex", "/w/ex" + os.sep
    assert "/w/exfil/a.txt".startswith(real_ex)          # تلهٔ نسخهٔ قبلی
    assert not "/w/exfil/a.txt".startswith(inside)       # رفعِ فعلی
    assert "/w/ex/a.txt".startswith(inside)              # فایلِ سالم باید بماند


@needs_7z
def test_7z_neutralises_traversal_absolute_and_symlink(tmp_path):
    """رفتارِ ضدِ-traversalِ 7z را **پین** می‌کند.

    گارد بعد از استخراج اجرا می‌شود، پس امنیتِ واقعی این‌جا به خودِ 7z بند است.
    اگر روزی باینری/استخراج‌کننده عوض شد و این تضمین رفت، باید این‌جا بفهمیم —
    نه در تولید.
    """
    arc, exdir = tmp_path / "evil.zip", tmp_path / "ex"
    outside = tmp_path / "OUTSIDE.txt"
    with zipfile.ZipFile(arc, "w") as z:
        z.writestr("../../OUTSIDE.txt", "escaped\n")
        z.writestr("/abs/ABS.txt", "absolute\n")
        z.writestr("ok.txt", "fine\n")
    exdir.mkdir()
    subprocess.run(["7z", "x", str(arc), f"-o{exdir}", "-y", "-bd", "-bb0"],
                   check=True, capture_output=True, timeout=60)

    assert not outside.exists(), "traversal از پوشهٔ استخراج بیرون زد"
    written = {str(p.relative_to(exdir)) for p in exdir.rglob("*") if p.is_file()}
    assert "ok.txt" in written
    assert all(".." not in w for w in written)
    for p in exdir.rglob("*"):                      # هیچ symlinkی ساخته نشود
        assert not p.is_symlink(), f"symlink ساخته شد: {p}"


# ── ۲-۹: رازِ node_peers ────────────────────────────────────────
def _func_src(path: str, name: str) -> str:
    """سورسِ یک تابع را **بدونِ import** بیرون می‌کشد.

    `app/admin_web.py` سرِ import به `cryptography`/`jinja2` نیاز دارد که فقط در
    `requirements-admin.txt`اند و در محیطِ تست (و روی رانرِ CI) نصب نیستند — پس
    `inspect.getsource` این‌جا اصلاً به تابع نمی‌رسد. همان محدودیتی که
    `routers/admin.py` را وادار کرد helper را در `cookies.py` بگذارد.
    """
    src = (REPO / path).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"تابعِ {name} در {path} پیدا نشد")


def test_server_no_longer_accepts_the_secret_in_the_query_string():
    src = _func_src("app/admin_web.py", "node_peers")
    assert 'request.query.get("key")' not in src, "راز نباید از query string خوانده شود"
    assert 'headers.get("X-Node-Key")' in src, "باید از هدر خوانده شود"


def test_the_client_was_changed_in_the_same_commit():
    """اگر فقط سمتِ سرور بسته شود، دفعهٔ بعد که نودی اضافه شود peerها بی‌صدا
    نمی‌آیند و هیچ‌چیز آن را نمی‌گیرد — این تست همان شکافِ دو-طرفه را می‌بندد."""
    sh = (REPO / "node/wg-sync.sh").read_text(encoding="utf-8")
    assert "/node/peers?key=" not in sh, "کلاینت هنوز راز را در URL می‌فرستد"
    assert "X-Node-Key: ${SECRET}" in sh, "کلاینت باید هدر بفرستد"


def test_no_caller_anywhere_still_uses_the_query_form():
    """کشفِ خودکار روی کلِ ریپو، چون کلاینتِ سوم ممکن است بعداً اضافه شود."""
    # فقط کدِ اجرایی؛ خودِ tests/ عمداً این رشته را به‌عنوان الگو دارد.
    hits = subprocess.run(
        ["grep", "-rn", "--include=*.sh", "--include=*.py", "node/peers?key=",
         "app", "node"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    assert not hits, f"هنوز جایی راز را در query می‌فرستد:\n{hits}"


# ── ۲-۱۰: نشتِ قفلِ جمع‌کردن ────────────────────────────────────
def test_collect_locks_do_not_accumulate():
    """با dictِ معمولی هر chat_id تا ابد یک Lock جا می‌گذاشت."""
    from app.routers import ops
    ops._collect_locks.clear()
    for chat_id in range(500):
        ops._collect_lock(chat_id)          # هیچ ارجاعِ قوی‌ای نگه نمی‌داریم
    gc.collect()
    assert len(ops._collect_locks) == 0, \
        f"{len(ops._collect_locks)} قفل نشت کرد (باید صفر باشد)"


def test_a_held_lock_is_still_shared_between_concurrent_users():
    """درستی مهم‌تر از پاک‌سازی: تا وقتی کسی قفل را دارد، رقیب باید **همان** را بگیرد."""
    from app.routers import ops
    ops._collect_locks.clear()

    async def scenario():
        held = ops._collect_lock(7)         # ارجاعِ قوی، مثلِ `async with`
        async with held:
            assert ops._collect_lock(7) is held, "کارِ هم‌زمان قفلِ دیگری گرفت"
            assert ops._collect_lock(8) is not held
        return held

    held = asyncio.run(scenario())
    assert held.locked() is False
    del held
    gc.collect()
    assert len(ops._collect_locks) == 0, "بعد از آزادشدن باید جمع شود"


# ── ۲-۱۱: حذفِ فایلِ کوکی ───────────────────────────────────────
@pytest.mark.parametrize("evil", [
    "../../../../etc/passwd",
    "../outside.txt",
    "/etc/shadow",
    "..%2f..%2fx.txt",
    "sub/dir/x.txt",
])
def test_cookie_path_never_escapes_the_directory(tmp_path, monkeypatch, evil):
    monkeypatch.setattr(ck.settings, "cookies_dir", str(tmp_path))
    path = ck.cookie_path(evil)
    assert path is None or os.path.dirname(os.path.abspath(path)) == str(tmp_path)


def test_remove_cookie_file_deletes_only_inside(tmp_path, monkeypatch):
    """بردارِ واقعی: فایلِ بیرون از پوشه نباید حذف شود."""
    cdir = tmp_path / "cookies"
    cdir.mkdir()
    victim = tmp_path / "important.txt"
    victim.write_text("do not delete")
    (cdir / "ig1.txt").write_text("cookie")
    monkeypatch.setattr(ck.settings, "cookies_dir", str(cdir))

    ck.remove_cookie_file("../important.txt")
    assert victim.exists(), "فایلِ بیرونِ پوشه حذف شد"

    ck.remove_cookie_file("ig1.txt")
    assert not (cdir / "ig1.txt").exists(), "فایلِ سالم باید حذف شود"


def test_both_delete_paths_share_one_implementation():
    """پنل هر دو گارد را داشت و دوقلوی رباتی‌اش هیچ‌کدام را.

    دو نسخهٔ دست‌نویس دوباره واگرا می‌شوند، پس تست خودِ اشتراک را می‌سنجد نه
    نتیجه را.
    """
    from app.routers import admin as admin_router
    bot_side = inspect.getsource(admin_router.cookie_action)
    panel_side = _func_src("app/admin_web.py", "cookies_delete")
    for who, src in (("ربات", bot_side), ("پنل", panel_side)):
        assert "remove_cookie_file" in src, f"مسیرِ {who} از تابعِ مشترک استفاده نمی‌کند"
        assert "os.remove(" not in src, f"مسیرِ {who} هنوز مستقیم حذف می‌کند"
