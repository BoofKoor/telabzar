"""فاز ۴ / موردِ ۳۴ت — شفافیت، CMYK و ۱۶ بیت در ابزارهای تصویر.

سه شکستِ اندازه‌گیری‌شده روی Pillowِ واقعی، پیش از رفع:

* «بهبود» روی PNGِ شفاف: `convert("RGB")` آلفا را دور می‌ریخت و پیکسل‌های شفاف
  (RGBِ صفر) **سیاه** می‌شدند — لوگو با پس‌زمینهٔ سیاه برمی‌گشت.
* JPEGِ **CMYK** → PNG: «cannot write mode CMYK as PNG»؛ عملیات شکست می‌خورد.
* PNGِ **۱۶ بیتی** → JPEG: مقدار در ۲۵۵ بریده می‌شد نه مقیاس، پس خروجی تقریباً
  یکسره سفید بود.

همه از مسیرِ واقعیِ توابعِ همگامِ `processing` و تصویرِ واقعیِ روی دیسک.
"""
from __future__ import annotations

import pytest
from PIL import Image

from app import processing as P


@pytest.fixture
def transparent(tmp_path):
    p = tmp_path / "logo.png"
    im = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    im.paste((255, 0, 0, 255), (10, 10, 30, 30))
    im.save(p)
    return p


@pytest.fixture
def cmyk(tmp_path):
    p = tmp_path / "print.jpg"
    Image.new("CMYK", (40, 40), (0, 128, 128, 0)).save(p)
    return p


@pytest.fixture
def gray16(tmp_path):
    p = tmp_path / "scan.png"
    g = Image.new("I;16", (40, 40))
    g.putdata([int(i * 65535 / 1599) for i in range(1600)])   # شیبِ کامل ۰..۶۵۵۳۵
    g.save(p)
    assert Image.open(p).mode.startswith("I")
    return p


@pytest.mark.parametrize("ext", ["png", "webp"], ids=["png", "webp"])
def test_enhance_keeps_transparency(transparent, tmp_path, ext):
    out = tmp_path / f"o.{ext}"
    P._enhance_image_sync(str(transparent), str(out))
    o = Image.open(out).convert("RGBA")
    assert o.getpixel((0, 0))[3] == 0, f"گوشهٔ شفاف کدر شد: {o.getpixel((0, 0))}"
    assert o.getpixel((20, 20))[3] == 255


def test_enhance_to_jpeg_flattens_on_white(transparent, tmp_path):
    """کنترل: JPEG آلفا ندارد — پس‌زمینه سفید شود نه سیاه."""
    out = tmp_path / "o.jpg"
    P._enhance_image_sync(str(transparent), str(out))
    assert min(Image.open(out).convert("RGB").getpixel((0, 0))) > 200


@pytest.mark.parametrize("fmt", ["png", "webp", "jpg"], ids=["png", "webp", "jpg"])
def test_a_cmyk_jpeg_converts(cmyk, tmp_path, fmt):
    out = tmp_path / f"o.{fmt}"
    P._convert_image_sync(str(cmyk), str(out), fmt)
    assert Image.open(out).size == (40, 40)


def test_a_cmyk_jpeg_rotates_to_png(cmyk, tmp_path):
    out = tmp_path / "o.png"
    P._rotate_image_sync(str(cmyk), str(out), "cw")
    assert Image.open(out).size == (40, 40)


@pytest.mark.parametrize("fmt", ["jpg", "png", "webp"], ids=["jpg", "png", "webp"])
def test_a_16bit_image_keeps_its_tones(gray16, tmp_path, fmt):
    out = tmp_path / f"o.{fmt}"
    P._convert_image_sync(str(gray16), str(out), fmt)
    o = Image.open(out).convert("L")
    first, mid, last = o.getpixel((0, 0)), o.getpixel((0, 20)), o.getpixel((39, 39))
    assert first < 20 and last > 235, (first, last)
    assert 100 < mid < 155, f"شیب بریده شد (وسط = {mid})؛ تصویر سفید شده"


def test_an_8bit_range_in_a_32bit_mode_is_not_darkened(tmp_path):
    """کنترلِ مقیاس: `I` با مقادیرِ ۰..۲۵۵ نباید بر ۲۵۶ تقسیم شود و سیاه شود."""
    p = tmp_path / "i8.tif"
    g = Image.new("I", (16, 16))
    g.putdata([200] * 256)
    g.save(p)
    out = tmp_path / "o.png"
    P._convert_image_sync(str(p), str(out), "png")
    assert Image.open(out).convert("L").getpixel((0, 0)) == 200


def test_an_ordinary_rgb_photo_is_untouched(tmp_path):
    """کنترل: مسیرِ عادی همان قبلی."""
    p = tmp_path / "a.png"
    Image.new("RGB", (8, 8), (10, 120, 200)).save(p)
    out = tmp_path / "o.png"
    P._convert_image_sync(str(p), str(out), "png")
    assert Image.open(out).convert("RGB").getpixel((0, 0)) == (10, 120, 200)
