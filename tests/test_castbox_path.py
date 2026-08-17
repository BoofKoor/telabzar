"""مسیرِ کست‌باکس: بازنویسیِ لینکِ کوتاه، گاردِ SSRF، کلیدِ کش، و ردِ کانال.

**مسئله.** کست‌باکس دو فرمِ کوتاه دارد که دکمهٔ Shareِ اپ تولیدشان می‌کند —
`/vb/<eid>` برای اپیزود و `/va/<cid>` برای کانال — و yt-dlp روی **هر دو** یک‌جا
می‌ایستد: صفحهٔ واسطهٔ `d.castbox.fm/dynamic-link/redirect?link=…` که یک صفحهٔ
JSِ بی‌محتواست. اندازه‌گیریِ اپراتور روی تولید:

    /ep/798014224 → extractor=html5، عنوانِ فارسیِ درست، دانلودِ ۴٫۱۶MB
    /vb/798014224 → ERROR: Unsupported URL: d.castbox.fm/dynamic-link/redirect?…

پس فرمِ کامل از قبل کار می‌کند و فقط فرمِ کوتاه — یعنی دقیقاً چیزی که کاربر
می‌فرستد — می‌شکند. رفع: بازنویسیِ **رشته‌ای و بی‌شبکهٔ** هر فرمِ اپیزود به
`/ep/<eid>` که اندازه‌گیری‌شده کار می‌کند.

**چرا این فایل بیشتر دربارهٔ SSRF است تا دربارهٔ کست‌باکس.** بازکردنِ پارامترِ
`link=` یعنی یک URL از داخلِ کوئری را می‌خوانیم، و آن مقدار **کاملاً
کاربر-ساخته** است: هاستِ `d.castbox.fm` واقعاً castbox.fm است، پس کاربر
می‌تواند خودش `…/redirect?link=http://169.254.169.254/` را بسازد و درِ ورودی
— که فقط هاستِ **بیرونی** را می‌سنجد — آن را عبور می‌دهد (اندازه‌گیری‌شده).
گیت‌کردن به دامنهٔ castbox.fm جوابش **نیست**.

**دو دفاعِ مستقل، و هرکدام تستِ خودش را دارد چون کارِ متفاوتی می‌کنند:**

  ۱) `castbox_target` URL را **بازمی‌سازد** (`https://castbox.fm/ep/<digits>`)
     و هرگز مقداری را عبور نمی‌دهد. این دفاعِ اولیه است: یک `link=`ِ خصمانه
     اصلاً با الگوهای اپیزود/کانال جور نمی‌شود و همان‌جا `None` می‌گیرد.
  ۲) `resolve_castbox` خروجی را از `is_safe_url_resolved` رد می‌کند. تنها
     چیزی که (۱) نمی‌گیردش این است: اگر **خودِ `castbox.fm`** به آدرسِ داخلی
     resolve شود. yt-dlp زیرفرایند است و رزولورِ وتوکننده نمی‌گیرد، پس این
     تنها لایه‌ای است که آن حالت را می‌بیند.

اگر این دو را یک تست می‌سنجید، سابوتاژِ گارد «نگرفت» گزارش می‌شد و شبیهِ
ادعای ضعیف به‌نظر می‌رسید — در حالی که واقعاً دفاعِ **دیگری** کار را کرده بود.
پس عمداً جدا سنجیده می‌شوند.

**تلهٔ دو-شناسه‌ای.** فرمِ کانونیکِ واقعی که yt-dlp برمی‌گرداند
`…-id5174947-id798014224` است — **اول شناسهٔ کانال، بعد اپیزود**. الگوی
طبیعیِ `id(\\d+)` شناسهٔ کانال را برمی‌دارد و بی‌صدا فایلِ غلط را کش می‌کند.
`test_the_naive_id_pattern_would_take_the_channel_id` کنترلِ معکوسِ همین است.

**و یک قیدِ هارنس که این فایل را از یک false fail نجات داد.** `_picked` ctx را
دقیقاً مثلِ `YoutubeDL._select_formats` می‌سازد. نسخهٔ اولِ این سنجش
`incomplete_formats` را `False` هاردکد کرده بود و نتیجه گرفت `bv*+ba/b` روی
منبعِ فقط‌صوتی «هیچ فرمتی» برنمی‌دارد — یعنی یک مشکلِ **خیالی** که نزدیک بود
واردِ نقشه شود. yt-dlp خودش آن فلگ را از فرمت‌ها می‌سازد و برای منبعِ
فقط‌صوتی `True` است، و شاخهٔ `format_fallback` بهترین صوت را برمی‌دارد.
`test_the_harness_computes_the_flag_like_yt_dlp_does` همین را قفل می‌کند.
"""
from __future__ import annotations

