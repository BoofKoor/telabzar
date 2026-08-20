"""پنلِ ادمینِ وب (فاز D) — aiohttp + Jinja2.

ورود: ادمین شناسهٔ عددی‌اش را می‌زند → کدِ ۶رقمی از ربات به تلگرامش می‌رود →
کد را وارد می‌کند → سشنِ رمزنگاری‌شده (کوکی). فقط `ADMIN_IDS`.
صفحه‌ها: تنظیمات · کوکی‌ها · سلامت. فونتِ Vazirmatn به‌صورتِ webfontِ
جاسازی‌شده (app/static/fonts) سرو می‌شود تا همه‌جا دقیقاً وزیرمتن باشد.
اجرا: python -m app.admin_web
"""
from __future__ import annotations

import asyncio
import contextvars
import base64
import glob
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import pathlib
import re
import secrets
import shutil
import ssl
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import aiohttp
import redis.asyncio as aioredis
from aiohttp import web
from cryptography.fernet import Fernet, InvalidToken
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from sqlalchemy import func, select, text as sql_text, true as sa_true

from . import cookies as ck_pool
from . import dl_active
from . import nodes as node_mod
from . import settings_store
from . import textstore
from .config import settings
from .db import Sessionmaker
from .downloader import KNOWN_PLATFORMS, PLATFORM_LABELS
from . import langpack
from .i18n import (
    BUILTIN_NAMES,
    DEFAULT as i18n_DEFAULT,
    available_languages as i18n_available_languages,
    default_text,
    t as _t,
)
from .keyboards import OPS_BY_KIND
from .models import DownloadCache, File, Job, Node, User
from .panel_i18n import DIR as _PANEL_DIR_OF
from .panel_i18n import LANGS as PANEL_LANGS
from .panel_glyphs import lcd as _lcd
from .panel_i18n import normalize_lang, normalize_theme, pt
from .settings_store import ENUM_VALUES, RUNTIME_KEYS

log = logging.getLogger("telabzar.admin")

_COOKIE = "tab_admin"
_SESSION_TTL = 8 * 3600
#: هر دو مسیر به **خودِ این فایل** لنگر می‌خورند و عمداً `..` ندارند: مسیرِ
#: نسبی‌به‌CWD یا `..`دار در تست (که از ریشهٔ ریپو می‌دود) resolve می‌شود و در
#: کانتینر نه — یعنی سبزیِ CI و ۵۰۰ روی تولید. `COPY app ./app` هر دو را می‌آورد.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
#: `mimetypes` پایتون `woff2` را نمی‌شناسد، پس بدونِ این خطْ فونت‌های کنسول
#: با `application/octet-stream` سرو می‌شوند. مرورگر به‌هرحال از `format()`ِ
#: خودِ `@font-face` تشخیص می‌دهد، ولی نوعِ درست کشِ میانی و ابزارِ دیباگ را
#: هم درست می‌کند و هزینه‌اش یک خط است.
mimetypes.add_type("font/woff2", ".woff2")

#: خروجیِ استاتیکِ `panel/` (Next.js). در تولید `docker/admin.Dockerfile` آن را
#: از مرحلهٔ Node کپی می‌کند؛ در توسعه با `npm run export:panel` ساخته می‌شود.
#: نبودنش کشنده **نیست** — `/console` یک ۵۰۳ِ گویا می‌دهد و بقیهٔ پنل دست‌نخورده
#: می‌ماند، چون یک صفحهٔ ساخته‌نشده نباید کلِ سرویس را از کار بیندازد.
_CONSOLE_DIR = os.path.join(_STATIC_DIR, "console")

# پلتفرم‌هایی که ممکن است کوکیِ ورود لازم داشته باشند (نامِ فایل باید کلید را داشته باشد
# تا `_pick_cookies` تطبیقش دهد — مثلِ instagram_1.txt). X همان twitter است.
COOKIE_PLATFORMS = [
    ("instagram", "اینستاگرام"),
    ("twitter", "X / توییتر"),
    ("tiktok", "تیک‌تاک"),
    ("youtube", "یوتیوب"),
    ("pinterest", "پینترست"),
    ("other", "عمومی / سایر"),
]
# برچسبِ فارسیِ همهٔ پلتفرم‌ها (منبعِ واحد در downloader؛ شاملِ پلتفرم‌های نوِ دانلود).
_PLATFORM_FA = dict(PLATFORM_LABELS)

# گروه‌بندیِ کلیدها برای فرم: (عنوانِ کارت, [(کلید, برچسب, توضیح)])
GROUPS = [
    ("سقف‌ها و کنترلِ مصرف", [
        ("rate_per_min", "نرخ در دقیقه", "۰ = نامحدود"),
        ("daily_op_quota", "سقفِ روزانهٔ عملیات", "هر کاربر · ۰ = نامحدود"),
        ("max_file_mb", "حداکثر حجمِ فایل (MB)", ""),
    ]),
    ("دانلودر", [
        ("downloader_enabled", "دانلودر فعال", ""),
        ("dl_allow_unknown", "تلاش برای هر لینک", "هاستِ ناشناخته را هم دانلود کن"),
        ("dl_rich_posts", "پستِ چند‌عکسی به‌شکلِ مقاله", "Rich Message؛ خطا → آلبوم"),
        ("dl_cookie_when_needed", "کوکی فقط وقتی لازم است",
         "اول ناشناس تلاش کن — اکانت‌ها کمتر می‌سوزند"),
        ("dl_ig_anon_enabled", "اینستاگرام: اول بدونِ کوکی",
         "پست/ریلز/کاروسل را از صفحهٔ embed بگیر و کوکی را فقط وقتی خرج کن که "
         "این راه نگرفت. استوری و لینکِ پروفایل همیشه کوکی می‌خواهند."),
        ("dl_cache_enabled", "کشِ لینک‌های تکراری",
         "لینکِ قبلاً دانلودشده آنی از تلگرام تحویل می‌شود"),
        ("dl_pot_enabled", "توکنِ یوتیوب (pot-provider)", "اگر دانلودِ یوتیوب کرش کرد خاموشش کن"),
        ("dl_default_ux", "رفتارِ پیش‌فرضِ لینک", ""),
        ("dl_ux_youtube", "کیفیتِ یوتیوب", ""),
        ("dl_ux_instagram", "کیفیتِ اینستاگرام", ""),
        ("dl_ux_twitter", "کیفیتِ X / توییتر", ""),
        ("dl_ux_tiktok", "کیفیتِ تیک‌تاک", ""),
        ("dl_direct_enabled", "لینکِ فایلِ مستقیم",
         "هرچه صفحهٔ وب نیست: ریلیزِ گیت‌هاب، فایلِ APK یا PDF"),
        ("dl_direct_max_mb", "حداکثر حجمِ فایلِ مستقیم (MB)", "سقفِ کلیِ دانلود هم اعمال می‌شود"),
        ("dl_direct_proxy", "فایلِ مستقیم از پروکسی برود",
         "روشن = مثلِ بقیهٔ موتورها از PROXY_URL می‌رود. خاموش یعنی از IPِ خودِ سرور — "
         "برای نگرانیِ حجمِ دادهٔ سیم‌کارت، «حداکثر حجمِ فایلِ مستقیم» اهرمِ دقیق‌تری است."),
        ("proxy_url", "خروجیِ شبکه (PROXY_URL)",
         "خالی = مستقیم از IPِ سرور · مثل socks5h://host:1080 — همان چیزی که ردیفِ بالا "
         "به آن ارجاع می‌دهد"),
        ("dl_max_cookie_tries", "حداکثر اکانتِ امتحان‌شده در هر دانلود",
         "۰ = تا آخرِ استخر"),
        ("dl_exit_cooldown_min", "کنارگذاشتنِ خروجیِ خراب (دقیقه)",
         "وقتی چند اکانت روی یک خروجی بیفتند"),
        ("dl_max_size_mb", "حداکثر حجمِ دانلود (MB)", ""),
        ("dl_concurrency", "دانلودِ هم‌زمان (کل)", ""),
        ("dl_daily_count", "سقفِ روزانهٔ دانلود", "هر کاربر · ۰ = نامحدود"),
        ("dl_daily_mb", "سقفِ روزانهٔ حجمِ دانلود (MB)", "هر کاربر · ۰ = نامحدود"),
        ("dl_max_duration_min", "حداکثر مدتِ رسانه (دقیقه)", "۰ = بی‌سقف"),
        ("dl_cooldown_sec", "فاصلهٔ دو دانلودِ یک کاربر (ثانیه)", "۰ = بدونِ فاصله"),
        ("dl_op_daily_min", "سقفِ روزانهٔ پردازشِ رسانهٔ دانلودی (دقیقه)",
         "فقط عملیاتِ گران روی فایلِ دانلودی · ۰ = نامحدود"),
        ("dl_min_free_gb", "کفِ فضای آزادِ دیسک (GB)", "زیرِ این حد دانلود رد می‌شود · ۰ = بی‌قید"),
    ]),
    ("اسپاتیفای و اپل موزیک", [
        ("spotify_enabled", "اسپاتیفای فعال", "بدونِ credential هم کار می‌کند"),
        ("spotify_client_id", "Client ID", "اختیاری · پایدارتر/کامل‌تر"),
        ("spotify_client_secret", "Client Secret", ""),
        ("apple_enabled", "اپل موزیک فعال", "بی‌کلید · فعلاً فقط لینکِ تکِ‌آهنگ"),
        ("match_meta", "متادیتا از پلتفرمِ مبدأ", "خاموش = از یوتیوب · روشن = از مبدأ"),
        ("match_max_tracks", "سقفِ ترک (آلبوم/پلی‌لیست)", ""),
        ("match_source", "منبعِ تطبیق", "ytmusic = دقیق‌تر · youtube = خام"),
        ("match_min", "حداقلِ امتیازِ تطبیق", "۰..۱۰۰ · بالاتر = سخت‌گیرتر"),
        ("match_yt_fallback", "چاره‌یِ یوتیوب", "اگر تطبیقِ مطمئن نبود: بهترینِ موجود"),
    ]),
    ("کاهشِ حجمِ ویدیو", [
        ("compress_speed", "سرعت / کیفیت", "کندتر = کوچک‌تر"),
        ("video_encoder", "انکودر", "nvenc فقط با GPU"),
        ("compress_tiny_target_mb", "هدفِ «خیلی کم‌حجم» (MB)", "کلاس/جلسه"),
        ("compress_tiny_height", "کفِ رزولوشنِ خیلی کم‌حجم", "۴۸۰ یا ۳۶۰"),
        ("vjoin_max_mb", "سقفِ حجمِ چسباندنِ ویدیو (MB)", "۰ = مثلِ سقفِ فایل"),
    ]),
    ("رونویسی و اکسترا", [
        ("whisper_model", "مدلِ Whisper", ""),
        ("dl_sponsorblock", "SponsorBlock", "حذفِ اسپانسر/اینترو"),
        ("dl_subs", "زیرنویسِ خودکار (en+fa)", ""),
    ]),
    ("کوکی‌ها", [
        ("cookie_alert_min", "هشدار وقتی اکانتِ سالم کمتر از", "۰ = خاموش · به تلگرامِ ادمین"),
    ]),
    # سهمیهٔ استخرِ سشن. تحقیق: فشارِ ۲× یعنی سوختنِ ۴× — بالا بردن این اعداد
    # سرعت می‌دهد ولی عمرِ اکانت را کوتاه می‌کند.
    ("سهمیهٔ استخرِ سشن", [
        ("ck_cap_instagram", "سقفِ ساعتیِ اینستاگرام", "دانلود در ساعت، برای هر اکانت · ۰ = بی‌سقف"),
        ("ck_cap_youtube", "سقفِ ساعتیِ یوتیوب", "ناشناس هم جواب می‌دهد، پس دست‌ودل‌بازتر"),
        ("ck_cap_twitter", "سقفِ ساعتیِ X / توییتر", ""),
        ("ck_cap_tiktok", "سقفِ ساعتیِ تیک‌تاک", ""),
        ("ck_cap_default", "سقفِ ساعتیِ بقیه", "پلتفرمِ خارج از فهرست"),
        ("ck_min_gap_sec", "حداقل فاصلهٔ دو استفاده (ثانیه)", "از یک اکانت · ۰ = بدونِ فاصله"),
        ("ck_warmup_days", "روزهای گرم‌کردنِ اکانتِ تازه", "۰ = بدونِ گرم‌کردن"),
        ("ck_warmup_pct", "سهمِ روزِ اول (درصد)", "۲۵ = یک‌چهارمِ ظرفیت، بعد پلکانی تا ۱۰۰"),
        ("ck_cooldown_min", "کول‌داونِ خطا (دقیقه)", "پایه · هر خطای بعدی دوبرابر، تا ۶ ساعت"),
        ("ck_rate_cooldown_min", "استراحتِ محدودیتِ نرخ (دقیقه)", "بدونِ ضربه به اکانت"),
        ("ck_invalid_at", "خطای پشتِ‌هم تا «باطل»", "این تعداد شکست = نیازمندِ تعویض"),
    ]),
    # ربات هر فایلی را دوباره آپلود می‌کند، پس خودش توزیع‌کننده است — این فیلتر
    # جلوی همان مسیرِ بن‌شدنِ ربات را می‌گیرد.
    ("فیلترِ محتوای بزرگسال", [
        ("safety_enabled", "فیلتر فعال", "لینک و فایلِ آپلودی، هر دو"),
        ("safety_scan_pixels", "بررسیِ خودِ تصویر", "خاموش = فقط دامنه و متادیتا"),
        ("safety_threshold", "آستانهٔ اطمینان (درصد)", "بالاتر = سهل‌گیرتر · پیش‌فرض ۵۵"),
        ("safety_video_frames", "تعدادِ فریمِ بررسیِ ویدیو", "بیشتر = دقیق‌تر و کندتر"),
        ("safety_block_domains", "دامنه‌های مسدودِ اضافی", "با کاما یا خطِ جدید"),
        ("safety_allow_domains", "استثنا (هرگز مسدود نشود)", "برای رفعِ مسدودیِ اشتباه"),
        ("safety_notify_admin", "گزارشِ هر مسدودی به ادمین", ""),
        ("safety_strikes", "مسدودیِ خودکارِ کاربر پس از", "این تعداد تخلف · ۰ = خاموش"),
    ]),
    ("لینک و استریم", [
        ("stream_base", "پایهٔ لینک (نودِ استریم)", "خالی = دامنهٔ مستر · مثل https://cdn.example.com"),
    ]),
]

#: عنوانِ گروهی که کلیدهای **برچسب‌نخوردهٔ** `RUNTIME_KEYS` در آن می‌افتند.
_AUTO_GROUP = "🧷 بدونِ دسته"
#: توضیحِ ردیفِ خودکار. عمداً در **UI** می‌نشیند نه در CI: گروهِ خودکار وظیفه‌اش
#: این است که کلید هرگز نامرئی نشود، ولی اگر بی‌صدا جذبش کند هیچ‌کس برچسبِ
#: درست نمی‌نویسد. این متن خودش نق می‌زند.
_AUTO_HINT = "هنوز برچسبِ فارسی ندارد — در GROUPS دسته‌بندی‌اش کن"


#: آیکونِ هر گروهِ تنظیمات. عمداً **کنارِ** `GROUPS` و نه داخلش:
#: `tests/test_settings_rename.py` آن لیست را با `literal_eval` از سورس
#: می‌خواند (بدونِ import، چون ایمیجِ تست jinja2/cryptography ندارد)، پس
#: باید یک لیترالِ خالص بماند.
_GROUP_ICON = {
    "سقف‌ها و کنترلِ مصرف": "shield",
    "دانلودر": "download",
    "اسپاتیفای و اپل موزیک": "zap",
    "کاهشِ حجمِ ویدیو": "file",
    "رونویسی و اکسترا": "type",
    "کوکی‌ها": "cookie",
    "سهمیهٔ استخرِ سشن": "sliders",
    "فیلترِ محتوای بزرگسال": "shield",
    "لینک و استریم": "link",
}


