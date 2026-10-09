"""چیدمانِ صفحهٔ تنظیماتِ پنل — بخش، زیربخش و برچسبِ دوزبانهٔ هر کلید.

جای این داده یک ماژولِ **خالص** است (بی‌دیتابیس، بی‌Redis، بی‌وابستگی به `admin_web`)
به همان دلیلی که `panel_i18n` و `langpack` خالص‌اند: تست‌های jobِ اصلی باید
بتوانند ببینندش، و `admin_web` سرِ import به `cryptography`/`jinja2` نیاز دارد که
در `requirements-dev.txt` نیستند. تا پیش از بازطراحیِ ۲۰۲۶-۱۰ همین داده
`admin_web.GROUPS` بود و سه تستِ اصلی آن را با AST از سورس بیرون می‌کشیدند؛ حالا
مستقیم import می‌شود.

**این فایل فقط «کجا و با چه برچسبی» را می‌گوید، نه «چه مقداری».** نوع و پیش‌فرض از
`settings_store.RUNTIME_KEYS` می‌آید و کرانِ عددی از `settings_store.BOUNDS` — یک
منبع برای هرکدام، تا این‌جا و اعتبارسنجیِ سرور نتوانند سرِ «حداکثر چند است» واگرا
شوند. تنها نوع‌هایی که این‌جا *اضافه* می‌شوند نمایشی‌اند: `enum` (فهرستِ گزینه با
برچسب)، `secret` (ورودیِ پنهان) و `list` (متنِ چندخطی).

کلیدی که در `RUNTIME_KEYS` باشد و این‌جا نه، گم نمی‌شود: صفحه آن را در بخشِ خودکارِ
«بدون دسته» نشان می‌دهد (`admin_web._settings_sections`) و همان مجموعه را `save()`
می‌خواند. تستِ `test_settings_key_coverage` هر دو جهت را می‌سنجد.

برچسب‌ها از نمونهٔ تأییدشدهٔ طراحی (۲۰۲۶-۱۰) آمده‌اند: کوتاه، با واحد کنارِ فیلد نه
داخلِ متن، و «۰ یعنی …» فقط جایی که صفر معنای خاص دارد.
"""
from __future__ import annotations

ZERO_OFF = ("۰ یعنی بدون سقف", "0 means no limit")


def _f(k, typ, l, h=None, **kw):
    """یک ردیفِ فرم. `l`/`h` جفتِ (فارسی, انگلیسی) است."""
    return {"k": k, "type": typ, "l": l, "h": h, **kw}


def _plat_ux(p):
    return _f(f"dl_ux_{p}", "enum", (None, None), None, plat=p, opts=(
        ("", ("مثل پیش‌فرض", "Same as default")),
        ("quick", ("دانلود فوری", "Download right away")),
        ("probe", ("منوی کیفیت", "Quality menu")),
    ))