import socket
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from yt_dlp import YoutubeDL

from app import dl_cache
from app import downloader as D
from app.models import Base
from app.routers import download as R

# ── دادهٔ واقعیِ اندازه‌گیری‌شده روی تولید ───────────────────────────
EID = "798014224"
CID = "5174947"
# `webpage_url`ی که yt-dlp برای `/ep/798014224` برگرداند — **دو** شناسه دارد.
REAL_WEBPAGE_URL = (
    "https://castbox.fm/episode/"
    "%DA%86%D8%B1%D8%A7-%D9%88-%DA%86%D8%B7%D9%88%D8%B1-%D8%A8%D8%A7%DB%8C%D8%AF"
    f"-id{CID}-id{EID}")
VB = f"https://castbox.fm/vb/{EID}"          # دکمهٔ Shareِ اپ — فرمی که می‌شکست
EP = f"https://castbox.fm/ep/{EID}"          # فرمی که اندازه‌گیری‌شده کار می‌کند
VA = f"https://castbox.fm/va/{CID}"          # کانال، فرمِ کوتاه
CH = f"https://castbox.fm/ch/{CID}"
CH_SLUG = f"https://castbox.fm/channel/%DA%A9%D8%A7%D9%86%D8%A7%D9%84-id{CID}"
INTERSTITIAL = ("https://d.castbox.fm/dynamic-link/redirect?"
                f"link=https%3A%2F%2Fcastbox.fm%2Fep%2F{EID}&v=v1&appid=castbox")

# payloadهایی که کاربر می‌تواند **مستقیم** بفرستد؛ هاستشان واقعاً castbox.fm است.
SSRF_PAYLOADS = [
    pytest.param("http%3A%2F%2F169.254.169.254%2Flatest%2Fmeta-data%2F", id="cloud-metadata"),
    pytest.param("http%3A%2F%2F127.0.0.1%3A8080%2Fnode%2Fpeers", id="loopback-panel"),
    pytest.param("http%3A%2F%2F10.51.0.1%3A8081%2F", id="wireguard-bot-api"),
    pytest.param("http%3A%2F%2F2130706433%2F", id="numeric-loopback"),
]


def _wrapped(inner_encoded: str) -> str:
    return f"https://d.castbox.fm/dynamic-link/redirect?link={inner_encoded}&v=v1"


# ── جعلِ DNS (تنها چیزی که این‌جا جعل می‌شود) ────────────────────────
_real_getaddrinfo = socket.getaddrinfo


def _fake_dns(mapping: dict[str, str]):
    """رکوردِ DNS تنها چیزی است که در تست ساختنی نیست — همان قاعدهٔ `test_ssrf`.

    بدونِ این، `is_safe_url_resolved` روی رانر به DNSِ واقعی می‌خورد و تست‌های
    ردِ SSRF ممکن بود به **دلیلِ غلط** سبز شوند (شکستِ DNS هم رد است).
    """
    def _f(host, *a, **kw):
        if kw.get("flags", 0) & socket.AI_NUMERICHOST:
            return _real_getaddrinfo(host, *a, **kw)
        if host not in mapping:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        addr = mapping[host]
        fam = socket.AF_INET6 if ":" in addr else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, "", (addr, 0))]
    return _f


@pytest.fixture(autouse=True)
def _clear_dns_cache():
    getattr(D, "_dns_cache", {}).clear()
    yield
    getattr(D, "_dns_cache", {}).clear()


