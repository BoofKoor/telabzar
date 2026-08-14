"""مسیرِ ناشناسِ اینستاگرام (`app/instagram_anon.py`) — فاز ۱.

**فیکسچرها ضبطِ واقعی‌اند، نه ساختگی.** `tests/fixtures/ig_embed_{reel,carousel,
photo}.html` دقیقاً بایتِ پاسخِ `www.instagram.com/p/<sc>/embed/captioned/` روی
مسترِ تولید (VPSِ هلند، ۲۰۲۶-۰۸-۱۴) هستند، دست‌نخورده. دلیلش همان درسِ §۶ است:
دابلی که شکلِ خودش را تعریف کند، شکلِ واقعیِ API را پنهان می‌کند — و این ماژول
هیچ قراردادی جز «هرچه اینستاگرام امروز می‌دهد» ندارد.

اندازه‌گیریِ کنارِ ضبط، برای اینکه کسی دوباره از صفر شروع نکند: **هر دو شکلِ
`/p/<sc>/embed/captioned/` و `/reel/<sc>/embed/captioned/` برای هر سه لینک
HTTP 200 دادند** و ساختارِ پارس‌شده‌شان یکسان بود، پس کد مثلِ cobalt همیشه `/p/`
می‌سازد. فقط شکلِ `-p` کامیت شد؛ نگه‌داشتنِ هر دو حجمِ فیکسچر را دو برابر
می‌کرد بی‌آنکه چیزی دربارهٔ **کدِ ما** ثابت کند.

**شکافِ پوششیِ ثبت‌شده:** کاروسلِ واقعی هر ۱۱ فرزندش عکس است (`is_video=False`،
بدونِ `video_url`). پس شاخهٔ «فرزندِ ویدیویی» با دادهٔ واقعی **اصلاً اجرا
نمی‌شود** و تستی که روی این فیکسچر ادعا کند «ویدیو از `video_url` می‌آید»
توخالی است. آن شاخه این‌جا با `gql_data`ِ **دست‌ساز** تست می‌شود — که برای
سنجشِ *منطقِ خودمان* درست است، برخلافِ سنجشِ *شکلِ API*.
"""
from __future__ import annotations

import json
import logging
import pathlib
import re

import pytest
from aiohttp import web

from app import downloader as D
from app import instagram_anon as IA

FX = pathlib.Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FX / f"ig_embed_{name}.html").read_text(encoding="utf-8", errors="replace")


# ── ۱) استخراج از فیکسچرِ واقعی ──────────────────────────────────
def test_reel_yields_a_single_video_from_gql():
    content, items, caption = IA.parse_embed_page(_fixture("reel"))[0]
    assert content == IA.CONTENT_SINGLE_VIDEO
    assert len(items) == 1 and items[0].kind == "video"
    assert items[0].url.startswith("https://scontent-")
    assert caption and "تکنیک" in caption


def test_carousel_yields_eleven_items_in_order():
    """۱۱ عدد از دامپِ واقعی است، نه انتخابِ من — و ترتیب باربر است چون
    کاروسل در تلگرام به‌همان ترتیب فرستاده می‌شود."""
    content, items, _cap = IA.parse_embed_page(_fixture("carousel"))[0]
    assert content == IA.CONTENT_CAROUSEL
    assert len(items) == 11
    assert {i.kind for i in items} == {"photo"}

    raw = json.loads(json.loads(IA._INIT_RE.search(_fixture("carousel")).group(1))["contextJSON"])
    expected = [e["node"]["display_url"]
                for e in raw["gql_data"]["shortcode_media"]["edge_sidecar_to_children"]["edges"]]
    assert [i.url for i in items] == expected, "ترتیبِ فرزندان باید دقیقاً حفظ شود"


