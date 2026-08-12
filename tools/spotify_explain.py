#!/usr/bin/env python3
"""چرا این ترک اشتباه تطبیق خورد؟ — **کلِ** فهرستِ نامزدها با تصمیمِ هر گیت.

`spotify_bench.py` فقط برنده را می‌دهد؛ این یکی برای کالبدشکافیِ یک ترکِ مشخص
است: هر نامزد با عنوان، کانال/هنرمند، مدت، منبع، `art_track`، سه مؤلفهٔ امتیاز،
و اینکه گیت خورد یا نه و **کدام** گیت.

**سه شاخه‌ای که این ابزار از هم جدا می‌کند** (شاخهٔ سوم در فهرستِ اولیه نبود و
از خواندنِ `download_spotify` درآمد):

* **الف** ضبطِ درست بینِ نامزدها بود و **باخت** → مسئلهٔ رتبه‌بندی است.
* **ب** ضبطِ درست اصلاً در فهرست **نبود** → هیچ رتبه‌بندی‌ای نجاتش نمی‌دهد؛
  تنها جوابْ هشدار یا امتناع است (رفع ۲).
* **پ** **همهٔ** نامزدها گیت خوردند → `ranked` خالی می‌ماند، `best` هم `None`،
  و `download_spotify` به `ytsearch1:<query>` می‌افتد یعنی **نتیجهٔ اولِ خامِ
  یوتیوب، بدونِ هیچ امتیازدهی**. در این حالت گیت‌ها درست کار کرده‌اند و بعد
  دور زده شده‌اند — که از بیرون دقیقاً شبیهِ «گیت کار نکرد» به‌نظر می‌رسد.

**اجرا (روی مستر — یوتیوب از سندباکسِ توسعه در دسترس نیست):**

    cd <repo> && docker compose exec -T download-worker python - \
        "https://open.spotify.com/track/<id>" --raw < tools/spotify_explain.py

یا بدونِ لینک، با متادیتای دستی:

    ... python - --title Faryad --artist "Anoushirvan Rohani, Haydeh" --duration 311

`--raw` دیکشنریِ خامِ هر نامزد را هم چاپ می‌کند — برای دیدنِ اینکه مدت **واقعاً
غایب** بوده یا فقط صفر/رشته. کوکی مصرف نمی‌شود و دانلودی انجام نمی‌گیرد.
"""
from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, "/srv")
sys.path.insert(0, ".")

from app import downloader as D     # noqa: E402


def mmss(s: int | None) -> str:
    return "—" if not s else f"{s // 60}:{s % 60:02d}"


