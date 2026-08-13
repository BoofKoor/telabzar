#!/usr/bin/env python3
"""دو عددی که انتخابِ `_ALBUM_UNKNOWN` رویشان بند است — و سؤالِ بازِ شکلِ کوئری.

اپل برخلافِ اسپاتیفای **همیشه** `collectionName` می‌دهد، پس مؤلفهٔ آلبوم
(وزنِ ۰٫۰۸) که تا امروز هرگز شلیک نمی‌کرد، از فردا برای هر ترکِ اپل شلیک
می‌کند. سنجیده‌شده در سندباکس: با مرجعِ آلبوم‌دار، نامزدی که آلبومش را
**نمی‌گوید** (۱۰۶٫۰۰) از نامزدی که می‌گوید و **مخالف است** (۹۹٫۹۴) بالاتر
می‌نشیند — همان شکلِ «نمی‌دانم مثلِ کاملْ امتیاز می‌گیرد» که `_TIME_UNKNOWN`
برای مدت بست.

رفعش یک عددِ خنثی است، ولی آن عدد را **نباید حدس زد**. دو چیز لازم است و هر
دو از YouTube Music می‌آیند که از سندباکسِ توسعه در دسترس نیست:

  ۱. چه کسری از نامزدهای `songs` اصلاً `album` دارند؟ (اگر تقریباً همه دارند،
     نبودِ آلبوم حالتِ نادر است و عدد کم اهمیت دارد؛ اگر نصف‌به‌نصف است، عدد
     مستقیماً رتبه‌بندی را جابه‌جا می‌کند.)
  ۲. وقتی آلبوم **هست**، توزیعِ `_album_match` چیست؟ اختلاف‌ها عمدتاً
     «گلچین/تک‌آهنگ در برابرِ آلبومِ اصلی» است یا واقعاً ضبطِ دیگری؟ این
     تعیین می‌کند عددِ خنثی باید وسط باشد یا بالاتر.

و هم‌زمان سؤالِ بازِ دیگر را جواب می‌دهد: **آیا کوئریِ پرانتزدار واقعاً نتیجهٔ
بدتری می‌گیرد؟** چون اپل مهمان را داخلِ عنوان می‌گذارد
(`"Faryaad (feat. Karim Fakour)"`)، کوئریِ ساخته‌شده از عنوانِ خام آن پرانتز
را با خودش می‌برد. *شکلِ* کوئری در سندباکس سنجیده شد؛ *کیفیتِ نتیجه* فقط
این‌جا سنجیدنی است.

**اجرا روی مستر** (نه سندباکس — `itunes.apple.com` و YouTube Music هر دو
آن‌جا ۴۰۳ می‌دهند):

    docker compose exec -T download-worker python - \
        662720286 305568690 617154366 \
        < tools/apple_album_probe.py

گزینه‌ها:
  `--country us`  فروشگاهِ lookup (پیش‌فرض us)
  `--delay S`     فاصلهٔ بینِ جست‌وجوها (پیش‌فرض ۲؛ **صفرش نکن**)
  `--limit N`     سقفِ نامزد در هر جست‌وجو (پیش‌فرض ۶، همان مقدارِ تولید)

هرچه بیشتر شناسه بدهی عدد معنادارتر است؛ ترکِ ایرانی و غربی را قاطی کن،
وگرنه نتیجه یک‌سویه می‌شود. **کوکی مصرف نمی‌شود و چیزی دانلود نمی‌شود.**

⚠ **چرا این ابزار lookupِ خودش را دارد:** باید **قبل از** نوشتنِ
`apple_resolve` اجرا شود — عددش همان چیزی است که طراحی را تعیین می‌کند، پس
نمی‌تواند به کدی وابسته باشد که هنوز وجود ندارد. برای اینکه بعداً به کپیِ
دومِ واگرا تبدیل نشود، اگر `downloader.apple_resolve` موجود باشد **همان**
استفاده می‌شود و ابزار می‌گوید از کدام مسیر رفته. همین قاعده برای استخراجِ
feat هم هست. هر چیزِ دیگری (تفکیکِ هنرمند، امتیازِ آلبوم، نشانهٔ نسخه،
رتبه‌بندی) مستقیم از تولید صدا زده می‌شود — هیچ قاعده‌ای این‌جا بازنویسی نشده.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys

sys.path.insert(0, "/srv")
sys.path.insert(0, ".")

from app import downloader as D     # noqa: E402

ITUNES = "https://itunes.apple.com/lookup"

# پرانتز/براکتی که محتوایش **با** نشانهٔ feat شروع می‌شود — و نه چیزِ دیگری.
#
# `with` عمداً **نیست**، اندازه‌گیری‌شده: با آن، «Song (With Strings)» هم پاک
# می‌شد و «Strings» هنرمند حساب می‌شد، در حالی که آن یک نشانهٔ تنظیم است نه
# اعتبارِ مهمان. «Song (Live with the Orchestra)» در هر دو حالت سالم می‌ماند،
# چون محتوایش با `Live` شروع می‌شود نه با `with` — پس ریسک فقط `with`ِ آغازین
# بود و حذفش هزینه‌ای نداشت.
#
# این الگو عمداً **جراحی** است: فقط براکتِ feat را برمی‌دارد، نه هر براکتی.
# سنجیده‌شده که `[Daft Punk Remix]`, `(Radio Edit)`, `(Live)` و `[Extended Mix]`
# دست‌نخورده می‌مانند و `_version_markers` هنوز می‌بیندشان — وگرنه پاک‌سازی
# دقیقاً همان چیزی را نابود می‌کرد که جریمهٔ نسخه برای گرفتنش هست.
_FEAT_BRACKET = re.compile(r"\s*[\(\[]\s*(?:feat|ft|featuring)\b\.?\s*([^)\]]*)[\)\]]", re.I)


def _fallback_feat_split(track_name: str, artist_name: str) -> tuple[str, str]:
    """(عنوانِ پاک, هنرمندانِ ادغام‌شده) — نسخهٔ موقتِ ابزار، تا تولید داشته باشدش.

    تفکیک با `D._ARTIST_SPLIT_RE`ِ تولید انجام می‌شود و مقایسهٔ تکراری با
    `D._norm`ِ تولید، پس تنها چیزی که این‌جا دست‌نویس است خودِ الگوی براکت است.
    """
    guests: list[str] = []
    for blob in _FEAT_BRACKET.findall(track_name or ""):
        guests += [g.strip() for g in D._ARTIST_SPLIT_RE.split(blob) if g.strip()]
    names = [a.strip() for a in D._ARTIST_SPLIT_RE.split(artist_name or "") if a.strip()]
    seen = {D._norm(a) for a in names}
    for g in guests:
        if D._norm(g) not in seen:
            seen.add(D._norm(g))
            names.append(g)
    return _FEAT_BRACKET.sub("", track_name or "").strip(), ", ".join(names)


async def _lookup(track_id: str, country: str) -> dict | None:
    """ردیفِ ترکِ اپل، یا None. **همه‌جا `.get()`، هیچ‌جا اندیس.**

    سه شکلِ خرابی سنجیده شد و هر سه این‌جا پوشش دارد: `resultCount == 0` برای
    شناسهٔ باطل (اندیس‌زدن `IndexError` می‌دهد)؛ ردیفِ **collection** که نه
    `kind` دارد نه `trackId` نه `trackName`؛ و کلیدهای اختیاری مثلِ
    `collectionArtistName` که روی ترکِ واقعی هم می‌توانند غایب باشند.
    """
    import aiohttp
    url = f"{ITUNES}?id={track_id}&country={country}&entity=song"
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url) as r:
            if r.status != 200:
                print(f"  ✗ lookup HTTP {r.status} برای {track_id}", file=sys.stderr)
                return None
            body = await r.text()
    try:
        data = json.loads(body)
    except ValueError:
        print(f"  ✗ پاسخِ غیرِJSON برای {track_id}", file=sys.stderr)
        return None
    rows = data.get("results") or []
    if not rows:
        print(f"  ✗ resultCount=0 برای {track_id} (شناسهٔ باطل یا حذف‌شده)", file=sys.stderr)
        return None
    row = rows[0]
    if row.get("wrapperType") != "track" or row.get("kind") != "song":
        print(f"  ✗ {track_id} ترکِ آهنگ نیست: wrapperType={row.get('wrapperType')!r} "
              f"kind={row.get('kind')!r} collectionType={row.get('collectionType')!r}"
              f" — لینکِ آلبوم است؟ (فازِ ب)", file=sys.stderr)
        return None
    return row


async def reference(track_id: str, country: str) -> dict | None:
    """مرجعِ ترک به همان شکلی که ماچر می‌خواهد، از مسیرِ تولید اگر بود."""
    resolver = getattr(D, "apple_resolve", None)
    if resolver is not None:
        # امضای تولید هنوز نوشته نشده، پس این فراخوانی یک حدس است. اگر نخورْد
        # **بلند** می‌گوید و به lookupِ درون‌ابزاری برمی‌گردد — سقوطِ خاموش به
        # مسیرِ ضعیف‌تر دقیقاً همان چیزی است که پارسرِ اسپاتیفای را هفته‌ها
        # مرده نگه داشت.
        try:
            res = await resolver(f"https://music.apple.com/{country}/song/x/{track_id}")
            tr = (res.get("tracks") or [None])[0]
            if tr:
                tr["_via"] = "apple_resolve (تولید)"
                return tr
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ apple_resolve هست ولی این‌طور صدا زده نمی‌شود ({exc!r}) — "
                  f"امضایش عوض شده؛ ابزار به lookupِ خودش برگشت و باید به‌روز شود",
                  file=sys.stderr)
    row = await _lookup(track_id, country)
    if row is None:
        return None
    title, artist = _fallback_feat_split(row.get("trackName") or "", row.get("artistName") or "")
    ms = row.get("trackTimeMillis")
    return {
        "title": title,
        "raw_title": row.get("trackName") or "",
        "artist": artist,
        "raw_artist": row.get("artistName") or "",
        "album": row.get("collectionName") or "",
        "year": str(row.get("releaseDate") or "")[:4],
        "cover_url": row.get("artworkUrl100"),
        "duration": round((ms or 0) / 1000) or None,
        "isrc": None,
        "_via": "lookupِ درون‌ابزاری (apple_resolve هنوز وجود ندارد)",
    }


def target_index(cands: list[dict], track: dict, tol: int = 20) -> int | None:
    """ایندکسِ نامزدی که «همان ضبط» به‌نظر می‌رسد: هنرمند + مدت.

    همان معیارِ دوبخشیِ `spotify_query_probe.hits` است و همان محدودیت را دارد
    (ریمیکسِ همان هنرمند با همان طول هم واجدِ شرط می‌شود) — پس این عدد برای
    **مقایسهٔ دو شکلِ کوئری با هم** است، نه برای اعلامِ «ضبطِ درست پیدا شد».
    """
    want = {D._norm(a) for a in D._track_artists(track)}
    dur = track.get("duration")
    for i, c in enumerate(cands):
        cd = D._cand_dur(c)
        if not (dur and cd and abs(cd - dur) <= tol):
            continue
        if any(D._norm(a) in want for a in D._cand_artists(c)):
            return i
    return None


def rank_of(cands: list[dict], track: dict, idx: int | None) -> str:
    if idx is None:
        return "نیست"
    url = D._cand_url(cands[idx])
    ranked = D._rank_candidates(cands, track)
    pos = next((n for n, (_, c) in enumerate(ranked, 1) if D._cand_url(c) == url), None)
    return f"استخر {idx + 1} → رتبه {pos}" if pos else f"استخر {idx + 1} → **گیت خورد**"


def clip(s, n: int) -> str:
    s = (str(s) if s is not None else "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


async def main() -> int:
    ids, country, delay, limit = [], "us", 2.0, 6
    args, i = sys.argv[1:], 0
    while i < len(args):
        a = args[i]
        if a == "--country":  i += 1; country = args[i]
        elif a == "--delay":  i += 1; delay = float(args[i])
        elif a == "--limit":  i += 1; limit = int(args[i])
        elif not a.startswith("--"): ids.append(a)
        i += 1
    if not ids:
        print(__doc__)
        return 2

    # شمارنده‌های تجمعی — همان دو عددی که طراحی رویشان بند است.
    #
    # **روی نامزدِ یکتای هر ترک شمرده می‌شود، نه روی هر فراخوانیِ جست‌وجو.**
    # نسخهٔ اول در حلقهٔ سرچ `+= len(got)` می‌کرد، پس یک نامزد به‌ازای هر کوئری
    # و هر شکل چند بار شمرده می‌شد و مخرج بی‌معنا می‌شد (اجرای خشک: ۴۴ برای
    # ۴ نامزد). کسری که از آن درمی‌آمد کسرِ چیزی نبود.
    have_album = {"songs": [0, 0], "videos": [0, 0]}     # [دارای آلبوم, کل]
    buckets = {"same (≥90)": 0, "variant (45..90)": 0, "different (<45)": 0}
    survived = missing_album = 0
    examples: list[str] = []
    qwin = {"خام": 0, "پاک": 0, "هیچ‌کدام": 0, "هر دو": 0}
    qrank: dict[str, list[int]] = {"خام": [], "پاک": []}

    for tid in ids:
        print(f"\n{'=' * 78}\n▸ {tid}")
        tr = await reference(tid, country)
        if tr is None:
            continue
        print(f"  مسیر : {tr.get('_via')}")
        print(f"  عنوان: {tr.get('raw_title') or tr['title']!r}"
              + (f"  → پاک‌شده {tr['title']!r}" if tr.get("raw_title") not in (None, tr["title"]) else ""))
        print(f"  هنرمند: {tr.get('raw_artist', tr['artist'])!r}"
              + (f"  → با مهمان {tr['artist']!r}" if tr.get("raw_artist") not in (None, tr["artist"]) else ""))
        print(f"  آلبوم : {tr['album']!r}   مدت: {tr['duration']}s   "
              f"تفکیکِ هنرمند: {D._track_artists(tr)}")
        if not tr.get("album"):
            print("  ⚠ این ترک `collectionName` ندارد — برای سؤالِ آلبوم بی‌فایده است")

        # ── سؤالِ کوئری: عنوانِ خامِ اپل در برابرِ عنوانِ پاک‌شده ──
        raw_ref = {**tr, "title": tr.get("raw_title") or tr["title"],
                   "artist": tr.get("raw_artist") or tr["artist"]}
        shapes = {"خام": D._search_queries(raw_ref), "پاک": D._search_queries(tr)}
        pools: dict[str, list[dict]] = {}
        for lbl, queries in shapes.items():
            pool: dict[str, dict] = {}
            for q in queries:
                for filt in ("songs", "videos"):
                    got = await D._ytmusic_search(q, filt, None, limit=limit)
                    if not got:
                        continue
                    for c in got:
                        pool.setdefault(D._cand_url(c) or repr(c), c)
                    if delay:
                        await asyncio.sleep(delay)
                    if filt == "songs" and len(pool) >= 3:
                        break            # همان گیتِ تولید: songs بس بود → videos نگیر
            pools[lbl] = list(pool.values())
            idx = target_index(pools[lbl], tr)
            print(f"  کوئریِ {lbl:4}: {len(queries)} شکل، {len(pools[lbl])} نامزدِ یکتا"
                  f"   هدف: {rank_of(pools[lbl], tr, idx)}")
            for q in queries:
                print(f"           {q!r}")
            if idx is not None:
                qrank[lbl].append(idx + 1)
        fr, fc = target_index(pools["خام"], tr), target_index(pools["پاک"], tr)
        qwin["هر دو" if fr is not None and fc is not None else
             "خام" if fr is not None else
             "پاک" if fc is not None else "هیچ‌کدام"] += 1

        # پوششِ آلبوم روی نامزدهای **یکتا**ی همین ترک، به تفکیکِ فیلتر.
        for c in pools["پاک"]:
            filt = "songs" if c.get("art_track") else "videos"
            have_album[filt][1] += 1
            have_album[filt][0] += 1 if c.get("album") else 0

        # ── سؤالِ آلبوم: توزیع فقط روی **بازماندگانِ رتبه‌بندی** ──
        #
        # عمداً نه روی کلِ استخر. نامزدی که گیت‌های نام/مدت/هنرمند را رد نکرده
        # اصلاً امتیاز نمی‌گیرد، پس آلبومش هیچ تصمیمی را عوض نمی‌کند — ولی در
        # آمار می‌نشیند و «different» را پر می‌کند. اجرای خشک نشان داد چطور:
        # آلبومِ یک ویدیوی کاملاً بی‌ربط با آلبومِ مرجع مقایسه می‌شد و ۷۸٪
        # «different» می‌داد، عددی که به سؤالِ ما ربطی نداشت. سؤالِ درست این
        # است: «وقتی نامزدی که **واقعاً رقیب است** آلبومش را می‌گوید، چقدر
        # می‌خواند؟»
        if tr.get("album"):
            ranked = D._rank_candidates(pools["پاک"], tr)
            print(f"  آلبومِ بازماندگانِ رتبه‌بندی ({len(ranked)} از {len(pools['پاک'])} نامزد):")
            for score, c in ranked:
                survived += 1
                calb = c.get("album")
                sc = D._album_match(tr, c)
                if sc is None:
                    missing_album += 1
                    tag = "— آلبوم ندارد (مؤلفه حذف ⇒ نمرهٔ کامل)"
                else:
                    key = ("same (≥90)" if sc >= 90 else
                           "variant (45..90)" if sc >= 45 else "different (<45)")
                    buckets[key] += 1
                    tag = f"{sc:5.1f}  [{key}]"
                    if key == "different (<45)" and len(examples) < 12:
                        examples.append(f"{clip(tr['album'], 28)!r} ↔ {clip(calb, 28)!r}  ({sc:.1f})")
                marks = sorted(D._version_markers(c.get("title") or ""))
                print(f"    {score:6.1f} {clip(c.get('title'), 36):38} {clip(calb, 28):30} {tag}"
                      + (f"  ⚠{','.join(marks)}" if marks else ""))

    # ── جمع‌بندی ──
    print(f"\n{'=' * 78}\n### دو عددی که `_ALBUM_UNKNOWN` رویشان بند است\n")
    for filt, (n, tot) in have_album.items():
        pct = f"{100 * n / tot:.0f}%" if tot else "—"
        print(f"  نامزدهای یکتای «{filt}» که آلبوم دارند : {n}/{tot}  ({pct})")
    print("  نامزدهای ytsearch                     : ساختاراً صفر (yt-dlp کلیدِ album ندارد)")
    pct_m = f"{100 * missing_album / survived:.0f}%" if survived else "—"
    print(f"\n  ▸ عددِ اصلی — بازماندگانِ رتبه‌بندی که آلبوم **ندارند**: "
          f"{missing_album}/{survived}  ({pct_m})")
    print("    این‌ها دقیقاً همان‌هایی‌اند که امروز «نمرهٔ کاملِ آلبوم» می‌گیرند.")
    tot_b = sum(buckets.values())
    print(f"\n  توزیعِ `_album_match` روی بازماندگانی که آلبوم **دارند** (n={tot_b}):")
    for k, v in buckets.items():
        pct = f"{100 * v / tot_b:.0f}%" if tot_b else "—"
        print(f"    {k:20} {v:4}  ({pct})")
    if examples:
        print("\n  نمونه‌های «different» — بخوان و ببین گلچین/تک‌آهنگ است یا ضبطِ دیگر:")
        for e in examples:
            print(f"    {e}")
    print("\n  ⇒ اگر «بازماندهٔ بی‌آلبوم» نادر باشد، عددِ خنثی کم‌اهمیت است و وسط بس است.")
    print("  ⇒ اگر «different» عمدتاً گلچین/تک‌آهنگ باشد، خودِ مؤلفه بیش از حد جریمه می‌کند")
    print("     و عددِ خنثی باید بالاتر از وسط بنشیند — این را با چشم قضاوت کن، نه با عدد.")

    print(f"\n### شکلِ کوئری — عنوانِ خامِ اپل در برابرِ عنوانِ پاک‌شده\n")
    for k, v in qwin.items():
        print(f"  هدف پیدا شد با {k:9}: {v}")
    for k, v in qrank.items():
        avg = f"{sum(v) / len(v):.1f}" if v else "—"
        print(f"  میانگینِ رتبهٔ استخر ({k:4}): {avg}   (n={len(v)})")
    print("\n  ⇒ «هر دو» با رتبه‌های نزدیک یعنی پرانتز بی‌ضرر است و پاک‌سازی فقط")
    print("     برای دو شکل‌شدنِ کوئری و بستنِ جریمهٔ کاذب می‌ارزد — نه برای کیفیتِ سرچ.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
