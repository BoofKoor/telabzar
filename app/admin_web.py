"""پنلِ ادمینِ وب — aiohttp + Jinja2 (بازطراحیِ ۲۰۲۶-۱۰).

ورود: ادمین شناسهٔ تلگرامی‌اش را می‌زند → کدِ ۶رقمی از ربات به تلگرامش می‌رود →
کد را وارد می‌کند → نشستِ رمزنگاری‌شده (کوکی، Fernet). فقط `ADMIN_IDS`.

**ساختار:** صفحه‌ها سرورساید رندر می‌شوند و بدونِ JS هم کار می‌کنند (فرم می‌رود،
لینک می‌رود)؛ `app/static/js/panel.js` روی همان HTML نمودار، منو، دیالوگ، نوارِ
ذخیره و جست‌وجو را اضافه می‌کند. **هر عدد** از `panel_data` می‌آید و **هر متنِ
خودِ پنل** از `panel_i18n` (fa/en) — این فایل فقط هندلر و رندر است.

اجرا: python -m app.admin_web
"""
from __future__ import annotations

import asyncio
import base64
import contextvars
import glob
import gzip
import hashlib
import hmac
import ipaddress
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
from urllib.parse import parse_qsl, urlencode, urlsplit

import aiohttp
import redis.asyncio as aioredis
from aiohttp import web
from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.x509.oid import NameOID
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from sqlalchemy import select, text as sql_text

from . import cookies as ck_pool
from . import counters
from . import dl_active
from . import langpack
from . import nodes as node_mod
from . import panel_data as PD
from . import panel_fmt as F
from . import panel_settings as PS
from . import settings_store
from . import textstore
from .config import settings
from .db import Sessionmaker
from .downloader import PLATFORM_LABELS, PLATFORM_LABELS_EN
from .i18n import (
    BUILTIN_NAMES,
    DEFAULT as i18n_DEFAULT,
    available_languages as i18n_available_languages,
    default_text,
    t as _t,
)
from .keyboards import OPS_BY_KIND
from .models import AdminAction, Node, User
from .panel_i18n import DIR as _PANEL_DIR_OF
from .panel_i18n import LANGS as PANEL_LANGS
from .panel_i18n import STRINGS as _PANEL_STRINGS
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
#: `mimetypes`ِ پایتون `woff2` را نمی‌شناسد؛ بدونِ این خط فونت با
#: `application/octet-stream` سرو می‌شد.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("text/javascript", ".js")

#: پلتفرم‌هایی که فرمِ «افزودنِ اکانت» پیشنهاد می‌دهد (نامِ فایل باید کلید را داشته
#: باشد تا `cookies.guess_platform` تطبیقش دهد — مثلِ `instagram_1.txt`). X همان twitter است.
COOKIE_PLATFORMS = [
    ("instagram", "اینستاگرام"),
    ("youtube", "یوتیوب"),
    ("twitter", "X / توییتر"),
    ("tiktok", "تیک‌تاک"),
    ("pinterest", "پینترست"),
    ("other", "عمومی / سایر"),
]
_COOKIE_PLATFORM_KEYS = tuple(k for k, _ in COOKIE_PLATFORMS)


# ── نشستِ رمزنگاری‌شده (کوکی؛ بدونِ نیاز به ذخیرهٔ سمتِ سرور) ──────
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
    هر نود داده می‌شود (`nodes.node_config`)، پس «راز» نیست.
    """
    seed = settings.admin_secret
    if not seed:
        raise RuntimeError(_NO_SECRET)
    key = base64.urlsafe_b64encode(hashlib.sha256(f"telabzar-admin:{seed}".encode()).digest())
    return Fernet(key)


def _require_admin_secret() -> None:
    """پیش از سرو کردن، نبودِ راز را **بلند** اعلام و پروسه را متوقف می‌کند.

    عمداً refuse-to-start است نه هشدار: شعاعش فقط کانتینرِ `admin` است، `/admin`ِ
    تلگرام دست‌نخورده می‌ماند، و «‏.env گم شد» از قبل هم کشنده بود چون `BOT_TOKEN`
    پیش‌فرض ندارد.
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
        # رازِ خالی: `main()` از قبل جلوی بالا آمدن را می‌گیرد؛ این‌جا فقط برای
        # مسیرهای دیگر (تست/embed) **بسته** برمی‌گردیم نه ۵۰۰.
        return None
    # هر درخواست دوباره عضویت را چک کن: ادمینِ حذف‌شده از ADMIN_IDS نباید تا انقضای
    # کوکی (۸ ساعت) دسترسی داشته باشد.
    return aid if aid in settings.admin_id_set else None


def _need_admin(request: web.Request) -> int:
    """شناسهٔ ادمینِ این درخواست، یا ریدایرکت به ورود."""
    aid = _session_admin(request)
    if not aid:
        raise web.HTTPFound("/login")
    return aid


# ── دارایی‌های استاتیک: نسخه‌دار، فشرده، کشِ بلند ─────────────────
# CSS/JS/آیکون‌ها از حافظه سرو می‌شوند با `?v=<هش>` در URL: نسخهٔ درست یک سال
# `immutable` کش می‌شود و هر تغییرِ فایل هش و در نتیجه URL را عوض می‌کند، پس
# مرورگر هرگز نسخهٔ کهنه را با صفحهٔ تازه قاطی نمی‌کند. gzip یک‌بار سرِ بارگذاری
# ساخته می‌شود (`mtime=0` تا خروجی قطعی باشد)، نه سرِ هر درخواست.
_VERSIONED = ("css/panel.css", "js/panel.js", "icons.svg", "favicon.svg")
_TEXT_TYPES = ("text/", "image/svg+xml", "application/json")


class _Asset:
    __slots__ = ("data", "gz", "ver", "ctype")

    def __init__(self, data: bytes, ctype: str):
        self.data = data
        self.gz = gzip.compress(data, 9, mtime=0)
        self.ver = hashlib.sha256(data).hexdigest()[:10]
        self.ctype = ctype


def _load_assets() -> dict[str, _Asset]:
    out: dict[str, _Asset] = {}
    for rel in _VERSIONED:
        try:
            data = pathlib.Path(_STATIC_DIR, rel).read_bytes()
        except OSError:
            log.warning("panel asset missing: %s", rel)
            continue
        out[rel] = _Asset(data, mimetypes.guess_type(rel)[0] or "application/octet-stream")
    return out


_ASSETS = _load_assets()


def asset_url(rel: str) -> str:
    a = _ASSETS.get(rel)
    return f"/static/{rel}?v={a.ver}" if a else f"/static/{rel}"


_SPRITE = asset_url("icons.svg")
_STATIC_ROOT = pathlib.Path(_STATIC_DIR).resolve()


async def static_file(request: web.Request) -> web.StreamResponse:
    rel = request.match_info["path"]
    a = _ASSETS.get(rel)
    if a is not None:
        fresh = request.query.get("v") == a.ver
        etag = f'"{a.ver}"'
        headers = {"ETag": etag, "Vary": "Accept-Encoding",
                   "Cache-Control": "public, max-age=31536000, immutable" if fresh else "no-cache"}
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers=headers)
        body = a.data
        if "gzip" in request.headers.get("Accept-Encoding", "") and len(a.gz) < len(a.data):
            headers["Content-Encoding"] = "gzip"
            body = a.gz
        charset = "utf-8" if a.ctype.startswith(_TEXT_TYPES) else None
        return web.Response(body=body, content_type=a.ctype, charset=charset, headers=headers)
    # بقیه (فونت، مجوزِ فونت): از دیسک، با گاردِ پیمایشِ ساختاری نه فیلترِ رشته‌ای
    try:
        target = (_STATIC_ROOT / rel).resolve()
    except (OSError, RuntimeError, ValueError):
        raise web.HTTPNotFound()
    if not target.is_relative_to(_STATIC_ROOT) or not target.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(target, headers={"Cache-Control": "public, max-age=604800"})


# ── قالب‌ها و کمک‌رندرها ───────────────────────────────────────────
# قالب‌ها در `app/templates/*.html`. **زیرِ `app/` قیدِ سخت است:** Dockerfileِ پنل
# فقط `COPY app` و `COPY node` دارد، پس قالبی بیرونِ `app/` در ایمیج نیست.
ENV = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def ic(name: str, cls: str = "") -> Markup:
    """آیکونِ اسپرایت (`app/static/icons.svg`، Lucide/ISC)."""
    c = ("ic " + cls).strip()
    return Markup(f'<svg class="{escape(c)}" aria-hidden="true">'
                  f'<use href="{_SPRITE}#i-{escape(name)}"></use></svg>')


def dots(parts) -> Markup:
    """«الف · ب · ج» با هر جزء ایزوله در `<bdi>`.

    بدونِ ایزوله، الگوریتمِ دوجهته «ویدیو · 1080p · ۱۳۷ مگابایت» را در صفحهٔ RTL
    «ویدیو · ۱۳۷ · 1080p مگابایت» می‌چیند: `1080p` و عددِ بعدی یک دنبالهٔ LTR
    می‌سازند و عدد از واحدش جدا می‌شود (در اسکرین‌شات دیده شد). اجزای تهی حذف می‌شوند.
    """
    items = [p for p in parts if p not in (None, "")]
    return Markup(" · ").join(Markup("<bdi>{}</bdi>").format(p) for p in items)


ENV.globals["ic"] = ic
ENV.filters["dots"] = dots
ENV.globals["asset"] = asset_url
ENV.globals["PLAT_COLOR"] = PD.PLAT_COLOR
ENV.globals["KIND_COLOR"] = PD.KIND_COLOR
ENV.globals["PD_norm"] = PD.norm_error

#: رنگِ هر موجودیت در کلِ پنل یکی است: پلتفرم و نوعِ فایل هر کدام ته‌رنگِ خودشان را
#: دارند (همان ترتیبِ `panel_data.PLAT_COLOR`/`KIND_COLOR`)، پس رنگ معنا دارد نه تزئین.
_PLAT_TINT = {"youtube": "t1", "instagram": "t2", "twitter": "t3", "tiktok": "t4",
              "soundcloud": "t5", "spotify": "t6", "other": "t0"}
_KIND_TINT = {"video": "t1", "audio": "t2", "image": "t3", "document": "t4", "pdf": "t5",
              "archive": "t6", "app": "t0"}
#: هر عملیات آیکون و ته‌رنگِ ثابتِ خودش را دارد و رنگ از **خانواده** می‌آید نه از رتبه:
#: اندازه/فرمت نیلی، صدا نارنجی، ویرایش صورتی، بایگانی آبی، امنیت سبز.
_OP_ICON = {
    "compress": ("minimize-2", "t1"), "convert": ("arrow-left-right", "t1"),
    "resize": ("scaling", "t1"), "rotate": ("rotate-cw", "t1"), "enhance": ("sparkles", "t1"),
    "to_gif": ("film", "t1"), "to_pdf": ("file-text", "t1"), "images_to_pdf": ("images", "t1"),
    "extract_audio": ("audio-lines", "t2"), "transcribe": ("captions", "t2"),
    "speed": ("gauge", "t2"), "normalize": ("audio-waveform", "t2"), "mute": ("volume-x", "t2"),
    "meta_write": ("tags", "t2"), "meta_read": ("tag", "t2"),
    "trim": ("scissors", "t5"), "watermark": ("stamp", "t5"), "screenshot": ("camera", "t5"),
    "bg_remove": ("eraser", "t5"), "ocr": ("scan-text", "t5"), "video_concat": ("combine", "t5"),
    "rename": ("pencil", "t5"),
    "zip_many": ("file-archive", "t6"), "list_zip": ("list", "t6"), "extract": ("package-open", "t6"),
    "pdf_merge": ("files", "t6"), "pdf_select": ("scissors", "t6"), "pdf_rotate": ("rotate-cw", "t6"),
    "pdf_split": ("copy", "t6"), "pdf_lock": ("lock", "t3"), "pdf_unlock": ("key-round", "t3"),
    "scan": ("shield-check", "t3"),
}
_JOB_PILL = {"done": ("good", "check", "st.done"), "failed": ("bad", "x", "st.failed"),
             "running": ("info", "refresh-cw", "st.running"),
             "queued": ("neutral", "clock", "st.queued"),
             "cancelled": ("neutral", "ban", "st.cancelled")}
_DL_PILL = {"ok": ("good", "check", "st.done"), "fail": ("bad", "x", "st.failed"),
            "blocked": ("warn", "shield", "dl.blocked"), "refused": ("neutral", "ban", "dl.refused"),
            "cancelled": ("neutral", "ban", "st.cancelled")}
_CK_PILL = {"healthy": ("good", "circle-check"), "unproven": ("warn", "triangle-alert"),
            "suspect": ("warn", "triangle-alert"), "cooldown": ("neutral", "hourglass"),
            "invalid": ("bad", "circle-x"), "frozen": ("bad", "snowflake"),
            "disabled": ("neutral", "pause")}


class Fmt:
    """قالب‌بندیِ داده برای قالب‌ها — پوستهٔ نازک روی `panel_fmt` به زبانِ پنل.

    زمان‌ها از `panel_data` به‌شکلِ epoch می‌آیند (JSON‌پذیر، برای کش)، پس هر متدِ
    زمانی هر دو شکل را می‌پذیرد.
    """

    def __init__(self, lang: str):
        self.lang = lang
        self.fa = F.is_fa(lang)

    def t(self, key: str, **kw) -> str:
        return pt(self.lang, key, **kw)

    def num(self, x, d=None):
        return F.num(x, self.lang, d)

    def pct(self, x, d=0):
        return F.pct(x, self.lang, d)

    def ratio(self, a, b, d=0):
        return F.pct(a / b, self.lang, d) if b else "—"

    def size(self, b, d=None):
        return F.size(b, self.lang, d)

    def mb(self, m):
        return F.mb(m, self.lang)

    def secs(self, s):
        return F.secs(s, self.lang)

    def secs_short(self, s):
        return F.secs_short(s, self.lang)

    def digits(self, x):
        return F.digits(x, self.lang)

    @staticmethod
    def res(h) -> str:
        """کیفیتِ ویدیو مثلِ `1080p` — برچسبِ فنی، پس رقمِ لاتین (تصمیمِ ۲۰۲۶-۱۰)."""
        return f"{int(h)}p" if h else ""

    def clock(self, s):
        """ثانیه به `m:ss` با رقمِ زبان (همان شکلی که شمارندهٔ JS می‌سازد)."""
        m, x = divmod(max(0, int(s or 0)), 60)
        return self.digits(f"{m}:{x:02d}")

    @staticmethod
    def iso(s) -> str:
        """یک رشتهٔ لاتین/عددی داخلِ متنِ ترجمه‌شده، ایزوله با LRI…PDI.

        `t()` متنِ ساده برمی‌گرداند و autoescape هر `<bdi>`ی را که در kwargs برود
        escape می‌کند؛ نویسه‌های ایزوله متن‌اند نه نشانه‌گذاری، پس سالم می‌رسند و
        `/start` در جملهٔ فارسی `start/` نمی‌شود.
        """
        return "\u2066" + str(s) + "\u2069"

    @staticmethod
    def _dt(x):
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return PD.from_ts(x)
        return PD.aware(x)

    def when(self, x):
        return F.when(self._dt(x), self.lang)

    def full(self, x):
        return F.full(self._dt(x), self.lang)

    def ago(self, x):
        return F.ago(self._dt(x), self.lang) if x is not None else "—"

    def hm(self, x):
        return F.hm(self._dt(x), self.lang)

    def day_short(self, x):
        d = self._dt(x)
        return F.day_short(F.local(d), self.lang) if d else "—"

    def day_long(self, x):
        d = self._dt(x)
        return F.day_long(F.local(d), self.lang) if d else "—"

    # برچسب‌ها
    def plat(self, p):
        p = p or "other"
        if f"pl.{p}" in _PANEL_STRINGS:
            return pt(self.lang, f"pl.{p}")
        return (PLATFORM_LABELS if self.fa else PLATFORM_LABELS_EN).get(p) or p

    def ptint(self, p):
        # همان تاخوردگیِ نمودارها: پلتفرمی که رنگِ خودش را ندارد «سایر» است
        return _PLAT_TINT.get(PD.fold_platform(p), "t0")

    def picon(self, p):
        return PD.PLAT_ICON.get(p or "other", "globe")

    def kind(self, k):
        k = PD.fold_kind(k)
        return pt(self.lang, f"k.{k}")

    def ktint(self, k):
        return _KIND_TINT.get(PD.fold_kind(k), "t0")

    def kicon(self, k):
        return PD.KIND_ICON.get(PD.fold_kind(k), "file")

    def op(self, o):
        return pt(self.lang, f"op.{o}") if f"op.{o}" in _PANEL_STRINGS else (o or "—")

    def oicon(self, o):
        return _OP_ICON.get(o or "", ("wand-sparkles", "t0"))[0]

    def otint(self, o):
        return _OP_ICON.get(o or "", ("wand-sparkles", "t0"))[1]

    def err(self, cls):
        if not cls:
            return pt(self.lang, "st.failed")
        return pt(self.lang, f"err.{cls}") if f"err.{cls}" in _PANEL_STRINGS else cls

    def role(self, r):
        return pt(self.lang, f"role.{r}") if f"role.{r}" in _PANEL_STRINGS else (r or "—")

    def lang_name(self, code, names=None):
        if names and code in names:
            return names[code]
        return PANEL_LANGS.get(code) or BUILTIN_NAMES.get(code) or code or "—"

    def job_pill(self, status):
        cls, icon, key = _JOB_PILL.get(status, ("neutral", "circle", "st.queued"))
        return {"cls": cls, "icon": icon, "text": pt(self.lang, key)}

    def dl_pill(self, outcome):
        cls, icon, key = _DL_PILL.get(outcome, ("neutral", "circle", "st.failed"))
        return {"cls": cls, "icon": icon, "text": pt(self.lang, key)}

    def ck_pill(self, status):
        # ناشناخته عمداً «info» است نه «neutral»: «ادمین خاموشش کرد» (خاکستری) و
        # «وضعیتی که نمی‌شناسیم» دو معنای متفاوت‌اند و نباید یک ظاهر داشته باشند.
        cls, icon = _CK_PILL.get(status, ("info", "circle-help"))
        key = f"ck.{status}"
        return {"cls": cls, "icon": icon,
                "text": pt(self.lang, key) if key in _PANEL_STRINGS else status}

    # کاربر
    def uname(self, u):
        if not u:
            return pt(self.lang, "us.noname")
        if u.get("name"):
            return u["name"]
        if u.get("uname"):
            return "@" + u["uname"]
        if u.get("tg"):
            return str(u["tg"])
        return pt(self.lang, "us.noname")

    @staticmethod
    def initials(name: str | None) -> str:
        name = (name or "").strip().lstrip("@")
        if not name:
            return ""
        parts = name.split()
        if "؀" <= parts[0][0] <= "ۿ":
            return parts[0][0]
        return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()

    @staticmethod
    def av(uid) -> str:
        try:
            return f"av{int(uid or 0) % 6 + 1}"
        except (TypeError, ValueError):
            return "av1"


#: منوی پنل — اعلانی؛ هر آیتم ته‌رنگِ خودش را دارد (`.nav a.nN`) تا صفحه‌ها با یک
#: نگاه از هم جدا شوند، و صفحهٔ جاری رنگِ اصلی را می‌گیرد.
NAV = (
    ("grp.main", (("dashboard", "/", "layout-dashboard", "n1"),
                  ("activity", "/activity", "activity", "n3"),
                  ("reports", "/reports", "chart-column", "n6"),
                  ("users", "/users", "users", "n5"))),
    ("grp.infra", (("cookies", "/cookies", "cookie", "n2"),
                   ("nodes", "/nodes", "server", "n4"),
                   ("system", "/system", "heart-pulse", "n3"))),
    ("grp.bot", (("texts", "/texts", "type", "n6"),
                 ("buttons", "/buttons", "keyboard", "n5"),
                 ("langs", "/langs", "languages", "n1"))),
    ("", (("settings", "/settings", "settings", "n0"),)),
)

#: رنگِ هر صفحه به‌شکلِ کلاسِ `tN` (همان `nN`ِ منو) — برای آیکون‌هایی که به آن صفحه می‌برند.
_NAV_TINT = {key: "t" + tint[1:] for _g, items in NAV for key, _h, _i, tint in items}

