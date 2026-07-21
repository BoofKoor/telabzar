"""پنلِ ادمینِ وب (فاز D1) — aiohttp + Jinja2.

ورود: ادمین شناسهٔ عددی‌اش را می‌زند → کدِ ۶رقمی از ربات به تلگرامش می‌رود →
کد را وارد می‌کند → سشنِ رمزنگاری‌شده (کوکی). فقط `ADMIN_IDS`.
صفحه‌ها: تنظیمات (روی settings_store) + ستونِ سلامت. اجرا: python -m app.admin_web
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import shutil
import ssl
import time
from datetime import datetime, timezone

import aiohttp
import redis.asyncio as aioredis
from aiohttp import web
from cryptography.fernet import Fernet, InvalidToken
from jinja2 import Template
from sqlalchemy import text as sql_text

from . import settings_store
from .config import settings
from .db import Sessionmaker
from .settings_store import ENUM_VALUES, RUNTIME_KEYS

log = logging.getLogger("telabzar.admin")

_COOKIE = "tab_admin"
_SESSION_TTL = 8 * 3600

# گروه‌بندیِ کلیدها برای فرم: (عنوانِ کارت, [(کلید, برچسب, توضیح)])
GROUPS = [
    ("🚦 سقف‌ها و کنترلِ مصرف", [
        ("rate_per_min", "نرخ در دقیقه", "۰ = نامحدود"),
        ("daily_op_quota", "سقفِ روزانهٔ عملیات", "هر کاربر · ۰ = نامحدود"),
        ("max_file_mb", "حداکثر حجمِ فایل (MB)", ""),
    ]),
    ("⬇️ دانلودر", [
        ("downloader_enabled", "دانلودر فعال", ""),
        ("dl_default_ux", "رفتارِ پیش‌فرضِ لینک", ""),
        ("dl_ux_youtube", "کیفیتِ یوتیوب", ""),
        ("dl_ux_instagram", "کیفیتِ اینستاگرام", ""),
        ("dl_max_size_mb", "حداکثر حجمِ دانلود (MB)", ""),
        ("dl_concurrency", "دانلودِ هم‌زمان (کل)", ""),
        ("dl_daily_count", "سقفِ روزانهٔ دانلود", "هر کاربر · ۰ = نامحدود"),
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
        return int(data["id"])
    except (InvalidToken, ValueError, KeyError):
        return None


# ── قالب‌ها ─────────────────────────────────────────────────────
_CSS = """
*{margin:0;padding:0;box-sizing:border-box;font-family:'Vazirmatn','Segoe UI',Tahoma,system-ui,sans-serif}
:root{--bg:#eef2f7;--card:#fff;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--teal:#0d9488;
--teal2:#14b8a6;--green:#16a34a;--amber:#d97706;--red:#dc2626}
body{background:var(--bg);color:var(--ink)}
a{text-decoration:none}
"""

LOGIN_HTML = Template("""<!doctype html><html lang=fa dir=rtl><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>ورود · پنلِ تل‌ابزار</title>
<style>{{css}}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;
background:radial-gradient(120% 120% at 80% 0%,#134e4a,#0f172a 60%);padding:20px}
.wrap{display:flex;gap:34px;align-items:center;flex-wrap:wrap;justify-content:center}
.hero{color:#e2e8f0;width:300px}.hero .logo{font-size:28px;font-weight:800;color:#fff;margin-bottom:12px}
.hero p{font-size:14px;line-height:2;color:#94a3b8}
.card{width:360px;background:#fff;border-radius:20px;padding:28px;box-shadow:0 30px 60px rgba(0,0,0,.35)}
.card h2{font-size:18px}.card .sub{font-size:13px;color:#64748b;margin:6px 0 18px;line-height:1.9}
.err{background:#fef2f2;color:#b91c1c;font-size:13px;padding:10px 12px;border-radius:10px;margin-bottom:14px}
.sent{background:#ecfdf5;color:#047857;font-size:12.5px;font-weight:600;padding:9px 12px;border-radius:10px;margin-bottom:16px}
.lbl{font-size:12.5px;color:#475569;margin:0 0 8px;font-weight:600}
input{width:100%;height:46px;border:1.5px solid #cbd5e1;border-radius:12px;padding:0 14px;font-size:16px;
font-family:inherit;margin-bottom:14px;text-align:center;letter-spacing:2px}
.btn{width:100%;height:46px;background:linear-gradient(90deg,#0d9488,#14b8a6);color:#fff;border:0;
border-radius:12px;font-size:15px;font-weight:700;font-family:inherit;box-shadow:0 8px 20px rgba(13,148,136,.3);cursor:pointer}
.muted{text-align:center;font-size:11.5px;color:#94a3b8;margin-top:14px}
</style></head><body><div class=wrap>
<div class=hero><div class=logo>🧰 تل‌ابزار</div>
<p>ورود با تأییدِ دومرحله‌ایِ تلگرام — بدونِ پسورد. فقط ادمین‌های ثبت‌شده.</p></div>
<div class=card>
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
</div></div></body></html>""")

DASHBOARD_HTML = Template("""<!doctype html><html lang=fa dir=rtl><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>پنلِ مدیریت · تل‌ابزار</title>
<style>{{css}}
.app{display:flex;min-height:100vh}
.side{width:236px;background:linear-gradient(180deg,#0f172a,#15223b);color:#cbd5e1;display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
.brand{padding:22px;font-size:20px;font-weight:800;color:#fff}.brand small{display:block;font-size:11px;color:#7dd3fc;margin-top:2px}
.nav{padding:8px 12px;display:flex;flex-direction:column;gap:4px}
.nav a{display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:11px;color:#cbd5e1;font-size:14.5px}
.nav a.on{background:linear-gradient(90deg,rgba(20,184,166,.22),rgba(20,184,166,.05));color:#fff;box-shadow:inset 3px 0 0 var(--teal2)}
.nav a.soon{opacity:.5}.foot{margin-top:auto;padding:16px 20px;font-size:12px;color:#64748b}
.main{flex:1}.top{height:62px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 26px;position:sticky;top:0;z-index:5}
.top h1{font-size:17px}.who{display:flex;align-items:center;gap:14px;font-size:13px;color:var(--muted)}
.pill{display:inline-flex;align-items:center;gap:7px;background:{{ 'ecfdf5' if health.all_ok else 'fffbeb' }};color:{{ '047857' if health.all_ok else 'b45309' }};padding:6px 12px;border-radius:999px;font-weight:600;font-size:12.5px}
.dot{width:8px;height:8px;border-radius:50%;background:{{ '#16a34a' if health.all_ok else '#d97706' }}}
.body{padding:22px 26px;display:grid;grid-template-columns:1fr 372px;gap:20px;align-items:start}
@media(max-width:1000px){.body{grid-template-columns:1fr}}
.col{display:flex;flex-direction:column;gap:18px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.card h3{font-size:14px;font-weight:700;padding:15px 18px;border-bottom:1px solid var(--line);display:flex;gap:9px}
.card h3 .tag{margin-inline-start:auto;font-size:11px;font-weight:600;color:var(--teal);background:#f0fdfa;padding:3px 9px;border-radius:8px}
.rows{padding:6px 18px 14px}
.row{display:flex;align-items:center;justify-content:space-between;padding:11px 0;border-bottom:1px dashed #eef2f7;gap:12px}
.row:last-child{border-bottom:0}.row label{font-size:13.5px;color:#334155}.row label small{display:block;color:#94a3b8;font-size:11.5px;margin-top:2px}
.inp{width:150px;height:36px;border:1px solid #cbd5e1;border-radius:9px;padding:0 11px;font-size:13.5px;font-family:inherit;text-align:center;background:#fff}
.sel{width:160px;height:36px;border:1px solid #cbd5e1;border-radius:9px;padding:0 8px;font-size:13.5px;font-family:inherit;background:#fff}
.tg{appearance:none;width:46px;height:26px;border-radius:999px;background:#cbd5e1;position:relative;cursor:pointer}
.tg:checked{background:var(--teal2)}.tg::after{content:'';position:absolute;width:20px;height:20px;border-radius:50%;background:#fff;top:3px;right:3px;transition:.15s}
.tg:checked::after{right:23px}
.save{margin:2px 18px 18px;height:44px;width:calc(100% - 36px);background:linear-gradient(90deg,var(--teal),var(--teal2));color:#fff;border:0;border-radius:11px;font-size:15px;font-weight:700;font-family:inherit;cursor:pointer;box-shadow:0 6px 16px rgba(13,148,136,.28)}
.svc{display:flex;align-items:center;gap:10px;padding:9px 0;font-size:13.5px}.svc:not(:last-child){border-bottom:1px dashed #eef2f7}
.badge{margin-inline-start:auto;font-size:11.5px;font-weight:700;padding:3px 9px;border-radius:8px}
.ok{background:#ecfdf5;color:#047857}.warn{background:#fffbeb;color:#b45309}
.meter{height:9px;border-radius:999px;background:#e2e8f0;overflow:hidden}.meter i{display:block;height:100%;border-radius:999px}
.stat{display:flex;align-items:center;gap:10px;margin:12px 0;font-size:13px}.stat b{width:82px;color:#475569}.stat .meter{flex:1}
.mini{display:flex;gap:10px;padding:6px 18px 14px}.kpi{flex:1;background:#f8fafc;border:1px solid var(--line);border-radius:12px;padding:12px;text-align:center}
.kpi b{font-size:22px;color:var(--teal)}.kpi span{display:block;font-size:11.5px;color:var(--muted);margin-top:3px}
.saved{background:#ecfdf5;color:#047857;font-size:13px;padding:10px 14px;border-radius:10px;margin-bottom:16px;font-weight:600}
</style></head><body><div class=app>
<aside class=side><div class=brand>🧰 تل‌ابزار<small>پنلِ مدیریت</small></div>
<nav class=nav><a class=on href=/>⚙️ تنظیمات</a><a class=soon>🍪 کوکی‌ها</a><a class=soon>🩺 سلامت</a>
<a class=soon>👤 کاربران</a><a class=soon>📊 آمار</a></nav>
<div class=foot>نسخهٔ ۱.۰ · D1</div></aside>
<div class=main><div class=top><h1>تنظیمات</h1><div class=who>
<span class=pill><span class=dot></span> {{ 'همه سرویس‌ها آنلاین' if health.all_ok else 'بررسیِ سرویس‌ها' }}</span>
<span>ادمین · {{admin_id}}</span><a href=/logout style=color:#64748b>خروج ↩</a></div></div>
<div class=body>
  <div class=col>
    {% if saved %}<div class=saved>✅ تغییرات ذخیره شد (بدونِ ری‌استارت اعمال شد).</div>{% endif %}
    <form method=post action=/save>
    {% for title, fields in groups %}
      <div class=card><h3>{{title}}{% if loop.first %}<span class=tag>بدونِ ری‌استارت</span>{% endif %}</h3><div class=rows>
      {% for key, label, hint in fields %}
        <div class=row><label>{{label}}{% if hint %}<small>{{hint}}</small>{% endif %}</label>
        {% set kind = meta[key][0] %}
        {% if kind == 'bool' %}
          <input class=tg type=checkbox name="{{key}}" {% if v[key] %}checked{% endif %}>
        {% elif key in enums %}
          <select class=sel name="{{key}}">
            {% for opt in enums[key] %}<option value="{{opt}}" {% if v[key]|string == opt %}selected{% endif %}>{{ labels.get(opt, opt) }}</option>{% endfor %}
          </select>
        {% else %}
          <input class=inp name="{{key}}" value="{{v[key]}}">
        {% endif %}
        </div>
      {% endfor %}
      </div></div>
    {% endfor %}
      <button class=save>ذخیرهٔ تغییرات</button>
    </form>
  </div>
  <div class=col>
    <div class=card><h3>🩺 سلامتِ سرویس‌ها</h3><div class=rows>
      <div class=svc>🗄 Postgres <span class="badge {{ 'ok' if health.postgres else 'warn' }}">{{ 'آنلاین' if health.postgres else 'خطا' }}</span></div>
      <div class=svc>⚡ Redis <span class="badge {{ 'ok' if health.redis else 'warn' }}">{{ 'آنلاین' if health.redis else 'خطا' }}</span></div>
      <div class=svc>🔑 pot-provider <span class="badge {{ 'ok' if health.pot else 'warn' }}">{{ 'آنلاین' if health.pot else '—' }}</span></div>
    </div></div>
    <div class=card><h3>📦 صف و دیسک</h3><div class=rows>
      <div class=mini style=padding-inline:0>
        <div class=kpi><b>{{health.q_main}}</b><span>صفِ پردازش</span></div>
        <div class=kpi><b>{{health.q_dl}}</b><span>صفِ دانلود</span></div>
        <div class=kpi><b>{{health.dl_active}}</b><span>دانلودِ فعال</span></div>
      </div>
      {% if health.disk_total %}<div class=stat><b>دیسکِ ‎/work</b><div class=meter><i style="width:{{health.disk_pct}}%;background:{{ '#dc2626' if health.disk_pct>85 else '#14b8a6' }}"></i></div><span>{{health.disk_used}}/{{health.disk_total}}G</span></div>{% endif %}
    </div></div>
    <div class=card><h3>📈 نرخِ موفقیتِ دانلود <span class=tag>امروز</span></h3><div class=rows>
      {% if health.hosts %}{% for host, rate in health.hosts.items() %}
        <div class=stat><b>{{host}}</b><div class=meter><i style="width:{{rate}}%;background:{{ '#16a34a' if rate>=70 else '#d97706' }}"></i></div><span>{{rate}}%</span></div>
      {% endfor %}{% else %}<div style="font-size:12.5px;color:#94a3b8;padding:6px 0">هنوز دانلودی امروز ثبت نشده.</div>{% endif %}
    </div></div>
  </div>
</div></div></div></body></html>""")


# ── هلث ─────────────────────────────────────────────────────────
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
    # دیسک
    try:
        du = shutil.disk_usage(settings.work_dir)
        h["disk_total"] = round(du.total / 1024 ** 3)
        h["disk_used"] = round((du.total - du.free) / 1024 ** 3)
        h["disk_pct"] = round((du.total - du.free) / du.total * 100)
    except Exception:  # noqa: BLE001
        h["disk_total"] = 0
    # pot-provider ping
    h["pot"] = False
    if settings.pot_provider_url:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
                async with s.get(settings.pot_provider_url + "/ping") as resp:
                    h["pot"] = resp.status < 500
        except Exception:  # noqa: BLE001
            h["pot"] = False
    else:
        h["pot"] = None
    # نرخِ per-host امروز
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    hosts = {}
    for p in ("youtube", "instagram", "tiktok", "twitter"):
        ok = await _int(f"dlstat:{p}:ok:{day}")
        fail = await _int(f"dlstat:{p}:fail:{day}")
        if ok + fail:
            hosts[p] = round(ok / (ok + fail) * 100)
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


# ── هندلرها ─────────────────────────────────────────────────────
def _login_page(step: int = 1, admin_id: str = "", sent: bool = False, error: str = "") -> web.Response:
    html = LOGIN_HTML.render(css=_CSS, step=step, admin_id=admin_id, sent=sent, error=error)
    return web.Response(text=html, content_type="text/html")


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
    resp.set_cookie(_COOKIE, _make_session(int(admin_id)), max_age=_SESSION_TTL,
                    httponly=True, secure=True, samesite="Lax")
    raise resp


async def logout(_: web.Request) -> web.Response:
    resp = web.HTTPFound("/login")
    resp.del_cookie(_COOKIE)
    raise resp


async def dashboard(request: web.Request) -> web.Response:
    if not _session_admin(request):
        raise web.HTTPFound("/login")
    html = DASHBOARD_HTML.render(
        css=_CSS, admin_id=_session_admin(request), groups=GROUPS, meta=RUNTIME_KEYS,
        enums=ENUM_VALUES, labels=ENUM_LABELS, v=await _effective(),
        health=await _health(request.app), saved=request.query.get("saved") == "1")
    return web.Response(text=html, content_type="text/html")


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
    app.router.add_get("/healthz", healthz)
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
