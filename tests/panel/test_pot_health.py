"""سلامتِ pot-provider نباید صفحه را نگه دارد (C-3).

اندازه‌گیریِ سورسِ **پیش از** رفع، با سوکتی که accept می‌کند و هرگز جواب
نمی‌دهد — همان چیزی که ممیزی زد و این‌جا روی سورسِ فعلی بازتولید شد:

    `/` (داشبورد) → ۳۱۵۱ ms   ·   `/health` → ۳۰۲۳ ms   ·   بدونِ pot → ۲۱ ms

پس از رفع، همان سنجش: ۱۹۳ ms برای اولین بار (که تقریباً همه‌اش گرم‌شدنِ اولین
درخواست است — `/health` بلافاصله بعدش ۱۸ ms) و ۲۴ ms روی کشِ گرم.

**ادعای اصلی با زمان سنجیده نمی‌شود.** یک آستانهٔ زمانی روی رانرِ کند متزلزل
است، و بدتر: «سریع بود» می‌تواند یعنی «پروب اتفاقاً زود تمام شد». پس پروب با
چیزی عوض می‌شود که **هرگز** تمام نمی‌شود، و آن‌وقت «صفحه برگشت» تنها یک معنا
دارد: منتظرش نماند (§۶ — به بلاک‌کننده راهی برای تمام‌شدنِ خودبه‌خود نده).
یک تستِ ساعتیِ جدا با سوکتِ **واقعی** به‌عنوان لایهٔ دوم می‌ماند.
"""
from __future__ import annotations

import asyncio
import socket
import time
import unittest.mock as m

import pytest

POT_URL = "http://127.0.0.1:9/"          # ۹ = discard؛ هرگز صدا زده نمی‌شود


@pytest.fixture
def never_returns(panel, monkeypatch):
    """پروبی که تمام نمی‌شود، به‌علاوهٔ شمارندهٔ فراخوانی.

    `gate` برای تست‌هایی که می‌خواهند آزادش کنند؛ در غیرِ این صورت fixture خودش
    در پایان آزاد و پاکسازی می‌کند تا تسکِ پس‌زمینه از تست عمر بیشتری نکند.
    """
    calls: list[str] = []
    gate = asyncio.Event()

    async def probe(url: str) -> bool:
        calls.append(url)
        await gate.wait()
        return True

    monkeypatch.setattr(panel.aw.settings, "pot_provider_url", POT_URL)
    monkeypatch.setattr(panel.aw, "_pot_probe", probe)
    yield calls, gate
    gate.set()
    task = panel.client.app.get(panel.aw._POT_TASK)
    if task is not None and not task.done():
        task.cancel()


async def _get(panel, path):
    return await panel.client.get(path, cookies=panel.cookies, allow_redirects=False)


# ── ادعای اصلی: صفحه منتظرِ پروب نمی‌ماند ────────────────────────────────
@pytest.mark.parametrize("path", ["/", "/health"], ids=["dashboard", "health"])
async def test_the_page_never_waits_for_the_pot_probe(panel, never_returns, path):
    calls, _gate = never_returns
    r = await asyncio.wait_for(_get(panel, path), timeout=2)
    assert r.status == 200
    assert calls, "پروب اصلاً زمان‌بندی نشد — پس این تست چیزی را ثابت نمی‌کند"


# ── کش: مسیرِ درخواست باید صفر بایتِ شبکه داشته باشد ──────────────────────
async def test_a_fresh_cached_result_makes_no_probe_at_all(panel, never_returns):
    calls, _gate = never_returns
    await panel.redis.set(panel.aw._POT_LAST, "1")
    await panel.redis.set(panel.aw._POT_FRESH, "1", ex=30)
    r = await _get(panel, "/health")
    assert "آنلاین" in await r.text()
    assert calls == [], f"با کشِ تازه هم پروب زده شد: {calls}"


async def test_a_stale_cache_still_serves_the_last_known_value(panel, never_returns):
    """مسیرِ **خواندن**: با `last`ِ موجود و `fresh`ِ غایب، صفحه معطل نمی‌ماند."""
    calls, _gate = never_returns
    await panel.redis.set(panel.aw._POT_LAST, "1")      # `fresh` عمداً غایب
    r = await _get(panel, "/health")
    body = await r.text()
    assert "آنلاین" in body, "مقدارِ شناخته‌شده سرو نشد"
    assert calls, "تازه‌سازیِ پس‌زمینه زمان‌بندی نشد"


