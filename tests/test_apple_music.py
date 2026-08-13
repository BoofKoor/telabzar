"""اپل‌موزیک: درِ ورودی، resolver، استخراجِ feat، و کلیدِ کش.

ردیف‌ها از `tests/fixtures/apple_lookup.json` می‌آیند — **دامپِ واقعیِ**
`itunes.apple.com/lookup`، گرفته‌شده روی مستر از داخلِ download-worker
(2026-08-13) و کپی‌شدهٔ دست‌نخورده. هر ورودیِ آن فایل `_note`ِ خودش را دارد:
مبدأ، و اینکه چه چیزی را اثبات می‌کند و چه چیزی را **نه**.

**نسخهٔ قبلیِ این ردیف‌ها دست‌ساز بود و دو بار تستِ سبزِ بی‌معنا ساخت** — یک‌بار
با گذاشتنِ feat در عنوانِ «Get Lucky» (که سابوتاژِ `collectionArtistName` را
بی‌اثر کرد) و یک‌بار با مدتِ ۳۱۱ ثانیه برای «Faryaad» که عددش از ترکِ دیگری
آمده بود؛ مدتِ واقعی **۴۲۰** ثانیه است. حالا هیچ ردیفی دست‌ساز نیست.

چهار واقعیتِ ساختاری که این تست‌ها رویشان بنا شده‌اند، همه از خودِ دامپ:

* دکمهٔ Share فرمِ آلبوم با `?i=<trackid>` می‌دهد؛ شناسهٔ داخلِ مسیر **آلبوم** است.
* اپل ثابت‌قدم نیست: F2 مهمان را در **عنوان** می‌گذارد و `artistName` تنها
  هنرمندِ اصلی را دارد؛ F6 و F8 هر سه را در `artistName` می‌گذارند.
* کلیدها اختیاری‌اند و **سه شاهدِ مستقل** دارد: F2 اصلاً `collectionArtistName`
  ندارد، ردیفِ collectionِ F3 نه `kind` دارد نه `trackId` نه `trackName`، و F8
  هیچ کلیدِ قیمتی ندارد در حالی که F7 مقدارِ نگهبانِ `trackPrice = -1.0` دارد.
* `collectionExplicitness` و `trackExplicitness` واگرا می‌شوند (F8).
"""
from __future__ import annotations

import json
import pathlib

import pytest
from aiohttp import web

from tests.aiogram_double import ValidatingBot

from app import dl_cache as C
from app import downloader as D
from app import tasks_download as TD
from app.i18n import t

_FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "apple_lookup.json")
                 .read_text(encoding="utf-8"))


def row(key: str) -> dict:
    """ردیفِ خامِ lookup، عیناً همان‌طور که اپل داد."""
    return _FX[key]["results"][0]


def response(key: str) -> dict:
    """کلِ پاسخ، با `resultCount` — برای سرورِ تست."""
    return {k: v for k, v in _FX[key].items() if not k.startswith("_")}


ROW_MARYAM = row("F1_lookup_662720286")
ROW_FARYAAD = row("F2_lookup_305568690")
ROW_COLLECTION = row("F3_lookup_305568683_album")
ROW_MARYAM_GB = row("F5_lookup_662720286_country_gb")
ROW_LUCKY = row("F6_lookup_617154366")
ROW_REMIX = row("F7_lookup_664332744_feat_plus_remix")
ROW_RADIO = row("F8_lookup_1459540658_radio_edit")

