"""هشدارِ «کوکیِ سالم نمانده» باید بینِ «استخر سوخت» و «سطل هرگز پر نشد» فرق بگذارد.

پس‌زمینه (همه اندازه‌گیری‌شده، نه استدلال): `_cookie_platform` می‌تواند **۱۴**
سطلِ متفاوت بخواهد، ولی `admin_web.COOKIE_PLATFORMS` فقط **۶** تا می‌سازد. پس
هشت پلتفرمِ پشتیبانی‌شده (ساندکلاود، آپارات، ویمئو، توییچ، دیلی‌موشن، بندکمپ،
ردیت، استریمبل) و معمولاً «other» سطلی می‌خواهند که هیچ‌وقت اکانت ندارد — و
`_alert_if_low` برای هر کدامشان هر ۶ ساعت یک DMِ قرمز می‌فرستاد.

خالی‌بودنِ سطل دانلود را متوقف نمی‌کند: `run_download` یک تلاشِ **بی‌کوکی**
می‌زند و اگر سایت ناشناس جواب بدهد موفق می‌شود. پس آن هشدار نویز بود، نه خبر.

تستِ **کنترل** این‌جا از تستِ رفعْ مهم‌تر است: گاردِ ساده‌لوحانه
(`if not left: return`) هشدارِ استخرِ سوخته را هم خفه می‌کند، یعنی دقیقاً همان
چیزی که این تابع برایش وجود دارد. `test_a_burned_pool_still_screams` همان را
می‌گیرد و باید روی چنین رفعی fail شود.
"""
from __future__ import annotations

import logging
import os
import stat

import pytest

from tests.aiogram_double import ValidatingBot

from app import cookies as ck
from app import tasks_download as TD

_NETSCAPE = ("# Netscape HTTP Cookie File\n"
             ".example.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\tv\n")


