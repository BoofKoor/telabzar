"""فاز ۳ث — سه موردِ باقی‌ماندهٔ ممیزی.

* **۴** `pick()` به‌ازای هر اکانت چند رفت‌وبرگشتِ Redis می‌زد. روی مستر
  بی‌اهمیت است؛ روی نودِ دانلود هرکدام یک رفت‌وبرگشتِ WireGuard است و `pick()`
  داخلِ حلقهٔ چرخشِ کوکی صدا زده می‌شود، پس ضرب می‌شود.
* **۵** کشِ مدلِ whisper در ولوم بماند، وگرنه با هر `telabzar update` می‌رود.
* **۱۰** ردِ سنیِ اسپاتیفای علتِ اشتباه را نام می‌برد.

تستِ شمارش عمداً روی **رفتار** هم ادعا دارد، نه فقط تعداد: یک بهینه‌سازی که
انتخابِ اکانت را عوض کند از خودِ مشکل بدتر است.
"""
from __future__ import annotations

import pathlib
import tempfile
from collections import Counter

import fakeredis.aioredis as fr
import pytest
import pytest_asyncio

from app import cookies as ck

ROOT = pathlib.Path(__file__).resolve().parent.parent
NETSCAPE = ("# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\tvalue\n")


class CountingRedis(fr.FakeRedis):
    """Redisِ واقعیِ درون‌حافظه‌ای که فرمان‌هایش را می‌شمارد."""

    log: list[str] | None = None

    async def execute_command(self, *args, **kw):
        if CountingRedis.log is not None:
            CountingRedis.log.append(str(args[0]).upper())
        return await super().execute_command(*args, **kw)


@pytest_asyncio.fixture
async def pool(monkeypatch):
    """N اکانتِ اینستاگرام روی دیسکِ موقت + آینهٔ Redis.

    `cookies_dir` به `tmp` بسته می‌شود: با رشتهٔ خالی، `_save_cookie` مسیرِ
    **نسبی** می‌سازد و فایل‌ها در CWD (ریشهٔ ریپو یا دایرکتوریِ رانرِ CI) می‌ریزند.
    """
    r = CountingRedis(decode_responses=True)
    monkeypatch.setattr(ck.settings, "cookies_dir", tempfile.mkdtemp())

    async def _make(n: int) -> list[str]:
        names = [f"instagram-{i}.txt" for i in range(n)]
        for name in names:
            assert await ck._save_cookie(r, name, NETSCAPE) == ""
        return names

    r.make = _make          # type: ignore[attr-defined]
    yield r
    CountingRedis.log = None


async def _count(coro) -> tuple[int, dict, object]:
    CountingRedis.log = []
    got = await coro
    log, CountingRedis.log = CountingRedis.log, None
    return len(log), dict(Counter(log)), got


# ── مورد ۴: تعدادِ رفت‌وبرگشت باید ثابت بماند ─────────────────────────────
@pytest.mark.parametrize("n", [1, 4, 8])
async def test_pick_does_a_constant_number_of_round_trips(pool, n):
    """پیش از رفع: ۴N+۲ فرمان (۸ اکانت → ۳۴). حالا مستقل از N."""
    await pool.make(n)
    calls, kinds, got = await _count(ck.pick(pool, "instagram"))
    assert got is not None, "باید اکانتی برگردد وگرنه شمارش بی‌معناست"
    assert calls <= 8, f"{n} اکانت → {calls} فرمان {kinds} — هنوز per-account است"


