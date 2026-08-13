"""اثرِ انگشتِ زنجیرهٔ تطبیق: اگر جواب عوض شد، `_MATCH_VERSION` باید بالا برود.

`dl_cache._MATCH_VERSION` **دستی** بالا برده می‌شود، و یادداشتِ خودمان گفته این
همان شکلِ `_KNOWN_UNREACHABLE` و فهرستِ هاردکدِ کانکتورها است که هر دو رت کردند.
پس این تست عددِ نسخه را به **خروجیِ قابلِ مشاهدهٔ** زنجیره گره می‌زند: هر تغییری
که جوابِ تحویلی را عوض کند این‌جا می‌شکند و نویسنده مجبور می‌شود آگاهانه تصمیم
بگیرد. تغییرِ کامنت یا نامِ متغیرِ محلی نمی‌شکندش.

**دو نیمه، و نیمهٔ دوم دقیقاً همان جایی است که سه هفته کور بودیم.** کلیدِ کش
`(url, options, version)` است و URL با تغییرِ **پارسر** عوض نمی‌شود؛ پس اگر
`_parse_spotify_embed` اصلاح شود، مرجع و در نتیجه هدف عوض می‌شوند ولی اثرِ
انگشتِ ماچر — که مرجعش فیکسچرِ ثابت است — تکان نمی‌خورد و ما دوباره به
`DELETE` دستی برمی‌گردیم. همان پارسر بود که هفته‌ها بی‌صدا مرده بود، پس:

    نیمهٔ ۱  رفتارِ ماچر روی مجموعهٔ ثابتی از (مرجع، نامزدها)
    نیمهٔ ۲  خروجیِ پارسر روی دو دامپِ **واقعیِ** `__NEXT_DATA__`

و هر دو در **یک** ثابت جمع می‌شوند، چون هر دو یک سؤال را جواب می‌دهند: «آیا
جوابی که به کاربر می‌رسد عوض شده؟»

**قطعیت:** هر عددِ اعشاری قبل از هش با `round(x, 3)` گرد می‌شود، وگرنه هش بینِ
پایتون/معماری‌های مختلف پایدار نیست.

**فیکسچرها از کیس‌های واقعیِ اندازه‌گیری‌شده‌اند**، نه ساختگی: Faryad،
Jane Maryam، Hallelujah، به‌علاوهٔ کیس‌های سختِ شناخته‌شده — نامزدِ تماماً
فارسی‌نویس (۳۵٫۳ در برابرِ ۱۰۶)، مسیرِ اسکریپتِ مخلوط (`قطعه فریاد` +
`Anushiravan Ruhani`)، `Ebi ↔ Ebrahim Hamedi`، ریمیکس (جریمهٔ نسخه)، و **هر دو
شاخهٔ مدت**: نامزدِ بی‌مدت (مسیرِ `_TIME_UNKNOWN`) و ترکی که مدتِ **خودش**
نامعلوم است (مسیرِ حذفِ مؤلفه — همان که برای مقایسه‌پذیریِ بینِ ترک‌ها لازم است).

**فیکسچرِ پارسر دامپِ واقعیِ trim‌شده است** (`_fixture_note` خودش می‌گوید از کجا
آمده): فیلدهای بی‌ربط حذف شده‌اند ولی هر کلیدی که پارسر می‌خواند دست‌نخورده است.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from app import dl_cache as C
from app import downloader as D

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────────────────────
# اگر این تست شکست: خروجیِ زنجیره عوض شده. **آگاهانه** تصمیم بگیر —
#   • عوض شدن مطلوب بود  → `dl_cache._MATCH_VERSION` را یکی ببر بالا **و**
#                            مقدارِ زیر را با عددی که تست چاپ می‌کند عوض کن.
#   • عوض شدن ناخواسته بود → باگ را رفع کن، این عدد را دست نزن.
# ─────────────────────────────────────────────────────────────────────────────
_FINGERPRINT = "7d38598886db25f5"


def _r(v):
    """گردکردنِ صریح برای قطعیتِ هش (فلوتِ خام بینِ محیط‌ها پایدار نیست)."""
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, (list, tuple)):
        return [_r(x) for x in v]
    if isinstance(v, dict):
        return {k: _r(v[k]) for k in sorted(v)}
    return v


def cand(vid, title, artists, dur, art_track=True):
    return {"id": vid, "title": title, "artists": artists, "album": None,
            "duration_seconds": dur, "art_track": art_track, "source": "ytmusic"}


# ── نیمهٔ ۱: رفتارِ ماچر ─────────────────────────────────────────────────────
FARYAD = {"title": "Faryad", "artist": "Anoushirvan Rohani, Haydeh", "duration": 311}
JANE = {"title": "Jane Maryam", "artist": "Mohammad Nouri", "duration": 311}
COHEN = {"title": "Hallelujah", "artist": "Leonard Cohen", "duration": 275}
EBI = {"title": "Shabe Nasimi", "artist": "Ebi", "duration": 300}
NO_DUR = {"title": "Faryad", "artist": "Anoushirvan Rohani, Haydeh", "duration": None}
# مرجعی که خودش `(feat. X)` در عنوان دارد — شکلی که اپل رایجش کرد.
FEAT = {"title": "Faryad (feat. Haydeh)", "artist": "Anoushirvan Rohani", "duration": 311}

CASES: list[tuple[str, dict, list[dict]]] = [
    ("faryad", FARYAD, [
        cand("right", "Faryad", ["Anoushirvan Rohani", "Haydeh"], 312),
        cand("wrong", "Faryaad", ["Anoushirvan Rohani", "Maziar", "Kari"], 312),
        cand("remix", "Faryad (DJ Fere Remix)", ["Anoushirvan Rohani", "Haydeh"], 311),
        cand("mixed", "قطعه فریاد", ["Anushiravan Ruhani"], 311),      # مسیرِ معافیتِ خط
        cand("allfa", "قطعه فریاد", ["هایده"], 311),                   # ۳۵٫۳ — باید گیت بخورد
        cand("novid", "Faryad", ["Haydeh"], 311, art_track=False),     # بی‌art_track
    ]),
    ("jane", JANE, [
        cand("jr", "Jane Maryam", ["Mohammad Nouri"], 311),
        cand("jw", "Jane Maryam", ["Sara Naeini"], 309),
    ]),
    ("hallelujah", COHEN, [
        cand("hc", "Hallelujah", ["Leonard Cohen"], 275),
        cand("hb", "Hallelujah", ["Jeff Buckley"], 273),               # تناقض
        cand("hp", "Hallelujah", ["Pentatonix"], 280),                 # تناقض
    ]),
    ("stage_name", EBI, [
        cand("eb", "Shabe Nasimi", ["Ebrahim Hamedi"], 300),           # محدودیتِ شناخته‌شده
    ]),
    # مسیرِ `_TIME_UNKNOWN`: مدتِ **نامزد** نامعلوم، مدتِ ترک معلوم
    ("cand_no_duration", FARYAD, [
        cand("nodur", "Faryad", ["Anoushirvan Rohani", "Haydeh"], None),
        cand("exact", "Faryad", ["Anoushirvan Rohani", "Haydeh"], 311),
        cand("off3", "Faryad", ["Anoushirvan Rohani", "Haydeh"], 314),
    ]),
    # عنوانِ **feat‌دار** در مسیرِ مشترک. اپل مهمان را همیشه در عنوان می‌گذارد و
    # `_split_feat_title` آن را در `apple_resolve` بیرون می‌کشد — یعنی هرگز به
    # این‌جا نمی‌رسد (با اجرا سنجیده شد: صفر فراخوانی از مسیرِ اسپاتیفای، و
    # فینگرپرینتِ پیش و پس از کارِ اپل بیت‌به‌بیت یکی ماند). ولی فینگرپرینت
    # فقط به‌اندازهٔ پوششِ فیکسچرش قوی است: بدونِ این کیس، اگر روزی استخراج به
    # کدِ مشترک منتقل شود این تست ساکت می‌ماند. حالا نمی‌ماند.
    ("feat_in_title", FEAT, [
        cand("fr", "Faryad (feat. Haydeh)", ["Anoushirvan Rohani", "Haydeh"], 311),
        cand("fc", "Faryad", ["Anoushirvan Rohani"], 311),
        # براکتِ نشانه کنارِ براکتِ feat: هر دو باید دیده شوند
        cand("fl", "Faryad (feat. Haydeh) [Live]", ["Anoushirvan Rohani", "Haydeh"], 311),
    ]),
    # مسیرِ حذفِ مؤلفه: مدتِ **خودِ ترک** نامعلوم → مؤلفه حذف می‌شود، نه ۵۰ تزریق
    ("track_no_duration", NO_DUR, [
        cand("a", "Faryad", ["Anoushirvan Rohani", "Haydeh"], 311),
        cand("b", "Faryad", ["Anoushirvan Rohani", "Haydeh"], None),
    ]),
]


def matcher_state() -> list:
    """تصمیم‌های قابلِ مشاهدهٔ ماچر روی همهٔ کیس‌ها — گردشده و مرتب."""
    out = []
    for name, track, cands in CASES:
        ranked = [(_r(s), c["id"]) for s, c in D._rank_candidates(cands, track)]
        gated = sorted(c["id"] for c in cands
                       if c["id"] not in {i for _s, i in ranked})
        per = {c["id"]: {
            "name": _r(D._name_match(track, c)),
            "artist": _r(D._artist_match(track, c)),
            "contra": D._artist_contradiction(track, c),
            "exempt": D._name_gate_exempt(track, c),
            "markers": sorted(D._version_markers(c["title"])),
            "score": _r(D._match_score(c, track)),
        } for c in cands}
        out.append({"case": name, "ranked": ranked, "gated": gated,
                    "per": _r(per),
                    "note": bool(ranked and D.match_confidence_note(
                        track, next(c for c in cands if c["id"] == ranked[0][1])))})
    return out


# ── نیمهٔ ۲: خروجیِ پارسر روی دامپِ واقعی ────────────────────────────────────
def _embed_html(path: pathlib.Path) -> str:
    raw = path.read_text(encoding="utf-8")
    return f'<script id="__NEXT_DATA__" type="application/json">{raw}</script>'


def parser_state() -> list:
    """مرجعی که پارسر از دامپِ واقعی می‌سازد — یعنی چیزی که ماچر رویش کار می‌کند."""
    out = []
    for fname, kind in (("spotify_embed_track.json", "track"),
                        ("spotify_embed_playlist.json", "playlist")):
        parsed = D._parse_spotify_embed(
            _embed_html(ROOT / "tests" / "fixtures" / fname), kind, 200)
        assert parsed is not None, f"پارسر روی {fname} شکست — دامپ یا پارسر خراب است"
        out.append({
            "fixture": fname,
            "kind": parsed.get("kind"),
            "title": parsed.get("title"),
            "tracks": [{k: _r(t.get(k)) for k in ("title", "artist", "duration", "year")}
                       for t in parsed["tracks"]],
            "blind": [D.reference_is_blind(t) for t in parsed["tracks"]],
        })
    return out


def fingerprint() -> str:
    payload = json.dumps({"matcher": matcher_state(), "parser": parser_state()},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── تست‌ها ──────────────────────────────────────────────────────────────────
def test_the_chain_still_produces_the_pinned_answer():
    got = fingerprint()
    assert got == _FINGERPRINT, (
        "\n\nخروجیِ زنجیرهٔ تطبیق عوض شده (ماچر یا پارسر).\n\n"
        "**اول تشخیص بده کدام‌یک — نسخهٔ کش فقط برای یکی‌شان است، و این را\n"
        "با حدس تشخیص نده. روالِ دقیق:**\n\n"
        "  ۱) کیس‌های تازه‌ای که در همین تغییر به `CASES` (یا فیکسچرِ پارسر)\n"
        "     اضافه کرده‌ای را **موقتاً بردار**.\n"
        "  ۲) هش را دوباره حساب کن.\n"
        "  ۳) اگر با مقدارِ **پین‌شدهٔ قبلی** یکی شد → فقط پوشش رشد کرده،\n"
        "     رفتار دست‌نخورده است: عدد را عوض کن و `_MATCH_VERSION` را\n"
        "     **بالا نبر** (بالا بردنش ردیف‌های سالمِ کش را برای مشکلی که\n"
        "     ندارند دور می‌ریزد و یک `DELETE` بی‌دلیل به استقرار می‌چسباند).\n"
        "  ۴) اگر **یکی نشد** → پاسخِ کیسی که از قبل بود عوض شده، یعنی تغییرِ\n"
        "     رفتار — **حتی اگر در همان کامیت کیس هم اضافه کرده باشی**. آن‌وقت\n"
        "     `dl_cache._MATCH_VERSION` را یکی ببر بالا و آن استقرار یک\n"
        "     `DELETE FROM download_cache WHERE platform IN (…)` می‌خواهد.\n\n"
        "  ⚠ گامِ ۱ حذف‌شدنی نیست: «کیس اضافه کردم» به‌تنهایی هیچ چیزی را ثابت\n"
        "     نمی‌کند، چون یک کامیت می‌تواند هم‌زمان کیس اضافه کند **و** رفتار را\n"
        "     عوض کند، و آن‌وقت هش عوض می‌شود به دو دلیل که از بیرون یکی به‌نظر\n"
        "     می‌رسند.\n\n"
        f'        _FINGERPRINT = "{got}"\n\n'
        "اگر عوض شدن **ناخواسته** بود: باگ را رفع کن و این عدد را دست نزن.\n")


def test_the_fingerprint_is_deterministic_across_runs():
    assert fingerprint() == fingerprint()


def test_the_fixture_covers_every_signal_the_matcher_uses():
    """پوششِ فیکسچر: هر شاخه‌ای که روی جواب اثر دارد باید نمایندهٔ داشته باشد."""
    st = matcher_state()
    per = {c: v for case in st for c, v in case["per"].items()}
    assert any(v["contra"] for v in per.values()), "قاعدهٔ تناقض نماینده ندارد"
    assert any(v["exempt"] for v in per.values()), "معافیتِ خط نماینده ندارد"
    assert any(v["markers"] for v in per.values()), "جریمهٔ نسخه نماینده ندارد"
    assert any(c["gated"] for c in st), "هیچ نامزدی گیت نمی‌خورد"
    # art_track در هر دو حالت
    flags = {c["art_track"] for _n, _t, cs in CASES for c in cs}
    assert flags == {True, False}, f"art_track هر دو حالت را ندارد: {flags}"
    # هر دو شاخهٔ مدت
    assert any(c["duration_seconds"] is None for _n, _t, cs in CASES for c in cs), \
        "نامزدِ بی‌مدت (مسیرِ _TIME_UNKNOWN) نیست"
    assert any(t.get("duration") is None for _n, t, _cs in CASES), \
        "ترکِ بی‌مدت (مسیرِ حذفِ مؤلفه) نیست"
    # مسیرِ اسکریپتِ مخلوط، صریح
    assert per["mixed"]["exempt"] is True and per["allfa"]["exempt"] is False
    # عنوانِ feat‌دار در **مرجع** و در **نامزد** — بدونِ این، انتقالِ استخراجِ
    # feat به کدِ مشترک این فینگرپرینت را تکان نمی‌داد.
    assert any("feat" in t["title"].lower() for _n, t, _cs in CASES), \
        "مرجعی با عنوانِ feat‌دار نیست"
    assert any("feat" in c["title"].lower() for _n, _t, cs in CASES for c in cs), \
        "نامزدی با عنوانِ feat‌دار نیست"
    assert per["fl"]["markers"] == ["live"], "نشانهٔ نسخه کنارِ براکتِ feat باید دیده شود"


def test_the_parser_half_reads_a_real_recorded_dump():
    """نیمهٔ پارسر باید روی دامپِ **واقعی** باشد، نه فیکسچرِ ساختگی.

    فیکسچرِ ساختگی پارسر را در برابرِ **فرضِ ما** پین می‌کند نه در برابرِ
    اسپاتیفای — و همین دسته اشتباه بود که سه هفته پارسر را مرده نگه داشت.
    """
    for fname in ("spotify_embed_track.json", "spotify_embed_playlist.json"):
        blob = json.loads((ROOT / "tests" / "fixtures" / fname).read_text(encoding="utf-8"))
        note = " ".join(blob.get("_fixture_note") or [])
        assert "واقعی" in note, f"{fname} منشأش را اعلام نمی‌کند"
    st = parser_state()
    assert st[0]["tracks"][0]["artist"] == "Mohammad Nouri"
    assert st[0]["tracks"][0]["duration"] == 311      # میلی‌ثانیه، با round نه int
    assert not any(st[0]["blind"]), "مرجعِ کور از دامپِ سالم درنمی‌آید"