# مدتِ واقعیِ Faryaad — از خودِ دامپ خوانده می‌شود، نه هاردکد.
FARYAAD_SECS = round(ROW_FARYAAD["trackTimeMillis"] / 1000)

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
    """نامزدهای یوتیوب، با مدتِ **واقعیِ** ترک از دامپ.

    نسخهٔ قبلی ۳۱۱ ثانیه داشت — عددی که از ترکِ دیگری آمده بود. مدتِ واقعیِ
    Faryaad ۴۲۰ است، و با آن `_duration_reject` نامزدهای ۳۱۱ثانیه‌ای را
    **رد می‌کند** (اختلاف ۱۰۹ ثانیه، ۲۶٪)، پس آن تست‌ها روی فیکسچرِ واقعی
    افتادند. همان چیزی که فیکسچرِ واقعی برای گرفتنش هست.
    """
    return [D._norm_ytm(c, "songs") for c in (
        {"videoId": "correct", "title": "Faryaad (feat. Karim Fakour)",
         "artists": [{"name": "Anoushirvan Rohani"}, {"name": "Karim Fakour"}],
         "album": None, "duration_seconds": FARYAAD_SECS},
        {"videoId": "wrong-singer", "title": "Faryaad",
         "artists": [{"name": "Anoushirvan Rohani"}, {"name": "Maziar"}],
         "album": None, "duration_seconds": FARYAAD_SECS},
    )]


def test_the_hidden_guest_disarms_the_contradiction_gate():
    """مرجعِ خام: نامزدِ خوانندهٔ **غلط** از Art Trackِ درست بالاتر می‌نشیند.

    قاعدهٔ `_artist_contradiction` «جاافتاده **و** اضافه» می‌خواهد؛ با مرجعِ
    تک‌هنرمنده هیچ‌وقت «جاافتاده» نمی‌شود، پس نامزدی که خوانندهٔ دیگری را ادعا
    می‌کند از گیت رد می‌شود. این همان باگی است که قاعدهٔ تناقض ساخته شد تا
    بگیردش.
    """
    raw = {"title": ROW_FARYAAD["trackName"], "artist": ROW_FARYAAD["artistName"],
           "album": "", "duration": FARYAAD_SECS}
    ranked = D._rank_candidates(_cands(), raw)
    order = [D._cand_url(c).rsplit("=", 1)[1] for _s, c in ranked]
    assert order[0] == "wrong-singer", "پیش از رفع: غلط اول است"
    assert D._artist_match(raw, _cands()[0]) < 70


def test_extracting_the_guest_restores_the_right_order_and_rejects_the_wrong_singer():
    title, artist = D._split_feat_title(ROW_FARYAAD["trackName"], ROW_FARYAAD["artistName"])
    fixed = {"title": title, "artist": artist, "album": "", "duration": FARYAAD_SECS}
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
        keys = {"662720286": "F1_lookup_662720286", "305568690": "F2_lookup_305568690",
                "305568683": "F3_lookup_305568683_album", "617154366": "F6_lookup_617154366",
                "664332744": "F7_lookup_664332744_feat_plus_remix",
                "1459540658": "F8_lookup_1459540658_radio_edit"}
        # `country=gb` روی همان ترک پاسخِ **ضبط‌شدهٔ** gb را می‌دهد
        if q.get("id") == "662720286" and q.get("country") == "gb":
            body = response("F5_lookup_662720286_country_gb")
        else:
            key = keys.get(q.get("id", ""))
            body = response(key) if key else {"resultCount": 0, "results": []}
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
    assert tr["duration"] == FARYAAD_SECS == 420  # میلی‌ثانیه → ثانیه، با round
    assert ROW_FARYAAD["trackTimeMillis"] == 420049
    assert tr["year"] == "1970"      # از خودِ دامپ، نه حدس
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


# ── چیزهایی که فیکسچرِ واقعی لو داد ─────────────────────────────
def test_the_album_name_and_the_track_title_are_not_interchangeable():
    """در F7 این دو **عیناً یکی‌اند** تا وقتی عنوان پاک شود، و بعد واگرا می‌شوند.

    اپل برای تک‌آهنگِ ریمیکس، `collectionName` را برابرِ `trackName` می‌گذارد؛
    پس تا وقتی به عنوان دست نزده باشی هیچ تفاوتی دیده نمی‌شود و استفادهٔ اشتباهِ
    یکی به‌جای دیگری بی‌صدا می‌ماند. بعد از پاک‌سازیِ feat، عنوان کوتاه می‌شود و
    آلبوم **نمی‌شود** — آلبوم عمداً پاک نمی‌شود، چون نامِ محصول است نه عنوانِ ترک.
    """
    assert ROW_REMIX["collectionName"] == ROW_REMIX["trackName"]      # از خودِ دامپ
    title, _artist = D._split_feat_title(ROW_REMIX["trackName"], ROW_REMIX["artistName"])
    assert title == "Get Lucky [Daft Punk Remix]"
    assert title != ROW_REMIX["collectionName"]


