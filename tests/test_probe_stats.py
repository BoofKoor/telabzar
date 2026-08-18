"""شمارندهٔ فازِ probe — و مهم‌تر از خودِ شمارنده، اینکه چیزِ دیگری عوض نشده.

هر تستِ این فایل از **مسیرِ واقعی** می‌رود: `run_download`ِ واقعی با یک
`yt-dlp`ِ اجراییِ واقعی روی PATH، و `on_dl_pick`ِ واقعی با `CallbackQuery`ِ
واقعیِ aiogram. صداکردنِ مستقیمِ `probe_stats.note_pick()` تابعِ کمکی را تست
می‌کند و **اتصال** را نه — همان شکافی که `test_probe_cookie_blame.py` برای
بستنش نوشته شد و همان‌جا هم ثبت شده که جهش‌آزمایی نشان داد حذفِ کاملِ یک شاخه
صفر تست را می‌شکند.

سه ادعا این‌جا از بقیه مهم‌ترند و هر سه **کنترل**اند نه قابلیت:

۱) `test_an_age_blocked_probe_is_not_counted_as_a_menu` — probeِ موفقی که
   سیاست کشتش هرگز منو نمی‌بیند، پس اگر در سطلِ `menu` بیفتد مخرجِ نرخِ
   رهاشدن با هر لینکِ سنی باد می‌کند. سابوتاژش بردنِ شمارنده به بالای گیت است.
۲) `test_a_cancel_of_a_running_download_is_not_counted` — `Dl(sel="cancel")`
   دو تولیدکننده دارد و از روی callback تفکیک‌پذیر نیست؛ این تست تنها چیزی
   است که ثابت می‌کند نشانگر واقعاً تفکیکشان می‌کند.
۳) `test_the_probe_phase_still_costs_exactly_what_it_did` — قیدِ «فقط
   اندازه‌گیری». چهار هزینهٔ ثبت‌شدهٔ فازِ probe باید **دست‌نخورده** بمانند؛
   اگر کسی بعداً «کمکی» یکی‌شان را ببندد این تست قرمز می‌شود و مجبورش می‌کند
   تصمیم را صریح بگیرد، نه اینکه سوارِ یک PRِ اندازه‌گیری شود.
"""
from __future__ import annotations

import json
import os
import stat
import textwrap
from datetime import datetime, timezone

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User as TgUser

from tests.aiogram_double import ValidatingBot

from app import cookies as ck
from app import dl_active
from app import probe_stats as PS
from app import tasks_download as TD
from app.callbacks import Dl
from app.routers.download import on_dl_pick

# yt-dlpِ جعلی: با `FAKE_MODE=ok` همان JSONی را می‌دهد که `-J` می‌دهد، وگرنه
# مثلِ خطای واقعی روی stderr می‌افتد. هر فراخوانی ثبت می‌شود تا «چند بار موتور
# صدا شد» و «با کدام کوکی» قابلِ assert باشد.
_FAKE_YTDLP = r'''#!/usr/bin/env python3
import os, sys
argv = sys.argv[1:]
ckp = argv[argv.index("--cookies") + 1] if "--cookies" in argv else ""
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(os.path.basename(ckp) + "\n")
if os.environ.get("FAKE_MODE") == "ok":
    sys.stdout.write(os.environ["FAKE_JSON"])
    sys.exit(0)
sys.stderr.write("ERROR: [youtube] abc: %s\n" % os.environ.get("FAKE_ERR", "boom"))
sys.exit(1)
'''

NETSCAPE = ("# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tLOGIN_INFO\tvalue\n")

# خطایی که `_is_cookie_error` واقعاً می‌گیردش، وگرنه حلقه نمی‌چرخد و تستِ
# «هر تلاش یک اکانت» توخالی می‌شود (تلهٔ ۱ در `test_probe_cookie_blame`).
MSG_ROTATES = ("An unexpected error occurred: JSONDecodeError - "
               "Expecting value: line 1 column 1 (char 0)")


def _info(**over) -> str:
    data = {
        "title": "T", "id": "abc", "duration": 100,
        "thumbnail": "https://example.invalid/t.jpg",
        "formats": [
            {"height": 720, "vcodec": "h264", "tbr": 1000.0, "acodec": "none"},
            {"height": None, "vcodec": "none", "acodec": "aac", "tbr": 128.0},
        ],
    }
    data.update(over)
    return json.dumps(data)


class FakeBot(ValidatingBot):
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def _on(self, name, payload):
        self.sent.append((name, payload))
        return True