class FakeBot(ValidatingBot):
    """فقط `send_message` را نگه می‌دارد؛ امضاها از خودِ aiogram می‌آیند."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.edits: list[str] = []

    def _on(self, name, payload):
        if name == "send_message":
            self.messages.append(payload["text"])
        elif name == "edit_message_text":
            self.edits.append(payload["text"])
        elif name == "edit_message_caption":
            self.edits.append(payload.get("caption"))
        return True


@pytest.fixture
def pool(tmp_path, monkeypatch):
    """استخرِ واقعی روی دیسکِ موقت + ادمینی که DM را دریافت کند."""
    d = tmp_path / "ck"
    d.mkdir()
    monkeypatch.setattr(ck.settings, "cookies_dir", str(d))
    monkeypatch.setattr(TD.settings, "admin_ids", "42")
    return d


@pytest.fixture
def fail_ytdlp(tmp_path, monkeypatch):
    """yt-dlpِ **اجراییِ** جعلی که شکست می‌خورد — زیرفرایندِ واقعی، نه ماک."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("yt-dlp", "gallery-dl"):
        s = bindir / tool
        s.write_text("#!/usr/bin/env python3\nimport sys\n"
                     'sys.stderr.write("ERROR: Unsupported URL\\n")\nsys.exit(1)\n')
        s.chmod(s.stat().st_mode | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")


async def _add(redis, name: str, platform: str, **meta_over) -> None:
    assert await ck._save_cookie(redis, name, _NETSCAPE) == ""
    meta = await ck.get_meta(redis, name)
    meta.update({"platform": platform, **meta_over})
    await ck.set_meta(redis, name, meta)


# ── ۱) سطلی که هرگز پر نشده ────────────────────────────────────────
async def test_a_bucket_that_was_never_stocked_is_silent(redis, pool):
    """«۰ از ۰» خبر نیست. روی سورسِ پیش از رفع، این‌جا یک DMِ قرمز می‌آمد."""
    assert await ck.pool_counts(redis, "other") == (0, 0)

    bot = FakeBot()
    await TD._alert_if_low(redis, bot, "other")

    assert bot.messages == [], f"سطلِ خالی نباید DM بدهد: {bot.messages}"


@pytest.mark.parametrize("platform",
                         ["soundcloud", "aparat", "vimeo", "twitch",
                          "dailymotion", "bandcamp", "reddit", "streamable"])
async def test_the_unstockable_platforms_are_silent(platform, redis, pool):
    """این هشت‌تا را پنل اصلاً نمی‌تواند پر کند، پس هشدارشان همیشه کاذب است."""
    bot = FakeBot()
    await TD._alert_if_low(redis, bot, platform)
    assert bot.messages == []


# ── ۲) کنترل: استخرِ سوخته هنوز باید داد بزند ──────────────────────
async def test_a_burned_pool_still_screams(redis, pool):
    """سه اکانت که هیچ‌کدام قابلِ‌استفاده نیستند = استخرِ سوخته.

    این تستِ **کنترل** است: اگر گارد را روی `healthy_count` بنویسی (`if not
    left: return`) این‌جا fail می‌شود، چون آن‌وقت رفع تبدیل می‌شود به خفه‌کردنِ
    همان زنگی که تابع برایش هست.
    """
    await _add(redis, "cookies_a.txt", "other", frozen=True)
    await _add(redis, "cookies_b.txt", "other", fail_streak=9)
    await _add(redis, "cookies_c.txt", "other", disabled=True)
    total, left = await ck.pool_counts(redis, "other")
    # فیکسچر باید واقعاً همان چیزی باشد که ادعا می‌کند، وگرنه تست بی‌معنی است
    assert (total, left) == (3, 0), [a["status"] for a in await ck.accounts(redis, "other")]

    bot = FakeBot()
    await TD._alert_if_low(redis, bot, "other")

    assert len(bot.messages) == 1, "استخرِ سوخته باید دقیقاً یک DM بدهد"
    assert "🔴" in bot.messages[0] and "نمانده" in bot.messages[0]


# ── ۳) کنترل: سطلِ سالم ساکت است (رفتارِ قبلی دست‌نخورده) ───────────
async def test_a_stocked_healthy_bucket_is_silent(redis, pool, monkeypatch):
    monkeypatch.setattr(TD.settings, "cookie_alert_min", 1)
    await _add(redis, "youtube_a.txt", "youtube")
    assert await ck.pool_counts(redis, "youtube") == (1, 1)

    bot = FakeBot()
    await TD._alert_if_low(redis, bot, "youtube")

    assert bot.messages == []


# ── ۴) کنترل: استخرِ نازک‌شده هنوز هشدارِ زردش را می‌دهد ────────────
async def test_a_thinning_pool_still_warns(redis, pool, monkeypatch):
    """مسیرِ ناصفر نباید قربانیِ این رفع شود."""
    monkeypatch.setattr(TD.settings, "cookie_alert_min", 2)
    await _add(redis, "youtube_a.txt", "youtube")
    await _add(redis, "youtube_b.txt", "youtube", frozen=True)
    assert await ck.pool_counts(redis, "youtube") == (2, 1)

    bot = FakeBot()
    await TD._alert_if_low(redis, bot, "youtube")

    assert len(bot.messages) == 1
    assert "🍪" in bot.messages[0], bot.messages[0]


# ── ۵) همان علامتی که گزارش شد، از مسیرِ واقعیِ `run_download` ──────
async def test_a_failed_unknown_link_does_not_alert(redis, pool, tmp_path,
                                                    monkeypatch, fail_ytdlp):
    """لینکِ هاستِ ناشناخته که شکست می‌خورد: کاربر خطا می‌بیند، ادمین نه.

    این دقیقاً همان چیزی است که گزارش شد — لینکِ اپل روی کدِ قدیم «other» می‌شد
    و شکست می‌خورد. اندازه‌گیری‌شده: هیچ اکانتی ضربه نمی‌خورد (استخر خالی است،
    پس `cookie_name` همیشه `None` است و `failures` تهی می‌ماند)، تنها اثرِ آن
    شکست همان DM بود.
    """
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "w"))
    os.makedirs(tmp_path / "w", exist_ok=True)
    bot = FakeBot()

    await TD.run_download({"bot": bot, "redis": redis}, {
        "ref": "alr00001", "chat_id": 7, "status_mid": 9, "lang": "fa",
        "url": "https://music.apple.com/us/album/x/305568683?i=305568690",
        "platform": "other", "engine": "ytdlp", "phase": "fetch",
        "selector": "best", "owner_id": 1, "tg_user_id": 42})

    assert bot.edits and "❌" in bot.edits[-1], "کاربر باید خطا را ببیند"
    assert bot.messages == [], f"ادمین نباید هشدار بگیرد: {bot.messages}"


