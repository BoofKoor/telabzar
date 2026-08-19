"""هارنسِ تستِ رفتاریِ پنلِ ادمین.

این پوشه تنها جایی است که `app.admin_web` را **import** می‌کند، و به همین دلیل
تنها جایی است که `cryptography`/`jinja2` لازم دارد — یعنی `requirements-admin.txt`
که عمداً در `requirements-dev.txt` نیست. پس:

* `pytest.ini` با `addopts = --ignore=tests/panel` این پوشه را از اجرای پیش‌فرض
  بیرون می‌گذارد، تا `pytest`ِ خالی (محلی و jobِ اصلیِ CI) بدونِ استکِ پنل سبز
  بماند. مسیرِ **صریح** (`pytest tests/panel`) همچنان اجرایش می‌کند.
* jobِ `panel` در `.github/workflows/tests.yml` هر دو فایلِ requirements را نصب
  می‌کند و همین پوشه را می‌زند.
* `tests/test_repo_hygiene._ADMIN_ONLY` این مسیر را استثنا می‌کند — استثنا روی
  **پوشه** است نه فهرستِ فایل، پس تستِ تازه خودبه‌خود پوشش می‌گیرد.

**چرا env بازی درنمی‌آید و به‌جایش `Sessionmaker` وصله می‌شود.** هارنسِ ممیزیِ
فاز ۱ بیرون از `tests/` بود و می‌توانست `POSTGRES_DSN` را **پیش از** importِ
`app` ست کند. این‌جا نمی‌شود: `tests/conftest.py:17` از قبل `setdefault`ش کرده و
`app/db.py:53` موتور را **سرِ import** می‌سازد، پس تا وقتی تستِ ما اجرا شود
موتور به Postgres بسته شده. الگوی جاافتادهٔ ریپو
(`tests/test_settings_rename.py:36-40`) به‌جایش نامِ `Sessionmaker` را در خودِ
ماژول وصله می‌زند، و همان کار این‌جا انجام می‌شود.

فهرستِ ماژول‌ها **اندازه‌گیری شده** است، نه حدس: با importِ `app.admin_web` و
پیمایشِ `sys.modules` دقیقاً چهار ماژول نامِ `Sessionmaker` را نگه می‌دارند.
`_SESSIONMAKER_HOLDERS` همان‌هاست و `test_the_sessionmaker_holder_list_is_complete`
(در `tests/panel/test_panel_harness.py`) با همان پیمایش نگه‌داری‌اش می‌کند — پس
اگر ماژولِ پنجمی اضافه شود، تست می‌افتد نه اینکه بی‌صدا به Postgres وصل شود.

SQLite عمداً **فایل‌محور** روی `tmp_path` است، نه `:memory:` — طبقِ §۶، حالتِ
حافظه‌ای همهٔ سشن‌ها را روی یک اتصال multiplex می‌کند و هم‌زمانی را مدل نمی‌کند.
"""
from __future__ import annotations

import time as _real_time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

#: ماژول‌هایی که سرِ import نامِ `Sessionmaker` را به فضای نامِ خودشان می‌آورند.
#: اندازه‌گیری‌شده، نه دستی — تستِ همراهش همین را ثابت می‌کند.
_SESSIONMAKER_HOLDERS = ("app.db", "app.admin_web", "app.settings_store", "app.textstore")

#: شناسهٔ ادمینِ تست. `settings.admin_id_set` یک propertyِ **فقط‌خواندنی** است
#: (`app/config.py:181`) و مشتق از `admin_ids`، پس باید فیلدِ زیرین ست شود.
ADMIN_ID = 111


