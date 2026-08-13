"""فاز ۳الف — بهداشتِ ریپو: موردِ ۶ (فایلِ دیتابیسِ کامیت‌شده) و موردِ ۷ (کهنگیِ
`.env.example` در **هر دو** جهت).

این‌ها گاردهای ارزان‌اند و عمداً **کشف‌محور** نوشته شده‌اند نه فهرست‌دستی: درسی
که `test_worker_settings.py` و `test_ssrf.py` قبلاً ثبت کرده‌اند این است که هر
قاعده‌ای که با یک لیستِ دست‌نویس اعمال شود، روزی از خودِ کد عقب می‌افتد.
"""
from __future__ import annotations

import ast

import pathlib
import re
import subprocess

from pydantic_core import PydanticUndefined

from app.config import Settings

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── کمکی‌ها ────────────────────────────────────────────────────────────────
def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return out.stdout.split()


def _settings_keys() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def _compose_vars() -> set[str]:
    """متغیرهایی که خودِ docker-compose مصرف می‌کند (فیلدِ Settings نیستند)."""
    found: set[str] = set()
    for fname in ("docker-compose.yml", "docker-compose.nodes.yml"):
        found |= set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", (ROOT / fname).read_text()))
    return found


def _example_keys() -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=",
                          (ROOT / ".env.example").read_text(), re.M))


def _install_env_keys() -> set[str]:
    """کلیدهایی که `install.sh` واقعاً داخلِ `.env` می‌نویسد (از heredoc)."""
    src = (ROOT / "install.sh").read_text()
    m = re.search(r"cat > \.env <<EOF\n(.*?)\nEOF", src, re.S)
    assert m, "بلاکِ ساختِ .env در install.sh پیدا نشد — این تست باید به‌روز شود"
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", m.group(1), re.M))


# ── موردِ ۶: هیچ فایلِ دیتابیسی کامیت نشود ─────────────────────────────────
def test_no_database_file_is_committed():
    """`x.db` تا فاز ۳ کامیت‌شده بود (از PR #41).

    خالی بود و راز نداشت، ولی هیچ کدی هم نمی‌خواندش — تولید روی Postgres است.
    """
    bad = [p for p in _tracked_files()
           if p.endswith((".db", ".sqlite", ".sqlite3"))]
    assert not bad, f"فایلِ دیتابیس نباید کامیت شود: {bad}"


def test_gitignore_actually_blocks_database_files():
    """حذف از index کافی نیست — الگو باید جلوی برگشتنش را هم بگیرد."""
    r = subprocess.run(["git", "check-ignore", "-q", "x.db"], cwd=ROOT)
    assert r.returncode == 0, "`.gitignore` الگوی *.db را ندارد"


# ── موردِ ۷ (جهتِ رفت): کلیدِ مرده در نمونه نماند ──────────────────────────
def test_every_example_key_is_actually_consumed_somewhere():
    """هر کلیدِ `.env.example` یا فیلدِ Settings است یا compose مصرفش می‌کند.

    `DOMAIN` و `WEBHOOK_SECRET` هیچ‌کدام نبودند: اولی فقط ورودیِ خودِ
    `install.sh` است (برای ساختنِ `PUBLIC_BASE`) و دومی بازماندهٔ طرحِ webhook
    است در حالی که ربات long-polling می‌کند.
    """
    unknown = _example_keys() - _settings_keys() - _compose_vars()
    assert not unknown, f"کلیدِ نمونه که هیچ‌جا خوانده نمی‌شود: {sorted(unknown)}"


def test_install_script_writes_only_keys_that_are_read():
    """همان قاعده برای `.env`ی که installer می‌سازد.

    بستنِ فقط یک طرف بی‌فایده است: اگر نمونه پاک شود ولی `install.sh` همچنان
    `DOMAIN=` بنویسد، هر نصبِ تازه دوباره کلیدِ مرده می‌گیرد.
    """
    unknown = _install_env_keys() - _settings_keys() - _compose_vars()
    assert not unknown, f"install.sh کلیدِ مرده می‌نویسد: {sorted(unknown)}"


