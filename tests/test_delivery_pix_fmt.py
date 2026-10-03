"""فاز ۳ / موردِ ۱۱ — خروجیِ برش/تبدیل/واترمارک باید 4:2:0ِ ۸بیتی باشد.

`compress_video` همیشه `-pix_fmt yuv420p` داشت؛ سه تابعِ دیگری که ویدیو را
دوباره رمزگذاری می‌کنند نداشتند. ffmpeg فرمتِ پیکسلِ منبع را نگه می‌دارد، پس
HEVCِ ۱۰بیتیِ آیفون بعد از برش H.264ِ «High 10» می‌شد و webm، VP9ِ Profile 2 —
فایلی که بیشترِ پخش‌کننده‌ها باز نمی‌کنند.

منبع با **ffv1** ساخته می‌شود (انکودرِ داخلیِ خودِ ffmpeg، پس به build با
libx265 یا x264ِ ۱۰بیتی بند نیست) و خروجی با ffprobeِ واقعی خوانده می‌شود.

منبعِ دوم (۴:۴:۴ با ابعادِ **فرد**) دو کار می‌کند. روی سورسِ پیش از رفع می‌افتد
چون خروجی ۴:۴:۴ می‌ماند («High 4:4:4 Predictive»، همان‌قدر ناسازگار) — و این
تنها حالتی است که واترمارک هم خراب بود: `overlay` روی منبعِ ۴:۲:۰ِ ۱۰بیتی خودش
۸بیتی می‌دهد (اندازه‌گیری‌شده، پس آن یک خانه پیش از رفع هم سبز است). و رفعِ
**نصفه** را می‌گیرد: `-pix_fmt yuv420p`ِ خالی روی ابعادِ فرد libx264 را می‌شکند
(«width not divisible by 2») در حالی که همان فایل پیش از رفع دست‌کم انکود می‌شد.
"""
from __future__ import annotations

import ast
import inspect
import json
import subprocess

import pytest
from PIL import Image

from app import processing as P

needs_ffmpeg = pytest.mark.ffmpeg


def _src(path, size: str, pix_fmt: str) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration=2",
         "-f", "lavfi", "-i", "sine=duration=2", "-shortest",
         "-c:v", "ffv1", "-pix_fmt", pix_fmt, "-c:a", "aac", str(path)],
        check=True, capture_output=True, timeout=120)
    return str(path)


def _stream(path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,pix_fmt,profile,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)["streams"][0]


async def _wm(src, out, tmp):
    png = tmp / "wm.png"
    Image.new("RGBA", (40, 20), (255, 0, 0, 128)).save(png)
    await P.watermark_video(src, str(out), str(png), "br")


OPS = {
    "trim": lambda src, out, tmp: P.trim_video(src, str(out), 0.2, 1.2),
    "convert-mp4": lambda src, out, tmp: P.convert_video(src, str(out), "mp4"),
    "convert-mkv": lambda src, out, tmp: P.convert_video(src, str(out), "mkv"),
    "convert-webm": lambda src, out, tmp: P.convert_video(src, str(out), "webm"),
    "watermark": _wm,
}
EXT = {"convert-mkv": "mkv", "convert-webm": "webm"}


@needs_ffmpeg
@pytest.mark.parametrize("op", sorted(OPS), ids=sorted(OPS))
async def test_a_10bit_source_comes_out_8bit(tmp_path, op):
    src = _src(tmp_path / "src10.mkv", "320x240", "yuv420p10le")
    assert "10" in _stream(src)["pix_fmt"], "پیش‌شرط: منبع باید واقعاً ۱۰بیتی باشد"
    out = tmp_path / f"out.{EXT.get(op, 'mp4')}"
    await OPS[op](src, out, tmp_path)
    st = _stream(out)
    assert st["pix_fmt"] == "yuv420p", f"{op}: خروجی {st['pix_fmt']} / {st.get('profile')}"
    assert "10" not in (st.get("profile") or ""), st


@needs_ffmpeg
@pytest.mark.parametrize("op", sorted(OPS), ids=sorted(OPS))
async def test_an_odd_sized_444_source_still_encodes(tmp_path, op):
    """رفعِ نصفه (`-pix_fmt` بدونِ زوج‌کردنِ ابعاد) این‌جا با خطای انکودر می‌شکند."""
    src = _src(tmp_path / "odd.mkv", "321x241", "yuv444p")
    out = tmp_path / f"out.{EXT.get(op, 'mp4')}"
    await OPS[op](src, out, tmp_path)
    st = _stream(out)
    assert st["pix_fmt"] == "yuv420p"
    assert st["width"] % 2 == 0 and st["height"] % 2 == 0, st


def _string_literals(fn) -> set[str]:
    tree = ast.parse(inspect.getsource(fn).lstrip())
    lits = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
            and isinstance(n.value, str)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    return lits | names


def test_every_reencoding_function_pins_the_pixel_format():
    """گارد: تابعِ بعدی که libx264/VP9 صدا بزند و فرمتِ پیکسل را رها کند گرفته شود.

    کشف‌محور روی کلِ ماژول، با AST — نه grep روی متن، چون کامنتِ همین رفع
    `yuv420p` را نام می‌برد و گاردِ متنی آن را «پین‌شده» می‌خواند (§۶).
    """
    offenders = []
    for name, fn in inspect.getmembers(P, inspect.isfunction):
        if fn.__module__ != P.__name__:
            continue
        lits = _string_literals(fn)
        encodes = "libx264" in lits or name == "convert_video"
        pinned = ("yuv420p" in lits or "_DELIVERY_VF" in lits
                  or "_video_encoder_args" in lits
                  or any("format=yuv420p" in s for s in lits))
        if encodes and not pinned:
            offenders.append(name)
    assert not offenders, f"این توابع فرمتِ پیکسلِ خروجی را رها کرده‌اند: {offenders}"
    assert "format=yuv420p" in P._DELIVERY_VF


def test_the_guard_is_not_vacuous():
    """کنترلِ ضدِ توخالی: گارد واقعاً سه تابعِ رفع‌شده را پیدا می‌کند."""
    found = {name for name, fn in inspect.getmembers(P, inspect.isfunction)
             if fn.__module__ == P.__name__ and "libx264" in _string_literals(fn)}
    assert {"trim_video", "watermark_video"} <= found, found