class Panel:
    """چیزی که یک تستِ پنل لازم دارد، در یک جا."""

    def __init__(self, client, redis, admin_web, admin_id: int, maker=None) -> None:
        self.client = client
        self.redis = redis
        self.aw = admin_web
        self.admin_id = admin_id
        #: sessionmakerِ همان SQLiteی که پنل به آن وصل شده — تا تستی که لازم
        #: دارد صفحه‌ای را با **داده** رندر کند بتواند ردیف بکارد. بدونِ این،
        #: هر ادعا دربارهٔ رندر روی صفحهٔ خالی گرفته می‌شود و توخالی است.
        self.maker = maker

    @property
    def cookies(self) -> dict[str, str]:
        """کوکیِ سشنِ یک ادمینِ لاگین‌شده (بدونِ طی‌کردنِ جریانِ کدِ تلگرام)."""
        return {self.aw._COOKIE: self.aw._make_session(self.admin_id)}

    def forged_cookies(self, secret: str) -> dict[str, str]:
        """کوکیِ ساخته‌شده از یک رازِ دلخواه — برای تست‌های مسیرِ سشن.

        عمداً `_make_session` را صدا **نمی‌زند**: آن تابع از `settings` می‌خواند،
        پس استفاده از آن یعنی سنجیدنِ کد با خودش. این‌جا مشتقِ کلید از صفر
        بازسازی می‌شود، همان کاری که یک مهاجمِ دارندهٔ راز می‌کند.
        """
        import base64
        import hashlib
        import json
        import time

        from cryptography.fernet import Fernet

        key = base64.urlsafe_b64encode(
            hashlib.sha256(f"telabzar-admin:{secret}".encode()).digest())
        payload = json.dumps({"id": self.admin_id, "t": int(time.time())}).encode()
        return {self.aw._COOKIE: Fernet(key).encrypt(payload).decode()}


class Clock:
    """ساعتِ کنترل‌پذیرِ fakeredis — یک پروکسیِ ماژولِ `time`.

    §۶ می‌گوید با fakeredis «شمارشِ فرمان معتبر است، زمان‌بندی نه»، و برای یک
    سقفِ نرخ این قید مستقیماً به کار می‌خورد: کلِ ادعا «چند تا در چند ثانیه» است،
    پس تستی که ساعت را مدل نکند یا باید `sleep` بزند (کُند و متزلزل) یا باید
    پنجره را با پاک‌کردنِ دستیِ کلید **تقلید** کند (یعنی همان چیزی را که می‌سنجد
    جعل کند).

    این‌جا هیچ‌کدام: `fakeredis._basefakesocket.time` عوض می‌شود، پس ریاضیِ
    انقضای **خودِ fakeredis** (`db.time = time.time()` و بعد
    `key.expireat - db.time`) روی ساعتِ ما می‌دود. TTL و انقضا واقعاً اجرا
    می‌شوند، فقط زمان را ما جلو می‌بریم. `test_the_clock_fixture_really_drives_
    redis_expiry` کنترلِ منفیِ همین است: بدونِ کارکردنِ این، هر ادعای پنجره‌ای
    بی‌معناست.

    فقط `time()` را می‌گیرد؛ بقیهٔ صفت‌ها (`sleep`, `monotonic`, …) به ماژولِ
    واقعی می‌روند، چون fakeredis برای فرمان‌های بلاک‌شونده از آن‌ها استفاده می‌کند.
    """

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __getattr__(self, name):
        return getattr(_real_time, name)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    """ساعتِ fakeredis را در دستِ تست می‌گذارد."""
    from fakeredis import _basefakesocket as bfs

    c = Clock()
    monkeypatch.setattr(bfs, "time", c)
    return c


@pytest.fixture
def sessionmaker_holders() -> tuple[str, ...]:
    """`_SESSIONMAKER_HOLDERS` برای تست‌ها — از راهِ fixture، نه importِ نسبی.

    `tests/panel/` عمداً package نیست (بدونِ `__init__.py`)، تا نامِ ماژولِ
    تست‌هایش با `tests/` بالادست تداخل نکند؛ پس `from .conftest import ...`
    کار نمی‌کند و مسیرِ درست همین است.
    """
    return _SESSIONMAKER_HOLDERS


