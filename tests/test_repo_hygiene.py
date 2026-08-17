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


#: اسراری که نصب‌کننده باید **تولید** کند (نه فقط بنویسد). فهرست صریح است، و
#: `test_no_new_bot_token_fallback_escapes_the_list` نگه‌داری‌اش می‌کند.
_GENERATED_SECRETS = {"ADMIN_SECRET", "NODE_SECRET"}


def _bot_token_fallbacks() -> set[str]:
    """تنظیماتی که کد روی خالی‌بودنشان به `BOT_TOKEN` برمی‌گردد."""
    found: set[str] = set()
    for path in (ROOT / "app").rglob("*.py"):
        for name in re.findall(r"settings\.([a-z_]+)\s+or\s+settings\.bot_token",
                               path.read_text(encoding="utf-8")):
            found.add(name.upper())
    return found


def test_every_generated_secret_is_actually_generated_by_the_installer():
    """هر رازِ این فهرست باید در `install.sh` تولید **و** حفظ شود.

    **این گارد از یک شکافِ واقعی درآمد.** `.env.example` از روزِ اول
    `ADMIN_SECRET` را مستند می‌کرد و `test_operationally_critical_keys_are_documented`
    هم نگهش می‌داشت — ولی `install.sh`، یعنی مسیری که هر نصبِ واقعی از آن
    می‌گذرد، **هرگز نمی‌نوشتش**. نتیجه: هر استقرارِ ساخته‌شده با نصب‌کننده
    کلیدِ نشستش را از `BOT_TOKEN` می‌گرفت، و `BOT_TOKEN` عمداً به هر نود داده
    می‌شود.

    گاردِ قبلی فقط **جهتِ رفت** را می‌بست (کلیدِ مرده ننویس). این یکی جهتِ
    برگشت است: چیزی که باید نوشته شود، نوشته می‌شود — و نه فقط نوشته، بلکه با
    مقدارِ **تولیدشده**، چون `X=` خالی همان تنزل را می‌دهد.
    """
    src = (ROOT / "install.sh").read_text()
    written = _install_env_keys()
    offenders = []
    for key in sorted(_GENERATED_SECRETS):
        if key not in written:
            offenders.append(f"{key}: در .env نوشته نمی‌شود")
        elif not re.search(rf"{key}=\$\(env_get {key}\).*\|\| {key}=\$\(rand", src):
            offenders.append(f"{key}: نوشته می‌شود ولی تولید/حفظ نمی‌شود")
    assert not offenders, (
        "این اسرار باید توسطِ نصب‌کننده تولید شوند:\n  " + "\n  ".join(offenders))


def test_no_new_bot_token_fallback_escapes_the_list():
    """نیمهٔ کشف‌محور — و **جهتش عمدی است**.

    نسخهٔ اولِ این گارد فهرست را از خودِ الگوی `settings.X or settings.bot_token`
    **کشف** می‌کرد، و با سابوتاژ معلوم شد خودتخریب است: رفعِ A-1 همان الگو را
    از `admin_web` برداشت، پس گارد دیگر `ADMIN_SECRET` را نمی‌خواست و
    برداشتنِ خطِ نصب‌کننده هیچ‌چیز را قرمز نمی‌کرد. معیاری که با رفعِ باگ ناپدید
    شود، از فردای رفع محافظت نمی‌کند.

    پس جهت برعکس شد: فهرست صریح است، و کشف کارِ **نگه‌داری**اش را می‌کند —
    هر fallbackِ تازه‌ای به `BOT_TOKEN` باید عضوِ فهرست باشد، وگرنه این تست
    می‌افتد و می‌گوید تولیدش را هم به نصب‌کننده اضافه کن.
    """
    escaped = _bot_token_fallbacks() - _GENERATED_SECRETS
    assert not escaped, (
        f"این‌ها روی خالی‌بودن به BOT_TOKEN تنزل می‌کنند ولی در "
        f"_GENERATED_SECRETS نیستند: {sorted(escaped)} — یا fallback را بردار، "
        f"یا به فهرست اضافه‌شان کن تا نصب‌کننده تولیدشان کند.")