SECTIONS: list[dict] = [
    {"id": "limits", "icon": "gauge", "tint": "t1", "t": ("محدودیت کاربران", "User limits"), "subs": [
        {"t": ("عملیات روی فایل", "File operations"), "f": [
            _f("rate_per_min", "int", ("درخواست در دقیقه", "Requests per minute"),
               ("برای هر کاربر · ۰ یعنی بدون سقف", "Per user · 0 means no limit")),
            _f("daily_op_quota", "int", ("سقف روزانه‌ی عملیات", "Daily operation limit"),
               ("برای هر کاربر · ۰ یعنی بدون سقف", "Per user · 0 means no limit")),
            _f("max_file_mb", "int", ("حداکثر حجم فایل برای عملیات", "Max file size for operations"),
               ("فایل بزرگ‌تر کارت می‌گیرد ولی عملیات روی آن اجرا نمی‌شود · ۰ یعنی بدون سقف",
                "Larger files still get a card, but no operation runs on them · 0 means no limit"), u="mb"),
        ]},
        {"t": ("دانلود", "Downloads"), "f": [
            _f("dl_daily_count", "int", ("تعداد دانلود در روز", "Downloads per day"),
               ("برای هر کاربر · ۰ یعنی بدون سقف", "Per user · 0 means no limit")),
            _f("dl_daily_mb", "int", ("حجم دانلود در روز", "Download volume per day"),
               ("برای هر کاربر · ۰ یعنی بدون سقف", "Per user · 0 means no limit"), u="mb"),
            _f("dl_cooldown_sec", "int", ("فاصله‌ی دو دانلود", "Gap between two downloads"),
               ("برای هر کاربر · ۰ یعنی بدون فاصله", "Per user · 0 means no gap"), u="sec"),
            _f("dl_max_duration_min", "int", ("حداکثر مدت ویدیو یا صوت", "Max media length"), ZERO_OFF, u="min"),
            _f("dl_op_daily_min", "int", ("پردازش روزانه‌ی رسانه‌ی دانلودی", "Daily processing of downloaded media"),
               ("فقط عملیات سنگین روی فایل دانلودی · ۰ یعنی بدون سقف",
                "Heavy operations on downloaded files only · 0 means no limit"), u="min"),
        ]},
    ]},
    {"id": "downloader", "icon": "download", "tint": "t3", "t": ("دانلودر", "Downloader"), "subs": [
        {"t": ("رفتار", "Behaviour"), "f": [
            _f("downloader_enabled", "bool", ("دانلودر روشن", "Downloader on"),
               ("خاموش یعنی ربات لینک را نمی‌پذیرد", "Off means links are not accepted")),
            _f("dl_allow_unknown", "bool", ("دانلود از هر سایتی", "Try any website"),
               ("لینک سایت‌های ناشناخته هم امتحان می‌شود", "Links from unknown sites are tried too")),
            _f("dl_rich_posts", "bool", ("پست چندعکسی به صورت مقاله", "Multi-photo posts as an article"),
               ("اگر نشد، آلبوم فرستاده می‌شود", "Falls back to an album")),
            _f("dl_cache_enabled", "bool", ("تحویل فوری لینک تکراری", "Instant delivery of repeated links"),
               ("لینکی که قبلاً دانلود شده بدون دانلود دوباره فرستاده می‌شود",
                "A link downloaded before is sent again without downloading")),
            _f("dl_cookie_when_needed", "bool", ("کوکی فقط در صورت نیاز", "Cookies only when needed"),
               ("اول بدون کوکی امتحان می‌شود تا اکانت‌ها کمتر مصرف شوند",
                "Tries without a cookie first so accounts last longer")),
            _f("dl_ig_anon_enabled", "bool", ("اینستاگرام اول بدون کوکی", "Instagram: try without a cookie first"),
               ("پست، ریلز و کاروسل؛ استوری و پروفایل همیشه کوکی لازم دارند",
                "Posts, reels and carousels; stories and profiles always need a cookie")),
            _f("dl_pot_enabled", "bool", ("توکن PO یوتیوب", "YouTube PO token"),
               ("اگر دانلود یوتیوب با خطای افزونه متوقف شد خاموشش کن",
                "Turn off if YouTube downloads crash in the plugin")),
        ]},
        {"t": ("خروجی", "Output"), "f": [
            _f("dl_sponsorblock", "str", ("حذف بخش‌های اسپانسر", "Remove sponsor segments"),
               ("دسته‌های SponsorBlock با کاما · خالی یعنی خاموش",
                "SponsorBlock categories, comma-separated · empty means off"), ltr=True, ph="sponsor,selfpromo"),
            _f("dl_subs", "bool", ("زیرنویس خودکار انگلیسی و فارسی", "Embed auto subtitles (en, fa)")),
        ]},
        {"t": ("ظرفیت", "Capacity"), "f": [
            _f("dl_concurrency", "int", ("دانلود هم‌زمان", "Concurrent downloads"),
               ("برای کل سیستم", "For the whole system")),
            _f("dl_max_size_mb", "int", ("حداکثر حجم دانلود", "Max download size"),
               ("حداکثر ۲۰۰۰؛ سقف ارسال تلگرام", "Up to 2000, Telegram’s upload limit"), u="mb"),
            _f("dl_min_free_gb", "int", ("حداقل فضای آزاد دیسک", "Minimum free disk space"),
               ("زیر این مقدار دانلود رد می‌شود · ۰ یعنی بدون شرط",
                "Below this, downloads are refused · 0 turns it off"), u="gb"),
        ]},
    ]},
    {"id": "direct", "icon": "link", "tint": "t6", "t": ("فایل مستقیم و پروکسی", "Direct files and proxy"), "subs": [
        {"f": [
            _f("dl_direct_enabled", "bool", ("دانلود فایل مستقیم", "Direct file downloads"),
               ("لینک فایل‌هایی که صفحه‌ی وب نیستند؛ مثل APK، PDF یا ریلیز گیت‌هاب",
                "Links that are not web pages: APK, PDF, GitHub releases")),
            _f("dl_direct_max_mb", "int", ("حداکثر حجم فایل مستقیم", "Max direct file size"),
               ("سقف کلی دانلود هم اعمال می‌شود", "The overall download limit still applies"), u="mb"),
            _f("dl_direct_proxy", "bool", ("فایل مستقیم از پروکسی", "Direct files through the proxy"),
               ("خاموش یعنی از IP خود سرور", "Off means from the server’s own IP")),
            _f("proxy_url", "str", ("پروکسی خروجی", "Outbound proxy"),
               ("خالی یعنی مستقیم از IP سرور", "Empty means straight from the server’s IP"),
               ltr=True, ph="socks5h://host:1080", check="url"),
        ]},
    ]},
    {"id": "quality", "icon": "list-checks", "tint": "t4", "t": ("منوی کیفیت", "Quality menu"), "subs": [
        {"f": [
            _f("dl_default_ux", "enum", ("رفتار پیش‌فرض لینک", "Default link behaviour"), None, opts=(
                ("quick", ("دانلود فوری با بهترین کیفیت", "Download right away, best quality")),
                ("probe", ("نمایش منوی کیفیت", "Show a quality menu")),
            )),
            _plat_ux("youtube"), _plat_ux("instagram"), _plat_ux("twitter"), _plat_ux("tiktok"),
        ]},
    ]},
    {"id": "music", "icon": "music", "tint": "t5", "t": ("اسپاتیفای و اپل موزیک", "Spotify and Apple Music"), "subs": [
        {"f": [
            _f("spotify_enabled", "bool", ("اسپاتیفای", "Spotify"),
               ("بدون کلید API هم کار می‌کند", "Works without an API key")),
            _f("spotify_client_id", "str", ("Client ID اسپاتیفای", "Spotify Client ID"),
               ("اختیاری", "Optional"), ltr=True),
            _f("spotify_client_secret", "secret", ("Client Secret اسپاتیفای", "Spotify Client Secret"),
               ("اختیاری", "Optional"), ltr=True),
            _f("apple_enabled", "bool", ("اپل موزیک", "Apple Music"),
               ("فقط لینک تک‌آهنگ", "Single-track links only")),
        ]},
        {"t": ("پیدا کردن آهنگ در یوتیوب", "Finding the track on YouTube"), "f": [
            _f("match_source", "enum", ("منبع جست‌وجو", "Search source"), None, opts=(
                ("ytmusic", ("YouTube Music (دقیق‌تر)", "YouTube Music (more accurate)")),
                ("youtube", ("یوتیوب", "YouTube")),
            )),
            _f("match_min", "int", ("حداقل امتیاز تطبیق", "Minimum match score"),
               ("۰ تا ۱۰۰ · بالاتر یعنی سخت‌گیرتر", "0–100 · higher is stricter")),
            _f("match_yt_fallback", "bool", ("بهترین نتیجه اگر تطبیق مطمئن نبود", "Use the best result when unsure"),
               ("خاموش یعنی آن آهنگ رد می‌شود", "Off skips that track")),
            _f("match_max_tracks", "int", ("حداکثر آهنگ در آلبوم یا پلی‌لیست", "Max tracks per album or playlist"),
               None, u="tracks"),
            _f("match_meta", "bool", ("اطلاعات آهنگ از اسپاتیفای یا اپل", "Track info from Spotify or Apple"),
               ("خاموش یعنی از یوتیوب", "Off takes it from YouTube")),
        ]},
    ]},
    {"id": "processing", "icon": "wand-sparkles", "tint": "t2", "t": ("پردازش فایل", "File processing"), "subs": [
        {"f": [
            _f("compress_speed", "enum", ("سرعت کاهش حجم", "Compression speed"),
               ("کندتر یعنی فایل کوچک‌تر", "Slower gives smaller files"), opts=(
                   ("fast", ("سریع", "Fast")), ("balanced", ("متعادل", "Balanced")),
                   ("quality", ("کیفیت بالا", "Best quality")),
               )),
            _f("video_encoder", "enum", ("انکودر ویدیو", "Video encoder"),
               ("NVENC فقط روی سرور دارای کارت گرافیک", "NVENC needs a GPU server"), opts=(
                   ("x264", ("x264 (پردازنده)", "x264 (CPU)")), ("nvenc", ("NVENC (کارت گرافیک)", "NVENC (GPU)")),
               )),
            _f("compress_tiny_target_mb", "int", ("حجم هدف «خیلی کم‌حجم»", "“Tiny” target size"),
               ("برای فیلم کلاس و جلسه", "For class and meeting recordings"), u="mb"),
            _f("compress_tiny_height", "int", ("رزولوشن «خیلی کم‌حجم»", "“Tiny” resolution"),
               ("۴۸۰ یا ۳۶۰", "480 or 360"), u="px"),
            _f("vjoin_max_mb", "int", ("سقف حجم چسباندن ویدیو", "Video join size limit"),
               ("۰ یعنی همان حداکثر حجم فایل", "0 means the max file size"), u="mb"),
            _f("whisper_model", "enum", ("مدل رونویسی", "Transcription model"),
               ("غیر از base، بار اول دانلود می‌شود", "Anything but base downloads on first use"), opts=(
                   ("tiny", ("tiny — سریع‌ترین", "tiny — fastest")), ("base", ("base — متعادل", "base — balanced")),
                   ("small", ("small", "small")), ("medium", ("medium", "medium")),
                   ("large-v3", ("large-v3 — دقیق‌ترین", "large-v3 — most accurate")),
               )),
        ]},
    ]},
    {"id": "pool", "icon": "cookie", "tint": "t2", "t": ("استخر کوکی", "Cookie pool"), "subs": [
        {"t": ("هشدار و چرخش", "Alerts and rotation"), "f": [
            _f("cookie_alert_min", "int", ("هشدار وقتی اکانت سالم کمتر از", "Alert when healthy accounts drop below"),
               ("پیام به ادمین در تلگرام · ۰ یعنی خاموش", "Telegram message to the admin · 0 turns it off"),
               u="accounts"),
            _f("dl_max_cookie_tries", "int", ("حداکثر اکانت در هر دانلود", "Max accounts tried per download"),
               ("۰ یعنی همه‌ی اکانت‌ها", "0 means all accounts"), u="accounts"),
            _f("dl_exit_cooldown_min", "int", ("کنار گذاشتن خروجی مسدود", "Bench a blocked exit for"),
               ("وقتی چند اکانت روی یک خروجی خطا بدهند", "When several accounts fail on the same exit"), u="min"),
        ]},
        {"t": ("سقف ساعتی هر اکانت", "Hourly limit per account"), "caps": True, "h": ZERO_OFF, "f": [
            _f("ck_cap_instagram", "int", ("اینستاگرام", "Instagram"), plat="instagram"),
            _f("ck_cap_youtube", "int", ("یوتیوب", "YouTube"), plat="youtube"),
            _f("ck_cap_twitter", "int", ("ایکس", "X"), plat="twitter"),
            _f("ck_cap_tiktok", "int", ("تیک‌تاک", "TikTok"), plat="tiktok"),
            _f("ck_cap_default", "int", ("سایر", "Others")),
        ]},
        {"t": ("فاصله و گرم‌کردن", "Pacing and warm-up"), "f": [
            _f("ck_min_gap_sec", "int", ("فاصله‌ی دو استفاده از یک اکانت", "Gap between two uses of an account"),
               ZERO_OFF, u="sec"),
            _f("ck_warmup_days", "int", ("گرم‌کردن اکانت تازه", "Warm-up for new accounts"),
               ("۰ یعنی بدون گرم‌کردن", "0 means no warm-up"), u="day"),
            _f("ck_warmup_pct", "int", ("ظرفیت روز اول", "First-day capacity"),
               ("بعد پله‌پله تا ۱۰۰٪", "Then rises step by step to 100%"), u="pct"),
        ]},
        {"t": ("خطا", "Failures"), "f": [
            _f("ck_cooldown_min", "int", ("استراحت بعد از خطا", "Rest after a failure"),
               ("هر خطای بعدی دو برابر، تا ۶ ساعت", "Doubles with each failure, up to 6 hours"), u="min"),
            _f("ck_rate_cooldown_min", "int", ("استراحت بعد از محدودیت نرخ", "Rest after a rate limit"),
               ("بدون جریمه برای اکانت", "No penalty for the account"), u="min"),
            _f("ck_invalid_at", "int", ("خطای پشت‌سرهم تا «باطل»", "Failures in a row before “invalid”")),
        ]},
    ]},
    {"id": "safety", "icon": "shield", "tint": "t5", "t": ("فیلتر محتوای بزرگسال", "Adult content filter"), "subs": [
        {"f": [
            _f("safety_enabled", "bool", ("فیلتر روشن", "Filter on"),
               ("برای لینک و فایل آپلودی", "For links and uploaded files")),
            _f("safety_scan_pixels", "bool", ("بررسی خود تصویر", "Scan the image itself"),
               ("خاموش یعنی فقط دامنه و اطلاعات متنی", "Off checks only the domain and text metadata")),
            _f("safety_threshold", "int", ("آستانه‌ی اطمینان", "Confidence threshold"),
               ("بالاتر یعنی سهل‌گیرتر", "Higher is more lenient"), u="pct"),
            _f("safety_video_frames", "int", ("فریم‌های بررسی در ویدیو", "Frames checked per video"),
               ("بیشتر یعنی دقیق‌تر و کندتر", "More is more accurate and slower"), u="frames"),
            _f("safety_notify_admin", "bool", ("گزارش هر مسدودی به ادمین", "Report every block to the admin")),
            _f("safety_strikes", "int", ("مسدودی خودکار کاربر بعد از", "Auto-block a user after"),
               ("۰ یعنی خاموش", "0 turns it off"), u="strikes"),
            _f("safety_block_domains", "list", ("دامنه‌های مسدود اضافه", "Extra blocked domains"),
               ("هر دامنه در یک خط", "One domain per line")),
            _f("safety_allow_domains", "list", ("دامنه‌های مجاز (استثنا)", "Allowed domains (exceptions)"),
               ("برای رفع مسدودی اشتباه", "To undo a false block")),
        ]},
    ]},
    {"id": "domain", "icon": "globe", "tint": "t6", "t": ("لینک و دامنه", "Links and domain"), "subs": [
        {"f": [
            _f("link_domain", "str", ("دامنه‌ی لینک دانلود و پخش", "Download and stream link domain"),
               ("رکورد A باید به IP همین سرور اشاره کند (کلودفلر: فقط DNS) · گواهی خودکار گرفته می‌شود · "
                "خالی یعنی دکمه‌ی لینک خاموش",
                "Its A record must point to this server (Cloudflare: DNS only) · the certificate is "
                "issued automatically · empty turns the link button off"),
               ltr=True, ph="dl.example.com", check="domain"),
            _f("stream_base", "str", ("پایه‌ی لینک روی نود استریم", "Link base on a gateway node"),
               ("فقط وقتی نود استریم آنلاین است", "Only used while a gateway node is online"),
               ltr=True, ph="https://cdn.example.com"),
            _f("dl_link_days", "int", ("عمر لینک عمومی", "Public link lifetime"),
               ("از آخرین درخواست لینک · ۰ یعنی بدون انقضا", "From the last link request · 0 means no expiry"),
               u="day"),
        ]},
    ]},
    {"id": "disk", "icon": "hard-drive", "tint": "t0", "t": ("فضای دیسک", "Disk space"), "subs": [
        {"f": [
            _f("tg_files_max_age_hours", "int", ("نگهداری فایل‌های گرفته‌شده از تلگرام", "Keep files fetched from Telegram for"),
               ("بعد از این مدت پاک و در صورت نیاز دوباره دانلود می‌شوند · ۰ یعنی خاموش",
                "They are removed after this and fetched again when needed · 0 turns it off"), u="hour"),
            _f("tg_files_min_free_gb", "int", ("حداقل فضای آزاد", "Minimum free space"),
               ("زیر این مقدار قدیمی‌ترین فایل‌ها زودتر پاک می‌شوند · ۰ یعنی خاموش",
                "Below this, the oldest files go first · 0 turns it off"), u="gb"),
        ]},
    ]},
]

#: واحدِ هر فیلد → کلیدِ `panel_i18n`.
UNITS = {"mb": "u.mb", "gb": "u.gb", "sec": "u.sec", "min": "u.min", "hour": "u.hour", "day": "u.day",
         "pct": "u.pct", "tracks": "u.tracks", "frames": "u.frames", "strikes": "u.strikes", "px": "u.px",
         "accounts": "u.accounts"}

#: نوع‌هایی که مقدارشان در لاگِ ادمین و در صفحه **نمایش داده نمی‌شود**.
SECRET_TYPES = ("secret",)


def fields() -> list[dict]:
    """همهٔ ردیف‌ها به ترتیبِ صفحه."""
    return [f for sec in SECTIONS for sub in sec["subs"] for f in sub["f"]]


def setting_keys() -> list[str]:
    """کلیدهای صفحه به ترتیب — همان چیزی که تست‌های ثبتِ کلید می‌پرسند."""
    return [f["k"] for f in fields()]


def field(key: str) -> dict | None:
    for f in fields():
        if f["k"] == key:
            return f
    return None
