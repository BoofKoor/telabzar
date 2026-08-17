"""فروشگاهِ تنظیماتِ زمانِ‌اجرا (admin-lite).

منبعِ زنده = **Redis** (همهٔ پروسه‌ها — bot و download-worker و … — ازش می‌خوانند،
پس تغییرِ ادمین فوراً و به‌شکلِ بین‌پروسه‌ای دیده می‌شود). منبعِ ماندگار = **Postgres**.
`env` (config.Settings) پیش‌فرض است؛ کلیدِ ذخیره‌شده آن را override می‌کند.

چون read-through از Redis است (نه کشِ in-process با TTL)، مشکلِ «کهنه‌ماندنِ یک
پروسه تا انقضای TTL» پیش نمی‌آید: نوشتنِ ادمین بلافاصله در Redis می‌نشیند و هر
خواننده در خواندنِ بعدی آن را می‌بیند.
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import Sessionmaker
from .models import Setting

log = logging.getLogger("telabzar.settings")

_PREFIX = "cfg:"
_MISSING = "\x00"  # نشانهٔ negative-cache: «در DB نیست → از پیش‌فرضِ env استفاده کن»

# کلیدهای قابلِ‌تنظیم از پنل → (نوع, پیش‌فرضِ env). مرجعِ /admin و اعتبارسنجی.
# همگام با docs/ADMIN_PANEL.md.
RUNTIME_KEYS: dict[str, tuple[str, object]] = {
    "rate_per_min": ("int", settings.rate_per_min),
    "daily_op_quota": ("int", settings.daily_op_quota),
    "whisper_model": ("str", settings.whisper_model),
    "max_file_mb": ("int", settings.max_file_mb),
    "video_encoder": ("str", settings.video_encoder),
    "compress_speed": ("str", settings.compress_speed),
    "compress_tiny_target_mb": ("int", settings.compress_tiny_target_mb),
    "compress_tiny_height": ("int", settings.compress_tiny_height),
    "vjoin_max_mb": ("int", settings.vjoin_max_mb),
    "stream_base": ("str", settings.stream_base),   # نودِ استریم: پایهٔ عمومیِ لینک‌ها
    "cookie_alert_min": ("int", settings.cookie_alert_min),  # آستانهٔ هشدارِ کوکی
    # ── سهمیه و سرعت‌گیرِ استخرِ سشن (app/cookies.py:Limits) ──
    "ck_cap_instagram": ("int", settings.ck_cap_instagram),
    "ck_cap_youtube": ("int", settings.ck_cap_youtube),
    "ck_cap_twitter": ("int", settings.ck_cap_twitter),
    "ck_cap_tiktok": ("int", settings.ck_cap_tiktok),
    "ck_cap_default": ("int", settings.ck_cap_default),
    "ck_min_gap_sec": ("int", settings.ck_min_gap_sec),
    "ck_warmup_days": ("int", settings.ck_warmup_days),
    "ck_warmup_pct": ("int", settings.ck_warmup_pct),
    "ck_cooldown_min": ("int", settings.ck_cooldown_min),
    "ck_rate_cooldown_min": ("int", settings.ck_rate_cooldown_min),
    "ck_invalid_at": ("int", settings.ck_invalid_at),
    # ── دانلودر ──
    "downloader_enabled": ("bool", settings.downloader_enabled),
    "dl_allow_unknown": ("bool", settings.dl_allow_unknown),
    "dl_rich_posts": ("bool", settings.dl_rich_posts),
    "dl_cache_enabled": ("bool", settings.dl_cache_enabled),
    "dl_cookie_when_needed": ("bool", settings.dl_cookie_when_needed),
    "dl_ig_anon_enabled": ("bool", settings.dl_ig_anon_enabled),
    "dl_pot_enabled": ("bool", settings.dl_pot_enabled),
    "proxy_url": ("str", settings.proxy_url),
    "dl_default_ux": ("str", settings.dl_default_ux),
    "dl_ux_youtube": ("str", ""),      # خالی = ارث از dl_default_ux
    "dl_ux_instagram": ("str", ""),
    "dl_ux_twitter": ("str", ""),
    "dl_ux_tiktok": ("str", ""),
    "dl_max_size_mb": ("int", settings.dl_max_size_mb),
    "dl_max_duration_min": ("int", settings.dl_max_duration_min),
    "dl_daily_count": ("int", settings.dl_daily_count),
    "dl_daily_mb": ("int", settings.dl_daily_mb),
    "dl_concurrency": ("int", settings.dl_concurrency),
    "dl_cooldown_sec": ("int", settings.dl_cooldown_sec),
    "dl_op_daily_min": ("int", settings.dl_op_daily_min),
    "dl_min_free_gb": ("int", settings.dl_min_free_gb),
    "dl_max_cookie_tries": ("int", settings.dl_max_cookie_tries),
    "dl_exit_cooldown_min": ("int", settings.dl_exit_cooldown_min),
    "dl_direct_enabled": ("bool", settings.dl_direct_enabled),
    "dl_direct_max_mb": ("int", settings.dl_direct_max_mb),
    "dl_direct_proxy": ("bool", settings.dl_direct_proxy),
    # ── فیلترِ محتوای بزرگسال (app/safety.py) ──
    "safety_enabled": ("bool", settings.safety_enabled),
    "safety_scan_pixels": ("bool", settings.safety_scan_pixels),
    "safety_threshold": ("int", settings.safety_threshold),
    "safety_video_frames": ("int", settings.safety_video_frames),
    "safety_notify_admin": ("bool", settings.safety_notify_admin),
    "safety_strikes": ("int", settings.safety_strikes),
    "safety_block_domains": ("str", ""),   # دامنه‌های اضافیِ ادمین
    "safety_allow_domains": ("str", ""),   # استثنا (رفعِ مثبتِ کاذب)
    "dl_sponsorblock": ("str", settings.dl_sponsorblock),
    "dl_subs": ("bool", settings.dl_subs),
    # ── پلتفرم‌های DRMدار (اسپاتیفای/اپل) ──
    "spotify_enabled": ("bool", settings.spotify_enabled),
    "spotify_client_id": ("str", settings.spotify_client_id),
    "spotify_client_secret": ("str", settings.spotify_client_secret),
    "apple_enabled": ("bool", settings.apple_enabled),
    # ── ماچر (مشترکِ هر پلتفرمی که هدفش را ما انتخاب می‌کنیم) ──
    # این پنج کلید تا امروز `spotify_*` نام داشتند و آن نام دیگر صادق نیست:
    # همین‌ها رفتارِ اپل را هم تعیین می‌کنند. مهاجرت خودکار است، ببین `_RENAMED`.
    "match_meta": ("bool", settings.match_meta),
    "match_max_tracks": ("int", settings.match_max_tracks),
    "match_source": ("str", settings.match_source),
    "match_min": ("int", settings.match_min),
    "match_yt_fallback": ("bool", settings.match_yt_fallback),
}

# نامِ قدیمیِ هر کلیدِ تغییرِنام‌داده. **fallback نیست، مهاجرت است** — و تفاوت
# مهم است: fallbackِ خالص یعنی پنل مقدارِ پیش‌فرض را نشان می‌دهد در حالی که
# مقدارِ مؤثر چیزِ دیگری است، و ذخیره از آن نمای غلط همان دادهٔ واقعی را پاک
# می‌کند (دقیقاً همان چیزی که `/buttons` یک‌بار کرد). پس اولین خواندن مقدار را
# زیرِ نامِ تازه می‌نویسد و نامِ قدیمی را حذف می‌کند؛ از آن به بعد مسیر عادی است.
#
# ⚠ **نقطهٔ حذفِ این نگاشت:** بعد از اینکه هر استقرارِ زنده‌ای یک‌بار با این کد
# بالا آمده باشد (یعنی دیگر هیچ ردیفِ `spotify_*`ی از این پنج‌تا در جدولِ
# `settings` نمانده)، این دیکشنری و شاخهٔ `get()` باید **حذف** شوند. تا وقتی
# این‌جاست، هر خواندنِ miss یک خواندنِ اضافه دارد. بدونِ نوشتنِ این نقطه، خودش
# می‌شد همان fallbackِ خاموشِ ماندگار.
_RENAMED: dict[str, str] = {
    "match_meta": "spotify_meta",
    "match_max_tracks": "spotify_max_tracks",
    "match_source": "spotify_source",
    "match_min": "spotify_match_min",
    "match_yt_fallback": "spotify_yt_fallback",
}

#: سقفِ آپلودِ سرورِ Bot APIِ محلی. **مشتق است، نه سلیقه**: `docs/telegram-api.md`
#: می‌گوید سرورِ خودمیزبان محدودیت را به «~۲۰۰۰ مگابایت» می‌برد، و کامنتِ خودِ
#: `config.py` روی `dl_max_size_mb` می‌نویسد «≤ سقفِ آپلودِ Bot API (فایلِ
#: بزرگ‌تر تحویل‌شدنی نیست)». پس هر کلیدی که **حجمِ یک فایلِ تحویل‌شدنی** را
#: توصیف می‌کند بالاتر از این عدد بی‌معناست: فایل ساخته می‌شود و بعد تحویل
#: نمی‌شود.
_UPLOAD_CEILING_MB = 2000

#: کرانِ مقادیرِ عددی: کلید → (کف, سقف)؛ `None` یعنی بی‌کران در آن جهت.
#:
#: **کف برای همهٔ کلیدهای `int` صفر است و این تنها بخشِ فراگیرِ ماجراست.** هیچ
#: مصرف‌کننده‌ای عددِ منفی را معنادار نمی‌داند؛ منفی صرفاً از فرم رد می‌شد و
#: بعد به شکلِ یک مقایسهٔ همیشه‌غلط ظاهر می‌شد (`max_file_mb = -1` یعنی هیچ
#: فایلی هرگز قبول نمی‌شود). صفر عمداً مجاز است، چون در این پروژه معنیِ
#: تثبیت‌شده‌ای دارد: «بی‌سقف/خاموش» — `ck_cap_*` (§۷: «سقفِ ۰ یعنی بی‌سقف»)،
#: `safety_strikes`، `dl_max_duration_min`، `ck_warmup_days`، و
#: `vjoin_max_mb` (کامنتِ `config.py`: «۰ = برگرد به max_file_mb»).
#:
#: **سقف فقط جایی که مشتق‌شدنی است.** برای بقیه عمداً چیزی ننوشته‌ام؛ عددی که
#: از هوا بیاید همان ثابتِ دستی‌ای است که §۷ بارها ثبت کرده می‌پوسد. یعنی
#: `safety_video_frames = 9999` هنوز پذیرفته می‌شود — احمقانه، ولی من کرانِ
#: قابلِ‌دفاعی برایش ندارم و ساختنِ یکی بدتر از نداشتنش است.
BOUNDS: dict[str, tuple[int, int | None]] = {
    # حجمِ فایل — سقف از سقفِ آپلودِ Bot API می‌آید (بالا).
    "max_file_mb": (0, _UPLOAD_CEILING_MB),
    "dl_max_size_mb": (0, _UPLOAD_CEILING_MB),
    "dl_direct_max_mb": (0, _UPLOAD_CEILING_MB),
    "vjoin_max_mb": (0, _UPLOAD_CEILING_MB),
    "compress_tiny_target_mb": (0, _UPLOAD_CEILING_MB),
    # درصد — واحدش را خودِ `config.py` اعلام کرده.
    "safety_threshold": (0, 100),      # «درصدِ اطمینانِ لازم برای مسدودی»
    "ck_warmup_pct": (0, 100),         # «سهمِ روزِ اول، درصدِ ظرفیت»
    # امتیازِ تطبیق — `config.py` بازه‌اش را «(۰..۱۰۰)» اعلام می‌کند. §۷ ثبت کرده
    # که امتیازِ برنده‌های واقعی به ۱۰۳ و ۱۰۶ هم می‌رسد (بونوسِ `art_track`)، پس
    # ۱۰۰ سقفِ **امتیاز** نیست؛ ولی سقفِ **آستانه** است: آستانهٔ ۱۰۰ از قبل یعنی
    # «فقط تطبیقِ تقریباً کامل»، و بین ۱۰۰ تا ۱۰۶ سیاستِ متفاوتی وجود ندارد.
    "match_min": (0, 100),
}

#: کلیدهایی با مقادیرِ مجازِ محدود (اعتبارسنجیِ /admin).
ENUM_VALUES: dict[str, tuple[str, ...]] = {
    "whisper_model": ("tiny", "base", "small", "medium", "large-v3"),
    "video_encoder": ("x264", "nvenc"),
    "compress_speed": ("fast", "balanced", "quality"),
    "dl_default_ux": ("probe", "quick"),
    "dl_ux_youtube": ("probe", "quick", ""),
    "dl_ux_instagram": ("probe", "quick", ""),
    "dl_ux_twitter": ("probe", "quick", ""),
    "dl_ux_tiktok": ("probe", "quick", ""),
    "match_source": ("ytmusic", "youtube"),
}


def validate_value(key: str, value: str) -> str | None:
    """پیامِ خطای فارسی اگر مقدار نامعتبر است، وگرنه `None`.

    **تنها مرجعِ اعتبارسنجیِ تنظیمات** — هم پنلِ وب و هم `/admin`ِ تلگرام از
    این‌جا می‌خوانند. این‌جا زندگی می‌کند نه در `admin_web`، چون `routers/admin`
    نمی‌تواند پنل را import کند (ایمیجِ ربات jinja2/cryptography ندارد) — همان
    قیدی که `cookies.py` و `dl_active.py` را سرِ جایشان نشانده. دو کپیِ
    دست‌نویس هم دقیقاً همان واگرایی‌ای می‌شد که این ممیزی پیدایش کرد.

    عددی‌بودن با `int()` سنجیده می‌شود نه `str.isdigit()`، چون `get_int()` در
    ادامه همان `int()` را می‌زند و **هر معیارِ دیگری یک شکافِ خاموش می‌سازد**:
    اندازه‌گیری‌شده، `"--5"` و `"⑦"` و `"²"` هر سه `isdigit()` را رد می‌کنند
    ولی `int()` رویشان می‌ترکد، پس مقدار ذخیره و در صفحه نشان داده می‌شد در
    حالی که سیستم روی پیش‌فرض کار می‌کرد — «تنظیم‌شده به‌نظر می‌رسد و نیست»،
    بدترین حالتِ همین خوشه. در جهتِ عکس، رقمِ **فارسی** (`۲۰۰۰`) هر دو را رد
    می‌کند و از قبل هم کار می‌کرد؛ این تابع رفتارش را عوض نمی‌کند.
    """
    if key not in RUNTIME_KEYS:
        return f"کلیدِ ناشناخته: {key}"
    kind = RUNTIME_KEYS[key][0]
    if kind == "int":
        try:
            n = int(value)
        except (TypeError, ValueError):
            return f"مقدارِ «{key}» باید عدد باشد (دریافت: «{value}»)."
        lo, hi = BOUNDS.get(key, (0, None))
        if n < lo:
            return f"مقدارِ «{key}» نمی‌تواند کمتر از {lo} باشد (دریافت: {n})."
        if hi is not None and n > hi:
            return f"مقدارِ «{key}» نمی‌تواند بیشتر از {hi} باشد (دریافت: {n})."
    elif kind == "bool":
        if value.strip().lower() not in ("0", "1", "true", "false", "yes", "no", "on", "off"):
            return f"مقدارِ «{key}» باید بولی باشد (on/off)."
    if key in ENUM_VALUES and value not in ENUM_VALUES[key]:
        allowed = " / ".join(v or "«خالی»" for v in ENUM_VALUES[key])
        return f"مقدارِ «{key}» باید یکی از این‌ها باشد: {allowed}"
    return None


class SettingsStore:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self.r = redis_client

    async def get(self, key: str) -> str | None:
        """override را برمی‌گرداند؛ None = تنظیم نشده (از پیش‌فرضِ env استفاده کن)."""
        try:
            cached = await self.r.get(_PREFIX + key)
        except Exception:  # noqa: BLE001  — Redis پایین؛ برگرد به DB
            cached = None
        if cached is not None:
            return None if cached == _MISSING else cached
        async with Sessionmaker() as s:
            row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        val = row.value if row is not None else None
        if val is None and key in _RENAMED:
            return await self._migrate_renamed(key)
        try:
            await self.r.set(_PREFIX + key, _MISSING if val is None else val)
        except Exception:  # noqa: BLE001  — کشِ Redis اختیاری است
            pass
        return val

    async def _migrate_renamed(self, key: str) -> str | None:
        """مقدارِ ذخیره‌شده زیرِ نامِ قدیمی را به نامِ تازه منتقل می‌کند (یک‌بار).

        روی `log.warning` می‌نشیند نه `info`: انتقالِ خاموش به مسیرِ دیگر همان
        الگویی است که پارسرِ اسپاتیفای را هفته‌ها مرده نگه داشت. اگر این خط را
        دیدی یعنی مهاجرت هنوز تمام نشده و `_RENAMED` هنوز حذف‌شدنی نیست.
        """
        old = _RENAMED[key]
        val = await self.get(old)                 # `old` در `_RENAMED` نیست → بی‌بازگشت
        if val is None:
            # **این‌جا عمداً negative-cache نوشته نمی‌شود.** پروسهٔ دیگری ممکن است
            # همین لحظه مهاجرت را تمام کرده و `cfg:<key>` را روی مقدارِ واقعی
            # گذاشته باشد؛ نوشتنِ `_MISSING` رویش آن مقدار را **بی‌صدا و ماندگار**
            # دفن می‌کند (کلیدِ منفی TTL ندارد) و ادمین بی‌آنکه بفهمد به پیش‌فرض
            # برمی‌گردد. هزینه‌اش یک `GET`ِ اضافهٔ Redis روی هر خواندنِ کلیدِ
            # تنظیم‌نشده است — که با حذفِ `_RENAMED` صفر می‌شود.
            return None
        log.warning("settings: migrating %r → %r (value %r). Remove the _RENAMED entry once "
                    "every deployment has started on this code.", old, key, val)
        try:
            await self.set(key, val)
            await self.reset(old)
        except Exception:  # noqa: BLE001  — پروسهٔ دیگری زودتر رسید؛ مقدار یکی است
            log.info("settings: %r was migrated concurrently by another process", key)
        return val

    async def set(self, key: str, value: str) -> None:
        """نوشتنِ override — **مقاوم در برابرِ رقابتِ INSERT**.

        «اول SELECT بعد INSERT» یک check-then-actِ کلاسیک است: دو پروسه که
        هم‌زمان یک کلیدِ **تازه** بنویسند، هر دو `row is None` می‌بینند و دومی با
        `UNIQUE constraint failed: settings.key` می‌ترکد. تا امروز عملاً بی‌خطر
        بود چون تنها نویسنده پنل بود (یک پروسه، نرخِ پایین) — ولی مهاجرتِ
        `_RENAMED` این را به مسیرِ **هر** پروسه سرِ اولین خواندن تبدیل کرد، و
        بعد از یک `telabzar update` همه با هم بالا می‌آیند. با اجرا بازتولید شد،
        نه با استدلال: دو `get_int` هم‌زمان → `IntegrityError`.

        **مسیرِ دوم یک `UPDATE`ِ مستقیم است، نه تکرارِ همان عملیات.** تعارض خودش
        ثابت می‌کند ردیف حالا هست، و `UPDATE` روی کلیدِ یکتا اصلاً نمی‌تواند
        تعارض بدهد — یعنی تلاشِ دوم **قطعی** است، نه وابسته به اینکه commitِ
        برنده پیش از SELECTِ ما رسیده باشد یا نه.

        **صداقتِ اندازه‌گیری:** روی DBِ فایل‌محور و ۲۰ اجرا به‌ازای هر حالت، «یک
        retry» هم ۲۰/۲۰ می‌شود؛ پس تفاوتِ این دو در این مقیاس **سنجیده‌نشدنی**
        است و انتخابِ `UPDATE` بر پایهٔ ساختار است نه عدد. آنچه عدد نشان می‌دهد
        خودِ باگ است: بی‌محافظت ۱/۲۰ در n=2 و ۰/۲۰ در n=8.
        (هشدار برای هر سنجشِ بعدی: روی `sqlite+aiosqlite:///:memory:` اصلاً
        رقابت مدل نمی‌شود — SQLAlchemy یک اتصالِ مشترک نگه می‌دارد — و اولین
        اندازه‌گیریِ همین رفع را گمراه کرد.)

        **فقط `IntegrityError` گرفته می‌شود** — `except Exception` این‌جا خطای
        واقعیِ دیتابیس (اتصال، قفل، اسکیما) را پنهان می‌کرد و نوشتنِ ازدست‌رفته را
        به سکوت تبدیل می‌کرد. مسیرِ دوم خودش هیچ چیزی نمی‌گیرد: اگر آن هم بشکند،
        خطای واقعی است و باید بالا برود.
        """
        try:
            async with Sessionmaker() as s:
                row = (await s.execute(
                    select(Setting).where(Setting.key == key))).scalar_one_or_none()
                if row is None:
                    s.add(Setting(key=key, value=value))
                else:
                    row.value = value
                await s.commit()
        except IntegrityError:
            log.info("settings: %r was created concurrently; writing it as an update", key)
            async with Sessionmaker() as s:
                await s.execute(sa_update(Setting).where(Setting.key == key).values(value=value))
                await s.commit()
        try:
            await self.r.set(_PREFIX + key, value)  # همهٔ پروسه‌ها فوراً می‌بینند
        except Exception:  # noqa: BLE001
            pass

    async def reset(self, key: str) -> None:
        async with Sessionmaker() as s:
            row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
        try:
            await self.r.set(_PREFIX + key, _MISSING)
        except Exception:  # noqa: BLE001
            pass

    async def all_overrides(self) -> dict[str, str]:
        async with Sessionmaker() as s:
            rows = (await s.execute(select(Setting))).scalars().all()
        return {r.key: r.value for r in rows}

    async def get_int(self, key: str, default: int) -> int:
        v = await self.get(key)
        if v is None:
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    async def get_str(self, key: str, default: str) -> str:
        v = await self.get(key)
        return default if v is None else v

    async def get_bool(self, key: str, default: bool) -> bool:
        v = await self.get(key)
        if v is None:
            return default
        return v.strip().lower() in ("1", "true", "yes", "on")


# ── singletonِ سطحِ پروسه (bot/worker یک‌بار init می‌کنند) ───────
_store: SettingsStore | None = None


def init_store(redis_url: str) -> SettingsStore:
    global _store
    if _store is None:
        _store = SettingsStore(aioredis.from_url(redis_url, decode_responses=True))
    return _store


def set_store(store: SettingsStore | None) -> None:
    """تزریقِ مستقیم (برای تست)."""
    global _store
    _store = store


def get_store() -> SettingsStore | None:
    return _store


# توابعِ راحتِ سطحِ‌ماژول: اگر store مقداردهی نشده، به پیش‌فرضِ env برمی‌گردند.
async def get_int(key: str, default: int) -> int:
    return await _store.get_int(key, default) if _store is not None else default


async def get_str(key: str, default: str) -> str:
    return await _store.get_str(key, default) if _store is not None else default


async def get_bool(key: str, default: bool) -> bool:
    return await _store.get_bool(key, default) if _store is not None else default
