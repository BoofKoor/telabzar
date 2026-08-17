"""کاورِ صوتی: جاسازی در فایل، و **نخوردنِ** بردِ بدونِ ترنسکدِ #۱۱۵.

**علامت.** خطِ فرمانِ تولید `--write-thumbnail --convert-thumbnails jpg` داشت
(یعنی کاور دانلود می‌شد و روی دیسک می‌نشست) و `--embed-metadata` داشت، ولی
`--embed-thumbnail` **نداشت**. `--embed-metadata` فقط تگِ متنی می‌نویسد، پس
تصویر دانلود می‌شد و دور ریخته می‌شد: کاربر MP3 را ذخیره می‌کرد و در پخش‌کننده
تصویری نمی‌دید.

**چرا فقط مسیرِ صوت، و چرا این قیدِ سخت است نه احتیاط.** `EmbedThumbnailPP`
برای پسوندی که پشتیبانی نمی‌کند `PostProcessingError` می‌دهد
(`ogg/opus/flac` بدونِ mutagen، و هر پسوندِ ناشناخته بی‌قیدوشرط)، و چون
`--ignore-errors` نمی‌فرستیم، `YoutubeDL.run_pp` دوباره raise می‌کند و **کلِ
دانلود می‌شکند**. مسیرِ ویدیو روی منبعِ فقط‌صوتی می‌تواند دقیقاً همان پسوندها
را بدهد — کد خودش برایش fallback دارد. پس گیت روی `audio_only` جلوی یک شکستِ
**پرصدا** را می‌گیرد، نه یک زشتیِ کوچک.

**و بردِ #۱۱۵ نباید بی‌صدا از دست برود.** ساندکلاود از انتخابگرِ #۱۱۵ فایلِ
mp3ِ آماده می‌گیرد و `--audio-format mp3` آن را **ترنسکد نمی‌کند**
(«Not converting audio … already in target format mp3»). جاسازیِ کاور برای mp3
هم در `EmbedThumbnailPP` مستقیم ffmpeg با `-c copy` است، پس فقط یک استریمِ
تصویر اضافه می‌شود. `test_an_mp3_input_is_never_transcoded` همین را قفل می‌کند.

**هارنس، و چرا کنترلِ منفی‌اش پیش‌شرطِ اعتبار است.** `_extract_decision` خودِ
`FFmpegExtractAudioPP`ِ yt-dlp را اجرا می‌کند و فقط **ffprobe** را جعل می‌کند
(یعنی «چه کدکی در فایل است») — نه خودِ تصمیم را؛ همان الگوی فهرستِ فرمتِ #۱۱۵.
بدونِ کنترلِ منفی، «ffmpeg صدا زده نشد» می‌تواند معنیِ «هارنس اصلاً کار نمی‌کند»
بدهد و سبزش بی‌معنا باشد — دقیقاً همان false failی که یک‌بار با
`incomplete_formats`ِ هاردکدشده رخ داد. پس
`test_the_harness_can_tell_a_transcode_from_a_copy` اول می‌آید.
"""
from __future__ import annotations

import os

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP

from app import downloader as D


def _cmd(selector: str, platform_url: str = "https://castbox.fm/ep/798014224") -> list[str]:
    """خطِ فرمانِ **واقعیِ** تولید، از خودِ `download_ytdlp`.

    عمداً بازسازی نمی‌شود: یک کپیِ دست‌نویس روزی که سورس عوض شود ساکت می‌ماند
    (همان درسِ `remove_cookie_file`). به‌جایش `_run_dl` وصله می‌خورد و `cmd`
    ضبط می‌شود.
    """
    import asyncio

    captured: list[list[str]] = []

    async def fake_run_dl(cmd, progress=None, cancel=None, timeout=0):
        captured.append(list(cmd))
        raise RuntimeError("stopped after building the command")

    real = D._run_dl
    D._run_dl = fake_run_dl
    try:
        asyncio.run(D.download_ytdlp(platform_url, "/tmp/nope", selector, {}))
    except Exception:  # noqa: BLE001 — فقط خطِ فرمان را می‌خواهیم
        pass
    finally:
        D._run_dl = real
    assert captured, "خطِ فرمان ساخته نشد — هارنس دیگر چیزی را که فکر می‌کند نمی‌سنجد."
    return captured[0]


def _extract_decision(src_ext: str, src_acodec: str, tmp_path) -> dict:
    """تصمیمِ codecِ `FFmpegExtractAudioPP`ِ **واقعی**، بدونِ اجرای ffmpeg.

    فقط `get_audio_codec` (یعنی ffprobe) جعل می‌شود. خروجی خالی = هیچ
    فراخوانیِ ffmpegی نشد = فایل دست‌نخورده ماند.
    """
    src = tmp_path / f"x.{src_ext}"
    src.write_bytes(b"\0" * 16)
    pp = FFmpegExtractAudioPP(YoutubeDL({"quiet": True}), preferredcodec="mp3")
    seen: dict = {}
    pp.get_audio_codec = lambda path: src_acodec
    def fake_run_ffmpeg(path, out_path, codec, more_opts):
        seen["codec"] = codec
        (tmp_path / os.path.basename(out_path)).write_bytes(b"\0")
    pp.run_ffmpeg = fake_run_ffmpeg
    pp.run({"filepath": str(src), "ext": src_ext})
    return seen