# ── ۶) همان تفکیک، یک پله آرام‌تر: سطحِ لاگِ `_warn_cookieless` ─────
# DM ساکت شد ولی خطِ ERROR نه — و ERRORِ کاذبِ دائمی یعنی خطای واقعی لایش گم
# می‌شود. سه حالت، چون تفکیک دو مرزی است نه یکی.
def _levels(records, needle="cookieless attempt"):
    return [r.levelname for r in records if needle in r.getMessage()]


async def test_an_unstocked_bucket_does_not_log_an_error(redis, pool, caplog):
    """سطلِ بی‌اکانت مسیرِ سالم است — لاگ باید باشد، ولی ERROR نه."""
    with caplog.at_level(logging.DEBUG, logger="telabzar.dl"):
        await TD._warn_cookieless(redis, FakeBot(), "aparat", "master")

    assert _levels(caplog.records) == ["INFO"], _levels(caplog.records)


async def test_a_burned_pool_still_logs_an_error(redis, pool, caplog):
    """کنترلِ معکوس: اکانت دارد ولی هیچ‌کدام سالم نیست → واقعاً ناهنجاری است.

    اگر این گارد را روی `usable` بنویسی (نه `total`) این تست fail می‌شود — همان
    اشتباهی که `test_a_burned_pool_still_screams` یک پله بالاتر می‌گیرد.
    """
    await _add(redis, "cookies_a.txt", "other", frozen=True)
    await _add(redis, "cookies_b.txt", "other", fail_streak=9)
    assert await ck.pool_counts(redis, "other") == (2, 0)

    with caplog.at_level(logging.DEBUG, logger="telabzar.dl"):
        await TD._warn_cookieless(redis, FakeBot(), "other", "master")

    assert _levels(caplog.records) == ["ERROR"], _levels(caplog.records)


async def test_a_pool_the_worker_cannot_see_still_errors_and_dms(redis, pool, caplog):
    """حالتی که این تابع اصلاً برایش ساخته شد: اکانتِ سالم هست ولی بی‌کوکی رفتیم."""
    await _add(redis, "instagram_a.txt", "instagram")
    assert await ck.pool_counts(redis, "instagram") == (1, 1)

    bot = FakeBot()
    with caplog.at_level(logging.DEBUG, logger="telabzar.dl"):
        await TD._warn_cookieless(redis, bot, "instagram", "master")

    assert _levels(caplog.records) == ["ERROR"], _levels(caplog.records)
    assert len(bot.messages) == 1 and "🛠" in bot.messages[0]


# ── ۷) نقطهٔ کورِ «۰ از ۰»: هرگز‌پرنشده در برابرِ پر‌بوده‌و‌خالی‌شده ─────
# بدونِ ردِ ماندگار، حذفِ اکانت‌های مردهٔ اینستاگرام (پیش از افزودنِ تازه‌ها)
# سطل را به همان «۰ از ۰»ی می‌رساند که تازه ساکتش کردیم — یعنی نویزِ نُه سطل را
# می‌بندیم و سیگنالِ سطل‌های مهم را خاموش می‌کنیم.
async def _delete(redis, name: str) -> None:
    """همان تابعی که هر دو مسیرِ حذفِ تولید صدا می‌زنند.

    نسخهٔ اولِ این کمکی سه گام را دستی نوشته بود و **دو** تایش را گرفت، پس تست
    شکست: `list_names` وقتی روی دیسک چیزی پیدا نکند به آینهٔ Redis برمی‌گردد و
    اکانت‌های «حذف‌شده» را همچنان می‌دید. همان تجربه دلیلِ یک‌جا شدنِ حذف است.
    """
    await ck.delete_account(redis, name)