_LANG_COOKIE = "tab_lang"
_THEME_COOKIE = "tab_theme"

#: ترجیحاتِ رندر (زبانِ پنل، پوسته، مسیرِ جاری) برای همین درخواست — ContextVar، چون
#: هر هندلرِ aiohttp در تسکِ خودش می‌دود و نشتی بینِ دو درخواست ممکن نیست.
_PREFS: contextvars.ContextVar[tuple[str, str, str]] = contextvars.ContextVar(
    "panel_prefs", default=("fa", "light", "/"))


@web.middleware
async def _panel_prefs(request: web.Request, handler):
    token = _PREFS.set((normalize_lang(request.cookies.get(_LANG_COOKIE)),
                        normalize_theme(request.cookies.get(_THEME_COOKIE)),
                        request.path_qs))
    try:
        return await handler(request)
    finally:
        _PREFS.reset(token)


async def prefs(request: web.Request) -> web.Response:
    """سوییچِ زبان/پوستهٔ **پنل** — کوکی؛ بدونِ JS هم کار می‌کند."""
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

    `//evil.example` یک URLِ پروتکل‌نسبی است، و هیچ کاراکترِ کنترلی/فاصله‌ای
    پذیرفته نمی‌شود: پارسرِ URLِ مرورگر tab و خطِ جدید را از **وسطِ** URL حذف
    می‌کند، پس `to=/%09/evil.example` به `//evil.example` تبدیل می‌شد.
    """
    if any(c <= " " or c == "\x7f" for c in value):
        return "/"
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


#: کلیدهایی که `panel.js` لازم دارد — فقط همین‌ها به صفحه می‌روند، نه کلِ جدول.
_JS_KEYS = ("c.copied", "c.copy_manual", "c.total", "c.confirm", "c.unsaved", "c.no_results",
            "st.fix", "st.err.num", "st.err.neg", "st.err.max", "tx.missing", "tx.unknown",
            "tx.empty", "tx.fix", "tx.err.net", "tx.err.session", "tx.leave.title",
            "tx.leave.text", "tx.leave.ok", "srch.hint")


def _strip_params(path_qs: str, *names: str) -> str:
    parts = urlsplit(path_qs)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in names]
    return parts.path + ("?" + urlencode(q) if q else "")


def _flash(request: web.Request | None, lang: str) -> dict | None:
    """بنرِ نتیجهٔ یک ذخیره (`?ok=<کلید>` یا `?err=<متن>`).

    `ok` فقط یک **کلیدِ** شناخته‌شده است و متنش از جدولِ پنل می‌آید؛ هر مقدارِ
    دیگری «ذخیره شد» می‌شود. پس URL نمی‌تواند متنِ دلخواه به‌عنوانِ پیامِ موفقیت
    روی صفحه بگذارد. `err` متن است (خطای اعتبارسنجی) و escape می‌شود.
    """
    if request is None:
        return None
    err = request.query.get("err", "")
    if err:
        return {"ok": False, "text": err[:600]}
    ok = request.query.get("ok", "")
    if ok:
        return {"ok": True, "text": pt(lang, ok) if ok in _PANEL_STRINGS else pt(lang, "c.saved")}
    return None


def _render(name: str, request: web.Request | None = None, **ctx) -> web.Response:
    lang, theme, here = _PREFS.get()
    f = Fmt(lang)
    ctx.setdefault("lang", lang)
    ctx.setdefault("dir", _PANEL_DIR_OF[lang])
    ctx.setdefault("theme", theme)
    ctx.setdefault("t", f.t)
    ctx.setdefault("f", f)
    ctx.setdefault("nav", NAV)
    ctx.setdefault("here", here)
    ctx.setdefault("here_clean", _strip_params(here, "ok", "err"))
    ctx.setdefault("sprite", _SPRITE)
    ctx.setdefault("panel_langs", PANEL_LANGS)
    ctx.setdefault("active", "")
    ctx.setdefault("flash", _flash(request, lang))
    ctx.setdefault("js_i18n", {k: pt(lang, k) for k in _JS_KEYS})
    html = ENV.get_template(name + ".html").render(**ctx)
    return web.Response(text=html, content_type="text/html")


def _is_frag(request: web.Request) -> bool:
    return request.query.get("frag") == "1"


def _result(path: str, *, ok: str = "", err: str = "", **state) -> web.HTTPFound:
    """ریدایرکتِ «نتیجهٔ یک ذخیره» — **تنها** راهِ ساختنِ `ok=`/`err=` در پنل.

    یک تابع، نه چند کپیِ دست‌نویس: قاعده‌ای که در N نقطه دست‌نویس شود در N نقطه
    واگرا می‌شود. گاردِ ASTیِ `test_the_panel_has_one_result_redirect` مانعِ کپیِ
    بعدی است. `state` پارامترهای وضعیتِ صفحه است تا کاربر بعد از ذخیره به همان
    نمایی برگردد که در آن بود.
    """
    params = {k: str(v) for k, v in state.items() if v not in ("", None)}
    if ok:
        params["ok"] = ok
    if err:
        params["err"] = err
    q = urlencode(params)
    return web.HTTPFound(f"{path}?{q}" if q else path)


def _int(v, default: int = 0) -> int:
    try:
        return int(F.ascii_digits(str(v)).strip())
    except (TypeError, ValueError):
        return default


def _choice(v, allowed, default):
    return v if v in allowed else default


# ── سلامتِ pot-provider: هرگز روی مسیرِ درخواست ───────────────────────────
# تنها فراخوانیِ شبکهٔ بیرونیِ پنل بود و درجا داخلِ مسیرِ درخواست زده می‌شد؛ با
# سوکتی که جواب نمی‌دهد داشبورد ۳ ثانیه منتظر می‌ماند. نتیجه کش می‌شود و
# تازه‌سازی به پس‌زمینه می‌رود. دو کلید: `fresh` (TTLدار) و `last` (آخرین نتیجهٔ
# شناخته‌شده)، تا صفحه پس از پریدنِ کش «نامعلوم» نشود.
_POT_FRESH_TTL = 30
_POT_LAST = "potping:last"
_POT_FRESH = "potping:fresh"
_POT_TASK = "pot_refresh_task"
#: «تنظیم شده ولی هنوز نسنجیده» — با `None` («پیکربندی‌نشده») یکی نیست.
POT_UNKNOWN = "?"


async def _pot_probe(url: str) -> bool:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
            async with s.get(url + "/ping") as resp:
                return resp.status == 200
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
    """یک تازه‌سازیِ پس‌زمینه، و نه بیشتر (ارجاعِ تسک روی `app`)."""
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


# ── سلامتِ سرویس‌های دیگر (Bot API، ClamAV): همان الگو، پس‌زمینه ─────────
#: تست‌ها این را خاموش می‌کنند تا هیچ اتصالِ شبکه‌ای از پنل بیرون نرود.
PROBES_ENABLED = True
_SVC_KEY = "panel:svc"
_SVC_FRESH = "panel:svc:fresh"
_SVC_FRESH_TTL = 30
_SVC_TASK = "svc_refresh_task"


async def _probe_botapi() -> dict:
    url = f"{settings.local_api_base.rstrip('/')}/bot{settings.bot_token}/getMe"
    t0 = time.monotonic()
    ok = False
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
            async with s.get(url) as r:
                ok = r.status == 200 and bool((await r.json()).get("ok"))
    except Exception:  # noqa: BLE001
        ok = False
    return {"ok": ok, "ms": round((time.monotonic() - t0) * 1000)}


async def _probe_clamav() -> dict:
    t0 = time.monotonic()
    ver = ""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.clamav_host, settings.clamav_port), 3)
        try:
            writer.write(b"zVERSION\0")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(256), 3)
        finally:
            writer.close()
        ver = data.rstrip(b"\0").decode(errors="replace").strip()
    except Exception:  # noqa: BLE001
        ver = ""
    ok = ver.startswith("ClamAV")
    return {"ok": ok, "ms": round((time.monotonic() - t0) * 1000),
            "ver": ver.split("/")[0].replace("ClamAV", "").strip() if ok else ""}


async def _svc_refresh(app: web.Application) -> None:
    bot, clam = await asyncio.gather(_probe_botapi(), _probe_clamav())
    try:
        r: aioredis.Redis = app["redis"]
        await r.set(_SVC_KEY, json.dumps({"botapi": bot, "clamav": clam, "at": time.time()}))
        await r.set(_SVC_FRESH, "1", ex=_SVC_FRESH_TTL)
    except Exception:  # noqa: BLE001
        pass


def _schedule_svc_refresh(app: web.Application) -> None:
    if not PROBES_ENABLED:
        return
    task = app.get(_SVC_TASK)
    if task is not None and not task.done():
        return
    app[_SVC_TASK] = asyncio.create_task(_svc_refresh(app))


async def _svc_cached(app: web.Application) -> dict:
    try:
        r: aioredis.Redis = app["redis"]
        raw = await r.get(_SVC_KEY)
        fresh = await r.get(_SVC_FRESH)
    except Exception:  # noqa: BLE001
        return {}
    if not fresh:
        _schedule_svc_refresh(app)
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


async def _timed(coro) -> tuple[bool, int]:
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(coro, 3)
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    return ok, round((time.monotonic() - t0) * 1000)


async def _pg_ping() -> None:
    async with Sessionmaker() as s:
        await s.execute(sql_text("SELECT 1"))


async def _services(app: web.Application, tls: list[dict] | None = None) -> list[dict]:
    """ردیف‌های کارتِ «سرویس‌ها»: `ok` = True/False/None (None = نسنجیده/پیکربندی‌نشده)."""
    r: aioredis.Redis = app["redis"]
    pg_ok, pg_ms = await _timed(_pg_ping())
    rd_ok, rd_ms = await _timed(r.ping())
    svc = await _svc_cached(app)
    rows = [{"key": "postgres", "icon": "database", "tint": "t6", "ok": pg_ok, "ms": pg_ms},
            {"key": "redis", "icon": "zap", "tint": "t2", "ok": rd_ok, "ms": rd_ms}]
    for key, icon, tint in (("botapi", "send", "t1"), ("clamav", "shield", "t3")):
        row = svc.get(key) or {}
        rows.append({"key": key, "icon": icon, "tint": tint,
                     "ok": row.get("ok") if row else None, "ms": row.get("ms"),
                     "ver": row.get("ver") or "", "at": svc.get("at")})
    pot = await _pot_health(app)
    if pot is not None:
        rows.append({"key": "pot", "icon": "key-round", "tint": "t4",
                     "ok": None if pot == POT_UNKNOWN else bool(pot)})
    if tls:
        good = sum(1 for x in tls if not _cert_sev(x))
        rows.append({"key": "https", "icon": "lock", "tint": "t5", "ok": good == len(tls),
                     "certs": good})
    # یک شکل برای همهٔ ردیف‌ها: قالب `s.ms`/`s.ver` را می‌خواند، و کلیدِ **غایب** در
    # Jinja `Undefined` است نه `None` — پس `s.ms is not none` صادق می‌شد و
    # `f.num(Undefined)` صفحه را ۵۰۰ می‌کرد (ردیفِ pot وقتی سالم بود؛ اجراشده).
    for row in rows:
        row.setdefault("ms", None)
        row.setdefault("ver", "")
    return rows


# ── HTTPS: سرتیفیکیتِ خودکارِ Caddy ────────────────────────────────────────
#: انبارِ Caddy داخلِ کانتینرِ پنل (compose: `caddy-data:/caddy-data:ro`).
_CADDY_DATA = "/caddy-data"
#: سرویسِ Caddy روی شبکهٔ compose — مقصدِ handshakeِ «همین حالا صادر کن».
_CADDY_HOST = "caddy"
_CADDY_PORT = 443
_TLS_WARM_TASK = "tls_warm_task"
#: سقفِ خواندنِ `link_domain` در `/tls/ask` (Caddy منتظرِ این پاسخ است).
_TLS_ASK_TIMEOUT = 5
#: سقفِ handshakeِ پس‌زمینه. Caddy صدورِ on-demand را خودش در ۱۸۰ ثانیه می‌بُرد.
_TLS_WARM_TIMEOUT = 200


def _cert_info(domain: str) -> dict | None:
    """سرتیفیکیتِ صادرشده برای این دامنه، از خودِ انبارِ Caddy — بی‌شبکه و بی‌اثر بر ACME.

    مسیرش `caddy/certificates/<صادرکننده>/<دامنه>/<دامنه>.crt` است. اگر بیش از یک
    صادرکننده سرتیفیکیت داده، آن‌که دیرتر منقضی می‌شود. `domain` همیشه خروجیِ
    `normalize_domain` است، پس کاراکترِ glob ندارد.
    """
    best: dict | None = None
    pattern = os.path.join(_CADDY_DATA, "caddy", "certificates", "*", domain, f"{domain}.crt")
    for path in glob.glob(pattern):
        try:
            with open(path, "rb") as fh:
                cert = x509.load_pem_x509_certificate(fh.read())
        except (OSError, ValueError):
            continue
        exp = cert.not_valid_after_utc
        if best is None or exp > best["expires"]:
            org = (cert.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
                   or cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME))
            best = {"expires": exp, "issuer": str(org[0].value) if org else "?"}
    return best


#: آستانهٔ گواهی — **یک** قاعده برای رنگِ کارت، اعلان و نوارِ سرویس‌ها. Caddy گواهیِ
#: ۹۰روزه را ~۳۰ روز مانده تمدید می‌کند، پس ۱۴ روز یعنی تمدید واقعاً عقب افتاده.
_CERT_WARN_DAYS = 14
_CERT_BAD_DAYS = 3


def _cert_sev(row: dict) -> str:
    """«» (سالم) · «warn» (صادر نشده یا ≤۱۴ روز) · «bad» (≤۳ روز)."""
    if not row.get("cert"):
        return "warn"
    days = row.get("days", 99)
    return "bad" if days <= _CERT_BAD_DAYS else "warn" if days <= _CERT_WARN_DAYS else ""


async def _tls_status() -> list[dict]:
    """یک ردیف برای هر دامنهٔ پیکربندی‌شده (پنل، لینک) با وضعیتِ سرتیفیکیتش.

    `cert=None` یعنی «هنوز صادر نشده»: یا هیچ‌کس آن دامنه را باز نکرده، یا DNS به
    این سرور اشاره نمی‌کند.
    """
    rows = []
    for role, domain in (("panel", settings_store.panel_domain()),
                         ("link", await settings_store.link_domain())):
        if not domain:
            continue
        info = await asyncio.to_thread(_cert_info, domain)
        row = {"role": role, "domain": domain, "cert": info}
        if info:
            row["days"] = (info["expires"] - datetime.now(timezone.utc)).days
            row["expires"] = info["expires"].strftime("%Y-%m-%d")
            row["expires_ts"] = info["expires"].timestamp()
        row["sev"] = _cert_sev(row)
        rows.append(row)
    return rows


async def _tls_warm(domain: str) -> None:
    """یک handshake با Caddy برای این نام، تا سرتیفیکیت **همین حالا** صادر شود."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(_CADDY_HOST, _CADDY_PORT, ssl=ctx, server_hostname=domain),
            _TLS_WARM_TIMEOUT)
        writer.close()
        log.info("tls: %s answers over HTTPS", domain)
    except Exception as exc:  # noqa: BLE001  — فقط گزارش؛ کارتِ سلامت حقیقت را می‌گوید
        log.warning("tls: no certificate for %s yet (%s) — its A record must point at this "
                    "server and ports 80/443 must be open", domain, exc)


def _schedule_tls_warm(app: web.Application, domain: str) -> None:
    """یک handshakeِ پس‌زمینه در هر لحظه — ارجاع روی `app`، مثلِ تازه‌سازیِ pot."""
    task = app.get(_TLS_WARM_TASK)
    if task is not None and not task.done():
        return
    app[_TLS_WARM_TASK] = asyncio.create_task(_tls_warm(domain))


