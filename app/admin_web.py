"""پنلِ ادمینِ وب (فاز D) — aiohttp + Jinja2.

ورود: ادمین شناسهٔ عددی‌اش را می‌زند → کدِ ۶رقمی از ربات به تلگرامش می‌رود →
کد را وارد می‌کند → سشنِ رمزنگاری‌شده (کوکی). فقط `ADMIN_IDS`.
صفحه‌ها: تنظیمات · کوکی‌ها · سلامت. فونتِ Vazirmatn به‌صورتِ webfontِ
جاسازی‌شده (app/static/fonts) سرو می‌شود تا همه‌جا دقیقاً وزیرمتن باشد.
اجرا: python -m app.admin_web
"""
from __future__ import annotations

import base64
import glob
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import ssl
import time
from datetime import datetime, timedelta, timezone

import aiohttp
import redis.asyncio as aioredis
from aiohttp import web
from cryptography.fernet import Fernet, InvalidToken
from jinja2 import Environment, DictLoader, select_autoescape
from markupsafe import Markup
from sqlalchemy import func, select, text as sql_text, true as sa_true

from . import cookies as ck_pool
from . import nodes as node_mod
from . import settings_store
from . import textstore
from .config import settings
from .db import Sessionmaker
from .downloader import KNOWN_PLATFORMS, PLATFORM_LABELS
from .i18n import CATALOG, t as _t
from .keyboards import OPS_BY_KIND
from .models import DownloadCache, File, Job, Node, User
from .settings_store import ENUM_VALUES, RUNTIME_KEYS

log = logging.getLogger("telabzar.admin")

