"""فاز ۳ / موردِ ۲۶ — ظرفِ خروجیِ ویرایشِ تگ از کدک می‌آید، نه از نامِ فایل.

پیش از رفع `meta_write` پسوند را از `file.name` می‌گرفت و `-c copy` می‌زد. سه
شکستِ اجراشده با ffmpegِ واقعی:

    voice note (Opus، بی‌نام)  → `.mp3`  → «Exactly one MP3 audio stream is required»
    AACِ بی‌نام                 → `.mp3`  → همان
    «Mr. Brightside» (بی‌پسوند) → `. Brightside` → «Unable to choose an output format»

و یک شکلِ چهارم که بعد از رفعِ پسوند خودش را نشان داد: ظرفِ ogg کاورِ تصویری
نمی‌پذیرد («Unsupported codec id in stream 1»)، پس کاور روی Opus/Vorbis یک
رمزگذاریِ دوباره لازم دارد.

هارنس `_do_op`ِ واقعی است با `File`ِ ساخته‌شده در حافظه، نه صدا زدنِ مستقیمِ
`write_audio_metadata` — چون باگ دقیقاً در **اتصال** بود (پسوند را فراخوان حدس
می‌زد)، و تستی که فقط تابعِ پایین‌دست را بزند روی سورسِ قبل هم می‌توانست سبز بماند.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest
from PIL import Image

from app import tasks as T
from app.models import File

needs_ffmpeg = pytest.mark.ffmpeg

SOURCES = {
    "voice-opus": (["-c:a", "libopus"], "ogg", None),          # voice note: نام ندارد
    "aac-nameless": (["-c:a", "aac"], "m4a", None),
    "mp3-dotted-title": (["-c:a", "libmp3lame"], "mp3", "Mr. Brightside"),
    "vorbis": (["-c:a", "libvorbis"], "ogg", "song.ogg"),
    "wav": ([], "wav", "take.wav"),
}


def _src(tmp_path, key) -> tuple[str, str | None]:
    codec, ext, name = SOURCES[key]
    path = tmp_path / f"in.{ext}"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=1", *codec, str(path)],
                   check=True, capture_output=True, timeout=120)
    return str(path), name


def _probe(path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,codec_type:stream_disposition=attached_pic:stream_tags:format_tags",
         "-of", "json", str(path)], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def _title(info: dict) -> str | None:
    """تگِ سراسری (mp3/m4a/flac) یا تگِ **استریمِ صوت** (vorbis comment در ogg) —
    نه استریمِ کاور، که عنوانِ خودش («Album cover») را دارد."""
    tags = dict((info.get("format") or {}).get("tags") or {})
    for st in info.get("streams") or []:
        if st.get("codec_type") == "audio":
            tags = {**(st.get("tags") or {}), **tags}
    return {k.lower(): v for k, v in tags.items()}.get("title")


class Bot:
    """`meta_write` با کاور `_localize` را صدا می‌زند؛ این‌جا مسیرِ محلی برمی‌گردد."""

    def __init__(self, cover: str | None = None) -> None:
        self.cover = cover


async def _meta_write(tmp_path, monkeypatch, key, cover: bool):
    src, name = _src(tmp_path, key)
    cover_path = None
    if cover:
        cover_path = str(tmp_path / "cover.jpg")
        Image.new("RGB", (32, 32), (200, 10, 10)).save(cover_path)

    async def localize(bot, fid, workdir, subdir="in"):
        return cover_path
    monkeypatch.setattr(T, "_localize", localize)
    f = File(ref="r", owner_id=1, file_unique_id="u", file_id="f", kind="audio", name=name)
    work = tmp_path / "work"
    work.mkdir()
    args = {"tags": {"title": "Tagged Title", "artist": "A"}}
    if cover:
        args["cover_id"] = "cover-file-id"
    return await T._do_op(Bot(), "meta_write", args, f, src, str(work), "fa")


@needs_ffmpeg
@pytest.mark.parametrize("key", sorted(SOURCES), ids=sorted(SOURCES))
async def test_tags_are_written_without_a_cover(tmp_path, monkeypatch, key):
    res = await _meta_write(tmp_path, monkeypatch, key, cover=False)
    info = _probe(res["path"])
    assert _title(info) == "Tagged Title", info
    assert os.path.splitext(res["filename"])[1] == os.path.splitext(res["path"])[1], \
        "نامِ تحویلی باید پسوندِ ظرفِ واقعی را داشته باشد"


@needs_ffmpeg
@pytest.mark.parametrize("key", sorted(SOURCES), ids=sorted(SOURCES))
async def test_a_cover_is_embedded_whatever_the_source(tmp_path, monkeypatch, key):
    res = await _meta_write(tmp_path, monkeypatch, key, cover=True)
    info = _probe(res["path"])
    pics = [s for s in info["streams"] if (s.get("disposition") or {}).get("attached_pic")]
    assert pics, f"{key}: کاور جاسازی نشد — {info}"
    assert _title(info) == "Tagged Title"


@needs_ffmpeg
async def test_a_copyable_source_is_not_reencoded(tmp_path, monkeypatch):
    """کنترل: AAC با کاور همان AAC می‌ماند (کپی)، نه mp3 — رمزگذاری فقط وقتی لازم است."""
    res = await _meta_write(tmp_path, monkeypatch, "aac-nameless", cover=True)
    codecs = {s["codec_name"] for s in _probe(res["path"])["streams"]
              if s["codec_type"] == "audio"}
    assert codecs == {"aac"}, codecs
    assert res["path"].endswith(".m4a")


@needs_ffmpeg
async def test_a_lossless_source_stays_lossless_with_a_cover(tmp_path, monkeypatch):
    """wav ظرفی برای کاور ندارد؛ «ویرایشِ تگ» نباید بی‌صدا به mp3 افت کند."""
    res = await _meta_write(tmp_path, monkeypatch, "wav", cover=True)
    codecs = {s["codec_name"] for s in _probe(res["path"])["streams"]
              if s["codec_type"] == "audio"}
    assert codecs == {"flac"}, codecs


@pytest.mark.parametrize("name,stem", [
    ("Mr. Brightside", "Mr._Brightside"),
    ("Track 01. Intro", "Track_01._Intro"),
    ("song.mp3", "song"),
    ("dir/inner.m4a", "inner"),
    (None, "file"),
], ids=["dotted-title", "numbered-title", "real-ext", "path", "none"])
def test_only_a_real_extension_is_stripped(name, stem):
    assert T._safe_stem(name) == stem
