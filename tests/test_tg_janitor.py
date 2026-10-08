"""پاک‌سازیِ پوشهٔ سرورِ محلیِ Bot API (`app/tg_janitor.py`).

انگیزه، اندازه‌گیری‌شده روی تولید (۲۰۲۶-۱۰-۰۴): ۱۰۵ ویدیو و ۹۴٫۷ گیگابایت در یک
روز در `tg-bot-api-data/<token>/videos/`. دیسک پر شد و Postgres (PANIC روی
checkpoint)، Redis (`MISCONF`) و خودِ `local-bot-api` («Can't create directories»)
هم‌زمان افتادند — یعنی `/start` هیچ جوابی نمی‌داد.

درختِ واقعیِ آن پوشه (`du` روی تولید) همین شکل را دارد:
`<root>/<token>/{td.binlog, videos/, documents/, temp/, photos/, …}`.
"""
from __future__ import annotations

import ast
import sys
import asyncio
import os
import time
from pathlib import Path

import pytest

from app import tg_janitor as J

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "8998852717:AAtest"
NOW = 1_800_000_000.0
H = 3600
MB = 1024 ** 2


def _put(path: Path, size: int, age_sec: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)                       # sparse: حجمِ منطقی بدونِ خرجِ دیسک
    os.utime(path, (NOW - age_sec, NOW - age_sec))
    return path


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    bot = tmp_path / TOKEN
    return {
        "root": tmp_path,
        "binlog": _put(bot / "td.binlog", 32 * 1024, 30 * 24 * H),      # قدیمی، ولی نشستِ ربات
        # فایلی کنارِ binlog با نامی که فیلترِ نام نمی‌شناسد: فقط قاعدهٔ **عمق** نجاتش می‌دهد.
        "token_file": _put(bot / "state.dat", MB, 30 * 24 * H),
        "root_file": _put(tmp_path / "stray.bin", MB, 30 * 24 * H),     # سطحِ ریشه
        "old_video": _put(bot / "videos" / "file_1.mp4", 900 * MB, 10 * H),
        "mid_video": _put(bot / "videos" / "file_2.mp4", 800 * MB, 3 * H),
        "new_video": _put(bot / "videos" / "file_3.mp4", 700 * MB, 5 * 60),
        "old_doc": _put(bot / "documents" / "file_4.pdf", 5 * MB, 20 * H),
        "old_temp": _put(bot / "temp" / "part_9", 50 * MB, 8 * H),
        "old_db": _put(bot / "videos" / "cache.sqlite", MB, 30 * 24 * H),
    }


def _big_free(_root: str) -> int:
    return 10 ** 15


# ── قاعدهٔ سن ────────────────────────────────────────────────────────────
def test_old_media_is_removed_and_the_session_is_kept(tree):
    res = J.sweep(str(tree["root"]), 6, 0, now=NOW, free_fn=_big_free)
    gone = {k for k, p in tree.items() if k != "root" and not p.exists()}
    assert gone == {"old_video", "old_doc", "old_temp"}
    assert res.files == 3
    assert res.bytes == (900 + 5 + 50) * MB


def test_the_bot_session_is_never_a_candidate_however_old(tree):
    """`td.binlog` کنارِ پوشه‌های رسانه است، نه داخلشان — و همین آن را نجات می‌دهد.

    دو دفاعِ مستقل دارد (عمق و نام)، پس هر کدام جدا سنجیده می‌شود: `state.dat`
    را فقط عمق نجات می‌دهد و `cache.sqlite`ِ داخلِ `videos/` را فقط نام —
    وگرنه سابوتاژِ یکی را دیگری می‌پوشاند.
    """
    J.sweep(str(tree["root"]), 1, 10 ** 6, now=NOW, free_fn=lambda _r: 0)
    assert tree["binlog"].exists()
    assert tree["token_file"].exists()              # فقط قاعدهٔ عمق
    assert tree["root_file"].exists()
    assert tree["old_db"].exists()                  # فقط قاعدهٔ نام


