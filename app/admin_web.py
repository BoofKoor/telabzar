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
from sqlalchemy import func, select, text as sql_text

from . import settings_store
from . import textstore
from .config import settings
from .db import Sessionmaker
from .downloader import KNOWN_PLATFORMS, PLATFORM_LABELS
from .i18n import CATALOG
from .models import File, Job, User
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
        ("dl_pot_enabled", "توکنِ یوتیوب (pot-provider)", "اگر دانلودِ یوتیوب کرش کرد خاموشش کن"),
        ("dl_default_ux", "رفتارِ پیش‌فرضِ لینک", ""),
        ("dl_ux_youtube", "کیفیتِ یوتیوب", ""),
        ("dl_ux_instagram", "کیفیتِ اینستاگرام", ""),
        ("dl_ux_twitter", "کیفیتِ X / توییتر", ""),
        ("dl_ux_tiktok", "کیفیتِ تیک‌تاک", ""),
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
]

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
.top h1{font-size:17px}.who{display:flex;align-items:center;gap:14px;font-size:13px;color:var(--muted)}
.pill{display:inline-flex;align-items:center;gap:7px;background:#ecfdf5;color:#047857;padding:6px 12px;border-radius:999px;font-weight:600;font-size:12.5px}
.pill.bad{background:#fffbeb;color:#b45309}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green)}.pill.bad .dot{background:var(--amber)}
.lo{color:#64748b}
.body{padding:22px 26px}
.grid2{display:grid;grid-template-columns:1fr 372px;gap:20px;align-items:start}
@media(max-width:1000px){.grid2{grid-template-columns:1fr}}
.col{display:flex;flex-direction:column;gap:18px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.card h3{font-size:14px;font-weight:700;padding:15px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:9px}
.card h3 .tag{margin-inline-start:auto;font-size:11px;font-weight:600;color:var(--teal);background:#f0fdfa;padding:3px 9px;border-radius:8px}
.rows{padding:6px 18px 14px}
.row{display:flex;align-items:center;justify-content:space-between;padding:11px 0;border-bottom:1px dashed #eef2f7;gap:12px}
.row:last-child{border-bottom:0}.row label{font-size:13.5px;color:#334155}.row label small{display:block;color:#94a3b8;font-size:11.5px;margin-top:2px}
.inp{width:150px;height:36px;border:1px solid #cbd5e1;border-radius:9px;padding:0 11px;font-size:13.5px;font-family:inherit;text-align:center;background:#fff;color:var(--ink)}
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
.saved{background:#ecfdf5;color:#047857;font-size:13px;padding:10px 14px;border-radius:10px;margin-bottom:16px;font-weight:600}
.note{background:#eff6ff;color:#1d4ed8;font-size:12.5px;padding:10px 14px;border-radius:10px;margin-bottom:16px;line-height:1.9}
.errbox{background:#fef2f2;color:#b91c1c;font-size:12.5px;padding:10px 14px;border-radius:10px;margin-bottom:16px}
.tbl{width:100%;border-collapse:collapse}
.tbl th{text-align:right;font-size:11.5px;color:#94a3b8;font-weight:600;padding:9px 12px;border-bottom:1px solid var(--line)}
.tbl td{padding:12px;font-size:13px;border-bottom:1px dashed #eef2f7;vertical-align:middle}
.tbl tr:last-child td{border-bottom:0}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;color:#334155}
.chip{display:inline-block;font-size:11px;font-weight:600;padding:3px 9px;border-radius:8px;background:#f1f5f9;color:#475569}
.btn-sm{height:32px;padding:0 12px;border:1px solid #cbd5e1;background:#fff;border-radius:8px;font-size:12.5px;font-family:inherit;color:#334155;cursor:pointer}
.btn-sm:hover{background:#f8fafc}
.btn-danger{border-color:#fecaca;color:#b91c1c}.btn-danger:hover{background:#fef2f2}
.inline{display:inline}
.up{display:grid;grid-template-columns:1fr 190px 150px;gap:12px;align-items:end;padding:14px 18px}
@media(max-width:760px){.up{grid-template-columns:1fr}}
.up label{display:block;font-size:12px;color:#475569;margin-bottom:7px;font-weight:600}
.up input[type=file]{width:100%;font-size:12.5px;font-family:inherit}
.up .sel{width:100%}
.up button{height:38px;background:linear-gradient(90deg,var(--teal),var(--teal2));color:#fff;border:0;border-radius:10px;font-size:13.5px;font-weight:700;font-family:inherit;cursor:pointer}
.empty{font-size:13px;color:#94a3b8;padding:18px;text-align:center}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}
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
  <a class="{{'on' if active=='cookies'}}" href=/cookies>🍪 کوکی‌ها</a>
  <a class="{{'on' if active=='health'}}" href=/health>🩺 سلامت</a>
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

_COOKIES = """{% extends 'base' %}{% block title %}کوکی‌ها{% endblock %}{% block heading %}کوکی‌ها{% endblock %}
{% block body %}
{% if saved %}<div class=saved>✅ {{saved}}</div>{% endif %}
{% if error %}<div class=errbox>⚠️ {{error}}</div>{% endif %}
<div class=note>کوکی‌ها برای دانلودِ اینستاگرام/X/تیک‌تاک لازم‌اند (نیاز به ورود). چند اکانت اضافه کن تا
ربات بینشان بچرخد؛ اکانتی که بلاک بخورد خودکار برای ۳۰ دقیقه کنار گذاشته می‌شود. هم فایلِ
<span class=mono>cookies.txt</span> (Netscape) قبول است، هم خروجیِ <b>JSON</b>ِ افزونهٔ
<span class=mono>Cookie-Editor</span> (دکمهٔ Export → متن را در یک فایلِ <span class=mono>.txt</span>
بریز و همین‌جا آپلود کن). از اکانتِ یک‌بارمصرف استفاده کن، نه اصلی.
{% if not dir_ok %}<br><b>توجه:</b> پوشهٔ کوکی‌ها (<span class=mono>{{cookies_dir or 'COOKIES_DIR'}}</span>) پیدا/نوشتنی نیست.{% endif %}</div>
<div class=card style=margin-bottom:18px><h3>➕ افزودنِ کوکی</h3>
  <form method=post action=/cookies/upload enctype=multipart/form-data>
  <div class=up>
    <div><label>فایلِ cookies.txt</label><input type=file name=file accept=".txt" required></div>
    <div><label>پلتفرم</label><select class=sel name=platform>
      {% for key, fa in platforms %}<option value="{{key}}">{{fa}}</option>{% endfor %}
    </select></div>
    <div><label>برچسب (اختیاری)</label><input class=inp style=width:100% name=label placeholder="مثلاً acc1"></div>
  </div>
  <div style=padding:0_18px_16px><button class="btn-sm" style="background:linear-gradient(90deg,var(--teal),var(--teal2));color:#fff;border:0;height:38px;padding:0_18px;font-weight:700">بارگذاری</button></div>
  </form>
</div>
<div class=card><h3>🍪 اکانت‌های ذخیره‌شده <span class=tag>{{items|length}} فایل</span></h3>
{% if items %}
<table class=tbl><thead><tr><th>فایل</th><th>پلتفرم</th><th>حجم</th><th>وضعیت</th><th style=text-align:left>عملیات</th></tr></thead><tbody>
{% for c in items %}
<tr>
  <td class=mono>{{c.name}}</td>
  <td><span class=chip>{{ pfa.get(c.platform, c.platform) }}</span></td>
  <td class=num style=color:#64748b>{{c.size_kb}} KB</td>
  <td>{% if c.cooldown %}<span class="badge warn" style=margin:0>کنارگذاشته · {{c.cooldown_min}}′</span>{% else %}<span class="badge ok" style=margin:0>فعال</span>{% endif %}</td>
  <td style=text-align:left>
    <form class=inline method=post action=/cookies/cooldown><input type=hidden name=name value="{{c.name}}">
      <input type=hidden name=action value="{{'clear' if c.cooldown else 'set'}}">
      <button class=btn-sm>{{'فعال‌سازی' if c.cooldown else 'کنارگذاشتن'}}</button></form>
    <form class=inline method=post action=/cookies/delete onsubmit="return confirm('حذفِ {{c.name}}؟')">
      <input type=hidden name=name value="{{c.name}}"><button class="btn-sm btn-danger">حذف</button></form>
  </td>
</tr>
{% endfor %}
</tbody></table>
{% else %}<div class=empty>هنوز کوکی‌ای اضافه نشده.</div>{% endif %}
</div>
{% endblock %}"""

_HEALTH = """{% extends 'base' %}{% block title %}سلامت{% endblock %}{% block heading %}سلامتِ سیستم{% endblock %}
{% block body %}<div class=grid2>
<div class=col>""" + _HEALTH_CARDS + """</div>
<div class=col>
  <div class=card><h3>🍪 وضعیتِ کوکی‌ها</h3><div class=rows>
    {% if pool %}{% for p in pool %}
      <div class=svc>{{ pfa.get(p.platform, p.platform) }}
        <span class=num style="margin-inline-start:auto;color:#64748b">{{p.live}} فعال{% if p.cd %} · {{p.cd}} کنارگذاشته{% endif %}</span></div>
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
<table class=tbl><thead><tr><th>شناسهٔ تلگرام</th><th>نقش</th><th>فایل‌ها</th><th>ثبت‌نام</th><th>آخرین بازدید</th><th>وضعیت</th><th style=text-align:left>عملیات</th></tr></thead><tbody>
{% for u in users %}
<tr>
  <td class=mono>{{u.tg}}{% if u.is_admin %} <span class=tag2>ادمین</span>{% endif %}</td>
  <td><span class=chip>{{u.role}}</span></td>
  <td class=num>{{u.files}}</td>
  <td class=num style=color:#64748b>{{u.created}}</td>
  <td class=num style=color:#64748b>{{u.seen}}</td>
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
</tbody></table>
<div class=pager>
  <a class="{{'off' if page<=0}}" href="/users?page={{page-1}}{% if q %}&q={{q}}{% endif %}">→ قبلی</a>
  <span>صفحهٔ {{page+1}} از {{pages}}</span>
  <a class="{{'off' if page+1>=pages}}" href="/users?page={{page+1}}{% if q %}&q={{q}}{% endif %}">بعدی ←</a>
</div>
{% else %}<div class=empty>کاربری یافت نشد.</div>{% endif %}
</div>
{% endblock %}"""

_STATS = """{% extends 'base' %}{% block title %}آمار{% endblock %}{% block heading %}آمار{% endblock %}
{% block body %}
<div class=kpis>
  <div class=kpi2><b>{{s.users}}</b><span>کاربر {% if s.new7 %}<span class=up>+{{s.new7}} این هفته</span>{% endif %}</span></div>
  <div class=kpi2><b>{{s.active7}}</b><span>فعال (۷ روز)</span></div>
  <div class=kpi2><b>{{s.files}}</b><span>فایل</span></div>
  <div class=kpi2><b>{{s.storage_h}}</b><span>فضای پردازش‌شده</span></div>
  <div class=kpi2><b>{{s.dl_files}}</b><span>دانلود از لینک</span></div>
  <div class=kpi2><b>{{s.ops}}</b><span>عملیات {% if s.success_rate is not none %}<span class=up>{{s.success_rate}}٪ موفق</span>{% endif %}</span></div>
</div>
<div class=grid2>
<div class=col>
  <div class=card><h3>🗂 فایل‌ها بر اساسِ نوع</h3><div class=rows>
    {% if s.by_kind %}{% for r in s.by_kind %}
    <div class=bar-row><b>{{ kindfa.get(r.k, r.k) }}</b><div class=meter><i style="width:{{r.pct}}%;background:var(--teal2)"></i></div><span class=num>{{r.n}}</span></div>
    {% endfor %}{% else %}<div class=empty>هنوز فایلی نیست.</div>{% endif %}
  </div></div>
  <div class=card><h3>🔗 منبعِ فایل</h3><div class=rows>
    <div class=bar-row><b>آپلودِ کاربر</b><div class=meter><i style="width:{{s.src_up_pct}}%;background:var(--teal)"></i></div><span class=num>{{s.src_up}}</span></div>
    <div class=bar-row><b>دانلود از لینک</b><div class=meter><i style="width:{{s.src_dl_pct}}%;background:var(--amber)"></i></div><span class=num>{{s.dl_files}}</span></div>
  </div></div>
</div>
<div class=col>
  <div class=card><h3>⚙️ پرکاربردترین عملیات</h3><div class=rows>
    {% if s.by_op %}{% for r in s.by_op %}
    <div class=bar-row><b>{{ opfa.get(r.k, r.k) }}</b><div class=meter><i style="width:{{r.pct}}%;background:var(--green)"></i></div><span class=num>{{r.n}}</span></div>
    {% endfor %}{% else %}<div class=empty>هنوز عملیاتی اجرا نشده.</div>{% endif %}
  </div></div>
  <div class=card><h3>📅 ثبت‌نامِ ۷ روزِ اخیر</h3>
    <div class=hist>{% for d in s.signups %}<div class=b><em>{{d.n}}</em><i style="height:{{d.pct}}%"></i><span>{{d.day}}</span></div>{% endfor %}</div>
  </div>
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
font-family:inherit;margin-bottom:14px;text-align:center;letter-spacing:2px;color:var(--ink)}
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
    <input name=admin_id inputmode=numeric placeholder="مثلاً 123456789" autofocus style="letter-spacing:1px">
    <button class=btn>ارسالِ کد</button>
  </form>
{% endif %}
</div></div></body></html>"""

_TEXTS = """{% extends 'base' %}{% block title %}متن‌ها{% endblock %}{% block heading %}متن‌ها و لیبل‌ها{% endblock %}
{% block style %}
.tx-tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.tx-item{border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:10px;background:rgba(255,255,255,.02)}
.tx-key{display:flex;align-items:center;gap:8px;justify-content:space-between;flex-wrap:wrap}
.tx-def{color:#94a3b8;font-size:12.5px;margin:6px 0;white-space:pre-wrap;word-break:break-word}
.tx-item textarea{width:100%;box-sizing:border-box;background:#0b1220;color:#e2e8f0;border:1px solid var(--line);
  border-radius:9px;padding:8px;font-family:inherit;font-size:13.5px;line-height:1.7;resize:vertical}
.tx-row{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
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
    <span class=tag>بی‌ری‌استارت · HTML و ایموجیِ پرمیوم مجاز</span>
  </form>
  {% if saved %}<div class=saved>✅ {{saved}}</div>{% endif %}
  {% if error %}<div class=tx-err>⚠️ {{error}}</div>{% endif %}
  {% if not items %}
    <div class=empty>{% if q %}چیزی مطابقِ «{{q}}» پیدا نشد.{% else %}هنوز متنی ویرایش نشده. برای ویرایش، یک کلید یا متن را جست‌وجو کن.{% endif %}</div>
  {% endif %}
  {% for it in items %}
  <div class=tx-item>
    <div class=tx-key><code class=mono>{{it.key}}</code>
      {% if it.overridden %}<span class=chip>ویرایش‌شده</span>{% endif %}</div>
    <div class=tx-def>پیش‌فرض: {{it.default}}</div>
    <form method=post action=/texts/save>
      <input type=hidden name=key value="{{it.key}}">
      <input type=hidden name=lang value="{{lang}}">
      <input type=hidden name=q value="{{q}}">
      <textarea name=value rows=2>{{it.current}}</textarea>
      <div class=tx-row>
        <button class=save style="padding:8px 16px">ذخیره</button>
        {% if it.overridden %}
        <button class=btn-sm formaction=/texts/reset>بازگشت به پیش‌فرض</button>{% endif %}
      </div>
    </form>
  </div>
  {% endfor %}
  {% if truncated %}<div class=empty>فقط {{items|length}} موردِ اول نشان داده شد — جست‌وجو را دقیق‌تر کن.</div>{% endif %}
</div>{% endblock %}"""

ENV = Environment(
    loader=DictLoader({
        "base": _BASE, "settings": _SETTINGS, "cookies": _COOKIES,
        "health": _HEALTH, "users": _USERS, "stats": _STATS, "login": _LOGIN,
        "texts": _TEXTS,
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
        h["q_dl"] = await r.zcard("arq:queue:dl")
    except Exception:  # noqa: BLE001
        h["q_main"] = h["q_dl"] = 0
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


async def _stats() -> dict:
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    s: dict = {}
    async with Sessionmaker() as db:
        s["users"] = await db.scalar(select(func.count(User.id))) or 0
        s["active7"] = await db.scalar(select(func.count(User.id)).where(User.last_seen >= week)) or 0
        s["new7"] = await db.scalar(select(func.count(User.id)).where(User.created_at >= week)) or 0
        s["files"] = await db.scalar(select(func.count(File.id))) or 0
        storage = await db.scalar(select(func.coalesce(func.sum(File.size), 0))) or 0
        s["dl_files"] = await db.scalar(select(func.count(File.id)).where(File.source == "dl")) or 0
        s["ops"] = await db.scalar(select(func.count(Job.id))) or 0
        kind_rows = (await db.execute(select(File.kind, func.count(File.id))
                     .group_by(File.kind).order_by(func.count(File.id).desc()))).all()
        op_rows = (await db.execute(select(Job.op, func.count(Job.id))
                   .group_by(Job.op).order_by(func.count(Job.id).desc()).limit(8))).all()
        status_rows = {st: c for st, c in (await db.execute(
            select(Job.status, func.count(Job.id)).group_by(Job.status))).all()}
        signup_ts = (await db.execute(
            select(User.created_at).where(User.created_at >= week))).scalars().all()
    s["storage_h"] = _human_size(storage)
    s["src_dl"] = s["dl_files"]
    s["src_up"] = max(0, s["files"] - s["dl_files"])
    s["src_up_pct"] = round(s["src_up"] / s["files"] * 100) if s["files"] else 0
    s["src_dl_pct"] = round(s["src_dl"] / s["files"] * 100) if s["files"] else 0
    kmax = max((c for _, c in kind_rows), default=1) or 1
    s["by_kind"] = [{"k": k, "n": c, "pct": round(c / kmax * 100)} for k, c in kind_rows]
    omax = max((c for _, c in op_rows), default=1) or 1
    s["by_op"] = [{"k": k, "n": c, "pct": round(c / omax * 100)} for k, c in op_rows]
    done, failed = status_rows.get("done", 0), status_rows.get("failed", 0)
    s["success_rate"] = round(done / (done + failed) * 100) if (done + failed) else None
    keys = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    buckets = {k: 0 for k in keys}
    for ts in signup_ts:
        k = str(ts)[:10]
        if k in buckets:
            buckets[k] += 1
    smax = max(buckets.values(), default=1) or 1
    s["signups"] = [{"day": k[5:], "n": buckets[k], "pct": round(buckets[k] / smax * 100)} for k in keys]
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


async def _list_cookies(redis) -> list[dict]:
    d = settings.cookies_dir
    out: list[dict] = []
    if not d or not os.path.isdir(d):
        return out
    for f in sorted(glob.glob(os.path.join(d, "*.txt"))):
        base = os.path.basename(f)
        cd = 0
        if redis is not None:
            try:
                ttl = await redis.ttl(f"ckcd:{base}")
                cd = ttl if ttl and ttl > 0 else 0
            except Exception:  # noqa: BLE001
                cd = 0
        try:
            size_kb = round(os.path.getsize(f) / 1024, 1)
        except OSError:
            size_kb = 0
        out.append({"name": base, "platform": _guess_platform(base), "size_kb": size_kb,
                    "cooldown": cd, "cooldown_min": round(cd / 60)})
    return out


def _cookie_pool_summary(items: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for c in items:
        a = agg.setdefault(c["platform"], {"platform": c["platform"], "live": 0, "cd": 0})
        if c["cooldown"]:
            a["cd"] += 1
        else:
            a["live"] += 1
    return [agg[k] for k, _ in COOKIE_PLATFORMS if k in agg]


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
                   enums=ENUM_VALUES, labels=ENUM_LABELS, v=await _effective(),
                   health=health, saved=request.query.get("saved") == "1")


async def health_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    health = await _health(request.app)
    pool = _cookie_pool_summary(await _list_cookies(request.app["redis"]))
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
    return _render("stats", admin_id=_session_admin(request), active="stats",
                   pill_ok=await _pill_ok(request.app), s=await _stats(),
                   kindfa=_KIND_FA, opfa=_OP_FA)


# ── متن‌ها/لیبل‌ها (override زمانِ‌اجرا روی locales) ──────────────
_TEXT_KEYS = sorted(set(CATALOG["fa"]) | set(CATALOG["en"]))
_TEXTS_CAP = 100


def _text_default(lang: str, key: str) -> str:
    return CATALOG.get(lang, {}).get(key) or CATALOG["fa"].get(key) or key


def _texts_items(lang: str, q: str) -> tuple[list[dict], bool]:
    """بدونِ جست‌وجو فقط ویرایش‌شده‌ها؛ با جست‌وجو، تطبیق روی کلید/پیش‌فرض/متنِ فعلی."""
    ov = {k: v for (lg, k), v in textstore.snapshot().items() if lg == lang}
    ql = q.strip().lower()
    items: list[dict] = []
    for key in _TEXT_KEYS:
        override = ov.get(key)
        default = _text_default(lang, key)
        current = override if override is not None else default
        if ql:
            if ql not in key.lower() and ql not in default.lower() and ql not in current.lower():
                continue
        elif override is None:
            continue
        items.append({"key": key, "default": default, "current": current,
                      "overridden": override is not None})
    return items[:_TEXTS_CAP], len(items) > _TEXTS_CAP


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
    lang = request.query.get("lang", "fa")
    if lang not in ("fa", "en"):
        lang = "fa"
    q = request.query.get("q", "")
    items, truncated = _texts_items(lang, q)
    saved = {"1": "متن ذخیره شد (بی‌ری‌استارت اعمال شد).",
             "r": "به پیش‌فرض برگشت."}.get(request.query.get("ok", ""), "")
    return _render("texts", admin_id=_session_admin(request), active="texts",
                   pill_ok=await _pill_ok(request.app), lang=lang, q=q,
                   items=items, truncated=truncated, saved=saved,
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


async def cookies_page(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    items = await _list_cookies(request.app["redis"])
    msg = {"up": "کوکی اضافه شد.", "del": "کوکی حذف شد.",
           "cd": "وضعیتِ کوکی به‌روزرسانی شد."}.get(request.query.get("ok", ""), "")
    return _render("cookies", admin_id=_session_admin(request), active="cookies",
                   pill_ok=await _pill_ok(request.app), items=items,
                   platforms=COOKIE_PLATFORMS, dir_ok=_cookies_dir_ok(),
                   cookies_dir=settings.cookies_dir, saved=msg,
                   error=request.query.get("err", ""))


def _looks_like_cookiejar(text: str) -> bool:
    """اعتبارسنجیِ سبک: هدرِ Netscape یا خطوطِ tab-جدا (domain\\tflag\\t...)."""
    head = text.lstrip()[:200].lower()
    if head.startswith("# netscape") or "# http cookie file" in head:
        return True
    for line in text.splitlines():
        if line and not line.startswith("#") and line.count("\t") >= 5:
            return True
    return False


def _json_to_netscape(text: str) -> str | None:
    """خروجیِ JSONِ افزونه‌ها (Cookie-Editor / EditThisCookie) را به cookies.txtِ
    Netscape تبدیل می‌کند تا کاربر لازم نباشد فرمت را دستی عوض کند."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict):  # بعضی خروجی‌ها آرایه را می‌پیچند
        for key in ("cookies", "Request Cookies", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return None
    lines = ["# Netscape HTTP Cookie File", "# ساخته‌شده از خروجیِ JSON توسطِ پنلِ تل‌ابزار"]
    used = False
    for c in data:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        domain = c.get("domain") or c.get("host")
        if not name or not domain:
            continue
        value = c.get("value", "") or ""
        path = c.get("path") or "/"
        secure = bool(c.get("secure"))
        host_only = c.get("hostOnly")
        if host_only is None:
            host_only = not str(domain).startswith(".")
        include_sub = not host_only
        if include_sub and not str(domain).startswith("."):
            domain = "." + str(domain)
        exp = c.get("expirationDate") or c.get("expires") or c.get("expiry") or 0
        try:
            exp = max(0, int(float(exp)))
        except (TypeError, ValueError):
            exp = 0
        lines.append("\t".join([
            str(domain), "TRUE" if include_sub else "FALSE", str(path),
            "TRUE" if secure else "FALSE", str(exp), str(name), str(value),
        ]))
        used = True
    return "\n".join(lines) + "\n" if used else None


async def cookies_upload(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    if not _cookies_dir_ok():
        raise web.HTTPFound("/cookies?err=" + "پوشهٔ کوکی‌ها نوشتنی نیست.")
    reader = await request.multipart()
    platform, label, content = "other", "", b""
    async for part in reader:
        if part.name == "platform":
            platform = (await part.text()).strip() or "other"
        elif part.name == "label":
            label = (await part.text()).strip()
        elif part.name == "file":
            content = await part.read(decode=False)
    if not content:
        raise web.HTTPFound("/cookies?err=" + "فایلی انتخاب نشد.")
    if len(content) > 512 * 1024:
        raise web.HTTPFound("/cookies?err=" + "فایل خیلی بزرگ است.")
    try:
        text = content.decode("utf-8-sig", "replace")
    except Exception:  # noqa: BLE001
        raise web.HTTPFound("/cookies?err=" + "فایل خوانا نیست.")
    if not _looks_like_cookiejar(text):
        converted = _json_to_netscape(text)  # خروجیِ JSONِ Cookie-Editor را هم بپذیر
        if converted:
            text = converted
        else:
            raise web.HTTPFound(
                "/cookies?err=" + "نه cookies.txt (Netscape) است نه JSONِ معتبرِ کوکی.")
    if platform not in {k for k, _ in COOKIE_PLATFORMS}:
        platform = "other"
    # نامِ فایل: پلتفرم + برچسب، تا `_pick_cookies` با substringِ platform تطبیقش دهد.
    stem = platform if platform != "other" else "cookies"
    if label:
        stem += "_" + label
    name = _safe_cookie_name(stem) or "cookies.txt"
    dest = os.path.join(settings.cookies_dir, name)
    if os.path.exists(dest):  # برخورد → پسوندِ کوتاه
        name = _safe_cookie_name(f"{stem}_{secrets.token_hex(2)}") or name
        dest = os.path.join(settings.cookies_dir, name)
    try:
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        raise web.HTTPFound("/cookies?err=" + "ذخیره نشد.")
    try:
        os.chmod(dest, 0o600)  # best-effort؛ روی برخی bind-mountها اجازه ندارد
    except OSError:
        pass
    log.info("cookie uploaded: %s (%d bytes)", name, len(content))
    raise web.HTTPFound("/cookies?ok=up")


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
                await request.app["redis"].delete(f"ckcd:{name}")
            except Exception:  # noqa: BLE001
                pass
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
    app.router.add_post("/cookies/upload", cookies_upload)
    app.router.add_post("/cookies/delete", cookies_delete)
    app.router.add_post("/cookies/cooldown", cookies_cooldown)
    app.router.add_get("/health", health_page)
    app.router.add_get("/users", users_page)
    app.router.add_post("/users/block", users_block)
    app.router.add_get("/stats", stats_page)
    app.router.add_get("/texts", texts_page)
    app.router.add_post("/texts/save", texts_save)
    app.router.add_post("/texts/reset", texts_reset)
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
