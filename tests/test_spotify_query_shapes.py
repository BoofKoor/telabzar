"""شکلِ کوئریِ اسپاتیفای: «هنرمندِ اول + عنوان» و «هنرمندِ آخر + عنوان».

کوئریِ قبلی **همهٔ** هنرمندان را با ویرگول به‌هم می‌چسباند
(`"Anoushirvan Rohani, Haydeh Faryad"`) و برای موسیقیِ ایرانی این یعنی
«آهنگساز, خواننده» با آهنگسازِ اول. probeِ زنده روی مستر (۲۰۲۶-۰۸-۱۲) نشان داد
آن شکل ضبطِ درست را **اصلاً برنمی‌گرداند** — تنها چیزی که داد یک مثبتِ کاذبِ
«فقط مدت» در رتبهٔ ۳ بود. در همان اجرا:

    هنرمندِ اول + عنوان → رتبهٔ ۱   (نام+مدت)
    هنرمندِ آخر + عنوان → رتبهٔ ۲   (نام+مدت)
    ادغام               → ۶۱ نامزدِ یکتا، برنده `WUxurPJmKXI` با ۱۰۳٫۲،
                          که اپراتور با چشم تأیید کرد همان ضبطِ درست است

**دو شکلی که حذف شدند و دلیلشان:** «همهٔ هنرمندان با ویرگول» و «بدونِ ویرگول»
هدف را نیاوردند؛ «فقط عنوان» آورد ولی در رتبهٔ ۱۶ (Faryad) و ۱۰ (Jane Maryam)
و هر دو وقتی شکل‌های دیگر از قبل هدف را آورده بودند — پس هزینهٔ یک فراخوانیِ
اضافه را نمی‌ارزد.

**چرا اول و آخر، نه فقط اول:** اسپاتیفای برای موسیقیِ کلاسیکِ ایرانی آهنگساز را
اول می‌گذارد، پس «آخر» خواننده است — و خواننده چیزی است که ضبط را می‌شناساند.
برای انتشارِ غربی «اول» هنرمندِ اصلی است. دو شکل هر دو قاعده را می‌پوشاند.

**هزینه:** ترکِ تک‌هنرمند به **یک** کوئری فرو می‌ریزد (بی‌تغییر از قبل)،
چندهنرمند دو. گیتِ «استخر کم‌عمق است» روی استخرِ **ادغام‌شده** سنجیده می‌شود نه
به‌ازای هر شکل، و fallbackها به‌محضِ پرشدنِ استخر می‌ایستند — وگرنه شکل‌های
بیشتر یعنی fallbackهای بیشتر.

**ترتیبی، نه هم‌زمان:** `_ytmusic_search` روی ۴۲۹ خطا را می‌بلعد و `[]`
برمی‌گرداند (`downloader.py:1617-1620`)، یعنی شکستِ خاموش؛ دو برابر کردنِ نرخِ
لحظه‌ای روی endpointِ بی‌احراز-هویت این را محتمل‌تر می‌کند.
"""
from __future__ import annotations

import asyncio

import pytest

from app import downloader as D

FARYAD = {"title": "Faryad", "artist": "Anoushirvan Rohani, Haydeh", "duration": 311}
JANE = {"title": "Jane Maryam", "artist": "Mohammad Nouri", "duration": 311}

DEAD_COMMA = "Anoushirvan Rohani, Haydeh Faryad"   # شکلی که اثباتاً هدف را نمی‌آورد


def ytm(vid: str, title: str, arts: list[str], dur: int, art_track: bool = True) -> dict:
    """نامزد با همان کلیدهایی که `_norm_ytm` می‌سازد."""
    return {"id": vid, "title": title, "artists": arts, "album": None,
            "duration_seconds": dur, "art_track": art_track, "source": "ytmusic"}


# ── شکلِ کوئری ──────────────────────────────────────────────────────────────
def test_the_shapes_are_exactly_first_artist_and_last_artist():
    assert D._search_queries(FARYAD) == ["Anoushirvan Rohani Faryad", "Haydeh Faryad"]


def test_the_measured_dead_shapes_are_not_issued():
    """شکلِ کامایی و «فقط عنوان» نباید ساخته شوند — هزینه بی‌نتیجه."""
    qs = D._search_queries(FARYAD)
    assert DEAD_COMMA not in qs
    assert "Anoushirvan Rohani  Haydeh Faryad" not in qs
    assert "Faryad" not in qs, "«فقط عنوان» حذف شد (رتبهٔ ۱۶ و بی‌فایده)"


