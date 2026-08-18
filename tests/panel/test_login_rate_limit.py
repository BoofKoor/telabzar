"""محدودیتِ نرخِ مسیرِ لاگینِ پنل — رفتاری، روی سرورِ واقعی.

پورتِ پنل از اینترنت رسیدنی است، پس این تنها چیزی است که بینِ یک مهاجم و یک
کدِ ۶رقمی می‌ایستد. وضعِ **پیش از** رفع اندازه‌گیری شد نه حدس زده
(بلوکِ کامنتِ `_RL_WINDOW` در `app/admin_web.py`): محدودیت وجود **داشت** —
۵ درخواستِ کد در ۶۰۰ ثانیه و ۶ حدس در ۳۰۰ ثانیه — ولی `auth_request` شمارندهٔ
حدس را پاک می‌کرد، پس بودجهٔ واقعی **۳۰ حدس در ۶۰۰ ثانیه** بود.

سه ادعا در سه سطحِ **مستقل**، طبقِ «دفاع در عمق یعنی تست در عمق» (§۶): بودجهٔ
حدسِ per-code · گاردِ `admin_id_set` روی verify · سقفِ per-IP. هرکدام جایی
سنجیده می‌شود که **تنها همان** می‌تواند تصمیم بگیرد، وگرنه یک سابوتاژِ کاملاً
موفق «نگرفت» گزارش می‌شود چون لایهٔ دیگری پوششش داده.

**عددها عمداً لفظی‌اند، نه از روی ثابت‌های ماژول.** ارجاع به `_CODE_TRIES` تستی
می‌سازد که روی سورسِ پیش از رفع با `AttributeError` می‌افتد — و «این صفت وجود
ندارد» ادعای رفتاری نیست (§۷، درسِ `raising=False`). با عددِ لفظی، همان تست
روی سورسِ قدیم با **رفتارِ غلط** می‌افتد، که چیزی است که می‌خواهیم بسنجیم.

ساعت **مدل** شده است (fixtureِ `clock` در `conftest`), نه `sleep` و نه
پاک‌کردنِ دستیِ کلید.
"""
from __future__ import annotations

import unittest.mock as m

import pytest

#: بودجهٔ حدس به‌ازای هر کدِ صادرشده (پیش از رفع: ۶).
TRIES = 3
#: درخواستِ کد در هر پنجره، per-admin — **عمداً دست‌نخورده**.
REQ_PER_ADMIN = 5
#: درخواستِ کد در هر پنجره، per-IP.
REQ_PER_IP = 10
#: سقفِ verify در هر پنجره، per-IP — مشتق: ۱۰ درخواست × ۳ حدس.
VERIFY_PER_IP = 30
WINDOW = 600


@pytest.fixture
def sent_codes(panel):
    """`_send_code` را می‌گیرد و کدهای صادرشده را نگه می‌دارد (بدونِ شبکه)."""
    codes: list[str] = []

    async def fake_send(chat_id, code):
        codes.append(code)
        return True

    with m.patch.object(panel.aw, "_send_code", fake_send):
        yield codes


async def _req(panel, admin_id):
    return await panel.client.post("/auth/request", data={"admin_id": admin_id},
                                   allow_redirects=False)


async def _ver(panel, admin_id, code):
    return await panel.client.post("/auth/verify",
                                   data={"admin_id": admin_id, "code": code},
                                   allow_redirects=False)


def _consumed_a_guess(body: str) -> bool:
    """آیا این پاسخ یک حدس **خرج کرد**؟ — روی هر دو نسخهٔ سورس درست است.

    پیش از رفع: «کد نادرست» خرج می‌کرد و «تلاشِ زیاد» رد می‌شد بدونِ خرج.
    پس از رفع: «کد نادرست» خرج می‌کند و «کد سوخت» هم خرج می‌کند (آخرین حدس،
    که کد را هم می‌کشد). یک معیارِ واحد برای هر دو، وگرنه شمارش روی یکی از دو
    سورس بی‌معنا می‌شود.
    """
    return "کد نادرست" in body or "کد سوخت" in body