# ── موردِ ۷ (جهتِ برگشت): آنچه باید مستند باشد ────────────────────────────
def test_every_required_setting_is_documented():
    """کشف‌محور: هر فیلدِ **بدونِ پیش‌فرض** باید در نمونه باشد.

    امروز فقط `BOT_TOKEN` است، ولی فیلدِ الزامیِ بعدی خودکار پوشش می‌گیرد —
    بدونِ این‌که کسی یادش باشد این فایل را به‌روز کند.
    """
    required = {n.upper() for n, f in Settings.model_fields.items()
                if f.default is PydanticUndefined and f.default_factory is None}
    missing = required - _example_keys()
    assert not missing, f"فیلدِ الزامیِ مستندنشده: {sorted(missing)}"


# دنبالهٔ دستی و عمداً **کوتاه**: کلیدهایی که پیش‌فرض دارند (پس تستِ بالا
# نمی‌گیردشان) ولی بدونشان یک استقرارِ واقعی درست کار نمی‌کند. اگر روزی کلیدی
# از این‌جا بی‌اهمیت شد، حذفش کن — لیست نباید بلند شود.
_OPERATIONAL_KEYS = {
    "PROXY_URL",     # خروجیِ تمیز؛ خالی یعنی egress از IPِ خودِ مستر
    "ADMIN_SECRET",  # کلیدِ Fernetِ نشستِ پنل
    "NODE_SECRET",   # HMACِ توکنِ join نودها
    "PUBLIC_BASE",   # بدونش دکمهٔ «لینک» کار نمی‌کند
    "TLS_CERT",
    "TLS_KEY",
}


def test_operationally_critical_keys_are_documented():
    missing = _OPERATIONAL_KEYS - _example_keys()
    assert not missing, f"کلیدِ عملیاتیِ مستندنشده: {sorted(missing)}"


# ── ردهٔ کورِ «فقط روی CI می‌افتد» ───────────────────────────────
_ADMIN_ONLY = ("app.admin_web", "cryptography", "jinja2")


def test_no_test_imports_a_module_the_ci_runner_does_not_have():
    """هیچ تستی نباید چیزی را import کند که فقط در `requirements-admin.txt` است.

    **این گارد از یک شکستِ واقعیِ CI درآمد، نه از احتیاط.** یک تست
    `from app.admin_web import GROUPS` می‌کرد و محلی سبز بود چون سندباکسِ توسعه
    `cryptography` نصب داشت؛ روی رانرِ تمیز `ModuleNotFoundError` داد و PR را
    قرمز کرد. `requirements-dev.txt` عمداً استکِ پنل را ندارد، پس «محلی سبز
    است» درباره‌اش هیچ چیزی ثابت نمی‌کند — همان ردهٔ خطایی که با `7z` و با
    هارنسِ `:memory:` هم خوردیم.

    راهِ درست از قبل در ریپو بود: سورس را با AST بخوان، import نکن
    (`tests/test_phase2a._func_src`). این تست همان قاعده را اجباری می‌کند، و
    چون **کشف‌محور** است شاملِ هر تستِ تازه‌ای هم می‌شود.

    عمداً روی `tests/` است نه `app/`: خودِ پنل باید این‌ها را import کند.
    """
    offenders = []
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module]
            for m in mods:
                if any(m == a or m.startswith(a + ".") for a in _ADMIN_ONLY):
                    offenders.append(f"{path.name}:{node.lineno} → {m}")
    assert not offenders, (
        "این‌ها روی رانرِ CI موجود نیستند و فقط آن‌جا می‌افتند:\n  "
        + "\n  ".join(offenders)
        + "\nسورس را با AST بخوان (نمونه: tests/test_phase2a._func_src).")
