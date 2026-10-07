"""`tools/tg_disk_diag.sh` — ابزارِ تشخیصِ «چرا پوشهٔ سرورِ تلگرام پر شد».

روی **سرورِ تولید** اجرا می‌شود، پس ادعای «فقط خواندن» باید گارد داشته باشد نه
قول: هیچ فرمانِ پاک‌کننده/تغییردهنده‌ای (rm، `-delete`، `DELETE/UPDATE/DROP`،
`docker compose up/down/stop`) نباید واردش شود. گارد کامنت‌ها را **اول** دور
می‌ریزد — درسِ §۶: گاردی که متنِ خودِ فایل را می‌خواند سرانجام توضیحاتِ خودش را
می‌شمارد.
"""
from __future__ import annotations

import calendar
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "tg_disk_diag.sh"

_MUTATING = [
    r"\brm\b", r"-delete\b", r"\btruncate\b", r"\bmv\b",
    r"\b(DELETE|UPDATE|DROP|TRUNCATE|INSERT|ALTER)\b",
    r"docker\s+compose\s+(up|down|stop|restart|rm|kill|pull|build)\b",
    r"docker\s+(rm|kill|stop|restart|system\s+prune|volume\s+rm|image\s+rm)\b",
    r"\bredis-cli\b",
]


def _code_lines(src: str) -> list[str]:
    return [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]


def test_the_script_parses():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_the_script_is_read_only():
    code = "\n".join(_code_lines(SCRIPT.read_text(encoding="utf-8")))
    hits = [p for p in _MUTATING if re.search(p, code, re.IGNORECASE)]
    assert not hits, f"tg_disk_diag.sh must stay read-only — matched {hits}"


def test_the_guard_ignores_comments_but_not_code():
    """کنترلِ خودارجاعی: واژهٔ ممنوع در کامنت شمرده نشود، در کد بشود."""
    assert not any(re.search(p, "\n".join(_code_lines("# never rm or DELETE here\necho ok")), re.I)
                   for p in _MUTATING)
    assert any(re.search(p, "\n".join(_code_lines("echo ok\nrm -f /x")), re.I) for p in _MUTATING)


def test_the_script_has_no_persian_for_the_server_terminal():
    assert not re.search(r"[؀-ۿ]", SCRIPT.read_text(encoding="utf-8"))


TOKEN = "1234567890:AAH" + "x" * 32          # شکلِ واقعیِ نامِ پوشهٔ سرور
MB = 1024 * 1024


def _at(when: str) -> int:
    return calendar.timegm(time.strptime(when, "%Y-%m-%d %H:%M"))


def _fake_tg(tmp_path: Path) -> Path:
    """پوشهٔ سرور با دو ویدیو و یک سند؛ فایل‌ها sparse‌اند تا حجمِ واقعی (بالای
    آستانهٔ ۵۰ مگِ بخشِ ۷) بدونِ نوشتنِ بایت ساخته شود."""
    tg = tmp_path / "tg"
    for typ, name, size, when in (("videos", "file_0.mp4", 60 * MB, "2026-10-04 13:30"),
                                  ("videos", "file_1.mp4", 70 * MB, "2026-10-04 13:45"),
                                  ("documents", "file_2.zip", 80 * MB, "2026-10-05 02:10")):
        d = tg / TOKEN / typ
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        with open(f, "wb") as fh:
            fh.truncate(size)
        os.utime(f, (_at(when), _at(when)))
    (tg / TOKEN / "td.binlog").write_bytes(b"x")
    return tg


# لاگِ ورکر با یک بایتِ NUL پیش از خطِ جاب — بدونِ `grep -a`، GNU grep بعد از
# آن فقط «binary file matches» می‌دهد و هر خطِ بعدی را جا می‌اندازد.
_WORKER_LOG = ("2026-10-04T13:00:00.1Z noise\x00here\n"
               "2026-10-04T20:05:00.1Z 20:05:00:   0.40s → abc:run_screen("
               "{'file_id_row': 7, 'chat_id': 123456789, 'note_mid': 3})\n"
               "2026-10-05T01:10:00.1Z 01:10:00:   0.10s → def:run_op(41, 555501234, 9, 'fa')\n")


