"""نگهبانِ مسیرِ تستِ پنل — که بی‌صدا نمیرد.

`tests/panel/` سه بندِ مستقل دارد و **هر سه** باید با هم درست بمانند، وگرنه
پوشش بی‌سروصدا صفر می‌شود:

  ۱) `pytest.ini` آن را از اجرای پیش‌فرض بیرون می‌گذارد (وگرنه اجرای محلی و
     jobِ اصلیِ CI روی نبودِ `cryptography`/`jinja2` می‌شکنند)
  ۲) jobِ `panel` در CI استکِ ادمین را نصب و همان پوشه را اجرا می‌کند
  ۳) `test_repo_hygiene._ADMIN_ONLY` همان پوشه را استثنا می‌کند

اگر (۲) حذف شود، (۱) و (۳) سرِ جایشان می‌مانند و پوشه **هرگز اجرا نمی‌شود** —
دقیقاً همان شکلِ مارکرِ ffmpeg که از ۲۰۲۶-۰۷ تا فاز ۲ب از هیچ‌چیز محافظت نمی‌کرد
و کسی متوجه نشد.

**این فایل عمداً در `tests/` است نه در `tests/panel/`** — اگر داخلِ آن پوشه
می‌بود، با حذفِ jobِ پنل خودِ نگهبان هم از اجرا می‌افتاد و نگهبانی که با چیزی
که نگهبانش است بمیرد، نگهبان نیست. این‌جا در jobِ **اصلی** می‌دود و هیچ
وابستگیِ ادمینی ندارد: همه‌چیز با AST و YAML خوانده می‌شود، بدونِ import.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "tests" / "panel"
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

#: کفِ تعدادِ تست. عمداً کف است نه عددِ دقیق — عددِ دقیق با هر تستِ تازه عوض
#: می‌شود و گارد را به یک مزاحمِ شکننده تبدیل می‌کند.
_MIN_PANEL_TESTS = 5


def _test_functions(path: Path) -> int:
    """تعدادِ تابعِ تست در یک فایل، با **AST** نه تطبیقِ رشته.

    رشته‌ای نوشتنش همان تله‌ای است که یک‌بار نگهبانِ `7z` را توخالی کرد: آن
    نسخه `@needs_7z`ِ داخلِ **داکس‌استرینگِ خودش** را می‌شمرد، پس با برداشتنِ
    دکوراتور هم سبز می‌ماند.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name.startswith("test_"))


def _panel_job() -> dict:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    for job in jobs.values():
        steps = job.get("steps", [])
        runs = " ".join(str(s.get("run", "")) for s in steps)
        if "requirements-admin.txt" in runs and "tests/panel" in runs:
            return job
    raise AssertionError(
        "هیچ jobی در tests.yml هم `requirements-admin.txt` نصب می‌کند و هم "
        "`tests/panel` را اجرا — یعنی پوشهٔ پنل هیچ‌جا اجرا نمی‌شود.")


def test_the_panel_directory_is_not_dead_weight():
    """پوشه باید واقعاً تست داشته باشد، وگرنه jobش چیزی را ثابت نمی‌کند."""
    assert PANEL_DIR.is_dir(), f"{PANEL_DIR} وجود ندارد"
    files = sorted(PANEL_DIR.glob("test_*.py"))
    total = sum(_test_functions(p) for p in files)
    assert total >= _MIN_PANEL_TESTS, (
        f"فقط {total} تست در {PANEL_DIR.name}/ هست (کف: {_MIN_PANEL_TESTS}) — "
        f"یا تست‌های پنل حذف شده‌اند یا این مسیر دارد می‌میرد.")


def test_ci_runs_the_panel_directory_with_the_admin_stack():
    """jobِ پنل باید هم استکِ ادمین را نصب کند هم پوشه را اجرا."""
    job = _panel_job()          # نبودش خودش AssertionError است
    runs = " ".join(str(s.get("run", "")) for s in job["steps"])
    assert "pytest tests/panel" in runs, (
        "jobِ پنل `requirements-admin.txt` نصب می‌کند ولی `pytest tests/panel` "
        "را اجرا نمی‌کند.")


