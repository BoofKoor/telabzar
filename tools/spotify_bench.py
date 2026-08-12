#!/usr/bin/env python3
"""سنجهٔ کیفیتِ matcherِ اسپاتیفای — جدولِ **برچسب‌پذیر** برای تصمیم دربارهٔ آستانه.

چرا این شکل: توزیعِ امتیاز به‌تنهایی فقط می‌گوید چند ترک هشدار می‌گیرند، نه اینکه
آستانه **درست را از غلط جدا می‌کند یا نه**. اگر امتیازِ ۴۰ و ۸۰ هر دو نتیجهٔ درست
بدهند، آستانه نویز است. پس خروجی طوری است که آدم روی هر ردیف علامتِ درست/غلط
بزند و بعد سه سؤال جواب بگیرند: آستانه جداکننده هست؟ عددش چند؟ و بازوزنیِ
`art_track` بهتر می‌کند یا بدتر؟

**اجرا (روی مستر، بدونِ rebuild):** اسکریپت از stdin به کانتینر داده می‌شود، پس
لازم نیست در ایمیج باشد:

    cd <repo> && docker compose exec -T download-worker python - \
        en=<playlist-url> multi=<playlist-url> fa=<playlist-url> hard=<playlist-url> \
        < tools/spotify_bench.py

هر آرگومان یک `<سطل>=<لینکِ اسپاتیفای>` است (ترک، آلبوم یا پلی‌لیست). نامِ سطل
دلخواه است؛ پیشنهادِ طراحی: `en` تک‌هنرمندِ انگلیسی · `multi` چندهنرمند
(feat/&/,) · `fa` فارسی و ایرانی · `hard` موردهای سخت (ریمیکسِ رسمی، لایو
آلبوم، ترکِ هم‌نام از هنرمندانِ مختلف). چند لینک در یک سطل هم مجاز است.

گزینه‌ها: `--per-bucket N` (پیش‌فرض ۱۰) · `--delay S` (پیش‌فرض ۲) · `--tsv <path>`.

**دو قیدِ عمدی:**
* **هیچ کوکی‌ای مصرف نمی‌شود** — `opts` بدونِ `cookies` می‌رود، پس جست‌وجوها
  ناشناس‌اند و سهمیهٔ هیچ اکانتی از استخرِ سشن نمی‌سوزد.
* **هیچ دانلودی انجام نمی‌شود** — فقط `_gather_candidates` + `_rank_candidates`.
  تأخیرِ پیش‌فرض بینِ ترک‌ها هست تا IPِ مستر پرچم نخورد.
"""
from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, "/srv")          # داخلِ کانتینر؛ بی‌ضرر اگر از ریشهٔ ریپو اجرا شود
sys.path.insert(0, ".")

from app import downloader as D     # noqa: E402


# ── جمع‌آوری ──────────────────────────────────────────────────────────────
async def resolve_bucket(url: str, per_bucket: int) -> list[dict]:
    """لینکِ اسپاتیفای → ترک‌ها، از **همان مسیری که تولید می‌رود** (embed).

    عمداً credential نمی‌دهیم: مسیرِ APIِ رسمی برای ما بسته است، پس سنجه باید
    همان متادیتایی را ببیند که ربات می‌بیند.
    """
    try:
        out = await D.spotify_resolve(url, "", "", per_bucket)
        return out.get("tracks") or []
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ resolve failed: {str(exc)[:120]}", file=sys.stderr)
        return []


async def measure(track: dict, opts: dict) -> dict:
    """یک ترک → نامزدها، رتبه‌بندی، و هرچه برای برچسب‌زدن لازم است."""
    t0 = time.monotonic()
    try:
        cands = await D._gather_candidates(track, opts, "ytmusic")
    except Exception as exc:  # noqa: BLE001
        return {"track": track, "error": str(exc)[:120]}
    ranked = D._rank_candidates(cands, track)
    win = ranked[0] if ranked else None
    runner = ranked[1] if len(ranked) > 1 else None
    row = {
        "track": track,
        "n_cands": len(cands),
        "n_ranked": len(ranked),
        "gated": len(cands) - len(ranked),
        "secs": time.monotonic() - t0,
        "score": win[0] if win else None,
        "runner": runner[0] if runner else None,
        "win_title": (win[1].get("title") if win else None),
        "win_url": (D._cand_url(win[1]) if win else None),
        "win_artists": (", ".join(D._cand_artists(win[1])) if win else ""),
        "art_track": bool(win[1].get("art_track")) if win else False,
        "source": (win[1].get("source") or "ytsearch") if win else "",
        "cand_dur": D._cand_dur(win[1]) if win else None,
    }
    td, cd = track.get("duration"), row["cand_dur"]
    row["ddiff"] = (cd - td) if (td and cd) else None
    return row