def test_a_single_artist_track_collapses_to_one_query():
    """اول و آخر یکی‌اند → یک کوئری، پس هزینه از امروز بیشتر نمی‌شود."""
    assert D._search_queries(JANE) == ["Mohammad Nouri Jane Maryam"]


def test_a_three_artist_track_uses_the_ends_not_the_middle():
    tr = {"title": "Get Lucky",
          "artist": "Daft Punk, Pharrell Williams, Nile Rodgers", "duration": 248}
    assert D._search_queries(tr) == ["Daft Punk Get Lucky", "Nile Rodgers Get Lucky"]


def test_a_track_with_no_artist_falls_back_to_the_title():
    assert D._search_queries({"title": "Faryad", "artist": ""}) == ["Faryad"]
    assert D._search_queries({"title": "Faryad"}) == ["Faryad"]


def test_a_track_with_neither_title_nor_artist_yields_no_query():
    """بدونِ عنوان و هنرمند، جست‌وجویی معنی ندارد — کوئریِ تهی نفرست."""
    assert D._search_queries({}) == []
    assert D._search_queries({"title": "", "artist": ""}) == []


def test_the_split_separators_still_apply():
    """`_track_artists` جداکننده‌های غیرِویرگول را هم می‌شکند."""
    tr = {"title": "Work", "artist": "Drake & Rihanna", "duration": 219}
    assert D._search_queries(tr) == ["Drake Work", "Rihanna Work"]


# ── جمع‌آوریِ نامزد ─────────────────────────────────────────────────────────
class Recorder:
    """جایگزینِ `_ytmusic_search` که فراخوان‌ها و هم‌پوشانی‌شان را ثبت می‌کند."""

    def __init__(self, by_query: dict[tuple[str, str], list[dict]] | None = None,
                 default: list[dict] | None = None):
        self.by_query = by_query or {}
        self.default = default if default is not None else []
        self.calls: list[tuple[str, str]] = []
        self.inside = 0
        self.max_inside = 0

    async def __call__(self, query, filt, proxy, limit=6, timeout=20):
        self.inside += 1
        self.max_inside = max(self.max_inside, self.inside)
        self.calls.append((query, filt))
        await asyncio.sleep(0)          # فرصتِ واقعی برای هم‌پوشانی، اگر هم‌زمان بود
        try:
            return list(self.by_query.get((query, filt), self.default))
        finally:
            self.inside -= 1


async def test_each_shape_gets_its_own_songs_search(monkeypatch):
    rec = Recorder(default=[ytm("a", "Faryad", ["Haydeh"], 311),
                            ytm("b", "Faryad", ["Haydeh"], 312),
                            ytm("c", "Faryad", ["Haydeh"], 310)])
    monkeypatch.setattr(D, "_ytmusic_search", rec)
    await D._gather_candidates(FARYAD, {}, "ytmusic")
    assert rec.calls == [("Anoushirvan Rohani Faryad", "songs"), ("Haydeh Faryad", "songs")]


async def test_the_searches_are_sequential_not_concurrent(monkeypatch):
    """۴۲۹ بی‌صدا `[]` می‌دهد، پس نرخِ لحظه‌ای را دو برابر نکن."""
    rec = Recorder(default=[ytm("a", "Faryad", ["Haydeh"], 311)])
    monkeypatch.setattr(D, "_ytmusic_search", rec)
    monkeypatch.setattr(D, "_yt_search_candidates", _no_ytsearch)
    await D._gather_candidates(FARYAD, {}, "ytmusic")
    assert rec.max_inside == 1, "دو جست‌وجو هم‌زمان اجرا شدند"


async def _no_ytsearch(query, opts, limit=6, timeout=60):
    return []


async def test_candidates_from_both_shapes_are_merged_and_deduped(monkeypatch):
    """ویدیوی مشترک یک‌بار بیاید، ویدیوی مخصوصِ هر شکل هم بیاید."""
    shared = ytm("shared", "Faryad", ["Haydeh"], 311)
    rec = Recorder(by_query={
        ("Anoushirvan Rohani Faryad", "songs"): [shared, ytm("onlyA", "Faryad", ["X"], 311)],
        ("Haydeh Faryad", "songs"): [dict(shared), ytm("onlyB", "Faryad", ["Y"], 311)],
    })
    monkeypatch.setattr(D, "_ytmusic_search", rec)
    monkeypatch.setattr(D, "_yt_search_candidates", _no_ytsearch)
    out = await D._gather_candidates(FARYAD, {}, "ytmusic")
    ids = [c["id"] for c in out]
    assert ids == ["shared", "onlyA", "onlyB"], f"ادغام/dedup درست نشد: {ids}"