def clip(s, n: int) -> str:
    s = (str(s) if s is not None else "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def gate_of(cand: dict, track: dict) -> tuple[str, str]:
    """کدام گیت این نامزد را انداخت؟ (به همان ترتیبِ `_rank_candidates`)."""
    if not D._cand_url(cand):
        return "url", "شناسه/لینک ندارد"
    nm = D._name_match(track, cand)
    if nm < 45:
        return "name", f"شباهتِ عنوان {nm:.0f} < ۴۵"
    if D._duration_reject(cand, track):
        cd, td = D._cand_dur(cand), track.get("duration")
        return "duration", f"اختلافِ مدت {abs(cd - td)}s = {abs(cd - td) / td:.0%}"
    am = D._artist_match(track, cand)
    if D._explicit_artist(cand) and am is not None and am < 40:
        return "artist", f"هنرمندِ صریح، شباهت {am:.0f} < ۴۰"
    return "", ""


async def main() -> int:
    args = sys.argv[1:]
    url = title = artist = ""
    dur = 0
    raw = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--title":   i += 1; title = args[i]
        elif a == "--artist": i += 1; artist = args[i]
        elif a == "--duration": i += 1; dur = int(args[i])
        elif a == "--raw":   raw = True
        elif not a.startswith("--"): url = a
        i += 1

    if url:
        res = await D.spotify_resolve(url, "", "", 1)
        tracks = res.get("tracks") or []
        if not tracks:
            print("هیچ ترکی از لینک درنیامد.", file=sys.stderr)
            return 1
        track = tracks[0]
    elif title:
        track = D._embed_track(title, artist, None, dur * 1000)
    else:
        print(__doc__)
        return 2

    print("=" * 78)
    print("ترکِ اسپاتیفای (از مسیرِ embed، همان که تولید می‌بیند):")
    for k in ("title", "artist", "album", "year", "duration", "isrc"):
        print(f"    {k:<9} = {track.get(k)!r}")
    query = " ".join(p for p in (track.get("artist"), track.get("title")) if p).strip()
    print(f"    کوئری     = {query!r}")
    print("=" * 78)

    cands = await D._gather_candidates(track, {}, "ytmusic")   # بدونِ کوکی
    print(f"\n{len(cands)} نامزد جمع شد.\n")
    if not cands:
        print("→ شاخهٔ ب: هیچ نامزدی پیدا نشد. `download_spotify` به ytsearch1 خام می‌افتد.")
        return 0

    scored = []
    for c in cands:
        g, why = gate_of(c, track)
        scored.append((None if g else D._match_score(c, track), g, why, c))
    scored.sort(key=lambda x: (x[0] is None, -(x[0] or 0)))

    for n, (sc, g, why, c) in enumerate(scored, 1):
        src = c.get("source") or "ytsearch"
        arts = ", ".join(D._cand_artists(c)) or "—"
        cd = D._cand_dur(c)
        td = track.get("duration")
        tm = D._time_match(cd, td)
        tm_s = (f"{tm:.0f}" if tm is not None
                else (f"{D._TIME_UNKNOWN:.0f} (خنثی)" if td and not cd else "—"))
        head = f"  {n:2d}. " + (f"امتیاز {sc:6.1f}" if sc is not None else f"✗ گیتِ {g:<8}")
        print(f"{head}   [{src}{' · art_track' if c.get('art_track') else ''}"
              f"{' · صریح' if D._explicit_artist(c) else ''}]")
        print(f"      عنوان : {clip(c.get('title'), 60)}")
        print(f"      هنرمند: {clip(arts, 40)}   مدت: {mmss(cd)}"
              + (f"  (Δ {cd - td:+d}s)" if cd and td else "  (مدت ندارد)"))
        print(f"      مؤلفه‌ها: نام {D._name_match(track, c):5.1f} · "
              f"هنرمند {('%5.1f' % D._artist_match(track, c)) if D._artist_match(track, c) is not None else '   —'} · "
              f"مدت {tm_s}")
        if g:
            print(f"      ✗ افتاد: {why}")
        if raw:
            print(f"      raw: {json.dumps(c, ensure_ascii=False)[:200]}")
        print()

    ranked = D._rank_candidates(cands, track)
    print("=" * 78)
    print(f"از گیت رد شدند: {len(ranked)} از {len(cands)}")
    if not ranked:
        print("\n→ **شاخهٔ پ**: هیچ نامزدی از گیت رد نشد، پس `ranked` خالی است و")
        print("  `download_spotify` به `ytsearch1:<query>` می‌افتد — نتیجهٔ اولِ خامِ")
        print("  یوتیوب، **بدونِ هیچ امتیازدهی**. گیت‌ها کار کردند و بعد دور زده شدند.")
        print(f"  یعنی فایلِ تحویلی = اولین نتیجهٔ جست‌وجوی: {query!r}")
        return 0

    best_score, best = ranked[0]
    print(f"\nبرنده: {clip(best.get('title'), 55)}")
    print(f"       {D._cand_url(best)}")
    print(f"       امتیاز {best_score:.1f}  ·  مدت {mmss(D._cand_dur(best))}"
          f"  ·  منبع {best.get('source') or 'ytsearch'}")
    print(f"\nآستانهٔ پیش‌فرض ۵۵ → {'بالای آستانه' if best_score >= 55 else 'زیرِ آستانه'}"
          " (ولی با spotify_yt_fallback روشن، آستانه امروز اثری ندارد)")
    if len(ranked) > 1:
        print(f"نفرِ دوم: {ranked[1][0]:.1f} — {clip(ranked[1][1].get('title'), 45)}")
    print("\nحالا با چشم قضاوت کن: ضبطِ درست در فهرستِ بالا هست؟")
    print("  هست و نبرد  → شاخهٔ الف (مسئلهٔ رتبه‌بندی)")
    print("  اصلاً نیست → شاخهٔ ب (پوششِ کاتالوگ؛ فقط هشدار/امتناع جواب است)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