def _setting_groups() -> list[tuple[str, list[tuple[str, str, str]]]]:
    """گروه‌های فرمِ تنظیمات = `GROUPS` + هرچه در `RUNTIME_KEYS` جا مانده.

    **چرا خودکار، و چرا این تنها راهِ دوام است.** `GROUPS` فهرستِ دستی است و
    تنها گاردش (`tests/test_settings_rename.py:153`) فقط جهتِ
    «ردیفِ پنل باید کلیدِ واقعی باشد» را می‌سنجد. جهتِ دیگر — «کلیدِ واقعی باید
    ردیف داشته باشد» — هرگز نوشته نشد، و نتیجه‌اش شش کلیدِ زنده بود که از هیچ
    صفحه‌ای دیده نمی‌شدند: `proxy_url`, `dl_max_duration_min`, `dl_daily_mb`,
    `dl_cooldown_sec`, `dl_op_daily_min`, `dl_min_free_gb`. هر شش‌تا از
    `settings_store` خوانده می‌شوند (یعنی بدونِ ری‌استارت اثر دارند) و از
    `/admin`ِ تلگرام هم قابلِ تنظیم بودند — فقط پنل نمی‌دیدشان. ردیفِ دستی برای
    آن شش‌تا اضافه شد، ولی خودِ **الگو** رفع نمی‌شود مگر با یک مسیرِ خودکار.

    **هم `settings_page` و هم `save()` باید از این‌جا بخوانند.** `save()` مجموعهٔ
    `rendered` را می‌سازد تا کلیدهای خارج از فرم را ریست نکند؛ اگر آن یکی از
    `GROUPS`ِ خام بخواند و صفحه از این‌جا، ردیفِ خودکار رندر می‌شود و **بی‌صدا
    ذخیره نمی‌شود** — همان «بنرِ سبز روی کاری که انجام نشد» که کلِ خوشهٔ B را
    ساخت.
    """
    placed = {key for _title, rows in GROUPS for key, _l, _h in rows}
    leftover = [(k, k, _AUTO_HINT) for k in RUNTIME_KEYS if k not in placed]
    return [*GROUPS, (_AUTO_GROUP, leftover)] if leftover else list(GROUPS)

# کلیدهایی که مقدارشان فهرست/متنِ چندخطی است — ورودیِ ۱۶۰ پیکسلی برایشان
# بی‌فایده است، پس textarea می‌گیرند.
LONGTEXT_KEYS = ("safety_block_domains", "safety_allow_domains")

ENUM_LABELS = {
    "probe": "منوی کیفیت", "quick": "گرفتنِ سریع", "": "— ارث از پیش‌فرض",
    "tiny": "tiny", "base": "base", "small": "small", "medium": "medium", "large-v3": "large-v3",
    "fast": "سریع", "balanced": "بالانس", "quality": "کیفیت",
    "x264": "x264 (CPU)", "nvenc": "NVENC (GPU)",
    "ytmusic": "YouTube Music (دقیق)", "youtube": "یوتیوب (خام)",
}


# ── سشنِ رمزنگاری‌شده (کوکی؛ بدونِ نیاز به ذخیرهٔ سمتِ سرور) ──────
#: پیامِ واحدِ «رازِ نشست خالی است» — هم در startup چاپ می‌شود هم در استثنا، تا
#: هرکس از هر مسیری به آن بخورد **همان** دستورِ رفع را ببیند.
_NO_SECRET = (
    "ADMIN_SECRET is empty. The panel refuses to start.\n"
    "With it empty the session key would be derived from BOT_TOKEN, which every\n"
    "node holds — anyone with it could forge an admin session.\n"
    "Fix (one line, then restart just this container):\n"
    '  echo "ADMIN_SECRET=$(openssl rand -hex 32)" >> /root/telabzar/.env\n'
    "  docker compose up -d admin"
)


def _fernet() -> Fernet:
    """کلیدِ Fernetِ کوکیِ نشست.

    **هیچ fallbackی به `BOT_TOKEN` ندارد و نباید داشته باشد.** آن fallback یعنی
    هر دارندهٔ `BOT_TOKEN` می‌تواند کوکیِ ادمین بسازد — و `BOT_TOKEN` عمداً به
    هر نود داده می‌شود (`nodes.node_config`)، پس «راز» نیست. تولید از
    ۲۰۲۶-۰۸-۱۷ `ADMIN_SECRET` را ست دارد و `install.sh` از این پس خودش
    می‌سازدش؛ این استثنا برای هر مسیرِ دیگری است که به این‌جا برسد.
    """
    seed = settings.admin_secret
    if not seed:
        raise RuntimeError(_NO_SECRET)
    key = base64.urlsafe_b64encode(hashlib.sha256(f"telabzar-admin:{seed}".encode()).digest())
    return Fernet(key)


def _require_admin_secret() -> None:
    """پیش از سرو کردن، نبودِ راز را **بلند** اعلام و پروسه را متوقف می‌کند.

    عمداً refuse-to-start است نه هشدار. سه چیز این را کم‌هزینه می‌کند و هر سه
    اندازه‌گیری شده‌اند: شعاعش فقط کانتینرِ `admin` است (هیچ ماژولِ دیگری
    `admin_web` را import نمی‌کند)، `/admin`ِ تلگرام دست‌نخورده می‌ماند پس
    اپراتور کنترلِ ربات را از دست نمی‌دهد، و «‏.env گم شد» از قبل هم کشنده بود
    چون `BOT_TOKEN` پیش‌فرض ندارد و `Settings()` سرِ import می‌ترکد.
    """
    if not settings.admin_secret:
        log.critical("FATAL: %s", _NO_SECRET)
        raise SystemExit(1)


def _make_session(admin_id: int) -> str:
    return _fernet().encrypt(json.dumps({"id": admin_id, "t": int(time.time())}).encode()).decode()


def _session_admin(request: web.Request) -> int | None:
    tok = request.cookies.get(_COOKIE)
    if not tok:
        return None
    try:
        data = json.loads(_fernet().decrypt(tok.encode(), ttl=_SESSION_TTL))
        aid = int(data["id"])
    except (InvalidToken, ValueError, KeyError):
        return None
    except RuntimeError:
        # رازِ خالی. `main()` از قبل جلوی بالا آمدن را می‌گیرد، پس این‌جا فقط
        # برای مسیرهای دیگر (embed/تست) است: **بسته** برمی‌گردیم نه ۵۰۰، تا
        # نبودِ راز به «هیچ‌کس نمی‌تواند وارد شود» ترجمه شود نه به رگبارِ خطا.
        return None
    # هر درخواست دوباره عضویت را چک کن: ادمینِ حذف‌شده از ADMIN_IDS نباید تا انقضای
    # کوکی (۸ ساعت) دسترسی داشته باشد.
    return aid if aid in settings.admin_id_set else None


# ── استایلِ مشترک ───────────────────────────────────────────────
# CSS در `app/static/css/panel.css` زندگی می‌کند، نه به‌شکلِ رشته در این فایل.
#
# **ولی همچنان درون‌خطی تزریق می‌شود، و این تصمیم است نه تنبلی.** رفتنِ به یک
# `<link>`ِ خارجی بایت‌های HTML را عوض می‌کند (پس از اثباتِ «هیچ‌چیز عوض نشد»
# بیرون می‌افتد) و سه خوانندهٔ `<style>`ِ همان پاسخ را می‌شکند —
# `test_panel_css_classes`، `_rule_for`ِ `test_cookie_status_badges` و پیش‌شرطِ
# `test_security_headers`. اندازه‌گیری‌شده: ۱۵ شکست اگر فقط این برود، ۱۹ اگر
# تگِ `<style>` کلاً برود. آن سوییچ (به‌علاوهٔ برداشتنِ `style-src
# 'unsafe-inline'`) تغییرِ جداست با اثباتِ خودش.
#
# فونت از `/static/fonts` می‌آید و `@font-face` سرِ همین فایل است.
_CSS = pathlib.Path(_STATIC_DIR, "css", "panel.css").read_text(encoding="utf-8")


# ── قالب‌ها ──────────────────────────────────────────────────────
# قالب‌ها در `app/templates/*.html` زندگی می‌کنند، نه به‌شکلِ رشته در این فایل.
# **زیرِ `app/` یک قیدِ سخت است، نه سلیقه:** `docker/admin.Dockerfile` فقط
# `COPY app ./app` و `COPY node ./node` می‌کند، پس قالبی بیرونِ `app/` در
# ایمیج **نیست** و پنل روی تولید ۵۰۰ می‌دهد در حالی که CI سبز است — چون تست
# از ریشهٔ ریپو می‌دود جایی که پوشه هست. همان حادثه‌ای که یک‌بار برای
# `node/install.sh` افتاد و کامنتِ خودِ Dockerfile یادگارِ آن است.
# `app/static/fonts/` از قبل با همین مکانیزم سرو می‌شود.

ENV = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(default=True, default_for_string=True),
)
#: عددِ کانونی به‌شکلِ شبکهٔ نقطه‌ای. globalِ Jinja است نه متغیرِ context، چون
#: تابع است نه داده و هر صفحه‌ای ممکن است بخواهدش.
ENV.globals["lcd"] = _lcd


#: منوی پنل — یک ساختارِ **اعلانی**، نه HTMLِ دست‌نویس در قالب. شماره‌ها بخشی
#: از زبانِ بصریِ کنسول‌اند (نه تزئین): آدرسِ پایدارِ هر صفحه‌اند و برچسبشان با
#: عوض‌شدنِ زبانِ پنل تغییر نمی‌کند.
_NAV = (
    ("control", (("01", "settings", "/", "sliders"),
                 ("02", "users", "/users", "users"),
                 ("03", "cookies", "/cookies", "cookie"))),
    ("system", (("04", "health", "/health", "pulse"),
                ("05", "nodes", "/nodes", "server"))),
    ("content", (("06", "texts", "/texts", "type"),
                 ("07", "buttons", "/buttons", "palette"),
                 ("08", "langs", "/langs", "globe"))),
    ("data", (("09", "stats", "/stats", "chart"),)),
)

_LANG_COOKIE = "tab_lang"
_THEME_COOKIE = "tab_theme"
_NEXT_THEME = {"auto": "dark", "dark": "light", "light": "auto"}

#: ترجیحاتِ رندر (زبانِ پنل، پوسته، مسیرِ جاری) برای همین درخواست.
#:
#: **چرا ContextVar و نه یک پارامترِ `_render`:** `_render` سیزده محلِ فراخوانی
#: دارد و یکی‌شان (`_login_page`) اصلاً `request` در دست ندارد — پس پارامترکردن
#: یعنی سیزده امضا عوض شود و یک مسیر همچنان بی‌ترجیح بماند. هر هندلرِ aiohttp
#: در تسکِ خودش می‌دود و contextvar به‌ازای هر تسک کپی می‌شود، پس نشتی بینِ دو
#: درخواستِ هم‌زمان ممکن نیست؛ میدل‌ور در `finally` هم ریستش می‌کند.
_PREFS: contextvars.ContextVar[tuple[str, str, str]] = contextvars.ContextVar(
    "panel_prefs", default=("fa", "auto", "/"))


@web.middleware
async def _panel_prefs(request: web.Request, handler):
    token = _PREFS.set((normalize_lang(request.cookies.get(_LANG_COOKIE)),
                        normalize_theme(request.cookies.get(_THEME_COOKIE)),
                        request.path))
    try:
        return await handler(request)
    finally:
        _PREFS.reset(token)


async def prefs(request: web.Request) -> web.Response:
    """سوییچِ زبان/پوستهٔ **پنل** — کوکی، بدونِ JS و بدونِ FOUC.

    `<html lang dir data-theme>` سرورساید رندر می‌شود، پس صفحه از همان اولین
    بایت درست است؛ نسخهٔ JSمحور یک پرشِ دیدنی می‌دهد و با CSPِ فعلی (که
    `script-src` را باز نگه‌داشتنش هزینه دارد) هم‌خوان نیست.
    """
    resp = web.HTTPFound(_safe_back(request.query.get("to", "")))
    if "lang" in request.query:
        resp.set_cookie(_LANG_COOKIE, normalize_lang(request.query["lang"]),
                        max_age=365 * 86400, samesite="Lax")
    if "theme" in request.query:
        resp.set_cookie(_THEME_COOKIE, normalize_theme(request.query["theme"]),
                        max_age=365 * 86400, samesite="Lax")
    raise resp


def _safe_back(value: str) -> str:
    """مقصدِ بازگشت — فقط مسیرِ نسبیِ همین سایت، وگرنه `/`.

    `//evil.example` یک URLِ **پروتکل‌نسبی** است و مرورگر بیرون می‌بردش، پس
    شرطِ «با `/` شروع می‌شود» به‌تنهایی open-redirect را نمی‌بندد.
    """
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


def _render(name: str, **ctx) -> web.Response:
    lang, theme, here = _PREFS.get()
    ctx.setdefault("css", Markup(_CSS))
    ctx.setdefault("pfa", _PLATFORM_FA)
    ctx.setdefault("lang", lang)
    ctx.setdefault("dir", _PANEL_DIR_OF[lang])
    ctx.setdefault("theme", theme)
    ctx.setdefault("next_theme", _NEXT_THEME[theme])
    ctx.setdefault("panel_langs", PANEL_LANGS)
    ctx.setdefault("pt", lambda key, **kw: pt(lang, key, **kw))
    ctx.setdefault("nav", _NAV)
    ctx.setdefault("mesh", ())
    ctx.setdefault("here", here)
    ctx.setdefault("now", datetime.now(timezone.utc).strftime("%H:%M:%S"))
    ctx.setdefault("active", "")
    ctx.setdefault("admin_id", "")
    ctx.setdefault("pill_ok", True)
    html = ENV.get_template(name + ".html").render(**ctx)
    return web.Response(text=html, content_type="text/html")


def _result(path: str, *, ok: str = "", err: str = "", **state) -> web.HTTPFound:
    """ریدایرکتِ «نتیجهٔ یک ذخیره» — **تنها** راهِ ساختنِ `ok=`/`err=` در پنل.

    یک تابع، نه چند کپیِ دست‌نویس. انگیزه‌اش ممیزیِ خودِ همین خوشه است:
    `texts_save` مسیرِ خطا را داشت و `buttons_save` نداشت، و آن ناسازگاری —
    نه محدودیتِ طراحی — چیزی بود که B-1 را ساخت. همان درسِ
    `cookies.delete_account` و `_search_queries`: قاعده‌ای که در N نقطه دست‌نویس
    شود، در N نقطه واگرا می‌شود و هیچ‌کدام دیگری را خبر نمی‌کند. گاردِ ASTیِ
    `test_the_panel_has_one_result_redirect` در `tests/test_repo_hygiene.py`
    مانعِ کپیِ بعدی می‌شود.

    `state` پارامترهای وضعیتِ خودِ صفحه است (`kind`/`lang`/`q`/…) تا کاربر بعد از
    خطا به همان نمایی برگردد که در آن بود؛ مقدارِ تهی حذف می‌شود تا URL شلوغ نشود.
    کوئری با `urlencode` ساخته می‌شود، پس فاصله و «»ِ پیام‌های فارسی یک‌جا و
    یک‌شکل انکود می‌شوند به‌جای الحاقِ رشته‌ایِ هر مسیر.
    """
    params = {k: str(v) for k, v in state.items() if v not in ("", None)}
    if ok:
        params["ok"] = ok
    if err:
        params["err"] = err
    q = urlencode(params)
    return web.HTTPFound(f"{path}?{q}" if q else path)