@pytest.fixture()
def public_dns(monkeypatch):
    """castbox.fm سالم است — حالتِ عادی."""
    monkeypatch.setattr(socket, "getaddrinfo",
                        _fake_dns({"castbox.fm": "93.184.216.34",
                                   "d.castbox.fm": "93.184.216.34"}))


# ── تریپ‌وایر: آیا کاری به موتور رسید؟ ───────────────────────────────
class _Pool:
    """جای `ArqRedis`. تنها ادعای این فایل «جابی ساخته نشد» است، پس
    `enqueue_job` ضبط می‌شود و بقیهٔ متدها بی‌اثرند."""

    def __init__(self) -> None:
        self.jobs: list[tuple] = []
        self.kv: dict = {}

    async def enqueue_job(self, *a, **kw):
        self.jobs.append((a, kw))

    async def set(self, k, v, **kw):
        self.kv[k] = v

    async def get(self, k):
        return self.kv.get(k)

    async def exists(self, k):
        return 1 if k in self.kv else 0

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]

    async def expire(self, k, s):
        return True

    async def smembers(self, k):
        return set()

    async def keys(self, p="*"):
        return []


class _Bot(Bot):
    """`Bot`ِ واقعیِ aiogram با ترانسپورتِ ضبط‌کننده.

    عمداً `Bot` زیرکلاس می‌شود و متدها بازتعریف **نمی‌شوند**: `Message.reply`
    خودش مدلِ `SendMessage` را می‌سازد و pydantic اعتبارسنجی می‌کند، پس یک
    فراخوانیِ بدشکل این‌جا هم مثلِ تولید می‌ترکد (درسِ `tests/aiogram_double.py`).
    """

    def __init__(self) -> None:
        super().__init__(token="0:test")
        self.sent: list = []

    async def __call__(self, method, request_timeout=None):
        self.sent.append(method)
        # `on_link` روی نتیجهٔ `reply` مقدارِ `.message_id` می‌خواند، پس داکل باید
        # قراردادِ **بازگشتِ** واقعی را هم مدل کند نه فقط پذیرشِ آرگومان‌ها —
        # وگرنه مسیرِ سالم با `AttributeError` می‌افتد و شبیهِ باگِ کد به‌نظر
        # می‌رسد. همان درسِ `tests/aiogram_double.py`، این‌بار سمتِ خروجی.
        return Message(message_id=len(self.sent) + 100,
                       date=datetime.now(timezone.utc),
                       chat=Chat(id=4242, type="private"),
                       text=getattr(method, "text", None)).as_(self)

    @property
    def texts(self) -> list[str]:
        return [getattr(m, "text", "") or "" for m in self.sent]


def _msg(text: str, bot: _Bot) -> Message:
    return Message(message_id=1, date=datetime.now(timezone.utc),
                   chat=Chat(id=4242, type="private"), text=text).as_(bot)


async def _run(url: str, db=None) -> tuple[_Bot, _Pool]:
    """`on_link`ِ **واقعی** را با یک لینک اجرا می‌کند."""
    bot, pool = _Bot(), _Pool()
    await R.on_link(_msg(url, bot), lang="fa", arq_pool=pool, user=None, session=db)
    return bot, pool


@pytest.fixture()
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


# ── ۱) قلبِ کار: payloadهای SSRF به موتور نمی‌رسند ────────────────────
# سه تست، عمداً در **سه سطح**. اجرای دفترچهٔ سابوتاژ نشان داد چرا لازم است:
# وقتی دفاعِ اول را برداشتم، تستِ انتها‌به‌انتها **سبز ماند** چون دفاعِ دوم
# گرفتش — یعنی آن تست به‌تنهایی نمی‌تواند بگوید کدام لایه کار کرده. همان
# «دو سبزِ تفکیک‌ناپذیر» که §۶ دربارهٔ سابوتاژ می‌گوید.
@pytest.mark.parametrize("payload", SSRF_PAYLOADS)
def test_the_rebuild_alone_rejects_the_payloads(payload):
    """**دفاعِ اول، ایزوله** — بدونِ هیچ گاردی.

    `castbox_target` خالص است و URL را بازمی‌سازد، پس یک `link=`ِ خصمانه اصلاً
    با الگوی اپیزود/کانال جور نمی‌شود. سابوتاژ: عبوردادنِ مقدارِ باز‌شده
    به‌جای بازسازی، **همین** تست را می‌اندازد.
    """
    assert D.castbox_target(_wrapped(payload)) is None, (
        "مقدارِ `link=` عبور داده شد به‌جای اینکه URL بازسازی شود — دفاعِ اول "
        "از بین رفته و فقط گارد مانده.")