_COOKIE = "tab_admin"
_SESSION_TTL = 8 * 3600
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

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
    ("🚦 سقف‌ها و کنترلِ مصرف", [
        ("rate_per_min", "نرخ در دقیقه", "۰ = نامحدود"),
        ("daily_op_quota", "سقفِ روزانهٔ عملیات", "هر کاربر · ۰ = نامحدود"),
        ("max_file_mb", "حداکثر حجمِ فایل (MB)", ""),
    ]),
    ("⬇️ دانلودر", [
        ("downloader_enabled", "دانلودر فعال", ""),
        ("dl_allow_unknown", "تلاش برای هر لینک", "هاستِ ناشناخته را هم دانلود کن"),
        ("dl_rich_posts", "پستِ چند‌عکسی به‌شکلِ مقاله", "Rich Message؛ خطا → آلبوم"),
        ("dl_cookie_when_needed", "کوکی فقط وقتی لازم است",
         "اول ناشناس تلاش کن — اکانت‌ها کمتر می‌سوزند"),
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
        ("dl_max_size_mb", "حداکثر حجمِ دانلود (MB)", ""),
        ("dl_concurrency", "دانلودِ هم‌زمان (کل)", ""),
        ("dl_daily_count", "سقفِ روزانهٔ دانلود", "هر کاربر · ۰ = نامحدود"),
    ]),
    ("🎧 اسپاتیفای", [
        ("spotify_enabled", "اسپاتیفای فعال", "بدونِ credential هم کار می‌کند"),
        ("spotify_client_id", "Client ID", "اختیاری · پایدارتر/کامل‌تر"),
        ("spotify_client_secret", "Client Secret", ""),
        ("spotify_meta", "متادیتا از اسپاتیفای", "خاموش = از یوتیوب · روشن = از اسپاتیفای"),
        ("spotify_max_tracks", "سقفِ ترک (آلبوم/پلی‌لیست)", ""),
        ("spotify_source", "منبعِ تطبیق", "ytmusic = دقیق‌تر · youtube = خام"),
        ("spotify_match_min", "حداقلِ امتیازِ تطبیق", "۰..۱۰۰ · بالاتر = سخت‌گیرتر"),
        ("spotify_yt_fallback", "چاره‌یِ یوتیوب", "اگر تطبیقِ مطمئن نبود: نتیجهٔ اولِ یوتیوب"),
    ]),
    ("🎬 کاهشِ حجمِ ویدیو", [
        ("compress_speed", "سرعت / کیفیت", "کندتر = کوچک‌تر"),
        ("video_encoder", "انکودر", "nvenc فقط با GPU"),
        ("compress_tiny_target_mb", "هدفِ «خیلی کم‌حجم» (MB)", "کلاس/جلسه"),
        ("compress_tiny_height", "کفِ رزولوشنِ خیلی کم‌حجم", "۴۸۰ یا ۳۶۰"),
        ("vjoin_max_mb", "سقفِ حجمِ چسباندنِ ویدیو (MB)", "۰ = مثلِ سقفِ فایل"),
    ]),
    ("🎙 رونویسی و اکسترا", [
        ("whisper_model", "مدلِ Whisper", ""),
        ("dl_sponsorblock", "SponsorBlock", "حذفِ اسپانسر/اینترو"),
        ("dl_subs", "زیرنویسِ خودکار (en+fa)", ""),
    ]),
    ("🍪 کوکی‌ها", [
        ("cookie_alert_min", "هشدار وقتی اکانتِ سالم کمتر از", "۰ = خاموش · به تلگرامِ ادمین"),
    ]),
    # سهمیهٔ استخرِ سشن. تحقیق: فشارِ ۲× یعنی سوختنِ ۴× — بالا بردن این اعداد
    # سرعت می‌دهد ولی عمرِ اکانت را کوتاه می‌کند.
    ("🧬 سهمیهٔ استخرِ سشن", [
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
    ("🔞 فیلترِ محتوای بزرگسال", [
        ("safety_enabled", "فیلتر فعال", "لینک و فایلِ آپلودی، هر دو"),
        ("safety_scan_pixels", "بررسیِ خودِ تصویر", "خاموش = فقط دامنه و متادیتا"),
        ("safety_threshold", "آستانهٔ اطمینان (درصد)", "بالاتر = سهل‌گیرتر · پیش‌فرض ۵۵"),
        ("safety_video_frames", "تعدادِ فریمِ بررسیِ ویدیو", "بیشتر = دقیق‌تر و کندتر"),
        ("safety_block_domains", "دامنه‌های مسدودِ اضافی", "با کاما یا خطِ جدید"),
        ("safety_allow_domains", "استثنا (هرگز مسدود نشود)", "برای رفعِ مسدودیِ اشتباه"),
        ("safety_notify_admin", "گزارشِ هر مسدودی به ادمین", ""),
        ("safety_strikes", "مسدودیِ خودکارِ کاربر پس از", "این تعداد تخلف · ۰ = خاموش"),
    ]),
    ("🔗 لینک و استریم", [
        ("stream_base", "پایهٔ لینک (نودِ استریم)", "خالی = دامنهٔ مستر · مثل https://cdn.example.com"),
    ]),
]

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
def _fernet() -> Fernet:
    seed = settings.admin_secret or settings.bot_token
    key = base64.urlsafe_b64encode(hashlib.sha256(f"telabzar-admin:{seed}".encode()).digest())
    return Fernet(key)


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
    # هر درخواست دوباره عضویت را چک کن: ادمینِ حذف‌شده از ADMIN_IDS نباید تا انقضای
    # کوکی (۸ ساعت) دسترسی داشته باشد.
    return aid if aid in settings.admin_id_set else None


# ── فونت + استایلِ مشترک ────────────────────────────────────────
# webfontِ متغیرِ Vazirmatn از /static سرو می‌شود؛ font-display:swap تا رندر بلاک نشود.
_FONT_FACE = (
    "@font-face{font-family:'Vazirmatn';src:url('/static/fonts/Vazirmatn.woff2') format('woff2');"
    "font-weight:100 900;font-style:normal;font-display:swap}"
)
_CSS = _FONT_FACE + """
*{margin:0;padding:0;box-sizing:border-box;font-family:'Vazirmatn','Segoe UI',Tahoma,system-ui,sans-serif}
:root{--bg:#eef2f7;--card:#fff;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--teal:#0d9488;
--teal2:#14b8a6;--green:#16a34a;--amber:#d97706;--red:#dc2626}
body{background:var(--bg);color:var(--ink)}
a{text-decoration:none;color:inherit}
.app{display:flex;min-height:100vh}
.side{width:236px;background:linear-gradient(180deg,#0f172a,#15223b);color:#cbd5e1;display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
.brand{padding:22px;font-size:20px;font-weight:800;color:#fff}.brand small{display:block;font-size:11px;color:#7dd3fc;margin-top:2px}
.nav{padding:8px 12px;display:flex;flex-direction:column;gap:4px}
.nav a{display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:11px;color:#cbd5e1;font-size:14.5px}
.nav a.on{background:linear-gradient(90deg,rgba(20,184,166,.22),rgba(20,184,166,.05));color:#fff;box-shadow:inset 3px 0 0 var(--teal2)}
.nav a:not(.on):not(.soon):hover{background:rgba(255,255,255,.05)}
.nav a.soon{opacity:.45;cursor:default}.foot{margin-top:auto;padding:16px 20px;font-size:12px;color:#64748b}
.main{flex:1;min-width:0}.top{height:62px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 26px;position:sticky;top:0;z-index:5}
.top h1{font-size:17px}.who{display:flex;align-items:center;gap:14px;font-size:13px;color:var(--muted);flex-wrap:wrap;justify-content:flex-end}
.pill{display:inline-flex;align-items:center;gap:7px;background:#ecfdf5;color:#047857;padding:6px 12px;border-radius:999px;font-weight:600;font-size:12.5px}
.pill.bad{background:#fffbeb;color:#b45309}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green)}.pill.bad .dot{background:var(--amber)}
.lo{color:#64748b}
.body{padding:22px 26px}
.grid2{display:grid;grid-template-columns:1fr 372px;gap:16px;align-items:start}
@media(max-width:1000px){.grid2{grid-template-columns:1fr}}
.col{display:flex;flex-direction:column;gap:16px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.body>.card+.card,form>.card+.card{margin-top:16px}
.card h3{font-size:14px;font-weight:700;padding:15px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:9px}
.tag{font-size:11px;font-weight:600;color:var(--teal);background:#f0fdfa;padding:3px 9px;border-radius:8px;white-space:nowrap}
.card h3 .tag{margin-inline-start:auto}
.card h3 .tag+.tag{margin-inline-start:6px}
.hint{color:#64748b;font-size:12px;line-height:2;padding:12px 18px;border-bottom:1px solid var(--line);
  display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tabs{display:flex;gap:6px;flex-wrap:wrap;padding:12px 18px 0}
.tab{padding:7px 12px;border-radius:9px;font-size:12.5px;color:#475569;background:#f1f5f9;border:1px solid transparent}
.tab:hover{background:#e2e8f0}
.tab.on{background:#f0fdfa;color:var(--teal);border-color:#99f6e4;font-weight:700}
.rows{padding:6px 18px 14px}
.pad{padding:14px 18px}
.row{display:flex;align-items:center;justify-content:space-between;padding:11px 0;border-bottom:1px dashed #eef2f7;gap:12px}
.row:last-child{border-bottom:0}.row label{font-size:13.5px;color:#334155}.row label small{display:block;color:#94a3b8;font-size:11.5px;margin-top:2px}
.ta-inline{width:230px;min-height:64px;border:1px solid #cbd5e1;border-radius:9px;padding:8px 10px;font-size:12.5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#fff;color:var(--ink);resize:vertical;unicode-bidi:isolate}
.inp{width:160px;height:36px;border:1px solid #cbd5e1;border-radius:9px;padding:0 11px;font-size:13.5px;font-family:inherit;text-align:center;background:#fff;color:var(--ink)}
.sel{width:160px;height:36px;border:1px solid #cbd5e1;border-radius:9px;padding:0 8px;font-size:13.5px;font-family:inherit;background:#fff;color:var(--ink)}
.tg{appearance:none;width:46px;height:26px;border-radius:999px;background:#cbd5e1;position:relative;cursor:pointer;flex:none}
.tg:checked{background:var(--teal2)}.tg::after{content:'';position:absolute;width:20px;height:20px;border-radius:50%;background:#fff;top:3px;right:3px;transition:.15s}
.tg:checked::after{right:23px}
.save{margin:2px 18px 18px;height:44px;width:calc(100% - 36px);background:linear-gradient(90deg,var(--teal),var(--teal2));color:#fff;border:0;border-radius:11px;font-size:15px;font-weight:700;font-family:inherit;cursor:pointer;box-shadow:0 6px 16px rgba(13,148,136,.28)}
.svc{display:flex;align-items:center;gap:10px;padding:9px 0;font-size:13.5px}.svc:not(:last-child){border-bottom:1px dashed #eef2f7}
.badge{margin-inline-start:auto;font-size:11.5px;font-weight:700;padding:3px 9px;border-radius:8px}
.ok{background:#ecfdf5;color:#047857}.warn{background:#fffbeb;color:#b45309}.dim{background:#f1f5f9;color:#64748b}
.meter{height:9px;border-radius:999px;background:#e2e8f0;overflow:hidden}.meter i{display:block;height:100%;border-radius:999px}
.stat{display:flex;align-items:center;gap:10px;margin:12px 0;font-size:13px}.stat b{width:82px;color:#475569}.stat .meter{flex:1}.stat .num{color:#94a3b8;font-size:11.5px;min-width:60px;text-align:left}
.mini{display:flex;gap:10px;padding:6px 18px 14px}.kpi{flex:1;background:#f8fafc;border:1px solid var(--line);border-radius:12px;padding:12px;text-align:center}
.kpi b{font-size:22px;color:var(--teal)}.kpi span{display:block;font-size:11.5px;color:var(--muted);margin-top:3px}
.save-sm{height:32px;padding:0 18px;border:0;border-radius:9px;font-size:13px;font-weight:700;font-family:inherit;cursor:pointer;background:linear-gradient(90deg,var(--teal),var(--teal2));color:#fff}
.saved{background:#ecfdf5;color:#047857;font-size:13px;padding:10px 14px;border-radius:10px;margin-bottom:16px;font-weight:600}
.note{background:#eff6ff;color:#1d4ed8;font-size:12.5px;padding:10px 14px;border-radius:10px;margin-bottom:16px;line-height:1.9}
.errbox{background:#fef2f2;color:#b91c1c;font-size:12.5px;padding:10px 14px;border-radius:10px;margin-bottom:16px}
/* پیام‌هایی که مستقیم فرزندِ کارت‌اند باید هم‌ترازِ بقیهٔ محتوا باشند، نه چسبیده به لبه */
.card>.saved,.card>.errbox,.card>.note,.card>.tx-err,.card>.empty{margin-inline:18px}
.tbl-wrap{overflow-x:auto}
.tbl{width:100%;border-collapse:collapse}
.tbl td.num{white-space:nowrap}
.tbl th{text-align:right;font-size:11.5px;color:#94a3b8;font-weight:600;padding:9px 12px;border-bottom:1px solid var(--line)}
.tbl td{padding:12px;font-size:13px;border-bottom:1px dashed #eef2f7;vertical-align:middle}
.tbl tr:last-child td{border-bottom:0}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;color:#334155}
/* متن‌های لاتین/عددی داخلِ صفحهٔ RTL نباید جابه‌جا شوند (تاریخ، حجم، IP، دستور) */
.mono,.num,code,.hist .b span{unicode-bidi:isolate}
.num{direction:ltr;unicode-bidi:isolate;text-align:right}
.ltr{direction:ltr;text-align:left;unicode-bidi:isolate}
.chip{display:inline-block;font-size:11px;font-weight:600;padding:3px 9px;border-radius:8px;background:#f1f5f9;color:#475569}
.btn-sm{height:32px;padding:0 12px;border:1px solid #cbd5e1;background:#fff;border-radius:8px;font-size:12.5px;font-family:inherit;color:#334155;cursor:pointer}
.btn-sm:hover{background:#f8fafc}
.btn-danger{border-color:#fecaca;color:#b91c1c}.btn-danger:hover{background:#fef2f2}
.inline{display:inline}
.btn-go{height:34px;padding:0 15px;border:0;border-radius:9px;font-size:13px;font-weight:700;font-family:inherit;
  cursor:pointer;background:linear-gradient(90deg,var(--teal),var(--teal2));color:#fff}
.empty{font-size:13px;color:#94a3b8;padding:18px;text-align:center}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:16px}
@media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}}
.kpi2{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.kpi2 b{font-size:26px;color:var(--ink);display:block;line-height:1.2}
.kpi2 span{font-size:12px;color:var(--muted)}.kpi2 .up{display:inline;padding:0;color:var(--green);font-size:11.5px;font-weight:700}
.bar-row{display:flex;align-items:center;gap:10px;margin:11px 0;font-size:13px}
.bar-row b{width:96px;color:#475569;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-row .meter{flex:1}.bar-row .num{min-width:44px;text-align:left;color:#94a3b8;font-size:12px}
.hist{display:flex;align-items:flex-end;gap:9px;height:130px;padding:14px 18px 6px}
.hist .b{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:5px;height:100%}
.hist .b i{width:66%;min-height:3px;background:linear-gradient(180deg,var(--teal2),var(--teal));border-radius:6px 6px 0 0}
.hist .b em{font-size:11px;color:#475569;font-style:normal;font-weight:700}.hist .b span{font-size:10px;color:#94a3b8}
.pager{display:flex;align-items:center;justify-content:center;gap:14px;padding:16px;font-size:13px;color:var(--muted)}
.pager a{padding:8px 14px;border:1px solid #cbd5e1;border-radius:9px;color:#334155;font-size:12.5px}
.pager a:hover{background:#f8fafc}.pager .off{opacity:.4;pointer-events:none}
.search{display:flex;gap:10px;margin-bottom:16px}
.search input{height:38px;border:1px solid #cbd5e1;border-radius:9px;padding:0 12px;font-size:13px;font-family:inherit;width:220px;color:var(--ink)}
.search button{height:38px;padding:0 16px;background:linear-gradient(90deg,var(--teal),var(--teal2));color:#fff;border:0;border-radius:9px;font-size:13px;font-weight:700;font-family:inherit;cursor:pointer}
.tag2{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:7px;background:#eef2ff;color:#4338ca}
/* موبایل/تبلت: سایدبار به یک نوارِ افقیِ بالای صفحه تبدیل می‌شود */
@media(max-width:860px){
  .app{flex-direction:column}
  .side{width:100%;height:auto;position:static;flex-direction:row;flex-wrap:wrap;align-items:center;row-gap:4px}
  .brand{padding:14px 18px;font-size:17px}.brand small{display:none}
  .nav{flex-direction:row;flex-wrap:wrap;padding:0 14px 12px;gap:6px}
  .nav a{padding:8px 11px;font-size:13px;border-radius:9px}
  .foot{display:none}
  .top{height:auto;min-height:56px;padding:10px 16px;gap:10px;flex-wrap:wrap}
  .body{padding:16px}
}
@media(max-width:560px){
  .body{padding:12px}.rows,.pad{padding-inline:12px}.card h3{padding:13px 12px}
  .tbl th,.tbl td{padding:9px 7px;font-size:12px}
}
"""


# ── قالب‌ها (وراثت از base) ─────────────────────────────────────
_BASE = """<!doctype html><html lang=fa dir=rtl><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{% block title %}پنلِ مدیریت{% endblock %} · تل‌ابزار</title>
<style>{{css}}{% block style %}{% endblock %}</style></head><body><div class=app>
<aside class=side><div class=brand>🧰 تل‌ابزار<small>پنلِ مدیریت</small></div>
<nav class=nav>
  <a class="{{'on' if active=='settings'}}" href=/>⚙️ تنظیمات</a>
  <a class="{{'on' if active=='texts'}}" href=/texts>✏️ متن‌ها</a>
  <a class="{{'on' if active=='buttons'}}" href=/buttons>🎨 کلیدها</a>
  <a class="{{'on' if active=='cookies'}}" href=/cookies>🍪 کوکی‌ها</a>
  <a class="{{'on' if active=='health'}}" href=/health>🩺 سلامت</a>
  <a class="{{'on' if active=='nodes'}}" href=/nodes>🖧 نودها</a>
  <a class="{{'on' if active=='users'}}" href=/users>👤 کاربران</a>
  <a class="{{'on' if active=='stats'}}" href=/stats>📊 آمار</a>
</nav>
<div class=foot>نسخهٔ ۱.۰ · D3</div></aside>
<div class=main><div class=top><h1>{% block heading %}{% endblock %}</h1><div class=who>
<span class="pill {{'' if pill_ok else 'bad'}}"><span class=dot></span> {{'همه سرویس‌ها آنلاین' if pill_ok else 'بررسیِ سرویس‌ها'}}</span>
<span>ادمین · {{admin_id}}</span><a href=/logout class=lo>خروج ↩</a></div></div>
<div class=body>{% block body %}{% endblock %}</div></div></div></body></html>"""

_HEALTH_CARDS = """
<div class=card><h3>🩺 سلامتِ سرویس‌ها</h3><div class=rows>
  <div class=svc>🗄 Postgres <span class="badge {{'ok' if health.postgres else 'warn'}}">{{'آنلاین' if health.postgres else 'خطا'}}</span></div>
  <div class=svc>⚡ Redis <span class="badge {{'ok' if health.redis else 'warn'}}">{{'آنلاین' if health.redis else 'خطا'}}</span></div>
  <div class=svc>🔑 pot-provider (یوتیوب)
    {% if health.pot is none %}<span class="badge dim">پیکربندی‌نشده</span>
    {% else %}<span class="badge {{'ok' if health.pot else 'warn'}}">{{'آنلاین' if health.pot else 'خطا'}}</span>{% endif %}</div>
</div></div>
<div class=card><h3>📦 صف و دیسک</h3><div class=rows>
  <div class=mini style=padding-inline:0>
    <div class=kpi><b>{{health.q_main}}</b><span>صفِ پردازش</span></div>
    <div class=kpi><b>{{health.q_proc}}</b><span>صفِ نودِ پردازش</span></div>
    <div class=kpi><b>{{health.q_dl}}</b><span>صفِ دانلود</span></div>
    <div class=kpi><b>{{health.dl_active}}</b><span>دانلودِ فعال</span></div>
  </div>
  {% if health.disk_total %}<div class=stat><b>دیسکِ ‎/work</b><div class=meter><i style="width:{{health.disk_pct}}%;background:{{'#dc2626' if health.disk_pct>85 else '#14b8a6'}}"></i></div><span class=num>{{health.disk_used}}/{{health.disk_total}}G</span></div>{% endif %}
</div></div>
<div class=card><h3>📈 نرخِ موفقیتِ دانلود <span class=tag>امروز</span></h3><div class=rows>
  {% if health.hosts %}{% for h in health.hosts %}
    <div class=stat><b>{{ pfa.get(h.name, h.name) }}</b><div class=meter><i style="width:{{h.rate}}%;background:{{'#16a34a' if h.rate>=70 else '#d97706'}}"></i></div><span class=num>{{h.rate}}% · {{h.ok}}/{{h.ok+h.fail}}</span></div>
  {% endfor %}{% else %}<div class=empty>هنوز دانلودی امروز ثبت نشده.</div>{% endif %}
</div></div>"""

_SETTINGS = """{% extends 'base' %}{% block title %}تنظیمات{% endblock %}{% block heading %}تنظیمات{% endblock %}
{% block body %}<div class=grid2>
<div class=col>
  {% if saved %}<div class=saved>✅ تغییرات ذخیره شد (بدونِ ری‌استارت اعمال شد).</div>{% endif %}
  <form method=post action=/save>
  {% for title, fields in groups %}
    <div class=card><h3>{{title}}{% if loop.first %}<span class=tag>بدونِ ری‌استارت</span>{% endif %}</h3><div class=rows>
    {% for key, label, hint in fields %}
      <div class=row><label>{{label}}{% if hint %}<small>{{hint}}</small>{% endif %}</label>
      {% set kind = meta[key][0] %}
      {% if kind == 'bool' %}<input class=tg type=checkbox name="{{key}}" {% if v[key] %}checked{% endif %}>
      {% elif key in enums %}<select class=sel name="{{key}}">
        {% for opt in enums[key] %}<option value="{{opt}}" {% if v[key]|string == opt %}selected{% endif %}>{{ labels.get(opt, opt) }}</option>{% endfor %}
      </select>
      {% elif key in longtext %}<textarea class="ta-inline" name="{{key}}" rows=3
        dir=ltr spellcheck=false>{{v[key]}}</textarea>
      {% else %}<input class=inp name="{{key}}" value="{{v[key]}}">{% endif %}
      </div>
    {% endfor %}
    </div></div>
  {% endfor %}
    <button class=save>ذخیرهٔ تغییرات</button>
  </form>
</div>
<div class=col>""" + _HEALTH_CARDS + """</div>
</div>{% endblock %}"""

_COOKIES = """{% extends 'base' %}{% block title %}کوکی‌ها{% endblock %}{% block heading %}اکانت‌های کوکی{% endblock %}
{% block style %}
.ta{width:100%;box-sizing:border-box;background:#0b1220;color:#7dd3fc;border:1px solid #1e293b;border-radius:11px;
  padding:11px 13px;font-family:ui-monospace,monospace;font-size:12px;line-height:1.75;resize:vertical;
  direction:ltr;text-align:left;unicode-bidi:isolate}
.ck-form{display:flex;gap:10px;margin:0 0 10px;flex-wrap:wrap;align-items:center}
.ck-form .inp{flex:1;min-width:190px;text-align:start}
.ck-hint{color:#94a3b8;font-size:12px}
.ck-go{display:flex;gap:10px;margin-top:10px;align-items:center;flex-wrap:wrap}
.ck-row{display:flex;align-items:center;gap:11px;padding:11px 0;border-top:1px solid var(--line);flex-wrap:wrap}
.ck-row:first-child{border-top:0}
.sdot{width:9px;height:9px;border-radius:50%;flex:none}
.s-healthy{background:#16a34a}.s-suspect{background:#d97706}.s-invalid{background:#dc2626}
.s-cooldown{background:#0ea5e9}.s-disabled{background:#cbd5e1}.s-frozen{background:#b91c1c}
.ck-name{font-size:13.5px;font-weight:700;min-width:96px}
.ck-meta{color:#94a3b8;font-size:12px;min-width:170px}
.ck-acts{display:flex;gap:6px;flex-wrap:wrap;margin-inline-start:auto}
.guide{margin:0;padding-inline-start:20px;font-size:12.5px;line-height:2.1;color:#334155}
.guide li{margin-bottom:2px}
.repl{background:#f8fafc;border:1px dashed #cbd5e1;border-radius:12px;padding:12px;margin:2px 0 10px}
{% endblock %}
{% block body %}
{% if saved %}<div class=saved>✅ {{saved}}</div>{% endif %}
{% if error %}<div class=errbox>⚠️ {{error}}</div>{% endif %}

<div class=card>
  <h3>📌 روالِ درستِ استخراجِ کوکی <span class=tag>مهم‌ترین عاملِ عمرِ اکانت</span></h3>
  <div class=pad>
    <div class=note style=margin-bottom:12px>
      <b>چرا کوکیِ یوتیوب زود می‌میرد:</b> اگر تبِ یوتیوب در مرورگرِ عادی باز بماند،
      یوتیوب کوکی را <b>می‌چرخاند</b> و نسخه‌ای که export کرده‌ای باطل می‌شود. راهِ
      درست طبقِ ویکیِ خودِ yt-dlp این است:
    </div>
    <ol class=guide>
      <li>یک پنجرهٔ <b>ناشناس (Incognito / Private)</b> باز کن و لاگین کن.</li>
      <li><b>در همان تب</b> برو به <span class="mono ltr">youtube.com/robots.txt</span>.</li>
      <li>کوکی‌های <span class="mono ltr">youtube.com</span> را export کن.</li>
      <li>پنجرهٔ ناشناس را <b>ببند</b> — <b>لاگ‌اوت نکن</b> (لاگ‌اوت سشن را باطل می‌کند).</li>
    </ol>
    <div class=hint style="border:0;padding:10px 0 0">
      اینستاگرام: همان روال، ولی کافی است <span class=mono>sessionid</span> را داشته باشی.
      سشنِ اینستاگرام به <b>IP و دستگاه</b> حساس است؛ کوکی را از همان‌جایی بگیر که
      قرار است استفاده شود و اکانت‌ها را قاطیِ هم نکن.
    </div>
  </div>
</div>

<div class=card>
  <h3>➕ افزودنِ اکانت <span class=tag>کپی/پیست — بدونِ فایل</span></h3>
  <div class=pad>
    <div class=note>محتوای <b>cookies.txt</b> (Netscape) یا خروجیِ <b>JSON</b>ِ افزونهٔ
      <span class=mono>Cookie-Editor</span> را کپی کن و این‌جا بچسبان. برای اینستاگرام فقط
      <span class=mono>sessionid</span> کافی است. از اکانتِ یک‌بارمصرف استفاده کن، نه اصلی.
      {% if not dir_ok %}<br><b>توجه:</b> پوشهٔ کوکی‌ها (<span class=mono>{{cookies_dir or 'COOKIES_DIR'}}</span>) پیدا/نوشتنی نیست.{% endif %}
      {% if dl_node_online %}<br>🖧 نودِ دانلود آنلاین است — کوکی‌ها خودکار به آن همگام می‌شوند ({{mirrored}} در Redis).{% endif %}
    </div>
    <form method=post action=/cookies/add>
      <div class=ck-form>
        <select class=sel name=platform>
          {% for key, fa in platforms %}<option value="{{key}}">{{fa}}</option>{% endfor %}
        </select>
        <input class=inp name=label placeholder="برچسبِ اکانت (مثلاً ig-acc4)">
        <span class=ck-hint>برچسب فقط برای شناساییِ خودت است</span>
      </div>
      <textarea class=ta name=content rows=4 required dir=ltr
        placeholder="# Netscape HTTP Cookie File&#10;.instagram.com&#9;TRUE&#9;/&#9;TRUE&#9;1789…&#9;sessionid&#9;42891…"></textarea>
      <div class=ck-go>
        <button class=btn-go>بررسی و افزودن</button>
        <span class=ck-hint>هنگامِ افزودن، ساختار و کوکیِ کلیدی بررسی می‌شود.</span>
      </div>
    </form>
  </div>
</div>

{% if attention %}
<div class=card style="border-color:#fecaca">
  <h3>🛑 نیازمندِ رسیدگی <span class="tag" style="background:#fef2f2;color:#b91c1c">{{attention|length}}</span></h3>
  <div class=pad>
    <div class=hint style="border:0;padding:0 0 10px">
      این اکانت‌ها با تلاشِ خودکار درست نمی‌شوند (چک‌پوینت/۲FA یا کوکیِ باطل).
      ربات هم موقعِ رخ‌دادن در تلگرام خبر می‌دهد و می‌توانی همان‌جا کوکیِ تازه بچسبانی.
    </div>
    {% for c in attention %}
    <div class=ck-row>
      <span class="sdot s-{{c.status}}"></span>
      <b class=ck-name>{{c.label}}</b>
      <span class="badge {{c.badge}}" style=margin:0>{{c.status_fa}}</span>
      <span class=ck-meta>{{ pfa.get(c.platform, c.platform) }}
        {%- if c.last_error %} · <span class=mono>{{c.last_error}}</span>{% endif %}</span>
      <span class=ck-acts>
        <form class=inline method=post action=/cookies/unfreeze>
          <input type=hidden name=name value="{{c.name}}">
          <button class=btn-sm>✅ رسیدگی شد</button></form>
        <form class=inline method=post action=/cookies/delete onsubmit="return confirm('حذفِ {{c.label}}؟')">
          <input type=hidden name=name value="{{c.name}}"><button class="btn-sm btn-danger">حذف</button></form>
      </span>
    </div>
    {% endfor %}
  </div>
</div>
{% endif %}

{% for g in groups %}
<div class=card>
  <h3>{{ pfa.get(g.platform, g.platform) }}
    <span class=tag>{{g.healthy}} سالم از {{g.total}}</span></h3>
  <div class=pad style=padding-top:2px>
    {% for c in g['items'] %}
    <div class=ck-row>
      <span class="sdot s-{{c.status}}"></span>
      <b class=ck-name>{{c.label}}</b>
      <span class="badge {{c.badge}}" style=margin:0>{{c.status_fa}}</span>
      <span class=ck-meta>آخرین موفقیت: {{c.last_ok_fa}} · خطا: <bdi>{{c.fail_streak}}</bdi> · افزوده: {{c.added_fa}}
        · سهمیه: {% if c.budget %}<bdi>{{c.used}}/{{c.budget}}</bdi> در ساعت{% else %}<bdi>{{c.used}}</bdi> در ساعت · بی‌سقف{% endif %}{% if c.warming %} <span class=chip>در حالِ گرم‌شدن</span>{% endif %}
        {%- if c.node_id %} · خروجی: <span class=mono>{{c.node_name}}</span>{% endif %}</span>
      <span class=ck-acts>
        <button class=btn-sm onclick="var d=document.getElementById('i-{{loop.index0}}-{{g.platform}}');
          d.style.display=d.style.display=='none'?'block':'none';return false">🧬 هویت</button>
        <button class=btn-sm onclick="var d=document.getElementById('r-{{loop.index0}}-{{g.platform}}');
          d.style.display=d.style.display=='none'?'block':'none';return false">🔄 کوکیِ تازه</button>
        <form class=inline method=post action=/cookies/cooldown><input type=hidden name=name value="{{c.name}}">
          <input type=hidden name=action value="{{'clear' if c.status=='cooldown' else 'set'}}">
          <button class=btn-sm>{{'فعال‌سازی' if c.status=='cooldown' else 'کنارگذاشتن'}}</button></form>
        <form class=inline method=post action=/cookies/delete onsubmit="return confirm('حذفِ {{c.label}}؟')">
          <input type=hidden name=name value="{{c.name}}"><button class="btn-sm btn-danger">حذف</button></form>
      </span>
    </div>
    <div class=repl id="i-{{loop.index0}}-{{g.platform}}" style=display:none>
      <div style="color:#64748b;font-size:12px;margin-bottom:7px">
        هویتِ این اکانت — کوکی همیشه با <b>همین خروجی و همین UA</b> استفاده می‌شود.
        سرویس‌ها IP را هویت می‌دانند؛ جابه‌جاییِ IPِ یک سشن سریع‌ترین راهِ چک‌پوینت است.
      </div>
      <form method=post action=/cookies/identity class=ck-form>
        <input type=hidden name=name value="{{c.name}}">
        <select class=sel name=node_id>
          <option value="">خروجی: هرکدام</option>
          {% for n in nodes %}<option value="{{n.id}}" {% if c.node_id==n.id %}selected{% endif %}>{{n.name}}</option>{% endfor %}
        </select>
        <input class=inp name=proxy value="{{c.proxy}}" placeholder="پروکسیِ اختصاصی (اختیاری)">
        <input class=inp name=user_agent value="{{c.user_agent}}" placeholder="User-Agent (اختیاری)">
        <button class=btn-go>ذخیره</button>
      </form>
    </div>
    <div class=repl id="r-{{loop.index0}}-{{g.platform}}" style=display:none>
      <div style="color:#64748b;font-size:12px;margin-bottom:7px">کوکیِ تازهٔ همین اکانت را بچسبان — برچسب و تاریخچه حفظ می‌شود:</div>
      <form method=post action=/cookies/replace>
        <input type=hidden name=name value="{{c.name}}">
        <textarea class=ta name=content rows=3 required dir=ltr placeholder=".instagram.com&#9;TRUE&#9;/&#9;TRUE&#9;…&#9;sessionid&#9;…"></textarea>
        <div class=ck-go><button class=btn-go>بررسی و جایگزینی</button></div>
      </form>
    </div>
    {% endfor %}
  </div>
</div>
{% endfor %}
{% if not groups %}<div class=card><div class=empty>هنوز اکانتی اضافه نشده.</div></div>{% endif %}
{% endblock %}"""

_HEALTH = """{% extends 'base' %}{% block title %}سلامت{% endblock %}{% block heading %}سلامتِ سیستم{% endblock %}
{% block body %}<div class=grid2>
<div class=col>""" + _HEALTH_CARDS + """</div>
<div class=col>
  <div class=card><h3>🍪 وضعیتِ کوکی‌ها</h3><div class=rows>
    {% if pool %}{% for p in pool %}
      <div class=svc>{{ pfa.get(p.platform, p.platform) }}
        <span style="margin-inline-start:auto;color:#64748b;font-size:12.5px"><bdi>{{p.live}}</bdi> سالم{% if p.cd %} · <bdi>{{p.cd}}</bdi> کنارگذاشته{% endif %}{% if p.bad %} · <bdi>{{p.bad}}</bdi> باطل{% endif %}</span></div>
    {% endfor %}{% else %}<div class=empty>کوکی‌ای ثبت نشده.</div>{% endif %}
  </div></div>
  <div class=card><h3>ℹ️ راهنما</h3><div class=rows style=font-size:12.5px;color:#64748b;line-height:2>
    نرخِ موفقیتِ per-host از شمارنده‌های امروز محاسبه می‌شود. افتِ ناگهانیِ یک پلتفرم معمولاً یعنی
    کوکی بلاک شده یا pot-provider/پروکسی مشکل دارد — قبل از شکایتِ کاربرها این‌جا دیده می‌شود.
  </div></div>
</div>
</div>{% endblock %}"""

_USERS = """{% extends 'base' %}{% block title %}کاربران{% endblock %}{% block heading %}کاربران{% endblock %}
{% block body %}
{% if done %}<div class=saved>✅ {{done}}</div>{% endif %}
<form class=search method=get action=/users>
  <input name=q value="{{q}}" inputmode=numeric placeholder="جستجو با شناسهٔ عددی">
  <button>جستجو</button>
  {% if q %}<a class=btn-sm style="display:flex;align-items:center" href=/users>پاک‌کردن</a>{% endif %}
</form>
<div class=card><h3>👤 کاربران <span class=tag>{{total}} کل{% if blocked %} · {{blocked}} بلاک{% endif %}</span></h3>
{% if users %}
<div class=tbl-wrap><table class=tbl><thead><tr><th>شناسهٔ تلگرام</th><th>نقش</th><th>فایل‌ها</th><th>ثبت‌نام</th><th>آخرین بازدید</th><th>وضعیت</th><th style=text-align:left>عملیات</th></tr></thead><tbody>
{% for u in users %}
<tr>
  <td class=mono>{{u.tg}}{% if u.is_admin %} <span class=tag2>ادمین</span>{% endif %}</td>
  <td><span class=chip>{{u.role}}</span></td>
  <td class=num>{{u.files}}</td>
  <td class="num mono" style=color:#64748b>{{u.created}}</td>
  <td class="num mono" style=color:#64748b>{{u.seen}}</td>
  <td>{% if u.blocked %}<span class="badge warn" style=margin:0>بلاک</span>{% else %}<span class="badge ok" style=margin:0>فعال</span>{% endif %}</td>
  <td style=text-align:left>
    {% if u.is_admin %}<span class=num style=color:#cbd5e1>—</span>
    {% else %}<form class=inline method=post action=/users/block>
      <input type=hidden name=id value="{{u.id}}"><input type=hidden name=page value="{{page}}"><input type=hidden name=q value="{{q}}">
      <input type=hidden name=action value="{{'unblock' if u.blocked else 'block'}}">
      <button class="btn-sm {{'' if u.blocked else 'btn-danger'}}">{{'رفعِ بلاک' if u.blocked else 'بلاک'}}</button></form>{% endif %}
  </td>
</tr>
{% endfor %}
</tbody></table></div>
<div class=pager>
  <a class="{{'off' if page<=0}}" href="/users?page={{page-1}}{% if q %}&q={{q}}{% endif %}">→ قبلی</a>
  <span>صفحهٔ {{page+1}} از {{pages}}</span>
  <a class="{{'off' if page+1>=pages}}" href="/users?page={{page+1}}{% if q %}&q={{q}}{% endif %}">بعدی ←</a>
</div>
{% else %}<div class=empty>کاربری یافت نشد.</div>{% endif %}
</div>
{% endblock %}"""

_STATS = """{% extends 'base' %}{% block title %}آمار{% endblock %}{% block heading %}آمار{% endblock %}
{% block style %}
.sv{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px dashed #eef2f7}
.sv:last-child{border-bottom:0}
.sv b{font-size:12.5px;font-weight:600;min-width:96px}
.sv .meter{flex:1}
.sv .n{color:#64748b;font-size:12px;min-width:52px;text-align:left;direction:ltr;unicode-bidi:isolate}
.ts{display:flex;align-items:flex-end;gap:3px;height:120px;padding:16px 18px 0}
.ts .c{flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:2px;min-width:0}
.ts .c i{display:block;border-radius:3px 3px 0 0;min-height:2px}
.ts .c .f{background:var(--teal2)}.ts .c .o{background:var(--green)}.ts .c .u{background:var(--amber)}
.ts-x{display:flex;gap:3px;padding:6px 18px 14px;color:#94a3b8;font-size:10px}
.ts-x span{flex:1;text-align:center;min-width:0;overflow:hidden;unicode-bidi:isolate}
.lg{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:#64748b;padding:0 18px 12px}
.lg i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-inline-end:5px}
.errline{padding:9px 0;border-bottom:1px dashed #eef2f7;font-size:12px;display:flex;gap:10px}
.errline:last-child{border-bottom:0}
.errline code{flex:1;color:#b91c1c;word-break:break-word;font-size:11.5px}
.kpi3{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px}
@media(max-width:1000px){.kpi3{grid-template-columns:repeat(2,1fr)}}
.kpi3 .b{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.kpi3 .b em{display:block;font-size:11.5px;color:#94a3b8;font-style:normal;margin-bottom:5px}
.kpi3 .b strong{font-size:21px;font-weight:800;direction:ltr;unicode-bidi:isolate;display:block}
.kpi3 .b span{font-size:11.5px;color:var(--green);font-weight:600}
{% endblock %}
{% block body %}
<div class=tabs style="padding:0 0 14px">
  {% for key, label, _d in s.ranges %}
  <a class="tab {% if key==s.range %}on{% endif %}" href="/stats?range={{key}}">{{label}}</a>
  {% endfor %}
</div>

<div class=kpi3>
  <div class=b><em>کاربران</em><strong>{{s.users}}</strong>
    {% if s.users_new %}<span>+{{s.users_new}} در این بازه</span>{% endif %}</div>
  <div class=b><em>کاربرِ فعال</em><strong>{{s.users_active}}</strong>
    {% if s.users_blocked %}<span style=color:#dc2626>{{s.users_blocked}} بلاک</span>{% endif %}</div>
  <div class=b><em>فایل</em><strong>{{s.files}}</strong>
    <span>{{s.dl_files}} از لینک</span></div>
  <div class=b><em>حجمِ پردازش‌شده</em><strong><bdi>{{s.storage_h}}</bdi></strong></div>
  <div class=b><em>عملیات</em><strong>{{s.ops}}</strong>
    {% if s.success_rate is not none %}<span>{{s.success_rate}}٪ موفق</span>{% endif %}</div>
  <div class=b><em>میانگینِ زمانِ پردازش</em><strong><bdi>{{s.avg_op_h}}</bdi></strong>
    {% if s.queued %}<span style=color:#d97706>{{s.queued}} در صف</span>{% endif %}</div>
  <div class=b><em>مدتِ کلِ رسانه</em><strong><bdi>{{s.media_h}}</bdi></strong></div>
  <div class=b><em>تحویلِ آنی از کش</em><strong>{{s.cache_hits}}</strong>
    <span><bdi>{{s.cache_saved_h}}</bdi> صرفه‌جویی</span></div>
</div>

<div class=card>
  <h3>📈 روند <span class=tag>{{s.series_days}} روزِ اخیر · اوجِ روزانه {{s.ts_max}}</span></h3>
  <div class=lg><span><i style=background:var(--teal2)></i>فایل</span>
    <span><i style=background:var(--green)></i>عملیات</span>
    <span><i style=background:var(--amber)></i>کاربرِ جدید</span></div>
  <div class=ts>
    {% for d in s.ts %}
    <div class=c title="{{d.day}} — فایل {{d.f}} · عملیات {{d.o}} · کاربر {{d.u}}">
      {% if d.u %}<i class=u style="height:{{d.u_h}}px"></i>{% endif %}
      {% if d.o %}<i class=o style="height:{{d.o_h}}px"></i>{% endif %}
      {% if d.f %}<i class=f style="height:{{d.f_h}}px"></i>{% endif %}
    </div>
    {% endfor %}
  </div>
  <div class=ts-x>
    {% set step = (s.ts|length // 6) + 1 %}
    {% for d in s.ts %}<span>{% if loop.index0 % step == 0 %}{{d.day}}{% endif %}</span>{% endfor %}
  </div>
</div>

<div class=grid2>
<div class=col>
  <div class=card><h3>🗂 فایل‌ها بر اساسِ نوع</h3><div class=rows>
    {% if s.by_kind %}{% for r in s.by_kind %}
    <div class=sv><b>{{r.k}}</b><div class=meter><i style="width:{{r.pct}}%;background:var(--teal2)"></i></div><span class=n>{{r.n}}</span></div>
    {% endfor %}{% else %}<div class=empty>در این بازه فایلی نیست.</div>{% endif %}
  </div></div>

  <div class=card><h3>📥 پلتفرمِ دانلود <span class=tag>از این پس ثبت می‌شود</span></h3><div class=rows>
    {% if s.by_platform %}{% for r in s.by_platform %}
    <div class=sv><b>{{r.k}}</b><div class=meter><i style="width:{{r.pct}}%;background:var(--teal)"></i></div><span class=n>{{r.n}}</span></div>
    {% endfor %}{% else %}<div class=empty>هنوز دانلودی با پلتفرمِ ثبت‌شده نیست.</div>{% endif %}
  </div></div>

  <div class=card><h3>📦 توزیعِ حجم</h3><div class=rows>
    {% if s.by_size %}{% for r in s.by_size %}
    <div class=sv><b>{{r.k}}</b><div class=meter><i style="width:{{r.pct}}%;background:var(--teal2)"></i></div><span class=n>{{r.n}}</span></div>
    {% endfor %}{% else %}<div class=empty>—</div>{% endif %}
  </div></div>

  <div class=card><h3>🎞 کیفیتِ ویدیو</h3><div class=rows>
    {% if s.by_res %}{% for r in s.by_res %}
    <div class=sv><b>{{r.k}}</b><div class=meter><i style="width:{{r.pct}}%;background:var(--green)"></i></div><span class=n>{{r.n}}</span></div>
    {% endfor %}{% else %}<div class=empty>ویدیویی با ابعادِ ثبت‌شده نیست.</div>{% endif %}
  </div></div>

  <div class=card><h3>👤 کاربرانِ برتر</h3>
    {% if s.top_users %}
    <div class=tbl-wrap><table class=tbl>
      <thead><tr><th>شناسه</th><th>فایل</th><th>حجم</th></tr></thead><tbody>
      {% for u in s.top_users %}
      <tr><td class="num mono">{{u.tg}}</td><td class=num>{{u.files}}</td>
        <td class=num><bdi>{{u.size}}</bdi></td></tr>
      {% endfor %}</tbody></table></div>
    {% else %}<div class=empty>—</div>{% endif %}
  </div>
</div>

<div class=col>
  <div class=card><h3>⚙️ پرکاربردترین عملیات</h3><div class=rows>
    {% if s.by_op %}{% for r in s.by_op %}
    <div class=sv><b>{{r.k}}</b><div class=meter><i style="width:{{r.pct}}%;background:var(--green)"></i></div><span class=n>{{r.n}}</span></div>
    {% endfor %}{% else %}<div class=empty>عملیاتی اجرا نشده.</div>{% endif %}
  </div></div>

  <div class=card><h3>⏱ کارایی هر عملیات <span class=tag>موفقیت · میانگین · p95</span></h3>
    {% if s.op_perf %}
    <div class=tbl-wrap><table class=tbl>
      <thead><tr><th>عملیات</th><th>تعداد</th><th>موفق</th><th>میانگین</th><th>p95</th></tr></thead><tbody>
      {% for r in s.op_perf %}
      <tr><td>{{r.op}}</td><td class=num>{{r.n}}</td>
        <td class=num style="color:{{'#dc2626' if r.rate is not none and r.rate < 80 else '#16a34a'}}">
          {% if r.rate is not none %}{{r.rate}}٪{% else %}—{% endif %}</td>
        <td class=num><bdi>{{r.avg}}</bdi></td><td class=num><bdi>{{r.p95}}</bdi></td></tr>
      {% endfor %}</tbody></table></div>
    {% else %}<div class=empty>هنوز عملیاتِ تمام‌شده‌ای نیست.</div>{% endif %}
  </div>

  <div class=card><h3>⚠️ پرتکرارترین خطاها</h3><div class=pad>
    {% if s.errors %}{% for e in s.errors %}
    <div class=errline><span class=chip>{{e.n}}</span><code>{{e.msg}}</code></div>
    {% endfor %}{% else %}<div class=empty>خطایی ثبت نشده. 🎉</div>{% endif %}
  </div></div>

  <div class=card><h3>🔗 منبعِ فایل</h3><div class=rows>
    <div class=sv><b>آپلودِ کاربر</b><div class=meter><i style="width:{{s.src_up_pct}}%;background:var(--teal)"></i></div><span class=n>{{s.src_up}}</span></div>
    <div class=sv><b>دانلود از لینک</b><div class=meter><i style="width:{{s.src_dl_pct}}%;background:var(--amber)"></i></div><span class=n>{{s.src_dl}}</span></div>
  </div></div>

  <div class=card><h3>🌐 زبانِ کاربران</h3><div class=rows>
    {% for r in s.by_lang %}
    <div class=sv><b>{{r.k}}</b><div class=meter><i style="width:{{r.pct}}%;background:var(--teal2)"></i></div><span class=n>{{r.n}}</span></div>
    {% endfor %}
  </div></div>

  <div class=card><h3>📄 پرتکرارترین فرمت‌ها</h3><div class=rows>
    {% if s.by_ext %}{% for r in s.by_ext %}
    <div class=sv><b class=mono>{{r.k}}</b><div class=meter><i style="width:{{r.pct}}%;background:var(--teal)"></i></div><span class=n>{{r.n}}</span></div>
    {% endfor %}{% else %}<div class=empty>—</div>{% endif %}
  </div></div>

  <div class=card><h3>⚡ کشِ دانلود</h3><div class=rows>
    <div class=sv><b>ورودی‌ها</b><div class=meter><i style="width:100%;background:#e2e8f0"></i></div><span class=n>{{s.cache_rows}}</span></div>
    <div class=sv><b>تحویلِ آنی</b><div class=meter><i style="width:100%;background:var(--green)"></i></div><span class=n>{{s.cache_hits}}</span></div>
    <div class=sv><b>صرفه‌جویی</b><div class=meter><i style="width:100%;background:var(--teal2)"></i></div><span class=n><bdi>{{s.cache_saved_h}}</bdi></span></div>
  </div></div>
</div>
</div>
{% endblock %}"""

_LOGIN = """<!doctype html><html lang=fa dir=rtl><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>ورود · پنلِ تل‌ابزار</title>
<style>{{css}}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;
background:radial-gradient(120% 120% at 80% 0%,#134e4a,#0f172a 60%);padding:20px}
.wrap{display:flex;gap:34px;align-items:center;flex-wrap:wrap;justify-content:center}
.hero{color:#e2e8f0;width:300px}.hero .logo{font-size:28px;font-weight:800;color:#fff;margin-bottom:12px}
.hero p{font-size:14px;line-height:2;color:#94a3b8}
.lcard{width:360px;background:#fff;border-radius:20px;padding:28px;box-shadow:0 30px 60px rgba(0,0,0,.35)}
.lcard h2{font-size:18px}.lcard .sub{font-size:13px;color:#64748b;margin:6px 0 18px;line-height:1.9}
.err{background:#fef2f2;color:#b91c1c;font-size:13px;padding:10px 12px;border-radius:10px;margin-bottom:14px}
.sent{background:#ecfdf5;color:#047857;font-size:12.5px;font-weight:600;padding:9px 12px;border-radius:10px;margin-bottom:16px}
.lbl{font-size:12.5px;color:#475569;margin:0 0 8px;font-weight:600}
.lcard input{width:100%;height:46px;border:1.5px solid #cbd5e1;border-radius:12px;padding:0 14px;font-size:16px;
font-family:inherit;margin-bottom:14px;text-align:center;letter-spacing:2px;color:var(--ink);direction:ltr}
.lcard input:focus{outline:0;border-color:var(--teal2);box-shadow:0 0 0 3px rgba(20,184,166,.18)}
.btn{width:100%;height:46px;background:linear-gradient(90deg,#0d9488,#14b8a6);color:#fff;border:0;
border-radius:12px;font-size:15px;font-weight:700;font-family:inherit;box-shadow:0 8px 20px rgba(13,148,136,.3);cursor:pointer}
.muted{text-align:center;font-size:11.5px;color:#94a3b8;margin-top:14px}
</style></head><body><div class=wrap>
<div class=hero><div class=logo>🧰 تل‌ابزار</div>
<p>ورود با تأییدِ دومرحله‌ایِ تلگرام — بدونِ پسورد. فقط ادمین‌های ثبت‌شده.</p></div>
<div class=lcard>
{% if step == 2 %}
  <h2>کدِ تأیید</h2><p class=sub>کدی که ربات به تلگرامت فرستاد را وارد کن.</p>
  {% if sent %}<div class=sent>✅ کد به تلگرامِ ادمین ارسال شد</div>{% endif %}
  {% if error %}<div class=err>{{error}}</div>{% endif %}
  <form method=post action=/auth/verify>
    <input type=hidden name=admin_id value="{{admin_id}}">
    <div class=lbl>کدِ ۶ رقمی</div>
    <input name=code inputmode=numeric maxlength=6 autocomplete=one-time-code placeholder="------" autofocus>
    <button class=btn>ورود ↩</button>
  </form>
  <div class=muted>اعتبار تا ۵ دقیقه · تک‌مصرف</div>
{% else %}
  <h2>ورود به پنل</h2><p class=sub>شناسهٔ عددیِ تلگرامِ ادمین را وارد کن؛ یک کد برایت فرستاده می‌شود.</p>
  {% if error %}<div class=err>{{error}}</div>{% endif %}
  <form method=post action=/auth/request>
    <div class=lbl>شناسهٔ عددیِ ادمین</div>
    <input name=admin_id inputmode=numeric placeholder="123456789" autofocus style="letter-spacing:1px">
    <button class=btn>ارسالِ کد</button>
  </form>
{% endif %}
</div></div></body></html>"""

_TEXTS = """{% extends 'base' %}{% block title %}متن‌ها{% endblock %}{% block heading %}متن‌ها و لیبل‌ها{% endblock %}
{% block style %}
.tx-tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:14px 18px;margin:0;
  border-bottom:1px solid var(--line)}
.tx-tools .tag{margin-inline-start:auto}
.tx-list{padding:14px 18px}
.tx-cat{border:1px solid var(--line);border-radius:12px;margin-bottom:10px;background:rgba(255,255,255,.02);overflow:hidden}
.tx-cat:last-child{margin-bottom:0}
.tx-cat>summary{cursor:pointer;padding:12px 14px;font-weight:600;list-style:none;display:flex;align-items:center;gap:8px}
.tx-cat>summary::-webkit-details-marker{display:none}
.tx-cat>summary::before{content:'▸';color:#64748b;transition:transform .15s}
.tx-cat[open]>summary::before{transform:rotate(90deg)}
.tx-cat .cnt{color:#64748b;font-size:12px;font-weight:400}
.tx-cat .ed{color:var(--teal2);font-size:12px}
.tx-body{padding:0 14px 12px}
.tx-item{border-top:1px solid var(--line);padding:11px 0}
.tx-key{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tx-def{color:#94a3b8;font-size:12.5px;margin:6px 0;white-space:pre-wrap;word-break:break-word}
.tx-item textarea{flex:1;min-width:0;box-sizing:border-box;background:#f8fafc;color:var(--ink);border:1px solid #cbd5e1;
  border-radius:9px;padding:8px 10px;font-family:inherit;font-size:13.5px;line-height:1.7;resize:vertical}
.tx-item textarea:focus{outline:0;border-color:var(--teal2);background:#fff;box-shadow:0 0 0 3px rgba(20,184,166,.14)}
.tx-edit{display:flex;gap:8px;align-items:flex-start}
.tx-actions{display:flex;flex-direction:column;gap:6px;flex:none}
.tx-actions .btn-sm,.tx-actions .save-sm{width:100%;white-space:nowrap}
@media(max-width:640px){.tx-edit{flex-direction:column}.tx-actions{flex-direction:row;width:100%}}
.tx-err{background:rgba(220,38,38,.14);border:1px solid rgba(220,38,38,.5);color:#fecaca;padding:9px 12px;border-radius:10px;margin-bottom:10px}
{% endblock %}
{% block body %}
<div class=card>
  <form class=tx-tools method=get action=/texts>
    <select class=sel name=lang onchange="this.form.submit()">
      <option value=fa {% if lang=='fa' %}selected{% endif %}>فارسی</option>
      <option value=en {% if lang=='en' %}selected{% endif %}>English</option>
    </select>
    <input class=inp name=q value="{{q}}" placeholder="جست‌وجوی کلید یا متن…" style="flex:1;min-width:180px">
    <button class=btn-sm>جست‌وجو</button>
    {% if q %}<a class=btn-sm href="/texts?lang={{lang}}">پاک‌کردن</a>{% endif %}
    <span class=tag>{{total}} متن · {{edited}} ویرایش‌شده · بی‌ری‌استارت</span>
  </form>
  {% if saved %}<div class=saved style=margin-top:14px>✅ {{saved}}</div>{% endif %}
  {% if error %}<div class=tx-err style=margin-top:14px>⚠️ {{error}}</div>{% endif %}
  {% if not groups %}<div class=empty>چیزی مطابقِ «{{q}}» پیدا نشد.</div>{% endif %}
  <div class=tx-list>
  {% for g in groups %}
  <details class=tx-cat {% if g.open %}open{% endif %}>
    <summary>{{g.title}} <span class=cnt>({{g.n}})</span>
      {% if g.edited %}<span class=ed>· {{g.edited}} ویرایش‌شده</span>{% endif %}</summary>
    <div class=tx-body>
    {% for it in g['items'] %}
      <div class=tx-item>
        <div class=tx-key><code class=mono>{{it.key}}</code>
          {% if it.overridden %}<span class=chip>ویرایش‌شده</span>{% endif %}</div>
        <div class=tx-def>پیش‌فرض: {{it.default}}</div>
        <form method=post action=/texts/save>
          <input type=hidden name=key value="{{it.key}}">
          <input type=hidden name=lang value="{{lang}}">
          <input type=hidden name=q value="{{q}}">
          <div class=tx-edit>
            <textarea name=value rows=2>{{it.current}}</textarea>
            <div class=tx-actions>
              <button class=save-sm>ذخیره</button>
              {% if it.overridden %}
              <button class=btn-sm formaction=/texts/reset>بازگشت به پیش‌فرض</button>{% endif %}
            </div>
          </div>
        </form>
      </div>
    {% endfor %}
    </div>
  </details>
  {% endfor %}
  </div>
</div>{% endblock %}"""

_BUTTONS ="""{% extends 'base' %}{% block title %}کلیدها{% endblock %}{% block heading %}استایل و چیدمانِ کلیدها{% endblock %}
{% block style %}
.tgprev{background:linear-gradient(135deg,#dbeafe,#eef4fb);border:1px solid #cddcf0;border-radius:16px;padding:14px}
.tgmsg{background:#fff;border-radius:12px;padding:8px 12px;font-size:12.5px;color:#334155;margin-bottom:8px;display:inline-block}
.tgrow{display:flex;gap:6px;margin-bottom:6px}
.tgb{flex:1;display:flex;align-items:center;justify-content:center;padding:9px 8px;border-radius:8px;font-size:12.5px;font-weight:600;background:#f1f5f9;color:#1e293b;text-align:center}
.tgb.hid{opacity:.4;border:1px dashed #94a3b8;background:#fff}
.bt-row{display:flex;align-items:center;gap:8px;padding:8px 4px;border-bottom:1px dashed #eef2f7;background:#fff;border-radius:8px}
.bt-row .grip{color:#94a3b8;font-size:18px;cursor:grab;letter-spacing:-3px;user-select:none}
.bt-row .op{font-size:10.5px;color:#94a3b8;min-width:70px}
.bt-row .inp{height:32px}.bt-row .sel{height:32px}
.bt-row.dragging{opacity:.4;background:#f0fdfa}
.bt-head{display:flex;gap:8px;color:#94a3b8;font-size:11px;padding:2px 4px 6px;border-bottom:1px solid var(--line)}
{% endblock %}
{% block body %}
<div class=card>
  <h3>📱 پیش‌نمایشِ زنده <span class=tag>همان‌طور که کاربر می‌بیند</span></h3>
  <div class=tabs>
    {% for k, label in kinds %}<a class="tab {% if k==kind %}on{% endif %}" href="/buttons?kind={{k}}&lang={{lang}}">{{label}}</a>{% endfor %}
  </div>
  <div class=pad>
    <div class=tgprev>
      <div class=tgmsg>{{prev_msg}}</div>
      <div id=prevkeys>
        {% for row in pv_rows %}<div class=tgrow>{% for b in row %}<span class="tgb {{b.cls}}" {% if b.color %}style="background:{{b.color}};color:#fff"{% endif %}>{{b.text}}</span>{% endfor %}</div>{% endfor %}
        {% if hidden_items %}<div class=tgrow>{% for it in hidden_items %}<span class="tgb hid">👁‍🗨 {{it.text}}</span>{% endfor %}</div>{% endif %}
        <div class=tgrow><span class="tgb">{{close_label}}</span></div>
      </div>
    </div>
  </div>
</div>
<div class=card>
  <h3>✏️ چیدمان و استایلِ منوی «{{kindlabel}}» <span class=tag>بکش برای جابه‌جایی · بی‌ری‌استارت</span></h3>
  <div class=hint>متن · رنگ (آبی/سبز/قرمز) · ایموجیِ پرمیوم · عرض (تمام/نصف/یک‌سوم؛ ردیف‌ها را می‌سازد) · نمایش. زبانِ متن:
    <select class=sel style="height:30px" onchange="location.href='/buttons?kind={{kind}}&lang='+this.value">
      <option value=fa {% if lang=='fa' %}selected{% endif %}>فارسی</option>
      <option value=en {% if lang=='en' %}selected{% endif %}>English</option></select></div>
  {% if saved %}<div class=saved>✅ {{saved}}</div>{% endif %}
  <form method=post action=/buttons/save id=btnform>
    <input type=hidden name=kind value="{{kind}}">
    <input type=hidden name=lang value="{{lang}}">
    <input type=hidden name=order id=orderfield value="{{ items|map(attribute='op')|join(',') }}">
    <div class=pad style="padding-top:2px">
      <div class=bt-head><span style="width:22px"></span><span style="width:70px">op</span><span style="flex:1">متن</span>
        <span style="width:96px">رنگ</span><span style="width:96px">ایموجی</span><span style="width:104px">عرض</span><span style="width:44px">نمایش</span></div>
      <div id=rowlist>
      {% for it in items %}
        <div class=bt-row data-op="{{it.op}}">
          <span class=grip>⠿</span>
          <span class=op>{{it.op}}</span>
          <input class=inp name="text_{{it.op}}" value="{{it.text}}" style="flex:1;min-width:90px">
          <select class=sel name="style_{{it.op}}" style="width:96px">
            <option value="" {% if not it.style %}selected{% endif %}>—</option>
            <option value=primary {% if it.style=='primary' %}selected{% endif %}>آبی</option>
            <option value=success {% if it.style=='success' %}selected{% endif %}>سبز</option>
            <option value=danger {% if it.style=='danger' %}selected{% endif %}>قرمز</option></select>
          <input class=inp name="emoji_{{it.op}}" value="{{it.emoji}}" inputmode=numeric placeholder="—" style="width:96px;text-align:center">
          <select class=sel name="width_{{it.op}}" style="width:104px">
            <option value=full {% if it.width=='full' %}selected{% endif %}>تمام‌عرض</option>
            <option value=half {% if it.width=='half' %}selected{% endif %}>نصف</option>
            <option value=third {% if it.width=='third' %}selected{% endif %}>یک‌سوم</option></select>
          <input type=checkbox class=tg name="show_{{it.op}}" {% if not it.hidden %}checked{% endif %}>
        </div>
      {% endfor %}
      </div>
    </div>
    <button class=save>ذخیرهٔ منوی «{{kindlabel}}»</button>
    <button class=btn-sm formaction=/buttons/reset style="margin:0 18px 18px">بازگشت به چیدمانِ پیش‌فرضِ این منو</button>
  </form>
</div>
<script>
var CLOSE_LABEL = {{ close_label|tojson }};
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function colorOf(v){return {primary:'#3b82f6',success:'#22c55e',danger:'#ef4444'}[v]||'';}
function syncOrder(){
  var ops=[].map.call(document.querySelectorAll('#rowlist .bt-row'),function(r){return r.dataset.op;});
  document.getElementById('orderfield').value=ops.join(',');
}
function rebuildPreview(){
  var rows=[].slice.call(document.querySelectorAll('#rowlist .bt-row'));
  var vis=[];
  rows.forEach(function(r){
    var op=r.dataset.op;
    if(!r.querySelector('input.tg').checked) return;
    var text=r.querySelector('[name="text_'+op+'"]').value||op;
    var color=colorOf(r.querySelector('[name="style_'+op+'"]').value);
    var width=r.querySelector('[name="width_'+op+'"]').value;
    vis.push({text:text,color:color,width:width});
  });
  var cap={full:1,half:2,third:3},out=[],i=0;
  while(i<vis.length){var c=cap[vis[i].width]||3,j=i;
    while(j<vis.length&&j-i<c&&vis[j].width===vis[i].width)j++;
    out.push(vis.slice(i,j));i=j;}
  var html='';
  out.forEach(function(row){html+='<div class=tgrow>';
    row.forEach(function(b){html+='<span class="tgb" style="'+(b.color?('background:'+b.color+';color:#fff'):'')+'">'+esc(b.text)+'</span>';});
    html+='</div>';});
  html+='<div class=tgrow><span class="tgb">'+esc(CLOSE_LABEL)+'</span></div>';
  document.getElementById('prevkeys').innerHTML=html;
}
(function(){
  var list=document.getElementById('rowlist');
  list.querySelectorAll('.bt-row').forEach(function(row){
    var grip=row.querySelector('.grip');
    grip.addEventListener('mousedown',function(){row.setAttribute('draggable','true');});
    row.addEventListener('dragstart',function(){row.classList.add('dragging');});
    row.addEventListener('dragend',function(){row.classList.remove('dragging');row.setAttribute('draggable','false');syncOrder();rebuildPreview();});
  });
  list.addEventListener('dragover',function(e){e.preventDefault();
    var dragging=list.querySelector('.dragging');if(!dragging)return;
    var els=[].slice.call(list.querySelectorAll('.bt-row:not(.dragging)'));
    var after=els.reduce(function(cl,ch){var box=ch.getBoundingClientRect();var off=e.clientY-box.top-box.height/2;
      return (off<0&&off>cl.off)?{off:off,el:ch}:cl;},{off:-1e9,el:null}).el;
    if(after==null)list.appendChild(dragging);else list.insertBefore(dragging,after);
  });
  document.getElementById('btnform').addEventListener('input',rebuildPreview);
  document.getElementById('btnform').addEventListener('change',rebuildPreview);
  rebuildPreview();
})();
</script>{% endblock %}"""

_NODES = """{% extends 'base' %}{% block title %}نودها{% endblock %}{% block heading %}نودهای توزیع‌شده{% endblock %}
{% block style %}
.nd{display:flex;align-items:center;gap:12px;padding:12px;border:1px solid var(--line);border-radius:12px}
.nd+.nd{margin-top:9px}
.nd .st{width:9px;height:9px;border-radius:50%;flex:none}
.nd .on{background:#16a34a}.nd .off{background:#cbd5e1}
.nd .meta{flex:1;min-width:0}.nd .meta b{font-size:14px}
.nd .meta small{color:#94a3b8;font-size:11.5px;display:block;margin-top:2px}
.nd .rl{font-size:12px;background:#f0fdfa;color:var(--teal);padding:3px 9px;border-radius:8px;white-space:nowrap}
.cmd{background:#0b1220;color:#7dd3fc;font-family:ui-monospace,monospace;font-size:12.5px;padding:12px;border-radius:10px;
  word-break:break-all;line-height:1.9;user-select:all;direction:ltr;text-align:left;unicode-bidi:isolate}
.nd-form{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
.nd-form .inp{width:200px;text-align:start}
{% endblock %}
{% block body %}
<div class=card>
  <h3>🖧 نودها <span class=tag>{{nodes|length}} نود · {{online}} آنلاین</span>
    {% if reaped %}<span class=tag style="background:#fef3c7;color:#92400e">↩ {{reaped}} جابِ برگردانده‌شده</span>{% endif %}</h3>
  <div class=pad>
    {% if not master_ready %}<div class=errbox>⚠️ WireGuardِ مستر پیکربندی نشده (WG_MASTER_PUBKEY / WG_ENDPOINT / ADMIN_BASE). راهنما در README.</div>{% endif %}
    {% if not nodes %}<div class=empty>هنوز نودی وصل نشده. با «افزودن نود» یک دستورِ نصب بساز.</div>{% endif %}
    {% for n in nodes %}
    <div class=nd>
      <span class="st {{'on' if n.online else 'off'}}"></span>
      <div class=meta><b>{{n.emoji}} {{n.name}}</b>
        <small>{{n.role_label}} · <bdi>{{n.wg_ip}}</bdi>
        {%- if n.online %} · بار: <bdi>{{n.load}}</bdi> · انجام: <bdi>{{n.done}}</bdi> · نسخه <bdi>{{n.ver}}</bdi>
        {%- else %} · آفلاین{% endif %}</small></div>
      <span class=rl>{{n.role}}</span>
      <form method=post action=/nodes/remove onsubmit="return confirm('این نود حذف شود؟')">
        <input type=hidden name=id value="{{n.id}}">
        <button class=btn-sm>حذف</button></form>
    </div>
    {% endfor %}
  </div>
</div>
<div class=card>
  <h3>➕ افزودنِ نود</h3>
  <div class=pad>
    {% if token %}
      <div class=note>روی سرورِ نود (Ubuntu/Debian، با root) این را اجرا کن — توکن یک‌بارمصرف و ۳۰ دقیقه معتبر است:</div>
      <div class=cmd>{{install_cmd}}</div>
    {% else %}
      <div class=note>نقشِ نود را انتخاب کن؛ یک دستورِ نصب برایت می‌سازد.</div>
      <form class=nd-form method=post action=/nodes/add>
        <select class=sel name=role style="min-width:220px">
          {% for k, r in roles.items() %}<option value="{{k}}">{{r.emoji}} {{r.label}}</option>{% endfor %}
        </select>
        <input class=inp name=name placeholder="نامِ نود (مثلاً de-1)">
        <button class=btn-go>ساختِ دستورِ نصب</button>
      </form>
    {% endif %}
  </div>
</div>{% endblock %}"""

ENV = Environment(
    loader=DictLoader({
        "base": _BASE, "settings": _SETTINGS, "cookies": _COOKIES,
        "health": _HEALTH, "users": _USERS, "stats": _STATS, "login": _LOGIN,
        "texts": _TEXTS, "buttons": _BUTTONS, "nodes": _NODES,
    }),
    autoescape=select_autoescape(default=True, default_for_string=True),
)


def _render(name: str, **ctx) -> web.Response:
    ctx.setdefault("css", Markup(_CSS))
    ctx.setdefault("pfa", _PLATFORM_FA)
    html = ENV.get_template(name).render(**ctx)
    return web.Response(text=html, content_type="text/html")


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
    h["dl_active"] = await _int("dl:active")
    try:
        du = shutil.disk_usage(settings.work_dir)
        h["disk_total"] = round(du.total / 1024 ** 3)
        h["disk_used"] = round((du.total - du.free) / 1024 ** 3)
        h["disk_pct"] = round((du.total - du.free) / du.total * 100)
    except Exception:  # noqa: BLE001
        h["disk_total"] = 0
    h["pot"] = None
    if settings.pot_provider_url:
        h["pot"] = False
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
                async with s.get(settings.pot_provider_url + "/ping") as resp:
                    h["pot"] = resp.status == 200  # 404/403 = خطا، نه «آنلاین»
        except Exception:  # noqa: BLE001
            h["pot"] = False
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
    s["by_lang"] = _bars(lang_rows, lambda k: {"fa": "فارسی", "en": "English"}.get(k, k))
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
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


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
    """نامِ فایل را به یک basenameِ امنِ .txt تبدیل می‌کند (بدونِ traversal)."""
    base = os.path.basename((name or "").strip())
    base = _SAFE_NAME.sub("_", base).strip("._")
    if not base:
        return None
    if not base.lower().endswith(".txt"):
        base += ".txt"
    return base


# ── هندلرها ─────────────────────────────────────────────────────
def _login_page(step: int = 1, admin_id: str = "", sent: bool = False, error: str = "") -> web.Response:
    return _render("login", step=step, admin_id=admin_id, sent=sent, error=error)


async def login(request: web.Request) -> web.Response:
    if _session_admin(request):
        raise web.HTTPFound("/")
    return _login_page()


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


async def auth_request(request: web.Request) -> web.Response:
    form = await request.post()
    admin_id = (form.get("admin_id") or "").strip()
    if not admin_id.isdigit() or int(admin_id) not in settings.admin_id_set:
        return _login_page(error="شناسهٔ ادمین نامعتبر است.")
    r: aioredis.Redis = request.app["redis"]
    rk = f"panelreq:{admin_id}"
    n = await r.incr(rk)
    if n == 1:
        await r.expire(rk, 600)
    if n > 5:
        return _login_page(error="درخواستِ زیاد؛ چند دقیقه بعد امتحان کن.")
    code = f"{secrets.randbelow(1000000):06d}"
    await r.set(f"panelcode:{admin_id}", code, ex=300)
    await r.delete(f"paneltry:{admin_id}")
    if not await _send_code(int(admin_id), code):
        return _login_page(error="نتوانستم کد را بفرستم؛ مطمئن شو ربات را /start کرده‌ای.")
    return _login_page(step=2, admin_id=admin_id, sent=True)


async def auth_verify(request: web.Request) -> web.Response:
    form = await request.post()
    admin_id = (form.get("admin_id") or "").strip()
    code = (form.get("code") or "").strip()
    if not admin_id.isdigit():
        return _login_page(error="نامعتبر.")
    r: aioredis.Redis = request.app["redis"]
    tk = f"paneltry:{admin_id}"
    tries = await r.incr(tk)
    if tries == 1:
        await r.expire(tk, 300)
    if tries > 6:
        return _login_page(error="تلاشِ زیاد؛ از نو کد بگیر.")
    real = await r.get(f"panelcode:{admin_id}")
    if not real or code != real:
        return _login_page(step=2, admin_id=admin_id, sent=True, error="کد نادرست است.")
    await r.delete(f"panelcode:{admin_id}")
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
                   pill_ok=health["all_ok"], groups=GROUPS, meta=RUNTIME_KEYS,
                   enums=ENUM_VALUES, labels=ENUM_LABELS, longtext=LONGTEXT_KEYS,
                   v=await _effective(),
                   health=health, saved=request.query.get("saved") == "1")


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
    data = await _users_list(page, request.query.get("q", ""))
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
_TEXT_KEYS = sorted(set(CATALOG["fa"]) | set(CATALOG["en"]))

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
    return CATALOG.get(lang, {}).get(key) or CATALOG["fa"].get(key) or key


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
    from urllib.parse import quote_plus
    params = [f"lang={lang}"]
    if q:
        params.append("q=" + quote_plus(q))
    for k, v in extra.items():
        params.append(f"{k}=" + quote_plus(str(v)))
    return web.HTTPFound("/texts?" + "&".join(params))