async def test_the_last_known_value_outlives_the_freshness_window(
        panel, clock, monkeypatch):
    """مسیرِ **نوشتن**: چرا دو کلید، نه یکی.

    تستِ بالا کش را دستی می‌کارد، پس دربارهٔ TTLِ نوشته‌شده هیچ نمی‌گوید — و
    سابوتاژ همین را نشان داد: وصله‌کردنِ مسیرِ نوشتن هیچ‌کدام را نمی‌انداخت.
    این‌جا از خودِ `_pot_refresh` رد می‌شود و ساعت را جلو می‌برد: اگر `last` هم
    TTL بگیرد، پنجرهٔ تازگی که بگذرد مقدارِ شناخته‌شده هم می‌رود و صفحه
    «نامعلوم» می‌شود.
    """
    monkeypatch.setattr(panel.aw.settings, "pot_provider_url", POT_URL)

    async def probe(url: str) -> bool:
        return True

    monkeypatch.setattr(panel.aw, "_pot_probe", probe)
    await panel.aw._pot_refresh(panel.client.app)

    clock.advance(panel.aw._POT_FRESH_TTL + 1)
    assert await panel.redis.get(panel.aw._POT_FRESH) is None, "پنجرهٔ تازگی نگذشت"
    assert await panel.redis.get(panel.aw._POT_LAST) == "1", \
        "مقدارِ شناخته‌شده همراهِ پنجرهٔ تازگی منقضی شد"
    assert "آنلاین" in await (await _get(panel, "/health")).text()


async def test_only_one_background_refresh_runs_at_a_time(panel, never_returns):
    """رفرشِ پیاپیِ صفحه نباید تسک روی تسک انباشته کند.

    درهم‌آمیزی **مجبور** شده است، نه امیدوارانه: پروب روی یک `Event` می‌ایستد،
    پس هر سه درخواست قطعاً هم‌زمان داخلِ آن‌اند (§۶).
    """
    calls, gate = never_returns
    for _ in range(3):
        await _get(panel, "/health")
    assert len(calls) == 1, f"{len(calls)} پروبِ هم‌زمان زمان‌بندی شد"
    gate.set()


# ── سه‌حالتی‌بودن: «نسنجیده» با «پیکربندی‌نشده» یکی نیست ──────────────────
async def test_a_configured_but_unprobed_provider_is_not_called_unconfigured(
        panel, never_returns):
    r = await _get(panel, "/health")
    body = await r.text()
    assert "در حالِ بررسی" in body
    assert "پیکربندی‌نشده" not in body


async def test_an_unset_provider_is_still_reported_as_unconfigured(panel, monkeypatch):
    """کنترل — روی هر دو سورس سبز است: حالتِ قدیمی نباید عوض شده باشد."""
    monkeypatch.setattr(panel.aw.settings, "pot_provider_url", "")
    body = await (await _get(panel, "/health")).text()
    assert "پیکربندی‌نشده" in body
    assert "در حالِ بررسی" not in body


# ── خودِ تازه‌سازی ────────────────────────────────────────────────────────
@pytest.mark.parametrize("ok,expected", [(True, "1"), (False, "0")],
                         ids=["reachable", "hung-or-dead"])
async def test_the_background_refresh_records_the_result(panel, monkeypatch, ok, expected):
    monkeypatch.setattr(panel.aw.settings, "pot_provider_url", POT_URL)

    async def probe(url: str) -> bool:
        return ok

    monkeypatch.setattr(panel.aw, "_pot_probe", probe)
    await panel.aw._pot_refresh(panel.client.app)
    assert await panel.redis.get(panel.aw._POT_LAST) == expected
    assert await panel.redis.ttl(panel.aw._POT_FRESH) > 0


