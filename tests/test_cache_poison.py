"""رگرسیونِ مسمومیتِ کشِ بین‌کاربری از راهِ کلیدِ کش.

باگ: `dl_cache._cache_url` الگوهای شناسهٔ یوتیوب/اینستاگرام/X/تیک‌تاک را با
`search` **هرجای** URL و بدونِ چکِ هاست جور می‌کرد. پس یک هاستِ ناشناخته مثلِ
`attacker.example/x?r=youtu.be/<id>` همان کلیدِ ویدیوی واقعی را می‌گرفت؛ چون این
پلتفرم‌ها نسخهٔ کلید نمی‌گیرند (در `_MATCH_PLATFORMS` نیستند)، کلیدها یکی می‌شدند و
بعد از آن هر کاربری که لینکِ واقعی می‌فرستاد فایلِ مهاجم را می‌گرفت (کش بی‌انقضا).
رفع: هر الگو فقط وقتی اعمال شود که `platform_of` (هاست‌محور) همان پلتفرم را بدهد.
"""
from __future__ import annotations

import pytest

from app import dl_cache as C


@pytest.mark.parametrize("attacker,real", [
    ("https://attacker.example/promo.bin?r=youtu.be/dQw4w9WgXcQ",
     "https://youtu.be/dQw4w9WgXcQ"),
    ("https://attacker.example/x#youtube.com/watch?v=dQw4w9WgXcQ",
     "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("https://evil.example/instagram.com/p/ABCdef123/",
     "https://www.instagram.com/p/ABCdef123/"),
    ("https://evil.example/path?u=x.com/user/status/1234567890",
     "https://x.com/user/status/1234567890"),
    ("https://evil.example/?u=tiktok.com/@u/video/7234567890123456789",
     "https://www.tiktok.com/@u/video/7234567890123456789"),
])
def test_foreign_host_does_not_collide_with_real_platform(attacker, real):
    assert C.cache_key(attacker, "best") != C.cache_key(real, "best"), \
        f"poison: {attacker!r} shares a cache key with {real!r}"


@pytest.mark.parametrize("a,b", [
    ("https://youtu.be/dQw4w9WgXcQ",
     "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=xyz"),
    ("https://www.instagram.com/p/ABCdef123/",
     "https://instagram.com/reel/ABCdef123/?igsh=1"),
])
def test_real_platform_forms_still_coalesce(a, b):
    # رفع نباید نرمال‌سازیِ شکل‌های واقعیِ یک پلتفرم را بشکند
    assert C.cache_key(a, "best") == C.cache_key(b, "best")
