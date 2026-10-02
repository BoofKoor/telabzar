"""رگرسیونِ تزریقِ پیکربندیِ WireGuard از راهِ کلیدِ عمومیِ نود.

باگ: `node_join` فقط `len(pubkey) <= 64` را چک می‌کرد، پس یک کلیدِ حاویِ خطِ
جدید از آن رد می‌شد و `render_peers` آن را مستقیم در `wg0.conf` می‌گذاشت — و چون
کانفیگ سرِ boot با `wg-quick` بالا می‌آید، خطوطِ `[Interface]`/`PostUp`ِ تزریق‌شده
می‌توانستند به اجرای فرمان برسند. رفع: اعتبارسنجیِ سخت‌گیرِ فرمتِ کلید + کنارگذاریِ
کلیدِ نامعتبر در `render_peers` (تورِ دوم).
"""
from __future__ import annotations

import base64
import os

import pytest

from app import nodes


def _wgkey() -> str:
    return base64.b64encode(os.urandom(32)).decode()


_GOOD = _wgkey()


@pytest.mark.parametrize("pk,ok", [
    (_GOOD, True),                                           # ۴۴ کاراکترِ معتبر
    (_GOOD[:-1] + "+", False),                               # بدونِ `=` پایانی درست
    ("short=", False),
    ("", False),
    (_GOOD + "\nAllowedIPs = 0.0.0.0/0", False),
    (_GOOD + "\n[Interface]\nPostUp = rm -rf /", False),
    ("key with spaces ============================", False),
])
def test_valid_pubkey(pk, ok):
    assert nodes.valid_pubkey(pk) is ok


def test_render_peers_drops_injected_key():
    good = _wgkey()
    evil = _wgkey() + "\n[Interface]\nPostUp = x"
    out = nodes.render_peers([(evil, "10.51.0.2"), (good, "10.51.0.3")])
    assert "PostUp" not in out
    assert "[Interface]" not in out
    assert good in out                       # کلیدِ سالم می‌ماند
    assert out.count("[Peer]") == 1          # فقط یک peerِ معتبر