async def tls_ask(request: web.Request) -> web.Response:
    """گیتِ صدورِ سرتیفیکیتِ Caddy (`on_demand_tls { ask }` در `docker/caddy/Caddyfile`).

    Caddy پیش از گرفتن **یا حتی بارگذاریِ** سرتیفیکیتِ یک نامِ SNI این‌جا را صدا
    می‌زند؛ هر پاسخِ غیرِ2xx یعنی «نه». فقط دو نام: دامنهٔ پنل (env) و دامنهٔ لینک
    (پنل). عمومی است، و دامنهٔ پنل بی‌Redis/Postgres تأیید می‌شود؛ خواندنِ دامنهٔ
    لینک کران‌دار است و روی خطا «نه» می‌گوید.
    """
    name = settings_store.normalize_domain(request.query.get("domain", "")) or ""
    if name:
        allowed = name == settings_store.panel_domain()
        if not allowed:
            try:
                link = await asyncio.wait_for(settings_store.link_domain(), _TLS_ASK_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                log.warning("tls ask: cannot read link_domain (%s) — refusing %s", exc, name)
                link = ""
            allowed = name == link
        if allowed:
            log.info("tls ask: approved %s", name)
            return web.Response(text="ok")
    log.debug("tls ask: refused %r", request.query.get("domain", ""))
    return web.Response(status=403, text="no")


async def _effective() -> dict:
    """مقدارِ مؤثرِ هر کلیدِ زمانِ‌اجرا (override یا پیش‌فرض)، با نوعِ درست."""
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


# ── پوسته: منو، نوارِ وضعیت، اعلان‌ها ───────────────────────────────────
_QUEUES = (("ops", "arq:queue"), ("proc", "arq:queue:proc"), ("dl", "arq:queue:dl"),
           ("dlm", "arq:queue:dl:master"))
_ALERT_RANK = {"bad": 0, "warn": 1, "info": 2}


async def _queue_depths(redis) -> dict[str, int]:
    out = {}
    for key, name in _QUEUES:
        try:
            out[key] = int(await redis.zcard(name) or 0)
        except Exception:  # noqa: BLE001
            out[key] = 0
    return out


def _disk() -> dict | None:
    try:
        du = shutil.disk_usage(settings.work_dir)
    except Exception:  # noqa: BLE001
        return None
    if not du.total:
        return None
    used = du.total - du.free
    return {"total": du.total, "used": used, "free": du.free, "pct": used / du.total}


async def _node_rows(redis) -> list[dict]:
    """نودها: ردیفِ DB + heartbeatِ زنده + آخرین تماس."""
    try:
        async with Sessionmaker() as s:
            rows = (await s.execute(select(Node).order_by(Node.created_at))).scalars().all()
    except Exception:  # noqa: BLE001
        rows = []
    live = await node_mod.list_live(redis)
    seen = await node_mod.last_seen(redis, [n.id for n in rows])
    out = []
    for n in rows:
        hb = live.get(n.id) or {}
        out.append({"id": n.id, "name": n.name, "role": n.role, "wg_ip": n.wg_ip,
                    "online": bool(hb), "load": hb.get("load"), "ver": hb.get("ver") or "",
                    "done": hb.get("done"), "beat": hb.get("at") or seen.get(n.id),
                    "joined": PD.ts(n.created_at)})
    return out


async def _shell(request: web.Request, admin_id: int) -> dict:
    """هرچه پوسته (منو، نوارِ بالا، اعلان‌ها) روی **هر** صفحه لازم دارد.

    همین داده‌ها خوراکِ کارتِ «نیاز به بررسی» داشبورد و صفحهٔ سیستم هم هست، پس
    خامشان هم برمی‌گردد تا هر صفحه دوباره نپرسد.
    """
    lang = _PREFS.get()[0]
    f = Fmt(lang)
    app = request.app
    redis = app["redis"]
    try:
        async with Sessionmaker() as s:
            me = (await s.execute(select(User).where(User.tg_user_id == admin_id))).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        me = None
    admin = {"tg": admin_id, "name": (me.full_name if me else "") or "",
             "uname": (me.username if me else "") or ""}
    admin["initials"] = f.initials(admin["name"] or admin["uname"])
    admin["av"] = f.av(me.id if me else admin_id)

    try:
        lim = await ck_pool.load_limits()
        accounts = await ck_pool.accounts(redis, lim=lim)
    except Exception:  # noqa: BLE001
        lim, accounts = None, []
    nodes = await _node_rows(redis)
    queues = await _queue_depths(redis)
    disk = _disk()
    try:
        stuck = await PD.stuck_jobs()
    except Exception:  # noqa: BLE001
        stuck = {"n": 0, "oldest": None, "queued": 0, "running": 0}
    try:
        tls = await _tls_status()
    except Exception:  # noqa: BLE001
        tls = []
    services = await _services(app, tls)

    alerts: list[dict] = []
    usable: dict[str, int] = {}
    for a in accounts:
        if a.get("status") in ck_pool.USABLE:
            p = a.get("platform") or "other"
            usable[p] = usable.get(p, 0) + 1
    for a in accounts:
        p = a.get("platform") or "other"
        label = a.get("label") or os.path.splitext(a["name"])[0]
        if a.get("status") == ck_pool.FROZEN:
            alerts.append({"sev": "bad", "icon": "snowflake",
                           "title": f.t("al.frozen", id=f.iso(label), p=f.plat(p)),
                           "sub": f.t("ck.attn.frozen") if usable.get(p) else f.t("al.frozen.s", p=f.plat(p)),
                           "href": "/cookies#attn", "at": a.get("last_error_at") or 0})
        elif a.get("status") == ck_pool.INVALID:
            alerts.append({"sev": "bad", "icon": "circle-x",
                           "title": f.t("al.invalid", id=f.iso(label), p=f.plat(p)),
                           "sub": f.t("al.invalid.s", n=f.num(a.get("fail_streak") or 0)),
                           "href": "/cookies#attn", "at": a.get("last_error_at") or 0})
    for n in nodes:
        if not n["online"]:
            alerts.append({"sev": "warn", "icon": "server", "title": f.t("al.node", name=f.iso(n["name"])),
                           "sub": f.t("al.node.s", t=f.ago(n["beat"])) if n["beat"] else f.t("nd.off.note"),
                           "href": "/nodes", "at": n["beat"] or 0})
    if stuck.get("n"):
        alerts.append({"sev": "warn", "icon": "hourglass", "title": f.t("al.stuck", n=f.num(stuck["n"])),
                       "sub": f.t("al.stuck.s", t=f.ago(stuck["oldest"])),
                       "href": "/activity?tab=ops&st=queued", "at": stuck.get("oldest") or 0})
    if disk and disk["pct"] >= 0.9:
        alerts.append({"sev": "bad" if disk["pct"] >= 0.95 else "warn", "icon": "hard-drive",
                       "title": f.t("al.disk", p=f.pct(disk["pct"])),
                       "sub": f.t("al.disk.s", f=f.size(disk["free"])), "href": "/system", "at": time.time()})
    for s in services:
        if s["ok"] is False and s["key"] != "https":
            alerts.append({"sev": "bad", "icon": s["icon"], "title": f.t("al.svc", s=f.t("sy.svc." + s["key"])),
                           "sub": f.t("al.svc.s", t=f.ago(s.get("at"))) if s.get("at") else "",
                           "href": "/system", "at": s.get("at") or time.time()})
    for row in tls:
        if not row.get("cert"):
            alerts.append({"sev": "warn", "icon": "lock", "title": f.t("al.tls.none", d=f.iso(row["domain"])),
                           "sub": f.t("al.tls.none.s"), "href": "/system#certs", "at": 0})
        elif _cert_sev(row):
            alerts.append({"sev": _cert_sev(row), "icon": "lock",
                           "title": f.t("al.tls.exp", d=f.iso(row["domain"]), n=f.num(max(0, row["days"]))),
                           "sub": f.t("al.tls.exp.s"), "href": "/system#certs", "at": 0})
    alerts.sort(key=lambda x: (_ALERT_RANK.get(x["sev"], 3), -(x["at"] or 0)))

    ck_bad = sum(1 for a in accounts if a.get("status") in (ck_pool.FROZEN, ck_pool.INVALID))
    nodes_off = sum(1 for n in nodes if not n["online"])
    return {"admin": admin, "alerts": alerts, "badges": {"cookies": ck_bad, "nodes": nodes_off},
            "queue_total": sum(queues.values()), "queues": queues, "disk": disk,
            "accounts": accounts, "lim": lim, "nodes": nodes, "stuck": stuck, "tls": tls,
            "services": services}


async def _page(request: web.Request, name: str, active: str, **ctx) -> web.Response:
    """رندرِ یک صفحهٔ کامل (با پوسته). `ctx["shell"]` اگر از قبل ساخته شده باشد."""
    admin_id = ctx.pop("admin_id", None) or _need_admin(request)
    shell = ctx.pop("shell", None) or await _shell(request, admin_id)
    return _render(name, request, active=active, shell=shell, **ctx)


# ── لاگِ کارهای ادمین ─────────────────────────────────────────────────────
#: کلیدهایی که مقدارشان هرگز در لاگ نوشته نمی‌شود (فقط «تنظیم شد/خالی شد»).
_SECRET_KEYS = frozenset(f["k"] for f in PS.fields() if f["type"] in PS.SECRET_TYPES)
#: `user:pass@` در URLِ پروکسی — رمزِ پروکسی هم راز است.
_USERINFO = re.compile(r"(?<=//)[^/@\s]+@")


def _audit_value(key: str, value) -> str:
    if key in _SECRET_KEYS:
        return "•••" if value not in ("", None) else ""
    s = "" if value is None else str(value)
    return _USERINFO.sub("•••@", s)[:200]


async def _audit(request: web.Request, action: str, target: str = "",
                 admin_id: int | None = None, **detail) -> None:
    """یک ردیف در `admin_actions`. بهترین‌تلاش: شکستِ لاگ هرگز کارِ ادمین را نمی‌شکند."""
    try:
        aid = admin_id if admin_id is not None else _session_admin(request)
        async with Sessionmaker() as s:
            s.add(AdminAction(admin_id=aid, action=action[:32], target=(target or "")[:200] or None,
                              detail=detail or None, ip=_client_ip(request)[:64]))
            await s.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("admin log write failed (%s): %s", action, exc)


# ── ورود ───────────────────────────────────────────────────────────────────
# سقفِ نرخ (اندازه‌گیری‌شده، §۷): بودجهٔ حدس به **کد** بسته است نه به اندپوینت —
# تمام‌شدنش کد را می‌کشد و کاربر کدِ تازه می‌گیرد؛ ۵ کد × ۳ حدس = ۱۵ حدس در ۶۰۰
# ثانیه. سقفِ per-IP نرخِ مهاجمِ تک‌هدف را کم نمی‌کند ولی حجمِ خامِ verify را
# کران‌دار می‌کند، و برخلافِ سقفِ per-admin بلاک‌شدنِ IPِ مهاجم قفلِ ادمین نیست.
_RL_WINDOW = 600
_RL_REQ_PER_ADMIN = 5
_RL_REQ_PER_IP = 10
_CODE_TTL = 300
_CODE_TRIES = 3
_RL_VERIFY_PER_IP = _RL_REQ_PER_IP * _CODE_TRIES
#: فاصلهٔ «ارسالِ دوباره» در رابط (فقط UX؛ سقفِ واقعی همان per-admin است).
_RESEND_WAIT = 30
#: کوکیِ «کد برای این شناسه فرستاده شد» — مرحلهٔ دوم از آن خوانده می‌شود، نه از
#: URL، تا صفحه برای هر شناسهٔ دلخواه یک پیشگوی «این ادمین هست؟» نشود.
_PENDING = "tab_pending"

#: بلندترین شناسهٔ تلگرامی که می‌پذیریم. `str.isdigit()` طولی را رد نمی‌کند و
#: `int()` روی رشتهٔ بالای ۴۳۰۰ رقم `ValueError` می‌دهد.
_ADMIN_ID_MAXLEN = 20


def _is_internal_peer(addr: str) -> bool:
    """همتای سوکت از **داخلِ** همین ماشین/شبکهٔ داکر است (خصوصی یا loopback)؟"""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback


def _client_ip(request: web.Request) -> str:
    """آدرسِ کلاینت برای سقفِ نرخِ per-IPِ ورود.

    **`X-Forwarded-For` فقط وقتی خوانده می‌شود که همتای سوکت داخلی باشد** — یعنی
    اتصال از Caddy آمده، نه از اینترنت. Caddy (بی `trusted_proxies`) هر XFFِ ورودی
    را دور می‌ریزد و IPِ واقعیِ همتای خودش را می‌گذارد. همتای **عمومی** (پنلِ
    مستقیم روی `:2083`) XFF را نادیده می‌گیرد: آن هدر را خودِ کلاینت ست می‌کند.
    """
    peer = request.remote or "?"
    if _is_internal_peer(peer):
        last = request.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(last))
        except ValueError:
            pass
    return peer


async def _rate_limit(r: aioredis.Redis, key: str, limit: int, window: int) -> bool:
    """یک پنجرهٔ ثابتِ شمارنده‌ای. `True` یعنی این درخواست مجاز است.

    ترمیمِ TTLِ گم‌شده در `counters.incr_window` است — همان پیاده‌سازی که سقفِ نرخِ
    ربات هم از آن رد می‌شود.
    """
    return await counters.incr_window(r, key, window) <= limit


def _https(request: web.Request) -> bool:
    return request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"


async def _send_code(chat_id: int, code: str, lang: str = "fa") -> bool:
    url = f"{settings.local_api_base.rstrip('/')}/bot{settings.bot_token}/sendMessage"
    text = pt(lang, "in.tg_msg", code=f"<code>{code}</code>")
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


def _form_id(value) -> str:
    """شناسه از فرم: رقمِ فارسی/عربی به لاتین، فاصله و جداکننده حذف."""
    return re.sub(r"[\s٬,]", "", F.ascii_digits(str(value or "")))[:64]


def _set_pending(resp: web.StreamResponse, request: web.Request, admin_id: str) -> None:
    tok = _fernet().encrypt(json.dumps({"id": admin_id}).encode()).decode()
    resp.set_cookie(_PENDING, tok, max_age=_CODE_TTL + 300, httponly=True,
                    secure=_https(request), samesite="Lax")


def _pending_admin(request: web.Request) -> str:
    tok = request.cookies.get(_PENDING)
    if not tok:
        return ""
    try:
        data = json.loads(_fernet().decrypt(tok.encode(), ttl=_CODE_TTL + 300))
        aid = str(data["id"])
    except (InvalidToken, ValueError, KeyError, RuntimeError):
        return ""
    return aid if _is_admin_id(aid) else ""


def _login_render(request: web.Request, *, step: int = 1, admin_id: str = "", error: str = "",
                  left: int = 0, wait: int = 0, dead: str = "", toast: str = "") -> web.Response:
    return _render("login", request, flash=None, step=step, admin_id=admin_id, error=error,
                   left=left, wait=wait, dead=dead, toast=toast, code_ttl=_CODE_TTL)


def _login_err(lang: str, key: str) -> str:
    """متنِ خطای ورود. `/start` جداسازی می‌شود، وگرنه در متنِ RTL «start/» دیده می‌شود."""
    return pt(lang, key, s=Fmt.iso("/start"))


_LOGIN_ERRORS = {"rl_ip": "in.rl.ip", "rl_admin": "in.rl.admin", "send_fail": "in.send_fail",
                 "expired": "in.expired", "burned": "in.burned"}


async def login(request: web.Request) -> web.Response:
    if _session_admin(request):
        raise web.HTTPFound("/")
    lang = _PREFS.get()[0]
    r: aioredis.Redis = request.app["redis"]
    e = request.query.get("e", "")
    if request.query.get("change") == "1":
        resp = web.HTTPFound("/login")
        resp.del_cookie(_PENDING)
        raise resp
    aid = _pending_admin(request)
    if not aid:
        err = _login_err(lang, _LOGIN_ERRORS[e]) if e in ("rl_ip", "rl_admin", "send_fail") else ""
        return _login_render(request, error=err)
    try:
        ttl = int(await r.ttl(f"panelcode:{aid}"))
        tries = int(await r.get(f"paneltry:{aid}") or 0)
    except Exception:  # noqa: BLE001
        ttl, tries = -2, 0
    if ttl <= 0:
        return _login_render(request, step=2, admin_id=aid,
                             dead="burned" if e == "burned" else "expired")
    error = ""
    if e == "wrong":
        error = pt(lang, "in.wrong", n=F.num(max(0, _CODE_TRIES - tries), lang))
    elif e in ("rl_ip", "rl_admin"):
        error = _login_err(lang, _LOGIN_ERRORS[e])
    return _login_render(request, step=2, admin_id=aid, error=error, left=ttl,
                         wait=max(0, _RESEND_WAIT - (_CODE_TTL - ttl)),
                         toast=pt(lang, "in.sent") if request.query.get("sent") == "1" else "")


async def auth_request(request: web.Request) -> web.Response:
    lang = _PREFS.get()[0]
    r: aioredis.Redis = request.app["redis"]
    # سقفِ IP **پیش از** اعتبارسنجیِ شناسه، وگرنه کوبیدن با شناسهٔ نامعتبر رایگان است.
    if not await _rate_limit(r, f"panelip:req:{_client_ip(request)}", _RL_REQ_PER_IP, _RL_WINDOW):
        return _login_render(request, error=pt(lang, "in.rl.ip"))
    form = await request.post()
    admin_id = _form_id(form.get("admin_id"))
    if not admin_id.isdigit() or len(admin_id) > _ADMIN_ID_MAXLEN:
        return _login_render(request, admin_id=admin_id[:_ADMIN_ID_MAXLEN],
                             error=pt(lang, "in.bad_id", e="78216453"))
    if not _is_admin_id(admin_id):
        return _login_render(request, admin_id=admin_id, error=pt(lang, "in.not_admin"))
    if not await _rate_limit(r, f"panelreq:{admin_id}", _RL_REQ_PER_ADMIN, _RL_WINDOW):
        return _login_render(request, admin_id=admin_id, error=pt(lang, "in.rl.admin"))
    code = f"{secrets.randbelow(1000000):06d}"
    await r.set(f"panelcode:{admin_id}", code, ex=_CODE_TTL)
    # کدِ تازه بودجهٔ حدسِ تازه می‌آورد — بی‌خطر، چون بودجه به کد بسته است نه به اندپوینت.
    await r.delete(f"paneltry:{admin_id}")
    if not await _send_code(int(admin_id), code, lang):
        await r.delete(f"panelcode:{admin_id}")
        return _login_render(request, admin_id=admin_id, error=_login_err(lang, "in.send_fail"))
    resp = web.HTTPFound("/login?sent=1")
    _set_pending(resp, request, admin_id)
    raise resp


async def auth_verify(request: web.Request) -> web.Response:
    r: aioredis.Redis = request.app["redis"]
    if not await _rate_limit(r, f"panelip:ver:{_client_ip(request)}", _RL_VERIFY_PER_IP, _RL_WINDOW):
        raise web.HTTPFound("/login?e=rl_ip")
    form = await request.post()
    admin_id = _form_id(form.get("admin_id")) or _pending_admin(request)
    code = _form_id(form.get("code"))
    # همان گاردی که `auth_request` دارد. بدونش، هر شناسهٔ عددیِ دلخواه یک کلیدِ
    # `paneltry:` می‌ساخت.
    if not _is_admin_id(admin_id):
        raise web.HTTPFound("/login")
    tk = f"paneltry:{admin_id}"
    tries = await r.incr(tk)
    if tries == 1 or await r.ttl(tk) < 0:
        await r.expire(tk, _CODE_TTL)
    real = await r.get(f"panelcode:{admin_id}")
    if not real:
        await r.delete(tk)
        await _audit(request, "login_fail", target=admin_id, admin_id=int(admin_id), reason="expired")
        raise web.HTTPFound("/login?e=expired")
    # روی **بایت** مقایسه می‌شود، نه رشته: `compare_digest` روی strِ غیرASCII
    # `TypeError` می‌دهد (رقمِ فارسی پیش از این‌جا لاتین شده، ولی گارد می‌ماند).
    ok = secrets.compare_digest(code.encode(), real.encode())
    if not ok:
        if tries >= _CODE_TRIES:
            # **کد** را می‌کشیم، نه اندپوینت را.
            await r.delete(f"panelcode:{admin_id}", tk)
            await _audit(request, "login_fail", target=admin_id, admin_id=int(admin_id), reason="burned")
            raise web.HTTPFound("/login?e=burned")
        await _audit(request, "login_fail", target=admin_id, admin_id=int(admin_id), reason="wrong_code")
        raise web.HTTPFound("/login?e=wrong")
    await r.delete(f"panelcode:{admin_id}", tk)
    await _audit(request, "login", admin_id=int(admin_id))
    resp = web.HTTPFound("/")
    # secure از اسکیمِ واقعی: روی HTTPِ ساده کوکیِ Secure دور انداخته می‌شود → لوپِ ورود.
    resp.set_cookie(_COOKIE, _make_session(int(admin_id)), max_age=_SESSION_TTL,
                    httponly=True, secure=_https(request), samesite="Lax")
    resp.del_cookie(_PENDING)
    raise resp


async def logout(_: web.Request) -> web.Response:
    resp = web.HTTPFound("/login")
    resp.del_cookie(_COOKIE)
    raise resp


# ── کمک‌های مشترکِ صفحه‌ها ────────────────────────────────────────────────
async def _cached(redis, key: str, ttl: int, build):
    """کشِ JSONِ چندثانیه‌ای برای داده‌ی سنگینِ صفحه (بدونِ کش اگر Redis نیست)."""
    try:
        raw = await redis.get(key)
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    data = await build()
    try:
        await redis.set(key, json.dumps(data, default=str), ex=ttl)
    except Exception:  # noqa: BLE001
        pass
    return data


def _delta(f: Fmt, cur, prev, *, pp: bool = False, inverse: bool = False, ok: bool = True) -> dict:
    """تغییر نسبت به دورهٔ قبل. `ok=False` یعنی دورهٔ قبل کامل ثبت نشده → «—»."""
    if not ok or prev is None or cur is None or (not pp and not prev):
        return {"cls": "na", "icon": "", "text": "—", "title": f.t("r.na")}
    if pp:
        d = (cur - prev) * 100
        text = f.num(abs(d), 1) + " " + f.t("u.pp")
        title = f.t("c.pp", n=f.num(abs(d), 1))
    else:
        d = (cur - prev) / prev * 100
        text = f.pct(abs(d) / 100, 1)
        title = ""
    if abs(d) < 0.05:
        return {"cls": "flat", "icon": "", "text": text, "title": title}
    good = d < 0 if inverse else d > 0
    return {"cls": "up" if good else "down", "icon": "arrow-up" if d > 0 else "arrow-down",
            "text": text, "title": title}


def _rate_cls(v) -> str:
    if v is None:
        return ""
    return "good" if v >= 0.9 else "warn" if v >= 0.75 else "bad"


def _qs(base: dict, **over) -> str:
    """کوئری‌استرینگ از وضعیتِ صفحه + تغییرات؛ مقدارِ تهی و «صفحهٔ ۱» حذف می‌شوند."""
    q = {}
    for k, v in {**base, **over}.items():
        if v in ("", None) or (k == "page" and str(v) in ("0", "1")):
            continue
        q[k] = v
    return urlencode(q)


def _pager(f: Fmt, data: dict, path: str, state: dict) -> dict:
    page, pages, per, total = data["page"], data["pages"], data["per"], data["total"]
    a = (page - 1) * per + 1 if total else 0
    b = min(total, page * per)
    return {"text": f.t("c.range", a=f.num(a), b=f.num(b), n=f.num(total)),
            "prev": f"{path}?{_qs(state, page=page - 1)}" if page > 1 else "",
            "next": f"{path}?{_qs(state, page=page + 1)}" if page < pages else ""}