async def test_the_round_trips_do_not_grow_with_the_pool(pool):
    """ادعای اصلی: از ۲ به ۸ اکانت، تعدادِ فرمان **نباید** زیاد شود.

    (نسخهٔ اولِ این تست هر دو بار ۸ اکانت می‌ساخت، یعنی ۸ را با ۸ مقایسه
    می‌کرد و بدیهی سبز بود — روی سورسِ پیش از رفع هم پاس می‌شد.)
    """
    await pool.make(2)
    small, kinds_s, _ = await _count(ck.pick(pool, "instagram"))
    await pool.make(8)                       # همان استخر، حالا بزرگ‌تر
    big, kinds_b, _ = await _count(ck.pick(pool, "instagram"))
    assert big == small, (
        f"با رشدِ استخر ۲→۸ تعداد عوض شد: {small} {kinds_s} → {big} {kinds_b}")


# ── مورد ۴: رفتارِ انتخاب نباید عوض شده باشد ─────────────────────────────
async def test_a_cooled_down_account_is_still_skipped(pool):
    """کول‌داون حالا از `TTL` می‌آید نه `EXISTS` — نباید چیزی از دست برود."""
    names = await pool.make(3)
    await pool.set(ck._CK_CD + names[1], "1", ex=600)
    seen = {await ck.pick(pool, "instagram") for _ in range(12)}
    assert names[1] not in seen, "اکانتِ در کول‌داون نباید انتخاب شود"
    assert seen - {None} == {names[0], names[2]}


async def test_the_panel_still_sees_the_remaining_cooldown(pool):
    """`accounts()` ثانیهٔ باقی‌مانده را می‌داد؛ پنل به آن وابسته است."""
    names = await pool.make(2)
    await pool.set(ck._CK_CD + names[0], "1", ex=450)
    rows = {a["name"]: a for a in await ck.accounts(pool, "instagram")}
    assert rows[names[0]]["status"] == ck.COOLDOWN
    assert 0 < rows[names[0]]["cooldown"] <= 450
    assert rows[names[1]]["cooldown"] == 0


async def test_the_hourly_cap_is_still_enforced(pool):
    """سرعت‌گیر باید دقیقاً مثلِ قبل کار کند (خواندنش دسته‌ای شده، نه منطقش)."""
    names = await pool.make(2)
    lim = ck.default_limits()
    cap = ck.hourly_cap("instagram", lim)
    assert cap > 0, "اینستاگرام باید سقف داشته باشد وگرنه تست بی‌معناست"
    for _ in range(cap + 1):
        await ck.note_spend(pool, names[0])
    seen = {await ck.pick(pool, "instagram") for _ in range(8)}
    assert names[0] not in seen, "اکانتِ پرمصرف نباید انتخاب شود"


async def test_a_disabled_or_frozen_account_is_still_skipped(pool):
    names = await pool.make(3)
    for name, flag in ((names[0], "disabled"), (names[1], "frozen")):
        meta = await ck.get_meta(pool, name)
        meta[flag] = True
        await ck.set_meta(pool, name, meta)
    seen = {await ck.pick(pool, "instagram") for _ in range(8)}
    assert seen - {None} == {names[2]}


async def test_exit_pinning_still_decides(pool):
    """اکانتِ پین‌شده به خروجیِ دیگر برداشته نمی‌شود؛ همان خروجی مقدم است."""
    names = await pool.make(2)
    for name, node in ((names[0], "nodeA"), (names[1], "nodeB")):
        meta = await ck.get_meta(pool, name)
        meta["node_id"] = node
        await ck.set_meta(pool, name, meta)
    assert await ck.pick(pool, "instagram", node_id="nodeA") == names[0]
    assert await ck.pick(pool, "instagram", node_id="nodeB") == names[1]


async def test_a_corrupt_counter_does_not_break_the_pick(pool):
    """نسخهٔ تکی (`usage`) کلِ خواندن را در try داشت، پس مقدارِ خراب فقط ۰ می‌داد.

    در مسیرِ دسته‌ای همان `int()` بیرونِ try می‌افتد و `pick()` را می‌ترکاند —
    یعنی یک بایتِ خراب در Redis کلِ دانلود را از کار می‌انداخت. جنسِ تفاوتی که
    با جابه‌جاکردنِ خواندن‌ها به‌راحتی جا می‌ماند.
    """
    names = await pool.make(2)
    await pool.set(ck._hour_key(names[0]), "not-a-number")
    await pool.set(ck._CK_LAST + names[1], "garbage")
    assert await ck.pick(pool, "instagram") in names


