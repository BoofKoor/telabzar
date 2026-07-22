"""پیکربندی از محیط (env / .env)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram
    bot_token: str
    default_lang: str = "fa"
    admin_ids: str = ""
    max_file_mb: int = 2000

    # سرورِ محلیِ Bot API (ربات با long-polling به آن وصل می‌شود)
    local_api_base: str = "http://local-bot-api:8081"

    # داده
    redis_url: str = "redis://redis:6379/0"
    postgres_dsn: str = (
        "postgresql+asyncpg://telabzar:telabzar@postgres:5432/telabzar"
    )

    # پردازش (ورکر)
    work_dir: str = "/work"
    # انکودِ ویدیو: x264 (پیش‌فرض، CPU) یا nvenc (اگر GPU + passthroughِ داکر داری —
    # بسیار سریع‌تر). مقدارِ نامعتبر/نبودِ سخت‌افزار → خودکار به x264 برمی‌گردد.
    # از پنلِ ادمین هم قابلِ تغییر است.
    video_encoder: str = "x264"
    # سرعت/کیفیتِ کاهشِ حجم (پریستِ ffmpeg): fast=veryfast · balanced=medium ·
    # quality=slow. کندتر = فایلِ کوچک‌تر ولی زمانِ بیشتر. از پنل قابلِ تغییر.
    compress_speed: str = "fast"

    # رونویسیِ صوت (faster-whisper) — اندازهٔ مدل: tiny/base/small/medium/large-v3.
    # پیش‌فرض base (تعادلِ RAM/دقت روی CPU). بعداً از پنلِ ادمین (M5) قابلِ تغییر
    # می‌شود — فهرستِ تنظیماتِ قابلِ‌مدیریت در docs/ADMIN_PANEL.md نگه‌داری می‌شود.
    whisper_model: str = "base"

    # امنیت
    clamav_host: str = "clamav"
    clamav_port: int = 3310

    # آرشیو (محدودیتِ استخراج — دفاعِ پایه در برابرِ bomb)
    max_extract_files: int = 40
    max_extract_mb: int = 500

    # کنترلِ سوءاستفاده (بات عمومی) — ۰ = نامحدود (خاموش).
    # فعلاً خاموش؛ بعداً از پنلِ ادمین (M5) مقداردهی می‌شود.
    daily_op_quota: int = 0
    rate_per_min: int = 0

    # لینک دانلود/استریم (سرویسِ gateway؛ فایل از دیسکِ local-bot-api سرو می‌شود)
    public_base: str = ""          # پایهٔ عمومی، مثل https://files.example.com
    gateway_port: int = 8080       # پورتِ داخلِ کانتینر (بدونِ نیاز به cap)
    tls_cert: str = ""             # مسیرِ سرتیفیکیتِ Origin کلودفلر (PEM)
    tls_key: str = ""              # مسیرِ کلیدِ خصوصیِ Origin (PEM)

    # دانلودرِ رسانه (لینک → دانلود → همان pipeline). همهٔ سقف‌ها از پنلِ ادمین
    # قابلِ‌تغییرند (settings_store)؛ مقادیرِ زیر پیش‌فرضِ env‌اند. ۰ = نامحدود.
    downloader_enabled: bool = True
    dl_allow_unknown: bool = True  # لینکِ هاستِ ناشناخته را هم با yt-dlp تلاش کن (از پنل خاموش‌شدنی)
    dl_rich_posts: bool = True     # پستِ چند‌عکسی را Rich Message بفرست (fallback: آلبوم)
    proxy_url: str = ""            # egressِ تمیزِ خودت، مثل socks5h://host:1080 (خالی = مستقیم)
    cookies_dir: str = ""          # پوشهٔ کوکی‌ها (چرخشِ اکانت برای اینستا/X)
    pot_provider_url: str = ""     # http://bgutil-pot-provider:4416 (توکنِ یوتیوب)
    dl_pot_enabled: bool = True    # استفاده از pot-provider؛ اگر پلاگین کرش کند از پنل خاموشش کن
    dl_default_ux: str = "quick"   # probe | quick — پیش‌فرضِ رفتارِ لینک
    dl_max_size_mb: int = 2000     # ≤ سقفِ آپلودِ Bot API (فایلِ بزرگ‌تر تحویل‌شدنی نیست)
    dl_max_duration_min: int = 0   # ردِ رسانهٔ خیلی بلند در probe
    dl_daily_count: int = 0        # سقفِ تعدادِ دانلودِ روزانهٔ هر کاربر
    dl_daily_mb: int = 0           # سقفِ حجمِ دانلودِ روزانهٔ هر کاربر
    dl_concurrency: int = 3        # حداکثر دانلودِ هم‌زمان (کلِ سیستم)
    dl_cooldown_sec: int = 0       # فاصلهٔ حداقلی بینِ دو دانلودِ هر کاربر
    dl_op_daily_min: int = 0       # سقفِ دقیقهٔ رسانهٔ دانلودی که هر کاربر می‌تواند «پردازش» کند
    dl_min_free_gb: int = 3        # اگر فضای آزادِ /work کمتر از این بود، دانلود را رد کن
    # فاز C — اکسترا/سختی‌سازی
    dl_sponsorblock: str = ""      # دسته‌های SponsorBlock برای حذف (مثل sponsor,selfpromo)؛ خالی=خاموش
    dl_subs: bool = False          # جاسازیِ زیرنویسِ خودکار (en+fa) در ویدیو
    cobalt_url: str = ""           # نمونهٔ self-hostedِ Cobalt به‌عنوان fallback؛ خالی=خاموش
    cobalt_api_key: str = ""       # کلیدِ API نمونهٔ Cobalt (در صورتِ نیاز)
    # ── اسپاتیفای (متادیتا از API + تطبیقِ صوت روی یوتیوب) ──
    spotify_enabled: bool = True       # پردازشِ لینکِ اسپاتیفای (نیازمندِ client id/secret)
    spotify_client_id: str = ""        # از پنل ست می‌شود (اپِ رایگانِ Spotify Developer)
    spotify_client_secret: str = ""    # از پنل ست می‌شود
    spotify_meta: bool = False         # خاموش=متادیتا از یوتیوب · روشن=متادیتا از اسپاتیفای
    spotify_max_tracks: int = 20       # سقفِ تعدادِ ترک در هر آلبوم/پلی‌لیست

    # پنلِ ادمینِ وب (فاز D) — سرویسِ جدا، احراز با کدِ تلگرام
    admin_port: int = 8080         # پورتِ داخلِ کانتینر (میزبان → 2083)
    admin_base: str = ""           # URL عمومیِ پنل (برای دستورِ /panel)؛ مثل https://panel.example.com:2083
    admin_secret: str = ""         # کلیدِ رمزِ سشن؛ خالی = از bot_token مشتق می‌شود

    @property
    def admin_id_set(self) -> set[int]:
        out: set[int] = set()
        for part in self.admin_ids.replace(" ", "").split(","):
            if part.isdigit():
                out.add(int(part))
        return out


settings = Settings()  # type: ignore[call-arg]
