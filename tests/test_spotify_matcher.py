"""matcherِ اسپاتیفای: باگِ `ft`، مدتِ نامعلوم، و اولین پوششِ پارسرِ embed.

سه رفع این‌جا سنجیده می‌شوند (فاز ۳ج):

* **۱** `_ARTIST_SPLIT_RE` مرزِ کلمه نداشت، پس `ft` هرجای نام می‌بُرد:
  «Daft Punk» → `['Da','Punk']`. اثرش دو چیز بود که هر دو این‌جا تست دارند —
  ردِ **نامزدِ درست** روی ترک‌های چندهنرمندی، و نصف‌شدنِ فاصلهٔ «ضبطِ درست» تا
  «کاور» روی همه.
* **۳** مدتِ نامعلومِ نامزد دقیقاً مثلِ مدتِ کاملاً درست امتیاز می‌گرفت.
* **۴** `_pick_best_match` کدِ مرده بود.

و پوششِ `_parse_spotify_embed` که تا امروز **صفر** بود، در حالی که از امروز
تنها مسیرِ متادیتاست (APIِ رسمی برای ما بسته است — §۷).

**مرزِ صداقتِ تستِ پارسر، صریح:** صفحهٔ واقعیِ `open.spotify.com` از محیطِ تست
در دسترس نیست (پروکسی `CONNECT` را ۴۰۳ می‌کند)، پس فیکسچرها از روی **انتظارِ
خودِ پارسر** ساخته شده‌اند نه از یک صفحهٔ ضبط‌شده. یعنی این تست‌ها ثابت **نمی‌کنند**
که نامِ فیلدهای اسپاتیفای همین‌هاست؛ چیزی که ثابت می‌کنند رفتارِ خودمان است —
مقاومت در برابر ورودیِ خراب، شکلِ خروجی، و اینکه album/year/isrc روی این مسیر
همیشه خالی‌اند. اگر روزی صفحهٔ واقعی گرفته شد، همان باید جای این فیکسچرها را
بگیرد؛ دستورش در CLAUDE.md §۷ آمده.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app import downloader as D

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── ابزارِ ساخت: از خودِ توابعِ تولید، نه دیکشنریِ دست‌ساز ──────────────────
def track(title: str, artist: str, dur: int | None) -> dict:
    """ترک **دقیقاً** همان‌طور که مسیرِ embed می‌سازد (بدونِ ISRC و آلبوم)."""
    return D._embed_track(title, artist, "http://cover", (dur or 0) * 1000)


def ytm(title: str, artists: list[str], dur: int | None, songs: bool = True) -> dict:
    """نامزدِ YouTube Music از مسیرِ واقعیِ `_norm_ytm` (پس `artists` صریح دارد)."""
    return D._norm_ytm({"videoId": "v" + title[:6], "title": title,
                        "artists": [{"name": a} for a in artists],
                        "album": None, "duration_seconds": dur},
                       "songs" if songs else "videos")


def yts(title: str, channel: str, dur: int | None) -> dict:
    """نامزدِ ytsearch: `artists` ندارد، نامِ هنرمند از کانال حدس زده می‌شود."""
    return {"id": "s" + title[:6], "title": title, "channel": channel, "duration": dur}


# ── رفع ۱: نامِ هنرمند نباید وسط شکسته شود ────────────────────────────────
# اندازه‌گیری‌شده روی سورسِ پیش از رفع: هر ۱۴ نام خرد می‌شدند، همه از شاخهٔ `ft`.
SHREDDED = ["Daft Punk", "Taylor Swift", "Kraftwerk", "Deftones", "Soft Cell",
            "Craft Spells", "Shaft", "Aftermath", "Lifted", "Gifted",
            "Fifty Fifty", "Aftertaste", "Left Boy", "Swift"]


@pytest.mark.parametrize("name", SHREDDED + ["Coldplay", "Drake", "محسن چاوشی"])
def test_a_single_artist_name_survives_intact(name):
    assert D._track_artists({"artist": name}) == [name]


def test_the_leading_boundary_alone_is_not_enough():
    """`\\bfeat` جلوی «Daft» را می‌گیرد ولی «Feature Films» را می‌شکند.

    برای همین مرز **دوطرفه** است؛ این تست جلوی برگشتنِ نسخهٔ نیمه‌کاره را می‌گیرد.
    """
    for name in ("Feature Films", "Featurette"):
        assert D._track_artists({"artist": name}) == [name]


@pytest.mark.parametrize("raw,parts", [
    ("Drake feat. Rihanna", ["Drake", "Rihanna"]),
    ("Drake ft. Rihanna", ["Drake", "Rihanna"]),
    ("Drake featuring Rihanna", ["Drake", "Rihanna"]),
    ("Drake FT Rihanna", ["Drake", "Rihanna"]),
    ("Calvin Harris, Rihanna", ["Calvin Harris", "Rihanna"]),
    ("A & B", ["A", "B"]),
    ("A x B", ["A", "B"]),
    ("A vs B", ["A", "B"]),
])
def test_real_separators_still_split(raw, parts):
    """رفع نباید خودِ قابلیت را بکشد — این نیمهٔ دومِ کار است."""
    assert D._track_artists({"artist": raw}) == parts


def test_the_correct_candidate_is_no_longer_gated_out(_=None):
    """قلبِ رفع ۱: روی ترکِ چندهنرمندی، گیتِ هنرمند نامزدِ **درست** را می‌انداخت.

    پیش از رفع `_artist_match` برابرِ ۳۲٫۳ می‌شد (زیرِ آستانهٔ ۴۰ در
    `_rank_candidates`) چون هنرمندِ اصلی به `'Da'` تبدیل شده بود.
    """
    tr = track("Get Lucky", "Daft Punk, Pharrell Williams, Nile Rodgers", 369)
    right = ytm("Get Lucky", ["Daft Punk"], 369)
    ranked = D._rank_candidates([right], tr)
    assert ranked, "نامزدِ درست نباید گیت بخورد"
    assert D._artist_match(tr, right) >= 40


@pytest.mark.parametrize("artist", SHREDDED + ["Coldplay", "محسن چاوشی"])
def test_the_exactly_right_candidate_scores_a_perfect_artist_match(artist):
    """بیانِ مستقیمِ رفع: نامزدی که هنرمندش **دقیقاً** همان است باید ۱۰۰ بگیرد.

    پیش از رفع «Daft Punk» عددِ ۴۶٫۴ می‌گرفت (چون به `['Da','Punk']` خرد شده
    بود) و همین ۵۴ واحد خطا روی مؤلفه‌ای با وزنِ ~۲۷٪ می‌نشست.
    """
    tr = track("Get Lucky", artist, 369)
    assert D._artist_match(tr, ytm("Get Lucky", [artist], 369)) == pytest.approx(100.0)


def test_the_margin_between_the_right_take_and_a_cover_is_restored():
    """اثرِ پیوسته: خرابیِ نام فاصلهٔ «ضبطِ درست» تا «کاور» را نصف می‌کرد.

    اندازه‌گیری‌شده برای Daft Punk: **۱۵٫۴ پیش از رفع، ۳۰٫۸ بعد از آن**. کفِ ۲۳
    از روی بازهٔ سنجیده‌شدهٔ نُه هنرمند (۲۳٫۷ تا ۳۰٫۹) انتخاب شده — بالاتر از هر
    چیزی که سورسِ خراب می‌توانست بدهد، پایین‌تر از هر چیزی که سورسِ سالم می‌دهد.

    (نسخهٔ اولِ این تست فاصلهٔ دو **هنرمندِ متفاوت** را برابر می‌خواست؛ غلط بود —
    فاصله به شباهتِ فازیِ همان نام با «The Cover Band» بستگی دارد و بی‌ربط به
    این باگ فرق می‌کند. آن ادعا هم روی سورسِ سالم می‌افتاد، یعنی تست خراب بود نه کد.)
    """
    for artist in ("Daft Punk", "Deftones", "Soft Cell"):
        tr = track("Get Lucky", artist, 369)
        right = ytm("Get Lucky", [artist], 369)
        cover = ytm("Get Lucky", ["The Cover Band"], 369, songs=False)
        margin = D._match_score(right, tr) - D._match_score(cover, tr)
        assert margin > 23, f"{artist}: فاصله {margin:.1f} — تفکیک هنوز کم است"


# ── رفع ۳: «نمی‌دانم» نباید مثلِ «کامل» امتیاز بگیرد ──────────────────────
def test_an_unknown_duration_no_longer_scores_like_a_perfect_one():
    tr = track("Song", "Solo Artist", 369)
    exact = ytm("Song", ["Solo Artist"], 369)
    unknown = ytm("Song", ["Solo Artist"], None)
    assert D._match_score(unknown, tr) < D._match_score(exact, tr)


def test_an_unknown_duration_ranks_below_a_near_miss_and_above_a_bad_one():
    """مقدارِ خنثی یعنی «متوسط»: بدتر از تطبیقِ نزدیک، بهتر از اختلافِ فاحش.

    ۵۰ روی منحنیِ `_time_match` معادلِ ۶٫۹ ثانیه است، پس ۳ ثانیه باید بالاتر و
    ۲۰ ثانیه پایین‌تر بنشیند.
    """
    tr = track("Song", "Solo Artist", 369)
    s = lambda d: D._match_score(ytm("Song", ["Solo Artist"], d), tr)  # noqa: E731
    assert s(372) > s(None) > s(389)


def test_the_neutral_value_is_the_midpoint_of_the_time_scale():
    """۵۰ خودسرانه نیست: وسطِ بازهٔ خروجیِ `_time_match` است."""
    assert D._TIME_UNKNOWN == 50.0
    # همان ۵۰ روی منحنی = چند ثانیه اختلاف؟ باید ~۶٫۹ باشد.
    secs = next(x / 10 for x in range(0, 400)
                if D._time_match(369 + x / 10, 369) <= D._TIME_UNKNOWN)
    assert 6.5 <= secs <= 7.5, f"معادلِ ثانیه‌ایِ عددِ خنثی جابه‌جا شده: {secs}"


def test_a_track_with_no_duration_drops_the_component_instead():
    """وقتی مدتِ **خودِ ترک** نامعلوم است، هیچ نامزدی قابلِ مقایسه نیست.

    دادنِ ۵۰ به همه فقط امتیازها را فشرده می‌کند؛ پس مؤلفه مثلِ قبل حذف می‌شود و
    دو نامزدِ یکسان باید امتیازِ یکسان بگیرند، چه مدت داشته باشند چه نه.
    """
    tr = track("Song", "Solo Artist", None)
    assert tr["duration"] is None, "فرضِ تست: ترکِ بدونِ مدت"
    assert D._match_score(ytm("Song", ["Solo Artist"], 200), tr) == \
           D._match_score(ytm("Song", ["Solo Artist"], None), tr)


def test_the_hard_duration_gate_still_ignores_unknowns():
    """گیتِ سخت روی دادهٔ ناموجود نباید رد کند — فقط امتیاز خنثی می‌شود."""
    tr = track("Song", "Solo Artist", 369)
    assert D._duration_reject(ytm("Song", ["Solo Artist"], None), tr) is False
    assert D._duration_reject(ytm("Song", ["Solo Artist"], 600), tr) is True


# ── رفع ۴: کدِ مرده ──────────────────────────────────────────────────────
def test_the_dead_helper_is_gone():
    assert not hasattr(D, "_pick_best_match"), \
        "دو نسخه از یک قاعده (این و منطقِ درجای download_spotify) واگرا می‌شوند"


# ── پارسرِ embed، روی پاسخِ **واقعیِ** ضبط‌شده ───────────────────────────
#
# نسخهٔ قبلیِ این بلوک فیکسچرِ **ساختگی** داشت — از روی انتظارِ خودِ پارسر ساخته
# شده بود، چون اسپاتیفای از سندباکسِ تست مسدود است. همان‌جا نوشتم که «عمداً
# چیزی دربارهٔ نامِ فیلدهای اسپاتیفای ثابت نمی‌کند»، و دقیقاً همان شکاف یک
# خرابیِ کامل را پنهان کرد: اسکیما عوض شده بود، `_find_spotify_entity` هیچ‌وقت
# چیزی پیدا نمی‌کرد، `_parse_spotify_embed` همیشه `None` می‌داد، و
# `_spotify_scrape` بی‌صدا به oEmbed می‌افتاد که فقط عنوان دارد. تست‌ها تمامِ این
# مدت سبز بودند چون شکلِ مردهٔ خودشان را می‌سنجیدند.
#
# حالا فیکسچرِ اصلی یک ضبطِ واقعی از مستر است (`tests/fixtures/`).
FIXTURE = ROOT / "tests" / "fixtures" / "spotify_embed_track.json"


def real_page() -> str:
    """صفحهٔ embed با پاسخِ واقعی داخلش."""
    return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + FIXTURE.read_text(encoding="utf-8")
            + "</script></body></html>")


def _page(entity: dict) -> str:
    return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}})
            + "</script></body></html>")


def _legacy_entity(title="Get Lucky", subtitle="Daft Punk", dur=369_000, **kw) -> dict:
    """شکلِ **قدیمیِ** اسپاتیفای (`subtitle` + `coverArt`).

    برای یک ترک اثباتاً دیگر برنمی‌گردد؛ به‌عنوان fallback نگه داشته می‌شود چون
    مسیرِ `trackList` (آلبوم/پلی‌لیست) هنوز روی اسکیمای امروز **تأیید نشده** و
    نمونه‌اش را نداریم. هر تستی که این را می‌سازد دربارهٔ همان fallback است، نه
    دربارهٔ رفتارِ امروزیِ اسپاتیفای.
    """
    e = {"title": title, "subtitle": subtitle, "duration": dur,
         "coverArt": {"sources": [{"url": "http://small"}, {"url": "http://big"}]}}
    e.update(kw)
    return e


def test_the_real_embed_response_yields_the_right_artist_and_duration():
    """قلبِ ماجرا. روی کدِ پیش از رفع، `artist` خالی و `duration` تهی بود —
    و همان باعث شد «Jane Maryam» به‌جای محمد نوری، سارا نایینی تحویل شود."""
    out = D._parse_spotify_embed(real_page(), "track", 20)
    assert out, "پارسر روی پاسخِ واقعی چیزی برنگرداند"
    t = out["tracks"][0]
    assert t["title"] == "Jane Maryam"
    assert t["artist"] == "Mohammad Nouri"
    assert t["duration"] == 311


def test_the_duration_is_milliseconds_not_seconds():
    """۳۱۰۹۷۳ = ۵:۱۱. اگر ثانیه خوانده شود می‌شود ~۳٫۶ روز و آن‌وقت
    `_duration_reject` **هر** نامزدی را رد می‌کند — خرابیِ بی‌صدا."""
    t = D._parse_spotify_embed(real_page(), "track", 20)["tracks"][0]
    assert t["duration"] == 311, "واحد جابه‌جا شده"
    assert t["duration"] < 3600, f"{t['duration']}s یعنی واحد ثانیه خوانده شده"
    # و اثرش را مستقیم بسنج: نامزدِ درستِ ۳۱۱ ثانیه‌ای نباید گیتِ مدت بخورد
    cand = ytm("Jane Maryam", ["Mohammad Nouri"], 311)
    assert D._duration_reject(cand, t) is False


def test_the_real_response_makes_the_right_recording_win():
    """سنجهٔ سرتاسری با نامزدهای **واقعیِ** همان اجرا (از خروجیِ مستر).

    پیش از رفع همه دقیقاً ۱۰۶٫۰ می‌گرفتند و برنده صرفاً اولین نفر بود.
    """
    track = D._parse_spotify_embed(real_page(), "track", 20)["tracks"][0]
    cands = [ytm("Jane Maryam", ["Sara Naeini"], 230),          # همانی که تحویل شد
             ytm("Jane Maryam", ["Evgeny Grinko"], 91),
             ytm("Jane Maryam", ["Soheil Salimzadeh"], 178),
             ytm("Jane Maryam", ["Mohammad Nouri"], 311),       # درست
             ytm("Jane Maryam", ["Bahman"], 385)]
    ranked = D._rank_candidates(cands, track)
    assert ranked, "همه گیت خوردند"
    assert D._cand_artists(ranked[0][1]) == ["Mohammad Nouri"], \
        f"برنده اشتباه است: {[(round(s, 1), D._cand_artists(c)) for s, c in ranked]}"
    # با مرجعِ سالم، نسخه‌های با مدتِ متفاوت **اصلاً از گیت رد نمی‌شوند** — که از
    # «امتیازِ کمتر گرفتند» قوی‌تر است. پیش از رفع هر پنج‌تا با ۱۰۶٫۰ مساوی بودند.
    # (ادعای اولیهٔ من «امتیازها باید متفاوت باشند» بود؛ غلط بود، چون بازمانده
    #  یکی بیشتر نیست و مجموعهٔ تک‌عضوی طبعاً یک مقدار دارد.)
    assert len(ranked) == 1, \
        f"نسخه‌های با مدتِ ناجور باید گیت بخورند: {[D._cand_artists(c) for _, c in ranked]}"


def test_the_year_now_arrives_but_album_and_isrc_still_do_not():
    """تصحیحِ ادعای قبلی: `year` **در دسترس است** (`releaseDate.isoString`).

    نسخهٔ قبلیِ این تست `year == ""` را قفل می‌کرد، که دیگر درست نیست. آلبوم و
    ISRC همچنان نمی‌آیند — و همان دوتاست که به امتیازدهی مربوط است (مؤلفهٔ
    آلبوم ۰٫۰۸ و بونوسِ ISRCِ +۲۰). خودِ `year` در `_match_score` استفاده
    نمی‌شود؛ فقط برای تگ‌گذاریِ متادیتای فایل است.
    """
    t = D._parse_spotify_embed(real_page(), "track", 20)["tracks"][0]
    assert t["year"] == "1996"
    assert t["album"] == "" and t["isrc"] is None
    assert set(t) == {"title", "artist", "album", "year", "cover_url", "duration", "isrc"}


def test_the_cover_comes_from_visual_identity():
    t = D._parse_spotify_embed(real_page(), "track", 20)["tracks"][0]
    assert t["cover_url"] == "https://i.scdn.co/image/ed5c0b36a2a80e037438dca38cd58f0a509136b0"


def test_the_entity_picked_is_the_complete_one_not_merely_the_first():
    """شرطِ قبلی «اولین تطبیق» بود، پس یک زیرآبجکتِ عنوان‌دار می‌توانست ببرد."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    real = data["props"]["pageProps"]["state"]["data"]["entity"]
    decoy = {"title": "Jane Maryam", "coverArt": {"sources": [{"url": "http://decoy"}]}}
    # طعمه **قبل** از entityِ واقعی، هم در dict و هم داخلِ لیست
    got = D._find_spotify_entity({"a": decoy, "b": [decoy], "c": {"entity": real}})
    assert got is real, "آبجکتِ ناقص برنده شد"


