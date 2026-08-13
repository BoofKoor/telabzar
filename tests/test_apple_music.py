"""اپل‌موزیک: درِ ورودی، resolver، استخراجِ feat، و کلیدِ کش.

⚠ **مرزِ صداقتِ این فایل، صریح:** `itunes.apple.com` از سندباکسِ توسعه در دسترس
نیست (۴۰۳ روی CONNECT، همان سیاستی که `open.spotify.com` را می‌بندد). پس
ردیف‌های زیر **دامپِ ضبط‌شده نیستند**؛ از فیلدهایی ساخته شده‌اند که اپراتور روی
مستر اندازه گرفت و گزارش کرد (شناسه‌های ۶۶۲۷۲۰۲۸۶ و ۳۰۵۵۶۸۶۹۰ و ۳۰۵۵۶۸۶۸۳ و
۶۱۷۱۵۴۳۶۶). یعنی **نامِ فیلدها و حضور/غیابشان واقعی است**، ولی این فایل
اسکیمای اپل را پین نمی‌کند — آن کارِ فیکسچرِ واقعی است وقتی رسید. آنچه این‌جا
پین می‌شود رفتارِ **کدِ خودمان** است.

سه واقعیتِ اندازه‌گیری‌شده که این تست‌ها رویشان بنا شده‌اند:

* دکمهٔ Share فرمِ آلبوم با `?i=<trackid>` می‌دهد؛ شناسهٔ داخلِ مسیر **آلبوم** است.
* اپل ثابت‌قدم نیست: «Faryaad» مهمان را در عنوان می‌گذارد و `artistName` فقط
  هنرمندِ اصلی است؛ «Get Lucky» هر سه را در `artistName` می‌گذارد.
* کلیدها اختیاری‌اند: یک ترکِ واقعی `collectionArtistName` نداشت، و ردیفِ
  `collection` نه `kind` دارد نه `trackId` نه `trackName`.
"""
from __future__ import annotations

import json

import pytest
from aiohttp import web

from tests.aiogram_double import ValidatingBot

from app import dl_cache as C
from app import downloader as D
from app import tasks_download as TD
from app.i18n import t

# ── ردیف‌های lookup (فیلدها واقعی‌اند، بدنه بازسازی‌شده — بالا را بخوان) ──
ROW_MARYAM = {
    "wrapperType": "track", "kind": "song", "trackId": 662720286,
    "trackName": "Jan-e Maryam", "artistName": "Mohammad Noori & Kambiz Mojdehi",
    "collectionName": "Mohammad Noori 5", "collectionArtistName": "Mohammad Noori",
    "trackTimeMillis": 310000, "releaseDate": "1996-06-03T12:00:00Z",
    "trackExplicitness": "notExplicit", "artworkUrl100": "https://is1.example/100x100bb.jpg",
    "previewUrl": "https://audio.example/p.m4a", "trackNumber": 3, "trackCount": 12,
}
# مهمان در **عنوان**، و این ردیف عمداً `collectionArtistName` ندارد (مثلِ واقعی).
ROW_FARYAAD = {
    "wrapperType": "track", "kind": "song", "trackId": 305568690,
    "trackName": "Faryaad (feat. Karim Fakour)", "artistName": "Anoushirvan Rohani",
    "collectionName": "Faryaad", "trackTimeMillis": 311000,
    "releaseDate": "1996-06-03T12:00:00Z", "artworkUrl100": "https://is1.example/a.jpg",
}
# شکلِ **دومِ** اپل، همان‌طور که اپراتور گزارش کرد: هر سه هنرمند در `artistName`
# و عنوان **تمیز**. نسخهٔ اولِ این ردیف feat را در عنوان هم گذاشته بود — حدسِ من،
# نه دادهٔ گزارش‌شده — و همان حدس یک تست را vacuous کرد: با feat در عنوان،
# استخراج هنرمندانِ گم‌شده را برمی‌گرداند و سابوتاژِ `collectionArtistName` بی‌اثر
# می‌شد. با عنوانِ تمیز (شکلِ واقعی) استفاده از هنرمندِ آلبوم واقعاً دو مهمان را
# می‌اندازد، که همان چیزی است که تست ادعا می‌کند.
ROW_LUCKY = {
    "wrapperType": "track", "kind": "song", "trackId": 617154366,
    "trackName": "Get Lucky",
    "artistName": "Daft Punk, Pharrell Williams & Nile Rodgers",
    "collectionArtistName": "Daft Punk", "collectionName": "Random Access Memories",
    "trackTimeMillis": 369000, "releaseDate": "2013-05-17T07:00:00Z",
}
# ردیفِ آلبوم: نه `kind`، نه `trackId`، نه `trackName`.
ROW_COLLECTION = {
    "wrapperType": "collection", "collectionType": "Album", "collectionId": 305568683,
    "collectionName": "Faryaad", "artistName": "Anoushirvan Rohani", "trackCount": 13,
    "amgArtistId": 123456, "copyright": "℗ 1996",
}