def _feed_row(f: Fmt, x: dict) -> dict:
    """یک ردیفِ «آخرین فعالیت‌ها» (دانلود یا عملیات) برای داشبورد و برگهٔ کاربر."""
    if x["type"] == "dl":
        ok = x["outcome"] == "ok"
        if ok:
            sub = [f.kind(x["kind"]) if x["kind"] else "",
                   f.res(x.get("height")),
                   f.size(x["size"]) if x.get("size") else "",
                   f.t("c.cached") if x["cached"] else (f.secs(x["took"]) if x.get("took") else "")]
        else:
            sub = [f.err(x["error_class"]) if x["outcome"] == "fail" else f.dl_pill(x["outcome"])["text"]]
        return {"tint": f.ptint(x["platform"]), "icon": f.picon(x["platform"]),
                "title": f.uname(x["user"]), "what": f.t("d.dl_from", p=f.plat(x["platform"])),
                "sub": [s for s in sub if s], "pill": f.dl_pill(x["outcome"]), "t": x["t"],
                "href": f"/activity?tab=dl&dl={x['id']}"}
    if x["status"] == "failed":
        sub = [PD.norm_error(x["error"]) or f.t("st.failed")]
    else:
        sub = [x["file"], f.size(x["size"]) if x.get("size") else "",
               f.secs(x["took"]) if x.get("took") and x["status"] == "done" else ""]
    return {"tint": f.otint(x["op"]), "icon": f.oicon(x["op"]), "title": f.uname(x["user"]),
            "what": f.op(x["op"]), "sub": [s for s in sub if s], "pill": f.job_pill(x["status"]),
            "t": x["t"], "href": f"/activity?tab=ops&job={x['id']}"}


_POOL_PLATS = ["instagram", "youtube", "twitter", "tiktok"]
_POOL_SEGS = (("ok", "var(--good)"), ("warn", "var(--warn)"), ("rest", "var(--neutral)"),
              ("bad", "var(--bad)"), ("off", "var(--border-strong)"))


# ── داشبورد ───────────────────────────────────────────────────────────────
_DASH_TTL = 15


