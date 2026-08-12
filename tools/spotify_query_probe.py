#!/usr/bin/env python3
"""کدام **کوئری** ضبطِ درست را برمی‌گرداند؟ — شاخهٔ ب، وقتی امتیازدهی بی‌تقصیر است.

`spotify_explain.py` نشان داد ضبطِ درستِ «Faryad» اصلاً در بیستِ نامزد نیست، پس
مسئله رتبه‌بندی نیست؛ چیزی که به YT Music می‌فرستیم درست نیست. کوئریِ فعلی
`"{artist} {title}"` است و `artist` **همهٔ** هنرمندان را با ویرگول به‌هم می‌چسباند —
که برای موسیقیِ ایرانی یعنی «آهنگساز, خواننده» و آهنگساز اول می‌آید.

این ابزار چند شکلِ کوئری را روی **یک** ترک اجرا می‌کند و می‌گوید هرکدام ضبطِ
هدف را برمی‌گرداند یا نه و در چه رتبه‌ای. هدف را با `--want-artist` و
`--want-secs` تعریف می‌کنی (مثلاً `--want-artist Haydeh --want-secs 311`).

**اجرا روی مستر** (یوتیوب از سندباکسِ توسعه در دسترس نیست):

    docker compose exec -T download-worker python - \
        "https://open.spotify.com/track/<id>" \
        --want-artist Haydeh --want-secs 311 \
        < tools/spotify_query_probe.py

گزینه‌ها: `--fa "<عنوانِ فارسی>"` یک کوئریِ فارسی هم اضافه می‌کند ·
`--delay S` (پیش‌فرض ۲).

کوکی مصرف نمی‌شود و چیزی دانلود نمی‌شود.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/srv")
sys.path.insert(0, ".")

from app import downloader as D     # noqa: E402


def variants(track: dict, fa: str = "") -> list[tuple[str, str]]:
    """(نام, کوئری) — همان شکل‌هایی که باید مقایسه شوند."""
    arts = D._track_artists(track)
    title = track.get("title") or ""
    raw = track.get("artist") or ""
    out = [
        ("فعلی (همهٔ هنرمندان)", f"{raw} {title}".strip()),
        ("بدونِ ویرگول", f"{raw.replace(',', ' ')} {title}".strip()),
        ("هنرمندِ اول + عنوان", f"{arts[0]} {title}".strip() if arts else title),
        ("هنرمندِ آخر + عنوان", f"{arts[-1]} {title}".strip() if arts else title),
        ("فقط عنوان", title),
    ]
    if len(arts) > 2:
        out.append(("دو هنرمندِ اول", f"{arts[0]} {arts[1]} {title}"))
    if fa:
        out.append(("فارسی", fa))
    seen, uniq = set(), []
    for n, q in out:                      # کوئریِ تکراری را دوبار نفرست
        if q and q not in seen:
            seen.add(q); uniq.append((n, q))
    return uniq


def hits(cands: list[dict], want_artist: str, want_secs: int,
         tol: int = 20) -> list[tuple[int, str]]:
    """(ایندکس, دلیل) برای نامزدهایی که با هدف می‌خوانند.

    **دو معیار، عمداً:** تطبیقِ نامِ هنرمند، **یا** فقط مدت. دلیلش همان چیزی است
    که این ابزار برای آن ساخته شده — اگر ضبطِ درست با نامِ **فارسی** فهرست شده
    باشد («هایده» در برابرِ `Haydeh`)، معیارِ نامْ آن را نمی‌بیند و ابزار
    «پیدا نشد» گزارش می‌کند، یعنی دقیقاً همان مثبتِ کاذبی که ما را به مسیرِ
    اشتباه می‌فرستد. مدت این شکاف را پر می‌کند.
    """
    out = []
    for i, c in enumerate(cands):
        arts = " ".join(D._cand_artists(c)).lower()
        dur = D._cand_dur(c)
        near = bool(dur and abs(dur - want_secs) <= tol)
        if want_artist.lower() in arts and near:
            out.append((i, "نام+مدت"))
        elif near:
            out.append((i, "فقط مدت — نامِ هنرمند شاید فارسی باشد"))
    return out


def clip(s, n):
    s = (str(s) if s is not None else "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


async def main() -> int:
    args, url, want_a, want_s, fa, delay = sys.argv[1:], "", "", 0, "", 2.0
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--want-artist": i += 1; want_a = args[i]
        elif a == "--want-secs": i += 1; want_s = int(args[i])
        elif a == "--fa":        i += 1; fa = args[i]
        elif a == "--delay":     i += 1; delay = float(args[i])
        elif not a.startswith("--"): url = a
        i += 1
    if not url or not want_a:
        print(__doc__)
        return 2

    res = await D.spotify_resolve(url, "", "", 1)
    track = (res.get("tracks") or [None])[0]
    if not track:
        print("ترک پارس نشد", file=sys.stderr)
        return 1
    print(f"مرجع: {track['title']!r} — {track['artist']!r} — {track['duration']}s")
    print(f"هدف : هنرمند شاملِ {want_a!r} و مدت ≈ {want_s or track['duration']}s\n")
    want_s = want_s or (track.get("duration") or 0)

    pool: dict[str, dict] = {}          # ادغامِ نامزدها بینِ همهٔ کوئری‌ها
    rows = []
    for name, q in variants(track, fa):
        cands = await D._ytmusic_search(q, "songs", None)            # بدونِ کوکی
        if len(cands) < 3:
            cands += await D._ytmusic_search(q, "videos", None)
        idx = hits(cands, want_a, want_s)
        rows.append((name, q, len(cands), idx, cands))
        for c in cands:
            pool.setdefault(D._cand_url(c) or repr(c), c)
        mark = f"✓ رتبهٔ {idx[0][0] + 1}" if idx else "✗ نیست"
        print(f"  {mark:<12} {name:<24} {q!r}   ({len(cands)} نامزد)")
        for j, why in idx[:2]:
            c = cands[j]
            print(f"               → {clip(c.get('title'), 40)} — "
                  f"{clip(', '.join(D._cand_artists(c)), 22)} · {D._cand_dur(c)}s  [{why}]")
        if delay:
            await asyncio.sleep(delay)

    merged = list(pool.values())
    midx = hits(merged, want_a, want_s)
    print(f"\n  ادغامِ همهٔ کوئری‌ها: {len(merged)} نامزدِ یکتا → "
          + (f"هدف هست ({midx[0][1]})" if midx else "هدف **هنوز نیست**"))
    if midx:
        ranked = D._rank_candidates(merged, track)
        target = merged[midx[0][0]]
        pos = next((n for n, (_, c) in enumerate(ranked, 1)
                    if D._cand_url(c) == D._cand_url(target)), None)
        print(f"  و بعد از رتبه‌بندی: {'رتبهٔ ' + str(pos) if pos else '**گیت خورد**'}"
              f"  (از {len(ranked)} بازمانده)")
        if ranked:
            print(f"  برندهٔ فعلی: {clip(ranked[0][1].get('title'), 40)} — "
                  f"{clip(', '.join(D._cand_artists(ranked[0][1])), 24)} "
                  f"({ranked[0][0]:.1f})")
    print("\n  ⇒ اگر ادغام هدف را می‌آورد ولی رتبه‌بندی نمی‌بردش، مسئله دوباره امتیازدهی است.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