async def test_deleting_the_last_account_leaves_a_durable_trace(redis, pool):
    """واحد: `was_stocked` باید از حذف جان به در ببرد — کلِ نکته همین است."""
    assert not await ck.was_stocked(redis, "instagram")
    await _add(redis, "instagram_a.txt", "instagram")
    assert await ck.was_stocked(redis, "instagram")

    await _delete(redis, "instagram_a.txt")

    assert await ck.pool_counts(redis, "instagram") == (0, 0)
    assert await ck.was_stocked(redis, "instagram"), "رد نباید با حذف پاک شود"


async def test_the_trace_has_no_expiry(redis, pool):
    """کلِ ارزشِ این رفع به ماندگاری بند است — یک TTL آن را بی‌صدا برمی‌گرداند.

    `TTL` روی کلیدِ **بدونِ انقضا** `-1` می‌دهد و روی کلیدِ **نبوده** `-2`، پس این
    یک assert هر دو خرابی را می‌گیرد: انقضای صریح، و انقضایی که از هلپری به ارث
    برسد. بعد از حذف سنجیده می‌شود، یعنی همان لحظه‌ای که رد باید کار کند.
    """
    await _add(redis, "instagram_a.txt", "instagram")
    await _delete(redis, "instagram_a.txt")

    assert await redis.ttl("ckseen:instagram") == -1, "رد نباید هیچ TTLی داشته باشد"


async def test_a_bucket_emptied_by_deletion_still_screams(redis, pool):
    """رفتاری: «۰ از ۰ ولی زمانی پر بوده» = قابلیتی که از کار افتاده.

    روی سورسِ پیش از این تغییر fail می‌شود — آن‌جا گارد فقط `total` را می‌دید و
    این حالت را با «آپارات» یکی می‌گرفت.
    """
    await _add(redis, "instagram_a.txt", "instagram")
    await _add(redis, "instagram_b.txt", "instagram")
    await _delete(redis, "instagram_a.txt")
    await _delete(redis, "instagram_b.txt")
    assert await ck.pool_counts(redis, "instagram") == (0, 0)

    bot = FakeBot()
    await TD._alert_if_low(redis, bot, "instagram")

    assert len(bot.messages) == 1, "سطلی که خالی شده باید داد بزند"
    assert "🔴" in bot.messages[0]


async def test_an_emptied_bucket_logs_an_error_not_an_info(redis, pool, caplog):
    """همان تفکیک در `_warn_cookieless`: خالی‌شدن ناهنجاری است، نه مسیرِ عادی."""
    await _add(redis, "instagram_a.txt", "instagram")
    await _delete(redis, "instagram_a.txt")

    with caplog.at_level(logging.DEBUG, logger="telabzar.dl"):
        await TD._warn_cookieless(redis, FakeBot(), "instagram", "master")

    assert _levels(caplog.records) == ["ERROR"], _levels(caplog.records)


async def test_a_never_stocked_bucket_is_still_silent_after_the_trace_exists(
        redis, pool, caplog):
    """کنترل: ردِ یک سطل نباید سطلِ دیگر را بیدار کند."""
    await _add(redis, "instagram_a.txt", "instagram")
    await _delete(redis, "instagram_a.txt")

    bot = FakeBot()
    with caplog.at_level(logging.DEBUG, logger="telabzar.dl"):
        await TD._alert_if_low(redis, bot, "aparat")
        await TD._warn_cookieless(redis, bot, "aparat", "master")

    assert bot.messages == []
    assert _levels(caplog.records) == ["INFO"], _levels(caplog.records)


