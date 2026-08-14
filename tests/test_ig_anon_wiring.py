"""فاز ۲ — اتصالِ مسیرِ ناشناسِ اینستاگرام به `run_download`.

فاز ۱ ماژول را ساخت و ثابت کرد پارس می‌کند (`tests/test_instagram_anon.py`، روی
فیکسچرهای **ضبط‌شدهٔ واقعی**). این فایل چیزِ دیگری را می‌سنجد: **سیم‌کشی** —
اینکه پاسِ ناشناس واقعاً پیش از هر انتخابِ کوکی اجرا می‌شود، شکستش دقیقاً به
مسیرِ امروز می‌افتد، و هیچ فایلی از خودش جا نمی‌گذارد.

سه انتخابِ هارنس که ارزشِ توضیح دارند:

**۱) صفحهٔ embed همان فیکسچرِ واقعیِ فاز ۱ است، فقط هاستِ CDNش چرخانده.** ساختنِ
یک صفحهٔ ساختگی یعنی این تست‌ها دربارهٔ صفحه‌ای باشند که هیچ‌وقت وجود نداشته؛
`_page()` فقط `https://scontent-ams2-1.cdninstagram.com` را به سرورِ محلی
برمی‌گرداند و ساختارِ JSON، فلگ‌های `is_video`، تعداد و **ترتیبِ** آیتم‌ها همان
چیزی می‌ماند که اینستاگرام واقعاً داد.

**۲) DNS جعل می‌شود، نه کد.** تنها چیزی که در این ریپو جعلش مجاز است رکوردِ DNS
است (§۶). پس `scontent-ams2-1.cdninstagram.com` به ۱۲۷٫۰٫۰٫۱ حل می‌شود و
`download_direct`ِ **واقعی** با کانکتور و `_follow`ِ واقعیِ خودش بایت‌ها را
می‌کشد. اگر به‌جایش `download_direct` را ماک می‌کردیم، دقیقاً همان چیزی را که
تصمیمِ «الف» ادعا می‌کند (ارثِ گاردهای SSRF و سقفِ دولایه) نسنجیده می‌گذاشتیم.

**۳) لایهٔ تحویل ضبط می‌شود، نه اجرا.** `_spawn`/`_deliver_rich_post`/
`_deliver_album` مرزِ بینِ «فایل‌ها را بساز» (چیزی که عوض شد) و «به تلگرام
بفرست» (دست‌نخورده) هستند. اجرای واقعی‌شان Postgres و ffprobe می‌خواهد — نویزی
که هیچ ادعایی از این فایل به آن بند نیست. **کدام شاخه گرفت و با چه آرگومانی**
دقیقاً همان چیزی است که تصمیمِ «ب» ادعا می‌کند، و همان assert می‌شود.
"""
from __future__ import annotations

import ast
import asyncio
import collections
import os
import re
import socket
import stat
from pathlib import Path

import pytest
from aiohttp import web

from tests.aiogram_double import ValidatingBot

from app import cookies as ck
from app import downloader as D
from app import instagram_anon as IGA
from app import tasks_download as TD

FIX = Path(__file__).parent / "fixtures"
CDN = "scontent-ams2-1.cdninstagram.com"

REEL = "https://www.instagram.com/reel/Db8fsxMsATy/"
CAROUSEL = "https://www.instagram.com/p/DbkmloxCI5b/"
PHOTO = "https://www.instagram.com/p/Db8kJCZu-go/"
STORY = "https://www.instagram.com/stories/someuser/3512345678/"
PROFILE = "https://www.instagram.com/someuser/"

_NETSCAPE = ("# Netscape HTTP Cookie File\n"
             ".instagram.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\tv\n")