SHARE_URL = "https://music.apple.com/us/album/faryaad-feat-karim-fakour/305568683?i=305568690&ls"


# ── درِ ورودی ────────────────────────────────────────────────────
@pytest.mark.parametrize("url,expected", [
    # **تلهٔ اصلی**: شناسهٔ مسیر آلبوم است، ترک در `?i=` نشسته.
    (SHARE_URL, ("track", "305568690", "us")),
    ("https://music.apple.com/us/album/mohammad-noori-5/662720280?i=662720286",
     ("track", "662720286", "us")),
    ("https://music.apple.com/us/song/jan-e-maryam/662720286", ("track", "662720286", "us")),
    ("https://music.apple.com/gb/album/random-access-memories/617154346",
     ("album", "617154346", "gb")),
    # شناسهٔ پلی‌لیست عددی نیست.
    ("https://music.apple.com/fr/playlist/persian/pl.u-abc123", ("playlist", "pl.u-abc123", "fr")),
    ("https://music.apple.com/album/x/305568683", ("album", "305568683", None)),
    ("https://geo.music.apple.com/us/album/x/305568683?i=305568690",
     ("track", "305568690", "us")),
    ("https://itunes.apple.com/us/album/x/305568683?i=305568690&uo=4",
     ("track", "305568690", "us")),
    ("https://music.apple.com/us/artist/haydeh/301234567", (None, None, "us")),
    ("https://open.spotify.com/track/ABC", (None, None, None)),
])
def test_apple_id_reads_the_entity_the_link_actually_names(url, expected):
    """`?i=` بر آخرین بخشِ مسیر مقدم است.

    پارسری که آخرین بخشِ مسیر را بردارد، برای لینکِ Share شناسهٔ **آلبوم**
    (۳۰۵۵۶۸۶۸۳) را می‌گیرد، lookup یک ردیفِ `collection` برمی‌گرداند و کاربر
    بی‌دلیل «پشتیبانی نمی‌شود» می‌بیند — با اینکه لینکش یک ترک بود.
    """
    assert D.apple_id(url) == expected


def test_apple_is_routed_as_its_own_platform_without_moving_spotify():
    assert D.platform_of(SHARE_URL) == "apple"
    assert D.engine_for(SHARE_URL) == "apple"
    assert "apple" in D.AUDIO_PLATFORMS          # منوی کیفیت بی‌معنی است
    # رگرسیون: اسپاتیفای دقیقاً همان رشتهٔ قبلی را می‌گیرد
    assert D.engine_for("https://open.spotify.com/track/ABC") == "spotify"


def test_apple_inherits_the_cache_guards_by_being_a_match_platform():
    """عضویت در `_MATCH_PLATFORMS` هر دو محافظت را با هم می‌آورد.

    اگر اپل آن‌جا نباشد، کلید نسخه نمی‌گیرد **و** `get_cached` به کلیدِ legacy
    می‌افتد — یعنی ردیفی از دورانِ `platform='other'` می‌تواند سرو شود.
    """
    assert "apple" in D._MATCH_PLATFORMS
    assert C._we_choose_the_target(SHARE_URL) is True
    assert C.cache_key(SHARE_URL, "audio") != C._legacy_key(SHARE_URL, "audio")