async def test_the_cleanup_hook_cancels_a_running_refresh(panel, never_returns):
    """تسکِ پس‌زمینه نباید از خودِ اپ عمر بیشتری کند.

    fixtureِ `panel` عمداً `on_cleanup` را خالی می‌کند (تا به Redisِ واقعی وصل
    نشود)، پس این مسیر در بقیهٔ تست‌ها اجرا نمی‌شود و باید صریح صدا زده شود.
    """
    _calls, _gate = never_returns
    await _get(panel, "/health")
    task = panel.client.app[panel.aw._POT_TASK]
    assert not task.done()

    await panel.aw._on_cleanup(panel.client.app)
    # `_on_cleanup` عمداً `await task` نمی‌زند: طبقِ §۷ انتظار روی تسکی که خودت
    # لغو کرده‌ای می‌تواند لغوِ **خودت** را ببلعد. پس تست باید خودش نوبت به حلقه
    # بدهد تا لغو واقعاً اجرا شود — بدونِ آن، تسک در حالتِ «cancelling» است نه
    # `cancelled`.
    #
    # **کران‌دار، و این را سابوتاژ یاد داد نه بازخوانی:** فرمِ اولِ این تست
    # `await task` بود، و وقتی سابوتاژ لغو را برداشت، تست به‌جای افتادن **هنگ
    # کرد** — پروب روی گِیتی می‌ایستد که تا teardown باز نمی‌شود، و teardown تا
    # تمام‌شدنِ بدنه اجرا نمی‌شود. یعنی همان چیزی که باید یک قرمزِ تمیز باشد به
    # یک jobِ گیرکرده تبدیل می‌شد — دقیقاً شکستی که `timeout-minutes` در CI
    # برایش گذاشته شد. یک تستِ هنگ‌کننده به‌اندازهٔ یک تستِ توخالی بد است.
    for _ in range(50):
        if task.done():
            break
        await asyncio.sleep(0.01)
    assert task.cancelled(), "تسکِ پس‌زمینه لغو نشد"


# ── لایهٔ دوم: سوکتِ واقعی، ساعتِ واقعی ───────────────────────────────────
async def test_a_really_hung_provider_does_not_slow_the_dashboard(panel, monkeypatch):
    """با سوکتی که accept می‌کند و جواب نمی‌دهد — همان شکلِ اندازه‌گیریِ ممیزی.

    **تنها تستی از این فایل که روی سورسِ پیش از رفع هم اجرا می‌شود**، چون به
    هیچ نامِ تازه‌ای دست نمی‌زند؛ بقیه `_pot_probe` را وصله می‌کنند و آن‌جا با
    `AttributeError` می‌افتند، که ادعای رفتاری نیست (§۷). پس ادعای سرخط این‌جا
    زندگی می‌کند و اندازه‌گیری‌شده: پیش از رفع ۳۰۱۲ ms، پس از رفع ~۲۰ ms.

    آستانه ۲ ثانیه است و هر دو طرفش حاشیهٔ بزرگ دارند: پیش از رفع کفِ سختِ ۳
    ثانیه است (تایم‌اوتِ خودِ پروب) و پس از رفع مسیرِ درخواست **صفر بایتِ
    شبکه** دارد. `wait_for` هم هست تا اگر روزی واقعاً هنگ کرد، تست سریع بیفتد
    نه اینکه سوییت را نگه دارد.
    """
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    host, port = srv.getsockname()
    monkeypatch.setattr(panel.aw.settings, "pot_provider_url", f"http://{host}:{port}")
    try:
        t0 = time.perf_counter()
        r = await asyncio.wait_for(_get(panel, "/health"), timeout=8)
        elapsed = time.perf_counter() - t0
        assert r.status == 200
        assert elapsed < 2, f"صفحه {elapsed*1000:.0f} ms منتظرِ pot ماند"
    finally:
        srv.close()
        task = panel.client.app.get(panel.aw._POT_TASK)
        if task is not None and not task.done():
            task.cancel()


# ── کنترل: بقیهٔ سلامت دست‌نخورده ─────────────────────────────────────────
async def test_the_rest_of_the_health_page_still_reports(panel, monkeypatch):
    monkeypatch.setattr(panel.aw.settings, "pot_provider_url", "")
    body = await (await _get(panel, "/health")).text()
    assert "Redis" in body and "Postgres" in body