def test_main_refuses_to_serve_without_the_session_secret():
    """`main()` باید `_require_admin_secret` را صدا بزند، پیش از `run_app`.

    با AST، نه تطبیقِ رشته — و **جدا از** تستِ رفتاریِ خودِ تابع: آن یکی تابع را
    مستقیم صدا می‌زند، پس اگر کسی فراخوانی را از `main()` بردارد ساکت می‌ماند.
    سابوتاژ دقیقاً همین را نشان داد.
    """
    tree = ast.parse((ROOT / "app" / "admin_web.py").read_text(encoding="utf-8"))
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    guard = [n.lineno for n in ast.walk(main)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_require_admin_secret"]
    serve = [n.lineno for n in ast.walk(main)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "run_app"]
    assert guard, (
        "main() دیگر رازِ نشست را چک نمی‌کند — پنل با ADMIN_SECRETِ خالی سرو می‌کند.")
    assert serve, "main() دیگر run_app صدا نمی‌زند — این تست باید به‌روز شود"
    assert min(guard) < min(serve), "چک باید **پیش از** سرو کردن باشد"


# ── ردهٔ کورِ «فقط روی CI می‌افتد» ───────────────────────────────
_ADMIN_ONLY = ("app.admin_web", "cryptography", "jinja2")

#: تنها مسیرِ **مجاز** برای importِ استکِ پنل. استثنا روی یک **پوشه** است نه
#: فهرستِ فایل، پس تستِ تازه‌ای که آن‌جا اضافه شود خودبه‌خود پوشش می‌گیرد و
#: کسی وسوسه نمی‌شود اسمِ فایلش را به فهرست اضافه کند (همان پوسیدگیِ
#: `_KNOWN_UNREACHABLE`). این پوشه در `pytest.ini` از اجرای پیش‌فرض بیرون است و
#: jobِ `panel` در CI با `requirements-admin.txt` اجرایش می‌کند —
#: `tests/test_panel_path_is_alive.py` هر سهٔ این بند را به هم گره می‌زند تا
#: هیچ‌کدام بی‌صدا از بقیه جدا نشود.
_PANEL_DIR = "tests/panel"


def _imported_modules(tree: ast.AST):
    """(نامِ کاملِ ماژول, خط) برای هر importِ درختِ AST.

    `from app import admin_web` هم باید «app.admin_web» بدهد، نه فقط «app» —
    وگرنه گارد یک **شکافِ واقعی** دارد: اندازه‌گیری‌شده، فرمِ
    `import app.admin_web` گرفته می‌شد ولی `from app import admin_web` بی‌صدا
    رد می‌شد، و دقیقاً همان فرمی است که آدم طبیعی می‌نویسد.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module, node.lineno
            for alias in node.names:
                yield f"{node.module}.{alias.name}", node.lineno


def _scannable(tests_dir: Path) -> list[Path]:
    """فایل‌هایی که گارد باید بخواند: تست‌ها **و** conftestها."""
    return sorted({*tests_dir.rglob("test_*.py"), *tests_dir.rglob("conftest.py")})


def _admin_only_offenders(paths, *, panel: Path | None) -> list[str]:
    """importهای ممنوعه در `paths`، با معافیتِ هرچه زیرِ `panel` است."""
    offenders = []
    for path in paths:
        if panel is not None and panel in path.resolve().parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for mod, lineno in _imported_modules(tree):
            if any(mod == a or mod.startswith(a + ".") for a in _ADMIN_ONLY):
                offenders.append(f"{path.name}:{lineno} → {mod}")
    return sorted(set(offenders))


def test_the_guard_also_reads_conftest_files(tmp_path):
    """الگوی قبلی `test_*.py` بود، پس conftest **کاملاً** نادیده گرفته می‌شد.

    و conftest دقیقاً جایی است که هارنس می‌نشیند — یعنی محتمل‌ترین جای یک
    importِ ممنوعه، نه یک حالتِ نظری.
    """
    (tmp_path / "test_a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("z = 3\n", encoding="utf-8")
    names = {p.name for p in _scannable(tmp_path)}
    assert names == {"test_a.py", "conftest.py"}, names


def test_the_guard_sees_the_from_package_import_form(tmp_path):
    """`from app import admin_web` باید گرفته شود، نه فقط `import app.admin_web`.

    اندازه‌گیری‌شده روی فرمِ قبلیِ گارد: دومی گرفته می‌شد و اولی بی‌صدا رد
    می‌شد — و اولی همان چیزی است که آدم طبیعی می‌نویسد.
    """
    f = tmp_path / "test_x.py"
    f.write_text("from app import admin_web\n", encoding="utf-8")
    assert _admin_only_offenders([f], panel=None) == ["test_x.py:1 → app.admin_web"]


def test_the_guard_still_sees_the_plain_and_submodule_forms(tmp_path):
    """کنترل: فرم‌هایی که از قبل گرفته می‌شدند نباید از دست بروند."""
    f = tmp_path / "test_y.py"
    f.write_text("import app.admin_web\nfrom cryptography.fernet import Fernet\n",
                 encoding="utf-8")
    hits = _admin_only_offenders([f], panel=None)
    assert any("app.admin_web" in h for h in hits)
    assert any("cryptography" in h for h in hits)


def test_an_ordinary_import_is_not_flagged(tmp_path):
    """کنترلِ معکوس: گارد نباید هر چیزی زیرِ `app` را بگیرد."""
    f = tmp_path / "test_z.py"
    f.write_text("from app import cookies\nimport app.downloader\n", encoding="utf-8")
    assert _admin_only_offenders([f], panel=None) == []


def test_the_panel_directory_is_exempt(tmp_path):
    """معافیت روی **پوشه** است، پس تستِ تازهٔ آن‌جا خودبه‌خود مجاز است."""
    panel = tmp_path / "panel"
    panel.mkdir()
    f = panel / "test_p.py"
    # عمداً فرمِ `import app.admin_web` نه `from app import ...`: این تست دربارهٔ
    # **معافیتِ مسیر** است، پس نباید به رفعِ فرمِ from-package گره بخورد — وگرنه
    # یک سابوتاژ دو تست را می‌اندازد و معلوم نمی‌شود کدام ادعا شکسته.
    f.write_text("import app.admin_web\n", encoding="utf-8")
    assert _admin_only_offenders([f], panel=None) != []      # بدونِ معافیت: گرفته می‌شود
    assert _admin_only_offenders([f], panel=panel.resolve()) == []


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
    offenders = _admin_only_offenders(_scannable(ROOT / "tests"),
                                      panel=(ROOT / _PANEL_DIR).resolve())
    assert not offenders, (
        "این‌ها روی رانرِ CI موجود نیستند و فقط آن‌جا می‌افتند:\n  "
        + "\n  ".join(sorted(set(offenders)))
        + f"\nیا سورس را با AST بخوان (نمونه: tests/test_phase2a._func_src)، "
          f"یا تست را در {_PANEL_DIR}/ بگذار که jobِ خودش را دارد.")


# ── حذفِ اکانتِ کوکی باید از یک جا باشد ────────────────────────────
#: گام‌های حذفِ یک اکانت. تکِ هرکدام کاربردِ مشروع دارد (مثلاً
#: `_mirror_all_cookies` فقط آینه را با دیسک هماهنگ می‌کند)؛ چیزی که باگ‌زاست
#: **ترکیب**شان در یک تابع است، یعنی یک کپیِ دستیِ دیگر از `delete_account`.
_DELETE_STEPS = ("remove_cookie_file", "_unmirror_cookie", "del_meta")


def test_only_delete_account_open_codes_the_delete_sequence():
    """هیچ تابعی جز `cookies.delete_account` نباید دنبالهٔ حذف را دستی بنویسد.

    دو مسیرِ حذف (پنل و کال‌بکِ ربات) هر سه گام را داشتند ولی با **ترتیبِ
    متفاوت** — همان شکلی که بعداً یکی به‌روز می‌شود و آن یکی نه، دقیقاً همان
    چیزی که یک‌بار `remove_cookie_file` را به `cookies.py` برد. پرش از
    `_unmirror_cookie` بی‌سروصداست: اکانتِ حذف‌شده روی **نودِ دانلود** همچنان
    انتخاب می‌شود، چون `list_names` روی دیسکِ خالی به آینهٔ Redis برمی‌گردد.

    معیار «≥۲ گام در یک تابع» است نه «هر گامی»: نسخهٔ اولِ این تست روی تکِ
    هر گام می‌افتاد و `_mirror_all_cookies` را — که فقط آینه را پاک می‌کند و
    اصلاً حذفِ اکانت نیست — مثبتِ کاذب گرفت. باریک‌کردنِ **قاعده** درست است،
    نه استثنای دستی برای آن تابع (که همان پوسیدگیِ فهرستِ دستی است).

    کشف‌محور است، پس مسیرِ حذفِ سومِ آینده هم پوشش دارد. `app/cookies.py`
    استثناست: خودِ `delete_account` آن‌جا زندگی می‌کند.
    """
    offenders = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        if path.name == "cookies.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            used = {}
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else \
                    f.id if isinstance(f, ast.Name) else ""
                if name in _DELETE_STEPS:
                    used.setdefault(name, node.lineno)
            if len(used) >= 2:
                steps = "، ".join(f"{n}()@{ln}" for n, ln in sorted(used.items()))
                offenders.append(
                    f"{path.relative_to(ROOT)}:{fn.lineno} {fn.name}() → {steps}")
    assert not offenders, (
        "این‌ها باید `cookies.delete_account()` را صدا بزنند، نه دنبالهٔ حذف را "
        "دستی بنویسند:\n  " + "\n  ".join(offenders))