# اسکیم+هاست در فیکسچرِ واقعی **چند عمق از escape** دارد: تگِ `<img srcset>` آن را
# ساده می‌نویسد (`https://…`) ولی `contextJSON` یک رشتهٔ JSON **داخلِ** یک JSONِ
# دیگر است، پس همان URL آن‌جا `https:\\\/\\\/…` است. یک `str.replace`ِ ساده فقط
# فرمِ اول را می‌گیرد و آن‌وقت رسانه‌ها به CDNِ واقعی روی پورتِ ۴۴۳ می‌روند — که
# دقیقاً همان چیزی بود که نسخهٔ اولِ این هارنس کرد و تست‌ها با
# `Cannot connect to host …:443` افتادند.
_SCHEME_RE = re.compile(r"https(:[\\/]+)" + re.escape(CDN))


def _page(name: str, port: int) -> str:
    """فیکسچرِ واقعیِ فاز ۱ با هاستِ CDN چرخانده به سرورِ محلی.

    `http` (نه `https`) چون TLSِ محلی ارزشی به این تست‌ها اضافه نمی‌کند، و پورت
    داخلِ خودِ URL می‌آید — `_is_media_url` از `p.hostname` استفاده می‌کند که پورت
    را کنار می‌گذارد، پس هر دو چکِ ماژول (پسوندِ هاست و اسکیم) واقعاً اجرا می‌شوند.
    """
    raw = (FIX / f"ig_embed_{name}.html").read_text(encoding="utf-8")
    return _SCHEME_RE.sub(lambda m: f"http{m.group(1)}{CDN}:{port}", raw)


class FakeBot(ValidatingBot):
    """امضاها از خودِ aiogram می‌آیند (درسِ `FakeBot` در §۶)."""

    def __init__(self) -> None:
        self.edits: list[str] = []
        self.messages: list[str] = []
        self.deleted: list[int] = []

    def _on(self, name, payload):
        if name == "edit_message_text":
            self.edits.append(payload["text"])
        elif name == "edit_message_caption":
            self.edits.append(payload.get("caption"))
        elif name == "send_message":
            self.messages.append(payload["text"])
        elif name == "delete_message":
            self.deleted.append(payload["message_id"])
        return True


# ── هارنس ────────────────────────────────────────────────────────
@pytest.fixture
async def ig(monkeypatch):
    """سرورِ **واقعیِ** aiohttp که هم صفحهٔ embed را می‌دهد هم بایت‌های رسانه.

    بدنهٔ هر فایل **مسیرِ خودش** است، پس ترتیبِ کاروسل با خواندنِ فایل‌ها قابلِ
    اثبات است بدونِ اینکه به نامِ فایل تکیه کنیم.
    """
    st = {"mode": "reel", "port": 0, "fail_from": None, "pad": 0, "hang": False}
    seen: list[str] = []

    async def handler(req: web.Request):
        seen.append(req.path)
        if req.path.startswith("/embed/"):
            mode = st["mode"]
            if mode == "403":
                return web.Response(status=403, text='{"message":"login_required"}')
            if mode == "500":
                return web.Response(status=500, text="kaput")
            if mode == "junk":       # نه بلاکِ init، نه تگِ عکس → unsupported
                return web.Response(text="<html>nothing here</html>",
                                    content_type="text/html")
            return web.Response(text=_page(mode, st["port"]), content_type="text/html")

        media_no = sum(1 for p in seen if not p.startswith("/embed/")) - 1
        if st["fail_from"] is not None and media_no >= st["fail_from"]:
            return web.Response(status=500, text="cdn down")
        if st["hang"]:
            await asyncio.sleep(30)
        body = req.path.encode() + b"\0" * st["pad"]
        ctype = "video/mp4" if req.path.endswith(".mp4") else "image/jpeg"
        return web.Response(body=body, content_type=ctype)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    # `shutdown_timeout` کوتاه: تستِ بودجهٔ زمانی عمداً یک هندلرِ **تمام‌نشدنی**
    # دارد (وگرنه «ایستاد» می‌توانست یعنی «خودش تمام شد» — تلهٔ ثبت‌شده در §۶)، و
    # بدونِ این، teardown برای همان ۳۰ ثانیه منتظر می‌ماند.
    site = web.TCPSite(runner, "127.0.0.1", 0, shutdown_timeout=0.1)
    await site.start()
    st["port"] = site._server.sockets[0].getsockname()[1]

    # DNS جعلی: تنها چیزی که §۶ جعلش را مجاز می‌داند. رزولورِ واقعیِ
    # `_safe_resolver` روی همین رکورد می‌نشیند، پس مسیرِ کد دست‌نخورده می‌ماند.
    import aiohttp
    real_resolve = aiohttp.DefaultResolver.resolve

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host.endswith((".cdninstagram.com", ".fbcdn.net")):
            return [{"hostname": host, "host": "127.0.0.1", "port": port,
                     "family": family, "proto": 0, "flags": 0}]
        return await real_resolve(self, host, port, family)

    monkeypatch.setattr(aiohttp.DefaultResolver, "resolve", resolve)
    monkeypatch.setattr(D, "_addr_is_internal", lambda addr: False)
    monkeypatch.setattr(IGA, "_EMBED", f"http://127.0.0.1:{st['port']}/embed/{{sc}}")

    st["seen"] = seen
    yield st
    await runner.cleanup()