def test_single_photo_comes_from_the_img_fallback_and_picks_the_widest_candidate():
    """(الف) تکـعکسی: `contextJSON` مقدارش null است، پس مسیرِ gql می‌افتد و رسانه
    باید از `<img class="EmbeddedMediaImage" srcset>` بیاید — با بزرگ‌ترین کاندید.

    عددِ ۳۰۷۲ از خودِ فیکسچر خوانده می‌شود نه هاردکد، وگرنه با عوض‌شدنِ دامپ
    تست به دلیلِ غلط قرمز می‌شود.
    """
    page = _fixture("photo")
    assert IA.extract_from_gql(None) is None, "پیش‌شرط: مسیرِ gql این‌جا چیزی ندارد"

    content, items, _cap = IA.parse_embed_page(page)[0]
    assert content == IA.CONTENT_SINGLE_PHOTO and len(items) == 1

    tag = IA._EMBEDDED_IMG_RE.search(page).group(0)
    srcset = IA._SRCSET_RE.search(tag).group(1)
    widths = [int(m.group(1)) for m in
              (IA._SRCSET_W_RE.search(t.strip()) for t in srcset.split(",")) if m]
    assert max(widths) == 3072, "فیکسچر عوض شده — این تست دربارهٔ «بزرگ‌ترین» است"

    widest = next(t.strip() for t in srcset.split(",")
                  if (m := IA._SRCSET_W_RE.search(t.strip())) and int(m.group(1)) == 3072)
    import html as _h
    assert items[0].url == _h.unescape(widest[:IA._SRCSET_W_RE.search(widest).start()].strip())


def test_the_photo_fixture_really_has_a_null_contextjson_not_a_missing_key():
    """تلهٔ ۲: چکِ «کلید موجود است» این حالت را رد می‌کند و پارس می‌ترکد."""
    init = json.loads(IA._INIT_RE.search(_fixture("photo")).group(1))
    assert "contextJSON" in init and init["contextJSON"] is None
    assert init["isRichEmbed"] is False, "پس گیت‌کردن روی isRichEmbed هم غلط بود"


def test_the_img_url_is_html_unescaped():
    """`srcset` داخلِ HTML است، پس `&` در آن `&amp;` نوشته شده. بدونِ unescape
    پارامترهای امضا خراب به CDN می‌رفتند. مسیرِ `gql_data` این مشکل را ندارد."""
    url = IA.parse_embed_page(_fixture("photo"))[0][1][0].url
    assert "&amp;" not in url and "&" in url

    raw_srcset = IA._SRCSET_RE.search(IA._EMBEDDED_IMG_RE.search(_fixture("photo")).group(0)).group(1)
    assert "&amp;" in raw_srcset, "کنترل: منبع واقعاً escape شده بود"


@pytest.mark.parametrize("name", ["reel", "carousel", "photo"])
def test_no_icon_or_foreign_host_survives(name):
    items = IA.parse_embed_page(_fixture(name))[0][1]
    assert items
    for it in items:
        assert "/rsrc.php/" not in it.url
        assert not it.url.split("/")[2].startswith("static.")
        assert IA._is_media_url(it.url)


@pytest.mark.parametrize("name,expected", [("reel", "Db8fsxMsATy"),
                                           ("carousel", "DbkmloxCI5b"),
                                           ("photo", "Db8kJCZu-go")])
def test_shortcode_round_trips_through_every_link_shape(name, expected):
    for shape in ("p", "reel", "reels", "tv"):
        assert IA.shortcode_of(f"https://www.instagram.com/{shape}/{expected}/") == expected
    assert IA.shortcode_of(f"https://www.instagram.com/p/{expected}/?igsh=abc") == expected
    assert IA.shortcode_of("https://www.instagram.com/someuser/") is None
    # کپشن: از gql می‌آید و در مسیرِ img عمداً None می‌ماند (§۷)
    caption = IA.parse_embed_page(_fixture(name))[0][2]
    assert (caption is None) == (name == "photo")


def test_the_img_fallback_is_sequential_not_parallel():
    """کنترلِ معکوس: روی ریل و کاروسل زیرشاخهٔ img باید **صفر** بار صدا شود.

    بدونِ این، «fallback هست» و «fallback مسیرِ موازی است» از بیرون یکی
    به‌نظر می‌رسند، و دومی یعنی هزینهٔ regex روی هر صفحهٔ ۳۵۰ کیلوبایتی.
    """
    calls: list[str] = []
    original = IA.extract_from_img
    IA.extract_from_img = lambda page: (calls.append("x"), original(page))[1]
    try:
        IA.parse_embed_page(_fixture("reel"))
        IA.parse_embed_page(_fixture("carousel"))
        assert calls == [], "gql جواب داده بود؛ img نباید اصلاً صدا شود"
        IA.parse_embed_page(_fixture("photo"))
        assert len(calls) == 1
    finally:
        IA.extract_from_img = original


# ── ۲) ورودیِ دست‌ساز: منطقِ خودمان، نه شکلِ API ─────────────────
def _gql(media: dict) -> dict:
    return {"shortcode_media": media}


