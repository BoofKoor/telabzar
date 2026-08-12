#!/usr/bin/env python3
"""ساختارِ **واقعیِ** پاسخِ صفحهٔ embedِ اسپاتیفای — قبل از هر حکمی دربارهٔ پارسر.

مشاهده‌شده روی مستر: `_parse_spotify_embed` فقط `title` را برمی‌گرداند و
`subtitle`/`duration` خالی‌اند. دو توضیحِ ممکن هست و از بیرون یکسان‌اند:

* **الف** اسپاتیفای نامِ کلیدها را عوض کرده (مثلاً `subtitle` → چیزِ دیگر).
* **ب** `_find_spotify_entity` **آبجکتِ اشتباه** را برمی‌دارد. شرطش
  `trackList is not None or (title and coverArt)` است و بازگشتی **اولین**
  تطبیق را در ترتیبِ کلیدهای dict برمی‌گرداند — پس یک زیرآبجکتِ تودرتو (مثلاً
  آلبوم) که اتفاقاً `title` و `coverArt` دارد می‌تواند قبل از entityِ اصلی
  گیر بیفتد، و آن‌وقت `title` درست درمی‌آید ولی بقیه نه. دقیقاً همان الگویی که
  دیده شد.

این اسکریپت هیچ حدسی نمی‌زند: درخت را چاپ می‌کند، هر کلیدِ مرتبط را نشان می‌دهد،
می‌گوید `_find_spotify_entity` چه چیزی برداشته، و **پاسخِ خام را روی دیسک ذخیره
می‌کند** تا همان فیکسچرِ واقعیِ تست شود (جای فیکسچرهای ساختگیِ فعلی).

**اجرا روی مستر:**

    cd <repo> && docker compose exec -T download-worker python - \
        "https://open.spotify.com/track/4Mrmg7XjDKqKWTw38hFCq6" \
        --save /work/embed_jane_maryam.json < tools/spotify_embed_dump.py

بعد فایلِ ذخیره‌شده را از کانتینر بیرون بکش:

    docker compose cp download-worker:/work/embed_jane_maryam.json .
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request

sys.path.insert(0, "/srv")
sys.path.insert(0, ".")

RELEVANT = re.compile(r"artist|subtitle|duration|isrc|album|release|year|title|name|track",
                      re.I)
MAX_DEPTH = 7


def fetch(url: str) -> str:
    from app import downloader as D          # همان هدرهایی که خودِ کد می‌فرستد
    req = urllib.request.Request(url, headers=D._BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        print(f"HTTP {r.status}", file=sys.stderr)
        return r.read().decode("utf-8", "replace")


def short(v) -> str:
    if isinstance(v, str):
        return repr(v if len(v) <= 60 else v[:57] + "…")
    return repr(v)


def tree(obj, path: str = "", depth: int = 0, hits: list | None = None) -> None:
    """درختِ کلیدها با مقدارهای کوتاه‌شده؛ کلیدهای مرتبط علامت می‌خورند."""
    if hits is None:
        hits = []
    pad = "  " * depth
    if depth > MAX_DEPTH:
        print(f"{pad}…")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            mark = " ◄" if RELEVANT.search(str(k)) else ""
            here = f"{path}/{k}"
            if isinstance(v, (dict, list)):
                n = len(v)
                print(f"{pad}{k}: {type(v).__name__}[{n}]{mark}")
                tree(v, here, depth + 1, hits)
            else:
                print(f"{pad}{k} = {short(v)}{mark}")
                if mark and v not in (None, "", 0):
                    hits.append((here, v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            print(f"{pad}[{i}]")
            tree(v, f"{path}[{i}]", depth + 1, hits)
        if len(obj) > 3:
            print(f"{pad}… و {len(obj) - 3} تای دیگر")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    url, save = "", ""
    i = 0
    while i < len(args):
        if args[i] == "--save":
            i += 1; save = args[i]
        elif not args[i].startswith("--"):
            url = args[i]
        i += 1
    if not url:
        print(__doc__)
        return 2

    html = fetch(url)
    print(f"طولِ HTML: {len(html)}")

    m = re.search(r'id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, re.S)
    print(f"__NEXT_DATA__ پیدا شد: {bool(m)}")
    if not m:
        # شاید اسپاتیفای تگِ دیگری می‌دهد — هر اسکریپتِ JSONدار را نشان بده
        print("\nتگ‌های script با نوعِ json:")
        for mm in re.finditer(r'<script[^>]*id="([^"]+)"[^>]*type="application/json"', html):
            print("   ", mm.group(1))
        if save:
            open(save, "w", encoding="utf-8").write(html)
            print(f"\nHTMLِ خام ذخیره شد: {save}")
        return 1

    data = json.loads(m.group(1))
    if save:
        with open(save, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        print(f"JSONِ خام ذخیره شد: {save}  ({len(m.group(1))} بایت)")

    print("\n" + "=" * 78)
    print("درختِ کامل (کلیدهای مرتبط با ◄ علامت خورده‌اند)")
    print("=" * 78)
    hits: list = []
    tree(data, hits=hits)

    print("\n" + "=" * 78)
    print("همهٔ مقدارهای غیرخالی زیرِ کلیدهای مرتبط — یعنی چیزی که *واقعاً* موجود است")
    print("=" * 78)
    for p, v in hits:
        print(f"  {p} = {short(v)}")

    from app import downloader as D
    ent = D._find_spotify_entity(data)
    print("\n" + "=" * 78)
    print("`_find_spotify_entity` چه چیزی برداشت؟")
    print("=" * 78)
    if ent is None:
        print("  هیچ‌چیز.")
    else:
        print(f"  کلیدهایش: {sorted(ent.keys())}")
        for k in ("title", "subtitle", "artists", "duration", "coverArt", "trackList",
                  "isrc", "album", "releaseDate"):
            if k in ent:
                v = ent[k]
                print(f"    {k} = {short(v) if not isinstance(v,(dict,list)) else type(v).__name__}")
        print(f"\n  ⚠ اگر این آبجکت `subtitle`/`duration` ندارد ولی جای دیگری از درخت هست،")
        print(f"    یعنی entityِ اشتباه برداشته شده (شاخهٔ ب)، نه اینکه اسپاتیفای حذفشان کرده.")

    print("\n" + "=" * 78)
    print("خروجیِ فعلیِ `_parse_spotify_embed` (همان که تولید می‌بیند)")
    print("=" * 78)
    kind, _ = D.spotify_id(url)
    out = D._parse_spotify_embed(html, kind or "track", 20)
    print(" ", json.dumps(out, ensure_ascii=False)[:600] if out else "None")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