@pytest.fixture
def spy(monkeypatch):
    """تریپ‌وایر روی هر تابعی از استخر که «اکانت را خرج می‌کند»."""
    calls: collections.Counter = collections.Counter()

    def _wrap(name: str):
        real = getattr(ck, name)

        async def _f(*a, **kw):
            calls[name] += 1
            return await real(*a, **kw)

        monkeypatch.setattr(ck, name, _f)

    for n in ("pick", "materialize", "note_use", "mark_ok", "mark_fail", "note_spend"):
        _wrap(n)
    return calls


@pytest.fixture
def delivered(monkeypatch):
    """مرزِ تحویل: چه شاخه‌ای گرفت و با چه آرگومانی."""
    out: list[tuple] = []

    async def _spawn(bot, chat_id, owner_id, path, name, kind, info, lang, **kw):
        out.append(("spawn", path, kind, kw.get("post_caption")))

    async def _rich(bot, chat_id, owner_id, media_paths, caption, lang):
        out.append(("rich", list(media_paths), caption))

    async def _album(bot, chat_id, owner_id, media_paths, caption, lang):
        out.append(("album", list(media_paths), caption))
        return []

    monkeypatch.setattr(TD, "_spawn", _spawn)
    monkeypatch.setattr(TD, "_deliver_rich_post", _rich)
    monkeypatch.setattr(TD, "_deliver_album", _album)
    return out