def _run(tmp_path: Path, tg: Path, *args: str, **extra: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp_path / "worker.log").write_text(_WORKER_LOG)
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f'case "$*" in *Mountpoint*) echo {tg} ;;\n'
        f'  *logs*worker*) cat {tmp_path / "worker.log"} ;; esac\n'
        "exit 0\n")
    docker.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "TLZ_DIR": str(repo),
           "OUT": str(tmp_path / "out.txt"), "TMPDIR": str(tmp_path), "PSQL": "cat", **extra}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, check=True,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(shutil.which("find") is None, reason="needs GNU find")
def test_the_report_counts_files_per_day_and_hour(tmp_path):
    _run(tmp_path, _fake_tg(tmp_path))
    text = (tmp_path / "out.txt").read_text()

    assert re.search(r"videos\s+2026-10-04\s+2 files", text), text
    assert re.search(r"documents\s+2026-10-05\s+1 files", text), text
    assert re.search(r"--- 2026-10-04 .*\n\s+2\s+videos 13\b", text), text   # ساعتِ ۱۳ UTC
    assert "files listed: 3" in text
    # بخشِ ۷ دادهٔ فایل‌ها را با نوعشان به psql می‌دهد (این‌جا `cat` همان را چاپ می‌کند).
    copied = text.split("COPY fs FROM STDIN;\n", 1)[1].split("\\.", 1)[0]
    assert re.search(rf"^{60 * MB}\t[0-9.]+\tvideos$", copied, re.M), copied
    assert re.search(rf"^{80 * MB}\t[0-9.]+\tdocuments$", copied, re.M), copied


@pytest.mark.skipif(shutil.which("find") is None, reason="needs GNU find")
def test_the_bot_token_never_reaches_the_report(tmp_path):
    """نامِ پوشهٔ سرور خودِ توکنِ ربات است و گزارش را کاربر جایی می‌چسباند."""
    _run(tmp_path, _fake_tg(tmp_path))
    text = (tmp_path / "out.txt").read_text()
    assert TOKEN not in text and TOKEN.split(":")[1] not in text
    assert "<bot>" in text      # کنترل: مسیر واقعاً چاپ شد، فقط پوشانده شد


@pytest.mark.skipif(shutil.which("grep") is None, reason="needs grep")
def test_a_nul_byte_in_the_logs_does_not_hide_later_jobs(tmp_path):
    _run(tmp_path, _fake_tg(tmp_path))
    text = (tmp_path / "out.txt").read_text()
    assert "binary file matches" not in text
    assert re.search(r"1 run_screen 20\b", text), text
    assert re.search(r"1 2026-10-04 chat \.\.6789", text), text
    assert re.search(r"1 2026-10-05 chat \.\.1234", text), text


@pytest.mark.skipif(shutil.which("find") is None, reason="needs GNU find")
def test_a_saved_list_stands_in_for_deleted_files(tmp_path):
    """فهرستِ ذخیره‌شده کافی است: بعد از پاک‌کردنِ فایل‌ها همان شمارش‌ها درمی‌آید."""
    tg = _fake_tg(tmp_path)
    saved = tmp_path / "saved.tsv"
    r = _run(tmp_path, tg, "--save-list", str(saved))
    assert "saved 3 files" in r.stdout
    assert not (tmp_path / "out.txt").exists()           # فقط فهرست، نه گزارش

    empty = tmp_path / "empty"
    (empty / TOKEN / "videos").mkdir(parents=True)
    _run(tmp_path, empty, FS_LIST=str(saved))
    text = (tmp_path / "out.txt").read_text()
    assert "files listed: 3" in text
    assert re.search(r"videos\s+2026-10-04\s+2 files", text), text


def test_a_legacy_two_column_list_is_read_as_videos(tmp_path):
    legacy = tmp_path / "legacy.tsv"
    legacy.write_text(f"{60 * MB}\t{_at('2026-10-04 21:00')}.0\n")
    empty = tmp_path / "empty"
    (empty / TOKEN).mkdir(parents=True)
    _run(tmp_path, empty, FS_LIST=str(legacy))
    text = (tmp_path / "out.txt").read_text()
    assert re.search(r"videos\s+2026-10-04\s+1 files", text), text
    assert re.search(r"\n\s+1\s+videos 21\b", text), text