async def test_the_budget_math_is_sync_and_testable_without_redis():
    """مثلِ `Limits`: ریاضی sync می‌ماند تا بدونِ Redis سنجیده شود."""
    lim = ck.default_limits()
    meta = ck._blank_meta("instagram-x.txt")
    meta["added"] = 0                      # گرم‌شده، سقفِ کامل
    cap = ck.hourly_cap("instagram", lim)
    assert ck.over_budget(meta, cap, 0, 1_000_000, lim) is True
    assert ck.over_budget(meta, 0, 0, 1_000_000, lim) is False
    # فاصلهٔ حداقلی: تازه استفاده شده → رد
    assert ck.over_budget(meta, 0, 1_000_000, 1_000_000, lim) is True


# ── مورد ۵: کشِ مدل باید ولوم داشته باشد ─────────────────────────────────
def test_the_model_cache_survives_a_container_recreate():
    """بدونِ ولوم، مدلِ غیرِ`base` با هر `telabzar update` دوباره دانلود می‌شد."""
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "model-cache:/opt/models/hf" in compose, "کشِ مدل به ولوم وصل نیست"
    assert "\n  model-cache:\n" in compose, "ولومِ model-cache تعریف نشده"


def test_the_image_still_prefetches_the_default_model():
    """ولوم جای پیش‌کش را نمی‌گیرد: بارِ اول محتوای ایمیج داخلش کپی می‌شود."""
    df = (ROOT / "docker" / "worker.Dockerfile").read_text()
    assert "WhisperModel('base'" in df
    assert "HF_HOME=/opt/models/hf" in df


# ── پیش‌فرضی که فایل در CWD می‌نوشت ──────────────────────────────────────
def test_the_cookies_dir_default_is_absolute():
    """`os.path.join("", name)` مسیرِ نسبی می‌دهد و کوکی در CWD نوشته می‌شود."""
    from app.config import Settings
    default = Settings.model_fields["cookies_dir"].default
    assert default.startswith("/"), f"پیش‌فرضِ نسبی: {default!r}"


def test_the_example_env_does_not_re_arm_the_mine():
    """`COOKIES_DIR=` خالی در `.env.example` پیش‌فرضِ امن را باطل می‌کند.

    سنجیده شد: با `COOKIES_DIR=""` در محیط، pydantic همان رشتهٔ خالی را
    می‌گیرد — یعنی فایلی که هر استقرارِ تازه کپی می‌کند، مین را دوباره
    مسلح می‌کرد.
    """
    for line in (ROOT / ".env.example").read_text().splitlines():
        assert not line.strip().startswith("COOKIES_DIR="), \
            "COOKIES_DIR نباید در .env.example باشد (compose هر سرویس را ست می‌کند)"


def test_every_service_that_writes_cookies_has_the_shared_dir():
    """ربات هم کوکی می‌نویسد (پیستِ داخلِ تلگرام) — نه فقط پنل.

    کانتینرِ ربات نه `COOKIES_DIR` داشت نه ولومِ `/cookies`، پس آن پیست هرگز به
    پوشهٔ مشترک نمی‌رسید: با پیش‌فرضِ خالی در CWDِ کانتینر می‌افتاد و با پیش‌فرضِ
    تازه اصلاً «ذخیره نشد.» می‌داد. `list_names` هم وقتی روی دیسک فایلی هست
    شاخهٔ دیسک را برنده می‌کند، پس آینهٔ Redis آن را پنهان نمی‌کرد.
    """
    import yaml
    svcs = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    for name in ("bot", "admin"):                     # هر دو `_save_cookie` می‌زنند
        svc = svcs[name]
        assert svc.get("environment", {}).get("COOKIES_DIR") == "/cookies", \
            f"سرویسِ {name} کوکی می‌نویسد ولی COOKIES_DIR ندارد"
        assert any(str(v).startswith("./cookies:/cookies") for v in svc.get("volumes", [])), \
            f"سرویسِ {name} پوشهٔ مشترکِ کوکی را سوار نکرده"


