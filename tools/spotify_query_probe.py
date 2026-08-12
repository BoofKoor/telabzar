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
import re
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
    """(ایندکس, دلیل) برای نامزدهایی که با هدف می‌خوانند — **قوی‌ها اول**.

    **دو معیار، عمداً:** تطبیقِ نامِ هنرمند، **یا** فقط مدت. دلیلش همان چیزی است
    که این ابزار برای آن ساخته شده — اگر ضبطِ درست با نامِ **فارسی** فهرست شده
    باشد («هایده» در برابرِ `Haydeh`)، معیارِ نامْ آن را نمی‌بیند و ابزار
    «پیدا نشد» گزارش می‌کند، یعنی دقیقاً همان مثبتِ کاذبی که ما را به مسیرِ
    اشتباه می‌فرستد. مدت این شکاف را پر می‌کند.

    **ولی دو معیارِ نامساوی نباید در یک فهرستِ مسطح قاتی شوند.** نسخهٔ اول
    اصابت‌ها را به ترتیبِ **استخر** برمی‌گرداند و هر دو صداکننده `[0]` را
    «هدف» می‌گیرند (`mark_of` برای چاپِ رتبه، و مسیرِ ادغام برای انتخابِ
    ویدیویی که رتبه‌بندی رویش سنجیده می‌شود). پس یک مثبتِ کاذبِ «فقط مدت» که
    در فهرست جلوتر بیفتد، اصابتِ واقعیِ «نام+مدت» را می‌پوشاند. اندازه‌گیری‌شده
    روی یک `Faryaad`ِ ۳۱۲ ثانیه‌ایِ دیگر که پیش از ضبطِ درستِ ۳۱۱ ثانیه‌ای
    می‌آمد: خروجی `[(0,'فقط مدت'), (2,'نام+مدت')]` بود و ابزار «رتبهٔ ۱» را
    برای ضبطِ **غلط** چاپ می‌کرد — همان «رتبهٔ ۳»ی که در گزارشِ قبلی مثبتِ
    کاذب از آب درآمد.

    حالا دو **رده** برمی‌گردد: نام+مدت، بعد فقط-مدت. ترتیبِ استخر داخلِ هر رده
    حفظ می‌شود (رده‌بندی است، نه مرتب‌سازیِ کامل) تا «رتبه»ی که چاپ می‌شود
    همان معنیِ قبلی را داشته باشد.
    """
    strong: list[tuple[int, str]] = []
    weak: list[tuple[int, str]] = []
    for i, c in enumerate(cands):
        arts = " ".join(D._cand_artists(c)).lower()
        dur = D._cand_dur(c)
        if not (dur and abs(dur - want_secs) <= tol):
            continue
        if want_artist.lower() in arts:
            strong.append((i, "نام+مدت"))
        else:
            weak.append((i, "فقط مدت — نامِ هنرمند شاید فارسی باشد"))
    return strong + weak


def mark_of(idx: list[tuple[int, str]]) -> str:
    """نشانِ یک‌خطیِ یک کوئری — و **نوعِ** اصابت را پنهان نمی‌کند.

    «✓ رتبهٔ ۳» برای اصابتی که فقط مدت خوانده، همان جمله‌ای است که ما را به
    نتیجهٔ غلط رساند. اصابتِ ضعیف حالا `؟` می‌گیرد و علتش را همراه دارد.
    """
    if not idx:
        return "✗ نیست"
    i, why = idx[0]
    if why.startswith("نام"):
        return f"✓ رتبهٔ {i + 1}"
    return f"؟ رتبهٔ {i + 1} (فقط مدت)"


def version_markers(title: str) -> list[str]:
    """کلمه‌های نسخه‌ای در عنوان — **از همان قاعدهٔ تولید**.

    نسخهٔ اولِ این تابع الگوی خودش را دست‌نویس می‌کرد. حالا تولید خودش
    `_version_markers` را دارد (روی متنِ حافظِ براکت، با مرزِ کلمه و فهرستِ
    صریحِ صورت‌ها)، پس نگه‌داشتنِ کپیِ دوم فقط راهی بود برای واگرا شدن — همان
    درسِ `remove_cookie_file`.
    """
    return sorted(D._version_markers(title))