# ── کلیدِ کش ─────────────────────────────────────────────────────
def test_storefront_is_out_of_the_key_but_the_track_id_is_not():
    """`us` و `gb` و فرمِ `/song/` یک ردیف؛ آلبوم ردیفِ جدا.

    شناسه سراسری است (`country=gb` همان ترک را داد و فقط قیمت/ارز/لینک عوض شد)،
    پس storefront همان `intl-fa`ِ اسپاتیفاست و باید از کلید بیرون بماند.
    """
    a = C.cache_key(SHARE_URL, "audio")
    b = C.cache_key("https://music.apple.com/gb/album/x/305568683?i=305568690", "audio")
    c = C.cache_key("https://music.apple.com/us/song/x/305568690", "audio")
    assert a == b == c
    assert C.cache_key("https://music.apple.com/us/album/x/305568683", "audio") != a


def test_two_tracks_of_one_album_do_not_share_a_key():
    """اگر `?i=` نادیده گرفته شود هر دو `am:album:305568683` می‌شوند → فایلِ غلط."""
    one = C.cache_key("https://music.apple.com/us/album/x/305568683?i=305568690", "audio")
    two = C.cache_key("https://music.apple.com/us/album/x/305568683?i=305568691", "audio")
    assert one != two


def test_the_cache_url_shape_is_am_kind_id():
    assert C._cache_url(SHARE_URL) == "am:track:305568690"
    assert C._cache_url("https://music.apple.com/fr/playlist/x/pl.u-a1") == "am:playlist:pl.u-a1"


# ── استخراجِ feat ────────────────────────────────────────────────
@pytest.mark.parametrize("title,artist,want_title,want_artists", [
    ("Faryaad (feat. Karim Fakour)", "Anoushirvan Rohani",
     "Faryaad", ["Anoushirvan Rohani", "Karim Fakour"]),
    # شکلِ دومِ اپل: همه در artistName، عنوانِ تمیز → بدونِ تکرار
    ("Get Lucky", "Daft Punk, Pharrell Williams & Nile Rodgers",
     "Get Lucky", ["Daft Punk", "Pharrell Williams", "Nile Rodgers"]),
    # همان نام‌ها در **هر دو** جا → باز هم بدونِ تکرار
    ("Get Lucky (feat. Pharrell Williams & Nile Rodgers)",
     "Daft Punk, Pharrell Williams & Nile Rodgers",
     "Get Lucky", ["Daft Punk", "Pharrell Williams", "Nile Rodgers"]),
    ("Get Lucky (feat. Pharrell Williams & Nile Rodgers)", "Daft Punk, Pharrell Williams",
     "Get Lucky", ["Daft Punk", "Pharrell Williams", "Nile Rodgers"]),
    # اختلافِ حروف/فاصله هم تکراری شمرده می‌شود (مقایسه با `_norm`)
    ("Song (feat. pharrell  williams)", "Daft Punk, Pharrell Williams",
     "Song", ["Daft Punk", "Pharrell Williams"]),
    ("Jan-e Maryam", "Mohammad Noori & Kambiz Mojdehi",
     "Jan-e Maryam", ["Mohammad Noori", "Kambiz Mojdehi"]),
])
def test_feat_extraction_handles_both_apple_shapes_without_duplicating(
        title, artist, want_title, want_artists):
    got_title, got_artist = D._split_feat_title(title, artist)
    assert got_title == want_title
    assert D._track_artists({"artist": got_artist}) == want_artists


@pytest.mark.parametrize("title,clean,markers", [
    # نشانهٔ نسخه باید **بماند** — وگرنه پاک‌سازی همان چیزی را می‌کشد که جریمه
    # برای گرفتنش هست.
    ("Get Lucky (feat. Pharrell Williams & Nile Rodgers) [Daft Punk Remix]",
     "Get Lucky [Daft Punk Remix]", {"remix"}),
    ("Get Lucky (Radio Edit)", "Get Lucky (Radio Edit)", {"radio edit"}),
    ("Jan-e Maryam (Live) [feat. X]", "Jan-e Maryam (Live)", {"live"}),
    ("Song [Extended Mix] (feat. A)", "Song [Extended Mix]", {"extended mix"}),
    # `with` عمداً نشانهٔ feat نیست: این یک نشانهٔ تنظیم است، نه اعتبارِ مهمان
    ("Song (With Strings)", "Song (With Strings)", set()),
    ("Song (Live with the Orchestra)", "Song (Live with the Orchestra)", {"live"}),
])
def test_the_title_clean_is_surgical_and_version_markers_survive(title, clean, markers):
    got, _ = D._split_feat_title(title, "A")
    assert got == clean
    assert D._version_markers(got) == markers