async def test_dedup_keeps_the_first_hit_and_its_art_track_flag(monkeypatch):
    """`songs` اول می‌آید، پس `art_track=True` باید بماند نه نسخهٔ `videos`.

    اگر نسخهٔ دوم برنده شود، بونوسِ +۶ـِ Art Track بی‌صدا از دست می‌رود.
    """
    rec = Recorder(by_query={
        ("Anoushirvan Rohani Faryad", "songs"): [ytm("v", "Faryad", ["Haydeh"], 311, True)],
        ("Haydeh Faryad", "songs"): [ytm("v", "Faryad", ["Haydeh"], 311, False)],
    })
    monkeypatch.setattr(D, "_ytmusic_search", rec)
    monkeypatch.setattr(D, "_yt_search_candidates", _no_ytsearch)
    out = await D._gather_candidates(FARYAD, {}, "ytmusic")
    assert len(out) == 1
    assert out[0]["art_track"] is True


async def test_the_thin_pool_gate_reads_the_merged_pool(monkeypatch):
    """دو شکل که هرکدام ۲ نامزد می‌دهند = استخرِ ۴ → **نباید** به `videos` بیفتد.

    گیت به‌ازای هر شکل می‌بود، هر دو (۲ < ۳) fallback می‌گرفتند.
    """
    rec = Recorder(by_query={
        ("Anoushirvan Rohani Faryad", "songs"): [ytm("a1", "Faryad", ["Haydeh"], 311),
                                                 ytm("a2", "Faryad", ["Haydeh"], 312)],
        ("Haydeh Faryad", "songs"): [ytm("b1", "Faryad", ["Haydeh"], 313),
                                     ytm("b2", "Faryad", ["Haydeh"], 314)],
    })
    monkeypatch.setattr(D, "_ytmusic_search", rec)
    monkeypatch.setattr(D, "_yt_search_candidates", _no_ytsearch)
    out = await D._gather_candidates(FARYAD, {}, "ytmusic")
    assert len(out) == 4
    assert [f for _q, f in rec.calls] == ["songs", "songs"], \
        f"به videos افتاد در حالی که استخر ۴ نامزد داشت: {rec.calls}"


async def test_the_videos_fallback_stops_once_the_pool_is_deep_enough(monkeypatch):
    """استخر که پر شد، شکلِ بعدی فراخوان نمی‌خورد — سقفِ هزینه."""
    rec = Recorder(by_query={
        ("Anoushirvan Rohani Faryad", "videos"): [ytm("v1", "Faryad", ["Haydeh"], 311, False),
                                                  ytm("v2", "Faryad", ["Haydeh"], 312, False),
                                                  ytm("v3", "Faryad", ["Haydeh"], 313, False)],
    })
    monkeypatch.setattr(D, "_ytmusic_search", rec)
    monkeypatch.setattr(D, "_yt_search_candidates", _no_ytsearch)
    await D._gather_candidates(FARYAD, {}, "ytmusic")
    assert rec.calls == [("Anoushirvan Rohani Faryad", "songs"),
                         ("Haydeh Faryad", "songs"),
                         ("Anoushirvan Rohani Faryad", "videos")], \
        f"شکلِ دومِ videos هم صدا زده شد: {rec.calls}"


async def test_source_youtube_skips_ytmusic_but_still_uses_the_new_shapes(monkeypatch):
    """`spotify_source=youtube` مسیرِ YT Music را رد می‌کند، ولی شکلِ کوئری همان است."""
    seen: list[str] = []

    async def fake_yt(query, opts, limit=6, timeout=60):
        seen.append(query)
        return []

    monkeypatch.setattr(D, "_yt_search_candidates", fake_yt)
    await D._gather_candidates(FARYAD, {}, "youtube")
    assert seen and seen[0] == "Anoushirvan Rohani Faryad"
    assert DEAD_COMMA not in seen