def test_age_zero_disables_the_age_rule(tree):
    res = J.sweep(str(tree["root"]), 0, 0, now=NOW, free_fn=_big_free)
    assert res.files == 0
    assert all(p.exists() for k, p in tree.items() if k != "root")


def test_a_file_written_in_the_guard_window_survives_a_tiny_max_age(tree):
    """حتی با «۱ ساعت»، فایلی که ۵ دقیقه پیش نوشته شده (دانلودِ در جریان) می‌ماند."""
    J.sweep(str(tree["root"]), 1, 0, now=NOW, free_fn=_big_free)
    assert tree["new_video"].exists()
    assert not tree["mid_video"].exists()


def test_a_symlink_is_neither_followed_nor_removed(tree, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "precious.mp4"
    _put(outside, MB, 30 * 24 * H)
    link = tree["root"] / TOKEN / "videos" / "link.mp4"
    link.symlink_to(outside)
    J.sweep(str(tree["root"]), 1, 0, now=NOW, free_fn=_big_free)
    assert outside.exists()
    assert link.is_symlink()


# ── قاعدهٔ کفِ فضای آزاد ──────────────────────────────────────────────────
def _disk(tree, capacity: int):
    """فضای آزاد = ظرفیت − حجمِ فایل‌های هنوز موجود؛ یعنی هر حذف واقعاً جا باز می‌کند."""
    files = [p for k, p in tree.items() if k != "root"]

    def free(_root: str) -> int:
        return capacity - sum(p.stat().st_size for p in files if p.exists())
    return free


def test_below_the_floor_the_oldest_go_first_and_it_stops_at_the_floor(tree):
    used = sum(p.stat().st_size for k, p in tree.items() if k != "root")
    free = _disk(tree, used + 200 * MB)              # ۲۰۰ مگ آزاد
    res = J.sweep(str(tree["root"]), 0, 1, now=NOW, free_fn=free)   # کف: ۱ گیگ
    # قدیمی‌ترین نامزدها به ترتیب: doc (۲۰h)، video_1 (۱۰h)، temp (۸h) — بعد از
    # حذفِ video_1 فضای آزاد ۱۱۰۵ مگ است و باید همان‌جا بایستد، نه temp را هم بخورد.
    assert not tree["old_doc"].exists()
    assert not tree["old_video"].exists()
    assert tree["old_temp"].exists() and tree["mid_video"].exists()
    assert res.files == 2
    assert res.free_after >= 1024 ** 3


def test_the_floor_never_touches_the_guard_window(tree):
    J.sweep(str(tree["root"]), 0, 10 ** 6, now=NOW, free_fn=lambda _r: 0)
    assert tree["new_video"].exists()
    assert not tree["mid_video"].exists()


def test_floor_zero_disables_the_floor_rule(tree):
    res = J.sweep(str(tree["root"]), 0, 0, now=NOW, free_fn=lambda _r: 0)
    assert res.files == 0


def test_a_missing_root_is_a_no_op(tmp_path):
    assert J.sweep(str(tmp_path / "nope"), 6, 10, now=NOW).files == 0


# ── وقتی دیسک پر است، DB و Redis هم خراب‌اند ─────────────────────────────
async def test_a_broken_settings_store_falls_back_to_the_defaults(tree, monkeypatch):
    """دیسکِ پر = Postgresِ PANIC و Redisِ MISCONF — و همان لحظه‌ای است که این سرویس لازم است."""
    async def boom(key, default):
        raise RuntimeError("could not write: No space left on device")
    monkeypatch.setattr(J.settings_store, "get_int", boom)
    monkeypatch.setattr(J.time, "time", lambda: NOW)
    monkeypatch.setattr(J, "_free_bytes", _big_free)   # کفِ پیش‌فرض به دیسکِ سندباکس بند نشود
    res = await J.run_once(str(tree["root"]))
    assert not tree["old_video"].exists()           # پیش‌فرضِ ۶ ساعت اعمال شد
    assert tree["mid_video"].exists()
    assert res.files == 3


async def test_a_hanging_settings_store_does_not_stall_the_sweep(tree, monkeypatch):
    async def hang(key, default):
        await asyncio.sleep(3600)
    monkeypatch.setattr(J.settings_store, "get_int", hang)
    monkeypatch.setattr(J, "_SETTINGS_TIMEOUT", 0.05)
    monkeypatch.setattr(J.time, "time", lambda: NOW)
    monkeypatch.setattr(J, "_free_bytes", _big_free)
    res = await asyncio.wait_for(J.run_once(str(tree["root"])), 5)
    assert res.files == 3


async def test_the_panel_values_are_what_the_sweep_uses(tree, monkeypatch):
    vals = {"tg_files_max_age_hours": 2, "tg_files_min_free_gb": 0}

    async def get_int(key, default):
        return vals[key]
    monkeypatch.setattr(J.settings_store, "get_int", get_int)
    monkeypatch.setattr(J.time, "time", lambda: NOW)
    await J.run_once(str(tree["root"]))
    assert not tree["mid_video"].exists()           # ۳ ساعته، با «۲ ساعت» پاک شد


# ── ثبت: پنل و compose ───────────────────────────────────────────────────
def test_both_keys_are_registered_for_the_panel():
    from app.settings_store import RUNTIME_KEYS
    assert RUNTIME_KEYS["tg_files_max_age_hours"][0] == "int"
    assert RUNTIME_KEYS["tg_files_min_free_gb"][0] == "int"
    src = (ROOT / "app" / "admin_web.py").read_text(encoding="utf-8")
    groups = next(ast.literal_eval(n.value) for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Assign)
                  and any(getattr(t, "id", "") == "GROUPS" for t in n.targets))
    keys = {row[0] for _t, rows in groups for row in rows}
    assert {"tg_files_max_age_hours", "tg_files_min_free_gb"} <= keys