def test_a_band_name_in_a_feat_credit_no_longer_costs_a_false_penalty():
    """«(feat. Session Band)» امروز `session` را فعال می‌کند؛ پاک‌سازی می‌بنددش.

    این هزینهٔ پذیرفته‌شدهٔ `_penalty_text` بود و برای اسپاتیفای نظری می‌ماند
    (feat هرگز در عنوان نبود)؛ اپل feat را **همیشه** در عنوان می‌گذارد.
    """
    assert D._version_markers("Song (feat. Session Band)") == {"session"}
    clean, _ = D._split_feat_title("Song (feat. Session Band)", "A")
    assert D._version_markers(clean) == set()


def test_the_guest_only_comes_from_the_feat_bracket_not_from_a_marker_bracket():
    _title, artist = D._split_feat_title(
        "Get Lucky (feat. Pharrell Williams) [Daft Punk Remix]", "Daft Punk")
    assert D._track_artists({"artist": artist}) == ["Daft Punk", "Pharrell Williams"]


# ── چرا استخراج مهم است: وارونگیِ رتبه ───────────────────────────
def _cands() -> list[dict]:
    return [D._norm_ytm(c, "songs") for c in (
        {"videoId": "correct", "title": "Faryaad (feat. Karim Fakour)",
         "artists": [{"name": "Anoushirvan Rohani"}, {"name": "Karim Fakour"}],
         "album": None, "duration_seconds": 311},
        {"videoId": "wrong-singer", "title": "Faryaad",
         "artists": [{"name": "Anoushirvan Rohani"}, {"name": "Maziar"}],
         "album": None, "duration_seconds": 311},
    )]


def test_the_hidden_guest_disarms_the_contradiction_gate():
    """مرجعِ خام: نامزدِ خوانندهٔ **غلط** از Art Trackِ درست بالاتر می‌نشیند.

    قاعدهٔ `_artist_contradiction` «جاافتاده **و** اضافه» می‌خواهد؛ با مرجعِ
    تک‌هنرمنده هیچ‌وقت «جاافتاده» نمی‌شود، پس نامزدی که خوانندهٔ دیگری را ادعا
    می‌کند از گیت رد می‌شود. این همان باگی است که قاعدهٔ تناقض ساخته شد تا
    بگیردش.
    """
    raw = {"title": ROW_FARYAAD["trackName"], "artist": ROW_FARYAAD["artistName"],
           "album": "", "duration": 311}
    ranked = D._rank_candidates(_cands(), raw)
    order = [D._cand_url(c).rsplit("=", 1)[1] for _s, c in ranked]
    assert order[0] == "wrong-singer", "پیش از رفع: غلط اول است"
    assert D._artist_match(raw, _cands()[0]) < 70


def test_extracting_the_guest_restores_the_right_order_and_rejects_the_wrong_singer():
    title, artist = D._split_feat_title(ROW_FARYAAD["trackName"], ROW_FARYAAD["artistName"])
    fixed = {"title": title, "artist": artist, "album": "", "duration": 311}
    ranked = D._rank_candidates(_cands(), fixed)
    order = [D._cand_url(c).rsplit("=", 1)[1] for _s, c in ranked]
    assert order[0] == "correct"
    assert "wrong-singer" not in order, "قاعدهٔ تناقض باید حالا بگیردش"
    assert D._artist_match(fixed, _cands()[0]) == 100.0


def test_the_hidden_guest_also_costs_the_second_query_shape():
    """با مهمانِ پنهان `arts[0] == arts[-1]` → یک کوئری. شکلِ دوم همان است که
    برای موسیقیِ ایرانی **خواننده** را پیدا می‌کند."""
    raw = {"title": ROW_FARYAAD["trackName"], "artist": ROW_FARYAAD["artistName"]}
    title, artist = D._split_feat_title(raw["title"], raw["artist"])
    assert len(D._search_queries(raw)) == 1
    assert D._search_queries({"title": title, "artist": artist}) == [
        "Anoushirvan Rohani Faryaad", "Karim Fakour Faryaad"]


