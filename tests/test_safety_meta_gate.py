"""رگرسیونِ لایهٔ ۲ فیلترِ محتوای بزرگسال (متادیتا).

دو باگ:
۱) `normalize_probe` فقط `{title, duration, kind, thumbnail, options}` می‌داد، پس
   در فازِ probe شرطِ `age_limit>=18` — ارزان‌ترین و قوی‌ترین سیگنالِ ما — هرگز
   شلیک نمی‌کرد و لایهٔ ۲ عملاً به کلیدواژهٔ «عنوان» تقلیل می‌یافت.
۲) پیش‌فرضِ `dl_default_ux` برابرِ `quick` است، یعنی probe اصلاً اجرا نمی‌شود و
   گیتِ متادیتا فقط **بعد از** دانلود می‌آمد. رفع: `--match-filter age_limit<?18`
   روی همان فراخوانیِ دانلود — yt-dlp بعد از استخراج و قبل از کشیدنِ بایت‌های
   رسانه رد می‌کند (صفر رفت‌وبرگشتِ اضافه، صفر مصرفِ اضافه از سهمیهٔ اکانت).

`yt-dlp`ِ جعلی یک اسکریپتِ **واقعی** روی PATH است؛ زیرفرایند واقعاً اجرا می‌شود.
"""
from __future__ import annotations

import json
import os
import stat
import textwrap

import pytest

from app import downloader as D
from app import safety

# ── نمونهٔ واقع‌گرایانهٔ خروجیِ ‎-J ─────────────────────────────
BASE_J = {
    "id": "abc123", "title": "A perfectly ordinary clip", "duration": 212,
    "height": 720, "vcodec": "avc1",     # ‎-J این‌ها را در سطحِ بالا هم می‌دهد
    "thumbnail": "https://example.com/t.jpg", "uploader": "Some Channel",
    "channel": "Some Channel", "description": "just a normal description",
    "formats": [
        {"height": 720, "vcodec": "avc1", "acodec": "none", "tbr": 1500},
        {"height": None, "vcodec": "none", "acodec": "mp4a", "tbr": 128},
    ],
}


# ── (۱) normalize_probe باید متادیتای ایمنی را حمل کند ──────────
def test_probe_output_carries_age_limit():
    """قبل از رفع: `check_meta` روی خروجیِ probe همیشه None می‌داد."""
    norm = D.normalize_probe({**BASE_J, "age_limit": 18})
    assert norm.get("age_limit") == 18
    assert safety.check_meta(norm) == "age_limit:18"


def test_probe_output_without_age_limit_passes():
    """اکثریتِ قاطعِ ویدیوها `age_limit` ندارند — نباید مسدود شوند."""
    norm = D.normalize_probe(BASE_J)
    assert "age_limit" not in norm
    assert safety.check_meta(norm) is None


def test_probe_output_carries_description_and_tags():
    norm = D.normalize_probe({**BASE_J, "description": "hardcore porn video",
                              "tags": ["x", "y"], "categories": ["Film"]})
    assert norm["tags"] == ["x", "y"] and norm["categories"] == ["Film"]
    assert safety.check_meta(norm) is not None      # از توضیحات گرفته شد


def test_probe_output_caps_oversized_fields():
    """متادیتا نباید dictِ درون‌حافظه‌ای را متورم کند."""
    norm = D.normalize_probe({**BASE_J, "description": "x" * 9000,
                              "tags": [f"t{i}" for i in range(500)],
                              "categories": [f"c{i}" for i in range(500)]})
    assert len(norm["description"]) == 2000
    assert len(norm["tags"]) == 40 and len(norm["categories"]) == 20


def test_probe_keeps_its_existing_shape():
    """رفع نباید مصرف‌کننده‌های امروزیِ probe را بشکند."""
    norm = D.normalize_probe(BASE_J)
    assert norm["title"] == "A perfectly ordinary clip"
    assert norm["duration"] == 212 and norm["kind"] == "video"
    assert norm["thumbnail"] == "https://example.com/t.jpg"
    assert [o["sel"] for o in norm["options"]] == ["720"]