@pytest.fixture
async def panel(tmp_path, monkeypatch):
    """پنلِ زنده: سرورِ واقعیِ aiohttp + fakeredis + SQLiteِ فایل‌محور."""
    import fakeredis.aioredis as fr
    from aiohttp.test_utils import TestClient, TestServer

    from app import admin_web, settings_store, textstore
    from app.db import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'panel.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import sys
    for name in _SESSIONMAKER_HOLDERS:
        monkeypatch.setattr(sys.modules[name], "Sessionmaker", maker)

    redis = fr.FakeRedis(decode_responses=True)
    monkeypatch.setattr(settings_store, "_store", settings_store.SettingsStore(redis))
    # `textstore` سه دیکشنریِ **سطحِ ماژول** دارد که بینِ تست‌ها زنده می‌مانند، در
    # حالی که DB برای هر تست تازه است. بدونِ خالی‌کردنشان، overrideی که تستِ قبلی
    # ساخته در تستِ بعدی «از قبل موجود» دیده می‌شود — یعنی پیش‌شرطِ یک تست را
    # تستِ همسایه‌اش تعیین می‌کند و ترتیبِ اجرا نتیجه را عوض می‌کند. با اجرا پیدا
    # شد نه با خواندن: دو تست جدا سبز بودند و کنارِ هم قرمز.
    for _name in ("_overrides", "_button_styles", "_menu_layout"):
        monkeypatch.setattr(textstore, _name, type(getattr(textstore, _name))())
    monkeypatch.setattr(textstore, "_loaded_ver", None, raising=False)

    monkeypatch.setattr(admin_web.settings, "admin_ids", str(ADMIN_ID))
    # نمایندهٔ یک استقرارِ **درست‌پیکربندی‌شده**. تا پیش از رفعِ A-1 این‌جا ست
    # نمی‌شد و در نتیجه هر تستِ پنل بی‌سروصدا روی همان fallbackِ `BOT_TOKEN`
    # می‌دوید که قرار است بسته شود — یعنی هارنس مسیرِ آسیب‌پذیر را تمرین
    # می‌کرد. تست‌هایی که خالی‌بودن را می‌خواهند خودشان monkeypatch می‌کنند.
    monkeypatch.setattr(admin_web.settings, "admin_secret", "t" * 64)
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir()
    monkeypatch.setattr(admin_web.settings, "cookies_dir", str(cookies_dir))
    # هلثِ پنل یک GETِ ۳ثانیه‌ای به pot-provider می‌زند؛ در تست خاموشش می‌کنیم
    # تا اجرا به شبکه وابسته نشود.
    monkeypatch.setattr(admin_web.settings, "pot_provider_url", "")

    app = admin_web.build_app()
    # startupِ واقعی به Redis و Postgresِ واقعی وصل می‌شود؛ جایش fake را تزریق کن.
    app.on_startup.clear()
    app.on_cleanup.clear()

    async def _inject(a):
        a["redis"] = redis

    app.on_startup.append(_inject)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield Panel(client, redis, admin_web, ADMIN_ID, maker)
    finally:
        await client.close()
        await engine.dispose()


#: هر هفت وضعیتی که `cookies.status_of` می‌تواند برگرداند — یعنی هر هفت شاخهٔ
#: رندرِ بج و نقطه. وضعیتِ **ناشناخته** این‌جا کاشتنی نیست (وضعیت از روی متا
#: محاسبه می‌شود، نه از نامِ فایل)، پس تستِ خودش `status_of` را وصله می‌زند.
_SEED_STATUSES = ("healthy", "suspect", "invalid", "cooldown", "disabled",
                  "frozen", "unproven")