def test_a_video_child_uses_video_url_not_display_url():
    """شکافِ پوششی: کاروسلِ واقعی هیچ فرزندِ ویدیویی ندارد، پس این شاخه فقط
    این‌جا اجرا می‌شود."""
    out = IA.extract_from_gql(_gql({"edge_sidecar_to_children": {"edges": [
        {"node": {"is_video": True,
                  "video_url": "https://scontent-x.cdninstagram.com/v.mp4",
                  "display_url": "https://scontent-x.cdninstagram.com/poster.jpg"}},
        {"node": {"is_video": False,
                  "display_url": "https://scontent-x.cdninstagram.com/p.jpg"}},
    ]}}))
    content, items, _cap = out
    assert content == IA.CONTENT_CAROUSEL
    assert [(i.kind, i.url.rsplit("/", 1)[-1]) for i in items] == [
        ("video", "v.mp4"), ("photo", "p.jpg")]


def test_a_video_child_without_video_url_drops_the_whole_rung():
    """تصمیم ۶: بهتر است کلِ کاروسل به مسیرِ کوکی بیفتد تا اینکه ۱۰ عکس و یک
    **فریمِ پوستر** تحویل شود. cobalt این‌جا بی‌صدا پوستر می‌دهد؛ ما نه.

    و علت باید **مشخص** باشد (کدام فرزند)، نه یک no_mediaِ ژنریک، وگرنه
    تله‌متریِ فاز ۲ نمی‌تواند drift را از انتظارِ عادی تفکیک کند.
    """
    with pytest.raises(IA._VideoUrlMissing) as exc:
        IA.extract_from_gql(_gql({"edge_sidecar_to_children": {"edges": [
            {"node": {"is_video": False,
                      "display_url": "https://scontent-x.cdninstagram.com/a.jpg"}},
            {"node": {"is_video": True,
                      "display_url": "https://scontent-x.cdninstagram.com/poster.jpg"}},
        ]}}))
    assert "child 1" in exc.value.detail and "video_url" in exc.value.detail


def test_a_single_post_claiming_video_without_a_url_also_drops():
    """همان قاعده در سطحِ تک‌آیتم — وگرنه پستِ ویدیویی به‌صورتِ عکس تحویل می‌شد."""
    with pytest.raises(IA._VideoUrlMissing):
        IA.extract_from_gql(_gql({"is_video": True,
                                  "display_url": "https://scontent-x.cdninstagram.com/p.jpg"}))


def test_an_icon_url_in_a_structured_field_is_still_rejected():
    """لایهٔ دوم. روی فیکسچرِ واقعی هرگز شلیک نمی‌شود، پس تستش **باید**
    دست‌ساز باشد؛ روی فیکسچر توخالی می‌بود."""
    assert IA.extract_from_gql(_gql({
        "display_url": "https://static.cdninstagram.com/rsrc.php/v3/y/spinner.webp"})) is None
    assert IA.extract_from_gql(_gql({"display_url": "https://evil.example/x.jpg"})) is None


def test_xdt_shortcode_media_is_read_too():
    """تلهٔ `instagram.js:301`: پاسخِ GraphQL این کلید را می‌دهد، پاسخِ embed آن
    یکی را. تک‌کلیده نوشتنش ردهٔ آیندهٔ GraphQL را بی‌صدا می‌شکند."""
    out = IA.extract_from_gql({"xdt_shortcode_media": {
        "video_url": "https://scontent-x.cdninstagram.com/v.mp4"}})
    assert out is not None and out[0] == IA.CONTENT_SINGLE_VIDEO


@pytest.mark.parametrize("page", [
    "",
    "<html>nothing here</html>",
    '<script>requireLazy(["init",[],[{"contextJSON":"{not json"}]],0)</script>',
    '<script>requireLazy(["init",[],[not-json]],0)</script>',
    '<script>requireLazy(["init",[],[{"contextJSON":null}]],0)</script>',
])
def test_a_broken_page_reports_instead_of_crashing(page):
    media, note = IA.parse_embed_page(page)
    assert media is None
    assert isinstance(note, str)


