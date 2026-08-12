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

**فیکسچرها حالا ضبطِ واقعی‌اند** (`tests/fixtures/`, دامپِ ۲۰۲۶-۰۸-۱۲ از مستر):
یکی لینکِ تک‌ترک، یکی پلی‌لیست. نسخهٔ اولِ این فایل فیکسچرِ **ساختگی** داشت —
از روی انتظارِ خودِ پارسر، چون اسپاتیفای از سندباکسِ تست مسدود است — و همان‌جا
نوشته بودم که «عمداً چیزی دربارهٔ نامِ فیلدهای اسپاتیفای ثابت نمی‌کند». دقیقاً
همان شکاف یک خرابیِ کامل را پنهان کرد: اسکیما عوض شده بود، پارسر همیشه `None`
می‌داد، و `_spotify_scrape` بی‌صدا به oEmbed می‌افتاد که فقط عنوان دارد.

**دو شکلِ هنرمند، هر دو زنده — هیچ‌کدام کهنه نیست:**
    لینکِ تک‌ترک       → `artists: [{name}]`  (آرایه)
    ترکِ داخلِ trackList → `subtitle`          (رشته)
برداشتنِ `subtitle` به‌عنوان «پاکسازیِ کدِ کهنه» پلی‌لیست‌ها را می‌شکند؛
`test_both_live_artist_shapes_are_supported` عمداً همان را می‌گیرد.
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