@pytest.mark.parametrize("payload", SSRF_PAYLOADS)
async def test_the_ssrf_payloads_never_reach_the_engine(payload, public_dns):
    """ادعای **انتها‌به‌انتها**: با هر دو لایه، هیچ جابی ساخته نمی‌شود.

    عمداً نمی‌گوید کدام لایه گرفت — آن کارِ دو تستِ ایزولهٔ کناری است. این‌جا
    فقط چیزی سنجیده می‌شود که کاربر می‌بیند: نه جابی، نه دانلودی.
    """
    bot, pool = await _run(_wrapped(payload))
    assert pool.jobs == [], (
        "یک URLِ داخلی از درِ ورودی رد شد و جابِ دانلود ساخت — یعنی به yt-dlp "
        "می‌رسید، که زیرفرایند است و هیچ گاردِ SSRFی ندارد.")
    assert any("پشتیبانی نمی‌شود" in x for x in bot.texts), \
        f"انتظارِ dl_bad_link، دیده شد: {bot.texts}"


async def test_the_payload_is_not_merely_unresolvable(public_dns):
    """کنترلِ ضدِ vacuous برای تستِ بالا.

    اگر آن payloadها به‌دلیلِ **شکستِ DNS** رد می‌شدند، تستِ بالا به دلیلِ غلط
    سبز بود. این‌جا ثابت می‌شود مسیرِ سالم با همین DNS **کار می‌کند**، پس ردِ
    بالا واقعاً دربارهٔ محتوای `link=` است نه دربارهٔ نبودِ رکورد.
    """
    assert await D.resolve_castbox(EP) == EP


# ── ۲) دفاعِ دوم: گارد، و کارِ متفاوتی که می‌کند ──────────────────────
async def test_the_guard_rejects_a_castbox_that_resolves_internal(monkeypatch):
    """تنها حالتی که بازسازی نمی‌گیردش: خودِ `castbox.fm` داخلی شود.

    این کارِ **اختصاصیِ** `is_safe_url_resolved` در `resolve_castbox` است.
    سابوتاژ: برداشتنِ آن گارد این تست را می‌اندازد و هیچ‌کدام از بالایی‌ها را نه.
    """
    monkeypatch.setattr(socket, "getaddrinfo",
                        _fake_dns({"castbox.fm": "169.254.169.254"}))
    assert await D.resolve_castbox(EP) is None, (
        "castbox.fm به آدرسِ داخلی resolve شد ولی گارد ردش نکرد — yt-dlp "
        "زیرفرایند است و این تنها لایه‌ای است که این حالت را می‌بیند.")


async def test_the_pattern_path_goes_through_the_same_guard(monkeypatch):
    """مسیرِ **الگویی** (`/vb/`) هم از همان گارد رد می‌شود، نه فقط مسیرِ `link=`.

    قید: یک نقطهٔ خروج با یک قرارداد. اگر روزی کسی برای مسیرِ الگویی میان‌بر
    بزند، این تست می‌افتد.
    """
    monkeypatch.setattr(socket, "getaddrinfo",
                        _fake_dns({"castbox.fm": "10.51.0.1"}))
    assert await D.resolve_castbox(VB) is None
    bot, pool = await _run(VB)
    assert pool.jobs == [], "مسیرِ الگویی گارد را دور زد."


async def test_the_unwrap_depth_is_one(public_dns):
    """`link=`ی که خودش `link=` دارد بازگشتی باز نمی‌شود."""
    from urllib.parse import quote
    nested = _wrapped(quote(_wrapped(quote(EP, safe="")), safe=""))
    assert D.castbox_target(nested) is None
    assert await D.resolve_castbox(nested) is None