# ── نمایش ────────────────────────────────────────────────────────────────
def clip(s: str | None, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def mmss(sec: int | None) -> str:
    return "—" if not sec else f"{sec // 60}:{sec % 60:02d}"


def print_table(rows: list[tuple[str, dict]], min_score: float) -> None:
    """هر ترک یک بلوکِ چندخطی، نه یک ردیفِ ستون‌بندی‌شده.

    عمداً: با متنِ فارسی در کنارِ لاتین، ستون‌بندی **قابلِ اتکا نیست** — padding
    کاراکتر می‌شمارد نه عرضِ رندرشده، و الگوریتمِ bidi ترتیب را هم جابه‌جا می‌کند،
    پس جدولِ ستونی دقیقاً روی سطلِ فارسی از هم می‌پاشد. بلوک این را دور می‌زند.
    برای برچسب‌زدنِ انبوه، `--tsv` بهتر است (صفحه‌گسترده).
    """
    print()
    print("━" * 78)
    for i, (bucket, r) in enumerate(rows, 1):
        tr = r["track"]
        head = f"{i:3d} [{bucket}]"
        sp = f"{clip(tr.get('title'), 44)} — {clip(tr.get('artist'), 30)}"
        if r.get("error"):
            print(f"{head}  ✗ خطا: {clip(r['error'], 60)}")
            print(f"        اسپاتیفای: {sp}\n")
            continue
        if r["score"] is None:
            print(f"{head}  ⚠ هیچ نامزدی از گیت رد نشد ({r['n_cands']} نامزد) → ytsearch1 خام")
            print(f"        اسپاتیفای: {sp}\n")
            continue
        gap = f"Δ۲ {r['score'] - r['runner']:.0f}" if r["runner"] is not None else "تک‌نامزد"
        flags = " · ".join(filter(None, [
            gap,
            "art_track" if r["art_track"] else "",
            r["source"],
            "⚠ زیرِ آستانه" if r["score"] < min_score else "",
        ]))
        dd = "" if r["ddiff"] is None else f" (Δ {r['ddiff']:+d}s)"
        print(f"{head}  امتیاز {r['score']:6.1f}   [{flags}]        ✓/✗ ____")
        print(f"        اسپاتیفای: {sp} · {mmss(tr.get('duration'))}")
        print(f"        انتخاب   : {clip(r['win_title'], 44)} — "
              f"{clip(r['win_artists'], 26)} · {mmss(r['cand_dur'])}{dd}")
        print(f"        لینک     : {r['win_url']}")
        print(f"        نامزدها  : {r['n_ranked']} از {r['n_cands']} نامزد از گیت رد شدند\n")
    print("━" * 78)
    print("  Δ۲ = فاصلهٔ برنده تا نفرِ دوم (کم = انتخابِ شکننده)  ·  "
          f"آستانه = spotify_match_min {min_score:.0f}")
    print("  روی هر بلوک علامت بزن: ✓ ضبطِ درست  ·  ✗ غلط (نسخهٔ اشتباه یا خوانندهٔ اشتباه)")


def summarise(rows: list[tuple[str, dict]], min_score: float) -> None:
    buckets: dict[str, list[dict]] = {}
    for b, r in rows:
        buckets.setdefault(b, []).append(r)
    print()
    print(f"  {'سطل':<8}{'ترک':>5}{'بی‌نامزد':>10}{'زیرِ آستانه':>13}"
          f"{'میانهٔ امتیاز':>14}{'کمینه':>8}{'بیشینه':>8}{'art_track':>11}")
    print("  " + "─" * 78)
    for b, rs in list(buckets.items()) + ([("همه", [r for _, r in rows])] if len(buckets) > 1 else []):
        sc = sorted(r["score"] for r in rs if r.get("score") is not None)
        none_n = sum(1 for r in rs if r.get("score") is None and not r.get("error"))
        below = sum(1 for s in sc if s < min_score)
        med = sc[len(sc) // 2] if sc else 0
        at = sum(1 for r in rs if r.get("art_track"))
        print(f"  {b:<8}{len(rs):>5}{none_n:>10}{below:>13}{med:>14.1f}"
              f"{(sc[0] if sc else 0):>8.1f}{(sc[-1] if sc else 0):>8.1f}{at:>11}")
    print()
    print("  یادآوری: تا وقتی ستونِ ✓/✗ پر نشده، این اعداد فقط توزیع‌اند —")
    print("  نمی‌گویند آستانه درست را از غلط جدا می‌کند یا نه.")


def report_embed_fields(rows: list[tuple[str, dict]]) -> None:
    """سؤالِ بازِ album/year/isrc را همین‌جا جواب می‌دهد (مجانی، از دلِ همین اجرا)."""
    tracks = [r["track"] for _, r in rows]
    have = {k: sum(1 for t in tracks if t.get(k)) for k in ("album", "year", "isrc", "duration")}
    print()
    print("  متادیتای برگشتی از مسیرِ embed (از مجموعِ "
          f"{len(tracks)} ترک):  " + "  ·  ".join(f"{k}={v}" for k, v in have.items()))
    if have["album"] or have["year"] or have["isrc"]:
        print("  ⚠ مسیرِ embed فیلدی داد که فکر می‌کردیم نمی‌دهد — بولتِ «The Spotify Web API")
        print("    is closed to us» در CLAUDE.md §۷ و فیکسچرهای tests/test_spotify_matcher.py")
        print("    باید به‌روز شوند، و شاخهٔ ISRC از «مردهٔ عمدی» به «زنده» برمی‌گردد.")
    else:
        print("  ✓ مطابقِ انتظار: فقط عنوان/هنرمند/مدت. album و year و isrc خالی‌اند.")


# ── main ─────────────────────────────────────────────────────────────────
async def main() -> int:
    args = sys.argv[1:]
    per_bucket, delay, tsv_path = 10, 2.0, ""
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--per-bucket":
            i += 1; per_bucket = int(args[i])
        elif a == "--delay":
            i += 1; delay = float(args[i])
        elif a == "--tsv":
            i += 1; tsv_path = args[i]
        elif "=" in a:
            b, u = a.split("=", 1)
            pairs.append((b, u))
        else:
            pairs.append(("—", a))
        i += 1
    if not pairs:
        print(__doc__)
        return 2

    # کوکی عمداً پاس داده نمی‌شود: سنجه نباید سهمیهٔ استخرِ سشن را بسوزاند.
    opts: dict = {}
    rows: list[tuple[str, dict]] = []
    for bucket, url in pairs:
        print(f"» {bucket}: {url}", file=sys.stderr)
        tracks = await resolve_bucket(url, per_bucket)
        print(f"  {len(tracks)} ترک", file=sys.stderr)
        for tr in tracks:
            rows.append((bucket, await measure(tr, opts)))
            print(f"  · {clip(tr.get('title'), 40)}", file=sys.stderr)
            if delay:
                await asyncio.sleep(delay)

    min_score = 55.0
    print_table(rows, min_score)
    summarise(rows, min_score)
    report_embed_fields(rows)

    if tsv_path:
        cols = ["bucket", "sp_title", "sp_artist", "sp_duration", "score", "runner_up",
                "win_title", "win_artists", "win_url", "dur_diff", "art_track", "source",
                "n_cands", "n_ranked", "note", "correct"]

        def r1(v):  # امتیاز با یک رقمِ اعشار — دقتِ بیشتر در برچسب‌زدن فقط نویز است
            return f"{v:.1f}" if isinstance(v, float) else v

        with open(tsv_path, "w", encoding="utf-8") as fh:
            fh.write("\t".join(cols) + "\n")
            for b, r in rows:
                t = r["track"]
                note = r.get("error") or ("no-candidate-passed-the-gates"
                                          if r.get("score") is None else "")
                fh.write("\t".join(str(r1(x) if x is not None else "") for x in [
                    b, t.get("title"), t.get("artist"), t.get("duration"),
                    r.get("score"), r.get("runner"), r.get("win_title"), r.get("win_artists"),
                    r.get("win_url"), r.get("ddiff"), r.get("art_track"), r.get("source"),
                    r.get("n_cands"), r.get("n_ranked"), note, ""]) + "\n")
        print(f"\n  TSV نوشته شد: {tsv_path}  (ستونِ correct را پر کن)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