@pytest.fixture
def ytdlp(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "yt-dlp"
    script.write_text(textwrap.dedent(_FAKE_YTDLP))
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    logpath = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_LOG", str(logpath))
    monkeypatch.setenv("FAKE_MODE", "ok")
    monkeypatch.setenv("FAKE_JSON", _info())

    class _Ctl:
        @staticmethod
        def ok(**over):
            monkeypatch.setenv("FAKE_MODE", "ok")
            monkeypatch.setenv("FAKE_JSON", _info(**over))

        @staticmethod
        def fail(err: str = MSG_ROTATES):
            monkeypatch.setenv("FAKE_MODE", "fail")
            monkeypatch.setenv("FAKE_ERR", err)

        @staticmethod
        def calls() -> list[str]:
            return logpath.read_text().splitlines() if logpath.exists() else []

    return _Ctl


@pytest.fixture
def payload(tmp_path, monkeypatch):
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "work"))
    os.makedirs(tmp_path / "work", exist_ok=True)
    return {"ref": "prb00001", "chat_id": 7, "status_mid": 9, "lang": "fa",
            "url": "https://www.youtube.com/watch?v=abc", "platform": "youtube",
            "engine": "ytdlp", "phase": "probe", "owner_id": 1, "tg_user_id": 42}


async def _stock(redis, monkeypatch, tmp_path, n: int) -> list[str]:
    ckdir = tmp_path / "ck"
    os.makedirs(ckdir, exist_ok=True)
    monkeypatch.setattr(ck.settings, "cookies_dir", str(ckdir))
    names = [f"cookies_youtube-{c}.txt" for c in "abcdefgh"[:n]]
    for name in names:
        assert await ck._save_cookie(redis, name, NETSCAPE) == ""
    assert len(await ck.accounts(redis, "youtube")) == n, \
        "استخر باید واقعاً اکانت داشته باشد وگرنه ادعای مصرفِ کوکی توخالی است"
    return names


async def _run(redis, payload, bot=None):
    bot = bot or FakeBot()
    await TD.run_download({"bot": bot, "redis": redis}, payload)
    return bot


async def _counts(redis) -> dict[str, int]:
    out = {}
    for b in PS.BUCKETS:
        raw = await redis.get(PS.key(b))
        out[b] = int(raw) if raw else 0
    return out


# ══ سمتِ ورکر ═══════════════════════════════════════════════════════

