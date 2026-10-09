"""`app/pdftools.py` با ابزارهای واقعی: باز/تعمیر، صفحه‌ها، رمز، فشرده‌سازی، عکس → PDF."""
from __future__ import annotations

import io
import os
import re
import subprocess

import pytest
from PIL import Image

from app import pdftools as T
from app.exceptions import UserFacingError
from tests.pdfgates import FIX, needs_pdf_tools

FA = str(FIX / "fa_chrome.pdf")


def _pages(path) -> int:
    return int(subprocess.run(["qpdf", "--show-npages", str(path)], capture_output=True,
                              text=True, timeout=30).stdout)


def _check(path) -> None:
    r = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=60)
    assert r.returncode in (0, 3), r.stdout + r.stderr


def _encrypt(src, out, user: str, owner: str) -> str:
    subprocess.run(["qpdf", "--encrypt", user, owner, "256", "--", src, str(out)],
                   check=True, timeout=60)
    return str(out)


async def _three(tmp_path) -> str:
    out = tmp_path / "three.pdf"
    subprocess.run(["qpdf", "--empty", "--pages", FA, FIX / "fa_lo.pdf", FIX / "cols_chrome.pdf",
                    "--", out], check=True, timeout=60)
    return str(out)


# ── prepare ──────────────────────────────────────────────────────
@needs_pdf_tools
async def test_an_owner_locked_pdf_opens_without_a_password(tmp_path):
    """بیشترِ PDFهای واقعی «قفلِ مالک» دارند: بی‌رمز باز می‌شوند ولی `pdfunite`
    ادغامشان را با «Could not merge encrypted files» رد می‌کرد."""
    locked = _encrypt(FA, tmp_path / "o.pdf", "", "owner-secret")
    out = await T.prepare(locked, str(tmp_path))
    assert out != locked and not await T.is_encrypted(out)
    _check(out)


@needs_pdf_tools
async def test_a_user_password_is_a_clear_message_not_a_qpdf_error(tmp_path):
    locked = _encrypt(FA, tmp_path / "u.pdf", "user-pw", "owner-pw")
    with pytest.raises(UserFacingError) as e:
        await T.prepare(locked, str(tmp_path))
    assert e.value.key == "pdf_needs_password"
    with pytest.raises(UserFacingError) as e:
        await T.prepare(locked, str(tmp_path), password="nope")
    assert e.value.key == "pdf_wrong_password"
    assert not await T.is_encrypted(await T.prepare(locked, str(tmp_path), password="user-pw"))


@needs_pdf_tools
async def test_not_a_pdf_and_a_damaged_pdf(tmp_path):
    fake = tmp_path / "x.pdf"
    fake.write_text("%!PS-Adobe-3.0\nshowpage\n")      # PostScript با پسوندِ pdf
    with pytest.raises(UserFacingError) as e:
        await T.prepare(str(fake), str(tmp_path))
    assert e.value.key == "pdf_not_pdf"
    broken = tmp_path / "b.pdf"
    broken.write_bytes(b"%PDF-1.4\n" + os.urandom(400))
    with pytest.raises(UserFacingError) as e:
        await T.prepare(str(broken), str(tmp_path))
    assert e.value.key == "pdf_damaged"


# ── صفحه‌ها ─────────────────────────────────────────────────────
@needs_pdf_tools
async def test_select_keeps_the_users_order(tmp_path):
    src = await _three(tmp_path)
    out = tmp_path / "s.pdf"
    await T.select_pages(src, [3, 1], str(out))
    assert _pages(out) == 2
    first = subprocess.run(["pdftotext", "-f", "1", "-l", "1", str(out), "-"],
                           capture_output=True, text=True, timeout=30).stdout
    assert "Two column English" in first, "صفحهٔ ۳ باید اول باشد"