async def test_the_resolver_keeps_the_album_raw_and_the_title_cleaned(itunes):
    res = await D.apple_resolve("https://music.apple.com/us/song/x/664332744")
    tr = res["tracks"][0]
    assert tr["title"] == "Get Lucky [Daft Punk Remix]"
    assert tr["album"] == ROW_REMIX["collectionName"]                 # خام، پاک‌نشده
    assert D._version_markers(tr["title"]) == {"remix"}               # نشانه زنده ماند


def test_the_remix_guests_come_out_of_the_title_even_though_artist_name_is_one_name():
    """`artistName` این ردیف فقط «Daft Punk» است و هر دو مهمان در عنوان‌اند."""
    assert ROW_REMIX["artistName"] == "Daft Punk"
    _title, artist = D._split_feat_title(ROW_REMIX["trackName"], ROW_REMIX["artistName"])
    assert D._track_artists({"artist": artist}) == [
        "Daft Punk", "Pharrell Williams", "Nile Rodgers"]


# ── explicitness: دو سطح، و واگرا ───────────────────────────────
def test_the_two_explicitness_levels_really_do_diverge_in_the_wild():
    """F8: گلچین «explicit» ولی خودِ ترک «notExplicit» — پین می‌شود تا کیس گم نشود."""
    assert ROW_RADIO["collectionExplicitness"] == "explicit"
    assert ROW_RADIO["trackExplicitness"] == "notExplicit"


async def test_the_resolver_reads_neither_explicitness_field(itunes):
    """**باگ نیست، چون هیچ‌کدام خوانده نمی‌شود** — و این تست جلوی برگشتش را می‌گیرد.

    `apple_resolve` فقط title/artist/album/year/cover_url/duration/isrc می‌دهد و
    هیچ سیگنالِ سنی/محتوایی از اپل نمی‌گیرد؛ گیتِ محتوا روی خودِ دانلودِ یوتیوب
    است (`--match-filter`, `AgeRestricted`). اگر روزی کسی این را وصل کند، باید
    **`trackExplicitness`** را بخواند: با فیلدِ گلچین، همین ترکِ تمیزِ F8 روی یک
    گلچینِ explicit علامت می‌خورد.
    """
    res = await D.apple_resolve("https://music.apple.com/us/song/x/1459540658")
    tr = res["tracks"][0]
    assert set(tr) == {"title", "artist", "album", "year", "cover_url", "duration", "isrc"}
    assert not any("explicit" in k.lower() for k in tr)


# ── خانوادهٔ سه‌تاییِ نسخه‌ها، همه از دامپِ واقعی ────────────────
_FAMILY = [("album", "F6_lookup_617154366"), ("remix", "F7_lookup_664332744_feat_plus_remix"),
           ("radio", "F8_lookup_1459540658_radio_edit")]


def _ref(key: str) -> dict:
    r = row(key)
    title, artist = D._split_feat_title(r["trackName"], r["artistName"])
    return {"title": title, "artist": artist, "album": r["collectionName"],
            "duration": round(r["trackTimeMillis"] / 1000)}


