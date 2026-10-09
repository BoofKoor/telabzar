"""داده‌ی صفحه‌های پنل: داشبورد، فعالیت‌ها، گزارش‌ها و کاربران.

پنل (`admin_web`) فقط **رندر** می‌کند؛ هر عدد از همین‌جا می‌آید. این ماژول به
jinja2/cryptography وابسته نیست، پس jobِ اصلیِ تست می‌تواند آن را import کند (همان
قاعدهٔ `panel_fmt` و `langpack`).

**تعریفِ اعداد** — هر کارتِ پنل یکی از این‌ها را نشان می‌دهد و تعریف فقط همین‌جاست:

* **آپلود** = ردیفِ `File` با `source` نه `dl` و نه `op` (آپلودها `source` تهی دارند).
  خروجیِ عملیات‌ها از ۲۰۲۶-۱۰ `source="op"` می‌گیرد؛ خروجی‌های **قدیمی‌تر** `source`
  تهی دارند و از آپلود تفکیک‌پذیر نیستند، پس در بازه‌های پیش از آن تاریخ کمی بیش‌شماری
  دارند. مهم نیست چون کم‌اند، ولی صادقانه این‌جا نوشته شد.
* **از لینک** = `File.source == "dl"` (تحویلِ تک‌فایل، از کش هم). آلبوم ردیفِ `File` ندارد.
* **کاربرِ فعال** = مالکِ متمایزِ هر کدام از: `File`، `DownloadEvent`، `Job`(⋈ `File`)
  در همان بازه.
* **موفقیتِ دانلود** = `ok / (ok + fail)` از `download_events`. ردِ سیاستی (`blocked`)،
  ردِ سقف (`refused`) و لغو شکستِ سرویس نیستند و در مخرج نمی‌آیند. این جدول از
  ۲۰۲۶-۱۰ پر می‌شود؛ وقتی شروعِ بازه را پوشش نمی‌دهد، صفحه «از تاریخِ …» می‌گوید و
  مقایسه با دورهٔ قبل را نشان نمی‌دهد.
* **کارِ گیرکرده** = `queued` بیش از ۳۰ دقیقه، یا `running` بیش از بلندترین
  `job_timeout` به‌علاوهٔ حاشیه (`STUCK_RUNNING`).

**زمان:** مرزِ سطل‌ها به ساعتِ **تهران** است (روز از نیمه‌شبِ تهران، هفته از شنبه) ولی
پیش از رفتن به SQL به **UTC** تبدیل می‌شود. SQLiteِ تست‌ها ساعتِ دیواریِ UTC را بی
منطقهٔ زمانی ذخیره می‌کند، پس مقایسه فقط با مقدارِ UTC درست است؛ Postgres با هر دو.

خروجی‌ها JSON‌پذیرند (زمان = ثانیهٔ epoch)، تا پنل بتواند آن‌ها را چند ثانیه در Redis
کش کند و برای هر زبان جدا قالب بزند.
"""
from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from . import panel_fmt as F
from .db import Sessionmaker
from .models import AdminAction, DownloadEvent, File, Job, Language, User
from .panel_i18n import pt

UTC = timezone.utc

#: بازه‌های داشبورد و گزارش‌ها.
DASH_RANGES = ("24h", "7d", "30d", "90d")
REPORT_RANGES = ("7d", "30d", "90d", "all")

#: پلتفرم‌هایی که رنگِ خودشان را دارند؛ بقیه در نمودار زیرِ «سایر» جمع می‌شوند
#: (رنگ هویتِ موجودیت است، و رنگِ نهم یعنی دو موجودیت با یک رنگ).
PLATS = ("youtube", "instagram", "twitter", "tiktok", "soundcloud", "spotify")
PLAT_COLOR = {"youtube": "var(--c1)", "instagram": "var(--c2)", "twitter": "var(--c3)",
              "tiktok": "var(--c4)", "soundcloud": "var(--c5)", "spotify": "var(--c6)",
              "other": "var(--c0)"}
PLAT_ICON = {"youtube": "video", "instagram": "image", "twitter": "message-square-text",
             "tiktok": "music", "soundcloud": "radio", "spotify": "music",
             "pinterest": "image", "other": "globe"}
KINDS = ("video", "audio", "image", "document", "pdf", "archive", "app")
KIND_COLOR = {"video": "var(--c1)", "audio": "var(--c2)", "image": "var(--c3)",
              "document": "var(--c4)", "pdf": "var(--c5)", "archive": "var(--c6)",
              "app": "var(--c0)"}
KIND_ICON = {"video": "file-video", "audio": "file-audio", "image": "file-image",
             "document": "file-text", "pdf": "file-text", "archive": "folder-archive",
             "app": "package"}

#: کارِ `queued` بیش از این «گیرکرده» است.
STUCK_QUEUED = timedelta(minutes=30)
#: کارِ `running` بیش از بلندترین `job_timeout` (۵۴۰۰ ثانیهٔ دانلود؛ پردازش ۲۰۰۰) به‌علاوهٔ
#: حاشیه. کمتر از این یعنی «کند»، نه «مرده».
STUCK_RUNNING = timedelta(seconds=5400 + 600)

PER_PAGE = 25
_UPLOAD_EXCLUDE = ("dl", "op")