@needs_pdf_tools
async def test_rotate_and_split(tmp_path):
    src = await _three(tmp_path)
    out = tmp_path / "r.pdf"
    await T.rotate(src, str(out), 90)
    info = subprocess.run(["pdfinfo", "-f", "1", "-l", "1", str(out)], capture_output=True,
                          text=True, timeout=30).stdout
    assert re.search(r"rot:\s+90\b", info), info
    files = await T.split(src, str(tmp_path / "sp"), "doc")
    assert [os.path.basename(f) for f in files] == ["doc-1.pdf", "doc-2.pdf", "doc-3.pdf"]
    assert all(_pages(f) == 1 for f in files)


@needs_pdf_tools
async def test_merge_needs_two(tmp_path):
    with pytest.raises(UserFacingError):
        await T.merge([FA], str(tmp_path / "m.pdf"))
    out = tmp_path / "m.pdf"
    await T.merge([FA, str(FIX / "fa_lo.pdf")], str(out))
    assert _pages(out) == 2


# ── رمز ─────────────────────────────────────────────────────────
@needs_pdf_tools
async def test_lock_never_puts_the_password_on_the_command_line(tmp_path, monkeypatch):
    seen: list[list[str]] = []
    real = T._capture

    async def spy(cmd, **kw):
        seen.append(list(cmd))
        return await real(cmd, **kw)

    monkeypatch.setattr(T, "_capture", spy)
    pw = "رمز-خیلی-سری"
    out = tmp_path / "l.pdf"
    await T.lock(FA, str(out), pw, str(tmp_path))
    assert seen and all(pw not in " ".join(c) for c in seen), seen
    with pytest.raises(UserFacingError):
        await T.prepare(str(out), str(tmp_path))
    assert await T.prepare(str(out), str(tmp_path), password=pw)


@needs_pdf_tools
async def test_lock_refuses_a_bad_password(tmp_path):
    with pytest.raises(UserFacingError) as e:
        await T.lock(FA, str(tmp_path / "l.pdf"), "a\nb", str(tmp_path))
    assert e.value.key == "pdf_pw_bad"