def test_a_blind_reference_is_recognised_as_blind():
    """مرجعِ بی‌هنرمند و بی‌مدت = matcher فقط روی نام قضاوت می‌کند."""
    assert D.reference_is_blind(D._embed_track("Jane Maryam", "", None, 0)) is True
    assert D.reference_is_blind(D._embed_track("Jane Maryam", "Mohammad Nouri", None, 0)) is False
    assert D.reference_is_blind(D._embed_track("Jane Maryam", "", None, 311_000)) is False
    real = D._parse_spotify_embed(real_page(), "track", 20)["tracks"][0]
    assert D.reference_is_blind(real) is False


def test_a_blind_reference_makes_every_same_titled_candidate_tie():
    """چرا کوری مهم است، به‌جای اینکه صرفاً ادعا شود.

    این همان چیزی است که روی مستر دیده شد: یازده نامزد با امتیازِ **دقیقاً**
    یکسان، پس برنده فقط «اولین نفرِ فهرست» بود.
    """
    blind = D._embed_track("Jane Maryam", "", None, 0)
    cands = [ytm("Jane Maryam", [a], d) for a, d in
             [("Sara Naeini", 230), ("Mohammad Nouri", 311), ("Bahman", 385)]]
    scores = {round(s, 1) for s, _ in D._rank_candidates(cands, blind)}
    assert len(scores) == 1, "فرضِ تست: با مرجعِ کور همه باید مساوی شوند"
    assert D.reference_is_blind(blind) is True