# ── زمان ──────────────────────────────────────────────────────────────────────
def aware(dt: datetime | None) -> datetime | None:
    """زمانِ ساده (SQLite) → آگاه با فرضِ UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def ts(dt: datetime | None) -> float | None:
    dt = aware(dt)
    return dt.timestamp() if dt else None


def from_ts(x: float | None) -> datetime | None:
    return datetime.fromtimestamp(x, UTC) if x is not None else None


def _bind(dt: datetime) -> datetime:
    """مقدارِ مقایسه برای SQL — همیشه UTC (توضیحِ سرِ ماژول)."""
    return aware(dt).astimezone(UTC)


def utc_today(now: datetime | None = None) -> str:
    """روزِ UTC با قالبِ کلیدهای سقفِ ربات (`dlq:cnt:<tg>:<YYYYMMDD>`)."""
    return (aware(now) or datetime.now(UTC)).strftime("%Y%m%d")


@dataclass
class Range:
    """یک بازهٔ نمودار: سطل‌های پشتِ‌هم از `starts[0]` تا `end` (اکنون).

    سطلِ آخر همیشه ناقص است (تا همین لحظه). `prev_start` شروعِ دورهٔ قبلی با **همان
    طول** است، نه همان تعداد سطلِ کامل — وگرنه دورهٔ جاری (ناقص) با دورهٔ قبلِ کامل
    مقایسه می‌شد و هر دلتا به‌دروغ منفی بود.
    """

    key: str
    unit: str                    # hour | day | week
    starts: list[datetime]       # شروعِ هر سطل (UTCِ آگاه)
    end: datetime
    prev_start: datetime | None  # None = مقایسه معنا ندارد («از ابتدا»)

    @property
    def start(self) -> datetime:
        return self.starts[0]

    def __len__(self) -> int:
        return len(self.starts)

    @property
    def days(self) -> float:
        return max(1e-9, (self.end - self.start).total_seconds() / 86400)

    def index(self, dt: datetime | None) -> int:
        """اندیسِ سطلِ این زمان، یا -۱ اگر بیرونِ بازه است."""
        dt = aware(dt)
        if dt is None or dt < self.starts[0] or dt > self.end:
            return -1
        return bisect.bisect_right(self.starts, dt) - 1

    def bucket_end(self, i: int) -> datetime:
        return self.starts[i + 1] if i + 1 < len(self.starts) else self.end

    def in_cur(self, dt: datetime | None) -> bool:
        dt = aware(dt)
        return dt is not None and self.start <= dt <= self.end

    def in_prev(self, dt: datetime | None) -> bool:
        dt = aware(dt)
        return (self.prev_start is not None and dt is not None
                and self.prev_start <= dt < self.start)


def make_range(key: str, now: datetime | None = None,
               first: datetime | None = None) -> Range:
    """سطل‌های یک بازه، هم‌تراز با ساعت/روز/هفتهٔ تهران.

    `24h` = ۲۴ سطلِ ساعتی · `7d`/`30d` = سطلِ روزانه · `90d` = ۱۳ هفته از شنبه ·
    `all` (گزارش‌ها) = از اولین داده (`first`)، روزانه اگر ≤۳۱ روز وگرنه هفتگی و حداکثر
    ۱۰۴ هفته.
    """
    now = aware(now) or datetime.now(UTC)
    loc = now.astimezone(F.TEHRAN)
    day0 = loc.replace(hour=0, minute=0, second=0, microsecond=0)

    def week_of(d: datetime) -> datetime:
        return d - timedelta(days=F.weekday_index(d.date()))

    if key == "24h":
        h0 = loc.replace(minute=0, second=0, microsecond=0)
        starts, unit = [h0 - timedelta(hours=23 - i) for i in range(24)], "hour"
    elif key in ("7d", "30d"):
        n = 7 if key == "7d" else 30
        starts, unit = [day0 - timedelta(days=n - 1 - i) for i in range(n)], "day"
    elif key == "90d":
        w0 = week_of(day0)
        starts, unit = [w0 - timedelta(weeks=12 - i) for i in range(13)], "week"
    else:
        f0 = (aware(first) or now).astimezone(F.TEHRAN).replace(
            hour=0, minute=0, second=0, microsecond=0)
        span = (day0 - f0).days + 1
        if span <= 31:
            n = max(7, span)
            starts, unit = [day0 - timedelta(days=n - 1 - i) for i in range(n)], "day"
        else:
            w0 = week_of(day0)
            weeks = min(104, (w0 - week_of(f0)).days // 7 + 1)
            starts, unit = [w0 - timedelta(weeks=weeks - 1 - i) for i in range(weeks)], "week"
    starts = [s.astimezone(UTC) for s in starts]
    prev = None if key == "all" else starts[0] - (now - starts[0])
    return Range(key, unit, starts, now, prev)


def bucket_label(R: Range, i: int, lang: str, long: bool = False) -> str:
    """برچسبِ محورِ x (کوتاه) یا عنوانِ tooltip/ردیفِ جدول (`long`)."""
    s = R.starts[i]
    if R.unit == "hour":
        if not long:
            return F.hm(s, lang)
        sep = "، " if F.is_fa(lang) else ", "
        return f"{F.day_short(s, lang)}{sep}{F.hm(s, lang)}–{F.hm(R.bucket_end(i), lang)}"
    if R.unit == "week":
        if not long:
            return F.day_short(s, lang)
        last = R.bucket_end(i) - timedelta(seconds=1)
        return pt(lang, "d.week", a=F.day_short(s, lang), b=F.day_short(last, lang))
    return F.day_long(s, lang) if long else F.day_short(s, lang)


def partial_note(R: Range, i: int, lang: str) -> str:
    return pt(lang, "d.partial", t=F.hm(R.end, lang)) if i == len(R) - 1 else ""


def column_spec(R: Range, series: list[dict], lang: str, *, aria: str = "",
                height: int | None = None, tall: bool = False, mini: bool = False,
                notes: bool = True) -> dict:
    """مشخصاتِ نمودارِ ستونی برای `panel.js` — همه‌چیز **پیش‌قالب‌شده** به زبانِ پنل.

    `series` = `[{"label", "color", "values": [...]}]`؛ این تابع `fmt` (مقدارِ قالب‌خورده‌ی
    هر سطل) و `totals` را اضافه می‌کند. سطلِ آخر هاشور می‌خورد (ناقص است).
    """
    n = len(R)
    out = []
    for s in series:
        vals = [float(v or 0) for v in s["values"]]
        fmt = s.get("fmt_fn") or (lambda v: F.num(v, lang))
        out.append({"label": s["label"], "color": s["color"], "values": vals,
                    "fmt": [fmt(v) for v in vals]})
    totals = [sum(s["values"][i] for s in out) for i in range(n)]
    spec = {"labels": [bucket_label(R, i, lang) for i in range(n)],
            "tips": [bucket_label(R, i, lang, long=True) for i in range(n)],
            "partial": [i == n - 1 for i in range(n)],
            "series": out, "totals": [F.num(v, lang) for v in totals], "aria": aria}
    if notes:
        spec["notes"] = [partial_note(R, i, lang) for i in range(n)]
    if height:
        spec["height"] = height
    if tall:
        spec["tall"] = True
    if mini:
        spec["mini"] = True
    return spec


def fold_platform(p: str | None) -> str:
    return p if p in PLATS else "other"


def fold_kind(k: str | None) -> str:
    if k in KINDS:
        return k
    return {"voice": "audio", "animation": "video"}.get(k or "", "document")


def _p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * 0.95))]


def _dur(created: datetime | None, finished: datetime | None) -> float | None:
    created, finished = aware(created), aware(finished)
    if not created or not finished:
        return None
    return max(0.0, (finished - created).total_seconds())


def _is_upload(source: str | None) -> bool:
    return source not in _UPLOAD_EXCLUDE


def user_ref(u: User | None, owner_id: int | None = None, tg: int | None = None) -> dict:
    """کاربر برای نمایش: شناسه، شناسهٔ تلگرام، نام، یوزرنیم."""
    if u is None:
        return {"id": owner_id, "tg": tg, "name": "", "uname": "", "known": False}
    return {"id": u.id, "tg": u.tg_user_id, "name": u.full_name or "",
            "uname": u.username or "", "known": True, "blocked": bool(u.is_blocked)}


def _like(col, q: str):
    return col.icontains(q, autoescape=True)


def _norm_q(q: str | None) -> str:
    return F.ascii_digits((q or "").strip())[:80]


# ── داشبورد ───────────────────────────────────────────────────────────────────
async def dashboard(key: str, now: datetime | None = None) -> dict:
    """همهٔ اعدادِ داشبورد برای یک بازه (JSON‌پذیر)."""
    key = key if key in DASH_RANGES else "7d"
    R = make_range(key, now)
    lo = _bind(R.prev_start or R.start)
    async with Sessionmaker() as s:
        total_users = await s.scalar(select(func.count(User.id))) or 0
        user_rows = (await s.execute(
            select(User.created_at).where(User.created_at >= lo))).scalars().all()
        files = (await s.execute(
            select(File.created_at, File.source, File.owner_id)
            .where(File.created_at >= lo))).all()
        events = (await s.execute(
            select(DownloadEvent.created_at, DownloadEvent.platform,
                   DownloadEvent.outcome, DownloadEvent.owner_id)
            .where(DownloadEvent.created_at >= lo))).all()
        ev_first = aware(await s.scalar(select(func.min(DownloadEvent.created_at))))
        first_user = aware(await s.scalar(select(func.min(User.created_at))))
        jobs = (await s.execute(
            select(Job.created_at, Job.finished_at, Job.op, Job.status, File.owner_id)
            .join(File, File.id == Job.file_id)
            .where(Job.created_at >= lo))).all()

    act = [[0, 0] for _ in range(len(R))]
    active = [set(), set()]          # [جاری, قبلی]
    files_n = {"dl": [0, 0], "up": [0, 0]}
    for created, source, owner in files:
        slot = 0 if R.in_cur(created) else 1 if R.in_prev(created) else None
        if slot is None:
            continue
        kind = "dl" if source == "dl" else "up" if _is_upload(source) else None
        if kind:
            files_n[kind][slot] += 1
            if slot == 0:
                i = R.index(created)
                act[i][0 if kind == "dl" else 1] += 1
        active[slot].add(owner)
    ev = {"ok": [0, 0], "fail": [0, 0]}
    plat: dict[str, dict[str, int]] = {}
    for created, platform, outcome, owner in events:
        slot = 0 if R.in_cur(created) else 1 if R.in_prev(created) else None
        if slot is None:
            continue
        if owner is not None:
            active[slot].add(owner)
        if outcome in ("ok", "fail"):
            ev[outcome][slot] += 1
            if slot == 0:
                p = plat.setdefault(fold_platform(platform), {"ok": 0, "fail": 0})
                p[outcome] += 1
    ops: dict[str, dict] = {}
    jobs_n, jobs_fail = 0, 0
    for created, finished, op, status, owner in jobs:
        slot = 0 if R.in_cur(created) else 1 if R.in_prev(created) else None
        if slot is None:
            continue
        active[slot].add(owner)
        if slot != 0 or status not in ("done", "failed", "cancelled"):
            continue
        jobs_n += 1
        o = ops.setdefault(op, {"op": op, "n": 0, "fail": 0, "durs": []})
        o["n"] += 1
        if status == "failed":
            o["fail"] += 1
            jobs_fail += 1
        d = _dur(created, finished)
        if d is not None and status == "done":
            o["durs"].append(d)
    new = [sum(1 for c in user_rows if R.in_cur(c)), sum(1 for c in user_rows if R.in_prev(c))]
    op_rows = []
    for o in sorted(ops.values(), key=lambda x: -x["n"]):
        durs = o.pop("durs")
        o["avg"] = sum(durs) / len(durs) if durs else None
        o["p95"] = _p95(durs)
        op_rows.append(o)
    active_n = [len({x for x in a if x is not None}) for a in active]
    return {
        "key": key, "end": ts(R.end),
        # اولین کاربر: مقایسه با دورهٔ قبل فقط وقتی معنا دارد که آن دوره کامل ثبت شده باشد
        "first": ts(first_user),
        "users": total_users,
        "active": active_n, "new": new, "files": files_n, "ev": ev,
        "ev_first": ts(ev_first),
        "act": act,
        "plat": sorted(({"p": k, **v} for k, v in plat.items()),
                       key=lambda x: -(x["ok"] + x["fail"])),
        "ops": op_rows, "jobs": [jobs_n, jobs_fail],
    }


def ev_coverage(payload: dict, R: Range) -> tuple[bool, bool, datetime | None]:
    """(جاری را کامل پوشش می‌دهد؟, قبلی را؟, از کِی ثبت شده).

    لاگِ دانلود از روزِ استقرارِ این نسخه پر می‌شود؛ پیش از آن «صفر شکست» یعنی «ثبت نشده».
    """
    first = from_ts(payload.get("ev_first"))
    if first is None:
        return False, False, None
    cur = first <= R.start
    prev = R.prev_start is not None and first <= R.prev_start
    return cur, prev, (None if cur else first)


async def recent_activity(limit: int = 6, owner_id: int | None = None,
                          since: datetime | None = None) -> list[dict]:
    """آخرین دانلودها و عملیات‌ها، با هم و به ترتیبِ زمان."""
    async with Sessionmaker() as s:
        eq = (select(DownloadEvent, User)
              .outerjoin(User, User.id == DownloadEvent.owner_id)
              .order_by(DownloadEvent.created_at.desc(), DownloadEvent.id.desc()).limit(limit))
        jq = (select(Job, File, User).join(File, File.id == Job.file_id)
              .outerjoin(User, User.id == File.owner_id)
              .where(Job.status != "queued")
              .order_by(Job.created_at.desc(), Job.id.desc()).limit(limit))
        if owner_id is not None:
            eq = eq.where(DownloadEvent.owner_id == owner_id)
            jq = jq.where(File.owner_id == owner_id)
        if since is not None:
            eq = eq.where(DownloadEvent.created_at >= _bind(since))
            jq = jq.where(Job.created_at >= _bind(since))
        evs = (await s.execute(eq)).all()
        jbs = (await s.execute(jq)).all()
    out = [event_row(e, u) for e, u in evs] + [job_row(j, f, u) for j, f, u in jbs]
    out.sort(key=lambda x: -(x["t"] or 0))
    return out[:limit]


def event_row(e: DownloadEvent, u: User | None) -> dict:
    return {"type": "dl", "id": e.id, "t": ts(e.created_at),
            "user": user_ref(u, e.owner_id, e.tg_user_id),
            "platform": e.platform or "other", "url": e.url or "", "outcome": e.outcome,
            "error_class": e.error_class or "", "error": e.error or "",
            "kind": e.kind or "", "size": e.size, "height": e.height,
            "duration": e.duration, "items": e.items,
            "took": (e.took_ms / 1000) if e.took_ms is not None else None,
            "cached": bool(e.cached), "cookie": e.cookie or "", "exit": e.exit or "",
            "attempts": e.attempts, "selector": e.selector or "", "engine": e.engine or "",
            "phase": e.phase or ""}


def job_row(j: Job, f: File | None, u: User | None) -> dict:
    return {"type": "job", "id": j.id, "t": ts(j.created_at),
            "user": user_ref(u, f.owner_id if f else None),
            "op": j.op, "status": j.status, "error": j.error or "",
            "file": (f.name if f else "") or "", "kind": (f.kind if f else "") or "",
            "size": f.size if f else None,
            "took": _dur(j.created_at, j.finished_at),
            "finished": ts(j.finished_at)}


def pool_rows(accounts: list[dict], order: list[str]) -> list[dict]:
    """استخرِ کوکی به تفکیکِ پلتفرم برای کارتِ داشبورد (سالم/هشدار/استراحت/بد/خاموش)."""
    bucket = {"healthy": "ok", "unproven": "warn", "suspect": "warn", "cooldown": "rest",
              "invalid": "bad", "frozen": "bad", "disabled": "off"}
    by: dict[str, dict] = {}
    for a in accounts:
        p = a.get("platform") or "other"
        c = by.setdefault(p, {"p": p, "ok": 0, "warn": 0, "rest": 0, "bad": 0, "off": 0, "n": 0})
        c[bucket.get(a.get("status"), "warn")] += 1
        c["n"] += 1
    rows = [by.pop(p) for p in order if p in by] + sorted(by.values(), key=lambda x: x["p"])
    for r in rows:
        r["ready"] = r["ok"] + r["warn"]
    return rows


# ── فعالیت‌ها ──────────────────────────────────────────────────────────────────
DL_STATUS = {"done": "ok", "failed": "fail", "blocked": "blocked",
             "refused": "refused", "cancelled": "cancelled"}
JOB_STATUS = ("done", "failed", "running", "queued", "cancelled")


def _page(page) -> int:
    try:
        return max(1, int(F.ascii_digits(str(page))))
    except (TypeError, ValueError):
        return 1


async def downloads_list(days: int, status: str, platform: str, q: str, page,
                         now: datetime | None = None, per: int = PER_PAGE) -> dict:
    now = aware(now) or datetime.now(UTC)
    lo = _bind(now - timedelta(days=days))
    conds = [DownloadEvent.created_at >= lo]
    if status in DL_STATUS:
        conds.append(DownloadEvent.outcome == DL_STATUS[status])
    if platform:
        conds.append(DownloadEvent.platform == platform)
    ql = _norm_q(q).lstrip("@")
    if ql:
        alts = [_like(DownloadEvent.url, ql), _like(User.full_name, ql), _like(User.username, ql)]
        if ql.isdigit() and len(ql) <= 19:
            alts.append(DownloadEvent.tg_user_id == int(ql))
        conds.append(or_(*alts))
    where = and_(*conds)
    page = _page(page)
    async with Sessionmaker() as s:
        base = select(DownloadEvent.id).outerjoin(User, User.id == DownloadEvent.owner_id).where(where)
        by_outcome = dict((await s.execute(
            select(DownloadEvent.outcome, func.count(DownloadEvent.id))
            .outerjoin(User, User.id == DownloadEvent.owner_id).where(where)
            .group_by(DownloadEvent.outcome))).all())
        cached = await s.scalar(select(func.count()).select_from(
            base.where(DownloadEvent.cached.is_(True)).subquery())) or 0
        total = sum(by_outcome.values())
        pages = max(1, (total + per - 1) // per)
        page = min(page, pages)
        rows = (await s.execute(
            select(DownloadEvent, User).outerjoin(User, User.id == DownloadEvent.owner_id)
            .where(where).order_by(DownloadEvent.created_at.desc(), DownloadEvent.id.desc())
            .limit(per).offset((page - 1) * per))).all()
        plats = [p for (p,) in (await s.execute(
            select(DownloadEvent.platform).where(DownloadEvent.created_at >= lo)
            .group_by(DownloadEvent.platform))).all() if p]
    return {"rows": [event_row(e, u) for e, u in rows], "total": total, "page": page,
            "pages": pages, "per": per, "by": by_outcome, "cached": cached,
            "platforms": sorted(plats)}


async def jobs_list(days: int, status: str, op: str, q: str, page,
                    now: datetime | None = None, per: int = PER_PAGE) -> dict:
    now = aware(now) or datetime.now(UTC)
    lo = _bind(now - timedelta(days=days))
    conds = [Job.created_at >= lo]
    if status in JOB_STATUS:
        conds.append(Job.status == status)
    if op:
        conds.append(Job.op == op)
    ql = _norm_q(q).lstrip("@#")
    if ql:
        alts = [_like(File.name, ql), _like(User.full_name, ql), _like(User.username, ql)]
        if ql.isdigit() and len(ql) <= 19:
            alts += [User.tg_user_id == int(ql), Job.id == int(ql)]
        conds.append(or_(*alts))
    where = and_(*conds)
    page = _page(page)
    async with Sessionmaker() as s:
        joined = (select(Job.status, func.count(Job.id)).join(File, File.id == Job.file_id)
                  .outerjoin(User, User.id == File.owner_id).where(where).group_by(Job.status))
        by_status = dict((await s.execute(joined)).all())
        total = sum(by_status.values())
        pages = max(1, (total + per - 1) // per)
        page = min(page, pages)
        rows = (await s.execute(
            select(Job, File, User).join(File, File.id == Job.file_id)
            .outerjoin(User, User.id == File.owner_id).where(where)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(per).offset((page - 1) * per))).all()
        ops = [o for (o,) in (await s.execute(
            select(Job.op).where(Job.created_at >= lo).group_by(Job.op))).all() if o]
    return {"rows": [job_row(j, f, u) for j, f, u in rows], "total": total, "page": page,
            "pages": pages, "per": per, "by": by_status, "ops": sorted(ops)}


async def admin_log(q: str, page, per: int = PER_PAGE) -> dict:
    ql = _norm_q(q)
    conds = []
    if ql:
        conds.append(or_(_like(AdminAction.action, ql), _like(AdminAction.target, ql),
                         _like(AdminAction.ip, ql)))
    page = _page(page)
    async with Sessionmaker() as s:
        cq = select(func.count(AdminAction.id))
        if conds:
            cq = cq.where(*conds)
        total = await s.scalar(cq) or 0
        pages = max(1, (total + per - 1) // per)
        page = min(page, pages)
        rq = select(AdminAction).order_by(AdminAction.created_at.desc(), AdminAction.id.desc())
        if conds:
            rq = rq.where(*conds)
        rows = (await s.execute(rq.limit(per).offset((page - 1) * per))).scalars().all()
        admin_ids = {r.admin_id for r in rows if r.admin_id}
        names = {}
        if admin_ids:
            for u in (await s.execute(select(User).where(User.tg_user_id.in_(admin_ids)))).scalars():
                names[u.tg_user_id] = user_ref(u)
    out = [{"id": r.id, "t": ts(r.created_at), "action": r.action, "target": r.target or "",
            "detail": r.detail or {}, "ip": r.ip or "",
            "admin": names.get(r.admin_id) or {"tg": r.admin_id, "name": "", "uname": ""}}
           for r in rows]
    return {"rows": out, "total": total, "page": page, "pages": pages, "per": per}


async def activity_counts(days: int, now: datetime | None = None) -> dict:
    now = aware(now) or datetime.now(UTC)
    lo = _bind(now - timedelta(days=days))
    async with Sessionmaker() as s:
        dl = await s.scalar(select(func.count(DownloadEvent.id))
                            .where(DownloadEvent.created_at >= lo)) or 0
        ops = await s.scalar(select(func.count(Job.id)).where(Job.created_at >= lo)) or 0
        log_n = await s.scalar(select(func.count(AdminAction.id))) or 0
    return {"dl": dl, "ops": ops, "log": log_n}


async def dl_event(event_id: int) -> dict | None:
    async with Sessionmaker() as s:
        row = (await s.execute(select(DownloadEvent, User)
                               .outerjoin(User, User.id == DownloadEvent.owner_id)
                               .where(DownloadEvent.id == event_id))).first()
    return event_row(*row) if row else None


async def job_detail(job_id: int) -> dict | None:
    async with Sessionmaker() as s:
        row = (await s.execute(select(Job, File, User).join(File, File.id == Job.file_id)
                               .outerjoin(User, User.id == File.owner_id)
                               .where(Job.id == job_id))).first()
    return job_row(*row) if row else None


# ── هشدارهای کارِ گیرکرده ─────────────────────────────────────────────────────
async def stuck_jobs(now: datetime | None = None) -> dict:
    """کارهای گیرکرده: تعداد و قدیمی‌ترین — همان چیزی که «در صف»ِ ساده پنهان می‌کرد."""
    now = aware(now) or datetime.now(UTC)
    async with Sessionmaker() as s:
        q_cut = _bind(now - STUCK_QUEUED)
        r_cut = _bind(now - STUCK_RUNNING)
        cond = or_(and_(Job.status == "queued", Job.created_at < q_cut),
                   and_(Job.status == "running", Job.created_at < r_cut))
        n = await s.scalar(select(func.count(Job.id)).where(cond)) or 0
        oldest = aware(await s.scalar(select(func.min(Job.created_at)).where(cond)))
        queued = await s.scalar(select(func.count(Job.id)).where(Job.status == "queued")) or 0
        running = await s.scalar(select(func.count(Job.id)).where(Job.status == "running")) or 0
    return {"n": n, "oldest": ts(oldest), "queued": queued, "running": running}


# ── کاربران ───────────────────────────────────────────────────────────────────
USER_SORTS = ("seen", "joined", "files")


async def _active_ids(s, since: datetime) -> set[int]:
    lo = _bind(since)
    ids = set((await s.execute(select(File.owner_id).where(File.created_at >= lo)
                              .group_by(File.owner_id))).scalars())
    ids |= set((await s.execute(select(DownloadEvent.owner_id)
                               .where(DownloadEvent.created_at >= lo)
                               .group_by(DownloadEvent.owner_id))).scalars())
    ids |= set((await s.execute(select(File.owner_id).join(Job, Job.file_id == File.id)
                               .where(Job.created_at >= lo).group_by(File.owner_id))).scalars())
    ids.discard(None)
    return ids


async def users_list(q: str, status: str, lang: str, sort: str, page,
                     now: datetime | None = None, per: int = PER_PAGE) -> dict:
    now = aware(now) or datetime.now(UTC)
    conds = []
    if status == "blocked":
        conds.append(User.is_blocked.is_(True))
    elif status == "active":
        conds.append(User.is_blocked.is_not(True))
    if lang:
        conds.append(User.lang == lang)
    ql = _norm_q(q).lstrip("@")
    if ql:
        alts = [_like(User.full_name, ql), _like(User.username, ql)]
        if ql.isdigit() and len(ql) <= 19:
            alts.append(User.tg_user_id == int(ql))
        conds.append(or_(*alts))
    sort = sort if sort in USER_SORTS else "seen"
    page = _page(page)
    async with Sessionmaker() as s:
        total_all = await s.scalar(select(func.count(User.id))) or 0
        blocked_all = await s.scalar(select(func.count(User.id))
                                     .where(User.is_blocked.is_(True))) or 0
        active7 = len(await _active_ids(s, now - timedelta(days=7)))
        cq = select(func.count(User.id))
        if conds:
            cq = cq.where(*conds)
        total = await s.scalar(cq) or 0
        pages = max(1, (total + per - 1) // per)
        page = min(page, pages)
        counts = (select(File.owner_id.label("oid"), func.count(File.id).label("n"))
                  .group_by(File.owner_id).subquery())
        rq = select(User, counts.c.n).outerjoin(counts, counts.c.oid == User.id)
        if conds:
            rq = rq.where(*conds)
        order = {"seen": (User.last_seen.desc(), User.id.desc()),
                 "joined": (User.created_at.desc(), User.id.desc()),
                 "files": (func.coalesce(counts.c.n, 0).desc(), User.id.desc())}[sort]
        rows = (await s.execute(rq.order_by(*order).limit(per).offset((page - 1) * per))).all()
        langs = [lg for (lg,) in (await s.execute(
            select(User.lang).group_by(User.lang))).all() if lg]
    users = [{**user_ref(u), "lang": u.lang or "", "joined": ts(u.created_at),
              "seen": ts(u.last_seen), "files": n or 0} for u, n in rows]
    return {"rows": users, "total": total, "page": page, "pages": pages, "per": per,
            "all": total_all, "blocked": blocked_all, "active7": active7,
            "langs": sorted(langs)}


async def user_detail(user_id: int) -> dict | None:
    async with Sessionmaker() as s:
        u = await s.get(User, user_id)
        if u is None:
            return None
        files = await s.scalar(select(func.count(File.id)).where(File.owner_id == u.id)) or 0
        dls = await s.scalar(select(func.count(DownloadEvent.id))
                             .where(DownloadEvent.owner_id == u.id)) or 0
        dl_files = await s.scalar(select(func.count(File.id))
                                  .where(File.owner_id == u.id, File.source == "dl")) or 0
        ops = await s.scalar(select(func.count(Job.id)).join(File, File.id == Job.file_id)
                             .where(File.owner_id == u.id)) or 0
        midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        ops_today = await s.scalar(
            select(func.count(Job.id)).join(File, File.id == Job.file_id)
            .where(File.owner_id == u.id, Job.created_at >= _bind(midnight))) or 0
    return {**user_ref(u), "lang": u.lang or "", "joined": ts(u.created_at),
            "seen": ts(u.last_seen), "files": files,
            # لاگِ دانلود تازه است؛ پیش از آن تنها ردِ دانلودها ردیف‌های `File`ِ دانلودی‌اند
            "dls": max(dls, dl_files), "ops": ops, "ops_today": ops_today}


async def search_users(q: str, limit: int = 5) -> list[dict]:
    ql = _norm_q(q).lstrip("@")
    if len(ql) < 2:
        return []
    alts = [_like(User.full_name, ql), _like(User.username, ql)]
    if ql.isdigit() and len(ql) <= 19:
        alts.append(User.tg_user_id == int(ql))
    async with Sessionmaker() as s:
        rows = (await s.execute(select(User).where(or_(*alts))
                                .order_by(User.last_seen.desc()).limit(limit))).scalars().all()
    return [user_ref(u) for u in rows]


# ── گزارش‌ها ──────────────────────────────────────────────────────────────────
_ERR_NORM = re.compile(r"\s+")
_HEIGHTS = (2160, 1440, 1080, 720, 480, 360)


def norm_error(text: str | None) -> str:
    """متنِ خطای عملیات (آزاد) → یک خطِ کوتاه برای گروه‌بندی."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return _ERR_NORM.sub(" ", first)[:140]