# ── ۸) حفرهٔ راه‌اندازیِ سرد ────────────────────────────────────────
# رد را `set_meta` می‌نویسد، ولی اکانت‌های موجود پیش از این کد ساخته شده‌اند و
# ردی ندارند. اندازه‌گیری‌شده، نویسنده‌های `set_meta` عبارت‌اند از `mark_ok`/
# `mark_fail` (هر تلاشِ دانلود)، `unfreeze` و سه مسیرِ پنل/ربات — پس پنجره از
# استقرار تا **اولین دانلودِ** آن پلتفرم باز است، و ادمین دقیقاً در همان پنجره
# سشن‌های مرده را پاک می‌کند.

async def _forget_trace(redis, platform: str) -> None:
    """اکانتی که پیش از افزوده‌شدنِ `ckseen` ساخته شده بود را شبیه‌سازی می‌کند."""
    await redis.delete(f"ckseen:{platform}")


async def test_without_the_backfill_a_pre_existing_pool_goes_silent(redis, pool):
    """**کنترلِ خودِ حفره** — این تست حفره را ثبت می‌کند، نه رفع را.

    رفتاری است و روی هر دو طرف سبز می‌ماند: کارش این است که نشان دهد بدونِ
    backfill سکوت واقعاً رخ می‌دهد، وگرنه تستِ بعدی چیزی را اثبات نمی‌کند.
    """
    await _add(redis, "instagram_a.txt", "instagram")
    await _forget_trace(redis, "instagram")          # اکانتِ «قدیمی»
    await _delete(redis, "instagram_a.txt")

    bot = FakeBot()
    await TD._alert_if_low(redis, bot, "instagram")
    assert bot.messages == [], "بدونِ backfill سکوت است — همین حفره است"


async def test_the_backfill_closes_the_cold_start_hole(redis, pool):
    """سرِ استارت، سطلِ پر باید ردش را بگیرد تا حذفِ بعدی ساکت نماند.

    صداقتِ اثبات: روی سورسِ پیش از رفع این با `AttributeError` می‌افتد (نبودِ
    symbol)، که ضعیف‌تر از شکافِ رفتاری است. چیزی که واقعاً رگرسیونِ محتمل را
    می‌گیرد `test_worker_startup_backfills_the_seen_marks` است — «هلپر هست ولی
    کسی صدایش نمی‌زند».
    """
    await _add(redis, "instagram_a.txt", "instagram")
    await _add(redis, "youtube_a.txt", "youtube")
    await _forget_trace(redis, "instagram")
    await _forget_trace(redis, "youtube")

    assert await ck.backfill_seen(redis) == 2

    await _delete(redis, "instagram_a.txt")
    bot = FakeBot()
    await TD._alert_if_low(redis, bot, "instagram")
    assert len(bot.messages) == 1, "سطلی که زمانی پر بوده باید داد بزند"


async def test_the_backfill_does_not_invent_a_trace(redis, pool):
    """کنترل: سطلی که اکانت ندارد نباید علامت بخورد، وگرنه backfill همان نویزِ
    نُه سطل را برمی‌گرداند."""
    await _add(redis, "instagram_a.txt", "instagram")
    assert await ck.backfill_seen(redis) == 1
    assert not await ck.was_stocked(redis, "aparat")

    bot = FakeBot()
    await TD._alert_if_low(redis, bot, "aparat")
    assert bot.messages == []


def test_worker_startup_backfills_the_seen_marks():
    """هلپرِ صداـنشده همان حفره است. سورس با AST خوانده می‌شود (نه import،
    چون `app.worker` سرِ import سراغِ چیزهایی می‌رود که رانرِ CI ندارد)."""
    import ast
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "app" / "worker.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "startup")
    called = {c.func.attr for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "backfill_seen" in called, "`worker.startup` باید backfill را صدا بزند"