def describe(c: dict) -> str:
    """شناسه + عنوانِ کامل + همهٔ هنرمندان + مدت — **بی‌برش**، چند خطی.

    خطِ برندهٔ نسخهٔ اول نه شناسه چاپ می‌کرد نه مدت، و فهرستِ هنرمند را روی ۲۴
    کاراکتر می‌بُرید (`'Anoushirvan Rohani, Maz…'`) — پس از خروجیِ ابزار
    نمی‌شد فهمید برنده **کدام ویدیو** است، و همین ابهامِ «برندهٔ ۱۰۳٫۲» را
    بی‌جواب گذاشت. این تابع برای همان یک سؤال است، پس چیزی را کوتاه نمی‌کند.

    نشانهٔ نسخه هم چاپ می‌شود، چون معیارِ `hits()` (هنرمند + مدت) ریمیکسِ همان
    هنرمند با همان طول را هم «هدف» می‌شمارد — با اجرای خشکِ ابزار پیدا شد، نه
    با استدلال.
    """
    arts = ", ".join(D._cand_artists(c)) or "—"
    dur = D._cand_dur(c)
    marks = version_markers(c.get("title") or "")
    out = (f"{D._cand_url(c)}\n"
           f"        عنوان : {c.get('title')}\n"
           f"        هنرمند: {arts}\n"
           f"        مدت   : {dur if dur is not None else '—'}s")
    if marks:
        out += f"\n        ⚠ نشانهٔ نسخه: {', '.join(marks)}  ← ضبطِ اصلی نیست؟"
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
        print(f"  {mark_of(idx):<22} {name:<24} {q!r}   ({len(cands)} نامزد)")
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
        print(f"  هدف   : [{midx[0][1]}]\n        {describe(target)}")
        pos = next((n for n, (_, c) in enumerate(ranked, 1)
                    if D._cand_url(c) == D._cand_url(target)), None)
        print(f"  و بعد از رتبه‌بندی: {'رتبهٔ ' + str(pos) if pos else '**گیت خورد**'}"
              f"  (از {len(ranked)} بازمانده)")
        if ranked:
            win = ranked[0][1]
            print(f"  برندهٔ فعلی ({ranked[0][0]:.1f}):\n        {describe(win)}")
            # همان سؤالی که ابهامِ «برندهٔ ۱۰۳٫۲» رویش بود — ولی **بیش از آنچه
            # سنجیده شده ادعا نمی‌کند**. تنها چیزی که این‌جا معلوم است این است
            # که برنده همان ویدیوی هدف است یا نه؛ و «هدف» صرفاً با نامِ هنرمند
            # + مدت تشخیص داده شده، پس نسخه/ریمیکسِ همان هنرمند با همان طول هم
            # واجدِ شرط است. با اجرای خشکِ ابزار پیدا شد: یک ریمیکسِ ۳۱۱ ثانیه‌ای
            # از همان هنرمند «هدف» شمرده شد و ابزار می‌گفت «همان ضبطِ درست است».
            same = D._cand_url(win) == D._cand_url(target)
            if same:
                print("\n  ⇒ برنده = همان ویدیوی هدف")
                if version_markers(win.get("title") or ""):
                    print("     ⚠ ولی عنوانش نشانهٔ نسخه دارد — با چشم بسنج، "
                          "ممکن است ضبطِ اصلی نباشد")
                else:
                    print("     (معیارِ هدف = هنرمند + مدت؛ عنوانِ بالا را با چشم تأیید کن)")
            else:
                print("\n  ⇒ برنده ویدیوی هدف **نیست**  ← ادغام به‌تنهایی کافی نیست")
    print("\n  ⇒ اگر ادغام هدف را می‌آورد ولی رتبه‌بندی نمی‌بردش، مسئله دوباره امتیازدهی است.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