@pytest.fixture
async def seeded(panel, tmp_path):
    """پنل، ولی با داده در **هر شاخهٔ** رندر.

    گاردِ کلاسِ CSS و برچسب‌های دامنه هر دو ادعایی دربارهٔ HTMLِ **رندرشده**
    دارند، و صفحهٔ خالی هیچ‌کدام را نمی‌سنجد: `/cookies`ِ بی‌اکانت هیچ بجی
    ندارد، `/stats`ِ بی‌جاب هیچ کارتِ کاراییی ندارد. پس این fixture عمداً
    پرمایه است — یک ردیف برای هر شاخه‌ای که تست‌ها به آن تکیه می‌کنند.
    """
    import time as _t
    from datetime import datetime, timedelta, timezone

    from app import cookies as ck
    from app.models import File, Job, Node, User

    now = datetime.now(timezone.utc)
    ts = int(_t.time())
    async with panel.maker() as s:
        blocked = User(tg_user_id=901, lang="fa", role="user", is_blocked=True)
        plain = User(tg_user_id=902, lang="en", role="user")
        s.add_all([blocked, plain])
        await s.flush()
        # فایل‌های «از لینک»: platform ست شده، و عمداً **هیچ ردیفِ Job**ی
        # ندارند — همان چیزی که کارت‌های jobs-محور نمی‌بینند.
        for i in range(4):
            s.add(File(owner_id=blocked.id, ref=f"dl{i}", file_unique_id=f"uq{i}",
                       file_id=f"fid{i}", name=f"clip{i}.mp4", kind="video",
                       size=10 ** 7, width=1920, height=1080, duration=61,
                       source="dl", platform="soundcloud", created_at=now))
        up = File(owner_id=blocked.id, ref="up0", file_unique_id="uqu", file_id="fidu",
                  name="track.mp3", kind="audio", size=10 ** 6, source="up", created_at=now)
        s.add(up)
        await s.flush()
        s.add(Job(file_id=up.id, op="compress", status="done", created_at=now,
                  finished_at=now + timedelta(seconds=3)))
        s.add(Job(file_id=up.id, op="convert", status="failed", error="ffmpeg exploded",
                  created_at=now, finished_at=now + timedelta(seconds=1)))
        s.add(Job(file_id=up.id, op="trim", status="queued", created_at=now))
        s.add(Node(id="n1", name="edge", role="download",
                   wg_ip="10.51.0.2", wg_pubkey="pubkey="))
        await s.commit()

    cdir = tmp_path / "cookies"
    for status in _SEED_STATUSES:
        fname = f"cookies_{status}.txt"
        (cdir / fname).write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        meta = {"platform": "instagram", "label": status, "added": ts - 86400 * 30,
                "last_ok": ts - 90, "fail_streak": 0, "disabled": False,
                "frozen": False, "last_error": "", "last_error_at": 0}
        if status == "invalid":
            meta["fail_streak"] = 99
        elif status == "suspect":
            meta["fail_streak"] = 1
        elif status == "frozen":
            meta["frozen"] = True
        elif status == "disabled":
            meta["disabled"] = True
        elif status == "unproven":
            meta["last_error"], meta["last_error_at"] = "redirect to login page", ts - 10
        await ck.set_meta(panel.redis, fname, meta)
        if status == "cooldown":
            await panel.redis.set(f"ckcd:{fname}", "1", ex=600)

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    await panel.redis.set(f"dlstat:soundcloud:ok:{day}", 1)
    await panel.redis.set(f"dlstat:soundcloud:fail:{day}", 2)
    await panel.redis.set("dlver:master",
                          '{"who":"master","gallery-dl":"1.29","yt-dlp":"2026.07.04"}')

    # عمقِ صف‌ها، با مقادیرِ عمداً **متمایز و سه‌رقمی**. یک عددِ تک‌رقمی در
    # صفحه‌ای که نرخ و نسخه و گیگابایتِ دیسک هم دارد ادعای ضعیفی می‌سازد: تستِ
    # «۲ در صفحه هست» می‌تواند به‌دلیلِ غلط سبز بماند. این چهارتا نه با هم جور
    # می‌شوند نه با چیزِ دیگری در همان صفحه، پس «این عدد رندر شد» واقعاً همان
    # را می‌گوید. صحتِ این انتخاب با سابوتاژ اثبات می‌شود نه با استدلال:
    # موردی که عدد را حذف کند باید تستِ متناظر را بیندازد.
    for key, n in (("arq:queue", 137), ("arq:queue:proc", 251),
                   ("arq:queue:dl", 149), ("arq:queue:dl:master", 260)):
        await panel.redis.zadd(key, {f"job{i}": float(i) for i in range(n)})
    # از مسیرِ خودِ `dl_active` — ساعتِ سرورِ Redis و همان هرس، نه zaddِ دستی.
    from app import dl_active
    for i in range(73):
        await dl_active.enter(panel.redis, f"live{i}")
    return panel