def test_three_real_versions_of_one_title_are_separated_by_duration():
    """۳۷۰ / ۶۳۳ / ۲۴۸ ثانیه — گیتِ مدت هر جفت را رد می‌کند.

    این خانواده رایگان از دامپ درآمد و ارزشش این است که **واقعی** است: سه شکلِ
    متفاوتِ `artistName`/`collectionName` روی یک عنوان. نام به‌تنهایی جدایشان
    نمی‌کند (هر سه «Get Lucky»اند)، پس مدت است که کار را می‌کند.
    """
    refs = {lbl: _ref(k) for lbl, k in _FAMILY}
    assert sorted(r["duration"] for r in refs.values()) == [248, 370, 633]
    for a in refs:
        for b in refs:
            if a == b:
                continue
            cand = {"id": b, "title": refs[b]["title"], "duration_seconds": refs[b]["duration"],
                    "artists": D._track_artists({"artist": refs[b]["artist"]}), "album": None}
            assert D._duration_reject(cand, refs[a]), f"{b} نباید برای {a} قبول شود"


def test_the_version_markers_of_the_family_survive_the_feat_clean():
    got = {lbl: sorted(D._version_markers(_ref(k)["title"])) for lbl, k in _FAMILY}
    assert got == {"album": [], "remix": ["remix"], "radio": ["radio edit"]}


def test_optional_keys_have_three_independent_witnesses_in_the_real_data():
    """چرا `.get()` همه‌جا لازم است — سه شاهد، هیچ‌کدام حدسی."""
    assert "collectionArtistName" not in ROW_FARYAAD          # ترکِ واقعی، کلیدِ غایب
    for k in ("kind", "trackId", "trackName", "trackTimeMillis"):
        assert k not in ROW_COLLECTION                        # ردیفِ آلبوم
    assert ROW_REMIX["trackPrice"] == -1.0                    # مقدارِ نگهبان
    assert not any("rice" in k for k in ROW_RADIO)            # هیچ کلیدِ قیمتی


async def test_the_gb_storefront_returns_the_same_track_with_only_locale_fields_changed(itunes):
    """پاسخِ **ضبط‌شدهٔ** gb — پایهٔ استدلالِ «storefront از کلیدِ کش بیرون».

    این‌جا دو دامپِ واقعی با هم مقایسه می‌شوند، پس ادعا از خودِ اپل می‌آید نه از ما.
    """
    for k in ("trackId", "trackName", "artistName", "collectionName",
              "trackTimeMillis", "previewUrl", "artworkUrl100"):
        assert ROW_MARYAM[k] == ROW_MARYAM_GB[k], k
    assert ROW_MARYAM["country"] == "USA" and ROW_MARYAM_GB["country"] == "GBR"
    assert ROW_MARYAM["trackPrice"] != ROW_MARYAM_GB["trackPrice"]
    res = await D.apple_resolve("https://music.apple.com/gb/song/x/662720286")
    assert res["tracks"][0]["duration"] == 310


async def test_a_song_url_carrying_an_album_id_is_caught_at_the_row_not_the_url(itunes):
    """گاردِ `wrapperType`/`kind` مسیرِ **خودش** را دارد و باید تست شود.

    سابوتاژ نشان داد این گارد تا امروز از هیچ تستی رد نمی‌شد: تستِ لینکِ آلبوم
    پیش از lookup و روی **شکلِ URL** رد می‌شود (`apple_id` می‌گوید «album»)، پس
    هرگز به ردیف نمی‌رسید. برداشتنِ کاملِ گارد، ۵۳ تست را سبز می‌گذاشت.

    این‌جا URL می‌گوید «song» ولی شناسه در واقع آلبوم است — فرمی که یک لینکِ
    دست‌کاری‌شده یا کوتاه‌شده می‌تواند بسازد. آن‌وقت تنها چیزی که جلوی جوابِ غلط
    را می‌گیرد خودِ ردیف است، که `kind` ندارد.
    """
    with pytest.raises(D.AppleUnsupported):
        await D.apple_resolve("https://music.apple.com/us/song/faryaad/305568683")
    assert itunes and itunes[0]["id"] == "305568683", "باید واقعاً lookup زده باشد"