# ── مورد ۱۰: ردِ سنیِ اسپاتیفای باید علتِ درست را نام ببرد ────────────────
async def _spotify(monkeypatch, tmp_path, outcomes: list[str]):
    """پلی‌لیستی به‌اندازهٔ `outcomes` می‌سازد و برای هر ترک نتیجهٔ خواسته‌شده را
    برمی‌گرداند: `age` (ردِ گیتِ سنی) · `fail` (شکستِ عادی) · `ok` (موفق).

    فقط دو تابعِ **بیرونی** جایگزین می‌شوند — resolveِ اسپاتیفای (شبکه) و
    `download_ytdlp` (زیرفرایند). خودِ حلقهٔ `download_matched` واقعی است، چون
    همان چیزی است که تست دربارهٔ آن ادعا دارد.
    """
    from app import downloader as D

    tracks = [{"title": f"t{i}", "artist": "a", "duration": 100} for i in range(len(outcomes))]

    async def _resolve(*a, **kw):
        return {"kind": "playlist", "title": "pl", "tracks": tracks}

    async def _cands(track, opts, source):
        return [{"url": "https://y/x", "title": track["title"], "duration": 100}]

    def _rank(cands, track):
        return [(99.0, cands[0])]

    calls = {"n": 0}

    async def _dl(target, tdir, sel, opts, progress=None, cancel=None):
        i = calls["n"]; calls["n"] += 1
        what = outcomes[i] if i < len(outcomes) else "fail"
        if what == "age":
            raise D.AgeRestricted("age_limit filter")
        if what == "fail":
            raise RuntimeError("bot check")
        path = tmp_path / f"o{i}.m4a"; path.write_bytes(b"audio")
        return str(path), {"duration": 100}, None

    monkeypatch.setattr(D, "spotify_resolve", _resolve)
    monkeypatch.setattr(D, "_gather_candidates", _cands)
    monkeypatch.setattr(D, "_rank_candidates", _rank)
    monkeypatch.setattr(D, "download_ytdlp", _dl)
    return D


async def test_an_all_age_restricted_playlist_says_so(monkeypatch, tmp_path):
    """قلبِ موردِ ۱۰: قبلاً «no YouTube match» می‌گرفت که علت را اشتباه می‌گفت."""
    D = await _spotify(monkeypatch, tmp_path, ["age", "age"])
    with pytest.raises(D.AgeRestricted):
        await D.download_matched("https://open.spotify.com/playlist/x", str(tmp_path), {})


async def test_a_mixed_playlist_still_delivers_the_rest_silently(monkeypatch, tmp_path):
    """رفتارِ عمدی و بدونِ تغییر: ترکِ سنی بی‌صدا می‌افتد، بقیه تحویل می‌شوند."""
    D = await _spotify(monkeypatch, tmp_path, ["age", "ok"])
    out = await D.download_matched("https://open.spotify.com/playlist/x", str(tmp_path), {})
    assert len(out) == 1, "ترکِ سالم باید تحویل شود"


async def test_a_mix_of_age_and_ordinary_failures_keeps_the_generic_message(
        monkeypatch, tmp_path):
    """شرط «همهٔ افتاده‌ها سنی بودند» است، نه «یکی سنی بود»."""
    D = await _spotify(monkeypatch, tmp_path, ["age", "fail"])
    with pytest.raises(RuntimeError) as ei:
        await D.download_matched("https://open.spotify.com/playlist/x", str(tmp_path), {})
    assert not isinstance(ei.value, D.AgeRestricted)
    assert "no YouTube match" in str(ei.value)
