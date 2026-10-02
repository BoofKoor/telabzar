"""رگرسیونِ OOMِ تصویر در لایهٔ غربالگری.

باگ: `scan_file` برای تصویر مسیرِ خام را مستقیم به NudeNet/OpenCV می‌داد، که
`cv2.imread` کلِ تصویر را decode می‌کند — یک PNGِ ۲۰۰۰۰² (فایلِ ۱٫۲مگابایتی)
~۳٫۵ گیگ RAM می‌گرفت و چون این روی هر آپلودِ عکس خودکار اجرا می‌شود، آلبومی از
چنین فایل‌هایی ورکر را OOM می‌کرد. رفع: تصویرِ بزرگ‌تر از سقف اول با Pillow کوچک
می‌شود و اگر نشد اسکن رد می‌شود (fail-open) — در هیچ حالتی مسیرِ خامِ تصویرِ
غول‌پیکر به detector نمی‌رسد.

بدونِ Pillow/nudenet تست می‌شود: ابعاد و detector هر دو تزریق‌پذیرند.
"""
from __future__ import annotations

import asyncio

import pytest

from app import safety as S


class _RecordingDetector:
    def __init__(self):
        self.seen: list[str] = []

    def detect(self, p):
        self.seen.append(p)
        return []


@pytest.fixture
def rec(monkeypatch):
    d = _RecordingDetector()
    monkeypatch.setattr(S, "_get_detector", lambda: d)
    return d


def _scan(path, **kw):
    return asyncio.run(S.scan_file(path, "image", **kw))


def test_small_image_goes_straight_to_detector(tmp_path, rec, monkeypatch):
    p = tmp_path / "small.jpg"
    p.write_bytes(b"fake")
    monkeypatch.setattr(S, "_image_dims", lambda _p: (800, 600))
    blocked, _, _ = _scan(str(p), workdir=str(tmp_path))
    assert blocked is False
    assert rec.seen == [str(p)]           # خودِ فایلِ کوچک اسکن شد


def test_huge_image_is_never_handed_raw_to_the_detector(tmp_path, rec, monkeypatch):
    p = tmp_path / "bomb.png"
    p.write_bytes(b"fake")
    monkeypatch.setattr(S, "_image_dims", lambda _p: (20000, 20000))
    # Pillow در این محیط نیست → downscale None می‌دهد → اسکن رد می‌شود
    monkeypatch.setattr(S, "_downscale_image", lambda _p, _w: None)
    blocked, score, _ = _scan(str(p), workdir=str(tmp_path))
    assert blocked is False and score == 0.0
    assert str(p) not in rec.seen         # فایلِ خامِ غول‌پیکر هرگز به detector نرفت
    assert rec.seen == []


def test_huge_image_is_downscaled_then_scanned(tmp_path, rec, monkeypatch):
    p = tmp_path / "big.jpg"
    p.write_bytes(b"fake")
    small = tmp_path / "small-scaled.jpg"
    small.write_bytes(b"x")
    monkeypatch.setattr(S, "_image_dims", lambda _p: (20000, 20000))
    monkeypatch.setattr(S, "_downscale_image", lambda _p, _w: str(small))
    _scan(str(p), workdir=str(tmp_path))
    assert rec.seen == [str(small)]       # نسخهٔ کوچک‌شده اسکن شد، نه اصل
    assert not small.exists()             # فایلِ موقت پاک شد