# ── ۰) اعتبارِ هارنس — پیش‌شرطِ همه‌چیزِ زیرین ───────────────────────
def test_the_harness_can_tell_a_transcode_from_a_copy(tmp_path):
    """**کنترلِ منفیِ اجباری.**

    بدونِ این، سبزیِ `test_an_mp3_input_is_never_transcoded` می‌تواند صرفاً
    یعنی «هارنس هیچ‌وقت ffmpeg را صدا نمی‌زند» — یک بنچِ مرده که از بیرون
    شبیهِ موفقیت است.
    """
    assert _extract_decision("m4a", "aac", tmp_path).get("codec") == "libmp3lame", \
        "هارنس ترنسکدِ واقعی را هم نمی‌بیند — هر عددی که بدهد بی‌معناست."


# ── ۱) بردِ #۱۱۵ دست‌نخورده ──────────────────────────────────────────
def test_an_mp3_input_is_never_transcoded(tmp_path):
    """ساندکلاود از انتخابگرِ #۱۱۵ mp3ِ آماده می‌گیرد؛ نباید دوباره انکد شود."""
    assert _extract_decision("mp3", "mp3", tmp_path) == {}, \
        "فایلِ mp3 دوباره انکد شد — بردِ #۱۱۵ از دست رفت."


def test_the_audio_extraction_flags_are_unchanged():
    cmd = _cmd("audio")
    assert "-x" in cmd
    i = cmd.index("--audio-format")
    assert cmd[i + 1] == "mp3"


# ── ۲) فلگ هست، و **فقط** روی مسیرِ صوت ─────────────────────────────
def test_the_audio_path_embeds_the_cover():
    assert "--embed-thumbnail" in _cmd("audio"), \
        "کاور جاسازی نمی‌شود — کاربر MP3 را بدونِ تصویر ذخیره می‌کند."


@pytest.mark.parametrize("selector", [
    pytest.param("best", id="best"),
    pytest.param("720", id="height-720"),
    pytest.param("1080", id="height-1080"),
])
def test_the_video_path_never_embeds(selector):
    """قیدِ سخت: مسیرِ ویدیو روی منبعِ فقط‌صوتی `opus`/`webm` می‌دهد، و
    `EmbedThumbnailPP` آن‌جا raise می‌کند → با نبودِ `--ignore-errors` کلِ
    دانلود می‌شکند."""
    assert "--embed-thumbnail" not in _cmd(selector)


def test_we_do_not_pass_ignore_errors():
    """پایهٔ استدلالِ بالا. اگر روزی `--ignore-errors` اضافه شد، شکستِ embed از
    «دانلودِ شکسته» به «خطای بی‌صدا» تبدیل می‌شود و این گیت باید بازبینی شود."""
    for sel in ("audio", "best"):
        cmd = _cmd(sel)
        assert "--ignore-errors" not in cmd and "-i" not in cmd


# ── ۳) کاور همچنان روی دیسک می‌ماند (کارت به آن تکیه دارد) ───────────
def test_the_thumbnail_is_still_written_to_disk():
    """`already_have_thumbnail = opts.writethumbnail` در yt-dlp یعنی با
    `--write-thumbnail` فایلِ jpg بعد از جاسازی **پاک نمی‌شود** — و
    `_newest(workdir, (".jpg", ".jpeg"))` همان را برای کارت برمی‌دارد."""
    cmd = _cmd("audio")
    assert "--write-thumbnail" in cmd
    i = cmd.index("--convert-thumbnails")
    assert cmd[i + 1] == "jpg"


def test_a_stray_jpg_cannot_be_picked_as_the_media_file(tmp_path):
    """`_newest` با **پسوند** فیلتر می‌کند، پس jpgِ کنارِ فایل رسانه شمرده
    نمی‌شود. محتمل‌ترین جای شکستنِ خاموش، و بسته است."""
    (tmp_path / "cover.jpg").write_bytes(b"\0")
    (tmp_path / "track.mp3").write_bytes(b"\0")
    got = D._newest(str(tmp_path), (".mp3", ".m4a", ".opus", ".ogg", ".wav"))
    assert got and got.endswith("track.mp3")
    assert D._newest(str(tmp_path), (".jpg", ".jpeg")).endswith("cover.jpg")


# ── ۴) کنترل: بقیهٔ خطِ فرمان دست‌نخورده ─────────────────────────────
def test_the_rest_of_the_command_is_unchanged():
    cmd = _cmd("audio")
    for flag in ("--embed-metadata", "--write-info-json", "--newline", "--no-playlist"):
        assert flag in cmd


def test_the_video_path_keeps_its_mp4_guarantees():
    cmd = _cmd("best")
    assert "--merge-output-format" in cmd and cmd[cmd.index("--merge-output-format") + 1] == "mp4"
    assert "-S" in cmd