# ── فشرده‌سازی ──────────────────────────────────────────────────
def _scan_jpeg(path, w=2480, h=3508):
    """صفحهٔ اسکن‌مانند: A4 در ۳۰۰dpi (نویزِ نرم + شیب)، JPEGِ ~۳ مگ.

    رزولوشن باید بالای آستانهٔ Ghostscript باشد (`DownsampleThreshold` ۱٫۵ برابرِ
    هدف): عکسِ ۲۰۰dpi زیرِ آن است و هیچ سطحی کوچکش نمی‌کند — نسخهٔ اولِ همین تست
    با ۱۶۰۰ پیکسل «بی‌فایده» برگرداند و چیزی نسنجید.
    """
    noise = Image.effect_noise((w // 4, h // 4), 60).resize((w, h))
    grad = Image.linear_gradient("L").resize((w, h))
    Image.merge("RGB", (noise, grad, Image.blend(noise, grad, 0.5))).save(path, "JPEG", quality=92)
    return str(path)


@needs_pdf_tools
async def test_strong_is_not_larger_than_normal(tmp_path):
    """اندازه‌گیری‌شده: بدونِ فیلترِ JPEGِ اجباری، «حداکثر» از «معمولی» **بزرگ‌تر** می‌شد."""
    pdf = tmp_path / "scan.pdf"
    await T.images_to_pdf([_scan_jpeg(tmp_path / "a.jpg")], str(pdf), workdir=str(tmp_path))
    n_dir, s_dir = tmp_path / "n", tmp_path / "s"
    n_dir.mkdir(), s_dir.mkdir()
    normal = await T.compress(str(pdf), str(n_dir), "normal")
    strong = await T.compress(str(pdf), str(s_dir), "strong")
    assert normal and strong
    assert os.path.getsize(strong) <= os.path.getsize(normal) < os.path.getsize(pdf)
    _check(strong)


@needs_pdf_tools
async def test_no_gain_is_none_not_a_worse_file(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "MIN_GAIN", 0.0)     # هیچ خروجی‌ای «۱۰۰٪ کوچک‌تر» نیست
    assert await T.compress(FA, str(tmp_path), "normal") is None


# ── عکس‌ها → PDF ────────────────────────────────────────────────
@needs_pdf_tools
async def test_a_jpeg_is_embedded_as_is(tmp_path):
    """JPEGِ RGBِ بی‌چرخش عیناً جاسازی می‌شود؛ قبلاً Pillow دوباره انکودش می‌کرد."""
    src = tmp_path / "p.jpg"
    Image.new("RGB", (800, 600), (200, 30, 30)).save(src, "JPEG", quality=90)
    out = tmp_path / "o.pdf"
    await T.images_to_pdf([str(src)], str(out), workdir=str(tmp_path))
    assert src.read_bytes() in out.read_bytes()
    _check(out)


@needs_pdf_tools
async def test_a4_orientation_follows_the_image_and_fit_keeps_its_size(tmp_path):
    wide, tall = tmp_path / "w.png", tmp_path / "t.png"
    Image.new("RGBA", (1200, 600), (0, 0, 255, 100)).save(wide)
    Image.new("L", (600, 1200), 128).save(tall)
    out = tmp_path / "a4.pdf"
    await T.images_to_pdf([str(wide), str(tall)], str(out), mode="a4", workdir=str(tmp_path))
    info = subprocess.run(["pdfinfo", "-f", "1", "-l", "2", str(out)], capture_output=True,
                          text=True, timeout=30).stdout
    assert "841.89 x 595.276" in info and "595.276 x 841.89" in info, info
    fit = tmp_path / "fit.pdf"
    await T.images_to_pdf([str(wide)], str(fit), mode="fit", workdir=str(tmp_path))
    info = subprocess.run(["pdfinfo", str(fit)], capture_output=True, text=True, timeout=30).stdout
    assert "576 x 288" in info, info          # ۱۲۰۰×۶۰۰ پیکسل در ۱۵۰dpi
    _check(out), _check(fit)


@needs_pdf_tools
async def test_exif_rotation_is_applied(tmp_path):
    """عکسِ گوشی: پیکسل‌ها افقی، تگِ چرخش «۹۰°» → صفحه باید عمودی باشد."""
    img = Image.new("RGB", (400, 200), "white")
    exif = img.getexif()
    exif[0x0112] = 6
    src = tmp_path / "phone.jpg"
    img.save(src, "JPEG", exif=exif.tobytes())
    out = tmp_path / "o.pdf"
    await T.images_to_pdf([str(src)], str(out), mode="fit", workdir=str(tmp_path))
    info = subprocess.run(["pdfinfo", str(out)], capture_output=True, text=True, timeout=30).stdout
    assert "96 x 192" in info, info


@needs_pdf_tools
async def test_render_pages_respects_the_cap(tmp_path):
    src = await _three(tmp_path)
    files = await T.render_pages(src, str(tmp_path / "pg"), "jpg", n_pages=3, max_pages=2, dpi=40)
    assert len(files) == 2
    with Image.open(files[0]) as im:
        assert im.format == "JPEG"


def test_zip_is_stored_not_deflated(tmp_path):
    import zipfile
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x" * 1000)
    out = tmp_path / "o.zip"
    T.zip_files([str(a)], str(out))
    with zipfile.ZipFile(out) as z:
        assert z.infolist()[0].compress_type == zipfile.ZIP_STORED


def test_safe_tag():
    assert T.safe_tag("1-3,7") == "1-3_7"
    assert T.safe_tag("../../x") == ""
    assert len(T.safe_tag("1," * 40)) <= 24


def test_is_pdf_reads_the_header_not_the_name(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"\n\n%PDF-1.7\n" + b"0" * 10)
    assert T.is_pdf(str(p))
    q = tmp_path / "y.pdf"
    q.write_bytes(io.BytesIO(b"PK\x03\x04").read())
    assert not T.is_pdf(str(q))