@pytest.fixture
def gallerydl_ok(tmp_path, monkeypatch):
    """gallery-dlِ **اجراییِ** جعلی که موفق می‌شود (مسیرِ کوکی).

    یک فایل در `<workdir>/gl/` می‌سازد، دقیقاً همان‌جایی که موتورِ واقعی می‌نویسد.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    s = bindir / "gallery-dl"
    s.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "d = sys.argv[sys.argv.index('-D') + 1]\n"
        "os.makedirs(d, exist_ok=True)\n"
        "open(os.path.join(d, 'from_cookie_path.jpg'), 'wb').write(b'cookie-bytes')\n")
    s.chmod(s.stat().st_mode | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    return s


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """فلگ روشن + استخرِ اینستاگرامِ **پر** + work_dirِ موقت."""
    ckdir = tmp_path / "ck"
    ckdir.mkdir(exist_ok=True)
    wd = tmp_path / "w"
    wd.mkdir(exist_ok=True)
    monkeypatch.setattr(ck.settings, "cookies_dir", str(ckdir))
    monkeypatch.setattr(TD.settings, "work_dir", str(wd))
    monkeypatch.setattr(TD.settings, "dl_ig_anon_enabled", True)
    monkeypatch.setattr(TD.settings, "admin_ids", "42")
    return wd


async def _stock(redis) -> None:
    """یک اکانتِ سالمِ اینستاگرام در استخر — تا «لمس نشد» معنا داشته باشه."""
    assert await ck._save_cookie(redis, "instagram_a.txt", _NETSCAPE) == ""
    meta = await ck.get_meta(redis, "instagram_a.txt")
    meta["platform"] = "instagram"
    await ck.set_meta(redis, "instagram_a.txt", meta)
    assert await ck.pool_counts(redis, "instagram") == (1, 1)


async def _run(bot, redis, url: str, ref: str = "iga00001") -> None:
    await TD.run_download({"bot": bot, "redis": redis}, {
        "ref": ref, "chat_id": 7, "status_mid": 9, "lang": "fa", "url": url,
        "platform": "instagram", "engine": "gallerydl", "phase": "fetch",
        "selector": "best", "owner_id": 1, "tg_user_id": 42})


def _counter(redis, bucket: str):
    return redis.get(f"dlstat:iganon:{bucket}:{TD._today()}")


# ── ۱) قلبِ کلِ کار ────────────────────────────────────────────────
async def test_a_successful_anonymous_pass_never_picks_or_materializes_a_cookie(
        ig, spy, delivered, wired, redis):
    """استخر **پر** است و باید دست‌نخورده بماند.

    ادعا «کوکی استفاده نشد» نیست — آن ضعیف است. ادعا این است که کوکی اصلاً
    **انتخاب و materialize نشد**: `pick` یک اکانت را از چرخه درمی‌آورد،
    `materialize` روی دیسکِ نود می‌نویسد و `note_use` مهرِ فاصلهٔ حداقلی می‌زند —
    هر سه بی‌بازگشت، حتی اگر فایل هیچ‌وقت به موتور نرسد.
    """
    await _stock(redis)
    ig["mode"] = "reel"
    bot = FakeBot()

    await _run(bot, redis, REEL)

    assert spy["pick"] == 0, f"هیچ اکانتی نباید انتخاب شود: {dict(spy)}"
    assert spy["materialize"] == 0, dict(spy)
    assert spy["note_use"] == 0 and spy["note_spend"] == 0, dict(spy)
    assert spy["mark_ok"] == 0 and spy["mark_fail"] == 0, dict(spy)
    assert [k for k, *_ in delivered] == ["spawn"], delivered
    assert await _counter(redis, "ok") == "1"


async def test_no_cookie_header_reaches_the_media_server(ig, wired, redis, monkeypatch):
    """`opts` عمداً **با** کوکی داده می‌شود — همان شکلی که `_opts` می‌سازد."""
    ig["mode"] = "carousel"
    seen_headers: list[dict] = []
    real = D.download_direct

    async def _tap(url, workdir, opts=None, **kw):
        seen_headers.append(dict(D._direct_headers(opts or {})))
        assert (opts or {}).get("cookies") == "/cookies/instagram_1.txt"
        return await real(url, workdir, opts, **kw)

    monkeypatch.setattr(D, "download_direct", _tap)
    got = await IGA.download_anonymous(
        CAROUSEL, str(wired / "job"),
        {"cookies": "/cookies/instagram_1.txt", "proxy": "", "user_agent": None})

    assert got.bucket == IGA.B_OK and got.paths
    assert seen_headers, "هیچ دانلودی انجام نشد — تست چیزی ثابت نمی‌کند"
    for h in seen_headers:
        assert not any(k.lower() == "cookie" for k in h), h
        assert "instagram_1.txt" not in repr(h)


# ── ۲) جداسازیِ فایل ──────────────────────────────────────────────
async def test_a_half_finished_anonymous_failure_leaves_no_file_behind(
        ig, spy, delivered, wired, gallerydl_ok, redis, monkeypatch):
    """کاروسلِ ۱۱تایی که آیتمِ چهارمش می‌افتد.

    **workdir باید در لحظه‌ای سنجیده شود که مسیرِ کوکی شروع می‌کند، نه بعد از
    پایانِ جاب.** نسخهٔ اولِ این تست بعد از `run_download` نگاه می‌کرد و توخالی
    بود: `finally`ِ خودِ `run_download` کلِ workdir را پاک می‌کند، پس «چیزی نمانده»
    بی‌قیدوشرط صادق بود و با خرابکاری هم سبز می‌ماند. همان تلهٔ «تستی که ادعا
    می‌کند چیزی نیست، در حالی که آن چیز به‌هرحال خودش می‌رود» در §۶.

    ادعا هم دقیقاً همان چیزی است که قید می‌گوید: مسیرِ کوکی نباید یک workdirِ
    آلوده تحویل بگیرد.
    """
    await _stock(redis)
    ig["mode"] = "carousel"
    ig["fail_from"] = 3
    saw: list[list[str]] = []
    real = D.download_gallerydl

    async def _tap(url, workdir, opts, **kw):
        saw.append(sorted(os.listdir(workdir)))
        return await real(url, workdir, opts, **kw)

    monkeypatch.setattr(D, "download_gallerydl", _tap)
    bot = FakeBot()

    await _run(bot, redis, CAROUSEL)

    media_hits = sum(1 for p in ig["seen"] if not p.startswith("/embed/"))
    assert media_hits >= 4, f"شکست باید **نیمه‌کاره** باشد، نه صفر آیتم: {media_hits}"
    assert saw, "مسیرِ کوکی اصلاً اجرا نشد — تست چیزی ثابت نمی‌کند"
    assert IGA.ANON_DIR not in saw[0], f"مسیرِ کوکی workdirِ آلوده دید: {saw[0]}"
    assert spy["pick"] == 1, dict(spy)
    assert [k for k, *_ in delivered] == ["spawn"], delivered
    assert delivered[0][1].endswith("from_cookie_path.jpg"), delivered
    assert await _counter(redis, "fetch_failed") == "1"


async def test_the_aggregate_cap_stops_a_greedy_carousel(
        ig, spy, delivered, wired, gallerydl_ok, redis, monkeypatch):
    """سقف **تجمعی** است: کاروسل باید وسطِ راه بایستد، نه بعد از ۱۱ فایل.

    نسخهٔ اولِ این تست خودش خراب بود و همین‌جا گرفته شد: ۱۱ آیتمِ ۴۰ کیلوبایتی
    زیرِ سقفِ ۱ مگابایتی می‌ماند، پس پاسِ ناشناس **موفق** می‌شد و تست چیزی را که
    ادعا می‌کرد نمی‌سنجید. ۲۰۰ کیلوبایت یعنی بودجه واقعاً وسطِ کاروسل تمام شود.
    """
    await _stock(redis)
    ig["mode"] = "carousel"
    ig["pad"] = 200_000                                   # ۱۱ × ۲۰۰KB ≫ سقفِ ۱MB
    monkeypatch.setattr(TD.settings, "dl_max_size_mb", 1)
    bot = FakeBot()

    await _run(bot, redis, CAROUSEL)

    wd = wired / "dl-iga00001"
    assert not (wd / IGA.ANON_DIR).exists(), "فایلِ نیمه‌کاره نباید بماند"
    assert await _counter(redis, "fetch_failed") == "1"
    assert await _counter(redis, "ok") is None, "پاسِ ناشناس نباید موفق شمرده شود"
    assert spy["pick"] == 1, "باید به مسیرِ کوکی افتاده باشد"


async def test_the_time_budget_stops_a_dribbling_cdn(ig, wired):
    """کرانِ زمانیِ پاسِ ناشناس، چون `download_direct` کرانِ کلی ندارد.

    `ClientTimeout(total=None, connect=30, sock_read=120)` برای یک فایلِ تکی درست
    است ولی این‌جا در N آیتم ضرب می‌شود، و تنها کرانِ باقی‌مانده `job_timeout`ِ
    ۵۴۰۰ ثانیه‌ای است. این پاس **گمانه‌زنی** است: اگر نگرفت باید سریع کنار برود
    تا مسیرِ کوکی وقت داشته باشد.

    سرور **تمام‌شدنی نیست** (۳۰ ثانیه می‌خوابد)، پس «ایستاد» فقط می‌تواند یعنی
    بودجه اعمال شد — نه اینکه اتفاقی زودتر تمام شده باشد.
    """
    ig["mode"] = "carousel"
    ig["hang"] = True
    loop = asyncio.get_running_loop()
    t0 = loop.time()

    got = await IGA.download_anonymous(CAROUSEL, str(wired / "job"),
                                       {"proxy": "", "user_agent": None}, budget=0.5)

    assert got.bucket == IGA.B_FETCH_FAILED, got
    assert loop.time() - t0 < 10, "بودجه اعمال نشد — به sleepِ ۳۰ ثانیه‌ای رسیدیم"
    assert not (wired / "job" / IGA.ANON_DIR).exists()


# ── ۳) کنترل: فلگِ خاموش یعنی مسیرِ امروز، بایت‌به‌بایت ────────────
async def test_with_the_flag_off_the_path_is_byte_for_byte_todays(
        ig, spy, delivered, wired, gallerydl_ok, redis, monkeypatch):
    """**کنترل** — روی هر دو سورس سبز است. گاردِ ضدِ رگرسیون، نه اثباتِ قابلیت."""
    monkeypatch.setattr(TD.settings, "dl_ig_anon_enabled", False)
    await _stock(redis)
    ig["mode"] = "reel"
    bot = FakeBot()

    await _run(bot, redis, REEL)

    assert ig["seen"] == [], f"با فلگِ خاموش هیچ درخواستی نباید برود: {ig['seen']}"
    assert spy["pick"] == 1 and spy["materialize"] == 1, dict(spy)
    assert delivered and delivered[0][1].endswith("from_cookie_path.jpg")
    for b in IGA.BUCKETS:
        assert await _counter(redis, b) is None, b


def test_the_flag_default_is_off():
    """پیش‌فرضِ `config` باید False باشد: استقرار نباید رفتاری را عوض کند."""
    from app.config import Settings
    assert Settings.model_fields["dl_ig_anon_enabled"].default is False


# ── ۴) سقوط به مسیرِ کوکی ────────────────────────────────────────
@pytest.mark.parametrize("mode,bucket", [("403", "blocked"),
                                         ("junk", "unsupported"),
                                         ("500", "network")])
async def test_a_failed_verdict_falls_through_to_the_cookie_path(
        mode, bucket, ig, spy, delivered, wired, gallerydl_ok, redis):
    await _stock(redis)
    ig["mode"] = mode
    bot = FakeBot()

    await _run(bot, redis, REEL)

    assert await _counter(redis, bucket) == "1", f"سطلِ {bucket}"
    assert spy["pick"] == 1, dict(spy)
    assert delivered and delivered[0][1].endswith("from_cookie_path.jpg"), delivered


# ── ۵) هیچ شکستِ ناشناسی پای اکانتی نوشته نمی‌شود ─────────────────
async def test_a_network_verdict_never_blames_an_account(
        ig, spy, delivered, wired, gallerydl_ok, redis, monkeypatch):
    """سرورِ مرده = قطعیِ شبکه. اکانتِ سالم نباید حتی یک ضربه بخورد.

    این همان درسِ `_resolve_blame` است: تقصیر را به متنِ خطا نسپار — و شکستی که
    اصلاً کوکی در آن دخیل نبوده هرگز تقصیرِ اکانت نیست.
    """
    await _stock(redis)
    before = await ck.get_meta(redis, "instagram_a.txt")
    # سرور را از دسترس خارج کن: پورتِ بسته روی همان هاست
    monkeypatch.setattr(IGA, "_EMBED", "http://127.0.0.1:1/embed/{sc}")
    bot = FakeBot()

    await _run(bot, redis, REEL)

    assert await _counter(redis, "network") == "1"
    assert spy["mark_fail"] == 0, f"هیچ اکانتی نباید ضربه بخورد: {dict(spy)}"
    after = await ck.get_meta(redis, "instagram_a.txt")
    assert after.get("fail_streak", 0) == before.get("fail_streak", 0)
    assert after.get("last_error", "") == before.get("last_error", "")


# ── ۶) استوری و پروفایل: نه شبکه، نه تلاش ────────────────────────
@pytest.mark.parametrize("url", [STORY, PROFILE])
async def test_a_story_or_profile_link_never_touches_the_anonymous_network(
        url, ig, spy, delivered, wired, gallerydl_ok, redis):
    """شورت‌کد ندارند، پس مسیرِ ناشناس ندارند — و نباید حتی یک درخواست بزنند."""
    await _stock(redis)
    bot = FakeBot()

    await _run(bot, redis, url)

    assert ig["seen"] == [], f"نباید درخواستی برود: {ig['seen']}"
    assert await _counter(redis, "skipped") == "1"
    assert await _counter(redis, "ok") is None
    assert spy["pick"] == 1, "باید مستقیم به مسیرِ کوکی رفته باشد"


# ── ۷) ترتیبِ کاروسل ──────────────────────────────────────────────
async def test_the_carousel_order_is_preserved(ig, wired):
    """ترتیب از **ساختِ** فهرست می‌آید، نه از `sorted()` روی نامِ CDN.

    بدنهٔ هر فایل مسیرِ خودش است، پس مقایسه مستقیم با ترتیبِ `result.items`
    انجام می‌شود — بدونِ تکیه بر نامِ فایل، که خودش چیزی است که عوض شده.

    **مرزِ صداقتِ این تست:** طراحی **دو** تضمینِ مستقل دارد و این تست فقط
    نتیجه را می‌سنجد، نه اینکه کدام‌شان کار کرده — زیرشاخهٔ per-item با ایندکسِ
    صفرپرشده (`00`, `01`, …) باعث می‌شود `sorted()` روی مسیرِ کامل **عیناً** با
    ترتیبِ ساخت یکی دربیاید. پس سابوتاژِ «`sorted()` به‌جای ترتیبِ ساخت» عمداً
    ثبت **نشده**: گرفتنی نیست چون خرابی‌ای نمی‌سازد. سابوتاژِ ثبت‌شده
    (`reversed`) ثابت می‌کند خودِ assert زنده است.
    """
    ig["mode"] = "carousel"
    opts = {"proxy": "", "user_agent": None}
    out = await IGA.resolve_detailed(CAROUSEL, opts)
    assert out.verdict == IGA.V_OK and len(out.result.items) == 11

    got = await IGA.download_anonymous(CAROUSEL, str(wired / "job"), opts)

    assert got.bucket == IGA.B_OK and len(got.paths) == 11
    from urllib.parse import urlparse
    want = [urlparse(i.url).path for i in out.result.items]
    have = [Path(p).read_bytes().decode() for p, _i, _t in got.paths]
    assert have == want, "ترتیبِ فایل‌ها با ترتیبِ آیتم‌ها یکی نیست"
    assert len(set(have)) == 11, "آیتم‌ها روی هم نوشته شده‌اند"


# ── ۸) تله‌متری ───────────────────────────────────────────────────
async def test_every_bucket_lands_in_its_own_counter(
        ig, spy, delivered, wired, gallerydl_ok, redis, monkeypatch):
    """هر شش سطل، از جمله `fetch_failed` که `resolve` دربارهٔ‌اش حرفی ندارد."""
    await _stock(redis)
    bot = FakeBot()

    runs = [("reel", REEL, None, "ok"), ("junk", REEL, None, "unsupported"),
            ("403", REEL, None, "blocked"), ("500", REEL, None, "network"),
            ("reel", STORY, None, "skipped"), ("carousel", CAROUSEL, 0, "fetch_failed")]
    for i, (mode, url, fail_from, _b) in enumerate(runs):
        ig["mode"], ig["fail_from"] = mode, fail_from
        await _run(bot, redis, url, ref=f"iga0000{i}")

    for _m, _u, _f, bucket in runs:
        assert await _counter(redis, bucket) == "1", bucket
    assert sorted(IGA.BUCKETS) == sorted(b for *_x, b in runs), \
        "فهرستِ سطل‌ها و پوششِ تست از هم واگرا شده‌اند"


# ── ۹) شکلِ تحویل دست‌نخورده ──────────────────────────────────────
async def test_a_carousel_keeps_the_gallerydl_album_shape(
        ig, spy, delivered, wired, redis):
    """`engine` باید `gallerydl` بماند، وگرنه شاخهٔ کاروسل عوض می‌شود."""
    await _stock(redis)
    ig["mode"] = "carousel"
    bot = FakeBot()

    await _run(bot, redis, CAROUSEL)

    assert [k for k, *_ in delivered] == ["rich"], delivered
    _kind, media, caption = delivered[0]
    assert len(media) == 11 and caption, "کپشنِ پست باید از مسیرِ ناشناس بیاید"


async def test_a_single_photo_keeps_the_gallerydl_card_shape(
        ig, spy, delivered, wired, redis):
    """تک‌آیتمِ گالری → کارتِ جدا (`_spawn`)، نه تحویلِ درجا."""
    await _stock(redis)
    ig["mode"] = "photo"
    bot = FakeBot()

    await _run(bot, redis, PHOTO)

    assert [k for k, *_ in delivered] == ["spawn"], delivered
    _kind, path, kind, _cap = delivered[0]
    assert kind == "image" and IGA.ANON_DIR in path, path


# ── ۱۰) لغو ──────────────────────────────────────────────────────
async def test_cancel_during_the_anonymous_pass_says_cancelled(
        ig, spy, delivered, wired, gallerydl_ok, redis):
    """لغو نباید بی‌صدا به مسیرِ کوکی بیفتد و یک اکانت خرج کند."""
    await _stock(redis)
    ig["mode"] = "carousel"
    await redis.set("cancel:dl:iga00001", "1")
    bot = FakeBot()

    await _run(bot, redis, CAROUSEL)

    from app.i18n import t
    assert bot.edits and bot.edits[-1] == t("fa", "cancelled"), bot.edits[-3:]
    assert delivered == [], "لغو نباید چیزی تحویل بدهد"
    assert spy["pick"] == 0, f"لغو نباید کوکی خرج کند: {dict(spy)}"
    assert not (wired / "dl-iga00001" / IGA.ANON_DIR).exists()


# ── ۱۱) فیلترِ ایمنی روی مسیرِ ناشناس هم اعمال می‌شود ─────────────
async def test_the_safety_layer_still_blocks_media_from_the_anonymous_path(
        ig, spy, delivered, wired, redis, monkeypatch):
    """تنها ویژگیِ **کاربر-محورِ ایمنیِ** این تغییر.

    منطقاً باید درست باشد (چون گامِ ناشناس قبل از حلقه است و چک‌ها بعد از آن)،
    ولی «منطقاً درست است» چیزی است که تست برای اثباتش وجود دارد.
    """
    await _stock(redis)
    ig["mode"] = "reel"

    async def _policy():
        return TD.safety.Policy(enabled=True, scan_pixels=True, threshold=0.5, frames=1)

    async def _scan(path, kind, threshold, frames, workdir):
        return True, 0.99, "EXPOSED"

    monkeypatch.setattr(TD.safety, "load_policy", _policy)
    monkeypatch.setattr(TD.safety, "scan_file", _scan)
    monkeypatch.setattr(TD.safety, "report_block",
                        lambda *a, **kw: asyncio.sleep(0, result=False))
    bot = FakeBot()

    await _run(bot, redis, REEL)

    from app.i18n import t
    assert delivered == [], "محتوای مسدود نباید تحویل شود"
    assert bot.edits and bot.edits[-1] == t("fa", "nsfw_blocked"), bot.edits[-3:]


# ── ۱۲) ثبتِ کلید (AST، بدونِ import — قاعدهٔ ۲۰۲۶-۰۸-۱۳) ─────────
def test_the_flag_is_registered_everywhere_the_panel_needs_it():
    """`admin_web` روی رانرِ CI قابلِ import نیست، پس سورس با AST خوانده می‌شود."""
    from app.settings_store import RUNTIME_KEYS
    assert RUNTIME_KEYS.get("dl_ig_anon_enabled") == ("bool", False)

    src = Path("app/admin_web.py").read_text(encoding="utf-8")
    groups = next(ast.literal_eval(n.value)
                  for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Assign)
                  and any(getattr(t, "id", "") == "GROUPS" for t in n.targets))
    keys = {row[0] for _title, rows in groups for row in rows}
    assert "dl_ig_anon_enabled" in keys, "کلید در هیچ صفحهٔ پنلی نیست"