# ── (۲) گیتِ سنی روی خودِ فراخوانیِ دانلود ──────────────────────
_FAKE_YTDLP = r'''#!/usr/bin/env python3
"""yt-dlpِ جعلی: argv را می‌نویسد و رفتارِ واقعیِ --match-filter را تقلید می‌کند."""
import json, os, sys

argv = sys.argv[1:]
with open(os.environ["FAKE_ARGV"], "w") as fh:
    json.dump(argv, fh)

mf = argv[argv.index("--match-filter") + 1] if "--match-filter" in argv else None
title = os.environ.get("FAKE_TITLE", "clip")
age = os.environ.get("FAKE_AGE")        # خالی = extractor اصلاً ست نکرده

if mf:
    # yt-dlp: مقایسهٔ ساده روی فیلدِ غایب False می‌دهد؛ `<?` غیبت را «قبول» می‌کند.
    field, _, rest = mf.partition("<")
    optional = rest.startswith("?")
    limit = int(rest.lstrip("?"))
    if age is None or age == "":
        passes = optional
    else:
        passes = int(age) < limit
    if not passes:
        print("[download] %s does not pass filter (%s), skipping .." % (title, mf))
        sys.exit(0)

out = os.environ["FAKE_OUT"]
open(os.path.join(out, "clip.mp3"), "wb").write(b"ID3fake-audio")
with open(os.path.join(out, "clip.info.json"), "w") as fh:
    json.dump({"title": title, "duration": 5, **({"age_limit": int(age)} if age else {})}, fh)
print("dl:100.0%")
'''


@pytest.fixture
def fake_ytdlp(tmp_path, monkeypatch):
    """`yt-dlp`ِ اجراییِ واقعی روی PATH."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "yt-dlp"
    script.write_text(textwrap.dedent(_FAKE_YTDLP))
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_ARGV", str(argv_file))
    monkeypatch.setenv("FAKE_OUT", str(tmp_path))
    return argv_file


def _argv(argv_file) -> list[str]:
    with open(argv_file) as fh:
        return json.load(fh)


async def test_match_filter_uses_the_optional_comparison(fake_ytdlp, tmp_path):
    """باید `age_limit<?18` باشد نه `age_limit<18`.

    در yt-dlp مقایسهٔ عددی روی فیلدِ **غایب** False می‌دهد، پس فرمِ بدونِ `?` هر
    ویدیویی را که extractor برایش age_limit ست نکرده رد می‌کرد.
    """
    await D.download_ytdlp("https://x.test/v", str(tmp_path), "audio",
                           {"max_age_limit": 18})
    argv = _argv(fake_ytdlp)
    assert "--match-filter" in argv
    assert argv[argv.index("--match-filter") + 1] == "age_limit<?18"


async def test_video_without_age_limit_downloads_normally(fake_ytdlp, tmp_path, monkeypatch):
    """گیتِ سنی نباید مسیرِ عادی را ببندد — این همان رگرسیونی است که `<` می‌ساخت."""
    monkeypatch.delenv("FAKE_AGE", raising=False)
    path, info, _thumb = await D.download_ytdlp(
        "https://x.test/v", str(tmp_path), "audio", {"max_age_limit": 18})
    assert path.endswith(".mp3") and os.path.exists(path)
    assert info["title"] == "clip"


async def test_under_age_limit_downloads_normally(fake_ytdlp, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_AGE", "0")
    path, _info, _thumb = await D.download_ytdlp(
        "https://x.test/v", str(tmp_path), "audio", {"max_age_limit": 18})
    assert os.path.exists(path)


async def test_age_restricted_video_is_rejected_before_any_media_byte(
        fake_ytdlp, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_AGE", "18")
    with pytest.raises(D.AgeRestricted):
        await D.download_ytdlp("https://x.test/v", str(tmp_path), "audio",
                               {"max_age_limit": 18})
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".mp3")], \
        "هیچ بایتِ رسانه‌ای نباید نوشته شده باشد"


async def test_no_match_filter_when_safety_is_off(fake_ytdlp, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_AGE", "18")
    path, _info, _thumb = await D.download_ytdlp(
        "https://x.test/v", str(tmp_path), "audio", {"max_age_limit": 0})
    assert "--match-filter" not in _argv(fake_ytdlp)
    assert os.path.exists(path)


async def test_ordinary_failure_is_not_reported_as_age_restriction(tmp_path, monkeypatch):
    """خطای معمولیِ موتور نباید به‌عنوان «محتوای سنی» به کاربر گفته شود."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "yt-dlp"
    script.write_text("#!/bin/sh\necho 'ERROR: Video unavailable' >&2\nexit 1\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    with pytest.raises(RuntimeError, match="Video unavailable"):
        await D.download_ytdlp("https://x.test/v", str(tmp_path), "audio",
                               {"max_age_limit": 18})