async def test_a_probe_that_shows_a_menu_is_counted(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """ادعای مرکزی: probeِ **موفق** تا امروز هیچ ردی نمی‌گذاشت.

    روی سورسِ پیش از رفع می‌افتد — `_metric` در شاخهٔ probe فقط روی شکست است،
    پس یک دانلودِ کاملاً سالم صفر شمارنده می‌ساخت.
    """
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.ok()

    await _run(redis, payload)

    c = await _counts(redis)
    assert c[PS.MENU] == 1
    assert c[PS.FAIL] == 0 and c[PS.BLOCKED] == 0
    assert c[PS.ATTEMPT] == 1, "یک probeِ موفق دقیقاً یک بار موتور را صدا می‌زند"


async def test_a_menu_leaves_a_marker_so_the_pick_can_be_deduped(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.ok()

    await _run(redis, payload)

    ttl = await redis.ttl(PS.menu_key(payload["ref"]))
    assert 0 < ttl <= PS.MENU_TTL, "نشانگر باید زنده و TTLدار باشد، نه جاودان"


async def test_a_failed_probe_counts_one_attempt_per_cookie_it_burned(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """`attempt` واحدِ **مصرفِ منبع** است، و probe می‌تواند چند اکانت خرج کند.

    این تفکیک کلِ دلیلِ وجودِ سطلِ `attempt` است: «چند probe اجرا شد» به سؤالِ
    «چند کوکی سوخت» جواب نمی‌دهد.
    """
    await _stock(redis, monkeypatch, tmp_path, 3)
    ytdlp.fail()
    # پیش‌شرط را پین کن، وگرنه حلقه اصلاً نمی‌چرخد و «۳ تلاش» بی‌معناست.
    assert TD._is_cookie_error("ERROR: " + MSG_ROTATES, "youtube") is True

    await _run(redis, payload)

    c = await _counts(redis)
    engine_calls = len(ytdlp.calls())
    assert engine_calls > 1, "این تست فقط وقتی معنا دارد که حلقه واقعاً چرخیده باشد"
    assert c[PS.ATTEMPT] == engine_calls, "هر فراخوانِ موتور باید یک تلاش بشمارد"
    assert c[PS.FAIL] == 1, "ولی شکست یک بار شمرده می‌شود، نه به‌ازای هر تلاش"
    assert c[PS.MENU] == 0 and c[PS.BLOCKED] == 0
    assert await redis.exists(PS.menu_key(payload["ref"])) == 0, \
        "probeِ شکست‌خورده منو ندارد، پس نباید نشانگر بگذارد"


async def test_an_age_blocked_probe_is_not_counted_as_a_menu(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """**کنترلِ اصلی.** موفق ولی بی‌منو ⇒ `blocked`، هرگز `menu`.

    اگر این‌ها در سطلِ `menu` بیفتند، هر لینکِ سنی به‌عنوان «رهاشده» شمرده
    می‌شود — یعنی همان عددی که کلِ تصمیم رویش بناست غلط دربیاید.
    """
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.ok(age_limit=18)
    monkeypatch.setattr(TD.safety, "load_policy", _policy(enabled=True))

    await _run(redis, payload)

    c = await _counts(redis)
    assert c[PS.BLOCKED] == 1
    assert c[PS.MENU] == 0, "این جاب هرگز منو نمی‌بیند، پس نباید در مخرجِ رهاشدن باشد"
    assert await redis.exists(PS.menu_key(payload["ref"])) == 0, \
        "بدونِ منو نشانگری هم نباید باشد، وگرنه یک cancelِ بی‌ربط menucancel می‌شود"


async def test_a_too_long_probe_is_not_counted_as_a_menu(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """همان کنترل، شاخهٔ دوم — `dl_max_duration_min` هم قبل از منو رد می‌کند."""
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.ok(duration=99999)
    monkeypatch.setattr(TD.settings_store, "get_int", _get_int(dl_max_duration_min=1))

    await _run(redis, payload)

    c = await _counts(redis)
    assert c[PS.BLOCKED] == 1 and c[PS.MENU] == 0


async def test_the_text_menu_fallback_is_counted_too(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """بدونِ تامبنیل، منو از مسیرِ `_edit` می‌رود — همان‌قدر «منو»ست."""
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.ok(thumbnail=None)

    bot = await _run(redis, payload)

    assert (await _counts(redis))[PS.MENU] == 1
    assert not [n for n, _ in bot.sent if n == "send_photo"], "این مسیر عکسی نیست"


async def test_a_photo_menu_does_not_also_send_the_text_menu(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """کنترلِ بازآراییِ پرچمِ `sent`.

    شمارنده بیرونِ `try`ِ عکس نشست تا استثنایی از خودش منو را **دوبار** نفرستد.
    این تست همان را پین می‌کند: مسیرِ عکسیِ موفق دقیقاً یک منو می‌فرستد.
    """
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.ok()

    bot = await _run(redis, payload)

    # فیلترِ `reply_markup` لازم است: پیامِ «در حالِ بررسی…» هم یک
    # `edit_message_text` است و بدونِ آن این assert همیشه می‌افتد.
    menus = [n for n, p in bot.sent
             if n in ("send_photo", "edit_message_text") and p.get("reply_markup")]
    assert menus == ["send_photo"], f"انتظار فقط یک منوی عکسی، دیده شد: {menus}"
    assert (await _counts(redis))[PS.MENU] == 1


def test_the_day_key_agrees_with_the_rest_of_dlstat():
    """§۷ می‌گوید این سطل‌ها را کنارِ `dlstat:<platform>:*` بخوان — پس روزشان
    باید یکی باشد. سه کپیِ دست‌نویسِ `_today()` وجود دارد و هر سه باید UTC
    بمانند؛ اگر یکی به ساعتِ محلی بیفتد، مقایسه بی‌صدا یک روز جابه‌جا می‌شود.
    """
    from app.routers import download as RD
    assert PS._today() == TD._today() == RD._today()
    assert PS.key("menu").endswith(TD._today())


async def test_the_buckets_carry_the_same_two_day_ttl_as_dlstat(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """تلهٔ شمارندهٔ جاودان: `INCR` بدونِ `EXPIRE` کلیدی می‌سازد که هرگز نمی‌میرد."""
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.ok()

    await _run(redis, payload)

    for bucket in (PS.MENU, PS.ATTEMPT):
        ttl = await redis.ttl(PS.key(bucket))
        assert 0 < ttl <= PS.TTL, f"{bucket} باید TTL داشته باشد، دیده شد {ttl}"
    assert PS.TTL == 172800, "باید با پنجرهٔ بقیهٔ `dlstat:*` یکی بماند"


# ══ سمتِ روتر ═══════════════════════════════════════════════════════

def _cq(ref: str, sel: str, bot) -> CallbackQuery:
    """`CallbackQuery`ِ **واقعیِ** aiogram، نه داکلی که `.data` را اعلام کند."""
    msg = Message(message_id=9, date=datetime.now(timezone.utc),
                  chat=Chat(id=4242, type="private"), text="menu").as_(bot)
    return CallbackQuery(id="cb1", from_user=TgUser(id=42, is_bot=False, first_name="u"),
                         chat_instance="ci", data=f"dl:{ref}:{sel}", message=msg).as_(bot)


async def _pick(redis, ref: str, sel: str = "720", bot=None):
    bot = bot or FakeBot()
    await on_dl_pick(_cq(ref, sel, bot), Dl(ref=ref, sel=sel), "fa",
                     redis, None, None)
    return bot


async def test_a_pick_is_counted_once_and_the_second_is_a_repick(redis):
    """یک منو می‌تواند چند pick بدهد — بدونِ dedupe تفاضل منفی می‌شود."""
    await PS.mark_menu(redis, "r1")

    await _pick(redis, "r1")
    await _pick(redis, "r1")

    c = await _counts(redis)
    assert c[PS.PICK] == 1, "منو یک بار «مصرف» می‌شود"
    assert c[PS.REPICK] == 1, "و بارِ دوم باید دیده شود، نه اینکه گم شود"


async def test_a_pick_is_counted_even_when_the_menu_context_expired(redis):
    """`dlctx` منقضی است، ولی کاربر **دکمه را زده** — این رهاشدن نیست.

    اگر شمارنده بعد از گاردِ `dlctx` می‌نشست، این مسیر به «رهاشده» نشت می‌کرد.
    """
    await PS.mark_menu(redis, "r2")
    assert await redis.exists("dlctx:r2") == 0, "پیش‌شرط: هیچ ctxی در کار نیست"

    bot = await _pick(redis, "r2")

    assert (await _counts(redis))[PS.PICK] == 1
    assert any(p.get("text") for n, p in bot.sent if n == "answer_callback_query"), \
        "و کاربر باید پیامِ انقضا را گرفته باشد — رفتار عوض نشده"


async def test_a_cancel_on_the_quality_menu_is_counted_separately(redis):
    """ردِ صریح، نه رهاشدن — وگرنه «رهاشده» تصمیمِ کاربر را هم می‌بلعد."""
    await PS.mark_menu(redis, "r3")

    await _pick(redis, "r3", sel="cancel")

    c = await _counts(redis)
    assert c[PS.MENU_CANCEL] == 1
    assert c[PS.PICK] == 0 and c[PS.REPICK] == 0


async def test_a_cancel_of_a_running_download_is_not_counted(redis):
    """**کنترلِ ابهامِ cancel.**

    `download_cancel_kb` همان `Dl(sel="cancel")` را می‌سازد که منوی کیفیت. تنها
    چیزی که تفکیکشان می‌کند نبودِ نشانگر است: مسیرِ quick هرگز نشانگر نمی‌سازد.
    """
    await _pick(redis, "rq", sel="cancel")

    c = await _counts(redis)
    assert c[PS.MENU_CANCEL] == 0, "لغوِ یک دانلودِ در حالِ اجرا ربطی به probe ندارد"
    assert sum(c.values()) == 0, "این مسیر نباید هیچ سطلی را تکان دهد"


async def test_a_cancel_after_a_pick_is_not_double_counted(redis):
    """نشانگر سرِ pick مصرف شده، پس cancelِ بعدی دوباره شمرده نمی‌شود."""
    await PS.mark_menu(redis, "r4")

    await _pick(redis, "r4")
    await _pick(redis, "r4", sel="cancel")

    c = await _counts(redis)
    assert (c[PS.PICK], c[PS.MENU_CANCEL]) == (1, 0)


# ══ فرمول، انتها به انتها ═══════════════════════════════════════════

async def test_the_abandonment_formula_holds_end_to_end(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """دو منو، یکی pick می‌شود و یکی رها — فرمول باید دقیقاً ۱ بدهد."""
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.ok()

    await _run(redis, payload)                       # منوی ۱
    await _pick(redis, payload["ref"])               # …و pick شد
    await _run(redis, {**payload, "ref": "prb00002"})  # منوی ۲ — رها

    c = await _counts(redis)
    abandoned = c[PS.MENU] - c[PS.PICK] - c[PS.MENU_CANCEL]
    assert (c[PS.MENU], c[PS.PICK]) == (2, 1)
    assert abandoned == 1


# ══ تریپ‌وایرِ «فقط اندازه‌گیری» ════════════════════════════════════

async def test_the_probe_phase_still_costs_exactly_what_it_did(
        ytdlp, payload, redis, tmp_path, monkeypatch):
    """قیدِ صریحِ این کار: **صفر تغییرِ رفتاری**.

    چهار هزینهٔ ثبت‌شدهٔ فازِ probe عمداً دست‌نخورده‌اند — رفعشان بعد از دیدنِ
    داده تصمیم می‌شود، نه سوارِ PRِ اندازه‌گیری. این تست هر چهار را پین می‌کند،
    پس «کمکِ» بعدی مجبور است تصمیم را صریح بگیرد نه بی‌صدا.
    """
    await _stock(redis, monkeypatch, tmp_path, 1)
    ytdlp.ok()

    await _run(redis, payload)

    # ۱) کوکی خرج شد ولی در سطلِ ساعتی شمرده نشد (`note_spend` صدا زده نمی‌شود)
    assert ytdlp.calls() and ytdlp.calls()[0], "probe واقعاً با کوکی رفت"
    assert not [k async for k in redis.scan_iter(match=ck._CK_USE + "*")], \
        "note_spend هنوز صدا زده نمی‌شود — این رفع نشده و نباید بی‌صدا رفع شود"
    # ۲) از سقفِ هم‌زمانی رد شد
    assert await dl_active.count(redis) == 0, "dl_active هنوز شامل probe نیست"
    # ۳) از `_charge` رد شد — همان حفرهٔ سهمیه
    assert await redis.exists(f"dlq:cnt:{payload['tg_user_id']}:{TD._today()}") == 0
    assert await redis.exists(f"dlq:cd:{payload['tg_user_id']}") == 0
    # ۴) و تنها کلیدهای تازه مالِ خودِ اندازه‌گیری‌اند
    new = [k async for k in redis.scan_iter(match="dlstat:probe:*")]
    assert new, "شمارنده باید واقعاً نوشته باشد وگرنه سه ادعای بالا توخالی‌اند"


async def test_a_pick_still_charges_and_enqueues(redis, monkeypatch):
    """نیمهٔ دومِ همان تریپ‌وایر، از **مسیرِ کامل**: ctxِ زنده تا enqueue.

    تست‌های بالا عمداً روی مسیرِ منقضی می‌روند (فقط شمارنده را ادعا می‌کنند)؛
    این یکی تا ته می‌رود تا ثابت کند افزودنِ شمارنده نه `_charge` را جابه‌جا
    کرده نه جابِ fetch را.
    """
    jobs: list[dict] = []

    async def _enqueue(name, payload, **kw):
        jobs.append({"name": name, **payload})

    monkeypatch.setattr(redis, "enqueue_job", _enqueue, raising=False)
    monkeypatch.setattr(TD.settings_store, "get_bool", _get_bool(dl_cache_enabled=False))
    await redis.set("dlctx:r5", json.dumps(
        {"url": "https://youtu.be/abc", "platform": "youtube", "engine": "ytdlp",
         "owner_id": 1, "tg_user_id": 42}))
    await PS.mark_menu(redis, "r5")

    await _pick(redis, "r5", sel="720")

    assert (await _counts(redis))[PS.PICK] == 1
    assert await redis.exists(f"dlq:cnt:42:{TD._today()}") == 1, \
        "`_charge` نباید با افزودنِ شمارنده جابه‌جا شده باشد"
    assert [j["phase"] for j in jobs] == ["fetch"], "جابِ fetch باید مثلِ قبل صف شود"
    assert jobs[0]["selector"] == "720"


# ── کمکی‌های وصله ──────────────────────────────────────────────────
# `Policy`ِ **واقعی** ساخته می‌شود نه داکل: گیتِ بزرگسال از فیلدهای همین شیء
# می‌خواند، و داکلی که فیلدهایش را خودش اعلام کند همان تلهٔ `aiogram_double`
# است — تغییرِ شکلِ `Policy` باید این تست را بشکند، نه اینکه از کنارش رد شود.

def _policy(**over):
    async def _load():
        return TD.safety.Policy(**over)
    return _load


def _get_int(**over):
    real = TD.settings_store.get_int

    async def _wrapped(key, default=0):
        if key in over:
            return over[key]
        return await real(key, default)
    return _wrapped


def _get_bool(**over):
    real = TD.settings_store.get_bool

    async def _wrapped(key, default=False):
        if key in over:
            return over[key]
        return await real(key, default)
    return _wrapped