def _services() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]


def _mounts_api_dir(svc: dict) -> list[str]:
    return [str(v) for v in svc.get("volumes", []) if str(v).startswith("tg-bot-api-data:")]


def test_the_janitor_service_runs_the_module_on_a_writable_mount():
    svc = _services()["tg-janitor"]
    assert svc["command"] == ["python", "-m", "app.tg_janitor"]
    assert _mounts_api_dir(svc) == ["tg-bot-api-data:/var/lib/telegram-bot-api"]
    assert J.ROOT == "/var/lib/telegram-bot-api"


def test_the_janitor_does_not_wait_for_a_healthy_database():
    """دیسکِ پر Postgres را unhealthy می‌کند؛ `depends_on: service_healthy` یعنی
    پاک‌کننده دقیقاً همان وقتی که لازم است بالا نمی‌آید."""
    assert "depends_on" not in _services()["tg-janitor"]


def test_only_the_server_and_the_janitor_may_write_the_api_dir():
    writers = sorted(name for name, svc in _services().items()
                     if any(not m.endswith(":ro") for m in _mounts_api_dir(svc)))
    assert writers == ["local-bot-api", "tg-janitor"]


def test_the_janitor_runs_in_the_lean_bot_image():
    """ایمیجِ ربات فقط `requirements.txt` دارد؛ ماژول نباید چیزِ دیگری import کند."""
    tree = ast.parse((ROOT / "app" / "tg_janitor.py").read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
    # کشف‌محور، نه فهرستِ دستی: «فقط کتابخانهٔ استاندارد» همان ادعاست، و فهرستِ دستی
    # با افزودنِ `json` (گزارشِ `janitor:last` برای پنل) بی‌دلیل قرمز شد.
    extra = mods - set(sys.stdlib_module_names)
    assert not extra, f"tg_janitor بیرون از کتابخانهٔ استاندارد import می‌کند: {sorted(extra)}"
    assert _services()["tg-janitor"]["build"]["dockerfile"] == "docker/bot.Dockerfile"