# ── کنترلِ منفیِ هارنس ────────────────────────────────────────────────────
async def test_the_clock_fixture_really_drives_redis_expiry(panel, clock):
    """کنترل — روی هر دو سورس سبز است، و باید باشد.

    بدونِ این، هر ادعای «در N ثانیه» در این فایل بی‌معناست: اگر ساعتِ تزریق‌شده
    به fakeredis وصل نباشد `advance` هیچ‌کاری نمی‌کند و تست‌های پنجره **به دلیلِ
    غلط** سبز می‌مانند — همان بنچِ مرده‌ای که §۶ می‌گوید سابوتاژ نمی‌گیردش.
    """
    await panel.redis.set("k", "v", ex=10)
    clock.advance(9)
    assert await panel.redis.get("k") == "v", "ساعت زودتر از موعد منقضی کرد"
    clock.advance(2)
    assert await panel.redis.get("k") is None, "انقضا روی ساعتِ مدل‌شده اجرا نشد"


# ── لایهٔ ۱: بودجهٔ حدس به **کد** بسته است، نه به اندپوینت ────────────────
async def test_the_guess_budget_per_issued_code_is_three(panel, clock, sent_codes):
    aid = str(panel.admin_id)
    await _req(panel, aid)
    for i in range(TRIES - 1):
        body = await (await _ver(panel, aid, f"{i:06d}")).text()
        assert "کد نادرست" in body, f"حدسِ {i} زودتر از موعد رد شد"
    body = await (await _ver(panel, aid, "999999")).text()
    assert "کد سوخت" in body, "حدسِ سوم باید آخرین باشد"
    assert await panel.redis.get(f"panelcode:{aid}") is None, "کد باید کشته می‌شد"


async def test_the_total_guesses_in_one_window_is_bounded(panel, clock, sent_codes):
    """ادعای سرخط: ۳۰ → ۱۵ حدس در هر پنجرهٔ ۶۰۰ ثانیه."""
    aid = str(panel.admin_id)
    total = 0
    for _ in range(40):
        if "درخواستِ زیاد" in await (await _req(panel, aid)).text():
            break
        for _ in range(20):
            body = await (await _ver(panel, aid, "000000")).text()
            if not _consumed_a_guess(body):
                break
            total += 1
            if "کد سوخت" in body:
                break
    assert total == REQ_PER_ADMIN * TRIES == 15, \
        f"بودجهٔ پنجره {total} حدس شد، انتظار ۱۵"


async def test_exhausting_the_guesses_leaves_a_fresh_code_working(
        panel, clock, sent_codes):
    """کنترل — روی هر دو سورس سبز است، و **باید** باشد.

    این ویژگی پیش از رفع هم برقرار بود (چون `auth_request` شمارنده را پاک
    می‌کرد) و رفع باید نگهش دارد: تنها به همین دلیل می‌شود سقفِ حدس را ۶ → ۳
    آورد. فرمِ بدیهی‌ترِ رفع («ریست را بردار») همین را می‌شکست و مسیرِ verify را
    برای ۳۰۰ ثانیه می‌بست — یعنی مهاجم با ۳ حدس ورودِ ادمینِ واقعی را می‌بست.

    ⚠ **دو مکانیزمِ مستقل این را برآورده می‌کنند** و همین را اولین اجرای دفترچهٔ
    سابوتاژ نشان داد، نه بازخوانی: ریستِ `paneltry` در `auth_request`، **و**
    پاک‌شدنِ همان کلید همراهِ کد وقتی بودجه تمام می‌شود. پس یک سابوتاژِ تک‌لایه
    این تست را **نمی‌اندازد** و «نگرفت» گزارش می‌شود بی‌آنکه تست ضعیف باشد
    (§۶). لایهٔ اول جدا در `test_a_fresh_code_starts_with_a_full_guess_budget`
    سنجیده می‌شود، و موردِ سابوتاژِ این تست **هر دو** را برمی‌دارد.
    """
    aid = str(panel.admin_id)
    await _req(panel, aid)
    for i in range(TRIES):
        await _ver(panel, aid, f"{i:06d}")

    await _req(panel, aid)                      # کدِ تازه، همان لحظه
    r = await _ver(panel, aid, sent_codes[-1])
    assert r.status == 302, f"ورود با کدِ تازه بلاک شد ({r.status})"
    assert panel.aw._COOKIE in r.cookies