def test_the_panel_job_runs_in_parallel_with_the_main_job():
    """بدونِ `needs:` — وگرنه قرمزیِ jobِ اصلی نتیجهٔ پنل را پنهان می‌کند."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    with_needs = {name for name, j in jobs.items() if j.get("needs")}
    assert not with_needs, (
        f"این jobها `needs:` دارند و دیگر موازی نیستند: {sorted(with_needs)} — "
        f"شکستِ یکی نتیجهٔ دیگری را پنهان می‌کند.")


def test_the_panel_job_asserts_a_nonzero_collection():
    """jobِ پنل باید تعدادِ جمع‌شده را assert کند، نه فقط `pytest` را صدا بزند.

    کفِ فرسایش: اگر پوشه از چند تست به یکی برسد، کدِ خروجِ pytest همچنان صفر
    است و تنها همین assert می‌گیردش.
    """
    runs = " ".join(str(s.get("run", "")) for s in _panel_job()["steps"])
    assert "--collect-only" in runs and "-ge" in runs, (
        "گامِ «تعدادِ جمع‌شده» از jobِ پنل حذف شده.")


def test_the_guard_exemption_matches_the_directory_ci_actually_runs():
    """استثنای گارد و مسیرِ CI نباید از هم drift کنند.

    اگر یکی جابه‌جا شود و دیگری نه، یا تست‌های پنل اجرا نمی‌شوند یا گارد
    جلویشان را می‌گیرد — هر دو حالت بی‌سروصدا.
    """
    from tests.test_repo_hygiene import _PANEL_DIR

    runs = " ".join(str(s.get("run", "")) for s in _panel_job()["steps"])
    assert _PANEL_DIR in runs, (
        f"گارد «{_PANEL_DIR}» را استثنا می‌کند ولی CI آن مسیر را اجرا نمی‌کند.")
    assert (ROOT / _PANEL_DIR).is_dir(), f"{_PANEL_DIR} روی دیسک نیست"


def test_pytest_ini_keeps_the_panel_directory_out_of_the_default_run():
    """بدونِ این، `pytest`ِ خالی در محیطِ بدونِ استکِ پنل می‌شکند."""
    ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "--ignore=tests/panel" in ini


def test_the_ignore_does_not_beat_an_explicit_path(tmp_path):
    """تقدمِ `--ignore` در برابرِ مسیرِ صریح — پین‌شده، نه فرض‌شده.

    کلِ این طرح روی همین بند ایستاده: `pytest tests/panel` باید با وجودِ
    `addopts = --ignore=tests/panel` تست جمع کند. این قراردادِ pytest است و
    قراردادهای pytest **عوض می‌شوند** — اندازه‌گیری‌شده روی ۹.۱.۱: کدِ خروجِ
    «همه deselect شدند» حالا ۵ است، در حالی که §۶ ثبت کرده بود صفر است. پس این
    یکی هم پین می‌شود تا اگر روزی برگشت، صریح قرمز شود نه بی‌صدا.

    زیرفرایندِ واقعی، چون سؤال دربارهٔ **خطِ فرمانِ** pytest است نه یک تابع.
    """
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntestpaths = tests\naddopts = --ignore=tests/panel\n", encoding="utf-8")
    panel = tmp_path / "tests" / "panel"
    panel.mkdir(parents=True)
    (panel / "test_x.py").write_text("def test_x(): assert True\n", encoding="utf-8")

    def run(*args):
        return subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                               "-p", "no:cacheprovider", *args],
                              cwd=tmp_path, capture_output=True, text=True).stdout

    explicit = run("tests/panel")
    default = run()
    assert "test_x" in explicit, (
        "مسیرِ صریح دیگر بر `--ignore` مقدم نیست — jobِ پنل از این به بعد صفر "
        "تست جمع می‌کند. `addopts` باید از pytest.ini برداشته شود و jobِ اصلی "
        "خودش `--ignore` را بدهد.")
    # کنترلِ منفی: اگر این هم `test_x` داشته باشد یعنی `--ignore` اصلاً کار
    # نمی‌کند و تستِ بالا چیزی ثابت نکرده.
    assert "test_x" not in default, "`--ignore` در addopts بی‌اثر است"