def test_a_classless_img_is_never_taken():
    """در HTMLِ واقعیِ تکـعکسی دو `<img srcset>`ِ بی‌کلاسِ دیگر هم هست و **هر
    دو روی cdninstagram**اند — پس فیلترِ هاست نمی‌گیردشان و فقط هدف‌گیریِ
    `class="EmbeddedMediaImage"` کار می‌کند."""
    others = [t for t in re.findall(r"<img[^>]*srcset=[^>]*>", _fixture("photo"))
              if "EmbeddedMediaImage" not in t]
    assert len(others) == 2, "کنترل: فیکسچر واقعاً `<img>`ِ دیگر دارد"
    assert all("cdninstagram.com" in t for t in others), "و فیلترِ هاست نمی‌گیردشان"

    page = '<img class="Avatar" srcset="https://scontent-x.cdninstagram.com/a.jpg 320w">'
    assert IA.extract_from_img(page) is None


# ── ۳) رفتار روی شبکه: سرورِ aiohttp واقعی، نه ماک ───────────────
@pytest.fixture
async def server():
    """سرورِ **واقعی** روی لوپ‌بک که نقشِ اینستاگرام را بازی می‌کند.

    ماک نمی‌کنیم چون آن‌وقت شکلِ سشنِ aiohttp را خودمان تعریف می‌کردیم — همان
    تله‌ای که §۶ دربارهٔ `FakeBot` ثبت کرده.
    """
    seen: list[dict] = []

    async def handler(req: web.Request):
        seen.append({"path": req.path, "headers": dict(req.headers), "query": req.query_string})
        mode = req.query.get("mode", "ok")
        if mode == "boom":
            raise web.HTTPInternalServerError(text="kaput")
        if mode == "403":
            return web.Response(status=403, text='{"message":"login_required"}')
        if mode == "404":
            return web.Response(status=404, text="gone")
        if mode == "junk":      # نه بلاکِ init، نه تگِ عکس → parse_failed
            return web.Response(text="<html>no media at all</html>", content_type="text/html")
        if mode == "empty":     # بلاکِ init سالم ولی بی‌رسانه → no_media
            return web.Response(
                text='<script>requireLazy(["init",[],[{"contextJSON":null}]],0)</script>',
                content_type="text/html")
        if mode == "oembed":
            return web.json_response({"media_id": "123_456"})
        return web.Response(text=_fixture("reel"), content_type="text/html")

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield port, seen
    await runner.cleanup()


@pytest.fixture
def point_at(monkeypatch):
    """URLهای اینستاگرام را به سرورِ محلی بچرخان و وتوی SSRF را برای لوپ‌بک بردار."""
    def _apply(port: int, mode: str = "ok"):
        monkeypatch.setattr(D, "_addr_is_internal", lambda addr: False)
        monkeypatch.setattr(IA, "_EMBED",
                            f"http://127.0.0.1:{port}/embed/{{sc}}?mode={mode}")
        monkeypatch.setattr(IA, "_OEMBED",
                            f"http://127.0.0.1:{port}/oembed/{{sc}}?mode=oembed")
    return _apply


URL = "https://www.instagram.com/p/Db8fsxMsATy/"


async def test_a_live_fetch_resolves_through_the_real_session(server, point_at):
    """مسیرِ کامل، از جمله `_new_session`/`_direct_connector` — نه سشنِ تزریقی."""
    port, _seen = server
    point_at(port)
    out = await IA.resolve_detailed(URL)
    assert out.verdict == IA.V_OK
    assert out.result is not None and out.result.content == IA.CONTENT_SINGLE_VIDEO
    assert out.result.via == "embed" and out.result.shortcode == "Db8fsxMsATy"
    assert await IA.resolve(URL) is not None


@pytest.mark.parametrize("mode,verdict,reason", [
    # دو علتِ متفاوت با یک حکم: «صفحه را نفهمیدیم» در برابرِ «صفحه را فهمیدیم
    # ولی رسانه‌ای نداشت». تله‌متریِ فاز ۲ باید این دو را جدا ببیند.
    ("junk", IA.V_UNSUPPORTED, IA.R_PARSE_FAILED),
    ("empty", IA.V_UNSUPPORTED, IA.R_NO_MEDIA),
    ("403", IA.V_BLOCKED, IA.R_LOGIN_REQUIRED),
    ("404", IA.V_UNSUPPORTED, IA.R_HTTP_ERROR),
    ("boom", IA.V_NETWORK, IA.R_HTTP_ERROR),
])
async def test_verdicts_separate_failure_from_a_broken_network(server, point_at, mode,
                                                               verdict, reason):
    """تفکیکی که فاز ۲ رویش تصمیم می‌گیرد: یک ۵xx یا قطعیِ شبکه نباید به
    `mark_fail` روی یک اکانتِ سالم تبدیل شود."""
    port, _seen = server
    point_at(port, mode)
    out = await IA.resolve_detailed(URL)
    assert out.result is None
    assert out.verdict == verdict
    assert next(r for r in out.rungs if r.rung == "embed").reason == reason


