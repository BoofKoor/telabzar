"""تاریخچهٔ فایل‌های کاربر — ثبت، پرس‌وجو و تغییر (۲۰۲۶-۱۰-۱۰).

هر فایلی که ربات به کاربر **تحویل داده** یک ردیفِ `File` دارد و از تاریخچه دوباره
فرستاده می‌شود — با `file_id`، یعنی صفر بایت آپلود و آنی. این ماژول دو نیمه دارد:

**ثبت.** ورودیِ کاربر، دانلودِ تک‌فایل و خروجیِ «spawn» از قبل ردیف داشتند. چیزهایی
که تا امروز **هیچ ردی** نمی‌گذاشتند و این‌جا ثبت می‌شوند: آلبوم/کاروسل (تازه و از
کش)، پستِ Rich، خروجیِ چندفایلیِ یک عملیات (`files`)، و خروجیِ رسانه‌ایِ جدا
(`send_media`: GIF، اسکرین‌شات، عکسِ بی‌پس‌زمینه). و نسخهٔ قبلیِ فایلی که یک عملیاتِ
درجا عوضش کرد در `file_versions` می‌ماند (`version_row`) — وگرنه فایلِ اصل برای
همیشه از دست می‌رفت، چون پیامِ آپلودی پاک شده و ردیف بازنویسی می‌شود. ثبت
**بهترین‌تلاش** است: هر فراخوان خطایش را می‌بلعد، چون تاریخچه نباید تحویلِ یک فایل
را بشکند.

**نمایش.** «مورد» یا یک فایل است یا یک گروه (`group_ref`). سه قاعده:
- **تکراری یکی می‌شود**: همان فایل (`file_unique_id`) که چند بار رسیده — آپلودِ
  دوباره، دانلودِ دوباره از کش — یک مورد است، با تازه‌ترین ردیف.
- **گروه یک مورد است** در نماهای «همه/نشان‌دار/دانلودها/آلبوم‌ها/جست‌وجو»، ولی در
  دسته‌های نوعِ فایل (ویدیو، تصویر، …) اعضا جدا می‌آیند: «همهٔ عکس‌هایم» یعنی عکسِ
  داخلِ کاروسل هم.
- **ترتیب** تازه‌ترین اول، با `last_at` (عملیاتِ درجا، آلبومِ تکراری) و در نبودش
  `created_at` — که عمداً دست نمی‌خورد چون آمارِ پنل روی آن است.

همه‌چیز در پایتون روی ستون‌های سبک انجام می‌شود، نه با SQLِ گروه‌بندی: یک کوئریِ
ایندکس‌دار (`ix_files_owner_created`) برای حداکثر `SCAN_MAX` ردیفِ تازه‌ترِ کاربر،
بعد یکی‌کردن/گروه‌بندی/صفحه‌بندی در حافظه. دو دلیل: هم روی SQLiteِ تست‌ها و هم
Postgresِ تولید یک رفتار دارد، و تاکردنِ فارسیِ جست‌وجو (`textfold.fold`) در SQL
شدنی نیست. اندازه‌اش اندازه‌گیری‌شده کوچک است: سنگین‌ترین کاربرِ تولید چند صد فایل
دارد، و سقف صریح است و در صفحه گفته می‌شود (`Overview.capped`).

**ایمنی.** تاریخچه فقط چیزی را نشان می‌دهد که ربات **قبلاً فرستاده**: آپلودی که
هنوز از فیلترِ محتوا رد نشده با `hidden_at` پنهان است تا `run_screen` آزادش کند
(`hold_for_screen`/`release_after_screen`)، و ردیفی که هنوز `file_id` ندارد (کارتِ
در حالِ ارسال) دیده نمی‌شود. بی این، تاریخچه راهی بود که ربات محتوای غربال‌نشده را
پیش از گیت بفرستد.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Sessionmaker
from .filetypes import FileInfo, detect
from .models import File, FileVersion
from .textfold import fold

log = logging.getLogger("telabzar.history")

#: حداکثر ردیفِ تازه‌ترِ یک کاربر که تاریخچه می‌بیند. بالاتر از آن صفحه می‌گوید
#: «فقط N فایلِ آخر» (`Overview.capped`) — بریدنِ بی‌صدا نیست.
SCAN_MAX = 5000
#: موردِ هر صفحهٔ فهرست (هر کدام یک دکمه) و عضوِ هر صفحهٔ گروه.
PAGE_SIZE = 8
GROUP_PAGE_SIZE = 10
#: نسخه‌های قبلی که نشان داده می‌شوند (تازه‌ترین اول).
VERSIONS_SHOWN = 10
#: عرضِ ستونِ `File.source_url`. Postgres طول را اعمال می‌کند و SQLiteِ تست‌ها نه
#: (§۷)، پس برش در پایتون است.
URL_MAX = 1024
#: کوتاه‌ترین جست‌وجو؛ یک حرف تقریباً همه‌چیز را جور می‌کند و فقط صفحه را پر.
SEARCH_MIN = 2

# ── دسته‌ها ─────────────────────────────────────────────────────────
# کدِ یک‌حرفی چون در callback (زیرِ ۶۴ بایت) می‌نشیند.
CAT_ALL, CAT_STAR, CAT_ALBUM, CAT_LINK, CAT_SEARCH = "a", "s", "g", "l", "q"
#: دسته‌های نوعِ فایل به ترتیبِ نمایش → `File.kind`. هر هفت نوعِ `filetypes` این‌جاست.
KIND_CATS: tuple[tuple[str, str], ...] = (
    ("v", "video"), ("u", "audio"), ("i", "image"), ("p", "pdf"),
    ("d", "document"), ("z", "archive"), ("k", "app"),
)
_KIND_OF = dict(KIND_CATS)
#: نماهایی که گروه را یک مورد می‌بینند. دسته‌های نوع اعضا را جدا می‌آورند.
_COLLAPSED = {CAT_ALL, CAT_STAR, CAT_ALBUM, CAT_LINK, CAT_SEARCH}


def is_category(c: str) -> bool:
    return c in _COLLAPSED or c in _KIND_OF


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime | None) -> datetime:
    """SQLite زمانِ بی‌منطقه برمی‌گرداند و Postgres آگاه؛ مقایسه باید یکی باشد."""
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def new_ref() -> str:
    """همان شکلِ `ref`ی که ورودی و ورکرها می‌سازند (۸ نویسهٔ تصادفی)."""
    return secrets.token_urlsafe(6)[:8]


def clip_url(url: str | None) -> str | None:
    return url[:URL_MAX] if url else None


def _clip(s: str | None, n: int) -> str | None:
    """برش به عرضِ ستون — Postgres طول را اعمال می‌کند و نوشتنِ بلندتر کلِ commitِ
    فراخوان را می‌شکست (در `run_op` یعنی جاب هرگز بسته نمی‌شد)؛ SQLite نه (§۷)."""
    return s[:n] if s else s


# ── مورد ────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Entry:
    """یک ردیفِ فهرستِ تاریخچه: یک فایل یا یک گروه.

    `ref` برای فایل همان `File.ref` است و برای گروه همان `group_ref`.
    """

    ref: str
    is_group: bool
    kind: str
    name: str | None
    size: int
    n: int
    at: datetime
    starred: bool
    source: str | None
    platform: str | None


_COLS = (File.id, File.ref, File.kind, File.name, File.size, File.created_at, File.last_at,
         File.file_unique_id, File.group_ref, File.starred_at, File.source, File.platform)


def _visible(owner_id: int):
    """ردیف‌هایی که در تاریخچه دیده می‌شوند: مالِ همین کاربر، پنهان‌نشده، تحویل‌شده.

    `file_id` تهی یعنی ردیفی که پیش از ارسالِ کارت commit شده (spawn) و هنوز
    نرسیده — یا هرگز نمی‌رسد.
    """
    return (File.owner_id == owner_id, File.hidden_at.is_(None), File.file_id != "")


def _uid(row) -> str:
    """کلیدِ یکی‌کردنِ تکراری‌ها. ردیفِ بی‌`file_unique_id` (کشِ خیلی قدیمی) با خودش."""
    return row.file_unique_id or f"#{row.id}"


def _order(row) -> tuple[datetime, int]:
    return (_utc(row.last_at or row.created_at), row.id)


def _single(row, *, starred: bool) -> Entry:
    return Entry(ref=row.ref, is_group=False, kind=row.kind, name=row.name,
                 size=int(row.size or 0), n=1, at=_utc(row.last_at or row.created_at),
                 starred=starred, source=row.source, platform=row.platform)


def build_entries(rows, *, collapse: bool) -> list[Entry]:
    """ردیف‌های سبک → موردها، تازه‌ترین اول. خالص، تا بی‌DB تست شود.

    `collapse`: گروه یک مورد است (نماهای «همه»…) یا اعضا جدا (دسته‌های نوع).
    تکراری‌ها (همان `file_unique_id`) همیشه یکی می‌شوند و تازه‌ترین ردیف می‌ماند.

    **نشان مالِ فایل است نه ردیف**: فایلِ تکی نشان‌دار است اگر **هر** ردیفی از همان
    فایل (`file_unique_id`) نشان داشته باشد — `is_starred` همین را برای صفحهٔ جزئیات
    می‌پرسد. فایلی که دوباره می‌رسد (آپلودِ دوباره، دانلودِ دوباره از کش) ردیفِ تازهٔ
    بی‌نشان می‌سازد، و با «نشانِ تازه‌ترین ردیف» نشان بی‌صدا گم می‌شد. گروه نشان‌دار
    است اگر یکی از **ردیف‌های خودش** نشان داشته باشد، تا «برداشتنِ نشانِ آلبوم» —
    که فقط ردیف‌های همان آلبوم را می‌زند — واقعاً آلبوم را بی‌نشان کند.
    """
    singles: dict[str, object] = {}
    starred = {_uid(r) for r in rows if r.starred_at is not None}
    groups: dict[str, list] = {}
    for row in rows:
        if collapse and row.group_ref:
            groups.setdefault(row.group_ref, []).append(row)
            continue
        key = _uid(row)
        cur = singles.get(key)
        if cur is None or _order(row) > _order(cur):
            singles[key] = row
    out = [_single(r, starred=k in starred) for k, r in singles.items()]
    for gref, members in groups.items():
        uniq: dict[str, object] = {}
        for m in members:
            k = _uid(m)
            if k not in uniq or _order(m) > _order(uniq[k]):
                uniq[k] = m
        items = sorted(uniq.values(), key=lambda m: m.id)
        first = items[0]
        out.append(Entry(
            ref=gref, is_group=True, kind=first.kind, name=first.name,
            size=sum(int(m.size or 0) for m in items), n=len(items),
            at=max(_utc(m.last_at or m.created_at) for m in items),
            starred=any(m.starred_at is not None for m in items),
            source=first.source, platform=first.platform))
    out.sort(key=lambda e: e.at, reverse=True)
    return out


async def _rows(session: AsyncSession, owner_id: int, *, caption: bool = False):
    """(ردیف‌های سبکِ دیدنی, آیا سقف خورد) — تازه‌ترین `SCAN_MAX` تا.

    عمداً بی‌فیلترِ دسته: دسته روی **موردها** اعمال می‌شود (`_KEEP`)، نه روی ردیف‌ها
    در SQL — وگرنه یک مورد با ردیف‌های دیگری ساخته می‌شد تا در شمارش (نشانِ ردیفِ
    قدیمی‌تر، نوعِ ردیفِ دیگر) و عددِ روی دکمه با طولِ فهرست نمی‌خواند.
    """
    cols = _COLS + ((File.post_caption,) if caption else ())
    q = (select(*cols).where(*_visible(owner_id))
         .order_by(File.created_at.desc(), File.id.desc()).limit(SCAN_MAX + 1))
    rows = (await session.execute(q)).all()
    return rows[:SCAN_MAX], len(rows) > SCAN_MAX


# ── نمای کلی ────────────────────────────────────────────────────────
@dataclass(slots=True)
class Overview:
    files: int          # فایلِ یکتا (تکراری‌ها یکی)
    size: int           # مجموعِ حجمِ همان فایل‌ها
    last: datetime | None
    counts: dict[str, int]
    capped: bool


#: کدام موردها در هر نمای جمع‌شده می‌آیند. **همین** گزاره‌ها هم شمارِ روی دکمه را
#: می‌سازند (`overview`) و هم فهرست را (`list_page`) — یک قاعده، تا «۳ نشان‌دار» روی
#: دکمه و فهرستِ دوموردی هرگز با هم دیده نشوند.
_KEEP = {
    CAT_ALL: lambda e: True,
    CAT_STAR: lambda e: e.starred,
    CAT_ALBUM: lambda e: e.is_group,
    CAT_LINK: lambda e: e.source == "dl",
}


async def overview(session: AsyncSession, owner_id: int) -> Overview:
    """شمارِ هر دسته با **یک** کوئری."""
    rows, capped = await _rows(session, owner_id)
    files = build_entries(rows, collapse=False)
    entries = build_entries(rows, collapse=True)
    counts = {c: sum(1 for e in entries if keep(e)) for c, keep in _KEEP.items()}
    for code, kind in KIND_CATS:
        counts[code] = sum(1 for e in files if e.kind == kind)
    return Overview(files=len(files), size=sum(e.size for e in files),
                    last=entries[0].at if entries else None, counts=counts, capped=capped)


# ── فهرست ───────────────────────────────────────────────────────────
@dataclass(slots=True)
class Page:
    items: list[Entry]
    total: int
    page: int
    pages: int


def paginate(entries: list[Entry], page: int, size: int = PAGE_SIZE) -> Page:
    """صفحهٔ خارج از بازه به نزدیک‌ترین صفحهٔ موجود می‌رود (دکمهٔ کهنه بعد از حذف)."""
    total = len(entries)
    pages = max(1, -(-total // size))
    page = min(max(1, page), pages)
    start = (page - 1) * size
    return Page(items=entries[start:start + size], total=total, page=page, pages=pages)


def search_matches(rows, query: str) -> list:
    """ردیف‌هایی که نام یا متنِ پستشان شاملِ `query` است — با تاکردنِ فارسی."""
    q = fold(query.strip())
    if not q:
        return []
    return [r for r in rows
            if any(q in fold(x) for x in (r.name, r.post_caption) if x)]


async def list_page(session: AsyncSession, owner_id: int, cat: str, page: int,
                    query: str | None = None) -> Page:
    if cat == CAT_SEARCH:
        rows, _ = await _rows(session, owner_id, caption=True)
        return paginate(build_entries(search_matches(rows, query or ""), collapse=True), page)
    rows, _ = await _rows(session, owner_id)
    if cat in _KIND_OF:
        kind = _KIND_OF[cat]
        return paginate([e for e in build_entries(rows, collapse=False) if e.kind == kind],
                        page)
    keep = _KEEP.get(cat, _KEEP[CAT_ALL])
    return paginate([e for e in build_entries(rows, collapse=True) if keep(e)], page)


# ── یک مورد ─────────────────────────────────────────────────────────
async def get_file(session: AsyncSession, owner_id: int, ref: str) -> File | None:
    """فایلِ دیدنیِ همین کاربر با این `ref`، وگرنه `None` (دکمهٔ کهنه، مالِ دیگری)."""
    res = await session.execute(select(File).where(File.ref == ref, *_visible(owner_id)))
    return res.scalar_one_or_none()


async def get_group(session: AsyncSession, owner_id: int, gref: str) -> list[File]:
    """اعضای دیدنیِ یک گروه به ترتیبِ رسیدن؛ تکراری‌ها (همان فایل) یکی."""
    res = await session.execute(
        select(File).where(File.group_ref == gref, *_visible(owner_id)).order_by(File.id))
    seen: set[str] = set()
    out: list[File] = []
    for f in res.scalars():
        k = _uid(f)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


async def is_starred(session: AsyncSession, owner_id: int, f: File) -> bool:
    """نشانِ **فایل** — هر ردیفِ دیدنیِ همان فایل؛ همان قاعدهٔ `build_entries`، تا
    فهرست ⭐ نشان ندهد و صفحهٔ همان مورد «نشان کن» بگوید."""
    res = await session.execute(
        select(func.count()).select_from(File)
        .where(*_same_file(owner_id, f), File.hidden_at.is_(None), File.file_id != "",
               File.starred_at.is_not(None)))
    return bool(res.scalar())


async def version_count(session: AsyncSession, file_row_id: int) -> int:
    res = await session.execute(
        select(func.count()).select_from(FileVersion).where(FileVersion.parent_id == file_row_id))
    return int(res.scalar() or 0)


async def versions(session: AsyncSession, owner_id: int, ref: str) -> list[FileVersion]:
    """نسخه‌های قبلیِ فایلِ همین کاربر، تازه‌ترین اول."""
    res = await session.execute(
        select(FileVersion).join(File, FileVersion.parent_id == File.id)
        .where(File.ref == ref, *_visible(owner_id))
        .order_by(FileVersion.id.desc()).limit(VERSIONS_SHOWN))
    return list(res.scalars())


# ── تغییر ───────────────────────────────────────────────────────────
def _same_file(owner_id: int, f: File):
    """همهٔ ردیف‌های همین کاربر که **همین فایل**‌اند — عضوِ آلبوم هم.

    نشان و حذف باید روی همه بنشیند، وگرنه تکراریِ قدیمی‌تر بعد از حذفِ تازه‌ترین
    دوباره در فهرست ظاهر می‌شد. عضوِ آلبوم هم، چون در دسته‌های نوع تکِ فایل و عضوِ
    آلبوم **یک** مورد می‌شوند: حذف یا برداشتنِ نشانی که فقط یکی را بزند مورد را سرِ
    جایش نگه می‌داشت. پیامدِ دیدنی‌اش عمدی است: آلبومی که این فایل را دارد هم
    نشان‌دار دیده می‌شود، و حذفِ فایل آن را از آلبوم هم برمی‌دارد.
    """
    if f.file_unique_id:
        return (File.owner_id == owner_id, File.file_unique_id == f.file_unique_id)
    return (File.owner_id == owner_id, File.id == f.id)


async def set_star(session: AsyncSession, owner_id: int, ref: str, on: bool, *,
                   group: bool) -> bool:
    """نشان را روی یک فایل (و تکراری‌هایش) یا همهٔ اعضای یک گروه بگذار/بردار."""
    value = _now() if on else None
    if group:
        where = (File.owner_id == owner_id, File.group_ref == ref, File.hidden_at.is_(None))
    else:
        f = await get_file(session, owner_id, ref)
        if f is None:
            return False
        where = _same_file(owner_id, f)
    res = await session.execute(update(File).where(*where).values(starred_at=value))
    await session.commit()
    return bool(res.rowcount)


async def hide(session: AsyncSession, owner_id: int, ref: str, *, group: bool) -> bool:
    """«حذف از تاریخچه» — نرم؛ کارتی که در چت مانده هنوز کار می‌کند."""
    if group:
        where = (File.owner_id == owner_id, File.group_ref == ref)
    else:
        f = await get_file(session, owner_id, ref)
        if f is None:
            return False
        where = _same_file(owner_id, f)
    res = await session.execute(
        update(File).where(*where, File.hidden_at.is_(None)).values(hidden_at=_now()))
    await session.commit()
    return bool(res.rowcount)


async def clear_all(session: AsyncSession, owner_id: int) -> int:
    """همهٔ تاریخچهٔ کاربر را پنهان کن. تعدادِ ردیف‌ها را برمی‌گرداند."""
    res = await session.execute(
        update(File).where(File.owner_id == owner_id, File.hidden_at.is_(None))
        .values(hidden_at=_now()))
    await session.commit()
    return int(res.rowcount or 0)


# ── ثبت ─────────────────────────────────────────────────────────────
def group_ref_for(owner_id: int, uids: list[str]) -> str:
    """شناسهٔ گروه از مالک + مجموعهٔ اعضا — **قطعی**، تا همان آلبوم که دوباره (از
    کش) برسد همان گروه باشد و ردیفِ تکراری نسازد. مالک داخلِ هش است تا دو کاربرِ
    یک کاروسل یک `group_ref` نگیرند. ۱۲ نویسه = عرضِ ستون."""
    h = hashlib.sha1(("%d\n" % owner_id + "\n".join(sorted(uids))).encode()).hexdigest()
    return "g" + h[:11]


def infos_of(messages) -> list[FileInfo]:
    """پیام‌هایی که ربات فرستاد → `FileInfo` — با **همان** قاعدهٔ ورودیِ کاربر
    (`filetypes.detect`)، پس نوع/نام/حجم دقیقاً همان است که آپلودش می‌داد. پیامی که
    رسانه ندارد (یا داکلِ ناقصِ تست) فقط کنار گذاشته می‌شود."""
    out: list[FileInfo] = []
    for msg in messages or []:
        try:
            info = detect(msg)
        except Exception:  # noqa: BLE001
            info = None
        if info is not None and info.file_id:
            out.append(info)
    return out


def rich_infos(msg) -> list[FileInfo]:
    """رسانه‌های یک پیامِ Rich (اسلایدشوی پستِ چندتایی) به ترتیبِ نمایش.

    `detect` این پیام را نمی‌شناسد چون رسانه داخلِ بلوک‌هاست نه روی خودِ پیام؛
    بلوک‌ها تودرتو می‌شوند (اسلایدشو، کلاژ)، پس درخت پیموده می‌شود.
    """
    out: list[FileInfo] = []

    def walk(blocks) -> None:
        for b in blocks or []:
            photo = getattr(b, "photo", None)
            video = getattr(b, "video", None)
            if photo:
                p = photo[-1]
                out.append(FileInfo("image", p.file_id, p.file_unique_id, None, p.file_size,
                                    "image/jpeg", width=p.width, height=p.height))
            elif video is not None:
                out.append(FileInfo("video", video.file_id, video.file_unique_id,
                                    video.file_name, video.file_size, video.mime_type,
                                    width=video.width, height=video.height,
                                    duration=video.duration))
            walk(getattr(b, "blocks", None))

    try:
        walk(getattr(getattr(msg, "rich_message", None), "blocks", None))
    except Exception:  # noqa: BLE001 — شکلِ ناآشنا فقط یعنی «ثبت نشد»
        log.warning("rich message media walk failed", exc_info=True)
    return [i for i in out if i.file_id]


async def record_infos(session: AsyncSession, owner_id: int, infos: list[FileInfo], *,
                       source: str, names: list[str | None] | None = None,
                       platform: str | None = None, post_caption: str | None = None,
                       source_url: str | None = None) -> list[File]:
    """فایل‌هایی که ربات **همین حالا** فرستاد → ردیفِ تاریخچه.

    یک فایل = یک مورد؛ چند فایل = یک گروه با `group_ref`ِ قطعی. اگر همان گروه
    (همان اعضا) از قبل در تاریخچهٔ کاربر هست ردیفِ تازه ساخته نمی‌شود و فقط
    `last_at` بالا می‌آید — آلبومی که دوباره از کش رسید دو بار در فهرست نمی‌آید.

    commit می‌کند. **هرگز داخلِ تراکنشی که شکستش تحویلی را «ناموفق» می‌خواند** صدایش
    نزن (تراکنشِ یک جاب): خطای DBِ تاریخچه آن‌جا جابِ تحویل‌شده را `running` جا
    می‌گذاشت — `tasks.run_op` به همین دلیل بعد از commitِ جاب `record_safely` می‌زند.
    """
    rows = [File(ref=new_ref(), owner_id=owner_id,
                 file_unique_id=_clip(i.file_unique_id, 64) or "",
                 file_id=i.file_id, kind=i.kind, mime=_clip(i.mime, 128),
                 name=_clip(names[n] if names and n < len(names) and names[n] else i.name, 256),
                 size=i.size, width=i.width, height=i.height, duration=i.duration,
                 changelog=[], source=source, platform=platform, post_caption=post_caption,
                 source_url=clip_url(source_url))
            for n, i in enumerate(infos or []) if i.file_id and len(i.file_id) <= 256]
    if not rows:
        return []
    if len(rows) > 1:
        gref = group_ref_for(owner_id, [r.file_unique_id or r.file_id for r in rows])
        existing = (await session.execute(
            select(File).where(File.group_ref == gref, *_visible(owner_id)))).scalars().all()
        if existing:
            now = _now()
            for f in existing:
                f.last_at = now
            await session.commit()
            return list(existing)
        for r in rows:
            r.group_ref = gref
    session.add_all(rows)
    await session.commit()
    return rows


async def record_safely(owner_id: int, infos: list[FileInfo], **kw) -> list[File]:
    """`record_infos` در نشستِ خودش، بهترین‌تلاش — برای مسیرهای تحویلی که نشستِ
    بازِ مناسبی ندارند. هیچ خطایی بالا نمی‌رود: تاریخچه نباید تحویل را بشکند."""
    if not owner_id or not infos:
        return []
    try:
        async with Sessionmaker() as s:
            return await record_infos(s, owner_id, infos, **kw)
    except Exception:  # noqa: BLE001
        log.warning("history record failed", exc_info=True)
        return []


#: نسخهٔ اصلی برای تست‌هایی که خودِ نوشتن در DB را می‌سنجند؛ `tests/conftest.py`
#: `record_safely` را در هر تست با ضبطِ درون‌حافظه‌ای عوض می‌کند.
_record_safely_real = record_safely


def version_row(parent_id: int, *, file_id: str, file_unique_id: str | None, kind: str,
                mime: str | None, name: str | None, size: int | None, width: int | None,
                height: int | None, duration: int | None,
                changelog: list | None) -> FileVersion:
    """نسخهٔ پیش از یک عملیاتِ درجا. `label` = آخرین کارِ همان نسخه (`None` = اصل)."""
    cl = list(changelog or [])
    return FileVersion(parent_id=parent_id, file_id=file_id,
                       file_unique_id=file_unique_id or "", kind=kind, mime=mime, name=name,
                       size=size, width=width, height=height, duration=duration,
                       label=(str(cl[-1])[:256] if cl else None), changelog=cl)


async def restore_version(session: AsyncSession, owner_id: int,
                          version_id: int) -> File | None:
    """نسخهٔ قبلی → فایلِ تازهٔ تاریخچه (ردیفِ تازه، کارتِ مستقل).

    `source="op"`: نه آپلود است نه دانلود — پنل آپلود را «`source` نه `dl` و نه
    `op`» می‌شمارد، پس هر مقدارِ تازه‌ای این‌جا آمارِ آپلود را باد می‌کرد.
    """
    res = await session.execute(
        select(FileVersion, File).join(File, FileVersion.parent_id == File.id)
        .where(FileVersion.id == version_id, *_visible(owner_id)))
    hit = res.first()
    if hit is None:
        return None
    ver, parent = hit
    f = File(ref=new_ref(), owner_id=owner_id, file_unique_id=ver.file_unique_id or "",
             file_id=ver.file_id, kind=ver.kind, mime=ver.mime, name=ver.name,
             size=ver.size, width=ver.width, height=ver.height, duration=ver.duration,
             changelog=list(ver.changelog or []), source="op",
             post_caption=parent.post_caption, platform=parent.platform,
             source_url=parent.source_url)
    session.add(f)
    await session.commit()
    return f


def touch(f: File) -> None:
    """فایل عوض شد (عملیاتِ درجا) → در تاریخچه بالا بیاید.

    اگر کاربر پیش‌تر از تاریخچه حذفش کرده بود و حالا روی کارتش کار کرد، دوباره دیده
    می‌شود: «حذف» یعنی «این را دیگر لازم ندارم»، و کارِ تازه خلافش را می‌گوید.
    آپلودِ در انتظارِ فیلتر این‌جا نمی‌رسد — هنوز کارتی ندارد که دکمه‌ای بزند.
    """
    f.last_at = _now()
    f.hidden_at = None


def hold_for_screen(f: File) -> None:
    """آپلودی که باید از فیلترِ محتوا رد شود تا آزادسازی در تاریخچه دیده نشود."""
    f.hidden_at = _now()


def release_after_screen(f: File) -> None:
    """فیلتر ردش نکرد و کارتش می‌رود → در تاریخچه دیده شود."""
    f.hidden_at = None