# ── ۳) کلیدِ کش: شش شکل، دو کلید ──────────────────────────────────────
@pytest.mark.parametrize("url", [
    pytest.param(VB, id="vb-short"),
    pytest.param(EP, id="ep-full"),
    pytest.param(REAL_WEBPAGE_URL, id="episode-persian-slug"),
    pytest.param(f"https://www.castbox.fm/ep/{EID}?utm_source=x", id="www-plus-utm"),
    pytest.param(INTERSTITIAL, id="interstitial"),
])
def test_every_episode_form_reaches_one_cache_key(url):
    assert dl_cache._cache_url(url) == f"cb:ep:{EID}"


@pytest.mark.parametrize("url", [
    pytest.param(VA, id="va-short"),
    pytest.param(CH, id="ch-full"),
    pytest.param(CH_SLUG, id="channel-persian-slug"),
])
def test_every_channel_form_reaches_one_cache_key(url):
    assert dl_cache._cache_url(url) == f"cb:ch:{CID}"


def test_the_episode_and_channel_keyspaces_stay_separate():
    """`ep` و `ch` دو فضای شناسهٔ متفاوت‌اند — همان استدلالِ `/sets/`ِ ساندکلاود."""
    assert dl_cache._cache_url(EP) != dl_cache._cache_url(CH)


def test_the_persian_slug_does_not_enter_the_key():
    """همان اپیزود با اسلاگِ دیگر باید همان کلید را بگیرد."""
    other_slug = f"https://castbox.fm/episode/%D8%AA%D8%B3%D8%AA-id{CID}-id{EID}"
    assert dl_cache._cache_url(other_slug) == dl_cache._cache_url(REAL_WEBPAGE_URL)


def test_the_naive_id_pattern_would_take_the_channel_id():
    """**کنترلِ معکوسِ تلهٔ دو-شناسه‌ای.**

    بدونِ این تست، یک الگوی ساده‌لوحانه بی‌صدا سبز می‌ماند: هر دو شناسه عددند و
    هر دو در همان URL، پس خروجی «معقول» به‌نظر می‌رسد و فقط با دانلودِ فایلِ
    غلط معلوم می‌شود. هم‌خانوادهٔ تلهٔ `acodec`ِ ساندکلاود و `srcset`ِ اینستاگرام.
    """
    import re
    naive = re.search(r"id(\d+)", REAL_WEBPAGE_URL).group(1)
    assert naive == CID, "فرضِ این تست عوض شده — فرمِ کانونیک دیگر دو شناسه ندارد."
    assert D.castbox_ids(REAL_WEBPAGE_URL) == ("ep", EID), (
        f"الگو شناسهٔ کانال ({CID}) را به‌جای اپیزود ({EID}) برداشت.")


# ── ۴) کانال: پیامِ روشن، نه سکوت و نه stderrِ خام ────────────────────
@pytest.mark.parametrize("url", [
    pytest.param(VA, id="va-short"),
    pytest.param(CH, id="ch-full"),
    pytest.param(CH_SLUG, id="channel-persian-slug"),
])
async def test_a_channel_link_gets_a_clear_message(url, public_dns):
    """اندازه‌گیری‌شده: yt-dlp روی صفحهٔ واسطه می‌ایستد و به صفحهٔ کانال هم
    نمی‌رسد، و آن صفحه تگِ `<audio>` ندارد — پس چیزی برای برداشتن نیست."""
    bot, pool = await _run(url)
    assert pool.jobs == [], "لینکِ کانال جابِ دانلود ساخت."
    assert bot.texts, "کاربر هیچ جوابی نگرفت — سکوت بدترین حالت است."
    assert "کانال" in bot.texts[0], f"پیامِ نامربوط: {bot.texts}"
    assert "Unsupported URL" not in bot.texts[0]