# ── شکلِ قدیمی: عمداً نگه داشته شده، چون مسیرِ trackList تأیید نشده ───────
def test_the_legacy_shape_still_parses_as_a_fallback():
    """اثباتاً دیگر برای یک ترک برنمی‌گردد؛ اگر آلبوم/پلی‌لیست هنوز این شکل را
    بدهد نباید بشکند. این تست دربارهٔ **fallback** است، نه رفتارِ امروز."""
    out = D._parse_spotify_embed(_page(_legacy_entity()), "track", 20)
    t = out["tracks"][0]
    assert (t["artist"], t["duration"], t["cover_url"]) == ("Daft Punk", 369, "http://big")


def test_a_playlist_page_parses_every_track_and_respects_the_cap():
    """مسیرِ `trackList` — **روی اسکیمای امروز تأیید نشده** (نمونه‌اش را نداریم)."""
    tl = [{"title": f"S{i}", "subtitle": "A", "duration": (100 + i) * 1000} for i in range(5)]
    out = D._parse_spotify_embed(_page(_legacy_entity(title="PL", trackList=tl)), "playlist", 3)
    assert [t["title"] for t in out["tracks"]] == ["S0", "S1", "S2"]
    assert out["title"] == "PL"


def test_a_track_falls_back_to_the_album_cover():
    tl = [{"title": "S", "subtitle": "A", "duration": 1000}]
    out = D._parse_spotify_embed(_page(_legacy_entity(title="ALB", trackList=tl)), "album", 20)
    assert out["tracks"][0]["cover_url"] == "http://big"