# ── هلث ─────────────────────────────────────────────────────────
async def _pill_ok(app: web.Application) -> bool:
    """چکِ سریعِ نوارِ بالا (فقط pg+redis) تا هر صفحه سنگین نشود."""
    r: aioredis.Redis = app["redis"]
    try:
        await r.ping()
        async with Sessionmaker() as s:
            await s.execute(sql_text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


# ── سلامتِ pot-provider: هرگز روی مسیرِ درخواست ───────────────────────────
# این چک تنها فراخوانیِ **شبکهٔ بیرونیِ** پنل است، و درجا داخلِ `_health` زده
# می‌شد — یعنی داشبورد منتظرِ یک سرویسِ خارجی می‌ماند. اندازه‌گیری‌شده روی سورسِ
# پیش از این تغییر، با سوکتی که accept می‌کند و هرگز جواب نمی‌دهد:
#
#   `/` (داشبورد) → ۳۱۵۱ ms   ·   `/health` → ۳۰۲۳ ms   ·   بدونِ pot → ۲۱ ms
#
# «گیرکرده» بدترین حالت است نه نادرترین: سرویسِ مرده اتصال را rejectمی‌کند و
# سریع برمی‌گردد، ولی کانتینری که زنده است و پاسخ نمی‌دهد دقیقاً همان تایم‌اوتِ
# ۳ ثانیه را خرج می‌کند — و صفحهٔ اولِ پنل جایی نیست که منتظرِ آن بمانیم.
#
# **کوتاه‌کردنِ تایم‌اوت رفع نیست، فقط عدد را کم می‌کند.** پس نتیجه کش می‌شود و
# تازه‌سازی به **پس‌زمینه** می‌رود: مسیرِ درخواست همیشه صفر بایتِ شبکه دارد.
#
# دو کلید، نه یکی، و تفکیکشان باربر است: `fresh` (با TTL) می‌گوید «تازه
# سنجیده‌ایم» و `last` (بی‌انقضا) آخرین نتیجهٔ **شناخته‌شده** را نگه می‌دارد. با
# یک کلیدِ TTLدار، هر بار که کش می‌پرید صفحه «نامعلوم» می‌شد؛ با این دو، صفحه
# آخرین چیزی را که می‌دانیم نشان می‌دهد و هم‌زمان در پس‌زمینه تازه می‌شود.
_POT_FRESH_TTL = 30
_POT_LAST = "potping:last"
_POT_FRESH = "potping:fresh"
_POT_TASK = "pot_refresh_task"
#: «تنظیم شده ولی هنوز نسنجیده‌ایم» — با `None` («پیکربندی‌نشده») یکی نیست، و
#: یکی‌کردنشان یعنی پنل در پنجرهٔ کوتاهِ پس از ری‌استارت **دروغِ** «پیکربندی‌نشده»
#: می‌گوید دربارهٔ سرویسی که پیکربندی شده است.
POT_UNKNOWN = "?"


async def _pot_probe(url: str) -> bool:
    """همان GETِ قبلی، با همان تایم‌اوت — فقط دیگر روی مسیرِ درخواست نیست."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
            async with s.get(url + "/ping") as resp:
                return resp.status == 200  # 404/403 = خطا، نه «آنلاین»
    except Exception:  # noqa: BLE001
        return False


async def _pot_refresh(app: web.Application) -> None:
    ok = await _pot_probe(settings.pot_provider_url)
    try:
        r: aioredis.Redis = app["redis"]
        await r.set(_POT_LAST, "1" if ok else "0")
        await r.set(_POT_FRESH, "1", ex=_POT_FRESH_TTL)
    except Exception:  # noqa: BLE001
        pass


def _schedule_pot_refresh(app: web.Application) -> None:
    """یک تازه‌سازیِ پس‌زمینه، و نه بیشتر.

    ارجاعِ تسک روی `app` نگه داشته می‌شود نه رها: asyncio فقط ارجاعِ ضعیف نگه
    می‌دارد و یک تسکِ بی‌ارجاع می‌تواند وسطِ کار جمع شود. همان ارجاع جلوی
    انباشتِ تسک روی رفرشِ پیاپیِ صفحه را هم می‌گیرد.
    """
    task = app.get(_POT_TASK)
    if task is not None and not task.done():
        return
    app[_POT_TASK] = asyncio.create_task(_pot_refresh(app))


async def _pot_health(app: web.Application) -> bool | str | None:
    """`None` = پیکربندی‌نشده · `POT_UNKNOWN` = هنوز نسنجیده · بولین = نتیجه."""
    if not settings.pot_provider_url:
        return None
    try:
        r: aioredis.Redis = app["redis"]
        fresh = await r.get(_POT_FRESH)
        last = await r.get(_POT_LAST)
    except Exception:  # noqa: BLE001
        return POT_UNKNOWN
    if not fresh:
        _schedule_pot_refresh(app)
    return POT_UNKNOWN if last is None else last == "1"


async def _health(app: web.Application) -> dict:
    r: aioredis.Redis = app["redis"]
    h: dict = {}
    try:
        async with Sessionmaker() as s:
            await s.execute(sql_text("SELECT 1"))
        h["postgres"] = True
    except Exception:  # noqa: BLE001
        h["postgres"] = False
    try:
        await r.ping()
        h["redis"] = True
    except Exception:  # noqa: BLE001
        h["redis"] = False

    async def _int(key: str) -> int:
        try:
            return int(await r.get(key) or 0)
        except Exception:  # noqa: BLE001
            return 0

    try:
        h["q_main"] = await r.zcard("arq:queue")
        h["q_proc"] = await r.zcard("arq:queue:proc")
        # صفِ دانلود = صفِ نود (arq:queue:dl) + صفِ مسترِ fallback (arq:queue:dl:master)
        h["q_dl"] = (await r.zcard("arq:queue:dl")) + (await r.zcard("arq:queue:dl:master"))
    except Exception:  # noqa: BLE001
        h["q_main"] = h["q_proc"] = h["q_dl"] = 0
    # شمارندهٔ خودترمیمِ دانلودِ زنده (ZSET با هرسِ ورودیِ کهنه) — نه `INCR dl:active`
    # که روی مرگِ کانتینر گیر می‌کرد و پنل عددِ گیرکرده را «الان چند دانلود» می‌خواند.
    h["dl_active"] = await dl_active.count(r)
    try:
        du = shutil.disk_usage(settings.work_dir)
        h["disk_total"] = round(du.total / 1024 ** 3)
        h["disk_used"] = round((du.total - du.free) / 1024 ** 3)
        h["disk_pct"] = round((du.total - du.free) / du.total * 100)
    except Exception:  # noqa: BLE001
        h["disk_total"] = 0
    h["pot"] = await _pot_health(app)
    # نسخهٔ موتورها که هر ورکرِ دانلود سرِ استارت گزارش کرده. اولین سؤال وقتی یک
    # پلتفرم «پاسخِ نامعتبر» می‌دهد: موتور عقب افتاده یا سشن مرده؟
    h["engines"] = []
    try:
        async for key in r.scan_iter(match="dlver:*", count=100):
            try:
                h["engines"].append(json.loads(await r.get(key) or "{}"))
            except (ValueError, TypeError):
                pass
        h["engines"].sort(key=lambda e: str(e.get("who") or ""))
    except Exception:  # noqa: BLE001
        h["engines"] = []
    # نرخِ per-host امروز (لیستِ مرتب برای رندر)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    hosts = []
    for p in KNOWN_PLATFORMS:
        ok = await _int(f"dlstat:{p}:ok:{day}")
        fail = await _int(f"dlstat:{p}:fail:{day}")
        if ok + fail:
            hosts.append({"name": p, "ok": ok, "fail": fail,
                          "rate": round(ok / (ok + fail) * 100)})
    h["hosts"] = hosts
    h["all_ok"] = h["postgres"] and h["redis"]
    return h


async def _effective() -> dict:
    vals = {}
    for k, (kind, default) in RUNTIME_KEYS.items():
        ov = await settings_store.get_str(k, None)  # None اگر تنظیم نشده
        if ov is None:
            vals[k] = default
        elif kind == "int":
            try:
                vals[k] = int(ov)
            except ValueError:
                vals[k] = default
        elif kind == "bool":
            vals[k] = ov.strip().lower() in ("1", "true", "yes", "on")
        else:
            vals[k] = ov
    return vals


# ── کاربران و آمار ──────────────────────────────────────────────
_KIND_FA = {"image": "تصویر", "video": "ویدیو", "audio": "صوت", "voice": "ویس",
            "document": "سند", "pdf": "PDF", "archive": "آرشیو", "animation": "گیف"}
_OP_FA = {"compress": "فشرده‌سازی", "convert": "تبدیلِ فرمت", "transcribe": "رونویسی",
          "scan": "اسکنِ ویروس", "bg_remove": "حذفِ پس‌زمینه", "watermark": "واترمارک",
          "trim": "برش", "screenshot": "اسکرین‌شات", "mute": "بی‌صداکردن", "to_gif": "به گیف",
          "ocr": "OCR", "resize": "تغییرِ اندازه", "rotate": "چرخش", "enhance": "بهبود",
          "to_pdf": "به PDF", "merge": "ادغام", "link": "لینکِ دانلود", "zip": "زیپ",
          "extract_audio": "جداسازیِ صوت", "normalize": "نرمال‌سازی", "speed": "تغییرِ سرعت"}


def _human_size(n) -> str:
    n = int(n or 0)
    for unit, div in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


# ── آمار ───────────────────────────────────────────────────────
# بازه‌های صفحهٔ آمار: (کلید, برچسب, تعدادِ روز | None=کل)
_RANGES = (("24h", "۲۴ ساعت", 1), ("7d", "۷ روز", 7), ("30d", "۳۰ روز", 30), ("all", "کل", None))
_RANGE_DAYS = {k: d for k, _l, d in _RANGES}
_STATS_TTL = 60          # کشِ کوتاهِ Redis؛ صفحه ~۲۰ کوئریِ تجمیعی دارد
_DUR_SAMPLE = 2000       # سقفِ نمونه برای p95 (percentile_cont فقط Postgres است)

_SIZE_BUCKETS = ((5, "< ۵MB"), (50, "۵–۵۰MB"), (200, "۵۰–۲۰۰MB"),
                 (1024, "۲۰۰MB–۱GB"), (None, "> ۱GB"))
_RES_BUCKETS = ((2160, "4K"), (1440, "2K"), (1080, "1080p"), (720, "720p"),
                (480, "480p"), (0, "کمتر"))


def _fmt_hours(seconds: float | int | None) -> str:
    """ثانیه → «۱۲ ساعت و ۳۴ دقیقه» (یا دقیقه/ثانیه اگر کوتاه بود)."""
    s = int(seconds or 0)
    if s <= 0:
        return "۰"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m {sec}s" if m else f"{sec}s"


def _fmt_secs(seconds: float | None) -> str:
    """مدتِ پردازش برای جدولِ عملیات."""
    if not seconds:
        return "—"
    return f"{seconds:.1f}s" if seconds < 60 else f"{seconds / 60:.1f}m"


def _bars(rows: list[tuple], labeler=None) -> list[dict]:
    """(کلید, تعداد) → ردیفِ نوار با درصدِ نسبت به بیشینه."""
    mx = max((c for _k, c in rows), default=1) or 1
    return [{"k": (labeler(k) if labeler else k), "n": c, "pct": round(c / mx * 100)}
            for k, c in rows]


_TS_H = 96   # بلندیِ نمودارِ روند (px)


def _day_keys(days: int, now: datetime) -> list[str]:
    return [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]


def _bucket(timestamps, keys: list[str]) -> dict[str, int]:
    """باکت‌بندیِ روزانه در پایتون — قابلِ‌حمل بینِ Postgres و SQLite (برخلافِ date_trunc)."""
    b = dict.fromkeys(keys, 0)
    for ts in timestamps:
        k = str(ts)[:10]
        if k in b:
            b[k] += 1
    return b


def _stacked_series(series: dict[str, list], days: int, now: datetime) -> list[dict]:
    """نمودارِ میله‌ایِ **انباشته** با مقیاسِ مشترک.

    هر سری اگر جدا نرمال شود، روزی با ۱ کاربر و روزی با ۳۰ فایل هر دو صددرصد
    می‌شوند و نمودار دروغ می‌گوید؛ پس ارتفاع بر اساسِ **مجموعِ بیشینهٔ روزها** است.
    """
    keys = _day_keys(days, now)
    buckets = {name: _bucket(ts, keys) for name, ts in series.items()}
    totals = [sum(b[k] for b in buckets.values()) for k in keys]
    mx = max(totals, default=0) or 1
    out = []
    for i, k in enumerate(keys):
        row = {"day": k[5:], "total": totals[i]}
        for name, b in buckets.items():
            n = b[k]
            row[name] = n
            row[name + "_h"] = round(n / mx * _TS_H) if n else 0
        out.append(row)
    return out


def _pct(part: int, whole: int) -> int:
    return round(part / whole * 100) if whole else 0


async def _stats(rng: str = "7d") -> dict:  # noqa: PLR0915 — یک تابعِ گردآوریِ خطی
    """آمارِ صفحهٔ /stats برای بازهٔ داده‌شده. کشِ ۶۰ ثانیه‌ای در Redis."""
    now = datetime.now(timezone.utc)
    days = _RANGE_DAYS.get(rng, 7)
    since = now - timedelta(days=days) if days else None
    s: dict = {"range": rng, "ranges": _RANGES, "days": days}

    def in_range(col):
        """شرطِ بازه (یا همیشه‌درست برای «کل») — تا کوئری‌ها یک‌شکل بمانند."""
        return col >= since if since is not None else sa_true()

    async with Sessionmaker() as db:
        # ── کاربران ──
        s["users"] = await db.scalar(select(func.count(User.id))) or 0
        s["users_new"] = await db.scalar(
            select(func.count(User.id)).where(in_range(User.created_at))) or 0
        s["users_active"] = await db.scalar(
            select(func.count(User.id)).where(in_range(User.last_seen))) or 0
        s["users_blocked"] = await db.scalar(
            select(func.count(User.id)).where(User.is_blocked.is_(True))) or 0
        lang_rows = (await db.execute(select(func.coalesce(User.lang, "—"), func.count(User.id))
                     .group_by(User.lang).order_by(func.count(User.id).desc()))).all()

        # ── فایل‌ها ──
        s["files"] = await db.scalar(select(func.count(File.id)).where(in_range(File.created_at))) or 0
        s["files_all"] = await db.scalar(select(func.count(File.id))) or 0
        storage = await db.scalar(select(func.coalesce(func.sum(File.size), 0))
                                  .where(in_range(File.created_at))) or 0
        s["dl_files"] = await db.scalar(select(func.count(File.id))
                                        .where(File.source == "dl", in_range(File.created_at))) or 0
        media_secs = await db.scalar(select(func.coalesce(func.sum(File.duration), 0))
                                     .where(in_range(File.created_at))) or 0
        kind_rows = (await db.execute(
            select(File.kind, func.count(File.id)).where(in_range(File.created_at))
            .group_by(File.kind).order_by(func.count(File.id).desc()))).all()
        plat_rows = (await db.execute(
            select(File.platform, func.count(File.id))
            .where(File.platform.is_not(None), in_range(File.created_at))
            .group_by(File.platform).order_by(func.count(File.id).desc()))).all()
        # حجم/ابعاد/نام برای توزیع‌ها — یک اسکنِ محدود، باکت‌بندی در پایتون
        dist_rows = (await db.execute(
            select(File.size, File.height, File.width, File.name, File.kind)
            .where(in_range(File.created_at)).limit(20000))).all()

        # ── عملیات ──
        s["ops"] = await db.scalar(select(func.count(Job.id)).where(in_range(Job.created_at))) or 0
        st_rows = {st: c for st, c in (await db.execute(
            select(Job.status, func.count(Job.id)).where(in_range(Job.created_at))
            .group_by(Job.status))).all()}
        op_rows = (await db.execute(
            select(Job.op, func.count(Job.id)).where(in_range(Job.created_at))
            .group_by(Job.op).order_by(func.count(Job.id).desc()).limit(10))).all()
        # نرخِ موفقیت + زمانِ پردازشِ هر op (finished_at−created_at؛ داده‌ای که تا امروز بلااستفاده بود)
        per_op = (await db.execute(
            select(Job.op, Job.status, Job.created_at, Job.finished_at)
            .where(in_range(Job.created_at), Job.finished_at.is_not(None))
            .order_by(Job.id.desc()).limit(_DUR_SAMPLE))).all()
        err_rows = (await db.execute(
            select(Job.op, Job.error).where(Job.status == "failed", Job.error.is_not(None),
                                            in_range(Job.created_at))
            .order_by(Job.id.desc()).limit(500))).all()

        # ── سریِ زمانی ──
        span = min(days, 30) if days else 30
        span = max(span, 2)          # «۲۴ ساعت» هم دو ستون بگیرد (دیروز/امروز)
        t_since = now - timedelta(days=span)
        file_ts = (await db.execute(select(File.created_at)
                   .where(File.created_at >= t_since))).scalars().all()
        job_ts = (await db.execute(select(Job.created_at)
                  .where(Job.created_at >= t_since))).scalars().all()
        user_ts = (await db.execute(select(User.created_at)
                   .where(User.created_at >= t_since))).scalars().all()

        # ── کاربرانِ برتر ──
        top_rows = (await db.execute(
            select(User.tg_user_id, func.count(File.id), func.coalesce(func.sum(File.size), 0))
            .join(File, File.owner_id == User.id).where(in_range(File.created_at))
            .group_by(User.id, User.tg_user_id)
            .order_by(func.count(File.id).desc()).limit(10))).all()

        # ── کشِ دانلود ──
        s["cache_rows"] = await db.scalar(select(func.count(DownloadCache.key))) or 0
        s["cache_hits"] = await db.scalar(
            select(func.coalesce(func.sum(DownloadCache.hits), 0))) or 0
        cache_saved = await db.scalar(select(func.coalesce(
            func.sum(DownloadCache.size * DownloadCache.hits), 0))) or 0

    # ── مشتقات ──
    s["storage_h"] = _human_size(storage)
    s["media_h"] = _fmt_hours(media_secs)
    s["src_dl"], s["src_up"] = s["dl_files"], max(0, s["files"] - s["dl_files"])
    s["src_up_pct"], s["src_dl_pct"] = _pct(s["src_up"], s["files"]), _pct(s["src_dl"], s["files"])
    s["by_kind"] = _bars(kind_rows, lambda k: _KIND_FA.get(k, k))
    s["by_op"] = _bars(op_rows, lambda k: _OP_FA.get(k, k))
    # نامِ زبان از `BUILTIN_NAMES` می‌آید نه یک کپیِ سومِ دست‌نویس؛ کدِ ناشناخته
    # (زبانِ افزوده‌ای که هنوز ثبت نشده) خامْ نشان داده می‌شود، که صادقانه است.
    s["by_lang"] = _bars(lang_rows, lambda k: BUILTIN_NAMES.get(k, k))
    s["by_platform"] = _bars(plat_rows, lambda k: _PLATFORM_FA.get(k, k or "—"))
    s["queued"] = st_rows.get("queued", 0) + st_rows.get("running", 0)
    s["cancelled"] = st_rows.get("cancelled", 0)
    done, failed = st_rows.get("done", 0), st_rows.get("failed", 0)
    s["done"], s["failed"] = done, failed
    s["success_rate"] = _pct(done, done + failed) if (done + failed) else None
    s["cache_saved_h"] = _human_size(cache_saved)

    # توزیعِ حجم / کیفیت / فرمت
    size_b = {label: 0 for _mb, label in _SIZE_BUCKETS}
    res_b = {label: 0 for _h, label in _RES_BUCKETS}
    ext_c: dict[str, int] = {}
    for size, height, _w, name, kind in dist_rows:
        mb = (size or 0) / 1024 / 1024
        for cap, label in _SIZE_BUCKETS:
            if cap is None or mb < cap:
                size_b[label] += 1
                break
        if kind == "video" and height:
            for cap, label in _RES_BUCKETS:
                if height >= cap:
                    res_b[label] += 1
                    break
        ext = (os.path.splitext(name or "")[1] or "").lstrip(".").lower()
        if 1 <= len(ext) <= 5:
            ext_c[ext] = ext_c.get(ext, 0) + 1
    s["by_size"] = _bars([(k, v) for k, v in size_b.items() if v])
    s["by_res"] = _bars([(k, v) for k, v in res_b.items() if v])
    s["by_ext"] = _bars(sorted(ext_c.items(), key=lambda kv: -kv[1])[:8])

    # نرخِ موفقیت + میانگین/‏p95ِ زمانِ هر op
    agg: dict[str, dict] = {}
    for op, status, created, finished in per_op:
        a = agg.setdefault(op, {"ok": 0, "bad": 0, "durs": []})
        if status == "done":
            a["ok"] += 1
        elif status == "failed":
            a["bad"] += 1
        try:
            d = (finished - created).total_seconds()
            if 0 <= d < 86400:
                a["durs"].append(d)
        except (TypeError, AttributeError):
            pass
    rows = []
    for op, a in agg.items():
        tot = a["ok"] + a["bad"]
        durs = sorted(a["durs"])
        p95 = durs[min(len(durs) - 1, int(len(durs) * 0.95))] if durs else None
        rows.append({"op": _OP_FA.get(op, op), "n": tot or len(durs),
                     "rate": _pct(a["ok"], tot) if tot else None,
                     "bad": a["bad"],
                     "avg": _fmt_secs(sum(durs) / len(durs) if durs else None),
                     "p95": _fmt_secs(p95)})
    s["op_perf"] = sorted(rows, key=lambda r: -r["n"])[:10]
    all_durs = sorted(d for a in agg.values() for d in a["durs"])
    s["avg_op_h"] = _fmt_secs(sum(all_durs) / len(all_durs) if all_durs else None)

    # پرتکرارترین خطاها (نرمال‌شده تا شمارش معنا بدهد)
    errs: dict[str, int] = {}
    for op, err in err_rows:
        msg = " ".join((err or "").split())[:110]
        if msg:
            key = f"{_OP_FA.get(op, op)} · {msg}"
            errs[key] = errs.get(key, 0) + 1
    s["errors"] = [{"msg": k, "n": v} for k, v in sorted(errs.items(), key=lambda kv: -kv[1])[:8]]

    # سریِ زمانی — سه سری روی یک نمودارِ انباشته با مقیاسِ مشترک
    s["series_days"] = span
    s["ts"] = _stacked_series({"f": file_ts, "o": job_ts, "u": user_ts}, span, now)
    s["ts_max"] = max((r["total"] for r in s["ts"]), default=0)

    s["top_users"] = [{"tg": tg, "files": n, "size": _human_size(sz)} for tg, n, sz in top_rows]
    return s


async def _stats_cached(app, rng: str) -> dict:
    """آمار با کشِ کوتاهِ Redis — رفرشِ پیاپیِ صفحه نباید به دیتابیس فشار بیاورد."""
    redis = app.get("redis")
    key = f"statscache:{rng}"
    if redis is not None:
        try:
            raw = await redis.get(key)
            if raw:
                return json.loads(raw)
        except Exception:  # noqa: BLE001
            pass
    s = await _stats(rng)
    if redis is not None:
        try:
            await redis.set(key, json.dumps(s, default=str), ex=_STATS_TTL)
        except Exception:  # noqa: BLE001
            pass
    return s


# ── کشِ صفحهٔ کاربران ─────────────────────────────────────────────────────
# هم‌شکلِ `_stats_cached`، و به همان دلیل: صفحه‌ای که ادمین پشتِ‌هم رفرش می‌کند
# نباید هر بار جدول را بپیماید. ولی **آنچه گران است سورت نیست، شمارش است** —
# اندازه‌گیری‌شده روی Postgres 16 با ۲۰۰هزار ردیف، پس از افزودنِ ایندکس:
#
#   count(*) → ۱۲٫۵ ms · count(*) بلاک‌شده‌ها → ۱۲٫۷ ms
#   کوئریِ خودِ صفحه → ۰٫۴۵ ms · شمارشِ فایل‌ها → ۰٫۴۱ ms
#
# یعنی دو `count(*)` حدودِ ۹۶٪ کارِ صفحه‌اند و ایندکس کاری با آن‌ها ندارد؛ این
# کش دقیقاً همان‌هاست که برمی‌دارد. روی جدولِ **امروزِ** تولید (۱۶۶۸ ردیف) کلِ
# صفحه ~۲٫۷ ms است، پس این بیمه برای رشد است نه رفعِ یک دردِ فعلی — و همین‌جا
# نوشته می‌شود تا نفرِ بعد فکر نکند عددی را که ندیده بهبود داده‌ایم.
_USERS_TTL = 30
_USERS_VER = "userscache:ver"


async def _users_cache_ver(redis) -> str:
    """شمارندهٔ نسخه — همان الگوی `txtver` که `textstore` از قبل دارد.

    باطل‌کردن با **نسخه** انجام می‌شود نه با پیمایش و حذفِ کلیدها: `users_block`
    فقط یک `INCR` می‌زند و همهٔ صفحه‌های کش‌شده در همان لحظه یتیم می‌شوند، بدونِ
    اینکه لازم باشد بدانیم کدام صفحه/جست‌وجو کش شده. کلیدهای کهنه خودشان با TTL
    می‌روند.

    این باطل‌سازی **شرطِ درستی است نه بهینه‌سازی**: بدونِ آن، ادمین «بلاک» را
    می‌زند، به `/users` برمی‌گردد و همان کاربر را هنوز آزاد می‌بیند — یعنی صفحه
    دربارهٔ کاری که همین الان انجام شد دروغ می‌گوید.
    """
    try:
        return str(await redis.get(_USERS_VER) or "0")
    except Exception:  # noqa: BLE001
        return "0"


async def _users_cache_bust(redis) -> None:
    try:
        await redis.incr(_USERS_VER)
    except Exception:  # noqa: BLE001
        pass


async def _users_cached(app, page: int, q: str) -> dict:
    redis = app.get("redis")
    if redis is None:
        return await _users_list(page, q)
    key = f"userscache:{await _users_cache_ver(redis)}:{page}:{q}"
    try:
        raw = await redis.get(key)
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    data = await _users_list(page, q)
    try:
        await redis.set(key, json.dumps(data, default=str), ex=_USERS_TTL)
    except Exception:  # noqa: BLE001
        pass
    return data


async def _users_list(page: int, q: str) -> dict:
    per = 40
    q = (q or "").strip()
    async with Sessionmaker() as db:
        base = select(User)
        if q:
            # جست‌وجو فقط با شناسهٔ عددیِ دقیق؛ ورودیِ غیرعددی/خیلی‌بزرگ → نتیجهٔ خالی
            # (نه کلِ لیست، و نه 500 روی int8 سرریز).
            if q.isdigit() and int(q) < 2 ** 63:
                base = base.where(User.tg_user_id == int(q))
            else:
                base = base.where(User.id == -1)
        total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
        # شمارشِ بلاک‌شده هم‌محدودهٔ جست‌وجو (وگرنه «۱ کل · ۵ بلاک»ِ بی‌معنی)
        blocked = await db.scalar(select(func.count()).select_from(
            base.where(User.is_blocked.is_(True)).subquery())) or 0
        rows = (await db.execute(
            base.order_by(User.last_seen.desc()).limit(per).offset(page * per))).scalars().all()
        ids = [u.id for u in rows]
        counts: dict[int, int] = {}
        if ids:
            cres = await db.execute(select(File.owner_id, func.count(File.id))
                                    .where(File.owner_id.in_(ids)).group_by(File.owner_id))
            counts = {oid: c for oid, c in cres.all()}
    admins = settings.admin_id_set
    users = [{
        "id": u.id, "tg": u.tg_user_id, "role": u.role, "blocked": bool(u.is_blocked),
        "is_admin": u.tg_user_id in admins,
        "created": str(u.created_at)[:10] if u.created_at else "",
        "seen": str(u.last_seen)[:16].replace("T", " ") if u.last_seen else "",
        "files": counts.get(u.id, 0),
    } for u in rows]
    pages = max(1, (total + per - 1) // per)
    return {"users": users, "page": page, "pages": pages, "total": total,
            "blocked": blocked, "q": q}


# ── کوکی‌ها ─────────────────────────────────────────────────────


def _cookies_dir_ok() -> bool:
    d = settings.cookies_dir
    return bool(d) and os.path.isdir(d) and os.access(d, os.W_OK)


def _guess_platform(name: str) -> str:
    low = name.lower()
    for key, _fa in COOKIE_PLATFORMS:
        if key != "other" and key in low:
            return key
    return "other"


def _safe_cookie_name(name: str) -> str | None:
    """نامِ فایل را به یک basenameِ امنِ .txt تبدیل می‌کند (بدونِ traversal).

    پیاده‌سازی در `cookies.safe_name` است تا پنل و هندلرِ تلگرامیِ ادمین **یک**
    قاعده داشته باشند؛ این نام فقط برای فراخوان‌های موجودِ همین فایل مانده.
    """
    return ck_pool.safe_name(name)


# ── هندلرها ─────────────────────────────────────────────────────
def _login_page(step: int = 1, admin_id: str = "", sent: bool = False, error: str = "") -> web.Response:
    return _render("login", step=step, admin_id=admin_id, sent=sent, error=error)


async def login(request: web.Request) -> web.Response:
    if _session_admin(request):
        raise web.HTTPFound("/")
    return _login_page()


# ── محدودیتِ نرخِ مسیرِ لاگین ──────────────────────────────────────────────
# پورتِ پنل از اینترنت رسیدنی است، پس این تنها چیزی است که بینِ یک مهاجم و یک
# کدِ ۶رقمی می‌ایستد. **وضعِ پیش از این تغییر با اجرا سنجیده شد، نه با خواندن**
# (هارنسِ `tests/panel/`، ساعتِ fakeredis مدل‌شده) — و برخلافِ فرضِ اولیه
# محدودیت **وجود داشت**:
#
#   `panelreq:<id>` → ۵ درخواستِ کد در ۶۰۰ ثانیه   (TTL سنجیده‌شده: ۶۰۰)
#   `paneltry:<id>` → ۶ حدس در ۳۰۰ ثانیه            (TTL سنجیده‌شده: ۳۰۰)
#
# ولی `auth_request` شمارندهٔ حدس را **پاک می‌کرد**، پس بودجهٔ واقعی ضرب می‌شد:
# **۳۰ حدس در هر پنجرهٔ ۶۰۰ ثانیه** (اندازه‌گیری‌شده، نه محاسبه‌شده)، و پس از
# گذشتِ پنجره از نو. یعنی در برابرِ فضای ۱۰^۶: ~۴٫۳e-3 در روز، یعنی احتمالِ
# تجمعیِ ~۷۹٪ در یک سالِ حملهٔ پیوسته. «بی‌نهایت» نبود، ولی برای اندپوینتی که
# برای همیشه باز است هم کافی نبود.
#
# **سه نقصِ مشخص که همان اندازه‌گیری داد:**
#   ۱. `auth_verify` شناسه را با `admin_id_set` **نمی‌سنجید** (برخلافِ
#      `auth_request`) — ۲۰۰ شناسهٔ دلخواه از یک IP، ۲۰۰ کلیدِ `paneltry:` ساخت
#      و هیچ‌کدام رد نشد. یعنی ساختِ کلیدِ بی‌کران از یک اندپوینتِ عمومی.
#   ۲. هیچ سقفی روی **مبدأ** نبود؛ هر دو شمارنده روی هویتِ **قربانی** بودند.
#   ۳. مقایسهٔ کد `!=` بود، نه زمان‌ثابت.
#
# **شکلِ رفع، و چرا این شکل:** بودجهٔ حدس به **خودِ کد** بسته شد نه به اندپوینت —
# با تمام‌شدنش کد کشته می‌شود و کاربر یک کدِ تازه می‌گیرد، به‌جای اینکه مسیرِ
# verify برای ۳۰۰ ثانیه بسته شود. این تفاوت باربر است: تنها به این دلیل می‌شود
# سقفِ حدس را ۶ → ۳ آورد **بدونِ** ساختنِ یک اهرمِ قفل‌کردنِ ادمینِ واقعی. (فرمِ
# بدیهی‌تر — «حذفِ ریست» — دقیقاً همان اهرم را می‌ساخت: مهاجم با ۶ حدس در هر
# ۳۰۰ ثانیه ورودِ ادمین را برای همیشه می‌بست.)
#
# **عددها:**
#   • `_CODE_TRIES = 3` — یک انسان که کدِ ۶رقمی را از DMِ تلگرام رونویسی می‌کند
#     به ۱ نیاز دارد؛ ۳ یک تایپ و یک کدِ کهنه را هم پوشش می‌دهد. ۶ → ۳ نرخِ
#     brute-force را نصف می‌کند و طبقِ بالا هزینهٔ در‌دسترس‌بودن ندارد.
#   • `_RL_REQ_PER_ADMIN = 5` — **عمداً دست‌نخورده.** این تنها اهرمی است که یک
#     مهاجم علیهِ ادمینِ واقعی دارد (بودجه را بسوزان → ادمین کد نمی‌گیرد)، پس
#     پایین‌آوردنش حاشیهٔ brute-force را با یک قفلِ ارزان‌ترِ ادمین عوض می‌کند.
#     آن معامله تصمیمِ طراحیِ احراز هویت است نه تنظیمِ نرخ؛ همان‌جا ماند که بود.
#   • `_RL_REQ_PER_IP = 10` — **دلخواه در حدِ یک مرتبهٔ بزرگی**، و صریح می‌گویم
#     دلخواه است. تنها قیدِ واقعی‌اش این است که باید **بالاتر از** سقفِ per-admin
#     باشد، وگرنه دو ادمینِ پشتِ یک NAT پیش از تمام‌شدنِ بودجهٔ خودشان به سقفِ IP
#     می‌خورند. ۱۰ = دو برابرِ ۵.
#   • `_RL_VERIFY_PER_IP` — **مشتق است نه دلخواه**: بیشترین حدسی که یک IP
#     می‌تواند زیرِ بودجهٔ درخواستِ خودش **مشروع** تولید کند، یعنی ۱۰×۳.
#
# **صادقانه: سقفِ per-IP نرخِ مهاجمِ تک‌هدف/تک‌مبدأ را کم نمی‌کند** — آن‌جا سقفِ
# per-admin زودتر می‌بندد. چیزی که می‌خرد این است که رفعِ بالا بلاکِ اندپوینت را
# برداشت، پس بدونِ آن حجمِ خامِ verify از یک مبدأ **بی‌کران** می‌شد؛ و برخلافِ
# سقفِ per-admin، بلاک‌شدنِ IPِ مهاجم قفلِ ادمین نیست.
#
# **بودجهٔ نهایی: ۵ کد × ۳ حدس = ۱۵ حدس در ۶۰۰ ثانیه** (از ۳۰). و اهرمِ واقعی
# برای بهترکردنِ این افق **طولِ کد** است نه این شمارنده‌ها: همین ۱۵ در برابرِ
# ۱۰^۸ به ~۰٫۵٪ در سال می‌رسد. ثبت شد، ساخته نشد — چون UXِ ورود را عوض می‌کند
# و تصمیمِ اپراتور است.
_RL_WINDOW = 600
_RL_REQ_PER_ADMIN = 5
_RL_REQ_PER_IP = 10
_CODE_TTL = 300
_CODE_TRIES = 3
_RL_VERIFY_PER_IP = _RL_REQ_PER_IP * _CODE_TRIES

#: بلندترین شناسهٔ تلگرامی که می‌پذیریم. `str.isdigit()` طولی را رد نمی‌کند و
#: `int()` در پایتون ۳٫۱۱+ روی رشتهٔ بالای ۴۳۰۰ رقم **`ValueError` می‌دهد**
#: (اجراشده) — یعنی یک فرمِ بزرگ، ۵۰۰ می‌گرفت نه «نامعتبر».
_ADMIN_ID_MAXLEN = 20


def _client_ip(request: web.Request) -> str:
    """آدرسِ همتای سوکت — عمداً `X-Forwarded-For` خوانده **نمی‌شود**.

    XFF را خودِ کلاینت ست می‌کند، پس اعتماد به آن سقفِ per-IP را برای همان
    استقراری که باید محافظتش کند (پنلِ مستقیماً روی اینترنت، همان چیزی که
    `install.sh` با TLSِ خودش می‌سازد) به یک no-op تبدیل می‌کند: مهاجم به‌ازای
    هر درخواست یک مقدارِ تازه می‌گذارد.

    بهایش صریح است: پشتِ یک پروکسیِ معکوس همهٔ کلاینت‌ها یک سطل می‌شوند. به
    همین دلیل عددهای per-IP **بالاتر از** عددهای per-admin چیده شده‌اند، پس یک
    ادمینِ عادی هیچ‌وقت اول به این سقف نمی‌خورد.
    """
    return request.remote or "?"


async def _rate_limit(r: aioredis.Redis, key: str, limit: int, window: int) -> bool:
    """یک پنجرهٔ ثابتِ شمارنده‌ای. `True` یعنی این درخواست مجاز است.

    یک پیاده‌سازی برای هر سه سطل — پیش از این همان قاعده **دو بار دستی** نوشته
    شده بود، همان شکلی که §۷ برای `remove_cookie_file` ثبت کرده.

    `expire` وقتی TTL گم باشد هم دوباره زده می‌شود، نه فقط روی `n == 1`.
    `INCR` و `EXPIRE` دو فرمانِ جدا هستند؛ اگر پروسه بینشان بمیرد کلید **بدونِ
    انقضا** می‌ماند و شمارنده تا ابد بالا می‌رود — یعنی قفلِ دائمیِ ورود که خودش
    ترمیم نمی‌شود و فقط با پاک‌کردنِ دستیِ کلید باز می‌شود (همان شکستی که §۷ برای
    `dl:active` ثبت کرده). با این فرم، درخواستِ بعدی ترمیمش می‌کند و هزینه‌اش
    همان دو فرمان می‌ماند.
    """
    n = await r.incr(key)
    if n == 1 or await r.ttl(key) < 0:
        await r.expire(key, window)
    return n <= limit


async def _send_code(chat_id: int, code: str) -> bool:
    url = f"{settings.local_api_base.rstrip('/')}/bot{settings.bot_token}/sendMessage"
    text = (f"🔐 کدِ ورود به پنلِ تل‌ابزار:\n\n<code>{code}</code>\n\n"
            "تا ۵ دقیقه معتبر است. اگر شما درخواست نداده‌اید، نادیده بگیرید.")
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}) as r:
                return bool((await r.json()).get("ok"))
    except Exception:  # noqa: BLE001
        return False


def _is_admin_id(admin_id: str) -> bool:
    """شناسهٔ فرم یک ادمینِ ثبت‌شده است؟ (طول‌دار، وگرنه `int()` می‌ترکد)"""
    return (admin_id.isdigit() and len(admin_id) <= _ADMIN_ID_MAXLEN
            and int(admin_id) in settings.admin_id_set)


async def auth_request(request: web.Request) -> web.Response:
    r: aioredis.Redis = request.app["redis"]
    # سقفِ IP **پیش از** اعتبارسنجیِ شناسه، وگرنه کوبیدن با شناسهٔ نامعتبر رایگان است.
    if not await _rate_limit(r, f"panelip:req:{_client_ip(request)}",
                             _RL_REQ_PER_IP, _RL_WINDOW):
        return _login_page(error="درخواستِ زیاد از این آدرس؛ چند دقیقه بعد امتحان کن.")
    form = await request.post()
    admin_id = (form.get("admin_id") or "").strip()
    if not _is_admin_id(admin_id):
        return _login_page(error="شناسهٔ ادمین نامعتبر است.")
    if not await _rate_limit(r, f"panelreq:{admin_id}", _RL_REQ_PER_ADMIN, _RL_WINDOW):
        return _login_page(error="درخواستِ زیاد؛ چند دقیقه بعد امتحان کن.")
    code = f"{secrets.randbelow(1000000):06d}"
    await r.set(f"panelcode:{admin_id}", code, ex=_CODE_TTL)
    # کدِ تازه بودجهٔ حدسِ تازه می‌آورد. این «ریست» حالا بی‌خطر است، چون بودجه
    # دیگر اندپوینت را نمی‌بندد — به کدی بسته است که همین الان عوض شد.
    await r.delete(f"paneltry:{admin_id}")
    if not await _send_code(int(admin_id), code):
        return _login_page(error="نتوانستم کد را بفرستم؛ مطمئن شو ربات را /start کرده‌ای.")
    return _login_page(step=2, admin_id=admin_id, sent=True)


async def auth_verify(request: web.Request) -> web.Response:
    r: aioredis.Redis = request.app["redis"]
    if not await _rate_limit(r, f"panelip:ver:{_client_ip(request)}",
                             _RL_VERIFY_PER_IP, _RL_WINDOW):
        return _login_page(error="تلاشِ زیاد از این آدرس؛ چند دقیقه بعد امتحان کن.")
    form = await request.post()
    admin_id = (form.get("admin_id") or "").strip()
    code = (form.get("code") or "").strip()
    # همان گاردی که `auth_request` دارد. بدونش، هر شناسهٔ عددیِ دلخواه یک کلیدِ
    # `paneltry:` می‌ساخت — اندازه‌گیری‌شده: ۲۰۰ شناسه از یک IP، ۲۰۰ کلید.
    if not _is_admin_id(admin_id):
        return _login_page(error="نامعتبر.")
    tk = f"paneltry:{admin_id}"
    tries = await r.incr(tk)
    if tries == 1 or await r.ttl(tk) < 0:
        await r.expire(tk, _CODE_TTL)
    real = await r.get(f"panelcode:{admin_id}")
    # روی **بایت** مقایسه می‌شود، نه رشته: `secrets.compare_digest` روی strِ
    # غیرASCII `TypeError` می‌دهد (اجراشده) و `'۱۲۳۴۵۶'.isdigit()` صادق است، پس
    # فرمِ رشته‌ای یک کدِ با رقمِ فارسی را به ۵۰۰ تبدیل می‌کرد نه به «کد نادرست».
    ok = bool(real) and secrets.compare_digest(code.encode(), real.encode())
    if not ok:
        if tries >= _CODE_TRIES:
            # **کد** را می‌کشیم، نه اندپوینت را: کاربر یک کدِ تازه می‌گیرد و
            # بلافاصله ادامه می‌دهد، در حالی که مهاجم برای حدسِ بیشتر باید از
            # سقفِ درخواستِ کد رد شود.
            await r.delete(f"panelcode:{admin_id}", tk)
            return _login_page(error="کد سوخت؛ از نو کد بگیر.")
        return _login_page(step=2, admin_id=admin_id, sent=True, error="کد نادرست است.")
    await r.delete(f"panelcode:{admin_id}", tk)
    resp = web.HTTPFound("/")
    # secure را از اسکیمِ واقعی بگیر: روی HTTPِ ساده (بدونِ TLS/پروکسی) کوکیِ Secure
    # توسطِ مرورگر دور انداخته می‌شود → لوپِ بی‌پایانِ بازگشت به /login. پشتِ Cloudflare/
    # پروکسی، X-Forwarded-Proto=https کوکی را درست Secure می‌کند.
    https = request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    resp.set_cookie(_COOKIE, _make_session(int(admin_id)), max_age=_SESSION_TTL,
                    httponly=True, secure=https, samesite="Lax")
    raise resp


async def logout(_: web.Request) -> web.Response:
    resp = web.HTTPFound("/login")
    resp.del_cookie(_COOKIE)
    raise resp


async def dashboard(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    health = await _health(request.app)
    return _render("settings", admin_id=_session_admin(request), active="settings",
                   pill_ok=health["all_ok"], groups=_setting_groups(), meta=RUNTIME_KEYS,
                   enums=ENUM_VALUES, labels=ENUM_LABELS, longtext=LONGTEXT_KEYS,
                   gicon=_GROUP_ICON,
                   v=await _effective(),
                   health=health, saved=request.query.get("ok") == "1",
                   error=request.query.get("err", ""))


async def health_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    health = await _health(request.app)
    summary = await ck_pool.pool_summary(request.app["redis"])
    pool = [{"platform": p, "live": d["healthy"] + d["suspect"],
             "cd": d["cooldown"], "bad": d["invalid"]}
            for p, d in sorted(summary.items())]
    return _render("health", admin_id=_session_admin(request), active="health",
                   pill_ok=health["all_ok"], health=health, pool=pool)


async def users_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    try:
        page = max(0, int(request.query.get("page", "0")))
    except ValueError:
        page = 0
    data = await _users_cached(request.app, page, request.query.get("q", ""))
    done = {"block": "کاربر بلاک شد.", "unblock": "بلاکِ کاربر برداشته شد."}.get(
        request.query.get("done", ""), "")
    return _render("users", admin_id=_session_admin(request), active="users",
                   pill_ok=await _pill_ok(request.app), done=done, **data)


async def users_block(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    uid = (form.get("id") or "").strip()
    action = (form.get("action") or "").strip()
    page = (form.get("page") or "0").strip()
    q = (form.get("q") or "").strip()
    outcome = ""
    if uid.isdigit() and action in ("block", "unblock"):
        async with Sessionmaker() as db:
            u = await db.get(User, int(uid))
            if u and u.tg_user_id not in settings.admin_id_set:  # ادمین را نمی‌شود بلاک کرد
                u.is_blocked = (action == "block")
                await db.commit()
                outcome = action
                # پیش از ریدایرکت، وگرنه صفحهٔ بعدی نمای کهنه را نشان می‌دهد و
                # ادمین فکر می‌کند بلاک نگرفت.
                await _users_cache_bust(request.app.get("redis"))
    # بازسازیِ URL از فیلدهای امن (نه ret کاربر → بدونِ open-redirect)
    params = []
    if page.isdigit() and int(page):
        params.append(f"page={int(page)}")
    if q.isdigit():
        params.append(f"q={int(q)}")
    if outcome:
        params.append(f"done={outcome}")
    raise web.HTTPFound("/users" + ("?" + "&".join(params) if params else ""))


async def stats_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    rng = request.query.get("range", "7d")
    if rng not in _RANGE_DAYS:
        rng = "7d"
    return _render("stats", admin_id=_session_admin(request), active="stats",
                   pill_ok=await _pill_ok(request.app),
                   s=await _stats_cached(request.app, rng),
                   kindfa=_KIND_FA, opfa=_OP_FA)


# ── متن‌ها/لیبل‌ها (override زمانِ‌اجرا روی locales) ──────────────
#: از `langpack` می‌آید، نه از یک کپیِ دوم — همان فهرست که export/import هم
#: رویش کار می‌کند، وگرنه صفحه و فایل می‌توانند سرِ «کلیدها کدام‌اند» واگرا شوند.
_TEXT_KEYS = list(langpack.TEXT_KEYS)


async def _languages(refresh: bool = False) -> dict[str, str]:
    """پوستهٔ پنلی روی `i18n.available_languages()` — تازه‌سازی + همان فهرست.

    فهرست عمداً این‌جا **ساخته نمی‌شود**: از فاز C رباتْ هم همان را می‌خواهد
    (منوی انتخابِ زبان)، و `routers/` نمی‌تواند این ماژول را import کند
    (ایمیجِ ربات jinja2/cryptography ندارد). پس سازنده به `i18n` منتقل شد و
    این‌جا فقط `refresh_if_stale` می‌ماند که پنلی است — پنل میان‌افزارِ
    per-update ندارد که خودش تازه کند.

    تاریخچه: پیش از فاز B هر صفحه‌ای که زبان داشت یک تاپلِ هاردکدِ
    `("fa","en")` داشت (۷ تا در همین فایل).
    """
    if refresh:
        await textstore.refresh_if_stale()
    return await i18n_available_languages()


async def _pick_lang(raw: str | None) -> tuple[str, dict[str, str]]:
    """(زبانِ معتبر, فهرستِ زبان‌ها) — ناشناخته به `DEFAULT` می‌افتد."""
    langs = await _languages()
    code = (raw or "").strip()
    return (code if code in langs else i18n_DEFAULT), langs

# دسته‌بندیِ کلیدها بر اساسِ پیشوند (سگمنتِ پیش از اولین «_»)؛ هرچه نیفتد → «سایر».
_TEXT_CATS: list[tuple[str, set[str]]] = [
    ("🔘 دکمه‌ها و لیبل‌ها", {"btn"}),
    ("🎬 کپشنِ نتیجه", {"cl"}),
    ("⬇️ دانلود", {"dl"}),
    ("📊 پیشرفت و وضعیت", {"pr", "processing", "queued", "cancelling", "cancelled", "done", "failed"}),
    ("🎵 متادیتای صوت", {"meta"}),
    ("💧 واترمارک", {"wm"}),
    ("🖼 تصویر و ویدیو", {"rot", "rotate", "resize", "ocr", "shot", "trim", "speed",
                          "cover", "compress", "vjoin", "merge", "img", "zip"}),
    ("🗣 رونویسی", {"asr", "tr"}),
    ("🧾 کارت و پیام‌ها", {"detected", "card", "link", "limit", "too", "ask", "send",
                           "coming", "welcome", "choose", "language", "list"}),
]
_TEXT_CAT_TITLES = [t for t, _ in _TEXT_CATS] + ["🧩 سایر"]


def _text_default(lang: str, key: str) -> str:
    """پیش‌فرضِ یک کلید — از `i18n`، تا صفحه و ربات **یک** زنجیرهٔ fallback داشته باشند."""
    return default_text(lang, key)


def _text_cat_index(key: str) -> int:
    seg = key.split("_")[0]
    for i, (_title, prefixes) in enumerate(_TEXT_CATS):
        if seg in prefixes:
            return i
    return len(_TEXT_CATS)  # سایر


def _texts_groups(lang: str, q: str) -> list[dict]:
    """همهٔ کلیدها، دسته‌بندی‌شده. با جست‌وجو فقط تطبیق‌ها؛ دسته‌های خالی حذف می‌شوند."""
    ov = {k: v for (lg, k), v in textstore.snapshot().items() if lg == lang}
    ql = q.strip().lower()
    buckets: list[list[dict]] = [[] for _ in _TEXT_CAT_TITLES]
    for key in _TEXT_KEYS:
        override = ov.get(key)
        default = _text_default(lang, key)
        current = override if override is not None else default
        if ql and ql not in key.lower() and ql not in default.lower() and ql not in current.lower():
            continue
        buckets[_text_cat_index(key)].append(
            {"key": key, "default": default, "current": current, "overridden": override is not None})
    groups: list[dict] = []
    for title, items in zip(_TEXT_CAT_TITLES, buckets):
        if items:
            edited = sum(1 for i in items if i["overridden"])
            groups.append({"title": title, "items": items, "n": len(items),
                           "edited": edited, "open": bool(ql)})
    if groups and not any(g["open"] for g in groups):  # صفحه هیچ‌وقت خالی به‌نظر نرسد
        groups[0]["open"] = True
    return groups


def _texts_redirect(lang: str, q: str, **extra) -> web.HTTPFound:
    return _result("/texts", lang=lang, q=q, **extra)


async def texts_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    await textstore.refresh_if_stale()  # همیشه از DB تازه؛ نمای کهنه نده (باگِ ریست پس از update)
    lang, langs = await _pick_lang(request.query.get("lang"))
    q = request.query.get("q", "")
    groups = _texts_groups(lang, q)
    total = sum(g["n"] for g in groups)
    edited = sum(g["edited"] for g in groups)
    saved = {"1": "متن ذخیره شد (بی‌ری‌استارت اعمال شد).",
             "r": "به پیش‌فرض برگشت."}.get(request.query.get("ok", ""), "")
    return _render("texts", admin_id=_session_admin(request), active="texts",
                   pill_ok=await _pill_ok(request.app), lang_sel=lang, langs=langs, q=q,
                   groups=groups, total=total, edited=edited, saved=saved,
                   error=request.query.get("err", ""))


async def texts_save(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    langs = await _languages(refresh=True)
    raw_lang = (form.get("lang") or "").strip()
    lang = raw_lang if raw_lang in langs else i18n_DEFAULT
    key = (form.get("key") or "").strip()
    q = (form.get("q") or "").strip()
    value = (form.get("value") or "").replace("\r\n", "\n")
    # زبانِ ناشناخته و کلیدِ ناشناخته دو خطای متفاوت‌اند و باید متفاوت گفته شوند؛
    # پیش از این هر دو «کلیدِ نامعتبر» می‌گرفتند، یعنی پیام علتِ غلط را نام می‌برد.
    if raw_lang not in langs:
        raise _texts_redirect(lang, q, err=f"زبانِ ناشناخته: «{raw_lang}».")
    if key not in langpack.TEXT_KEYS:
        raise _texts_redirect(lang, q, err="کلیدِ نامعتبر.")
    default = _text_default(lang, key)
    if value.strip() == default.strip():  # برابرِ پیش‌فرض = حذفِ override
        await textstore.reset_text(lang, key)
        raise _texts_redirect(lang, q, ok="r")
    err = textstore.validate(default, value)
    if err:
        raise _texts_redirect(lang, q, err=err)
    await textstore.set_text(lang, key, value)
    raise _texts_redirect(lang, q, ok="1")


async def texts_reset(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    langs = await _languages(refresh=True)
    raw_lang = (form.get("lang") or "").strip()
    lang = raw_lang if raw_lang in langs else i18n_DEFAULT
    key = (form.get("key") or "").strip()
    q = (form.get("q") or "").strip()
    if raw_lang in langs and key:
        await textstore.reset_text(lang, key)
    raise _texts_redirect(lang, q, ok="r")


# ── چیدمان و استایلِ کلیدهای منوی کارت (per-kind) ──────────────
from .keyboards import FEATURED_TOP  # noqa: E402
from . import keyboards as _KB  # noqa: E402

_KIND_TABS = [("image", "🖼 تصویر"), ("video", "🎬 ویدیو"), ("audio", "🎵 صوت"),
              ("document", "📄 سند"), ("pdf", "📕 PDF"), ("archive", "🗜 آرشیو"), ("app", "📦 اپ")]
_KIND_LABEL = dict(_KIND_TABS)
_STYLE_CLS = {"primary": "blue", "success": "green", "danger": "red"}
_STYLE_HEX = {"primary": "#3b82f6", "success": "#22c55e", "danger": "#ef4444"}


def _btn_default_width(kind: str, op: str, first_op: str) -> str:
    return "full" if (kind in FEATURED_TOP and op == first_op) else "third"


def _menu_editor_items(kind: str, lang: str) -> list[dict]:
    """همهٔ کلیدهای منوی kind (شاملِ مخفی‌ها) به ترتیبِ ویرایش، با متن/رنگ/ایموجی/عرض/نمایش."""
    ops = OPS_BY_KIND.get(kind, [])
    key_by_op = dict(ops)
    first_op = ops[0][0] if ops else ""
    layout = textstore.get_menu_layout(kind)
    styles = textstore.button_snapshot()
    order: list[str] = []
    meta: dict[str, dict] = {}
    if layout:
        meta = {e["op"]: e for e in layout}
        seen = set()
        for e in layout:
            if e["op"] in key_by_op:
                order.append(e["op"])
                seen.add(e["op"])
        for op, _k in ops:
            if op not in seen:
                order.append(op)
    else:
        order = [op for op, _k in ops]
    items = []
    for op in order:
        key = key_by_op[op]
        st, em = styles.get(op, (None, None))
        e = meta.get(op)
        items.append({
            "op": op, "key": key,
            "text": textstore.get_override(lang, key) or _text_default(lang, key),
            "style": st or "", "emoji": em or "",
            "width": (e.get("width") if e else None) or _btn_default_width(kind, op, first_op),
            "hidden": bool(e.get("hidden")) if e else False,
        })
    return items


def _menu_preview(items: list[dict]) -> tuple[list[list[dict]], list[dict]]:
    """ردیف‌های پیش‌نمایش (فقط کلیدهای visible) + فهرستِ مخفی‌ها."""
    vis = [it for it in items if not it["hidden"]]
    sizes = _KB._rows_from_widths([it["width"] for it in vis])
    rows, i = [], 0
    for s in sizes:
        chunk = vis[i:i + s]
        rows.append([{"text": c["text"], "cls": _STYLE_CLS.get(c["style"], ""),
                      "color": _STYLE_HEX.get(c["style"], "")} for c in chunk])
        i += s
    return rows, [it for it in items if it["hidden"]]


async def buttons_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    await textstore.refresh_if_stale()  # همیشه از DB تازه؛ نمای کهنه نده (باگِ ریست پس از update)
    kind = request.query.get("kind", "video")
    if kind not in _KIND_LABEL:
        kind = "video"
    lang, langs = await _pick_lang(request.query.get("lang"))
    items = _menu_editor_items(kind, lang)
    pv_rows, hidden_items = _menu_preview(items)
    saved = {"1": "ذخیره شد (بی‌ری‌استارت اعمال شد).",
             "r": "به چیدمانِ پیش‌فرض برگشت."}.get(request.query.get("ok", ""), "")
    return _render("buttons", admin_id=_session_admin(request), active="buttons",
                   pill_ok=await _pill_ok(request.app), kind=kind, lang_sel=lang, langs=langs,
                   kinds=_KIND_TABS,
                   kindlabel=_KIND_LABEL[kind], items=items, pv_rows=pv_rows,
                   hidden_items=hidden_items, close_label=_t(lang, "btn_close"),
                   prev_msg="🎬 نمونهٔ کارتِ فایل", saved=saved,
                   error=request.query.get("err", ""))


async def buttons_save(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    kind = (form.get("kind") or "video").strip()
    lang = (form.get("lang") or "").strip()
    if kind not in _KIND_LABEL or lang not in await _languages(refresh=True):
        raise web.HTTPFound("/buttons")
    key_by_op = dict(OPS_BY_KIND.get(kind, []))
    order = [op for op in (form.get("order") or "").split(",") if op in key_by_op]
    for op, _k in OPS_BY_KIND.get(kind, []):  # هر opِ جاافتاده را ته اضافه کن
        if op not in order:
            order.append(op)
    # **اول همه را بسنج، بعد بنویس.** پیش از این، اعتبارسنجی و نوشتن در یک حلقه
    # بودند و شاخهٔ `elif` هر متنی را که `validate()` رد می‌کرد به «حذفِ override»
    # ترجمه می‌کرد — یعنی یک تایپ در placeholder، برچسبِ سالمِ قبلی را پاک می‌کرد
    # و صفحه بنرِ **سبز** نشان می‌داد. حالا سه چیز از هم جدا شده‌اند: «مقدارِ
    # معتبر» و «خالی/برابرِ پیش‌فرض → حذفِ عمدی» و «نامعتبر → خطا».
    #
    # اتمیک است نه جزئی: فرم کلِ منو را یک‌جا می‌فرستد، پس «۱۱ تا از ۱۲ تا ذخیره
    # شد» خودش یک شکستِ نیمه‌خاموشِ دیگر است — ادمین نمی‌تواند بگوید کدام یکی جا
    # ماند. یا همه اعمال می‌شود یا هیچ‌کدام، با دلیل.
    layout, styles, texts, errors = [], {}, [], []
    for op in order:
        layout.append({"op": op, "hidden": form.get(f"show_{op}") != "on",
                       "width": textstore.clean_width(form.get(f"width_{op}", "third"))})
        styles[op] = textstore.clean_button(form.get(f"style_{op}", ""), form.get(f"emoji_{op}", ""))
        key = key_by_op[op]
        val = (form.get(f"text_{op}") or "").replace("\r\n", "\n").strip()
        default = _text_default(lang, key)
        if not val or val == default.strip():   # خالی یا برابرِ پیش‌فرض = حذفِ override
            texts.append((key, None))
            continue
        err = textstore.validate(default, val)
        if err:
            errors.append(f"«{default}»: {err}")
        else:
            texts.append((key, val))
    if errors:
        # هیچ نوشتنی انجام نشده — نه چیدمان، نه رنگ، نه متن.
        raise _result("/buttons", kind=kind, lang=lang, err=" · ".join(errors[:3]))
    for key, val in texts:
        cur = textstore.get_override(lang, key)   # فقط وقتی واقعاً عوض شده، تا bumpِ بی‌خود نزنیم
        if val is None:
            if cur is not None:
                await textstore.reset_text(lang, key)
        elif cur != val:
            await textstore.set_text(lang, key, val)
    await textstore.set_menu_layout(kind, layout)
    await textstore.set_button_styles(styles)
    raise _result("/buttons", kind=kind, lang=lang, ok="1")


async def buttons_reset(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    kind = (form.get("kind") or "video").strip()
    lang, _ = await _pick_lang(form.get("lang"))
    if kind in _KIND_LABEL:
        await textstore.reset_menu_layout(kind)
    raise _result("/buttons", kind=kind, lang=lang, ok="r")


# ── زبان‌ها: export/import بستهٔ ترجمه ──────────────────────────
#: پیام‌های موفقیتِ `/langs` (همان الگوی `saved` در بقیهٔ صفحه‌ها).
_LANG_OK = {
    "i": "بستهٔ زبان import شد (بی‌ری‌استارت اعمال شد).",
    "d": "زبان حذف شد.",
}


def _lang_rows(langs: dict[str, str]) -> list[dict]:
    """یک ردیف به‌ازای هر زبان، با پوششِ **محاسبه‌شده** نه برچسبِ ثابت."""
    total = len(langpack.TEXT_KEYS)
    rows = []
    for code, name in langs.items():
        builtin = code in BUILTIN_NAMES
        # زبانِ داخلی کاتالوگِ کد دارد، پس پوششش طبقِ تعریف کامل است؛ زبانِ
        # افزوده فقط به‌اندازهٔ ردیف‌هایش ترجمه دارد و بقیه به انگلیسی می‌افتد.
        done = total if builtin else len(textstore.lang_texts(code))
        rows.append({"code": code, "name": name, "builtin": builtin,
                     "done": done, "total": total,
                     "pct": done * 100 // total if total else 0})
    return rows


async def _langs_render(request, *, error: str = "", review=None,
                        raw: str = "", replace: bool = False, confirm: str = "") -> web.Response:
    langs = await _languages()
    return _render("langs", admin_id=_session_admin(request), active="langs",
                   pill_ok=await _pill_ok(request.app), langs=langs,
                   rows=_lang_rows(langs), default_lang=i18n_DEFAULT,
                   total=len(langpack.TEXT_KEYS), rv=review, raw=raw,
                   replace=replace, confirm=confirm,
                   saved=_LANG_OK.get(request.query.get("ok", ""), ""), error=error)


async def langs_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    await textstore.refresh_if_stale()
    return await _langs_render(request)


async def langs_export(request: web.Request) -> web.Response:
    """بستهٔ ترجمه برای دادن به یک چت‌بات. همین شکل دوباره import می‌شود."""
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    await textstore.refresh_if_stale()
    langs = await _languages()
    try:
        code = langpack.normalize_code(request.query.get("lang", ""))
    except langpack.PackError as exc:
        return await _langs_render(request, error=str(exc))
    source = request.query.get("source", "") or i18n_DEFAULT
    if source not in langs:
        source = i18n_DEFAULT
    name = (request.query.get("name", "") or "").strip() or langs.get(code) or code
    pack = langpack.build_pack(
        lang=code, name=name, source=source,
        texts=langpack.effective_texts(source, textstore.lang_texts(source)))
    return web.Response(
        text=pack, content_type="application/json", charset="utf-8",
        headers={"Content-Disposition": f'attachment; filename="telabzar-{code}.json"'})


async def langs_import(request: web.Request) -> web.Response:
    """بستهٔ چسبانده‌شده → سنجش → (تأیید برای زبانِ پیش‌فرض) → نوشتن.

    اتمیک: اگر حتی یک کلید خطا داشته باشد **هیچ‌چیز** نوشته نمی‌شود و فهرستِ
    کلید+دلیل برمی‌گردد، تا ادمین همان فهرست را به چت‌بات بدهد و دوباره بچسباند.
    """
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    await textstore.refresh_if_stale()
    form = await request.post()
    raw = str(form.get("pack") or "")
    replace = form.get("replace") == "on"
    langs = await _languages()

    try:
        pack = langpack.parse_pack(raw)
        code = langpack.normalize_code(str(form.get("lang") or "") or pack.get("lang") or "")
        # کدِ فرم حاکم است و کدِ داخلِ فایل فقط **مقایسه** می‌شود: یک چت‌بات
        # می‌تواند `"lang": "es"` را بی‌خبر به چیزِ دیگری عوض کند، و آن‌وقت
        # ترجمه زیرِ زبانِ اشتباه می‌نشیند بدونِ هیچ نشانه‌ای.
        in_file = str(pack.get("lang") or "")
        if in_file and langpack.normalize_code(in_file) != code:
            raise langpack.PackError(
                f"کدِ زبانِ داخلِ فایل («{in_file}») با کدِ فرم («{code}») یکی نیست.")
    except langpack.PackError as exc:
        return await _langs_render(request, error=str(exc), raw=raw, replace=replace)

    name = (str(form.get("name") or "").strip()
            or str(pack.get("name") or "").strip() or langs.get(code) or code)
    source = str(pack.get("source") or i18n_DEFAULT)
    rv = langpack.review(
        pack,
        source_texts=langpack.effective_texts(source, textstore.lang_texts(source)),
        current=langpack.effective_texts(code, textstore.lang_texts(code)))
    rv.name = name
    if not rv.ok:
        return await _langs_render(request, review=rv, raw=raw, replace=replace)

    # زبانِ **پیش‌فرض** تأییدِ صریح می‌خواهد: یک پیست می‌تواند کلِ رابطِ فارسی را
    # عوض کند، و برخلافِ زبان‌های دیگر این‌جا هیچ نسخهٔ «قبلی»ای در کاتالوگ نیست
    # که بشود با یک reset برگشت. برای بقیهٔ زبان‌ها لازم نیست.
    if code == i18n_DEFAULT and form.get("confirm") != "yes":
        return await _langs_render(request, review=rv, raw=raw, replace=replace, confirm="ask")

    if code not in BUILTIN_NAMES:
        await textstore.add_language(code, name)
    await textstore.set_texts(code, rv.entries, replace=replace)
    raise _result("/langs", ok="i")


async def langs_delete(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    code = str(form.get("code") or "").strip()
    if code in BUILTIN_NAMES:
        return await _langs_render(request, error="زبانِ داخلی حذف‌شدنی نیست.")
    await textstore.remove_language(code)
    raise _result("/langs", ok="d")


# ── نودهای توزیع‌شده (master/node روی WireGuard) ────────────────
#: توکنِ joinِ تازه‌ساخته، برای **نمایشِ یک‌بارهٔ** همان ادمین. کلید به شناسهٔ
#: ادمین بسته است، پس نه در URL می‌رود نه با شناسهٔ حدس‌زدنی قابلِ برداشتن است.
_JOIN_VIEW = "njoinview:"
_JOIN_VIEW_TTL = 1800           # هم‌اندازهٔ عمرِ خودِ توکن


async def _stash_join_view(redis, admin_id: int | None, token: str) -> None:
    if admin_id:
        await redis.set(f"{_JOIN_VIEW}{admin_id}", token, ex=_JOIN_VIEW_TTL)


async def _take_join_view(redis, admin_id: int | None) -> str:
    """توکن را برای نمایش برمی‌دارد و **مصرفش می‌کند**.

    `getdel` عمدی است: دستورِ نصب یک‌بار نشان داده می‌شود و رفرشِ صفحه دوباره
    نشانش نمی‌دهد. اگر ادمین قبل از کپی رفرش کند باید دکمه را دوباره بزند —
    قیمتِ کوچکی برای اینکه یک رازِ زنده در تاریخچهٔ مرورگر و در بافرِ صفحه
    نماند.
    """
    if not admin_id:
        return ""
    try:
        return await redis.getdel(f"{_JOIN_VIEW}{admin_id}") or ""
    except Exception:  # noqa: BLE001
        return ""


async def nodes_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    live = await node_mod.list_live(request.app["redis"])
    async with Sessionmaker() as s:
        rows = (await s.execute(select(Node))).scalars().all()
    items = []
    for n in rows:
        hb = live.get(n.id) or {}
        role = node_mod.ROLES.get(n.role, {})
        items.append({"id": n.id, "name": n.name, "role": n.role,
                      "role_label": role.get("label", n.role), "emoji": role.get("emoji", "🖧"),
                      "wg_ip": n.wg_ip, "online": bool(hb), "load": hb.get("load", 0),
                      "ver": hb.get("ver", "—"), "done": hb.get("done", 0)})
    token = await _take_join_view(request.app["redis"], _session_admin(request))
    base = settings.admin_base or (settings.public_base or "")
    install_cmd = f"curl -fsSL {base}/node/install.sh | sudo bash -s -- {token}" if token else ""
    master_ready = bool(settings.wg_master_pubkey and settings.wg_endpoint and base)
    reaped = await node_mod.reaped_count(request.app["redis"])
    return _render("nodes", admin_id=_session_admin(request), active="nodes",
                   pill_ok=await _pill_ok(request.app), nodes=items,
                   online=sum(1 for i in items if i["online"]), roles=node_mod.ROLES,
                   token=token, install_cmd=install_cmd, master_ready=master_ready,
                   reaped=reaped, error=request.query.get("err", ""))


async def nodes_add(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    role = (form.get("role") or "").strip()
    if role not in node_mod.ROLES:
        raise _result("/nodes", err="نقشِ نامعتبر.")
    # فرم از روزِ اول یک فیلدِ «نامِ نود» داشت و این هندلر هرگز نمی‌خواندش: نامِ
    # واقعی از POSTِ خودِ نود می‌آمد (`hostname -s` در `node/install.sh`)، پس
    # هرچه ادمین می‌نوشت بی‌صدا دور ریخته می‌شد و نودِ تازه با نامی غیر از آنچه
    # خواسته بود ظاهر می‌شد — و راهِ تغییرِ نام هم وجود ندارد.
    name = (form.get("name") or "").strip()[:node_mod.NAME_MAX]
    tok = await node_mod.make_join_token(request.app["redis"], role, name=name)
    # **هرگز در query string.** توکن یک‌بارمصرف است ولی تا مصرف‌شدن معتبر است، و
    # لاگِ دسترسیِ aiohttp مسیر را با query می‌نویسد (`%r`) — یعنی راز مستقیم به
    # `docker compose logs admin` می‌رود. لاگِ تولید نشان داد از ۹ خطِ `tok=`،
    # هشت‌تا `Referer` هم داشتند، پس same-origin تکثیرش هم می‌کرد.
    await _stash_join_view(request.app["redis"], _session_admin(request), tok)
    raise web.HTTPFound("/nodes")


async def nodes_remove(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    nid = (form.get("id") or "").strip()
    async with Sessionmaker() as s:
        n = await s.get(Node, nid)
        if n is not None:
            node_mod.remove_peer(n.wg_pubkey)  # peerِ WireGuard را بردار
            await s.delete(n)
            await s.commit()
    try:
        await request.app["redis"].delete(f"node:{nid}")
    except Exception:  # noqa: BLE001
        pass
    raise web.HTTPFound("/nodes")


# ── APIِ عمومیِ join (توکن گِیت است؛ نود قبل از WG صدایش می‌زند) ──
async def node_join(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad json"}, status=400)
    token = (data.get("token") or "").strip()
    pubkey = (data.get("pubkey") or "").strip()
    name = (data.get("name") or "").strip()[:64]
    # اعتبارسنجی **پیش از** مصرف. برعکسش یعنی یک درخواستِ ناقص — یا یک ریتریِ
    # نصب‌کننده روی خطای گذرا — توکن را می‌سوزاند، و نودِ واقعی بعدش
    # «invalid or used token» می‌گیرد بی‌آنکه بفهمد چرا. مصرف باید آخرین کاری
    # باشد که پیش از پذیرش انجام می‌شود، نه اولین.
    if not pubkey or len(pubkey) > 64:
        return web.json_response({"error": "missing pubkey"}, status=400)
    payload = await node_mod.consume_join_token(request.app["redis"], token)
    if payload is None:
        return web.json_response({"error": "invalid or used token"}, status=403)
    role = payload["role"]
    # نامی که ادمین در پنل نوشته بر نامِ خودگزارشِ نود مقدم است: عمدی و صریح
    # انتخاب شده، در برابرِ `hostname -s` که صرفاً fallback است.
    chosen = (payload.get("name") or "").strip() or name
    async with Sessionmaker() as s:
        used = {ip for (ip,) in (await s.execute(select(Node.wg_ip))).all()}
        ip = node_mod.next_wg_ip(used)
        if ip is None:
            return web.json_response({"error": "wg subnet full"}, status=507)
        nid = secrets.token_urlsafe(9)[:12]
        s.add(Node(id=nid, name=chosen or f"{role}-{nid[:4]}", role=role,
                   wg_ip=ip, wg_pubkey=pubkey))
        await s.commit()
    node_mod.add_peer(pubkey, ip)  # peer را به WGِ مستر اضافه کن (روی سرورِ واقعی)
    cfg = node_mod.node_config(role, ip)
    cfg["node_id"] = nid
    return web.json_response(cfg)


async def node_install(request: web.Request) -> web.Response:
    """اسکریپتِ نصبِ نود؛ عمومی (توکن گِیتِ واقعی است). baseِ مستر تزریق می‌شود."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "node", "install.sh")
    try:
        with open(os.path.abspath(path), encoding="utf-8") as fh:
            script = fh.read()
    except OSError:
        return web.Response(text="# install script not found", status=404)
    base = settings.admin_base or settings.public_base or ""
    script = script.replace("__MASTER_BASE__", base)
    return web.Response(text=script, content_type="text/plain")


async def node_peers(request: web.Request) -> web.Response:
    """پیکربندیِ [Peer]های WG از رویِ جدولِ Node (منبعِ حقیقت). هاست‌سایدِ `wg-sync`
    این را می‌گیرد و به [Interface]ِ ثابتِ مستر می‌چسباند + `wg syncconf`. با NODE_SECRET
    (یا BOT_TOKEN) گِیت می‌شود — روی WG/لوکال صدا زده می‌شود، نه عمومی."""
    # فقط هدر. قبلاً `?key=` هم پذیرفته می‌شد، ولی رازی که در query string برود
    # در لاگِ دسترسی و هر پروکسیِ میانی ثبت می‌شود؛ هدر این ردپا را نمی‌گذارد.
    # تنها کلاینتِ این endpoint هاست‌سایدِ `node/wg-sync.sh` است که با همین کامیت
    # به هدر سوییچ کرد — سمتِ سرور را تنها ببندی، دفعهٔ بعد که نودی اضافه شود
    # peerها بی‌صدا نمی‌آیند و نود آفلاین می‌ماند.
    key = request.headers.get("X-Node-Key") or ""
    secret = settings.node_secret or settings.bot_token or ""
    if not secret or not hmac.compare_digest(key, secret):
        return web.Response(text="# forbidden\n", status=403)
    async with Sessionmaker() as s:
        rows = (await s.execute(select(Node.wg_pubkey, Node.wg_ip))).all()
    peers = [(pk, ip) for (pk, ip) in rows if pk and ip]
    return web.Response(text=node_mod.render_peers(peers), content_type="text/plain")


_STATUS_FA = {ck_pool.HEALTHY: "سالم", ck_pool.SUSPECT: "مشکوک", ck_pool.INVALID: "باطل — نیازِ تعویض",
              ck_pool.COOLDOWN: "کنارگذاشته", ck_pool.DISABLED: "غیرفعال",
              ck_pool.FROZEN: "چک‌پوینت — نیازِ انسان",
              ck_pool.UNPROVEN: "آخرین تلاش ناموفق"}
_STATUS_BADGE = {ck_pool.HEALTHY: "ok", ck_pool.SUSPECT: "warn", ck_pool.INVALID: "err",
                 ck_pool.COOLDOWN: "warn", ck_pool.DISABLED: "dim",
                 ck_pool.FROZEN: "err", ck_pool.UNPROVEN: "warn"}
#: کلاسِ وضعیتِ **ناشناخته**. عمداً `dim` نیست: `dim` معنیِ تثبیت‌شده‌ای دارد
#: («ادمین خودش غیرفعالش کرد») و یکی‌کردنشان یعنی وضعیتی که نمی‌شناسیم دقیقاً
#: شبیهِ یک تصمیمِ عمدی دیده شود.
_BADGE_UNKNOWN = "unk"


def _badge_of(status: str) -> str:
    """کلاسِ بجِ یک وضعیتِ اکانت — **تنها** جایی که پیش‌فرض تعریف می‌شود.

    پیش از این `_STATUS_BADGE.get(..., "mute")` در **دو** محلِ فراخوانی نوشته
    شده بود، و `mute` هیچ‌جا در CSS تعریف نشده بود — یعنی همان الگوی «قاعده در
    N نقطه دست‌نویس شده» که §۷ بارها ثبت کرده، این‌بار با هر دو کپی خراب.
    """
    return _STATUS_BADGE.get(status, _BADGE_UNKNOWN)


def _ago_fa(ts: int) -> str:
    """«۴ دقیقه پیش» — برای زمانِ آخرین موفقیت/افزودن."""
    if not ts:
        return "—"
    d = max(0, int(time.time()) - int(ts))
    if d < 60:
        return "همین الان"
    if d < 3600:
        return f"{d // 60} دقیقه پیش"
    if d < 86400:
        return f"{d // 3600} ساعت پیش"
    return f"{d // 86400} روز پیش"


async def cookies_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    redis = request.app["redis"]
    lim = await ck_pool.load_limits()   # سهمیهٔ زنده (از /settings) — یک‌بار برای کلِ صفحه
    accounts = await ck_pool.accounts(redis, lim=lim)
    # نودهای موجود برای پینِ خروجی (هویتِ سشن = کوکی + IP + UA)
    async with Sessionmaker() as db:
        node_rows = (await db.execute(select(Node))).scalars().all()
    nodes = [{"id": n.id, "name": f"{n.name} · {n.role}"} for n in node_rows]
    node_names = {n["id"]: n["name"] for n in nodes}
    # گروه‌بندی per-platform (به ترتیبِ ثابتِ COOKIE_PLATFORMS)
    by_platform: dict[str, list[dict]] = {}
    for a in accounts:
        item = {**a, "status_fa": _STATUS_FA.get(a["status"], a["status"]),
                "badge": _badge_of(a["status"]),
                "last_ok_fa": _ago_fa(a.get("last_ok") or 0),
                "added_fa": _ago_fa(a.get("added") or 0),
                "used": await ck_pool.usage(redis, a["name"]),
                "budget": ck_pool.budget_of(a, None, lim),
                "warming": ck_pool.warmup_factor(int(a.get("added") or 0), None, lim) < 1.0,
                # متنِ خطا تا امروز ذخیره می‌شد ولی هیچ‌جا دیده نمی‌شد — همان چیزی
                # که ادمین برای فهمیدنِ «چرا کار نمی‌کند» لازم دارد.
                "err_txt": (a.get("last_error") or "")[:150],
                "err_fa": _ago_fa(a.get("last_error_at") or 0),
                "node_id": a.get("node_id") or "", "proxy": a.get("proxy") or "",
                "user_agent": a.get("user_agent") or "",
                "node_name": node_names.get(a.get("node_id") or "", a.get("node_id") or "")}
        by_platform.setdefault(a.get("platform") or "other", []).append(item)
    groups = []
    for key, _fa in COOKIE_PLATFORMS:
        items = by_platform.pop(key, [])
        if items:
            groups.append({"platform": key, "items": items, "total": len(items),
                           "healthy": sum(1 for i in items
                                          if i["status"] in ck_pool.USABLE)})
    for key, items in by_platform.items():  # پلتفرم‌های خارج از فهرست
        groups.append({"platform": key, "items": items, "total": len(items),
                       "healthy": sum(1 for i in items
                                      if i["status"] in ck_pool.USABLE)})
    # صفِ رسیدگی: فریزشده (چک‌پوینت/۲FA) یا باطل — با تلاشِ خودکار درست نمی‌شوند
    attention = [{**a, "status_fa": _STATUS_FA.get(a["status"], a["status"]),
                  "badge": _badge_of(a["status"])}
                 for a in accounts if a["status"] in (ck_pool.FROZEN, ck_pool.INVALID)]
    msg = {"up": "اکانت اضافه شد.", "del": "اکانت حذف شد.", "rep": "کوکی جایگزین شد.",
           "cd": "وضعیتِ اکانت به‌روزرسانی شد.",
           "fix": "اکانت به چرخش برگشت.",
           "ident": "هویتِ اکانت ذخیره شد.",
           "sync": "آینهٔ کوکی‌ها همگام شد."}.get(request.query.get("ok", ""), "")
    dl_node = await node_mod.role_online(redis, "download")
    mirrored = 0
    try:
        mirrored = await redis.scard(_CK_SET)
    except Exception:  # noqa: BLE001
        pass
    # آینه باید دقیقاً به‌اندازهٔ فایل‌های روی دیسک باشد؛ اگر نیست، نودِ دانلود
    # بخشی از اکانت‌ها را اصلاً نمی‌بیند و علتش هم بی‌سروصدا می‌ماند.
    disk_count = len(glob.glob(os.path.join(settings.cookies_dir, "*.txt"))) \
        if settings.cookies_dir and os.path.isdir(settings.cookies_dir) else 0
    exits = await ck_pool.exit_stats(redis)
    return _render("cookies", admin_id=_session_admin(request), active="cookies",
                   pill_ok=await _pill_ok(request.app), groups=groups,
                   platforms=COOKIE_PLATFORMS, dir_ok=_cookies_dir_ok(),
                   attention=attention, nodes=nodes,
                   cookies_dir=settings.cookies_dir, saved=msg,
                   error=request.query.get("err", ""),
                   dl_node_online=dl_node, mirrored=mirrored,
                   disk_count=disk_count, exits=exits, pfa=PLATFORM_LABELS,
                   mirror_gap=bool(disk_count and disk_count != mirrored))


# ── آینهٔ کوکی در Redis (تا نودِ دانلود که دیسکِ کوکیِ مستر را ندارد هم ببیندشان) ──
# کلیدها باید با `tasks_download._CK_SET`/`_CK_CONTENT` هماهنگ بمانند.
_CK_SET = "ckfiles"
_CK_CONTENT = "ckfile:"


# این توابع به `app/cookies.py` منتقل شدند (رباتْ هم برای پیستِ داخلِ تلگرام لازمشان
# دارد و نباید به فرآیندِ پنل وابسته باشد). نام‌های محلی برای سازگاریِ صداکننده‌ها:
_REQUIRED_COOKIE = ck_pool._REQUIRED_COOKIE
_looks_like_cookiejar = ck_pool._looks_like_cookiejar
_json_to_netscape = ck_pool._json_to_netscape
_normalize_cookie_text = ck_pool._normalize_cookie_text
_check_required = ck_pool._check_required
_save_cookie = ck_pool._save_cookie
_mirror_cookie = ck_pool._mirror_cookie
_unmirror_cookie = ck_pool._unmirror_cookie


async def _mirror_all_cookies(redis) -> None:
    """آینهٔ Redis را با فایل‌های روی دیسک هماهنگ می‌کند (self-heal روی استارتِ پنل —
    اگر Redis flush شده باشد یا فایلی بیرون از پنل عوض شده باشد)."""
    d = settings.cookies_dir
    if redis is None or not d or not os.path.isdir(d):
        return
    try:
        disk = {os.path.basename(f): f for f in glob.glob(os.path.join(d, "*.txt"))}
        try:
            mirrored = {(n if isinstance(n, str) else n.decode())
                        for n in await redis.smembers(_CK_SET)}
        except Exception:  # noqa: BLE001
            mirrored = set()
        for stale in mirrored - set(disk):
            await _unmirror_cookie(redis, stale)
        for name, path in disk.items():
            try:
                with open(path, encoding="utf-8") as fh:
                    await _mirror_cookie(redis, name, fh.read())
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass


# کوکیِ «کلیدی» هر پلتفرم — اگر در متنِ چسبانده‌شده نباشد، همان لحظه خطا می‌دهیم
# (به‌جای اینکه فردا وسطِ کارِ کاربر معلوم شود). یوتیوب: LOGIN_INFO همان سیگنالی است
# که خودِ yt-dlp برای «کوکیِ لاگین‌شده» چک می‌کند — و چکش رایگان است (بدونِ شبکه).


async def cookies_identity(request: web.Request) -> web.Response:
    """پینِ هویتِ اکانت: خروجی (نود) + پروکسیِ اختصاصی + User-Agent."""
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    name = os.path.basename((form.get("name") or "").strip())
    if not name:
        raise web.HTTPFound("/cookies")
    redis = request.app["redis"]
    meta = await ck_pool.get_meta(redis, name)
    meta["node_id"] = (form.get("node_id") or "").strip()[:24]
    meta["proxy"] = (form.get("proxy") or "").strip()[:200]
    meta["user_agent"] = (form.get("user_agent") or "").strip()[:300]
    await ck_pool.set_meta(redis, name, meta)
    raise _result("/cookies", ok="ident")


async def cookies_resync(request: web.Request) -> web.Response:
    """آینهٔ Redis را دوباره از روی دیسک بساز — نودِ دانلود فقط همین را می‌بیند."""
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    await _mirror_all_cookies(request.app["redis"])
    raise _result("/cookies", ok="sync")


async def cookies_unfreeze(request: web.Request) -> web.Response:
    """ادمین رسیدگی کرد → اکانت از صفِ «نیازمندِ انسان» بیرون و واردِ چرخش می‌شود."""
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    name = os.path.basename((form.get("name") or "").strip())
    redis = request.app["redis"]
    if name:
        await ck_pool.unfreeze(redis, name)
        try:
            await redis.delete(f"ckcheck:{name}")   # هشدارِ بعدی دوباره مجاز شود
        except Exception:  # noqa: BLE001
            pass
    raise _result("/cookies", ok="fix")


async def cookies_add(request: web.Request) -> web.Response:
    """افزودنِ اکانت با **چسباندنِ متنِ کوکی** (بدونِ آپلودِ فایل)."""
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    if not _cookies_dir_ok():
        raise _result("/cookies", err="پوشهٔ کوکی‌ها نوشتنی نیست.")
    form = await request.post()
    platform = (form.get("platform") or "other").strip()
    label = (form.get("label") or "").strip()
    text, err = _normalize_cookie_text(form.get("content") or "")
    if err:
        raise _result("/cookies", err=err)
    if platform not in {k for k, _ in COOKIE_PLATFORMS}:
        platform = "other"
    err = _check_required(text, platform)
    if err:
        raise _result("/cookies", err=err)
    # نامِ فایل با پیشوندِ پلتفرم (استخر با همین پلتفرم را تشخیص می‌دهد)
    stem = platform if platform != "other" else "cookies"
    if label:
        stem += "_" + label
    name = _safe_cookie_name(stem) or "cookies.txt"
    if os.path.exists(os.path.join(settings.cookies_dir, name)):
        name = _safe_cookie_name(f"{stem}_{secrets.token_hex(2)}") or name
    redis = request.app["redis"]
    err = await _save_cookie(redis, name, text)
    if err:
        raise _result("/cookies", err=err)
    meta = await ck_pool.get_meta(redis, name)
    meta.update({"label": label or os.path.splitext(name)[0], "platform": platform,
                 "added": int(time.time()), "fail_streak": 0, "disabled": False})
    await ck_pool.set_meta(redis, name, meta)
    log.info("cookie account added: %s (%d bytes)", name, len(text))
    raise _result("/cookies", ok="up")


async def cookies_replace(request: web.Request) -> web.Response:
    """جایگزینیِ **درجای** کوکیِ یک اکانت (برچسب/تاریخچه حفظ، خطاها صفر می‌شوند)."""
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    if not _cookies_dir_ok():
        raise _result("/cookies", err="پوشهٔ کوکی‌ها نوشتنی نیست.")
    form = await request.post()
    name = _safe_cookie_name(form.get("name") or "")
    text, err = _normalize_cookie_text(form.get("content") or "")
    if not name or err:
        raise _result("/cookies", err=err or "اکانت نامعتبر.")
    redis = request.app["redis"]
    meta = await ck_pool.get_meta(redis, name)
    err = _check_required(text, meta.get("platform") or ck_pool.guess_platform(name))
    if err:
        raise _result("/cookies", err=err)
    err = await _save_cookie(redis, name, text)
    if err:
        raise _result("/cookies", err=err)
    await ck_pool.mark_ok(redis, name)      # کوکیِ تازه → سالم + کول‌داون پاک
    log.info("cookie replaced for %s", name)
    raise _result("/cookies", ok="rep")


async def cookies_delete(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    name = _safe_cookie_name(form.get("name") or "")
    if name:
        # هر سه گام (آینه + فایل + متا) از یک جا — همان تابعِ مشترکِ مسیرِ ربات
        await ck_pool.delete_account(request.app["redis"], name)
    raise _result("/cookies", ok="del")


async def cookies_cooldown(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    name = _safe_cookie_name(form.get("name") or "")
    action = (form.get("action") or "").strip()
    if name and settings.cookies_dir and os.path.isfile(os.path.join(settings.cookies_dir, name)):
        r = request.app["redis"]
        try:
            if action == "clear":
                await r.delete(f"ckcd:{name}")
            elif action == "set":
                await r.set(f"ckcd:{name}", "1", ex=1800)
        except Exception:  # noqa: BLE001
            pass
    raise _result("/cookies", ok="cd")


async def save(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    store = settings_store.get_store()
    # فقط کلیدهایی که در فرم رندر شده‌اند (بقیه از /admin مدیریت می‌شوند و نباید ریست شوند)
    # **همان منبعی که صفحه از آن رندر شد** — نه `GROUPS`ِ خام. وگرنه ردیفِ
    # خودکار روی صفحه دیده می‌شود و این‌جا در `rendered` نیست، یعنی مقدارِ
    # تایپ‌شده بی‌صدا دور ریخته می‌شود و بنرِ سبز می‌آید.
    rendered = {key for _title, fields in _setting_groups() for key, _l, _h in fields}
    # **اول همه را بسنج، بعد بنویس** — مثلِ `/buttons`. پیش از این، هر مقدارِ
    # نامعتبر با یک `continue` بی‌صدا دور ریخته می‌شد و صفحه بی‌قیدوشرط بنرِ
    # سبز می‌داد: ادمین «۱٬۰۰۰» می‌نوشت، «ذخیره شد» می‌دید، و مقدارِ قبلی
    # همچنان برقرار بود. هیچ کرانی هم نبود، پس `max_file_mb = -1` پذیرفته و
    # ذخیره و بازنمایش می‌شد انگار تنظیمی عمدی است.
    pending, errors = [], []
    for k in sorted(rendered):
        kind, default = RUNTIME_KEYS[k]
        if kind == "bool":
            val = "on" if form.get(k) == "on" else "off"
            changed = (val == "on") != bool(default)
        else:
            val = (form.get(k) or "").strip()
            err = settings_store.validate_value(k, val)
            if err:
                errors.append(err)
                continue
            changed = str(val) != str(default)
        pending.append((k, val, changed))
    if errors:
        raise _result("/", err=" · ".join(errors[:3]))
    if store is not None:
        for k, val, changed in pending:
            if changed:
                await store.set(k, val)
            else:
                await store.reset(k)
    raise _result("/", ok="1")


async def healthz(_: web.Request) -> web.Response:
    return web.Response(text="ok")


#: پیامِ «کنسول ساخته نشده» — یک رشته، تا هم هندلر و هم تست یک منبع داشته باشند.
_CONSOLE_MISSING = (
    "کنسول ساخته نشده است. روی همین ماشین: cd panel && npm ci && npm run export:panel\n"
    "در تولید، مرحلهٔ Node در docker/admin.Dockerfile این کار را می‌کند."
)


def _console_target(tail: str) -> tuple[pathlib.Path, bool] | None:
    """`(مسیر, HTMLاست؟)` برای یک زیرمسیرِ کنسول، یا `None` اگر نبود.

    خروجیِ Next با `trailingSlash` هر صفحه را به‌شکلِ `<slug>/index.html`
    می‌دهد، پس بدونِ این تبدیل، `/console/health/` به یک **دایرکتوری** می‌رسد
    و aiohttp برایش ۴۰۳/۴۰۴ می‌دهد — یعنی هر صفحه‌ای جز خانه ۴۰۴ می‌شد.

    گاردِ پیمایش با `resolve()` + `is_relative_to` است نه با فیلترِ `..`:
    فیلترِ رشته‌ای فرم‌های encode‌شده و symlink را نمی‌گیرد، و این هندلر
    مسیرِ کنترل‌شدهٔ کاربر را مستقیم به فایل‌سیستم می‌دهد.
    """
    root = pathlib.Path(_CONSOLE_DIR).resolve()
    try:
        p = (root / tail.strip("/")).resolve()
    except OSError:
        return None
    if p != root and not p.is_relative_to(root):
        return None
    if p.is_file():
        return p, p.suffix.lower() in (".html", ".htm")
    idx = p / "index.html"
    if idx.is_file():
        return idx, True
    return None


async def console_page(request: web.Request) -> web.Response:
    """`/console/...` — کنسولِ Next، پشتِ همان نشستِ Fernetِ بقیهٔ پنل.

    **فقط HTML گِیت دارد، نه دارایی‌ها.** فایل‌های `_next/`/فونت JS/CSSِ
    ایستا هستند و هیچ دادهٔ کاربری‌ای حمل نمی‌کنند، پس گیت‌زدنشان امنیتی
    نمی‌خرد و در عوض کشِ مرورگر را می‌شکند — همان تفکیکی که `/static` از قبل
    دارد. مرز روی **نوعِ فایل** است نه روی مسیر، چون صفحهٔ تازه فردا زیرِ هر
    مسیری می‌تواند اضافه شود.

    نبودِ build ۵۰۳ می‌دهد نه ۵۰۰: «هنوز ساخته نشده» یک حالتِ **پیش‌بینی‌شده**
    است (توسعهٔ محلی، یا ایمیجی که مرحلهٔ Node را رد کرده)، و پیامش باید
    دستورِ رفع را بگوید نه یک traceback.
    """
    if not pathlib.Path(_CONSOLE_DIR, "index.html").is_file():
        if not _session_admin(request):
            raise web.HTTPFound("/login")
        return web.Response(status=503, text=_CONSOLE_MISSING,
                            content_type="text/plain", charset="utf-8")

    target = _console_target(request.match_info.get("tail", ""))
    if target is None:
        raise web.HTTPNotFound()
    path, is_html = target
    if is_html and not _session_admin(request):
        raise web.HTTPFound("/login")
    return web.FileResponse(path)


async def _on_startup(app: web.Application) -> None:
    settings_store.init_store(settings.redis_url)
    app["redis"] = aioredis.from_url(settings.redis_url, decode_responses=True)
    # مهم: بدونِ این، پس از ری‌استارت (telabzar update) دیکشنریِ متن‌ها/کلیدها خالی می‌ماند
    # و پنل «دیفالت» نشان می‌دهد — و ذخیرهٔ باتنی از رویِ آن نمای کهنه، override‌های واقعی
    # را با دیفالت بازنویسی می‌کند. پس در startup و سرِ هر صفحه از DB تازه می‌کنیم.
    try:
        await textstore.load()
    except Exception as exc:  # noqa: BLE001
        log.warning("panel: textstore preload failed: %s", exc)
    await _mirror_all_cookies(app["redis"])  # آینهٔ کوکی‌ها را با دیسک هماهنگ کن (نودها)


async def _on_cleanup(app: web.Application) -> None:
    # تازه‌سازیِ pot در پس‌زمینه می‌دود؛ اگر لغو نشود از خودِ اپ عمر بیشتری
    # می‌کند — همان انضباطی که keepaliveِ `dl_active` لازم دارد.
    task = app.get(_POT_TASK)
    if task is not None and not task.done():
        task.cancel()
    try:
        await app["redis"].aclose()
    except Exception:  # noqa: BLE001
        pass


#: هدرهای امنیتیِ هر پاسخ. امروز فقط `Referrer-Policy` — که **بخشی از رفعِ
#: نشتِ توکنِ join است، نه سخت‌سازیِ عمومی**: لاگِ تولید نشان داد از ۹ خطِ
#: حاویِ `tok=`، هشت‌تا `Referer` داشتند، یعنی مرورگر همان URL را روی هر
#: درخواستِ same-origin تکثیر می‌کرد. حتی حالا که توکن از URL بیرون آمده، این
#: هدر جلوی تکرارِ همین رده را برای هر مسیرِ آیندهٔ پنل می‌گیرد.
_SECURITY_HEADERS = {
    "Referrer-Policy": "no-referrer",
    # پنل قابلِ iframe شدن بود. چون توکنِ CSRF ندارد و کلِ دفاعش
    # `SameSite=Lax`ِ کوکی است، یک کلیکِ فریب‌خورده روی «بلاکِ کاربر» یا «حذفِ
    # اکانتِ کوکی» کافی بود.
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    # CSP سخت‌گیرانه است چون پنل **هیچ منبعِ خارجی ندارد** (اندازه‌گیری‌شده:
    # صفر ارجاعِ http(s) در قالب‌ها؛ فونت از /static می‌آید). `unsafe-inline`
    # برای style لازم است چون کلِ طراحی یک `<style>`ِ درون‌خطی است، و برای
    # script هم چون JSِ درون‌خطی داریم — هر دو ساختاری‌اند و بیرون‌بردنشان
    # تغییرِ جداست، نه بخشی از این سخت‌سازی.
    #
    # **سهمِ script دست‌کم گرفته شده بود و تصحیح شد (اندازه‌گیری‌شده):** این
    # کامنت می‌گفت «صفحهٔ /buttons یک بلاکِ inline دارد»، یعنی یک نقطه. واقعاً
    # **۸ نقطه در ۵ قالب** است — بلاکِ `<script>`ِ `buttons.html` به‌علاوهٔ ۷
    # هندلرِ رویدادِ درون‌خطی: دو `onsubmit` و دو `onclick` در `cookies.html`،
    # یک `onchange` در `texts.html`، یک `onchange` در `buttons.html` و یک
    # `onsubmit` در `nodes.html`. پس برداشتنِ `script-src 'unsafe-inline'`
    # هزینه‌اش هشت ویرایش است نه یکی.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    ),
}

#: HSTS فقط روی HTTPS. روی HTTPِ ساده فرستادنش بی‌اثر است و بدتر: اگر پنل
#: عمداً روی HTTP سرو شود (نصب بدونِ دامنه)، مرورگر را برای همان هاست به
#: HTTPSِ ناموجود قفل می‌کند. `_ssl_context()` تصمیم را از قبل گرفته.
_HSTS = "max-age=31536000; includeSubDomains"


@web.middleware
async def _security_headers(request: web.Request, handler):
    """هدرها روی **هر** پاسخ می‌نشینند، از جمله ریدایرکت‌ها و خطاها.

    ریدایرکت‌ها در aiohttp استثنا هستند (`HTTPFound` که `raise` می‌شود)، و
    دقیقاً همان‌هایی‌اند که در جریانِ نودها ساخته می‌شوند — پس اگر فقط مسیرِ
    موفق پوشش داده شود، جایی که بیشترین اهمیت را دارد بی‌هدر می‌ماند.
    """
    headers = dict(_SECURITY_HEADERS)
    # همان قاعده‌ای که کوکیِ نشست دارد: اسکیمِ **واقعی**، با احتسابِ پروکسی.
    if request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        headers["Strict-Transport-Security"] = _HSTS
    try:
        resp = await handler(request)
    except web.HTTPException as exc:
        exc.headers.update(headers)
        raise
    resp.headers.update(headers)
    return resp


def build_app() -> web.Application:
    app = web.Application(middlewares=[_security_headers, _panel_prefs])
    app.router.add_get("/", dashboard)
    app.router.add_get("/login", login)
    app.router.add_post("/auth/request", auth_request)
    app.router.add_post("/auth/verify", auth_verify)
    app.router.add_get("/logout", logout)
    app.router.add_get("/prefs", prefs)
    app.router.add_post("/save", save)
    app.router.add_get("/cookies", cookies_page)
    app.router.add_post("/cookies/add", cookies_add)
    app.router.add_post("/cookies/replace", cookies_replace)
    app.router.add_post("/cookies/delete", cookies_delete)
    app.router.add_post("/cookies/unfreeze", cookies_unfreeze)
    app.router.add_post("/cookies/resync", cookies_resync)
    app.router.add_post("/cookies/identity", cookies_identity)
    app.router.add_post("/cookies/cooldown", cookies_cooldown)
    app.router.add_get("/health", health_page)
    app.router.add_get("/users", users_page)
    app.router.add_post("/users/block", users_block)
    app.router.add_get("/stats", stats_page)
    app.router.add_get("/texts", texts_page)
    app.router.add_post("/texts/save", texts_save)
    app.router.add_post("/texts/reset", texts_reset)
    app.router.add_get("/buttons", buttons_page)
    app.router.add_post("/buttons/save", buttons_save)
    app.router.add_post("/buttons/reset", buttons_reset)
    app.router.add_get("/langs", langs_page)
    app.router.add_get("/langs/export", langs_export)
    app.router.add_post("/langs/import", langs_import)
    app.router.add_post("/langs/delete", langs_delete)
    app.router.add_get("/nodes", nodes_page)
    app.router.add_post("/nodes/add", nodes_add)
    app.router.add_post("/nodes/remove", nodes_remove)
    app.router.add_post("/node/join", node_join)      # عمومی (توکن گِیت)
    app.router.add_get("/node/install.sh", node_install)  # عمومی
    app.router.add_get("/node/peers", node_peers)         # گِیت با NODE_SECRET (wg-sync)
    app.router.add_get("/healthz", healthz)
    # یک هندلر برای کلِ زیردرختِ کنسول، نه `add_static`: خروجیِ Next هر صفحه
    # را `<slug>/index.html` می‌دهد و استاتیکِ aiohttp دایرکتوری را باز نمی‌کند،
    # پس با آن هر صفحه‌ای جز خانه ۴۰۴ می‌شد. گِیتِ نشست هم فقط روی HTML است و
    # این تفکیک داخلِ خودِ هندلر زندگی می‌کند، نه در ترتیبِ ثبتِ روت‌ها.
    app.router.add_get("/console", console_page)
    app.router.add_get(r"/console/{tail:.*}", console_page)
    if os.path.isdir(_STATIC_DIR):
        app.router.add_static("/static", _STATIC_DIR)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


def _ssl_context() -> ssl.SSLContext | None:
    cert, key = settings.tls_cert, settings.tls_key
    if cert and key and os.path.exists(cert) and os.path.exists(key):
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(cert, key)
        return ctx
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _require_admin_secret()      # پیش از هر کاری — با رازِ خالی اصلاً سرو نکن
    ctx = _ssl_context()
    log.info("Admin panel on :%s (tls=%s, admins=%d)",
             settings.admin_port, bool(ctx), len(settings.admin_id_set))
    web.run_app(build_app(), host="0.0.0.0", port=settings.admin_port, ssl_context=ctx, print=None)


if __name__ == "__main__":
    main()