async def test_a_fresh_code_starts_with_a_full_guess_budget(panel, clock, sent_codes):
    """لایهٔ ریست، **تنها جایی که فقط خودش تصمیم می‌گیرد**: مصرفِ *ناقص*.

    وقتی بودجه تمام شود، پاک‌شدنِ کد هم `paneltry` را می‌برد؛ پس اثرِ ریست فقط
    آن‌جا دیده می‌شود که کاربر ۱–۲ حدسِ اشتباه زده و بعد کدِ تازه خواسته. بدونِ
    ریست، کدِ تازه شمارندهٔ نیمه‌مصرفِ قبلی را به ارث می‌برد و زودتر می‌سوزد.
    """
    aid = str(panel.admin_id)
    await _req(panel, aid)
    for i in range(TRIES - 1):                  # مصرفِ ناقص، نه تمام
        await _ver(panel, aid, f"{i:06d}")

    await _req(panel, aid)                      # کدِ تازه
    for i in range(TRIES - 1):
        body = await (await _ver(panel, aid, f"{i:06d}")).text()
        assert "کد نادرست" in body, "کدِ تازه بودجهٔ کاملِ خودش را نگرفت"
    assert "کد سوخت" in await (await _ver(panel, aid, "999999")).text()


async def test_the_window_rolls_over_on_the_modelled_clock(panel, clock, sent_codes):
    """کنترل — سقفِ per-admin **عمداً** دست‌نخورده ماند، پس روی هر دو سورس سبز است.

    این عدد تنها اهرمی است که یک مهاجم علیهِ ادمینِ واقعی دارد (بودجه را
    بسوزان → ادمین کد نمی‌گیرد)، پس پایین‌آوردنش حاشیهٔ brute-force را با یک
    قفلِ ارزان‌ترِ ادمین عوض می‌کند. تست آن تصمیم را پین می‌کند.
    """
    aid = str(panel.admin_id)
    for _ in range(REQ_PER_ADMIN):
        await _req(panel, aid)
    assert "درخواستِ زیاد" in await (await _req(panel, aid)).text()

    clock.advance(WINDOW - 1)
    assert "درخواستِ زیاد" in await (await _req(panel, aid)).text(), \
        "پنجره زودتر از موعد باز شد"
    clock.advance(2)
    assert "درخواستِ زیاد" not in await (await _req(panel, aid)).text(), \
        "پنجره پس از گذشتنش باز نشد"


# ── لایهٔ ۲: گاردِ `admin_id_set` روی verify ───────────────────────────────
async def test_verify_rejects_an_id_that_is_not_an_admin(panel, clock):
    """پیش از رفع، verify فقط `isdigit()` را می‌سنجید — هر عددی کلید می‌ساخت."""
    r = await _ver(panel, "987654321", "000000")
    assert "نامعتبر" in await r.text()
    assert await panel.redis.keys("paneltry:*") == []


async def test_one_host_cannot_sweep_admin_ids(panel, clock):
    """اندازه‌گیریِ پیش از رفع: ۲۰۰ شناسه از یک IP → ۲۰۰ کلیدِ `paneltry:`.

    عمداً **زیرِ** سقفِ per-IP می‌ماند تا تنها گاردِ شناسه بتواند مسئول باشد —
    وگرنه ادعا را لایهٔ دیگری برآورده می‌کند و سابوتاژِ این لایه «نگرفت» می‌دهد.
    """
    for i in range(10):
        await _ver(panel, str(900000 + i), "000000")
    assert await panel.redis.keys("paneltry:*") == []


# ── لایهٔ ۳: سقفِ per-IP ──────────────────────────────────────────────────
async def test_the_per_ip_verify_ceiling_fires(panel, clock):
    """رفعِ لایهٔ ۱ بلاکِ اندپوینت را برداشت، پس حجمِ خامِ verify باید جایی بسته شود.

    پیش از رفع هیچ سقفی روی **مبدأ** نبود؛ آن‌جا این حلقه به پیامِ per-code
    می‌رسید، نه به پیامِ per-IP.
    """
    aid = str(panel.admin_id)
    for _ in range(VERIFY_PER_IP):
        body = await (await _ver(panel, aid, "000000")).text()
        assert "از این آدرس" not in body, "سقفِ IP زودتر از موعد بست"
    body = await (await _ver(panel, aid, "000000")).text()
    assert "از این آدرس" in body, "سقفِ per-IP روی verify شلیک نکرد"


