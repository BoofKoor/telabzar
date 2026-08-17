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

    def __init__(self, client, redis, admin_web, admin_id: int) -> None:
        self.client = client
        self.redis = redis
        self.aw = admin_web
        self.admin_id = admin_id

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
        yield Panel(client, redis, admin_web, ADMIN_ID)
    finally:
        await client.close()
        await engine.dispose()