# ── ۵) مسیرِ سالم: بازنویسی واقعاً اتفاق می‌افتد ──────────────────────
async def test_a_short_episode_link_is_enqueued_rewritten(public_dns, db):
    """کنترلِ مثبت — بدونِ این، همهٔ ادعاهای «رد شد» می‌توانند از یک رفعِ
    بیش‌ازحد سخت‌گیر بیایند."""
    bot, pool = await _run(VB, db=db)
    assert len(pool.jobs) == 1, f"انتظارِ یک جاب، دیده شد: {pool.jobs}"
    payload = pool.jobs[0][0][1]
    assert payload["url"] == EP, (
        f"URLِ بازنویسی‌نشده به ورکر رفت: {payload['url']} — yt-dlp روی این فرم "
        "می‌شکند.")
    assert payload["platform"] == "castbox"
    assert payload["selector"] == "audio", "پلتفرمِ صوتی باید صوتِ تمیز بگیرد."


# ── ۶) کنترل: بقیهٔ پلتفرم‌ها دست‌نخورده ──────────────────────────────
@pytest.mark.parametrize("url", [
    pytest.param("https://youtu.be/dQw4w9WgXcQ", id="youtube"),
    pytest.param("https://soundcloud.com/a/b", id="soundcloud"),
    pytest.param("https://example.com/file.mp3", id="unknown-host"),
])
def test_non_castbox_links_are_untouched(url):
    assert D.platform_of(url) != "castbox"
    assert D.castbox_target(url) is None
    assert not dl_cache._cache_url(url).startswith("cb:")


# ── ۷) انتخابگر: با ctxِ درست، نه هاردکد ──────────────────────────────
# شکلی که اکسترکتورِ html5 برای `<audio><source>` می‌سازد — از سورسِ خودِ
# yt-dlp: `vcodec='none'` وقتی media_type == 'audio'، و `acodec` ست نمی‌شود.
HTML5_MP3 = {"format_id": "0", "url": "https://sphinx.acast.com/x.mp3",
             "ext": "mp3", "vcodec": "none"}
VIDEO_FMT = {"format_id": "v", "url": "https://cdn/v.mp4", "ext": "mp4",
             "vcodec": "h264", "acodec": "aac", "height": 720}


def _ctx(formats: list[dict]) -> dict:
    """دقیقاً همان ctxی که `YoutubeDL._select_formats` می‌سازد."""
    return {"formats": formats,
            "has_merged_format": any(
                "none" not in (f.get("acodec"), f.get("vcodec")) for f in formats),
            "incomplete_formats": (all(f.get("vcodec") == "none" for f in formats)
                                   or all(f.get("acodec") == "none" for f in formats))}


def _picked(expr: str, formats: list[dict]) -> str | None:
    got = list(YoutubeDL({"format": expr, "quiet": True})
               .build_format_selector(expr)(_ctx(formats)))
    return got[0]["format_id"] if got else None


def test_the_harness_computes_the_flag_like_yt_dlp_does():
    """**پیش‌شرطِ اعتبارِ تستِ بعدی.**

    نسخهٔ اولِ این سنجش `incomplete_formats` را `False` هاردکد کرد و نتیجه گرفت
    انتخابگرِ تولید روی کست‌باکس هیچ فرمتی برنمی‌دارد — یک مشکلِ خیالی. yt-dlp
    آن فلگ را خودش از فرمت‌ها می‌سازد.
    """
    assert _ctx([HTML5_MP3])["incomplete_formats"] is True
    assert _ctx([VIDEO_FMT])["incomplete_formats"] is False


def test_the_production_selector_picks_the_audio_format():
    """انتخابگرِ تولید برای کست‌باکس (`AUDIO_PLATFORMS` → `audio`) و همچنین
    انتخابگرِ قبلی (`best`) هر دو همان تک‌فرمت را برمی‌دارند.

    یعنی افزودنِ کست‌باکس به `AUDIO_PLATFORMS` انتخابِ فرمت را عوض **نمی‌کند** —
    سودش UXِ قطعی و برچسب/متریک است، نه انتخابگر.
    """
    audio = D._selector_to_format("audio", "castbox")
    best = D._selector_to_format("best", "castbox")
    assert _picked(audio, [HTML5_MP3]) == "0"
    assert _picked(best, [HTML5_MP3]) == "0"
    # کنترلِ منفی: هارنس زنده است و روی ویدیو رفتارِ متفاوت دارد
    assert _picked(best, [VIDEO_FMT]) == "v"