async def test_the_per_ip_request_ceiling_fires(panel, clock, monkeypatch, sent_codes):
    """سقفِ IP روی `/auth/request` فقط با **چند** شناسهٔ ادمین دیده می‌شود.

    با یک شناسه، سقفِ per-admin (۵) زودتر می‌بندد و سقفِ IP (۱۰) هرگز شلیک
    نمی‌کند — یعنی تستی که یک شناسه بزند دربارهٔ چیزِ دیگری حرف می‌زند.
    """
    ids = [panel.admin_id, panel.admin_id + 1, panel.admin_id + 2]
    monkeypatch.setattr(panel.aw.settings, "admin_ids",
                        ",".join(str(i) for i in ids))
    for i in range(REQ_PER_IP):
        body = await (await _req(panel, str(ids[i % len(ids)]))).text()
        assert "از این آدرس" not in body, "سقفِ IP زودتر از موعد بست"
    body = await (await _req(panel, str(ids[0]))).text()
    assert "از این آدرس" in body, "سقفِ per-IP روی درخواستِ کد شلیک نکرد"


# ── خودِ سقف: نباید با یک خطای Redis برای همیشه قفل شود ───────────────────
async def test_the_limiter_repairs_a_counter_that_lost_its_ttl(panel, clock):
    """واحد، روی خودِ هلپر — پس روی سورسِ پیش از رفع اصلاً وجود ندارد.

    غیرِتوخالی‌بودنش از سابوتاژ می‌آید نه از اجرای pre-fix. ادعا: `INCR` و
    `EXPIRE` دو فرمانِ جدا هستند و اگر پروسه بینشان بمیرد کلید بی‌انقضا می‌ماند
    و شمارنده تا ابد بالا می‌رود — قفلِ دائمیِ ورود که خودش ترمیم نمی‌شود (همان
    شکستی که §۷ برای `dl:active` ثبت کرده). فرمِ `if n == 1` تنها روی اولین
    فراخوان `expire` می‌زند، پس دقیقاً همان کلید را برای همیشه رها می‌کند.
    """
    key = "panelip:req:127.0.0.1"
    await panel.redis.incr(key)                  # کلیدِ بی‌TTL، مثلِ مرگِ وسطِ راه
    assert await panel.redis.ttl(key) == -1

    assert await panel.aw._rate_limit(panel.redis, key, 10, WINDOW) is True
    assert await panel.redis.ttl(key) > 0, "TTLِ گم‌شده ترمیم نشد"


# ── ورودیِ بدشکل: «نادرست»، نه ۵۰۰ ───────────────────────────────────────
async def test_a_persian_digit_code_is_wrong_not_a_crash(panel, clock, sent_codes):
    """گاردِ رگرسیون روی **خودِ رفع**، نه یک نقصِ پیش از آن.

    `'۱۲۳۴۵۶'.isdigit()` صادق است و `secrets.compare_digest` روی strِ غیرASCII
    `TypeError` می‌دهد (هر دو اجراشده) — پس مقایسهٔ زمان‌ثابت باید روی **بایت**
    باشد. فرمِ رشته‌ای این ورودی را به ۵۰۰ تبدیل می‌کرد، در حالی که `!=`ِ قدیمی
    درست «کد نادرست» می‌داد.
    """
    aid = str(panel.admin_id)
    await _req(panel, aid)
    r = await _ver(panel, aid, "۱۲۳۴۵۶")
    assert r.status == 200
    assert "کد نادرست" in await r.text()


async def test_an_over_long_admin_id_is_rejected_not_a_crash(panel, clock):
    """`int()` روی رشتهٔ بالای ۴۳۰۰ رقم `ValueError` می‌دهد (اجراشده)، و
    `str.isdigit()` طول را رد نمی‌کند — پس این ورودی پیش از رفع ۵۰۰ می‌گرفت."""
    r = await _req(panel, "9" * 5000)
    assert r.status == 200
    assert "نامعتبر" in await r.text()


# ── کنترل: مسیرِ سالم نباید بسته شود ──────────────────────────────────────
async def test_a_correct_code_still_logs_in(panel, clock, sent_codes):
    aid = str(panel.admin_id)
    await _req(panel, aid)
    r = await _ver(panel, aid, sent_codes[-1])
    assert r.status == 302
    assert panel.aw._COOKIE in r.cookies


async def test_a_used_code_cannot_be_replayed(panel, clock, sent_codes):
    aid = str(panel.admin_id)
    await _req(panel, aid)
    assert (await _ver(panel, aid, sent_codes[-1])).status == 302
    r = await _ver(panel, aid, sent_codes[-1])
    assert r.status == 200, "کدِ مصرف‌شده دوباره پذیرفته شد"
