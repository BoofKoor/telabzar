"""فاز ۳ / موردِ ۱۲ — چرخشِ EXIF پیش از ذخیره اعمال شود.

دوربینِ موبایل پیکسل‌ها را به جهتِ سنسور ذخیره می‌کند و جهتِ درست را فقط در تگِ
`Orientation` می‌نویسد. Pillow آن تگ را هنگامِ ذخیرهٔ دوباره نمی‌برد، پس فشرده‌سازی
و تبدیلِ یک عکسِ عمودی خروجیِ **افقی** می‌داد. `resize`/`rotate`/`enhance` از قبل
`exif_transpose` داشتند؛ این‌ها نه.

ادعا روی **پیکسل** است نه فقط ابعاد: تبدیلِ اشتباه (مثلاً چرخشِ خلافِ جهت) هم
ابعادِ درست می‌دهد، پس یک نشانگرِ رنگی گوشهٔ بالا-چپِ بافرِ خام گذاشته می‌شود و
جای درستش بعد از چرخش سنجیده می‌شود.
"""
from __future__ import annotations

import ast
import inspect

import pytest
from PIL import Image

from app import processing as P

ORIENT = 0x0112


def _phone_photo(path) -> str:
    """بافرِ خام ۴۰×۲۰ (افقی) با Orientation=6 → نمایشِ درست ۲۰×۴۰ (عمودی).

    نشانگرِ قرمز گوشهٔ بالا-چپِ بافر است؛ Orientation=6 یعنی «۹۰° ساعتگرد بچرخان»،
    پس در تصویرِ درست، نشانگر به گوشهٔ **بالا-راست** می‌رود.
    """
    img = Image.new("RGB", (40, 20), (0, 0, 255))
    for x in range(8):
        for y in range(8):
            img.putpixel((x, y), (255, 0, 0))
    exif = Image.Exif()
    exif[ORIENT] = 6
    img.save(path, "JPEG", quality=95, exif=exif.tobytes())
    return str(path)


def _red(px) -> bool:
    r, g, b = px[:3]
    return r > 180 and g < 90 and b < 90


def _assert_upright(out) -> None:
    with Image.open(out) as im:
        assert (im.width, im.height) == (20, 40), f"کج ماند: {im.size}"
        assert im.getexif().get(ORIENT, 1) in (1, None), "تگِ چرخش نباید دوباره اعمال شود"
        rgb = im.convert("RGB")
        assert _red(rgb.getpixel((im.width - 3, 2))), "نشانگر باید بالا-راست باشد"
        assert not _red(rgb.getpixel((2, 2))), "چرخش در جهتِ اشتباه"


async def test_compress_keeps_a_portrait_photo_upright(tmp_path):
    src = _phone_photo(tmp_path / "in.jpg")
    out = tmp_path / "out.jpg"
    await P.compress_image(src, str(out))
    _assert_upright(out)


@pytest.mark.parametrize("fmt", ["jpg", "png", "webp"], ids=["jpg", "png", "webp"])
async def test_convert_keeps_a_portrait_photo_upright(tmp_path, fmt):
    src = _phone_photo(tmp_path / "in.jpg")
    out = tmp_path / f"out.{fmt}"
    await P.convert_image(src, str(out), fmt)
    _assert_upright(out)


async def test_resize_was_already_upright(tmp_path):
    """کنترل: مسیری که از قبل `exif_transpose` داشت — سبز روی هر دو طرف."""
    src = _phone_photo(tmp_path / "in.jpg")
    out = tmp_path / "out.png"
    await P.resize_image(src, str(out), 20)
    with Image.open(out) as im:
        assert (im.width, im.height) == (20, 40)


def test_every_pillow_open_in_processing_goes_through_upright():
    """گارد: `Image.open`ِ خامِ بعدی در `processing` (نسخهٔ سومِ دست‌نویس) گرفته شود.

    با AST روی کلِ ماژول، نه grep — داکس‌استرینگِ `_upright` خودش `Image.open` را
    نام می‌برد (§۶: گارد توضیحاتِ خودش را نخواند).
    """
    tree = ast.parse(inspect.getsource(P))
    opens = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "open" and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "Image"):
                opens.append(fn.name)
    assert opens == ["_upright"], f"Image.openِ مستقیم بیرونِ `_upright`: {opens}"