# ── resolver روی یک سرورِ واقعی ──────────────────────────────────
@pytest.fixture
async def itunes(monkeypatch):
    """سرورِ واقعیِ aiohttp که مثلِ خودِ iTunes جواب می‌دهد (و مثلِ آن ۴۰۰ می‌دهد).

    ماک نیست، طبقِ قاعدهٔ «واقعی به‌جای ماک» — پس مسیرِ HTTP و شاخهٔ retry
    واقعاً اجرا می‌شوند.
    """
    seen: list[dict] = []

    async def lookup(req):
        q = dict(req.query)
        seen.append(q)
        if q.get("country") == "zz":
            return web.Response(status=400, text="")     # سنجیده‌شده روی مستر
        rows = {"662720286": ROW_MARYAM, "305568690": ROW_FARYAAD,
                "617154366": ROW_LUCKY, "305568683": ROW_COLLECTION}
        row = rows.get(q.get("id", ""))
        body = {"resultCount": 1 if row else 0, "results": [row] if row else []}
        return web.Response(text=json.dumps(body), content_type="text/javascript")

    app = web.Application()
    app.router.add_route("*", "/lookup", lookup)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    monkeypatch.setattr(D, "_ITUNES_LOOKUP", f"http://127.0.0.1:{port}/lookup")
    yield seen
    await runner.cleanup()


async def test_a_share_link_resolves_to_the_track_the_i_param_names(itunes):
    res = await D.apple_resolve(SHARE_URL)
    assert itunes[0]["id"] == "305568690"        # نه ۳۰۵۵۶۸۶۸۳ِ آلبوم
    assert itunes[0]["country"] == "us"
    tr = res["tracks"][0]
    assert tr["title"] == "Faryaad"
    assert D._track_artists(tr) == ["Anoushirvan Rohani", "Karim Fakour"]
    assert tr["album"] == "Faryaad"
    assert tr["duration"] == 311                 # میلی‌ثانیه → ثانیه، با round
    assert tr["year"] == "1996"
    assert tr["isrc"] is None
    # شکلِ دیکشنری باید با مسیرِ اسپاتیفای یکی بماند
    assert set(tr) == {"title", "artist", "album", "year", "cover_url", "duration", "isrc"}


async def test_the_reference_dict_matches_the_spotify_shape_exactly(itunes):
    apple = (await D.apple_resolve("https://music.apple.com/us/song/x/662720286"))["tracks"][0]
    spotify = D._embed_track("T", [{"name": "A"}], None, 310000)
    assert set(apple) == set(spotify)


async def test_the_collection_artist_is_not_used_as_the_track_artist(itunes):
    """`collectionArtistName` هنرمندِ **آلبوم** است — «Daft Punk» در برابرِ هر سه."""
    res = await D.apple_resolve("https://music.apple.com/us/song/x/617154366")
    assert D._track_artists(res["tracks"][0]) == [
        "Daft Punk", "Pharrell Williams", "Nile Rodgers"]


async def test_a_row_without_collection_artist_name_does_not_raise(itunes):
    """کلیدها اختیاری‌اند — ردیفِ Faryaad اصلاً `collectionArtistName` ندارد."""
    assert "collectionArtistName" not in ROW_FARYAAD
    res = await D.apple_resolve(SHARE_URL)
    assert res["tracks"][0]["artist"]


async def test_an_album_link_is_refused_loudly_not_answered_wrongly(itunes):
    """ردیفِ collection نه `kind` دارد نه `trackId` — جوابِ غلطِ بی‌صدا ممنوع."""
    with pytest.raises(D.AppleUnsupported):
        await D.apple_resolve("https://music.apple.com/us/album/faryaad/305568683")


async def test_a_playlist_link_is_refused_without_even_a_lookup(itunes):
    with pytest.raises(D.AppleUnsupported):
        await D.apple_resolve("https://music.apple.com/fr/playlist/x/pl.u-abc123")
    assert itunes == [], "پلی‌لیست نباید حتی یک درخواست خرج کند"