def height_bucket(h: int | None) -> int | None:
    if not h:
        return None
    for b in _HEIGHTS:
        if h >= b * 0.9:
            return b
    return 240


async def first_activity() -> datetime | None:
    async with Sessionmaker() as s:
        cands = [await s.scalar(select(func.min(User.created_at))),
                 await s.scalar(select(func.min(File.created_at))),
                 await s.scalar(select(func.min(DownloadEvent.created_at)))]
    cands = [aware(c) for c in cands if c is not None]
    return min(cands) if cands else None


async def reports(key: str, now: datetime | None = None) -> dict:
    """داده‌ی صفحهٔ گزارش‌ها — تاریخچه، نه وضعیتِ زنده."""
    key = key if key in REPORT_RANGES else "30d"
    first = await first_activity() if key == "all" else None
    R = make_range(key, now, first)
    lo = _bind(R.prev_start or R.start)
    n = len(R)
    async with Sessionmaker() as s:
        total_users = await s.scalar(select(func.count(User.id))) or 0
        user_rows = (await s.execute(
            select(User.created_at).where(User.created_at >= lo))).scalars().all()
        files = (await s.execute(
            select(File.created_at, File.source, File.owner_id, File.kind, File.size,
                   File.platform, File.height)
            .where(File.created_at >= lo))).all()
        events = (await s.execute(
            select(DownloadEvent.created_at, DownloadEvent.platform, DownloadEvent.outcome,
                   DownloadEvent.owner_id, DownloadEvent.cached, DownloadEvent.size,
                   DownloadEvent.error_class, DownloadEvent.error)
            .where(DownloadEvent.created_at >= lo))).all()
        ev_first = aware(await s.scalar(select(func.min(DownloadEvent.created_at))))
        jobs = (await s.execute(
            select(Job.created_at, Job.finished_at, Job.op, Job.status, File.owner_id,
                   Job.error)
            .join(File, File.id == Job.file_id)
            .where(Job.created_at >= lo))).all()
        lang_rows = (await s.execute(select(User.lang, func.count(User.id))
                                     .group_by(User.lang))).all()

    new_b = [0] * n
    new_cur = new_prev = 0
    for c in user_rows:
        if R.in_cur(c):
            new_cur += 1
            new_b[R.index(c)] += 1
        elif R.in_prev(c):
            new_prev += 1

    # فعالِ روزانه: جفتِ (روزِ تهران، مالک)
    day_owner: set[tuple[str, int]] = set()

    def touch(created, owner):
        if owner is not None and R.in_cur(created):
            day_owner.add((F.local(aware(created)).date().isoformat(), owner))

    files_n = {"dl": [0, 0], "up": [0, 0]}
    bytes_n = [0, 0]
    kinds: dict[str, int] = {}
    quality: dict[int, int] = {}
    plat_b: dict[str, list[int]] = {}
    plat_n: dict[str, int] = {}
    per_user: dict[int, dict] = {}

    def urow(owner):
        return per_user.setdefault(owner, {"files": 0, "dls": 0, "ops": 0})

    for created, source, owner, kind, size, platform, height in files:
        slot = 0 if R.in_cur(created) else 1 if R.in_prev(created) else None
        if slot is None:
            continue
        k = "dl" if source == "dl" else "up" if _is_upload(source) else None
        if not k:
            continue
        files_n[k][slot] += 1
        bytes_n[slot] += size or 0
        if slot != 0:
            continue
        touch(created, owner)
        kk = fold_kind(kind)
        kinds[kk] = kinds.get(kk, 0) + 1
        if owner is not None:
            urow(owner)["files"] += 1
        if k == "dl":
            p = fold_platform(platform)
            plat_b.setdefault(p, [0] * n)[R.index(created)] += 1
            plat_n[p] = plat_n.get(p, 0) + 1
            if kind == "video":
                hb = height_bucket(height)
                if hb:
                    quality[hb] = quality.get(hb, 0) + 1

    ev_ok: dict[str, int] = {}
    ev_att: dict[str, int] = {}
    cache_hits = [0, 0]
    cache_bytes = 0
    errs: dict[tuple, dict] = {}
    for created, platform, outcome, owner, cached, size, err_cls, err in events:
        slot = 0 if R.in_cur(created) else 1 if R.in_prev(created) else None
        if slot is None:
            continue
        if outcome == "ok" and cached:
            cache_hits[slot] += 1
            if slot == 0:
                cache_bytes += size or 0
        if slot != 0:
            continue
        touch(created, owner)
        if owner is not None:
            urow(owner)["dls"] += 1
        p = fold_platform(platform)
        if outcome in ("ok", "fail"):
            ev_att[p] = ev_att.get(p, 0) + 1
            if outcome == "ok":
                ev_ok[p] = ev_ok.get(p, 0) + 1
        if outcome == "fail":
            key_ = ("dl", platform or "other", err_cls or "unrelated")
            e = errs.setdefault(key_, {"src": "dl", "where": platform or "other",
                                       "cls": err_cls or "unrelated", "n": 0,
                                       "last": None, "msg": ""})
            e["n"] += 1
            t_ = ts(created)
            if e["last"] is None or t_ > e["last"]:
                e["last"], e["msg"] = t_, (err or "")[:300]

    ops: dict[str, dict] = {}
    jobs_n = [0, 0]
    jobs_fail = [0, 0]
    for created, finished, op, status, owner, err in jobs:
        slot = 0 if R.in_cur(created) else 1 if R.in_prev(created) else None
        if slot is None:
            continue
        jobs_n[slot] += 1
        if status == "failed":
            jobs_fail[slot] += 1
        if slot != 0:
            continue
        touch(created, owner)
        if owner is not None:
            urow(owner)["ops"] += 1
        if status not in ("done", "failed"):
            continue
        o = ops.setdefault(op, {"op": op, "n": 0, "fail": 0, "durs": []})
        o["n"] += 1
        if status == "failed":
            o["fail"] += 1
            msg = norm_error(err) or "—"
            key_ = ("job", op, msg)
            e = errs.setdefault(key_, {"src": "job", "where": op, "cls": "", "n": 0,
                                       "last": None, "msg": msg})
            e["n"] += 1
            t_ = ts(created)
            if e["last"] is None or t_ > e["last"]:
                e["last"] = t_
        else:
            d = _dur(created, finished)
            if d is not None:
                o["durs"].append(d)

    op_rows = []
    for o in sorted(ops.values(), key=lambda x: -x["n"]):
        durs = o.pop("durs")
        o["avg"] = sum(durs) / len(durs) if durs else None
        o["p95"] = _p95(durs)
        op_rows.append(o)

    # فعالِ روزانه → سطل: روزانه = همان روز؛ هفتگی = میانگینِ روزهای هفته
    daily: dict[str, int] = {}
    for d, _o in day_owner:
        daily[d] = daily.get(d, 0) + 1
    act_b: list[float] = []
    for i in range(n):
        s0 = F.local(R.starts[i]).date()
        if R.unit == "day":
            act_b.append(daily.get(s0.isoformat(), 0))
            continue
        e0 = F.local(R.bucket_end(i) - timedelta(seconds=1)).date()
        days_in = [(s0 + timedelta(days=k)).isoformat() for k in range((e0 - s0).days + 1)]
        act_b.append(sum(daily.get(d, 0) for d in days_in) / max(1, len(days_in)))
    n_days = max(1, math.ceil(R.days))
    top = sorted(per_user.items(), key=lambda kv: (-kv[1]["files"], -kv[1]["dls"], -kv[1]["ops"]))[:8]
    return {
        "key": key, "end": ts(R.end), "first": ts(first),
        "users": total_users, "new": [new_cur, new_prev], "new_b": new_b,
        "files": files_n, "bytes": bytes_n, "cache": [cache_hits[0], cache_hits[1]],
        "cache_bytes": cache_bytes,
        "jobs": jobs_n, "jobs_fail": jobs_fail, "ev_first": ts(ev_first),
        "act_b": act_b, "act_avg": (sum(daily.values()) / n_days) if daily else 0,
        # ردیف‌ها اجتماعِ «فایل داد» و «تلاش شد» است: پلتفرمی که همهٔ تلاش‌هایش
        # شکست خورده هیچ فایلی ندارد، و اگر فقط از فایل‌ها ساخته می‌شد درست همان
        # پلتفرمِ خراب از گزارش ناپدید می‌شد.
        "plat": [{"p": p, "b": plat_b.get(p) or [0] * n, "n": plat_n.get(p, 0),
                  "ok": ev_ok.get(p, 0), "att": ev_att.get(p, 0)}
                 for p in sorted(set(plat_b) | set(ev_att),
                                 key=lambda x: (x == "other", -plat_n.get(x, 0), -ev_att.get(x, 0)))],
        "ops": op_rows,
        "kinds": sorted(({"k": k, "n": v} for k, v in kinds.items()), key=lambda x: -x["n"]),
        "quality": sorted(({"h": h, "n": v} for h, v in quality.items()), key=lambda x: -x["h"]),
        "errors": sorted(errs.values(), key=lambda e: (-e["n"], -(e["last"] or 0)))[:8],
        "top": [{"id": oid, **v} for oid, v in top],
        "langs": sorted(({"code": lg or "", "n": c} for lg, c in lang_rows),
                        key=lambda x: -x["n"]),
    }


async def users_by_ids(ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    async with Sessionmaker() as s:
        rows = (await s.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: user_ref(u) for u in rows}


async def lang_counts() -> dict[str, int]:
    """کاربرانِ هر زبانِ ربات (برای صفحهٔ زبان‌ها)."""
    async with Sessionmaker() as s:
        rows = (await s.execute(select(User.lang, func.count(User.id)).group_by(User.lang))).all()
    return {lg: n for lg, n in rows if lg}


async def language_dates() -> dict[str, float | None]:
    """تاریخِ افزوده‌شدنِ هر زبانِ افزوده (زبانِ داخلی ردیف ندارد)."""
    async with Sessionmaker() as s:
        rows = (await s.execute(select(Language.code, Language.created_at))).all()
    return {code: ts(at) for code, at in rows}