async def test_an_isrc_hit_is_kept_and_still_flagged(monkeypatch):
    """کدِ ISRC در تولید شلیک نمی‌کند ولی نباید با dedup بی‌صدا بشکند."""
    rec = Recorder(by_query={
        ("XYZ123", "songs"): [ytm("iso", "Faryad", ["Haydeh"], 311)],
        ("Anoushirvan Rohani Faryad", "songs"): [ytm("iso", "Faryad", ["Haydeh"], 311)],
    })
    monkeypatch.setattr(D, "_ytmusic_search", rec)
    monkeypatch.setattr(D, "_yt_search_candidates", _no_ytsearch)
    out = await D._gather_candidates({**FARYAD, "isrc": "XYZ123"}, {}, "ytmusic")
    assert len(out) == 1
    assert out[0].get("isrc_hit") is True


# ── یکپارچه: همان چیزی که روی مستر اندازه‌گیری شد ───────────────────────────
async def test_the_pipeline_now_reaches_the_recording_the_old_query_missed(monkeypatch):
    """gather → rank → برنده، با همان الگویی که probeِ مستر نشان داد.

    شکلِ کاماییِ قدیمی فقط یک مثبتِ کاذبِ «فقط مدت» می‌داد (یک `Faryaad`ِ دیگر
    از هنرمندِ دیگر)، و ضبطِ درست **تنها** از شکلِ «هنرمندِ اول/آخر» می‌آمد.
    این تست همان توزیع را مدل می‌کند: پیش از رفع، تولید فقط کوئریِ کامایی را
    می‌فرستاد و برنده ضبطِ غلط می‌شد.
    """
    right = ytm("WUxurPJmKXI", "Faryad", ["Anoushirvan Rohani", "Haydeh"], 312)
    false_pos = ytm("wrongOne", "Faryaad", ["Anoushirvan Rohani", "Maziar", "Kari"], 312)
    rec = Recorder(by_query={
        (DEAD_COMMA, "songs"): [false_pos],                 # شکلِ قدیمی: فقط مثبتِ کاذب
        ("Anoushirvan Rohani Faryad", "songs"): [right],    # رتبهٔ ۱ روی مستر
        ("Haydeh Faryad", "songs"): [right, false_pos],     # رتبهٔ ۲ روی مستر
    })
    monkeypatch.setattr(D, "_ytmusic_search", rec)
    monkeypatch.setattr(D, "_yt_search_candidates", _no_ytsearch)

    cands = await D._gather_candidates(FARYAD, {}, "ytmusic")
    ranked = D._rank_candidates(cands, FARYAD)
    assert ranked, "همهٔ نامزدها گیت خوردند"
    assert ranked[0][1]["id"] == "WUxurPJmKXI", (
        f"برنده {ranked[0][1]['id']!r} شد — ضبطِ درست نبرد")
    assert (DEAD_COMMA, "songs") not in rec.calls


# ── آخرین‌چاره: `ytsearch1:` باید همان شکلِ تازه را ببرد ─────────────────────
async def test_the_last_resort_ytsearch_uses_the_new_shape(monkeypatch, tmp_path):
    """وقتی هیچ نامزدی نماند، `ytsearch1:` نباید شکلِ مردهٔ کامایی را بفرستد.

    کوئری دو جا ساخته می‌شد (`_gather_candidates` و `download_spotify`)، پس
    عوض‌کردنِ یکی، آخرین‌چاره را روی همان شکلی می‌گذاشت که اثباتاً هدف را
    نمی‌آورد.
    """
    seen: list[str] = []

    async def fake_resolve(url, cid, secret, max_tracks, proxy=None):
        return {"tracks": [dict(FARYAD)]}

    async def fake_gather(track, opts, source):
        return []

    async def fake_dl(target, outdir, mode, opts, progress=None, cancel=None):
        seen.append(target)
        raise RuntimeError("stop here")

    monkeypatch.setattr(D, "spotify_resolve", fake_resolve)
    monkeypatch.setattr(D, "_gather_candidates", fake_gather)
    monkeypatch.setattr(D, "download_ytdlp", fake_dl)

    with pytest.raises(RuntimeError):
        await D.download_spotify("https://open.spotify.com/track/x", str(tmp_path), {})

    assert seen == ["ytsearch1:Anoushirvan Rohani Faryad"], f"هدفِ آخرین‌چاره: {seen}"
    assert f"ytsearch1:{DEAD_COMMA}" not in seen