def _entity_with_cover_art(title="Get Lucky", subtitle="Daft Punk", dur=369_000, **kw) -> dict:
    """entityِ ساختگی با کاورِ شکلِ `coverArt.sources[]`.

    **نامِ قبلیِ این تابع `_entity_with_cover_art` بود و گمراه‌کننده:** فقط `coverArt`
    کهنه است (اسکیمای امروزِ ترک `visualIdentity.image[]` می‌دهد). خودِ
    `subtitle` **زنده** است و شکلِ هنرمند در ترک‌های داخلِ `trackList`ِ
    پلی‌لیست است — با دامپِ ۲۰۲۶-۰۸-۱۲ تأیید شد. برچسبِ «قدیمی» رویش خطرناک
    بود، چون کسی می‌توانست به‌عنوانِ پاکسازی برش دارد و پلی‌لیست‌ها را بشکند.

    این ساختگی است و فقط برای سنجشِ **مکانیزمِ** ارث‌بریِ کاور به کار می‌رود.
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


# ── پلی‌لیست: مسیرِ `trackList`، **تأییدشده** روی اسکیمای امروز ───────────
#
# دامپِ ۲۰۲۶-۰۸-۱۲ نشان داد این شاخه هیچ‌وقت نشکسته بود — فقط لینکِ تک‌ترک خراب
# بود. و یک تصحیحِ مهم: **`subtitle` کدِ کهنه نیست.** دو مسیر دو شکلِ متفاوتِ
# هم‌زمان‌زنده دارند؛ برداشتنِ `subtitle` به‌عنوان «پاکسازیِ کد» پلی‌لیست‌ها را
# می‌شکند.
PLAYLIST_FIXTURE = ROOT / "tests" / "fixtures" / "spotify_embed_playlist.json"


def playlist_page() -> str:
    return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + PLAYLIST_FIXTURE.read_text(encoding="utf-8")
            + "</script></body></html>")


def test_the_real_playlist_response_parses_every_track():
    out = D._parse_spotify_embed(playlist_page(), "playlist", 20)
    assert out, "پارسر روی پاسخِ واقعیِ پلی‌لیست چیزی برنگرداند"
    assert [t["title"] for t in out["tracks"]] == \
        ["Yare Dabestanie Man", "Soltane Ghalbha", "Jane Maryam", "Gole Sangam"]


def test_a_playlist_track_gets_its_artist_from_the_string_subtitle():
    """شکلِ زندهٔ این مسیر: `subtitle` **رشته** است، نه آرایه."""
    out = D._parse_spotify_embed(playlist_page(), "playlist", 20)
    assert [t["artist"] for t in out["tracks"]][:2] == ["Fereydoon Foroughi", "Aref"]


def test_playlist_durations_are_milliseconds_too():
    """۲۱۶۱۳۷ms = ۳:۳۶ و ۳۱۰۹۷۳ms = ۵:۱۱ — پس رفعِ `round` هر دو مسیر را می‌گیرد."""
    out = D._parse_spotify_embed(playlist_page(), "playlist", 20)
    assert [t["duration"] for t in out["tracks"]] == [216, 254, 311, 290]


def test_the_playlist_cap_is_respected():
    out = D._parse_spotify_embed(playlist_page(), "playlist", 2)
    assert [t["title"] for t in out["tracks"]] == ["Yare Dabestanie Man", "Soltane Ghalbha"]


def test_both_live_artist_shapes_are_supported():
    """گاردِ صریح: **هر دو** شکل زنده‌اند و هیچ‌کدام نباید حذف شود.

    لینکِ تک‌ترک `artists: [{name}]` می‌دهد؛ ترکِ داخلِ پلی‌لیست `subtitle`ِ
    رشته‌ای. اگر روزی کسی `subtitle` را به‌عنوان کدِ کهنه بردارد، این تست
    می‌افتد — که همان هدفش است.
    """
    single = D._parse_spotify_embed(real_page(), "track", 20)["tracks"][0]
    in_list = D._parse_spotify_embed(playlist_page(), "playlist", 20)["tracks"][2]
    assert single["artist"] == "Mohammad Nouri", "شکلِ آرایه‌ای شکست"
    assert in_list["artist"] == "Mohammad Nouri", "شکلِ رشته‌ایِ subtitle شکست"
    # و هر دو باید مرجعِ کاملی بسازند، وگرنه matcher روی همان ترک کور می‌شود
    assert not D.reference_is_blind(single) and not D.reference_is_blind(in_list)


def test_the_playlist_owner_never_becomes_an_artist():
    """`subtitle` روی خودِ پلی‌لیست **مالک** است («Spotify»)، نه هنرمند.

    فیکسچرِ واقعی هر دو را دارد، پس این تست تفکیک را روی همان داده می‌سنجد.
    """
    out = D._parse_spotify_embed(playlist_page(), "playlist", 20)
    assert "Spotify" not in [t["artist"] for t in out["tracks"]]
    data = json.loads(PLAYLIST_FIXTURE.read_text(encoding="utf-8"))
    ent = data["props"]["pageProps"]["state"]["data"]["entity"]
    assert ent["subtitle"] == "Spotify", "فرضِ تست: فیکسچر مالک را دارد"


@pytest.mark.parametrize("kind", ["playlist", "album", "track"])
def test_a_collection_without_a_tracklist_is_a_parse_failure_not_one_track(kind):
    """مسیرِ واقعی و بی‌صدا که با اجرا پیدا شد.

    شاخهٔ تک‌ترک روی `not tl` می‌افتاد نه روی `kind`، پس پلی‌لیستِ خالی (یا هر
    پلی‌لیستی که فهرستش خوانده نشود) **یک ترکِ ساختگی** می‌ساخت: عنوانِ پلی‌لیست
    با هنرمندِ «Spotify». اندازه‌گیری‌شده پیش از رفع:
    `('Persian Essentials', 'Spotify', None)` — و `reference_is_blind` هم
    نمی‌گرفتش چون «Spotify» هنرمندِ ناتهی است. یعنی جست‌وجوی یوتیوب برای
    «Spotify Persian Essentials» و دانلودِ هرچه برگردد.

    مجموعه‌ای که فهرستش خوانده نشد، «یک ترک» نیست → شکستِ پارس، که به oEmbed
    می‌افتد و **هشدار لاگ می‌کند**.
    """
    data = json.loads(PLAYLIST_FIXTURE.read_text(encoding="utf-8"))
    ent = {k: v for k, v in
           data["props"]["pageProps"]["state"]["data"]["entity"].items() if k != "trackList"}
    page = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": ent}}}}})
            + "</script>")
    assert D._parse_spotify_embed(page, kind, 20) is None


def test_an_empty_playlist_is_also_a_parse_failure():
    data = json.loads(PLAYLIST_FIXTURE.read_text(encoding="utf-8"))
    ent = {**data["props"]["pageProps"]["state"]["data"]["entity"], "trackList": []}
    page = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": ent}}}}})
            + "</script>")
    assert D._parse_spotify_embed(page, "playlist", 20) is None


def test_the_playlist_entity_outscores_its_own_items():
    """اگر آیتمی برنده شود، فقط همان یک ترک پارس می‌شود و بقیه گم می‌شوند."""
    data = json.loads(PLAYLIST_FIXTURE.read_text(encoding="utf-8"))
    ent = data["props"]["pageProps"]["state"]["data"]["entity"]
    assert D._entity_score(ent) > D._entity_score(ent["trackList"][0])
    assert D._find_spotify_entity({"deep": {"x": ent}}) is ent


def test_a_playlist_track_has_no_cover_of_its_own():
    """در دامپِ واقعی، آیتم‌های trackList کاورِ اختصاصی ندارند.

    کاورِ سطحِ مجموعه در آن دامپ گزارش نشد، پس این‌جا ادعایی رویش نمی‌کنیم —
    فقط این‌که نبودنش پارس را نمی‌شکند. (مکانیزمِ ارث‌بریِ کاور جدا تست می‌شود.)
    """
    out = D._parse_spotify_embed(playlist_page(), "playlist", 20)
    assert all(t["cover_url"] is None for t in out["tracks"])


def test_a_track_inherits_the_collection_cover_when_there_is_one():
    """مکانیزمِ ارث‌بری، مستقل از اینکه اسپاتیفای کدام کلید را می‌دهد."""
    tl = [{"title": "S", "subtitle": "A", "duration": 1000}]
    out = D._parse_spotify_embed(_page(_entity_with_cover_art(title="ALB", trackList=tl)), "album", 20)
    assert out["tracks"][0]["cover_url"] == "http://big"


def test_a_list_of_artists_becomes_one_string():
    """چند هنرمند روی لینکِ تک‌ترک — همان حالتی که باگِ `ft` رویش نامزدِ درست را
    می‌انداخت.

    (نسخهٔ قبلی نیمهٔ دومی داشت که `subtitle`ِ **لیستی** را می‌سنجید. حذف شد:
    هیچ دامپی چنین شکلی نشان نداده — پلی‌لیست `subtitle`ِ رشته‌ای می‌دهد و
    تک‌ترک آرایهٔ `artists`. قفل‌کردنِ شکلی که ندیده‌ایم همان تلهٔ فیکسچرِ
    ساختگی است.)
    """
    modern = _page({"title": "X", "artists": [{"name": "Daft Punk"},
                                              {"name": "Pharrell Williams"}], "duration": 1000})
    assert D._parse_spotify_embed(modern, "track", 20)["tracks"][0]["artist"] == \
        "Daft Punk, Pharrell Williams"


def test_tracks_with_no_title_are_dropped():
    tl = [{"title": "Good", "subtitle": "A", "duration": 1000},
          {"title": "", "subtitle": "A", "duration": 1000}]
    out = D._parse_spotify_embed(_page(_entity_with_cover_art(trackList=tl)), "album", 20)
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