async def texts_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    await textstore.refresh_if_stale()  # همیشه از DB تازه؛ نمای کهنه نده (باگِ ریست پس از update)
    lang = request.query.get("lang", "fa")
    if lang not in ("fa", "en"):
        lang = "fa"
    q = request.query.get("q", "")
    groups = _texts_groups(lang, q)
    total = sum(g["n"] for g in groups)
    edited = sum(g["edited"] for g in groups)
    saved = {"1": "متن ذخیره شد (بی‌ری‌استارت اعمال شد).",
             "r": "به پیش‌فرض برگشت."}.get(request.query.get("ok", ""), "")
    return _render("texts", admin_id=_session_admin(request), active="texts",
                   pill_ok=await _pill_ok(request.app), lang=lang, q=q,
                   groups=groups, total=total, edited=edited, saved=saved,
                   error=request.query.get("err", ""))


async def texts_save(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    lang = (form.get("lang") or "fa").strip()
    key = (form.get("key") or "").strip()
    q = (form.get("q") or "").strip()
    value = (form.get("value") or "").replace("\r\n", "\n")
    valid_key = key in CATALOG.get(lang, {}) or key in CATALOG["fa"]
    if lang not in ("fa", "en") or not valid_key:
        raise _texts_redirect(lang if lang in ("fa", "en") else "fa", q, err="کلیدِ نامعتبر.")
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
    lang = (form.get("lang") or "fa").strip()
    key = (form.get("key") or "").strip()
    q = (form.get("q") or "").strip()
    if lang in ("fa", "en") and key:
        await textstore.reset_text(lang, key)
    raise _texts_redirect(lang if lang in ("fa", "en") else "fa", q, ok="r")


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
    lang = request.query.get("lang", "fa")
    if lang not in ("fa", "en"):
        lang = "fa"
    items = _menu_editor_items(kind, lang)
    pv_rows, hidden_items = _menu_preview(items)
    saved = {"1": "ذخیره شد (بی‌ری‌استارت اعمال شد).",
             "r": "به چیدمانِ پیش‌فرض برگشت."}.get(request.query.get("ok", ""), "")
    return _render("buttons", admin_id=_session_admin(request), active="buttons",
                   pill_ok=await _pill_ok(request.app), kind=kind, lang=lang, kinds=_KIND_TABS,
                   kindlabel=_KIND_LABEL[kind], items=items, pv_rows=pv_rows,
                   hidden_items=hidden_items, close_label=_t(lang, "btn_close"),
                   prev_msg="🎬 نمونهٔ کارتِ فایل", saved=saved)


async def buttons_save(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    kind = (form.get("kind") or "video").strip()
    lang = (form.get("lang") or "fa").strip()
    if kind not in _KIND_LABEL or lang not in ("fa", "en"):
        raise web.HTTPFound("/buttons")
    key_by_op = dict(OPS_BY_KIND.get(kind, []))
    order = [op for op in (form.get("order") or "").split(",") if op in key_by_op]
    for op, _k in OPS_BY_KIND.get(kind, []):  # هر opِ جاافتاده را ته اضافه کن
        if op not in order:
            order.append(op)
    layout, styles = [], {}
    for op in order:
        layout.append({"op": op, "hidden": form.get(f"show_{op}") != "on",
                       "width": textstore.clean_width(form.get(f"width_{op}", "third"))})
        styles[op] = textstore.clean_button(form.get(f"style_{op}", ""), form.get(f"emoji_{op}", ""))
        # متنِ لیبل (per-lang) — فقط وقتی واقعاً عوض شده set/reset کن (تا bumpِ بی‌خود نزنیم)
        key = key_by_op[op]
        val = (form.get(f"text_{op}") or "").replace("\r\n", "\n").strip()
        default = _text_default(lang, key)
        cur = textstore.get_override(lang, key)
        if val and val != default.strip() and textstore.validate(default, val) is None:
            if cur != val:
                await textstore.set_text(lang, key, val)
        elif cur is not None:
            await textstore.reset_text(lang, key)
    await textstore.set_menu_layout(kind, layout)
    await textstore.set_button_styles(styles)
    raise web.HTTPFound(f"/buttons?kind={kind}&lang={lang}&ok=1")


async def buttons_reset(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    kind = (form.get("kind") or "video").strip()
    lang = (form.get("lang") or "fa").strip()
    if kind in _KIND_LABEL:
        await textstore.reset_menu_layout(kind)
    raise web.HTTPFound(f"/buttons?kind={kind}&lang={lang}&ok=r")


# ── نودهای توزیع‌شده (master/node روی WireGuard) ────────────────
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
    token = request.query.get("tok", "")
    base = settings.admin_base or (settings.public_base or "")
    install_cmd = f"curl -fsSL {base}/node/install.sh | sudo bash -s -- {token}" if token else ""
    master_ready = bool(settings.wg_master_pubkey and settings.wg_endpoint and base)
    reaped = await node_mod.reaped_count(request.app["redis"])
    return _render("nodes", admin_id=_session_admin(request), active="nodes",
                   pill_ok=await _pill_ok(request.app), nodes=items,
                   online=sum(1 for i in items if i["online"]), roles=node_mod.ROLES,
                   token=token, install_cmd=install_cmd, master_ready=master_ready,
                   reaped=reaped)


async def nodes_add(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    role = (form.get("role") or "").strip()
    if role not in node_mod.ROLES:
        raise web.HTTPFound("/nodes")
    tok = await node_mod.make_join_token(request.app["redis"], role)
    raise web.HTTPFound(f"/nodes?tok={tok}")


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
    payload = await node_mod.consume_join_token(request.app["redis"], token)
    if payload is None:
        return web.json_response({"error": "invalid or used token"}, status=403)
    if not pubkey or len(pubkey) > 64:
        return web.json_response({"error": "missing pubkey"}, status=400)
    role = payload["role"]
    async with Sessionmaker() as s:
        used = {ip for (ip,) in (await s.execute(select(Node.wg_ip))).all()}
        ip = node_mod.next_wg_ip(used)
        if ip is None:
            return web.json_response({"error": "wg subnet full"}, status=507)
        nid = secrets.token_urlsafe(9)[:12]
        s.add(Node(id=nid, name=name or f"{role}-{nid[:4]}", role=role, wg_ip=ip, wg_pubkey=pubkey))
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
    key = request.query.get("key") or request.headers.get("X-Node-Key") or ""
    secret = settings.node_secret or settings.bot_token or ""
    if not secret or not hmac.compare_digest(key, secret):
        return web.Response(text="# forbidden\n", status=403)
    async with Sessionmaker() as s:
        rows = (await s.execute(select(Node.wg_pubkey, Node.wg_ip))).all()
    peers = [(pk, ip) for (pk, ip) in rows if pk and ip]
    return web.Response(text=node_mod.render_peers(peers), content_type="text/plain")


_STATUS_FA = {ck_pool.HEALTHY: "سالم", ck_pool.SUSPECT: "مشکوک", ck_pool.INVALID: "باطل — نیازِ تعویض",
              ck_pool.COOLDOWN: "کنارگذاشته", ck_pool.DISABLED: "غیرفعال",
              ck_pool.FROZEN: "چک‌پوینت — نیازِ انسان"}
_STATUS_BADGE = {ck_pool.HEALTHY: "ok", ck_pool.SUSPECT: "warn", ck_pool.INVALID: "err",
                 ck_pool.COOLDOWN: "warn", ck_pool.DISABLED: "mute",
                 ck_pool.FROZEN: "err"}


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
                "badge": _STATUS_BADGE.get(a["status"], "mute"),
                "last_ok_fa": _ago_fa(a.get("last_ok") or 0),
                "added_fa": _ago_fa(a.get("added") or 0),
                "used": await ck_pool.usage(redis, a["name"]),
                "budget": ck_pool.budget_of(a, None, lim),
                "warming": ck_pool.warmup_factor(int(a.get("added") or 0), None, lim) < 1.0,
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
                                          if i["status"] in (ck_pool.HEALTHY, ck_pool.SUSPECT))})
    for key, items in by_platform.items():  # پلتفرم‌های خارج از فهرست
        groups.append({"platform": key, "items": items, "total": len(items),
                       "healthy": sum(1 for i in items
                                      if i["status"] in (ck_pool.HEALTHY, ck_pool.SUSPECT))})
    # صفِ رسیدگی: فریزشده (چک‌پوینت/۲FA) یا باطل — با تلاشِ خودکار درست نمی‌شوند
    attention = [{**a, "status_fa": _STATUS_FA.get(a["status"], a["status"]),
                  "badge": _STATUS_BADGE.get(a["status"], "mute")}
                 for a in accounts if a["status"] in (ck_pool.FROZEN, ck_pool.INVALID)]
    msg = {"up": "اکانت اضافه شد.", "del": "اکانت حذف شد.", "rep": "کوکی جایگزین شد.",
           "cd": "وضعیتِ اکانت به‌روزرسانی شد.",
           "fix": "اکانت به چرخش برگشت.",
           "ident": "هویتِ اکانت ذخیره شد."}.get(request.query.get("ok", ""), "")
    dl_node = await node_mod.role_online(redis, "download")
    mirrored = 0
    try:
        mirrored = await redis.scard(_CK_SET)
    except Exception:  # noqa: BLE001
        pass
    return _render("cookies", admin_id=_session_admin(request), active="cookies",
                   pill_ok=await _pill_ok(request.app), groups=groups,
                   platforms=COOKIE_PLATFORMS, dir_ok=_cookies_dir_ok(),
                   attention=attention, nodes=nodes,
                   cookies_dir=settings.cookies_dir, saved=msg,
                   error=request.query.get("err", ""),
                   dl_node_online=dl_node, mirrored=mirrored)


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
    raise web.HTTPFound("/cookies?ok=ident")


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
    raise web.HTTPFound("/cookies?ok=fix")


async def cookies_add(request: web.Request) -> web.Response:
    """افزودنِ اکانت با **چسباندنِ متنِ کوکی** (بدونِ آپلودِ فایل)."""
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    if not _cookies_dir_ok():
        raise web.HTTPFound("/cookies?err=" + "پوشهٔ کوکی‌ها نوشتنی نیست.")
    form = await request.post()
    platform = (form.get("platform") or "other").strip()
    label = (form.get("label") or "").strip()
    text, err = _normalize_cookie_text(form.get("content") or "")
    if err:
        raise web.HTTPFound("/cookies?err=" + err)
    if platform not in {k for k, _ in COOKIE_PLATFORMS}:
        platform = "other"
    err = _check_required(text, platform)
    if err:
        raise web.HTTPFound("/cookies?err=" + err)
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
        raise web.HTTPFound("/cookies?err=" + err)
    meta = await ck_pool.get_meta(redis, name)
    meta.update({"label": label or os.path.splitext(name)[0], "platform": platform,
                 "added": int(time.time()), "fail_streak": 0, "disabled": False})
    await ck_pool.set_meta(redis, name, meta)
    log.info("cookie account added: %s (%d bytes)", name, len(text))
    raise web.HTTPFound("/cookies?ok=up")


async def cookies_replace(request: web.Request) -> web.Response:
    """جایگزینیِ **درجای** کوکیِ یک اکانت (برچسب/تاریخچه حفظ، خطاها صفر می‌شوند)."""
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    if not _cookies_dir_ok():
        raise web.HTTPFound("/cookies?err=" + "پوشهٔ کوکی‌ها نوشتنی نیست.")
    form = await request.post()
    name = _safe_cookie_name(form.get("name") or "")
    text, err = _normalize_cookie_text(form.get("content") or "")
    if not name or err:
        raise web.HTTPFound("/cookies?err=" + (err or "اکانت نامعتبر."))
    redis = request.app["redis"]
    meta = await ck_pool.get_meta(redis, name)
    err = _check_required(text, meta.get("platform") or ck_pool.guess_platform(name))
    if err:
        raise web.HTTPFound("/cookies?err=" + err)
    err = await _save_cookie(redis, name, text)
    if err:
        raise web.HTTPFound("/cookies?err=" + err)
    await ck_pool.mark_ok(redis, name)      # کوکیِ تازه → سالم + کول‌داون پاک
    log.info("cookie replaced for %s", name)
    raise web.HTTPFound("/cookies?ok=rep")


async def cookies_delete(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    name = _safe_cookie_name(form.get("name") or "")
    if name and settings.cookies_dir:
        path = os.path.join(settings.cookies_dir, name)
        if os.path.isfile(path) and os.path.dirname(os.path.abspath(path)) == os.path.abspath(settings.cookies_dir):
            try:
                os.remove(path)
            except Exception:  # noqa: BLE001
                pass
            await _unmirror_cookie(request.app["redis"], name)  # از آینهٔ نودها هم بردار
            await ck_pool.del_meta(request.app["redis"], name)  # متادیتا + کول‌داون
    raise web.HTTPFound("/cookies?ok=del")


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
    raise web.HTTPFound("/cookies?ok=cd")


async def save(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    form = await request.post()
    store = settings_store.get_store()
    # فقط کلیدهایی که در فرم رندر شده‌اند (بقیه از /admin مدیریت می‌شوند و نباید ریست شوند)
    rendered = {key for _title, fields in GROUPS for key, _l, _h in fields}
    for k in rendered:
        kind, default = RUNTIME_KEYS[k]
        if kind == "bool":
            val = "on" if form.get(k) == "on" else "off"
            changed = (val == "on") != bool(default)
        else:
            val = (form.get(k) or "").strip()
            if k in ENUM_VALUES and val not in ENUM_VALUES[k]:
                continue
            if kind == "int" and not val.lstrip("-").isdigit():
                continue
            changed = str(val) != str(default)
        if store is not None:
            if changed:
                await store.set(k, val)
            else:
                await store.reset(k)
    raise web.HTTPFound("/?saved=1")


async def healthz(_: web.Request) -> web.Response:
    return web.Response(text="ok")


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
    try:
        await app["redis"].aclose()
    except Exception:  # noqa: BLE001
        pass


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", dashboard)
    app.router.add_get("/login", login)
    app.router.add_post("/auth/request", auth_request)
    app.router.add_post("/auth/verify", auth_verify)
    app.router.add_get("/logout", logout)
    app.router.add_post("/save", save)
    app.router.add_get("/cookies", cookies_page)
    app.router.add_post("/cookies/add", cookies_add)
    app.router.add_post("/cookies/replace", cookies_replace)
    app.router.add_post("/cookies/delete", cookies_delete)
    app.router.add_post("/cookies/unfreeze", cookies_unfreeze)
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
    app.router.add_get("/nodes", nodes_page)
    app.router.add_post("/nodes/add", nodes_add)
    app.router.add_post("/nodes/remove", nodes_remove)
    app.router.add_post("/node/join", node_join)      # عمومی (توکن گِیت)
    app.router.add_get("/node/install.sh", node_install)  # عمومی
    app.router.add_get("/node/peers", node_peers)         # گِیت با NODE_SECRET (wg-sync)
    app.router.add_get("/healthz", healthz)
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
    ctx = _ssl_context()
    log.info("Admin panel on :%s (tls=%s, admins=%d)",
             settings.admin_port, bool(ctx), len(settings.admin_id_set))
    web.run_app(build_app(), host="0.0.0.0", port=settings.admin_port, ssl_context=ctx, print=None)


if __name__ == "__main__":
    main()
