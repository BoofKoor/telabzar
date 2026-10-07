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


@pytest.mark.skipif(shutil.which("find") is None, reason="needs GNU find")
def test_the_filesystem_sections_count_files_per_day(tmp_path):
    tg = tmp_path / "tg"
    vids = tg / "TOK" / "videos"
    vids.mkdir(parents=True)
    (tg / "TOK" / "td.binlog").write_bytes(b"x")
    stamp = calendar.timegm(time.strptime("2026-10-04 13:30", "%Y-%m-%d %H:%M"))
    for i, size in enumerate((3000, 5000)):
        f = vids / f"file_{i}.mp4"
        f.write_bytes(b"\0" * size)
        os.utime(f, (stamp, stamp))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f'#!/bin/sh\n[ "$1 $2" = "volume inspect" ] && echo {tg}\nexit 0\n')
    docker.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "out.txt"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "TLZ_DIR": str(repo),
           "OUT": str(out), "TMPDIR": str(tmp_path), "PSQL": "cat"}
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True, timeout=60)
    text = out.read_text()

    assert re.search(r"== TOK/videos/\n\s+2026-10-04\s+2 files", text), text
    assert re.search(r"### 5\..*\n\s+2 13\n", text), text           # ساعتِ ۱۳ UTC
    assert "files on disk: 2" in text
    # بخشِ ۷ واقعاً دادهٔ فایل‌ها را به psql می‌دهد (این‌جا `cat` همان را چاپ می‌کند).
    assert re.search(r"COPY fs FROM STDIN;\n3000\t", text) or re.search(r"\n5000\t", text), text