async def dashboard(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    lang = _PREFS.get()[0]
    f = Fmt(lang)
    key = _choice(request.query.get("r"), PD.DASH_RANGES, "7d")
    shell = await _shell(request, admin_id)
    d = await _cached(request.app["redis"], f"panel:dash:{key}", _DASH_TTL, lambda: PD.dashboard(key))
    R = PD.make_range(key, PD.from_ts(d["end"]))
    first = PD.from_ts(d.get("first"))
    cmp_ok = R.prev_start is not None and first is not None and first <= R.prev_start
    ev_cur, ev_prev, ev_since = PD.ev_coverage(d, R)

    files_c = d["files"]["dl"][0] + d["files"]["up"][0]
    files_p = d["files"]["dl"][1] + d["files"]["up"][1]
    ok_c, fail_c = d["ev"]["ok"][0], d["ev"]["fail"][0]
    ok_p, fail_p = d["ev"]["ok"][1], d["ev"]["fail"][1]
    att_c, att_p = ok_c + fail_c, ok_p + fail_p
    rate_c = ok_c / att_c if att_c else None
    rate_p = ok_p / att_p if att_p else None
    if ev_since:
        succ_sub = f.t("d.k.success.since", d=f.day_short(PD.ts(ev_since)))
    elif att_c:
        succ_sub = f.t("d.k.success.s", f=f.num(fail_c), n=f.num(att_c))
    else:
        succ_sub = f.t("d.k.success.none")
    kpis = [
        {"icon": "users", "tint": "t1", "label": f.t("d.k.active"), "value": f.num(d["active"][0]),
         "sub": f.t("d.k.active.s", n=f.num(d["users"])),
         "delta": _delta(f, d["active"][0], d["active"][1], ok=cmp_ok)},
        {"icon": "user-plus", "tint": "t5", "label": f.t("d.k.new"), "value": f.num(d["new"][0]),
         "sub": (f.t("d.k.new.s24", n=f.num(d["users"])) if key == "24h"
                 else f.t("d.k.new.s", n=f.num(d["new"][0] / max(1.0, R.days), 1))),
         "delta": _delta(f, d["new"][0], d["new"][1], ok=cmp_ok)},
        {"icon": "download", "tint": "t6", "label": f.t("d.k.files"), "value": f.num(files_c),
         "sub": f.t("d.k.files.s", dl=f.num(d["files"]["dl"][0]), up=f.num(d["files"]["up"][0])),
         "delta": _delta(f, files_c, files_p, ok=cmp_ok)},
        {"icon": "circle-check", "tint": "t3", "label": f.t("d.k.success"),
         "value": f.pct(rate_c) if rate_c is not None else "—", "sub": succ_sub,
         "delta": _delta(f, rate_c, rate_p, pp=True, ok=cmp_ok and ev_cur and ev_prev)},
    ]

    unit_title = {"hour": "d.act.hour", "day": "d.act.day", "week": "d.act.week"}[R.unit]
    act_dl = [a[0] for a in d["act"]]
    act_up = [a[1] for a in d["act"]]
    act_spec = PD.column_spec(R, [
        {"label": f.t("d.s.dl"), "color": "var(--c1)", "values": act_dl},
        {"label": f.t("d.s.up"), "color": "var(--c2)", "values": act_up}],
        lang, aria=f.t(unit_title), tall=True)
    act_rows = [{"label": PD.bucket_label(R, i, lang, long=True), "dl": act_dl[i], "up": act_up[i],
                 "partial": i == len(R) - 1} for i in reversed(range(len(R)))]

    plat_rows = [{**p, "att": p["ok"] + p["fail"]} for p in d["plat"]]
    plat_total = sum(p["att"] for p in plat_rows)
    donut = {"type": "donut", "aria": f.t("d.plat"), "center": f.num(plat_total),
             "center_label": f.t("d.req"),
             "items": [{"label": f.plat(p["p"]), "color": PD.PLAT_COLOR.get(p["p"], "var(--c0)"),
                        "value": p["att"],
                        "rows": [[f.t("d.req"), f.num(p["att"])],
                                 [f.t("c.share"), f.ratio(p["att"], plat_total)],
                                 [f.t("c.success"), f.ratio(p["ok"], p["att"])]]}
                       for p in plat_rows]}

    ops = d["ops"][:6]
    ops_max = max([o["n"] for o in ops] or [1])
    try:
        recent = [_feed_row(f, x) for x in await PD.recent_activity(6)]
    except Exception:  # noqa: BLE001
        recent = []
    pool = []
    for r in PD.pool_rows(shell["accounts"], _POOL_PLATS):
        r["segs"] = [(r[k], col) for k, col in _POOL_SEGS if r[k]]
        pool.append(r)
    services = shell["services"]
    period = (f.t("d.period.24h") if key == "24h"
              else f.t("d.period.days", a=f.day_short(PD.ts(R.start)), t=f.hm(d["end"])))
    return _render("dashboard", request, active="dashboard", shell=shell, key=key,
                   ranges=PD.DASH_RANGES, period=period,
                   cmp=f.t("r.cmp." + key) if cmp_ok else f.t("r.na"),
                   kpis=kpis, unit_title=unit_title, act_spec=act_spec, act_rows=act_rows,
                   act_tot=(sum(act_dl), sum(act_up)), plat_rows=plat_rows, plat_total=plat_total,
                   donut=donut, ops=ops, ops_max=ops_max, jobs=d["jobs"], recent=recent,
                   pool=pool, services=services,
                   svc_ok=sum(1 for s in services if s["ok"]),
                   rate_cls=_rate_cls)


# ── فعالیت‌ها ────────────────────────────────────────────────────────────
_ACT_TABS = ("dl", "ops", "log")
_PERS = (1, 7, 14)
_DL_STATUSES = ("done", "failed", "blocked", "refused", "cancelled")
_LOG_ICON = {"login": ("log-in", "t3"), "login_fail": ("lock", "tbad"),
             "setting": ("sliders-horizontal", "t0"), "cookie_add": ("cookie", "t2"),
             "cookie_replace": ("cookie", "t2"), "cookie_unfreeze": ("snowflake", "t6"),
             "cookie_delete": ("trash-2", "tbad"), "cookie_identity": ("fingerprint", "t2"),
             "cookie_toggle": ("power", "t2"), "cookie_cooldown": ("hourglass", "t2"),
             "cookie_resync": ("refresh-cw", "t2"), "text_save": ("type", "t6"),
             "text_reset": ("rotate-ccw", "t6"), "user_block": ("user-x", "tbad"),
             "user_unblock": ("user-check", "t3"), "buttons_save": ("keyboard", "t5"),
             "buttons_reset": ("rotate-ccw", "t5"), "lang_import": ("languages", "t1"),
             "lang_delete": ("trash-2", "tbad"), "node_add": ("server", "t4"),
             "node_remove": ("server", "tbad")}


def _setting_label(f: Fmt, key: str) -> str:
    fld = PS.field(key)
    if fld and fld["l"][0]:
        return fld["l"][0 if f.fa else 1]
    if fld and fld.get("plat"):
        return f.t("st.ux", p=f.plat(fld["plat"]))
    return key


def _setting_shown(f: Fmt, key: str, raw) -> str:
    if raw in ("on", True):
        return f.t("c.on")
    if raw in ("off", False):
        return f.t("c.off")
    if raw in ("", None):
        return "—"
    s = str(raw)
    if s == "•••":
        return s
    if s.isdigit():
        return f.num(int(s))
    return s


def _log_parts(f: Fmt, row: dict, langs: dict) -> list:
    a, tg, dt = row["action"], row["target"], row["detail"] or {}
    if a == "setting":
        return [_setting_label(f, tg), {"from": _setting_shown(f, tg, dt.get("from")),
                                         "to": _setting_shown(f, tg, dt.get("to"))}]
    if a == "cookie_add":
        return [tg, f.plat(dt.get("platform"))]
    if a == "cookie_cooldown":
        rest = {"set": "ck.m.rest", "clear": "ck.m.rest_end"}.get(dt.get("mode"))
        return [tg] + ([f.t(rest)] if rest else [])
    if a.startswith("cookie_"):
        extra = dt.get("state")
        return [tg] + ([f.t("c.on") if extra == "on" else f.t("c.off")] if extra in ("on", "off") else [])
    if a in ("text_save", "text_reset"):
        out = [tg] if tg else []
        if dt.get("n") and dt["n"] > 1:
            out = [f.t("lg.texts_n", n=f.num(dt["n"]))]
        return out + [f.lang_name(dt.get("lang"), langs)]
    if a in ("user_block", "user_unblock"):
        return [x for x in (dt.get("name"), tg) if x]
    if a in ("buttons_save", "buttons_reset"):
        return [f.kind(tg), f.lang_name(dt.get("lang"), langs)] if dt.get("lang") else [f.kind(tg)]
    if a == "lang_import":
        return [dt.get("name") or tg, tg] + ([f.t("lg.texts_n", n=f.num(dt["n"]))] if dt.get("n") else [])
    if a == "lang_delete":
        return [tg]
    if a in ("node_add", "node_remove"):
        return [x for x in (tg, f.role(dt.get("role"))) if x]
    if a == "login_fail":
        return [f.t("lg." + dt.get("reason", "wrong_code"))]
    return []


def _log_row(f: Fmt, row: dict, langs: dict) -> dict:
    icon, tint = _LOG_ICON.get(row["action"], ("history", "t0"))
    key = "lg." + row["action"]
    return {"t": row["t"], "icon": icon, "tint": tint,
            "label": f.t(key) if key in _PANEL_STRINGS else row["action"],
            "parts": _log_parts(f, row, langs), "ip": row["ip"], "admin": row["admin"]}


def _sheet_close(request: web.Request) -> str:
    return _strip_params(request.path_qs, "dl", "job", "open", "frag", "ok", "err")


async def _exit_label(f: Fmt, exit_id: str) -> str:
    """نامِ خروجیِ شبکهٔ یک دانلود: «مستر»، یا نامِ نود به‌جای شناسه‌اش."""
    if exit_id in ("", "master"):
        return f.t("ck.exit.master") if exit_id else ""
    try:
        async with Sessionmaker() as db:
            n = await db.get(Node, exit_id)
    except Exception:  # noqa: BLE001
        return exit_id
    return (n.name if n and n.name else "") or exit_id


async def activity(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    lang = _PREFS.get()[0]
    f = Fmt(lang)
    q = request.query
    tab = _choice(q.get("tab"), _ACT_TABS, "dl")
    per = _choice(_int(q.get("per"), 7), _PERS, 7)
    st = q.get("st", "")
    plat = (q.get("p") or "")[:24]
    op = (q.get("op") or "")[:32]
    text = (q.get("q") or "").strip()[:80]
    page = q.get("page", "1")

    sheet = sheet_kind = None
    dl_id, job_id = _int(q.get("dl")), _int(q.get("job"))
    if dl_id:
        sheet, sheet_kind = await PD.dl_event(dl_id), "dl"
        if sheet:
            sheet["exit_label"] = await _exit_label(f, sheet.get("exit") or "")
    elif job_id:
        sheet, sheet_kind = await PD.job_detail(job_id), "job"
    if _is_frag(request):
        if not sheet:
            raise web.HTTPNotFound()
        return _render("_sheet_" + sheet_kind, request, e=sheet, close_href=_sheet_close(request))

    state = {"tab": tab, "per": per if tab != "log" else "", "q": text}
    if tab == "dl":
        st = _choice(st, _DL_STATUSES, "")
        state.update(st=st, p=plat)
        data = await PD.downloads_list(per, st, plat, text, page)
        by = data["by"]
        summary = f.t("ac.sum.dl", n=f.num(data["total"]), ok=f.num(by.get("ok", 0)),
                      f=f.num(by.get("fail", 0)), c=f.num(data["cached"]))
        rows = data["rows"]
    elif tab == "ops":
        st = _choice(st, PD.JOB_STATUS, "")
        state.update(st=st, op=op)
        data = await PD.jobs_list(per, st, op, text, page)
        by = data["by"]
        summary = f.t("ac.sum.ops", n=f.num(data["total"]), f=f.num(by.get("failed", 0)),
                      r=f.num(by.get("running", 0)), q=f.num(by.get("queued", 0)))
        rows = data["rows"]
    else:
        data = await PD.admin_log(text, page)
        langs = await _languages()
        rows = [_log_row(f, x, langs) for x in data["rows"]]
        summary = ""
    state["page"] = data["page"] if data["page"] > 1 else ""
    counts = await PD.activity_counts(per)
    now = time.time()
    return await _page(request, "activity", "activity", admin_id=admin_id,
                       tab=tab, per=per, pers=_PERS, st=st, plat=plat, op=op, q=text,
                       data=data, rows=rows, summary=summary, counts=counts, state=state,
                       qs=lambda **kw: _qs(state, **kw), pager=_pager(f, data, "/activity", state),
                       dl_statuses=_DL_STATUSES, job_statuses=PD.JOB_STATUS,
                       stuck_after=PD.STUCK_QUEUED.total_seconds(), now=now,
                       sheet=sheet, sheet_kind=sheet_kind, close_href=_sheet_close(request),
                       multi_admin=len(settings.admin_id_set) > 1)


# ── کاربران ───────────────────────────────────────────────────────────────
#: کشِ صفحهٔ کاربران: دو `count(*)` روی‌هم ~۹۶٪ کارِ صفحه‌اند (اندازه‌گیری‌شده روی
#: Postgresِ ۲۰۰هزار ردیفی). باطل‌سازی با شمارندهٔ نسخه است و **شرطِ درستی** است:
#: بدونِ آن ادمین «بلاک» را می‌زند و همان کاربر را هنوز آزاد می‌بیند.
_USERS_TTL = 30
_USERS_VER = "userscache:ver"


async def _users_cache_ver(redis) -> str:
    try:
        return str(await redis.get(_USERS_VER) or "0")
    except Exception:  # noqa: BLE001
        return "0"


async def _users_cache_bust(redis) -> None:
    try:
        await redis.incr(_USERS_VER)
    except Exception:  # noqa: BLE001
        pass


async def _users_cached(app, q: str, status: str, lang: str, sort: str, page) -> dict:
    redis = app.get("redis")
    if redis is None:
        return await PD.users_list(q, status, lang, sort, page)
    key = f"userscache:{await _users_cache_ver(redis)}:{status}:{lang}:{sort}:{page}:{q}"
    return await _cached(redis, key, _USERS_TTL,
                         lambda: PD.users_list(q, status, lang, sort, page))


async def _user_sheet(request: web.Request, user_id: int) -> dict | None:
    u = await PD.user_detail(user_id)
    if not u:
        return None
    lang = _PREFS.get()[0]
    f = Fmt(lang)
    since = datetime.now(timezone.utc) - timedelta(days=14)
    try:
        recent = [_feed_row(f, x) for x in await PD.recent_activity(6, owner_id=user_id, since=since)]
    except Exception:  # noqa: BLE001
        recent = []
    redis = request.app["redis"]
    day = PD.utc_today()
    try:
        dl_today = int(await redis.get(f"dlq:cnt:{u['tg']}:{day}") or 0)
    except Exception:  # noqa: BLE001
        dl_today = 0
    eff = await _effective()
    u.update(recent=recent, dl_today=dl_today, dl_cap=int(eff.get("dl_daily_count") or 0),
             op_cap=int(eff.get("daily_op_quota") or 0),
             is_admin=u["tg"] in settings.admin_id_set)
    return u


async def users_page(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    lang = _PREFS.get()[0]
    f = Fmt(lang)
    q = request.query
    text = (q.get("q") or "").strip()[:80]
    status = _choice(q.get("st"), ("active", "blocked"), "")
    ulang = (q.get("lang") or "")[:16]
    sort = _choice(q.get("sort"), PD.USER_SORTS, "seen")
    page = q.get("page", "1")
    open_id = _int(q.get("open"))
    sheet = await _user_sheet(request, open_id) if open_id else None
    langs = await _languages()
    # مسدود/رفعِ مسدودی از داخلِ برگه به همان برگه برمی‌گردد تا وضعیتِ تازه دیده شود.
    sheet_back = _strip_params(request.path_qs, "frag", "ok", "err")
    if _is_frag(request):
        if not sheet:
            raise web.HTTPNotFound()
        return _render("_sheet_user", request, u=sheet, close_href=_sheet_close(request),
                       back=sheet_back, langs=langs)
    data = await _users_cached(request.app, text, status, ulang, sort, page)
    state = {"q": text, "st": status, "lang": ulang, "sort": sort if sort != "seen" else "",
             "page": data["page"] if data["page"] > 1 else ""}
    return await _page(request, "users", "users", admin_id=admin_id, data=data, q=text,
                       st=status, ulang=ulang, sort=sort, sorts=PD.USER_SORTS, state=state,
                       qs=lambda **kw: _qs(state, **kw), pager=_pager(f, data, "/users", state),
                       langs=langs, sheet=sheet, close_href=_sheet_close(request),
                       back=_strip_params(request.path_qs, "open", "ok", "err"),
                       sheet_back=sheet_back, admins=settings.admin_id_set)


async def users_block(request: web.Request) -> web.Response:
    _need_admin(request)
    form = await request.post()
    uid = _int(form.get("id"))
    action = (form.get("action") or "").strip()
    back = _safe_back(str(form.get("back") or "/users"))
    if not back.startswith("/users"):
        back = "/users"
    outcome = ""
    if uid and action in ("block", "unblock"):
        async with Sessionmaker() as db:
            u = await db.get(User, uid)
            if u and u.tg_user_id not in settings.admin_id_set:  # ادمین را نمی‌شود بلاک کرد
                u.is_blocked = (action == "block")
                await db.commit()
                outcome = action
                name, tg = u.full_name or u.username or "", u.tg_user_id
        if outcome:
            # پیش از ریدایرکت، وگرنه صفحهٔ بعدی نمای کهنه را نشان می‌دهد.
            await _users_cache_bust(request.app.get("redis"))
            await _audit(request, "user_" + outcome, target=str(tg), name=name)
    _path, _, query = back.partition("?")
    state = {k: v for k, v in parse_qsl(query) if k in ("q", "st", "lang", "sort", "page", "open")}
    ok = {"block": "us.blocked.ok", "unblock": "us.unblocked.ok"}.get(outcome, "")
    raise _result("/users", ok=ok, **state)


# ── گزارش‌ها ──────────────────────────────────────────────────────────────
_REPORTS_TTL = 60
_LANG_COLORS = ("var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)")


async def reports(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    lang = _PREFS.get()[0]
    f = Fmt(lang)
    key = _choice(request.query.get("r"), PD.REPORT_RANGES, "30d")
    d = await _cached(request.app["redis"], f"panel:rep:{key}", _REPORTS_TTL, lambda: PD.reports(key))
    R = PD.make_range(key, PD.from_ts(d["end"]), PD.from_ts(d.get("first")))
    first = PD.from_ts(d.get("first")) if key == "all" else await _first_user(request)
    cmp_ok = R.prev_start is not None and first is not None and first <= R.prev_start
    files_c = d["files"]["dl"][0] + d["files"]["up"][0]
    files_p = d["files"]["dl"][1] + d["files"]["up"][1]
    kpis = [
        {"icon": "users", "tint": "t1", "label": f.t("rp.k.users"), "value": f.num(d["users"]),
         "sub": f.t("rp.k.users.s", n=f.num(d["new"][0])), "delta": None},
        {"icon": "file", "tint": "t6", "label": f.t("rp.k.files"), "value": f.num(files_c),
         "sub": f.t("rp.k.files.s", dl=f.num(d["files"]["dl"][0]), up=f.num(d["files"]["up"][0])),
         "delta": _delta(f, files_c, files_p, ok=cmp_ok)},
        {"icon": "wand-sparkles", "tint": "t5", "label": f.t("rp.k.ops"), "value": f.num(d["jobs"][0]),
         "sub": f.t("rp.k.ops.s", f=f.num(d["jobs_fail"][0])),
         "delta": _delta(f, d["jobs"][0], d["jobs"][1], ok=cmp_ok)},
        {"icon": "hard-drive", "tint": "t4", "label": f.t("rp.k.bytes"), "value": f.size(d["bytes"][0]),
         "sub": f.t("rp.k.bytes.s", h=f.num(d["cache"][0]), s=f.size(d["cache_bytes"])),
         "delta": _delta(f, d["bytes"][0], d["bytes"][1], ok=cmp_ok)},
    ]
    new_spec = PD.column_spec(R, [{"label": f.t("rp.new"), "color": "var(--c5)", "values": d["new_b"]}],
                              lang, aria=f.t("rp.new"), height=200)
    act_label = f.t("rp.active.w") if R.unit == "week" else f.t("rp.active")
    act_spec = PD.column_spec(R, [{"label": act_label, "color": "var(--c1)", "values": d["act_b"],
                                   "fmt_fn": lambda v: F.num(v, lang, 0 if R.unit == "day" else 1)}],
                              lang, aria=f.t("rp.active"), height=200)
    plats = []
    for p in d["plat"]:
        spec = PD.column_spec(R, [{"label": f.plat(p["p"]), "color": PD.PLAT_COLOR.get(p["p"], "var(--c0)"),
                                   "values": p["b"]}], lang, aria=f.plat(p["p"]), height=40, mini=True,
                              notes=False)
        rate = p["ok"] / p["att"] if p["att"] else None
        plats.append({**p, "spec": spec, "rate": rate, "rcls": _rate_cls(rate)})
    kinds_total = sum(k["n"] for k in d["kinds"])
    kinds_donut = {"type": "donut", "aria": f.t("rp.kinds"), "center": f.num(kinds_total),
                   "center_label": f.t("rp.kinds.c"),
                   "items": [{"label": f.kind(k["k"]), "color": PD.KIND_COLOR.get(k["k"], "var(--c0)"),
                              "value": k["n"], "rows": [[f.t("rp.kinds.c"), f.num(k["n"])],
                                                        [f.t("c.share"), f.ratio(k["n"], kinds_total)]]}
                             for k in d["kinds"]]}
    q_total = sum(x["n"] for x in d["quality"])
    q_max = max([x["n"] for x in d["quality"]] or [1])
    langs = await _languages()
    lang_total = sum(x["n"] for x in d["langs"])
    lang_rows = [{**x, "color": _LANG_COLORS[i % len(_LANG_COLORS)],
                  "name": f.lang_name(x["code"], langs) if x["code"] else f.t("rp.lang.none")}
                 for i, x in enumerate(d["langs"])]
    users = await PD.users_by_ids([x["id"] for x in d["top"]])
    top = [{**x, "user": users.get(x["id"]) or {"id": x["id"], "name": "", "uname": "", "tg": None}}
           for x in d["top"]]
    span_days = max(1.0, R.days)
    # نرخِ موفقیت از لاگِ دانلود می‌آید که از روزِ استقرار پر می‌شود؛ پیش از آن «ثبت نشده».
    ev_cur, _ev_prev, ev_since = PD.ev_coverage(d, R)
    succ_note = ("" if ev_cur else f.t("d.k.success.since", d=f.day_short(PD.ts(ev_since)))
                 if ev_since else f.t("d.k.success.none"))
    return await _page(request, "reports", "reports", admin_id=admin_id, key=key,
                       ranges=PD.REPORT_RANGES, d=d, kpis=kpis, new_spec=new_spec, act_spec=act_spec,
                       plats=plats, kinds_donut=kinds_donut, kinds_total=kinds_total,
                       q_total=q_total, q_max=q_max, lang_rows=lang_rows, lang_total=lang_total,
                       top=top, span_days=span_days, start=PD.ts(R.start), succ_note=succ_note,
                       cmp="" if key == "all" else (f.t("r.cmp." + key) if cmp_ok else f.t("r.na")))


async def _first_user(request: web.Request) -> datetime | None:
    async def build():
        first = await PD.first_activity()
        return {"t": PD.ts(first)}
    d = await _cached(request.app["redis"], "panel:first", 600, build)
    return PD.from_ts(d.get("t"))


# ── کوکی‌ها ───────────────────────────────────────────────────────────────
# آینهٔ کوکی در Redis (تا نودِ دانلود که دیسکِ کوکیِ مستر را ندارد هم ببیندشان).
# کلیدها باید با `tasks_download._CK_SET`/`_CK_CONTENT` هماهنگ بمانند.
_CK_SET = "ckfiles"
_CK_CONTENT = "ckfile:"

# این توابع در `app/cookies.py` زندگی می‌کنند (رباتْ هم برای پیستِ داخلِ تلگرام
# لازمشان دارد و نباید به فرآیندِ پنل وابسته باشد).
_REQUIRED_COOKIE = ck_pool._REQUIRED_COOKIE
_normalize_cookie_text = ck_pool._normalize_cookie_text
_check_required = ck_pool._check_required
_save_cookie = ck_pool._save_cookie
_mirror_cookie = ck_pool._mirror_cookie
_unmirror_cookie = ck_pool._unmirror_cookie
_CK_CARD_PLATS = ("instagram", "youtube", "twitter", "tiktok")


def _cookies_dir_ok() -> bool:
    d = settings.cookies_dir
    return bool(d) and os.path.isdir(d) and os.access(d, os.W_OK)


def _safe_cookie_name(name: str) -> str | None:
    """basenameِ امنِ `.txt` (بدونِ traversal) — پیاده‌سازی در `cookies.safe_name`."""
    return ck_pool.safe_name(name)


async def _known_cookie(redis, raw: str) -> str | None:
    """نامِ امنِ اکانتی که صفحه **واقعاً نشانش می‌دهد** — وگرنه `None`.

    هر کارِ روی یک اکانت (جایگزینی، حذف، آزادسازی، هویت، روشن/خاموش، استراحت) از
    این‌جا رد می‌شود. بی این گارد، `get_meta` برای نامِ ناموجود یک متای تازه
    می‌ساخت و `set_meta` آن را می‌نوشت: یک فرمِ کهنه (اکانتی که در تبِ دیگر حذف
    شده) یا یک POSTِ دست‌ساز یک «متای شبح» در Redis می‌گذاشت، و چون `set_meta`
    ردِ ماندگارِ `ckseen:<پلتفرم>` را هم می‌نویسد، سطلی که هرگز پر نشده «زمانی
    پر بوده» خوانده می‌شد و هشدارِ کاذبِ «کوکی نمانده» می‌گرفت. جایگزینی بدترش
    را داشت: برای نامِ ناموجود فایلِ **تازه** می‌ساخت، یعنی اکانتِ حذف‌شده از راهِ
    «جایگزینی» بی‌صدا برمی‌گشت.

    «شناخته‌شده» یعنی همان فهرستی که صفحه از آن ساخته می‌شود (`list_names`: دیسک،
    یا آینهٔ Redis وقتی دیسک خالی است) — نه «فایل روی دیسک هست»، وگرنه اکانتِ
    فقط‌آینه‌ای که صفحه نشان می‌دهد حذف‌شدنی نبود.
    """
    name = _safe_cookie_name(raw or "")
    if not name:
        return None
    names, _local = await ck_pool.list_names(redis)
    return name if name in names else None


async def _mirror_all_cookies(redis) -> None:
    """آینهٔ Redis را با فایل‌های روی دیسک هماهنگ می‌کند (self-heal روی استارتِ پنل)."""
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


def _ck_label(a: dict) -> str:
    return a.get("label") or os.path.splitext(a.get("name") or "")[0]


async def cookies_page(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    lang = _PREFS.get()[0]
    f = Fmt(lang)
    shell = await _shell(request, admin_id)
    redis = request.app["redis"]
    lim = shell["lim"] or await ck_pool.load_limits()
    accounts = shell["accounts"]
    node_names = {n["id"]: n["name"] for n in shell["nodes"]}
    dl_nodes = [n for n in shell["nodes"] if n["role"] == "download"]
    now = int(time.time())

    rows = []
    for a in accounts:
        warm = ck_pool.warmup_factor(int(a.get("added") or 0), now, lim)
        budget = ck_pool.budget_of(a, now, lim)
        used = await ck_pool.usage(redis, a["name"])
        pin = str(a.get("node_id") or "")
        rows.append({**a, "label": _ck_label(a), "pill": f.ck_pill(a["status"]),
                     "used": used, "budget": budget, "warm": warm if warm < 1.0 else None,
                     "use_pct": min(1.0, used / budget) if budget else None,
                     "rest_until": now + int(a.get("cooldown") or 0) if a.get("cooldown") else None,
                     "err": (a.get("last_error") or "").removeprefix("ERROR: ")[:300],
                     "pin": pin, "pin_name": node_names.get(pin, pin)})

    def by_plat(p):
        return [r for r in rows if (r.get("platform") or "other") == p]

    cards = []
    for p in _CK_CARD_PLATS:
        acc = by_plat(p)
        ready = [r for r in acc if r["status"] in ck_pool.USABLE]
        caps = [r["budget"] for r in ready]
        pr = PD.pool_rows(acc, [p])
        segs = [(pr[0][k], col) for k, col in _POOL_SEGS if pr and pr[0][k]] if pr else []
        cards.append({"p": p, "n": len(acc), "ready": len(ready), "segs": segs,
                      "used": sum(r["used"] for r in ready),
                      "cap": sum(caps) if caps and all(caps) else 0})
    order = list(_COOKIE_PLATFORM_KEYS) + sorted({r.get("platform") or "other" for r in rows}
                                               - set(_COOKIE_PLATFORM_KEYS))
    groups = []
    for p in order:
        acc = by_plat(p)
        if acc:
            groups.append({"p": p, "rows": acc,
                           "ready": sum(1 for r in acc if r["status"] in ck_pool.USABLE)})
    attn = [r for r in rows if r["status"] in (ck_pool.FROZEN, ck_pool.INVALID)]

    exits = []
    for e in await ck_pool.exit_stats(redis):
        st = (("neutral", "ck.exit.unused") if e["ok"] + e["fail"] == 0
              else ("bad", "ck.exit.blocked") if e["blocked"] else ("good", "ck.exit.healthy"))
        exits.append({**e, "label": f.t("ck.exit.master") if e["exit"] == "master"
                      else node_names.get(e["exit"], e["exit"]), "st": st})

    dl_node = await node_mod.role_online(redis, "download")
    try:
        mirrored = int(await redis.scard(_CK_SET) or 0)
    except Exception:  # noqa: BLE001
        mirrored = 0
    disk_count = (len(glob.glob(os.path.join(settings.cookies_dir, "*.txt")))
                  if settings.cookies_dir and os.path.isdir(settings.cookies_dir) else 0)

    # بی‌JS: `?dlg=<شناسه>&name=<اکانت>` همان دیالوگ را باز رندر می‌کند
    dlg = request.query.get("dlg", "")
    dlg_acct = next((r for r in rows if r["name"] == request.query.get("name")), None)
    return _render("cookies", request, active="cookies", shell=shell, cards=cards, groups=groups,
                   attn=attn, exits=exits, total=len(rows),
                   ready=sum(1 for r in rows if r["status"] in ck_pool.USABLE),
                   platforms=COOKIE_PLATFORMS, required=_REQUIRED_COOKIE,
                   dl_nodes=dl_nodes, node_names=node_names, dir_ok=_cookies_dir_ok(),
                   cookies_dir=settings.cookies_dir, dl_node_online=dl_node,
                   mirrored=mirrored, disk_count=disk_count,
                   mirror_gap=bool(dl_node and disk_count != mirrored),
                   dlg=dlg, dlg_acct=dlg_acct, now=now)


async def cookies_add(request: web.Request) -> web.Response:
    """افزودنِ اکانت با **چسباندنِ متنِ کوکی** (بدونِ آپلودِ فایل)."""
    _need_admin(request)
    lang = _PREFS.get()[0]
    if not _cookies_dir_ok():
        raise _result("/cookies", err=pt(lang, "ck.dir.bad", d=settings.cookies_dir or "—"))
    form = await request.post()
    platform = (form.get("platform") or "other").strip()
    if platform not in _COOKIE_PLATFORM_KEYS:
        platform = "other"
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", (form.get("label") or "").strip())[:40].strip("-")
    text, err = _normalize_cookie_text(form.get("content") or "")
    if err:
        raise _result("/cookies", err=err, dlg="ck-add")
    err = _check_required(text, platform)
    if err:
        raise _result("/cookies", err=err, dlg="ck-add")
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
                 "added": int(time.time()), "fail_streak": 0, "disabled": False,
                 "node_id": (form.get("node_id") or "").strip()[:24],
                 "proxy": (form.get("proxy") or "").strip()[:200],
                 "user_agent": (form.get("user_agent") or "").strip()[:300]})
    await ck_pool.set_meta(redis, name, meta)
    log.info("cookie account added: %s (%d bytes)", name, len(text))
    await _audit(request, "cookie_add", target=meta["label"], platform=platform)
    raise _result("/cookies", ok="ck.added.ok")


async def cookies_replace(request: web.Request) -> web.Response:
    """جایگزینیِ **درجای** کوکیِ یک اکانت (برچسب/تاریخچه حفظ، خطاها صفر می‌شوند)."""
    _need_admin(request)
    lang = _PREFS.get()[0]
    if not _cookies_dir_ok():
        raise _result("/cookies", err=pt(lang, "ck.dir.bad", d=settings.cookies_dir or "—"))
    form = await request.post()
    redis = request.app["redis"]
    name = await _known_cookie(redis, form.get("name") or "")
    text, err = _normalize_cookie_text(form.get("content") or "")
    if not name or err:
        raise _result("/cookies", err=err or pt(lang, "ck.bad_acct"))
    meta = await ck_pool.get_meta(redis, name)
    err = _check_required(text, meta.get("platform") or ck_pool.guess_platform(name))
    if err:
        raise _result("/cookies", err=err, dlg="ck-replace", name=name)
    err = await _save_cookie(redis, name, text)
    if err:
        raise _result("/cookies", err=err)
    await ck_pool.mark_ok(redis, name)      # کوکیِ تازه → سالم + کول‌داون پاک
    log.info("cookie replaced for %s", name)
    await _audit(request, "cookie_replace", target=meta.get("label") or name)
    raise _result("/cookies", ok="ck.replaced.ok")


async def cookies_delete(request: web.Request) -> web.Response:
    _need_admin(request)
    form = await request.post()
    redis = request.app["redis"]
    name = await _known_cookie(redis, form.get("name") or "")
    if not name:
        raise _result("/cookies", err=pt(_PREFS.get()[0], "ck.bad_acct"))
    label = (await ck_pool.get_meta(redis, name)).get("label") or name
    # هر سه گام (آینه + فایل + متا) از یک جا — همان تابعِ مشترکِ مسیرِ ربات
    await ck_pool.delete_account(redis, name)
    await _audit(request, "cookie_delete", target=label)
    raise _result("/cookies", ok="ck.del.ok")


async def cookies_unfreeze(request: web.Request) -> web.Response:
    """ادمین رسیدگی کرد → اکانت از صفِ «نیازمندِ انسان» بیرون و واردِ چرخش می‌شود."""
    _need_admin(request)
    form = await request.post()
    redis = request.app["redis"]
    name = await _known_cookie(redis, form.get("name") or "")
    if not name:
        raise _result("/cookies", err=pt(_PREFS.get()[0], "ck.bad_acct"))
    await ck_pool.unfreeze(redis, name)
    try:
        await redis.delete(f"ckcheck:{name}")   # هشدارِ بعدی دوباره مجاز شود
    except Exception:  # noqa: BLE001
        pass
    await _audit(request, "cookie_unfreeze",
                 target=(await ck_pool.get_meta(redis, name)).get("label") or name)
    raise _result("/cookies", ok="ck.unfrozen")


async def cookies_identity(request: web.Request) -> web.Response:
    """پینِ هویتِ اکانت: خروجی (نود) + پروکسیِ اختصاصی + User-Agent."""
    _need_admin(request)
    form = await request.post()
    redis = request.app["redis"]
    name = await _known_cookie(redis, form.get("name") or "")
    if not name:
        raise _result("/cookies", err=pt(_PREFS.get()[0], "ck.bad_acct"))
    meta = await ck_pool.get_meta(redis, name)
    meta["node_id"] = (form.get("node_id") or "").strip()[:24]
    meta["proxy"] = (form.get("proxy") or "").strip()[:200]
    meta["user_agent"] = (form.get("user_agent") or "").strip()[:300]
    await ck_pool.set_meta(redis, name, meta)
    await _audit(request, "cookie_identity", target=meta.get("label") or name,
                 exit=meta["node_id"], proxy=_audit_value("proxy_url", meta["proxy"]))
    raise _result("/cookies", ok="ck.saved")


async def cookies_toggle(request: web.Request) -> web.Response:
    """غیرفعال/فعال‌کردنِ یک اکانت بدونِ حذفِ کوکی یا تاریخچه‌اش."""
    _need_admin(request)
    form = await request.post()
    redis = request.app["redis"]
    name = await _known_cookie(redis, form.get("name") or "")
    if not name:
        raise _result("/cookies", err=pt(_PREFS.get()[0], "ck.bad_acct"))
    meta = await ck_pool.get_meta(redis, name)
    meta["disabled"] = not bool(meta.get("disabled"))
    await ck_pool.set_meta(redis, name, meta)
    await _audit(request, "cookie_toggle", target=meta.get("label") or name,
                 state="off" if meta["disabled"] else "on")
    raise _result("/cookies", ok="ck.saved")


async def cookies_cooldown(request: web.Request) -> web.Response:
    _need_admin(request)
    form = await request.post()
    r = request.app["redis"]
    name = await _known_cookie(r, form.get("name") or "")
    if not name:
        raise _result("/cookies", err=pt(_PREFS.get()[0], "ck.bad_acct"))
    action = (form.get("action") or "").strip()
    if action not in ("set", "clear"):
        raise web.HTTPFound("/cookies")     # دکمه‌های صفحه فقط همین دو را می‌فرستند
    try:
        if action == "clear":
            await r.delete(f"ckcd:{name}")
        else:
            await r.set(f"ckcd:{name}", "1", ex=1800)
    except Exception:  # noqa: BLE001
        pass
    # `mode` نه `action`: `action` نامِ پارامترِ خودِ `_audit` است و
    # `action=` این‌جا TypeError می‌داد (هندلر ۵۰۰ می‌شد، پیش از هر نوشتنی).
    await _audit(request, "cookie_cooldown", target=name, mode=action)
    raise _result("/cookies", ok="ck.saved")


async def cookies_resync(request: web.Request) -> web.Response:
    """آینهٔ Redis را دوباره از روی دیسک بساز — نودِ دانلود فقط همین را می‌بیند."""
    _need_admin(request)
    await _mirror_all_cookies(request.app["redis"])
    await _audit(request, "cookie_resync")
    raise _result("/cookies", ok="ck.synced")


# ── نودهای توزیع‌شده (master/node روی WireGuard) ────────────────
#: توکنِ joinِ تازه‌ساخته، برای **نمایشِ یک‌بارهٔ** همان ادمین. کلید به شناسهٔ
#: ادمین بسته است، پس نه در URL می‌رود نه با شناسهٔ حدس‌زدنی قابلِ برداشتن است.
_JOIN_VIEW = "njoinview:"
_JOIN_VIEW_TTL = 1800           # هم‌اندازهٔ عمرِ خودِ توکن


async def _stash_join_view(redis, admin_id: int | None, token: str) -> None:
    if admin_id:
        await redis.set(f"{_JOIN_VIEW}{admin_id}", token, ex=_JOIN_VIEW_TTL)


async def _take_join_view(redis, admin_id: int | None) -> str:
    """توکن را برای نمایش برمی‌دارد و **مصرفش می‌کند** (`getdel`): دستورِ نصب یک‌بار
    نشان داده می‌شود و رفرشِ صفحه دوباره نشانش نمی‌دهد."""
    if not admin_id:
        return ""
    try:
        return await redis.getdel(f"{_JOIN_VIEW}{admin_id}") or ""
    except Exception:  # noqa: BLE001
        return ""


_ROLE_ICON = {"download": ("download", "t6"), "processing": ("cpu", "t5"), "gateway": ("globe", "t3")}
_QUEUE_INFO = (("ops", "arq:queue", "nd.q.ops", "master"),
               ("proc", "arq:queue:proc", "nd.q.proc", "processing"),
               ("dl", "arq:queue:dl", "nd.q.dl", "download"),
               ("dlm", "arq:queue:dl:master", "nd.q.dlm", "master"))


async def nodes_page(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    shell = await _shell(request, admin_id)
    redis = request.app["redis"]
    nodes = []
    for n in shell["nodes"]:
        icon, tint = _ROLE_ICON.get(n["role"], ("server", "t0"))
        role = node_mod.ROLES.get(n["role"], {})
        nodes.append({**n, "icon": icon, "tint": tint, "queue": role.get("queue") or ""})
    online_roles = {n["role"] for n in shell["nodes"] if n["online"]}
    queues = []
    for key, name, purpose, consumer in _QUEUE_INFO:
        down = consumer in ("processing", "download") and consumer not in online_roles
        queues.append({"key": name, "purpose": purpose, "consumer": consumer,
                       "depth": shell["queues"].get(key, 0), "down": down})
    token = await _take_join_view(redis, admin_id)
    base = settings.admin_base or (settings.public_base or "")
    install_cmd = f"curl -fsSL {base}/node/install.sh | sudo bash -s -- {token}" if token else ""
    master_ready = bool(settings.wg_master_pubkey and settings.wg_endpoint and base)
    reaped = await node_mod.reaped_count(redis)
    return _render("nodes", request, active="nodes", shell=shell, nodes=nodes, queues=queues,
                   online=sum(1 for n in nodes if n["online"]), roles=node_mod.ROLES,
                   install_cmd=install_cmd, master_ready=master_ready, reaped=reaped,
                   wg_subnet=settings.wg_subnet, wg_master_ip=settings.wg_master_ip,
                   dlg=request.query.get("dlg", ""))


async def nodes_add(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    lang = _PREFS.get()[0]
    form = await request.post()
    role = (form.get("role") or "").strip()
    if role not in node_mod.ROLES:
        raise _result("/nodes", err=pt(lang, "nd.bad_role"))
    # نامی که ادمین می‌نویسد داخلِ payloadِ **امضاشدهٔ** توکن می‌رود (نود نمی‌تواند عوضش کند)؛
    # خالی یعنی `hostname -s`ِ خودِ نود.
    name = (form.get("name") or "").strip()[:node_mod.NAME_MAX]
    tok = await node_mod.make_join_token(request.app["redis"], role, name=name)
    # **هرگز در query string.** لاگِ دسترسیِ aiohttp مسیر را با query می‌نویسد، و از
    # ۹ خطِ `tok=`ِ لاگِ تولید هشت‌تا `Referer` هم داشتند.
    await _stash_join_view(request.app["redis"], admin_id, tok)
    await _audit(request, "node_add", target=name, role=role)
    raise web.HTTPFound("/nodes?dlg=nd-made")


async def nodes_remove(request: web.Request) -> web.Response:
    _need_admin(request)
    form = await request.post()
    nid = (form.get("id") or "").strip()
    async with Sessionmaker() as s:
        n = await s.get(Node, nid) if nid else None
        if n is None:
            # فرمِ کهنه (نود در تبِ دیگر حذف شده): «حذف شد» نگو وقتی چیزی نبود
            raise _result("/nodes", err=pt(_PREFS.get()[0], "nd.rm.none"))
        name, role = n.name, n.role
        node_mod.remove_peer(n.wg_pubkey)  # peerِ WireGuard را بردار
        await s.delete(n)
        await s.commit()
    await node_mod.forget(request.app["redis"], nid)
    await _audit(request, "node_remove", target=name, role=role)
    raise _result("/nodes", ok="nd.rm.ok")


# ── APIِ عمومیِ join (توکن گِیت است؛ نود قبل از WG صدایش می‌زند) ──
async def node_join(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad json"}, status=400)
    token = (data.get("token") or "").strip()
    pubkey = (data.get("pubkey") or "").strip()
    name = (data.get("name") or "").strip()[:64]
    # اعتبارسنجی **پیش از** مصرف: برعکسش یعنی یک درخواستِ ناقص (یا ریتریِ نصب‌کننده)
    # توکن را می‌سوزاند. کلیدِ عمومی مستقیم در `wg0.conf` می‌نشیند، پس فرمتِ دقیق
    # اجباری است — مقدارِ حاویِ خطِ جدید می‌توانست دستور به کانفیگِ WG تزریق کند.
    if not node_mod.valid_pubkey(pubkey):
        return web.json_response({"error": "missing pubkey"}, status=400)
    payload = await node_mod.consume_join_token(request.app["redis"], token)
    if payload is None:
        return web.json_response({"error": "invalid or used token"}, status=403)
    role = payload["role"]
    # نامی که ادمین در پنل نوشته بر نامِ خودگزارشِ نود مقدم است.
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
    # فقط هدر: رازی که در query string برود در لاگِ دسترسی و هر پروکسیِ میانی ثبت
    # می‌شود. تنها کلاینتِ این endpoint `node/wg-sync.sh` است.
    key = request.headers.get("X-Node-Key") or ""
    secret = settings.node_secret or settings.bot_token or ""
    if not secret or not hmac.compare_digest(key, secret):
        return web.Response(text="# forbidden\n", status=403)
    async with Sessionmaker() as s:
        rows = (await s.execute(select(Node.wg_pubkey, Node.wg_ip))).all()
    peers = [(pk, ip) for (pk, ip) in rows if pk and ip]
    return web.Response(text=node_mod.render_peers(peers), content_type="text/plain")


# ── سیستم ─────────────────────────────────────────────────────────────────
async def system_page(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    if request.query.get("refresh") == "1":
        # تازه‌سازیِ دستی: کشِ پروب‌ها را دور بریز تا همین الان دوباره سنجیده شوند
        try:
            await request.app["redis"].delete(_SVC_FRESH, _POT_FRESH)
        except Exception:  # noqa: BLE001
            pass
        _schedule_svc_refresh(request.app)
        if settings.pot_provider_url:
            _schedule_pot_refresh(request.app)
        raise web.HTTPFound("/system")
    shell = await _shell(request, admin_id)
    redis = request.app["redis"]
    eff = await _effective()
    disk = shell["disk"]
    try:
        jan = json.loads(await redis.get("janitor:last") or "null")
    except Exception:  # noqa: BLE001
        jan = None
    segs, markers = [], []
    if disk:
        tg = min(disk["used"], int((jan or {}).get("kept_bytes") or 0))
        segs = [("sy.disk.tg", tg, "var(--c2)"), ("sy.disk.rest", disk["used"] - tg, "var(--c1)"),
                ("sy.disk.free", disk["free"], "var(--track)")]
        for key, cls, label in (("dl_min_free_gb", "dl", "sy.disk.min_dl"),
                                ("tg_files_min_free_gb", "tg", "sy.disk.min_tg")):
            gb = int(eff.get(key) or 0)
            if gb > 0:
                at = max(0.0, min(100.0, 100 - gb * 1024 ** 3 / disk["total"] * 100))
                markers.append({"cls": cls, "at": round(at, 1), "label": label, "gb": gb})
    engines = []
    try:
        async for key in redis.scan_iter(match="dlver:*", count=100):
            try:
                engines.append(json.loads(await redis.get(key) or "{}"))
            except (ValueError, TypeError):
                pass
    except Exception:  # noqa: BLE001
        pass
    engines.sort(key=lambda e: str(e.get("who") or ""))
    # همان نام‌گذاریِ صفحهٔ کوکی‌ها: «مستر» و نامِ نود، نه شناسهٔ خامش.
    f = Fmt(_PREFS.get()[0])
    node_names = {n["id"]: n["name"] for n in shell["nodes"]}
    for e in engines:
        who = str(e.get("who") or "")
        e["label"] = f.t("ck.exit.master") if who == "master" else node_names.get(who, who)
    dl_now = await dl_active.count(redis)
    svc = await _svc_cached(request.app)
    return _render("system", request, active="system", shell=shell, services=shell["services"],
                   svc_ok=sum(1 for s in shell["services"] if s["ok"]), checked=svc.get("at"),
                   disk=disk, segs=segs, markers=markers, jan=jan, engines=engines,
                   dl_active=dl_now, dl_conc=int(eff.get("dl_concurrency") or 0),
                   queues=shell["queues"], queue_names=_QUEUES, stuck=shell["stuck"],
                   tls=shell["tls"])


# ── متن‌های ربات (override زمانِ‌اجرا روی locales) ─────────────────────────
#: از `langpack` می‌آید، نه از یک کپیِ دوم — همان فهرست که export/import هم
#: رویش کار می‌کند، وگرنه صفحه و فایل می‌توانند سرِ «کلیدها کدام‌اند» واگرا شوند.
_TEXT_KEYS = list(langpack.TEXT_KEYS)


async def _languages(refresh: bool = False) -> dict[str, str]:
    """پوستهٔ پنلی روی `i18n.available_languages()` — تازه‌سازی + همان فهرست.

    فهرست عمداً این‌جا **ساخته نمی‌شود**: رباتْ هم همان را می‌خواهد (منوی انتخابِ
    زبان)، و `routers/` نمی‌تواند این ماژول را import کند (ایمیجِ ربات
    jinja2/cryptography ندارد). این‌جا فقط `refresh_if_stale` می‌ماند که پنلی است —
    پنل میان‌افزارِ per-update ندارد که خودش تازه کند.
    """
    if refresh:
        await textstore.refresh_if_stale()
    return await i18n_available_languages()


async def _pick_lang(raw: str | None) -> tuple[str, dict[str, str]]:
    """(زبانِ معتبر, فهرستِ زبان‌ها) — ناشناخته به `DEFAULT` می‌افتد."""
    langs = await _languages()
    code = (raw or "").strip()
    return (code if code in langs else i18n_DEFAULT), langs


#: دسته‌بندیِ کلیدها بر اساسِ پیشوند (سگمنتِ پیش از اولین «_»)؛ هرچه نیفتد → «سایر».
_TEXT_CATS: tuple[tuple[str, frozenset[str]], ...] = (
    ("btn", frozenset({"btn"})),
    ("cl", frozenset({"cl"})),
    ("dl", frozenset({"dl"})),
    ("pr", frozenset({"pr", "processing", "queued", "cancelling", "cancelled", "done", "failed"})),
    ("meta", frozenset({"meta"})),
    ("wm", frozenset({"wm"})),
    ("media", frozenset({"rot", "rotate", "resize", "ocr", "shot", "trim", "speed", "cover",
                         "compress", "vjoin", "merge", "img", "zip"})),
    ("asr", frozenset({"asr", "tr"})),
    ("card", frozenset({"detected", "card", "link", "limit", "too", "ask", "send", "coming",
                        "welcome", "choose", "language", "list"})),
)
_TEXT_CAT_IDS = tuple(c for c, _ in _TEXT_CATS) + ("other",)
#: آیکونِ سرِ هر دسته در فهرستِ متن‌ها.
_TEXT_CAT_ICON = {"btn": "keyboard", "cl": "captions", "dl": "download", "pr": "activity",
                  "meta": "music", "wm": "stamp", "media": "image", "asr": "audio-lines",
                  "card": "message-square-text", "other": "list"}
_PH = re.compile(r"\{(\w+)\}")
#: زبان‌های راست‌به‌چپ (کدِ پایه) — جهتِ جعبهٔ ویرایشِ متن و برچسبِ دکمه.
_RTL = frozenset({"fa", "ar", "he", "ur", "ps", "ckb", "sd", "ug", "yi", "dv"})


def _text_dir(code: str) -> str:
    return "rtl" if (code or "").split("-")[0].lower() in _RTL else "ltr"


def _text_default(lang: str, key: str) -> str:
    """پیش‌فرضِ یک کلید — از `i18n`، تا صفحه و ربات **یک** زنجیرهٔ fallback داشته باشند."""
    return default_text(lang, key)


def _text_cat(key: str) -> str:
    seg = key.split("_")[0]
    for cid, prefixes in _TEXT_CATS:
        if seg in prefixes:
            return cid
    return "other"


#: شکلِ جست‌وجوپذیرِ متن — **همان** قاعده‌ای که `fold`ِ `panel.js` دارد، تا فیلترِ
#: سمتِ سرور (بی‌JS) و فیلترِ درجا یک جواب بدهند: حروفِ کوچک، «ي/ى/ك»ِ عربی →
#: «ی/ک»ِ فارسی، و بی‌نیم‌فاصله و نشانهٔ جهت — وگرنه «میشود» «می‌شود» را پیدا نمی‌کرد.
_FOLD = str.maketrans({"\u064a": "\u06cc", "\u0649": "\u06cc", "\u0643": "\u06a9",
                       "\u200c": None, "\u200d": None, "\u200e": None, "\u200f": None})


def _fold(s: str) -> str:
    return s.lower().translate(_FOLD)


def _texts_rows(lang: str, q: str, cat: str, edited_only: bool) -> tuple[list[dict], dict[str, int]]:
    """**همهٔ** متن‌های یک زبان به ترتیبِ دسته، هر کدام با `shown` + شمارِ هر دسته.

    فیلتر ردیف را حذف نمی‌کند، فقط `shown=False` می‌دهد (قالب `hidden` می‌گذارد):
    `panel.js` همان فیلتر را درجا اعمال می‌کند، پس عوض‌کردنِ دسته یا جست‌وجو دیگر
    صفحه را از نو نمی‌سازد — قبلاً می‌ساخت و ویرایشِ ذخیره‌نشده بی‌صدا از بین می‌رفت.
    بی‌JS همین `hidden` همان فیلترِ سمتِ سرور است. شمارِ هر دسته با جست‌وجو و
    «فقط ویرایش‌شده‌ها» حساب می‌شود، نه با خودِ دسته (تراشه‌ها همین را نشان می‌دهند).
    """
    ov = textstore.lang_texts(lang)
    ql = _fold(q.strip())
    counts: dict[str, int] = {"all": 0}
    by_cat: dict[str, list[dict]] = {c: [] for c in _TEXT_CAT_IDS}
    for key in _TEXT_KEYS:
        default = _text_default(lang, key)
        override = ov.get(key)
        current = override if override is not None else default
        c = _text_cat(key)
        hit = (not ql or any(ql in _fold(x) for x in (key, default, current))) \
            and (override is not None or not edited_only)
        if hit:
            counts["all"] += 1
            counts[c] = counts.get(c, 0) + 1
        by_cat[c].append({"key": key, "cat": c, "default": default, "current": current,
                          "edited": override is not None, "shown": hit and cat in ("all", c),
                          "ph": sorted({"{%s}" % m for m in _PH.findall(default)}),
                          "lines": min(8, max(1, current.count("\n") + 1))})
    return [r for c in _TEXT_CAT_IDS for r in by_cat[c]], counts


def _texts_state(lang: str, q: str, cat: str, edited: bool) -> dict:
    return {"lang": lang if lang != i18n_DEFAULT else "", "q": q,
            "cat": cat if cat != "all" else "", "edited": "1" if edited else ""}


async def texts_page(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    # همیشه از DB تازه: بدونِ این، پس از ری‌استارت دیکشنریِ درون‌پروسه خالی است و
    # ذخیره از آن نمای کهنه overrideهای واقعی را با پیش‌فرض بازنویسی می‌کرد.
    await textstore.refresh_if_stale()
    lang, langs = await _pick_lang(request.query.get("lang"))
    q = (request.query.get("q") or "").strip()[:80]
    cat = _choice(request.query.get("cat"), ("all",) + _TEXT_CAT_IDS, "all")
    edited = request.query.get("edited") == "1"
    rows, counts = _texts_rows(lang, q, cat, edited)
    groups = [{"id": c, "rows": [r for r in rows if r["cat"] == c]} for c in _TEXT_CAT_IDS]
    groups = [dict(g, shown=any(r["shown"] for r in g["rows"])) for g in groups if g["rows"]]
    n_edited = sum(1 for k in textstore.lang_texts(lang) if k in langpack.TEXT_KEYS)
    state = _texts_state(lang, q, cat, edited)
    return await _page(request, "texts", "texts", admin_id=admin_id, lang_sel=lang, langs=langs,
                       q=q, cat=cat, edited=edited, groups=groups, counts=counts,
                       n_shown=sum(1 for r in rows if r["shown"]),
                       cats=("all",) + _TEXT_CAT_IDS, cat_icons=_TEXT_CAT_ICON, total=len(_TEXT_KEYS),
                       n_edited=n_edited, state=state, qs=lambda **kw: _qs(state, **kw),
                       text_dir=_text_dir(lang))


def _texts_back(form, lang: str) -> dict:
    return _texts_state(lang, str(form.get("q") or "")[:80],
                        _choice(str(form.get("cat") or ""), ("all",) + _TEXT_CAT_IDS, "all"),
                        str(form.get("edited") or "") == "1")


def _wants_json(request: web.Request) -> bool:
    """درخواستِ `fetch`ِ `panel.js` که پاسخِ JSON می‌خواهد — نه فرمِ معمولیِ بی‌JS."""
    return "application/json" in request.headers.get("Accept", "")


async def texts_save(request: web.Request) -> web.Response:
    """ذخیرهٔ دسته‌ای: هر `v:<کلید>`ی که فرم فرستاده (JS فقط تغییرکرده‌ها را می‌فرستد).

    **اول همه را بسنج، بعد بنویس**، در یک تراکنش (`textstore.set_texts`): یک متنِ
    نامعتبر یعنی هیچ‌کدام ذخیره نمی‌شود و فهرستِ کلید+دلیل برمی‌گردد. مقدارِ برابر
    با پیش‌فرض یعنی «override را بردار». فرمِ قدیمیِ تک‌کلیدی (`key`+`value`) هم
    پذیرفته می‌شود.

    دو پاسخ، یک قاعده: فرمِ بی‌JS ریدایرکت می‌گیرد (`_result`)، و `fetch`ِ
    `panel.js` (`Accept: application/json`) JSON — تا صفحه **رفرش نشود و به بالا
    نپرد**: ردیف‌های ذخیره‌شده درجا به‌روز می‌شوند و خطای هر کلید زیرِ همان ردیف
    می‌نشیند، با متنی که ادمین نوشته. پیش از این هر ذخیره صفحه را از نو می‌ساخت،
    اسکرول به بالا می‌رفت و ردِ اعتبارسنجی متنِ تایپ‌شده را دور می‌ریخت. نشستِ
    منقضی در JSON ۴۰۱ است نه ریدایرکت به `/login`، وگرنه fetch صفحهٔ ورود را با
    ۲۰۰ می‌گرفت و ویرایش‌ها بی‌دلیلِ گفته‌شده ذخیره نمی‌شدند.
    """
    ui = _PREFS.get()[0]
    as_json = _wants_json(request)
    if as_json and not _session_admin(request):
        return web.json_response({"ok": False, "login": True, "msg": pt(ui, "tx.err.session")},
                                 status=401)
    _need_admin(request)
    form = await request.post()
    langs = await _languages(refresh=True)
    raw_lang = (form.get("lang") or "").strip()
    lang = raw_lang if raw_lang in langs else i18n_DEFAULT
    back = _texts_back(form, lang)
    # زبانِ ناشناخته و کلیدِ ناشناخته دو خطای متفاوت‌اند و باید متفاوت گفته شوند.
    if raw_lang not in langs:
        msg = pt(ui, "tx.err.lang", l=raw_lang)
        if as_json:
            return web.json_response({"ok": False, "msg": msg, "errors": {}}, status=400)
        raise _result("/texts", err=msg, **back)
    posted: list[tuple[str, str]] = [(k[2:], str(v)) for k, v in form.items() if k.startswith("v:")]
    if form.get("key") is not None:
        posted.append((str(form.get("key") or "").strip(), str(form.get("value") or "")))
    changes: dict[str, str | None] = {}
    defaults: dict[str, str] = {}
    errors: dict[str, str] = {}
    for key, value in posted:
        if key not in langpack.TEXT_KEYS:
            errors[key[:60]] = pt(ui, "tx.err.key", k=key[:60])
            continue
        value = value.replace("\r\n", "\n")
        default = defaults[key] = _text_default(lang, key)
        if value.strip() == default.strip():          # برابرِ پیش‌فرض = حذفِ override
            changes[key] = None
            continue
        err = textstore.validate(default, value, lang=ui)
        if err:
            errors[key] = err
        else:
            changes[key] = value
    if errors:
        if as_json:
            return web.json_response({"ok": False, "errors": errors,
                                      "msg": pt(ui, "tx.err.n", n=Fmt(ui).num(len(errors)))}, status=400)
        shown = [msg if k not in langpack.TEXT_KEYS else f"{k}: {msg}" for k, msg in errors.items()]
        raise _result("/texts", err=" · ".join(shown[:3]), **back)
    ov = textstore.lang_texts(lang)
    sets = {k: v for k, v in changes.items() if v is not None and ov.get(k) != v}
    clears = [k for k, v in changes.items() if v is None and k in ov]
    if sets or clears:
        await textstore.set_texts(lang, sets, clear=clears)
        # برگرداندن به پیش‌فرض «ویرایش» نیست: با JS دکمهٔ «برگرداندن» هم از همین مسیر
        # ذخیره می‌شود، و بدونِ این تفکیک لاگِ ادمین آن را «ویرایشِ متن» می‌نوشت.
        if sets:
            await _audit(request, "text_save", target=next(iter(sets)) if len(sets) == 1 else "",
                         lang=lang, n=len(sets))
        if clears:
            await _audit(request, "text_reset", target=clears[0] if len(clears) == 1 else "",
                         lang=lang, n=len(clears))
    if not as_json:
        raise _result("/texts", ok="tx.saved.ok", **back)
    f = Fmt(ui)
    ov = textstore.lang_texts(lang)
    n_set, n_clear = len(sets), len(clears)
    if not (n_set or n_clear):
        msg = f.t("tx.saved.none")
    elif not n_set:
        msg = f.t("tx.reset.ok") if n_clear == 1 else f.t("tx.reset.n", n=f.num(n_clear))
    else:
        msg = f.t("tx.saved.one") if n_set + n_clear == 1 else f.t("tx.saved.n", n=f.num(n_set + n_clear))
    n_edited = sum(1 for k in ov if k in langpack.TEXT_KEYS)
    return web.json_response({
        "ok": True, "msg": msg,
        "saved": {k: {"value": ov.get(k, defaults[k]), "edited": k in ov, "default": defaults[k]}
                  for k in changes},
        "n_edited": n_edited, "n_edited_t": f.num(n_edited),
        "sub": f.t("tx.sub", n=f.num(len(_TEXT_KEYS)), e=f.num(n_edited)),
    })


async def texts_reset(request: web.Request) -> web.Response:
    """یک متن به پیش‌فرض. زبان یا کلیدِ ناشناخته خطا می‌گیرد، نه «برگشت» — همان دو
    خطای جدای `texts_save`؛ بنرِ سبز روی کاری که انجام نشد دقیقاً همان چیزی است
    که §۷ چهار بار ثبت کرده."""
    _need_admin(request)
    ui = _PREFS.get()[0]
    form = await request.post()
    langs = await _languages(refresh=True)
    raw_lang = (form.get("lang") or "").strip()
    lang = raw_lang if raw_lang in langs else i18n_DEFAULT
    back = _texts_back(form, lang)
    key = (form.get("reset") or form.get("key") or "").strip()
    if raw_lang not in langs:
        raise _result("/texts", err=pt(ui, "tx.err.lang", l=raw_lang), **back)
    if key not in langpack.TEXT_KEYS:
        raise _result("/texts", err=pt(ui, "tx.err.key", k=key[:60]), **back)
    if textstore.get_override(lang, key) is not None:
        await textstore.reset_text(lang, key)
        await _audit(request, "text_reset", target=key, lang=lang)
    raise _result("/texts", ok="tx.reset.ok", **back)


# ── دکمه‌های کارت: چیدمان و استایل (per-kind) ────────────────────────────
from . import keyboards as _KB  # noqa: E402

_KIND_ORDER = ("video", "audio", "image", "document", "pdf", "archive", "app")
_STYLE_IDS = ("", "primary", "success", "danger")
#: نمونهٔ کارت در پیش‌نمایش (آیکون, نامِ فایل, حجم MB, ارتفاع, مدت ثانیه)
_KIND_SAMPLE = {"video": ("film", "lecture_week3.mp4", 51.4, 1080, 1226),
                "audio": ("music", "Shadmehr - Taghdir.mp3", 8.6, None, 261),
                "image": ("image", "IMG_4821.jpg", 3.1, None, None),
                "document": ("file-text", "contract_v2.docx", 0.4, None, None),
                "pdf": ("file-text", "invoice-1405-07.pdf", 1.2, None, None),
                "archive": ("folder-archive", "photos_backup.zip", 212, None, None),
                "app": ("package", "telegram-x.apk", 78.5, None, None)}


def _menu_editor_items(kind: str, lang: str) -> list[dict]:
    """همهٔ کلیدهای منوی kind (شاملِ مخفی‌ها) به ترتیبِ ویرایش.

    همان قاعدهٔ `keyboards._resolved_menu` (opِ تازه‌ای که بعد از ذخیرهٔ چیدمان به کد
    اضافه شده ته می‌رود، با عرضِ پیش‌فرضِ `keyboards._default_width`)، با این تفاوت که
    مخفی‌ها هم برمی‌گردند — ویرایشگر باید بتواند دوباره نشانشان دهد.
    """
    ops = OPS_BY_KIND.get(kind, [])
    key_by_op = dict(ops)
    first_op = ops[0][0] if ops else ""
    layout = textstore.get_menu_layout(kind)
    styles = textstore.button_snapshot()
    meta: dict[str, dict] = {}
    order: list[str] = []
    if layout:
        meta = {e["op"]: e for e in layout}
        seen = set()
        for e in layout:
            if e["op"] in key_by_op and e["op"] not in seen:
                order.append(e["op"])
                seen.add(e["op"])
        order += [op for op, _k in ops if op not in seen]
    else:
        order = [op for op, _k in ops]
    items = []
    for op in order:
        key = key_by_op[op]
        st, em = styles.get(op, (None, None))
        e = meta.get(op)
        default = _text_default(lang, key)
        items.append({"op": op, "key": key, "default": default,
                      "text": textstore.get_override(lang, key) or default,
                      "style": st or "", "emoji": em or "",
                      "width": (e.get("width") if e else None) or _KB._default_width(kind, op, first_op),
                      "hidden": bool(e.get("hidden")) if e else False})
    return items


def _menu_preview(items: list[dict]) -> list[list[dict]]:
    """ردیف‌های پیش‌نمایش (فقط کلیدهای نمایان) — بسته‌بندی از خودِ `keyboards`."""
    vis = [it for it in items if not it["hidden"]]
    rows, i = [], 0
    for s in _KB._rows_from_widths([it["width"] for it in vis]):
        rows.append(vis[i:i + s])
        i += s
    return rows


async def buttons_page(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    await textstore.refresh_if_stale()
    kind = _choice(request.query.get("kind"), _KIND_ORDER, "video")
    lang, langs = await _pick_lang(request.query.get("lang"))
    items = _menu_editor_items(kind, lang)
    f = Fmt(_PREFS.get()[0])
    icon, name, mb, h, dur = _KIND_SAMPLE[kind]
    sample = {"icon": icon, "name": name, "media": kind in ("video", "image"),
              "info": [f.mb(mb), f.res(h), f.secs_short(dur) if dur else ""]}
    return await _page(request, "buttons", "buttons", admin_id=admin_id, kind=kind,
                       kinds=[(k, len(OPS_BY_KIND.get(k, []))) for k in _KIND_ORDER],
                       lang_sel=lang, langs=langs, items=items, pv_rows=_menu_preview(items),
                       close_label=_t(lang, "btn_close"), sample=sample, styles=_STYLE_IDS,
                       widths=textstore.BUTTON_WIDTHS, width_cap=json.dumps(_KB._WIDTH_CAP),
                       text_dir=_text_dir(lang))


async def buttons_save(request: web.Request) -> web.Response:
    _need_admin(request)
    form = await request.post()
    kind = (form.get("kind") or "video").strip()
    lang = (form.get("lang") or "").strip()
    if kind not in _KIND_ORDER or lang not in await _languages(refresh=True):
        raise web.HTTPFound("/buttons")
    key_by_op = dict(OPS_BY_KIND.get(kind, []))
    order = [op for op in (form.get("order") or "").split(",") if op in key_by_op]
    order = list(dict.fromkeys(order))
    for op, _k in OPS_BY_KIND.get(kind, []):  # هر opِ جاافتاده را ته اضافه کن
        if op not in order:
            order.append(op)
    # **اول همه را بسنج، بعد بنویس.** پیش از این، اعتبارسنجی و نوشتن در یک حلقه
    # بودند و شاخهٔ `elif` هر متنی را که `validate()` رد می‌کرد به «حذفِ override»
    # ترجمه می‌کرد — یعنی یک تایپ در placeholder، برچسبِ سالمِ قبلی را پاک می‌کرد.
    # اتمیک است: یا همه اعمال می‌شود یا هیچ‌کدام، با دلیل.
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
    await _audit(request, "buttons_save", target=kind, lang=lang)
    raise _result("/buttons", kind=kind, lang=lang, ok="bt.saved")


async def buttons_reset(request: web.Request) -> web.Response:
    _need_admin(request)
    form = await request.post()
    kind = (form.get("kind") or "video").strip()
    lang, _ = await _pick_lang(form.get("lang"))
    if kind not in _KIND_ORDER:
        raise web.HTTPFound("/buttons")     # همان رفتارِ `buttons_save`: نوعِ ناشناخته، بی‌کار
    await textstore.reset_menu_layout(kind)
    await _audit(request, "buttons_reset", target=kind)
    raise _result("/buttons", kind=kind, lang=lang if lang != i18n_DEFAULT else "", ok="bt.reset.ok")


# ── زبان‌ها: export/import بستهٔ ترجمه ─────────────────────────────────────
_PACK_MAX = 512 * 1024


async def _lang_rows(langs: dict[str, str]) -> list[dict]:
    """یک ردیف به‌ازای هر زبان، با پوششِ **محاسبه‌شده** نه برچسبِ ثابت."""
    total = len(langpack.TEXT_KEYS)
    users = await PD.lang_counts()
    added = await PD.language_dates()
    rows = []
    for code, name in langs.items():
        builtin = code in BUILTIN_NAMES
        # زبانِ داخلی کاتالوگِ کد دارد، پس پوششش طبقِ تعریف کامل است؛ زبانِ
        # افزوده فقط به‌اندازهٔ ردیف‌هایش ترجمه دارد و بقیه به انگلیسی می‌افتد.
        done = total if builtin else len([k for k in textstore.lang_texts(code) if k in langpack.TEXT_KEYS])
        rows.append({"code": code, "name": name, "builtin": builtin, "default": code == i18n_DEFAULT,
                     "done": done, "total": total, "pct": done / total if total else 0,
                     "users": users.get(code, 0), "added": added.get(code)})
    return rows


async def _langs_render(request: web.Request, *, error: str = "", review=None, raw: str = "",
                        replace: bool = False, confirm: str = "", form: dict | None = None,
                        dlg: str = "") -> web.Response:
    langs = await _languages()
    rows = await _lang_rows(langs)
    return await _page(request, "langs", "langs", rows=rows, langs=langs, default_lang=i18n_DEFAULT,
                       total=len(langpack.TEXT_KEYS), rv=review, raw=raw, replace=replace,
                       confirm=confirm, error=error, form=form or {},
                       dlg=dlg or (request.query.get("dlg") or ""),
                       pre=request.query.get("code") or "")


async def langs_page(request: web.Request) -> web.Response:
    _need_admin(request)
    await textstore.refresh_if_stale()
    return await _langs_render(request)


async def langs_export(request: web.Request) -> web.Response:
    """بستهٔ ترجمه برای دادن به یک ابزارِ ترجمه. همین شکل دوباره import می‌شود."""
    _need_admin(request)
    ui = _PREFS.get()[0]
    await textstore.refresh_if_stale()
    langs = await _languages()
    try:
        code = langpack.normalize_code(request.query.get("lang", ""))
    except langpack.PackError as exc:
        return await _langs_render(request, error=str(exc) or pt(ui, "lng.err.code"))
    source = request.query.get("source", "") or i18n_DEFAULT
    if source not in langs:
        source = i18n_DEFAULT
    name = (request.query.get("name", "") or "").strip()[:64] or langs.get(code) or code
    pack = langpack.build_pack(
        lang=code, name=name, source=source,
        texts=langpack.effective_texts(source, textstore.lang_texts(source)))
    return web.Response(
        text=pack, content_type="application/json", charset="utf-8",
        headers={"Content-Disposition": f'attachment; filename="telabzar-{code}.json"'})


async def _read_pack(form) -> str:
    """متنِ بسته: فایلِ بارگذاری‌شده بر متنِ چسبانده مقدم است."""
    up = form.get("pack_file")
    if isinstance(up, web.FileField):
        data = up.file.read(_PACK_MAX + 1)
        if len(data) > _PACK_MAX:
            raise langpack.PackError("فایل بزرگ‌تر از ۵۱۲ کیلوبایت است.")
        if data:
            return data.decode("utf-8-sig", errors="replace")
    return str(form.get("pack") or "")


async def langs_import(request: web.Request) -> web.Response:
    """بسته → سنجش → (تأیید برای زبانِ پیش‌فرض) → نوشتن.

    اتمیک: اگر حتی یک کلید خطا داشته باشد **هیچ‌چیز** نوشته نمی‌شود و فهرستِ
    کلید+دلیل برمی‌گردد، تا ادمین همان فهرست را به ابزارِ ترجمه بدهد و دوباره بفرستد.
    """
    _need_admin(request)
    await textstore.refresh_if_stale()
    form = await request.post()
    replace = form.get("replace") == "on" or form.get("mode") == "replace"
    fvals = {"code": str(form.get("lang") or "")[:32], "name": str(form.get("name") or "")[:64]}
    langs = await _languages()
    raw = ""
    try:
        raw = await _read_pack(form)
        pack = langpack.parse_pack(raw)
        code = langpack.normalize_code(str(form.get("lang") or "") or pack.get("lang") or "")
        # کدِ فرم حاکم است و کدِ داخلِ فایل فقط **مقایسه** می‌شود: ابزارِ ترجمه
        # می‌تواند `"lang"` را بی‌خبر عوض کند و ترجمه زیرِ زبانِ اشتباه بنشیند.
        in_file = str(pack.get("lang") or "")
        if in_file and langpack.normalize_code(in_file) != code:
            raise langpack.PackError(
                f"کدِ زبانِ داخلِ فایل («{in_file}») با کدِ فرم («{code}») یکی نیست.")
    except langpack.PackError as exc:
        return await _langs_render(request, error=str(exc), raw=raw, replace=replace, form=fvals,
                                   dlg="lng-import")
    name = (fvals["name"].strip() or str(pack.get("name") or "").strip() or langs.get(code) or code)[:64]
    fvals = {"code": code, "name": name}
    source = str(pack.get("source") or i18n_DEFAULT)
    rv = langpack.review(
        pack,
        source_texts=langpack.effective_texts(source, textstore.lang_texts(source)),
        current=langpack.effective_texts(code, textstore.lang_texts(code)),
        defaults=langpack.effective_texts(code, {}))
    rv.name = name
    if not rv.ok:
        return await _langs_render(request, review=rv, raw=raw, replace=replace, form=fvals,
                                   dlg="lng-import")
    # زبانِ **پیش‌فرض** تأییدِ صریح می‌خواهد: یک بسته می‌تواند کلِ رابطِ ربات را عوض
    # کند، و برخلافِ زبان‌های دیگر هیچ نسخهٔ «قبلی»ای نیست که با reset برگردد.
    if code == i18n_DEFAULT and form.get("confirm") != "yes":
        return await _langs_render(request, review=rv, raw=raw, replace=replace, confirm="ask",
                                   form=fvals, dlg="lng-import")
    if code not in BUILTIN_NAMES:
        await textstore.add_language(code, name)
    await textstore.set_texts(code, rv.overrides, replace=replace, clear=rv.defaulted)
    await _audit(request, "lang_import", target=code, name=name, n=len(rv.overrides))
    raise _result("/langs", ok="lng.d.saved")


async def langs_delete(request: web.Request) -> web.Response:
    _need_admin(request)
    ui = _PREFS.get()[0]
    form = await request.post()
    code = str(form.get("code") or "").strip()
    if code in BUILTIN_NAMES:
        return await _langs_render(request, error=pt(ui, "lng.err.builtin"))
    langs = await _languages()
    if code in langs:
        await textstore.remove_language(code)
        await _audit(request, "lang_delete", target=code, name=langs.get(code, ""))
    raise _result("/langs", ok="lng.del.ok")


# ── تنظیمات ───────────────────────────────────────────────────────────────
def _settings_auto_keys() -> list[str]:
    """کلیدهای `RUNTIME_KEYS` که در `panel_settings` جا ندارند — گم نمی‌شوند، در
    بخشِ «بدون دسته» می‌آیند و `save()` هم همان مجموعه را می‌خواند."""
    known = set(PS.setting_keys())
    return sorted(k for k in RUNTIME_KEYS if k not in known)


def _auto_field(key: str) -> dict:
    kind = RUNTIME_KEYS[key][0]
    if key in ENUM_VALUES:
        return {"k": key, "type": "enum", "l": (key, key), "h": None, "auto": True,
                "opts": tuple((v, (v or "—", v or "—")) for v in ENUM_VALUES[key])}
    return {"k": key, "type": {"bool": "bool", "int": "int"}.get(kind, "str"), "l": (key, key),
            "h": None, "auto": True, "ltr": True}


def _settings_sections() -> list[dict]:
    """بخش‌های صفحه = `panel_settings.SECTIONS` + بخشِ خودکار. **تنها منبعِ** هم رندر
    و هم `save()` — وگرنه ردیفی که دیده می‌شود ممکن بود بی‌صدا ذخیره نشود."""
    out = [dict(s) for s in PS.SECTIONS]
    auto = _settings_auto_keys()
    if auto:
        out.append({"id": "auto", "icon": "circle-help", "tint": "t0", "t": None,
                    "subs": [{"f": [_auto_field(k) for k in auto]}]})
    return out


def _settings_fields() -> list[dict]:
    return [fld for sec in _settings_sections() for sub in sec["subs"] for fld in sub["f"]]


def _fld_label(f: Fmt, fld: dict) -> str:
    if fld.get("auto"):
        return fld["k"]
    if fld["l"][0]:
        return fld["l"][0 if f.fa else 1]
    if fld.get("plat"):
        return f.plat(fld["plat"])
    return fld["k"]


def _fld_value_text(f: Fmt, fld: dict, v) -> str:
    """نمایشِ یک مقدار (پیش‌فرض یا لاگ) به زبانِ پنل."""
    typ = fld["type"]
    if typ == "bool":
        return f.t("c.on") if v else f.t("c.off")
    if typ == "enum":
        for val, lab in fld.get("opts", ()):
            if val == v:
                return lab[0 if f.fa else 1]
        return str(v) or "—"
    if typ == "int":
        unit = PS.UNITS.get(fld.get("u") or "")
        return f.num(v) + (" " + f.t(unit) if unit else "")
    if typ in PS.SECRET_TYPES:
        return f.t("st.secret.set") if v else "—"
    return str(v) if v not in ("", None) else "—"


def _settings_view(f: Fmt, eff: dict, q: str) -> tuple[list[dict], int]:
    """داده‌ی رندرِ هر بخش و هر فیلد (با جست‌وجوی سمتِ سرور برای حالتِ بی‌JS).

    جست‌وجو ردیفِ نامرتبط را **پنهان** می‌کند (`match=False`)، حذف نمی‌کند: `save()`
    هر کلیدِ bool را که در فرم نباشد «خاموش» می‌خواند، پس ردیفِ حذف‌شده یعنی
    خاموش‌شدنِ بی‌صدای سوییچ‌هایی که ادمین اصلاً ندیده.
    """
    ql = q.strip().lower()
    secs, shown = [], 0
    for sec in _settings_sections():
        subs, n_changed, n_all, n_match = [], 0, 0, 0
        for sub in sec["subs"]:
            items = []
            for fld in sub["f"]:
                k = fld["k"]
                kind, default = RUNTIME_KEYS[k]
                v = eff.get(k, default)
                label = _fld_label(f, fld)
                hlp = fld["h"][0 if f.fa else 1] if fld.get("h") else ""
                if fld.get("auto"):
                    hlp = f.t("st.auto.h")
                search = " ".join((label, k, hlp)).lower()
                changed = (bool(v) != bool(default)) if kind == "bool" else str(v) != str(default)
                n_all += 1
                n_changed += 1 if changed else 0
                match = not ql or ql in search
                n_match += 1 if match else 0
                typ = fld["type"]
                if typ == "int":
                    shown_v = f.digits(v)
                elif typ in PS.SECRET_TYPES:
                    shown_v = ""                    # راز هرگز در HTML نمی‌رود
                else:
                    shown_v = "" if v is None else str(v)
                opts = list(fld.get("opts") or ())
                if typ == "enum" and not any(o[0] == v for o in opts):
                    opts.append((v, (str(v), str(v))))     # مقدارِ ناشناخته گم نشود
                lo_hi = settings_store.BOUNDS.get(k)
                items.append({**fld, "label": label, "help": hlp, "value": v, "shown": shown_v,
                              "changed": changed, "default": default,
                              "default_text": _fld_value_text(f, fld, default),
                              "default_v": ("1" if default else "0") if typ == "bool"
                              else (f.digits(default) if typ == "int" else str(default or "")),
                              "unit": f.t(PS.UNITS[fld["u"]]) if fld.get("u") in PS.UNITS else "",
                              "max": lo_hi[1] if lo_hi and lo_hi[1] is not None else None,
                              "opts": [(val, lab[0 if f.fa else 1]) for val, lab in opts],
                              "search": search, "match": match,
                              "is_set": bool(v) if typ in PS.SECRET_TYPES else None})
            subs.append({"t": sub["t"][0 if f.fa else 1] if sub.get("t") else "",
                         "h": sub["h"][0 if f.fa else 1] if sub.get("h") else "",
                         "caps": bool(sub.get("caps")), "f": items,
                         "match": any(it["match"] for it in items)})
        shown += n_match
        title = sec["t"][0 if f.fa else 1] if sec.get("t") else f.t("st.auto")
        secs.append({"id": sec["id"], "icon": sec["icon"], "tint": sec["tint"], "title": title,
                     "subs": subs, "n_changed": n_changed, "n_all": n_all, "match": n_match > 0})
    return secs, shown


async def settings_page(request: web.Request) -> web.Response:
    admin_id = _need_admin(request)
    f = Fmt(_PREFS.get()[0])
    q = (request.query.get("q") or "").strip()[:60]
    eff = await _effective()
    secs, shown = _settings_view(f, eff, q)
    return await _page(request, "settings", "settings", admin_id=admin_id, secs=secs, shown=shown,
                       q=q, focus=request.query.get("focus") or "")


def _setting_error(f: Fmt, fld: dict, val: str, err: str) -> str:
    """پیامِ خطای اعتبارسنجی به زبانِ پنل برای حالت‌های رایج؛ بقیه همان متنِ مرجع."""
    label = _fld_label(f, fld)
    if RUNTIME_KEYS[fld["k"]][0] == "int":
        try:
            n = int(val)
        except (TypeError, ValueError):
            return f"{label}: {f.t('st.err.num')}"
        lo, hi = settings_store.BOUNDS.get(fld["k"], (0, None))
        if n < lo:
            return f"{label}: {f.t('st.err.neg')}"
        if hi is not None and n > hi:
            return f"{label}: {f.t('st.err.max', n=f.num(hi))}"
    return f"{label}: {err}"


def _clean_int(raw: str) -> str:
    """رقمِ فارسی/عربی → لاتین، جداکنندهٔ هزارگان و فاصله حذف — صفحه عدد را به رقمِ
    پنل نشان می‌دهد، پس بدونِ این هر ذخیره‌ای «۲۰۰۰» را با «2000» متفاوت می‌دید."""
    return re.sub(r"[\s٬,_]", "", F.ascii_digits(raw or ""))


async def save(request: web.Request) -> web.Response:
    """ذخیرهٔ صفحهٔ تنظیمات — **اول همه را بسنج، بعد بنویس**، با لاگِ تغییرها."""
    _need_admin(request)
    f = Fmt(_PREFS.get()[0])
    form = await request.post()
    store = settings_store.get_store()
    eff = await _effective()
    pending, errors, first_bad = [], [], ""
    for fld in _settings_fields():
        k = fld["k"]
        kind, default = RUNTIME_KEYS[k]
        if kind == "bool":
            val = "on" if form.get(k) == "on" else "off"
            changed = (val == "on") != bool(default)
            before = "on" if eff.get(k) else "off"
        else:
            raw = form.get(k)
            if fld["type"] in PS.SECRET_TYPES:
                # راز در صفحه رندر نمی‌شود، پس «خالی» یعنی «دست نزن» — مگر تیکِ پاک‌کردن.
                if form.get(f"clear__{k}") == "on":
                    raw = ""
                elif not (raw or "").strip():
                    continue
            if raw is None:
                continue                       # فیلدی که فرم نفرستاده دست نمی‌خورد
            val = str(raw).strip()
            if kind == "int":
                val = _clean_int(val)
            err = settings_store.validate_value(k, val)
            if err:
                errors.append(_setting_error(f, fld, val, err))
                first_bad = first_bad or k
                continue
            changed = str(val) != str(default)
            before = "" if eff.get(k) is None else str(eff.get(k))
        pending.append((k, val, changed, before))
    if errors:
        raise _result("/settings", err=" · ".join(errors[:3]), focus=first_bad)
    if store is not None:
        for k, val, changed, before in pending:
            if changed:
                await store.set(k, val)
            else:
                await store.reset(k)
            # تغییرنکرده یعنی `val` همان پیش‌فرض است، پس «بعد» همیشه `val` است.
            if str(before) != str(val):
                await _audit(request, "setting", target=k, **{"from": _audit_value(k, before),
                                                               "to": _audit_value(k, val)})
    # دامنهٔ لینک همین حالا سرتیفیکیت بگیرد، نه با اولین کلیکِ یک کاربر. هر ذخیره
    # (نه فقط تغییرِ همین فیلد): handshakeِ سرتیفیکیتِ موجود ارزان است، و ذخیرهٔ
    # دوباره پس از درست‌کردنِ DNS تنها راهِ «دوباره امتحان کن» از داخلِ پنل است.
    domain = await settings_store.link_domain()
    if domain:
        _schedule_tls_warm(request.app, domain)
    raise _result("/settings", ok="st.saved")


# ── جست‌وجو ───────────────────────────────────────────────────────────────
async def _search(q: str, lang: str) -> list[dict]:
    f = Fmt(lang)
    ql = q.strip().lower()
    if len(ql) < 2:
        return []
    groups = []
    # رنگِ آیکونِ هر نتیجه همان رنگِ صفحه‌ای است که به آن می‌رود (`NAV`): رنگ = مقصد.
    pages = [{"href": href, "icon": icon, "t": f.t("nav." + key), "tint": "t" + tint[1:]}
             for _g, items in NAV for key, href, icon, tint in items
             if ql in f.t("nav." + key).lower() or ql in key]
    groups.append({"label": f.t("srch.pages"), "items": pages[:5]})
    try:
        users = await PD.search_users(q, 5)
    except Exception:  # noqa: BLE001
        users = []
    groups.append({"label": f.t("srch.users"), "more": "/users?" + urlencode({"q": q.strip()}), "items": [
        {"href": f"/users?open={u['id']}", "icon": "user", "tint": _NAV_TINT["users"], "t": f.uname(u),
         "sub": ("@" + u["uname"]) if u.get("uname") and u.get("name") else str(u.get("tg") or ""),
         "mono": not (u.get("uname") and u.get("name"))} for u in users]})
    sets = []
    for fld in _settings_fields():
        label = _fld_label(f, fld)
        if ql in label.lower() or ql in fld["k"]:
            sets.append({"href": f"/settings?focus={fld['k']}", "icon": "sliders-horizontal",
                         "tint": _NAV_TINT["settings"], "t": label, "sub": fld["k"], "mono": True})
    groups.append({"label": f.t("srch.settings"), "more": "/settings?" + urlencode({"q": q.strip()}),
                   "items": sets[:5]})
    bot_lang = lang if lang in await _languages() else i18n_DEFAULT
    texts = []
    for key in _TEXT_KEYS:
        cur = textstore.get_override(bot_lang, key) or _text_default(bot_lang, key)
        # بدونِ تگ: «b» نباید با `<b>` جور شود و پیش‌نمایش نباید تگِ خام نشان دهد.
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cur)).strip()
        if ql in key.lower() or ql in plain.lower():
            texts.append({"href": "/texts?" + urlencode({"q": key, "lang": bot_lang if bot_lang != i18n_DEFAULT else ""}),
                          "icon": "type", "tint": _NAV_TINT["texts"], "t": key,
                          "sub": plain[:70], "mono": False})
            if len(texts) >= 5:
                break
    groups.append({"label": f.t("srch.texts"), "items": texts,
                   "more": "/texts?" + urlencode({"q": q.strip(), "lang": bot_lang if bot_lang != i18n_DEFAULT else ""})})
    return [g for g in groups if g["items"]]


async def api_search(request: web.Request) -> web.Response:
    if not _session_admin(request):
        return web.json_response({"error": "login"}, status=401)
    q = (request.query.get("q") or "").strip()[:80]
    return web.json_response({"groups": await _search(q, _PREFS.get()[0])},
                             headers={"Cache-Control": "no-store"})


async def search_page(request: web.Request) -> web.Response:
    """جست‌وجو بدونِ JS: همان نتایجِ `/api/search` به‌صورتِ یک صفحه."""
    admin_id = _need_admin(request)
    q = (request.query.get("q") or "").strip()[:80]
    groups = await _search(q, _PREFS.get()[0]) if q else []
    return await _page(request, "search", "", admin_id=admin_id, q=q, groups=groups,
                       total=sum(len(g["items"]) for g in groups))


async def moved_health(_: web.Request) -> web.Response:
    raise web.HTTPMovedPermanently("/system")


async def moved_stats(_: web.Request) -> web.Response:
    raise web.HTTPMovedPermanently("/reports")


async def healthz(_: web.Request) -> web.Response:
    return web.Response(text="ok")


# ── چرخهٔ عمر ─────────────────────────────────────────────────────────────
async def _on_startup(app: web.Application) -> None:
    settings_store.init_store(settings.redis_url)
    app["redis"] = aioredis.from_url(settings.redis_url, decode_responses=True)
    # بدونِ این، پس از ری‌استارت (telabzar update) دیکشنریِ متن‌ها/کلیدها خالی می‌ماند و
    # پنل «پیش‌فرض» نشان می‌دهد — و ذخیرهٔ دکمه‌ها از آن نمای کهنه overrideهای واقعی را
    # با پیش‌فرض بازنویسی می‌کند.
    try:
        await textstore.load()
    except Exception as exc:  # noqa: BLE001
        log.warning("panel: textstore preload failed: %s", exc)
    await _mirror_all_cookies(app["redis"])  # آینهٔ کوکی‌ها را با دیسک هماهنگ کن (نودها)
    _schedule_svc_refresh(app)


async def _on_cleanup(app: web.Application) -> None:
    # تسک‌های پس‌زمینه اگر لغو نشوند از خودِ اپ عمر بیشتری می‌کنند.
    for key in (_POT_TASK, _TLS_WARM_TASK, _SVC_TASK):
        task = app.get(key)
        if task is not None and not task.done():
            task.cancel()
    try:
        await app["redis"].aclose()
    except Exception:  # noqa: BLE001
        pass


#: هدرهای امنیتیِ هر پاسخ. `Referrer-Policy` **بخشی از رفعِ نشتِ توکنِ join است**:
#: لاگِ تولید نشان داد از ۹ خطِ حاویِ `tok=`، هشت‌تا `Referer` داشتند.
_SECURITY_HEADERS = {
    "Referrer-Policy": "no-referrer",
    # پنل قابلِ iframe شدن بود؛ یک کلیکِ فریب‌خورده روی «بلاکِ کاربر» کافی بود.
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    # پنل **هیچ منبعِ خارجی ندارد** (فونت و آیکون از /static) و از بازطراحیِ ۲۰۲۶-۱۰
    # **هیچ اسکریپتِ درون‌خطی** هم ندارد: همهٔ JS در `/static/js/panel.js` است و داده‌ی
    # صفحه با `data-*` و `<script type="application/json">` (که اجرا نمی‌شود) می‌رسد.
    # پس `script-src 'self'` بدونِ `unsafe-inline`. `style-src` هنوز `unsafe-inline`
    # دارد چون عرضِ نوارها و رنگِ تکه‌ها `style="…"`ِ درون‌خطی‌اند.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}

#: HSTS فقط روی HTTPS. روی HTTPِ ساده بی‌اثر است و بدتر: مرورگر را برای همان هاست
#: به HTTPSِ ناموجود قفل می‌کند (نصبِ بی‌دامنه).
_HSTS = "max-age=31536000; includeSubDomains"


@web.middleware
async def _security_headers(request: web.Request, handler):
    """هدرها روی **هر** پاسخ می‌نشینند، از جمله ریدایرکت‌ها و خطاها (`HTTPFound`
    استثناست، و جریانِ نودها دقیقاً از ریدایرکت ساخته شده)."""
    headers = dict(_SECURITY_HEADERS)
    if _https(request):
        headers["Strict-Transport-Security"] = _HSTS
    try:
        resp = await handler(request)
    except web.HTTPException as exc:
        exc.headers.update(headers)
        raise
    resp.headers.update(headers)
    return resp


_COMPRESS_TYPES = frozenset({"text/html", "application/json", "text/plain"})


@web.middleware
async def _compress(request: web.Request, handler):
    """HTML/JSONِ بزرگ‌تر از ۱ کیلوبایت gzip می‌شود (صفحهٔ متن‌ها ~۲۰۰ کیلوبایت است)."""
    resp = await handler(request)
    try:
        if (isinstance(resp, web.Response) and resp.content_type in _COMPRESS_TYPES
                and "Content-Encoding" not in resp.headers
                and "gzip" in request.headers.get("Accept-Encoding", "")
                and resp.body is not None and len(resp.body) > 1024):
            resp.enable_compression(web.ContentCoding.gzip)
            resp.headers["Vary"] = "Accept-Encoding"
    except Exception:  # noqa: BLE001  — فشرده‌سازی بهینه‌سازی است، نه شرطِ پاسخ
        pass
    return resp


#: مسیرهای POSTی که **مرورگر** صدایشان نمی‌زند و کوکیِ نشست هم نمی‌خواهند:
#: `/node/join` را نصب‌کنندهٔ نود با curl و یک توکنِ یک‌بارمصرف در بدنه صدا می‌زند.
_CSRF_EXEMPT = frozenset({"/node/join"})
_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _origin_netlocs(request: web.Request) -> set[str]:
    """مبدأهای قابلِ قبول: همان هاستی که درخواست به آن آمده، به‌علاوهٔ `ADMIN_BASE`
    (پروکسیِ معکوسی که `Host` را بازنویسی می‌کند)."""
    out = {request.host.lower()}
    base = settings.admin_base or ""
    if base:
        out.add(urlsplit(base).netloc.lower())
    return out


@web.middleware
async def _csrf_guard(request: web.Request, handler):
    """POSTِ میان‌سایتی را رد می‌کند — **سایت** نه فقط **دامنه**.

    `SameSite=Lax` مرزش «site» است نه «origin»: گیت‌وی و پنل روی یک هاست‌اند، پس
    هم‌سایت‌اند و کوکی همراهِ هر POSTی که از صفحه‌ای روی گیت‌وی بیاید فرستاده می‌شد.
    قاعده: اگر مرورگر `Sec-Fetch-Site` فرستاد فقط `same-origin`؛ وگرنه اگر `Origin`
    فرستاد باید همین هاست باشد؛ اگر هیچ‌کدام نبود (curl) مجاز است — چنین کلاینتی کوکیِ
    نشستِ قربانی را ندارد.
    """
    if request.method in _UNSAFE and request.path not in _CSRF_EXEMPT:
        sfs = request.headers.get("Sec-Fetch-Site", "").lower()
        origin = request.headers.get("Origin")
        if sfs:
            ok = sfs == "same-origin"
        elif origin is not None:
            ok = urlsplit(origin).netloc.lower() in _origin_netlocs(request)
        else:
            ok = True
        if not ok:
            log.warning("refused cross-site %s %s (sec-fetch-site=%r origin=%r)",
                        request.method, request.path, sfs, origin)
            raise web.HTTPForbidden(text="cross-site request refused")
    return await handler(request)


def build_app() -> web.Application:
    app = web.Application(middlewares=[_compress, _security_headers, _csrf_guard, _panel_prefs],
                          client_max_size=2 * 1024 * 1024)
    add = app.router.add_get
    post = app.router.add_post
    add("/", dashboard)
    add("/activity", activity)
    add("/reports", reports)
    add("/users", users_page)
    post("/users/block", users_block)
    add("/cookies", cookies_page)
    post("/cookies/add", cookies_add)
    post("/cookies/replace", cookies_replace)
    post("/cookies/delete", cookies_delete)
    post("/cookies/unfreeze", cookies_unfreeze)
    post("/cookies/resync", cookies_resync)
    post("/cookies/identity", cookies_identity)
    post("/cookies/toggle", cookies_toggle)
    post("/cookies/cooldown", cookies_cooldown)
    add("/nodes", nodes_page)
    post("/nodes/add", nodes_add)
    post("/nodes/remove", nodes_remove)
    add("/system", system_page)
    add("/texts", texts_page)
    post("/texts/save", texts_save)
    post("/texts/reset", texts_reset)
    add("/buttons", buttons_page)
    post("/buttons/save", buttons_save)
    post("/buttons/reset", buttons_reset)
    add("/langs", langs_page)
    add("/langs/export", langs_export)
    post("/langs/import", langs_import)
    post("/langs/delete", langs_delete)
    add("/settings", settings_page)
    post("/settings/save", save)
    post("/save", save)
    add("/search", search_page)
    add("/api/search", api_search)
    add("/health", moved_health)
    add("/stats", moved_stats)
    add("/login", login)
    post("/auth/request", auth_request)
    post("/auth/verify", auth_verify)
    # فقط POST (فرمِ منوی کاربر). GETِ خروج یعنی هر `<img src=…/logout>` در هر سایتی
    # ادمین را بیرون می‌انداخت — گاردِ CSRF فقط روی POST است.
    post("/logout", logout)
    add("/prefs", prefs)
    post("/node/join", node_join)              # عمومی (توکن گِیت)
    add("/node/install.sh", node_install)      # عمومی
    add("/node/peers", node_peers)             # گِیت با NODE_SECRET (wg-sync)
    add("/healthz", healthz)
    app.router.add_get("/tls/ask", tls_ask)    # عمومی — گیتِ صدورِ سرتیفیکیتِ Caddy
    add("/static/{path:.+}", static_file)
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