async def test_a_dead_endpoint_is_a_network_verdict(monkeypatch):
    monkeypatch.setattr(D, "_addr_is_internal", lambda addr: False)
    monkeypatch.setattr(IA, "_EMBED", "http://127.0.0.1:1/embed/{sc}")   # هیچ‌کس آن‌جا نیست
    out = await IA.resolve_detailed(URL)
    assert out.verdict == IA.V_NETWORK
    assert next(r for r in out.rungs if r.rung == "embed").status is None


async def test_total_failure_logs_exactly_one_warning_naming_every_rung(server, point_at, caplog):
    """سکوت این‌جا یعنی گذار به کوکی نامرئی شود — همان چیزی که یک پارسرِ مردهٔ
    اسپاتیفای را هفته‌ها پنهان کرد (§۷)."""
    port, _seen = server
    point_at(port, "junk")
    with caplog.at_level(logging.DEBUG, logger="telabzar.ig_anon"):
        await IA.resolve_detailed(URL)
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    msg = warnings[0].getMessage()
    assert "embed=" in msg and "oembed=" in msg and "verdict=" in msg


async def test_success_is_quiet(server, point_at, caplog):
    """کنترلِ معکوس: مسیرِ سالم نباید WARNING بدهد، وگرنه هشدار بی‌معنا می‌شود."""
    port, _seen = server
    point_at(port)
    with caplog.at_level(logging.DEBUG, logger="telabzar.ig_anon"):
        await IA.resolve_detailed(URL)
    assert [r for r in caplog.records if r.levelname == "WARNING"] == []


async def test_no_cookie_is_ever_sent(server, point_at):
    """قاعدهٔ بنیادیِ این ماژول. `opts` عمداً همان شکلی است که
    `tasks_download._opts()` می‌سازد — با کوکی داخلش."""
    port, seen = server
    point_at(port)
    opts = {"cookies": "/cookies/instagram_1.txt", "proxy": "", "user_agent": None}
    out = await IA.resolve_detailed(URL, opts, with_oembed=True)
    assert out.verdict == IA.V_OK
    assert len(seen) == 2, "هر دو رده باید واقعاً درخواست زده باشند"
    for req in seen:
        lower = {k.lower(): v for k, v in req["headers"].items()}
        assert "cookie" not in lower, req["headers"]
        blob = json.dumps(req)
        assert "instagram_1.txt" not in blob and "/cookies/" not in blob


async def test_oembed_is_skipped_by_default_and_never_gates(server, point_at):
    """رده A پیش‌فرض خاموش است (یک رفت‌وبرگشتِ اضافه روی هر دانلود)، و حتی وقتی
    روشن است نباید بتواند نردبون را بشکند."""
    port, seen = server
    point_at(port)
    out = await IA.resolve_detailed(URL)
    assert len(seen) == 1 and out.result.media_id is None
    assert next(r for r in out.rungs if r.rung == "oembed").reason == IA.R_SKIPPED

    seen.clear()
    out = await IA.resolve_detailed(URL, with_oembed=True)
    assert out.result.media_id == "123_456" and len(seen) == 2


async def test_a_url_without_a_shortcode_never_touches_the_network(server, point_at):
    port, seen = server
    point_at(port)
    out = await IA.resolve_detailed("https://www.instagram.com/someuser/")
    assert out.result is None and out.verdict == IA.V_UNSUPPORTED
    assert seen == [], "پروفایل حالتِ ناشناس نیست — نباید درخواستی برود"
    assert next(r for r in out.rungs if r.rung == "embed").reason == IA.R_BAD_URL


async def test_an_injected_session_is_used_and_not_closed(server, point_at):
    """تزریقِ سشن مسیرِ تست را ممکن می‌کند؛ بستنِ سشنِ **فراخوان** باگ می‌بود."""
    import aiohttp
    port, _seen = server
    point_at(port)
    async with aiohttp.ClientSession() as s:
        out = await IA.resolve_detailed(URL, session=s)
        assert out.verdict == IA.V_OK
        assert not s.closed