def test_a_list_of_artists_becomes_one_string():
    """شکلِ امروز `artists: [{name}]` است — همان حالتِ چندهنرمندی که باگِ `ft`
    رویش نامزدِ درست را می‌انداخت. شکلِ قدیمیِ `subtitle`ِ لیستی هم پشتیبانی می‌شود."""
    modern = _page({"title": "X", "artists": [{"name": "Daft Punk"},
                                              {"name": "Pharrell Williams"}], "duration": 1000})
    assert D._parse_spotify_embed(modern, "track", 20)["tracks"][0]["artist"] == \
        "Daft Punk, Pharrell Williams"
    legacy = _page(_legacy_entity(subtitle=[{"name": "Daft Punk"}, {"name": "Pharrell Williams"}]))
    assert D._parse_spotify_embed(legacy, "track", 20)["tracks"][0]["artist"] == \
        "Daft Punk, Pharrell Williams"


def test_tracks_with_no_title_are_dropped():
    tl = [{"title": "Good", "subtitle": "A", "duration": 1000},
          {"title": "", "subtitle": "A", "duration": 1000}]
    out = D._parse_spotify_embed(_page(_legacy_entity(trackList=tl)), "album", 20)
    assert [t["title"] for t in out["tracks"]] == ["Good"]


@pytest.mark.parametrize("html", [
    "", "<html>no next data here</html>",
    '<script id="__NEXT_DATA__">{not json}</script>',
    '<script id="__NEXT_DATA__">{"props": {}}</script>',      # هیچ entityای
])
def test_a_broken_page_returns_none_rather_than_raising(html):
    """اسپاتیفای صفحه‌اش را بی‌خبر عوض می‌کند؛ خطا باید بالادست تصمیم‌گیری شود."""
    assert D._parse_spotify_embed(html, "track", 20) is None


def test_the_entity_is_found_however_deep_it_sits():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    real = data["props"]["pageProps"]["state"]["data"]["entity"]
    html = ('<script id="__NEXT_DATA__">'
            + json.dumps({"a": [{"b": {"c": {"d": real}}}]}) + "</script>")
    out = D._parse_spotify_embed(html, "track", 20)
    assert out and out["tracks"][0]["artist"] == "Mohammad Nouri"
