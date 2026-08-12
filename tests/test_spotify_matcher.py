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

import pytest

from app import downloader as D


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


# ── پارسرِ embed: تنها مسیرِ متادیتا، تا امروز بدونِ هیچ تستی ─────────────
def _page(entity: dict) -> str:
    """صفحهٔ embed با همان قالبی که `_parse_spotify_embed` می‌خواند."""
    return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}})
            + "</script></body></html>")


def _entity(title="Get Lucky", subtitle="Daft Punk", dur=369_000, **kw) -> dict:
    e = {"title": title, "subtitle": subtitle, "duration": dur,
         "coverArt": {"sources": [{"url": "http://small"}, {"url": "http://big"}]}}
    e.update(kw)
    return e


def test_a_single_track_page_parses():
    out = D._parse_spotify_embed(_page(_entity()), "track", 20)
    assert out and len(out["tracks"]) == 1
    t = out["tracks"][0]
    assert t["title"] == "Get Lucky"
    assert t["artist"] == "Daft Punk"
    assert t["duration"] == 369, "میلی‌ثانیه باید به ثانیه تبدیل شود"
    assert t["cover_url"] == "http://big", "بزرگ‌ترین کاور (آخرین source) انتخاب می‌شود"


def test_this_path_never_yields_album_year_or_isrc():
    """همان چیزی که کلِ طراحیِ matcher باید رویش بنا شود — پس قفلش می‌کنیم.

    اگر روزی این تست بشکند یعنی مسیرِ embed فیلدِ تازه‌ای داد؛ آن‌وقت بولتِ
    «The Spotify Web API is closed to us» در §۷ باید به‌روز شود، چون شاخهٔ ISRC و
    بونوسِ +۲۰ از «مردهٔ عمدی» به «زنده» برمی‌گردند.
    """
    out = D._parse_spotify_embed(_page(_entity()), "track", 20)
    t = out["tracks"][0]
    assert t["album"] == "" and t["year"] == "" and t["isrc"] is None
    assert set(t) == {"title", "artist", "album", "year", "cover_url", "duration", "isrc"}, \
        "شکلِ ترک عوض شده — `_match_score` و `_gather_candidates` را هم ببین"


def test_a_playlist_page_parses_every_track_and_respects_the_cap():
    tl = [{"title": f"S{i}", "subtitle": "A", "duration": (100 + i) * 1000} for i in range(5)]
    out = D._parse_spotify_embed(_page(_entity(title="PL", trackList=tl)), "playlist", 3)
    assert [t["title"] for t in out["tracks"]] == ["S0", "S1", "S2"]
    assert out["title"] == "PL"


def test_a_track_falls_back_to_the_album_cover():
    """آیتم‌های trackList اغلب coverArt ندارند — کاورِ مجموعه باید جا بیفتد."""
    tl = [{"title": "S", "subtitle": "A", "duration": 1000}]
    out = D._parse_spotify_embed(_page(_entity(title="ALB", trackList=tl)), "album", 20)
    assert out["tracks"][0]["cover_url"] == "http://big"


def test_a_list_valued_subtitle_becomes_one_artist_string():
    """`_embed_track` صراحتاً این حالت را هندل می‌کند، یعنی در عمل رخ می‌دهد —
    و همین حالتِ چندهنرمندی است که باگِ `ft` رویش نامزدِ درست را می‌انداخت."""
    e = _entity(subtitle=[{"name": "Daft Punk"}, {"name": "Pharrell Williams"}])
    out = D._parse_spotify_embed(_page(e), "track", 20)
    assert out["tracks"][0]["artist"] == "Daft Punk, Pharrell Williams"


def test_tracks_with_no_title_are_dropped():
    tl = [{"title": "Good", "subtitle": "A", "duration": 1000},
          {"title": "", "subtitle": "A", "duration": 1000}]
    out = D._parse_spotify_embed(_page(_entity(trackList=tl)), "album", 20)
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
    """`_find_spotify_entity` بازگشتی می‌گردد تا تغییرِ مسیرِ JSON نشکندش."""
    deep = {"a": [{"b": {"c": {"d": _entity()}}}]}
    html = ('<script id="__NEXT_DATA__">' + json.dumps(deep) + "</script>")
    out = D._parse_spotify_embed(html, "track", 20)
    assert out and out["tracks"][0]["title"] == "Get Lucky"