async def test_an_unknown_id_gives_a_clear_error_not_an_index_error(itunes):
    """`resultCount == 0` → `results` خالی؛ `results[0]` `IndexError` می‌داد."""
    with pytest.raises(RuntimeError, match="no such track"):
        await D.apple_resolve("https://music.apple.com/us/song/x/999999999")


async def test_a_bad_storefront_retries_without_country_instead_of_failing(itunes):
    """`country=zz` روی مستر **HTTP 400** داد، نه resultCountِ صفر.

    پس شاخهٔ retry باید استثنا را هم بگیرد، نه فقط نتیجهٔ خالی را — وگرنه یک
    storefrontِ نامعتبر کلِ لینک را می‌شکست.
    """
    res = await D.apple_resolve("https://music.apple.com/zz/song/x/662720286")
    assert [q.get("country") for q in itunes] == ["zz", None]
    assert res["tracks"][0]["title"] == "Jan-e Maryam"


async def test_the_lookup_asks_for_songs_so_the_album_branch_stays_out(itunes):
    await D.apple_resolve(SHARE_URL)
    assert itunes[0].get("entity") == "song"


# ── انتها به انتها: لینکِ آلبوم نباید استخرِ کوکی را بسوزاند ──────
class _Bot(ValidatingBot):
    """امضاها از خودِ aiogram bind می‌شوند — نه از فهرستِ دستیِ ماک."""

    def __init__(self) -> None:
        self.edits: list[str] = []
        self.messages: list[str] = []

    def _on(self, name, payload):
        if name == "edit_message_text":
            self.edits.append(payload["text"])
        elif name == "edit_message_caption":
            self.edits.append(payload.get("caption"))
        elif name == "send_message":
            self.messages.append(payload["text"])
        return True


@pytest.fixture
def album_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path))
    return {"ref": "apl12345", "chat_id": 7, "status_mid": 9, "lang": "fa",
            "url": "https://music.apple.com/us/album/faryaad/305568683",
            "platform": "apple", "engine": "apple", "phase": "fetch",
            "selector": "audio", "owner_id": 1, "tg_user_id": 42}


async def test_an_album_link_tells_the_user_instead_of_failing_obscurely(album_payload, redis):
    bot = _Bot()
    await TD.run_download({"bot": bot, "redis": redis}, album_payload)
    assert t("fa", "dl_apple_entity") in bot.edits


async def test_an_album_link_does_not_walk_the_whole_youtube_cookie_pool(
        album_payload, redis, tmp_path, monkeypatch):
    """چرخش این‌جا کلِ استخر را برای لینکی می‌سوزاند که هیچ‌وقت کار نمی‌کند.

    اپل فایل را از یوتیوب می‌گیرد، پس `_cookie_platform` کوکیِ **یوتیوب**
    می‌خواهد؛ بدونِ شاخهٔ اختصاصی، `AppleUnsupported` به `except Exception`
    می‌افتاد و به‌ازای هر اکانت یک تلاش خرج می‌شد — همان «یک URLِ خراب کلِ استخر
    را می‌خورد» که §۷ دربارهٔ خطاهای غیرِکوکی هشدار می‌دهد.
    """
    from app import cookies as ck
    monkeypatch.setattr(ck.settings, "cookies_dir", str(tmp_path / "ck"))
    (tmp_path / "ck").mkdir(exist_ok=True)
    netscape = ("# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tLOGIN_INFO\tvalue\n")
    for name in ("youtube-a.txt", "youtube-b.txt"):
        assert await ck._save_cookie(redis, name, netscape) == ""
    assert await ck.accounts(redis, "youtube"), "تست باید واقعاً اکانت داشته باشد"

    await TD.run_download({"bot": _Bot(), "redis": redis}, album_payload)

    for acct in await ck.accounts(redis, "youtube"):
        assert acct["fail_streak"] == 0, f"{acct['name']} نباید ضربه خورده باشد"
        assert acct["status"] == "healthy", f"{acct['name']} باید سالم بماند"


async def test_the_album_link_frees_the_concurrency_slot(album_payload, redis):
    from app import dl_active
    await TD.run_download({"bot": _Bot(), "redis": redis}, album_payload)
    assert await dl_active.count(redis) == 0
