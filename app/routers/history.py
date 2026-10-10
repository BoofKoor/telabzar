"""«🗂 تاریخچهٔ فایل‌ها» — دیدن، جست‌وجو و دوباره‌گرفتنِ هر فایلی که ربات فرستاده.

داده و قاعده‌ها در `app/history.py`اند؛ این‌جا فقط نما و کنش. سه چیز که شکلِ
این ماژول را ساخت:

- **همه‌چیز یک پیام است که ویرایش می‌شود** (نمای کلی → فهرست → جزئیات → نسخه‌ها)، تا
  مرور چت را پر نکند. فقط «دوباره بفرست» پیامِ تازه می‌سازد: خودِ فایل، به‌صورتِ
  کارت با همان منوی عملیات، پس کاربر می‌تواند همان‌جا رویش کار کند.
- **دوباره‌فرستادن با `file_id` است** — صفر بایت آپلود، آنی، بدونِ سهمیه. فایلِ تکی
  از `cards.send_card` می‌رود (همان کارتِ همیشگی، با fallbackِ خودش)؛ گروه به‌صورتِ
  آلبوم، و اگر تلگرام آلبوم را رد کرد عضو به عضو.
- **هر دکمه مالکیت را از نو می‌سنجد**: پرس‌وجوها روی `user.id` فیلتر می‌شوند، پس
  دکمهٔ کهنه یا callbackِ دست‌ساز به فایلِ کسِ دیگری نمی‌رسد و «دیگر در تاریخچه
  نیست» می‌گیرد.
"""
from __future__ import annotations

import logging
from html import escape
from urllib.parse import urlsplit

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    LinkPreviewOptions,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from .. import history as H
from .. import panel_fmt as F_
from ..callbacks import Hist, Nav
from ..cards import _ICON, _quality_label, send_card
from ..downloader import find_url, platform_label
from ..i18n import t
from ..models import File, User
from ..states import HistorySearch

log = logging.getLogger("telabzar.history")

router = Router(name="history")

#: کلیدِ برچسبِ هر دسته.
_CAT_KEY = {H.CAT_ALL: "hist_cat_all", H.CAT_STAR: "hist_cat_star",
            H.CAT_ALBUM: "hist_cat_album", H.CAT_LINK: "hist_cat_link",
            **{code: f"hist_cat_{kind}" for code, kind in H.KIND_CATS}}
#: ترتیبِ دکمه‌های نمای کلی: «همه» و «نشان‌دار»، نوع‌ها، بعد آلبوم و دانلود.
_CAT_ORDER = (H.CAT_ALL, H.CAT_STAR, *(code for code, _k in H.KIND_CATS),
              H.CAT_ALBUM, H.CAT_LINK)
_KINDS = frozenset(k for _c, k in H.KIND_CATS)
_NAME_MAX = 28           # نامِ روی دکمه؛ بلندتر روی گوشی بریده می‌شود
_SEARCH_TTL = 86400      # توکنِ جست‌وجو یک روز می‌ماند (صفحه‌بندیِ نتیجه)
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _fl(lang: str) -> str:
    """زبانِ قالب‌بندیِ `panel_fmt`. فقط fa رقم و ماهِ فارسی می‌گیرد: `is_fa` آن‌جا
    یعنی «نه en»، پس بی این زبانِ افزوده (es…) تاریخِ شمسی و رقمِ فارسی می‌دید."""
    return "fa" if lang == "fa" else "en"


def _short(s: str, n: int = _NAME_MAX) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=txt, callback_data=cb) for txt, cb in row] for row in rows if row])


def _cat_title(lang: str, c: str, query: str | None = None) -> str:
    if c == H.CAT_SEARCH:
        return t(lang, "hist_cat_search", q=escape(_short(query or "", 40)))
    return t(lang, _CAT_KEY.get(c, "hist_cat_all"))


def _split_cat(c: str) -> tuple[str, str]:
    """`c` → (دسته، توکنِ جست‌وجو). `q<توکن>` نتیجهٔ جست‌وجوست."""
    if c.startswith(H.CAT_SEARCH):
        return H.CAT_SEARCH, c[1:]
    return (c if H.is_category(c) else H.CAT_ALL), ""


def _where(f, lang: str) -> str:
    """از کجا آمد: پلتفرم، وگرنه دامنهٔ لینک."""
    if f.platform and f.platform != "other":
        return platform_label(f.platform, _fl(lang))
    host = (urlsplit(f.source_url).hostname or "") if f.source_url else ""
    return host.removeprefix("www.") or "—"


def _source_line(f, lang: str) -> str:
    if f.source == "dl":
        return t(lang, "hist_src_dl", platform=escape(_where(f, lang)))
    if f.source == "op":
        return t(lang, "hist_src_op")
    return t(lang, "hist_src_upload")


def _link_line(f, lang: str) -> str | None:
    url = f.source_url or ""
    if not url.startswith(("http://", "https://")):
        return None
    return f'🌐 <a href="{escape(url, quote=True)}">{t(lang, "hist_source_link")}</a>'


def _meta_line(f: File, lang: str) -> str:
    fl = _fl(lang)
    parts = [f"📦 {F_.size(f.size, fl)}"] if f.size else []
    if f.kind == "video":
        q = _quality_label(f.width, f.height)
        if q:
            parts.append(f"🎞 {q}")
    if f.kind in ("video", "audio") and f.duration:
        parts.append(f"⏱ {F_.secs_short(f.duration, fl)}")
    if f.kind == "image" and f.width and f.height:
        parts.append(f"🖼 {F_.digits(f'{f.width}×{f.height}', fl)}")
    return "  ·  ".join(parts)


def _when(f) -> object:
    return f.last_at or f.created_at


# ── نماها ───────────────────────────────────────────────────────────
async def overview_view(session: AsyncSession, user: User, lang: str):
    """(متن، کیبورد)ِ نمای کلی — از منوی خانه، `/history` و «‹ دسته‌ها»."""
    ov = await H.overview(session, user.id)
    back = (t(lang, "btn_back"), Nav(to="home").pack())
    if not ov.counts.get(H.CAT_ALL):
        return t(lang, "hist_empty"), _kb([[back]])
    fl = _fl(lang)
    lines = [t(lang, "hist_title"), "",
             t(lang, "hist_summary", files=F_.num(ov.files, fl), size=F_.size(ov.size, fl),
               last=F_.when(ov.last, fl))]
    if ov.capped:
        lines.append(t(lang, "hist_capped", n=F_.num(H.SCAN_MAX, fl)))
    lines += ["", t(lang, "hist_pick")]
    cats = [(f"{t(lang, _CAT_KEY[c])} · {F_.num(ov.counts[c], fl)}", Hist(v="l", c=c).pack())
            for c in _CAT_ORDER if c == H.CAT_ALL or ov.counts.get(c)]
    rows = [cats[i:i + 2] for i in range(0, len(cats), 2)]
    rows.append([(t(lang, "hist_btn_search"), Hist(v="q").pack()),
                 (t(lang, "hist_btn_clear"), Hist(v="c").pack())])
    rows.append([back])
    return "\n".join(lines), _kb(rows)


def _entry_label(e: H.Entry, lang: str) -> str:
    fl = _fl(lang)
    star = "⭐ " if e.starred else ""
    day = F_.day_short(e.at, fl)
    if e.is_group:
        head = platform_label(e.platform, fl) if e.platform and e.platform != "other" \
            else (e.name or "—")
        return f"{star}📚 {_short(head)} · {t(lang, 'hist_group_n', n=F_.num(e.n, fl))} · {day}"
    head = (f"{_ICON.get(e.kind, '📄')} {_short(e.name)}" if e.name
            else t(lang, f"hist_cat_{e.kind}" if e.kind in _KINDS else "hist_cat_document"))
    size = f" · {F_.size(e.size, fl)}" if e.size else ""
    return f"{star}{head}{size} · {day}"


def list_view(page: H.Page, c: str, lang: str, title: str):
    """(متن، کیبورد)ِ یک صفحه از فهرست. `c` همان مقدارِ callback است (با توکن)."""
    fl = _fl(lang)
    if not page.total:
        text = t(lang, "hist_list_empty", title=title)
    else:
        text = t(lang, "hist_list_head", title=title, n=F_.num(page.total, fl),
                 page=F_.num(page.page, fl), pages=F_.num(page.pages, fl))
    rows = [[(_entry_label(e, lang),
              Hist(v="g" if e.is_group else "d", c=c, p=page.page, r=e.ref).pack())]
            for e in page.items]
    if page.pages > 1:
        nav = []
        if page.page > 1:
            nav.append((t(lang, "hist_btn_prev"), Hist(v="l", c=c, p=page.page - 1).pack()))
        nav.append((f"{F_.num(page.page, fl)}/{F_.num(page.pages, fl)}", Hist(v="n").pack()))
        if page.page < page.pages:
            nav.append((t(lang, "hist_btn_next"), Hist(v="l", c=c, p=page.page + 1).pack()))
        rows.append(nav)
    if c.startswith(H.CAT_SEARCH):
        rows.append([(t(lang, "hist_btn_search"), Hist(v="q").pack())])
    rows.append([(t(lang, "hist_btn_cats"), Hist(v="o").pack())])
    return text, _kb(rows)


async def detail_view(session: AsyncSession, f: File, lang: str, c: str, p: int):
    """(متن، کیبورد)ِ یک فایل."""
    fl = _fl(lang)
    head = (f"{_ICON.get(f.kind, '📄')} <b>{escape(f.name)}</b>" if f.name
            else f"<b>{t(lang, _CAT_KEY.get(_kind_cat(f.kind), 'hist_cat_document'))}</b>")
    lines = [head]
    meta = _meta_line(f, lang)
    if meta:
        lines.append(meta)
    lines += [f"🗓 {F_.full(_when(f), fl)}", _source_line(f, lang)]
    link = _link_line(f, lang)
    if link:
        lines.append(link)
    if f.changelog:
        lines.append(t(lang, "hist_ops_done",
                       ops=" · ".join(escape(str(x)) for x in f.changelog[-3:])))
    star = (("s0", "hist_btn_unstar") if await H.is_starred(session, f.owner_id, f)
            else ("s1", "hist_btn_star"))
    rows = [[(t(lang, "hist_btn_send"), Hist(v="ss", c=c, p=p, r=f.ref).pack())],
            [(t(lang, star[1]), Hist(v=star[0], c=c, p=p, r=f.ref).pack()),
             (t(lang, "hist_btn_hide"), Hist(v="x", c=c, p=p, r=f.ref).pack())]]
    nver = await H.version_count(session, f.id)
    if nver:
        rows.append([(t(lang, "hist_btn_versions", n=F_.num(nver, fl)),
                      Hist(v="vl", c=c, p=p, r=f.ref).pack())])
    rows.append([(t(lang, "btn_back"), Hist(v="l", c=c, p=p).pack())])
    return "\n".join(lines), _kb(rows)


def _kind_cat(kind: str) -> str:
    for code, k in H.KIND_CATS:
        if k == kind:
            return code
    return "d"


def group_view(members: list[File], lang: str, c: str, p: int, m: int, gref: str):
    """(متن، کیبورد)ِ یک گروه: فرستادنِ همه، نشان/حذف، و اعضا برای فرستادنِ تکی."""
    fl = _fl(lang)
    first = members[0]
    title = (platform_label(first.platform, fl) if first.platform and first.platform != "other"
             else (first.name or "—"))
    at = max((_when(x) for x in members if _when(x) is not None), default=None)
    total = sum(int(x.size or 0) for x in members)
    lines = [f"📚 <b>{escape(title)}</b>",
             " · ".join(s for s in (t(lang, "hist_group_n", n=F_.num(len(members), fl)),
                                    F_.size(total, fl) if total else "") if s),
             f"🗓 {F_.full(at, fl)}", _source_line(first, lang)]
    link = _link_line(first, lang)
    if link:
        lines.append(link)
    if first.post_caption:
        lines.append(f"<blockquote expandable>{escape(first.post_caption[:600])}</blockquote>")
    lines += ["", t(lang, "hist_group_hint")]
    starred = any(x.starred_at for x in members)
    star = ("g0", "hist_btn_unstar") if starred else ("g1", "hist_btn_star")
    rows = [[(t(lang, "hist_btn_send_all"), Hist(v="sa", c=c, p=p, m=m, r=gref).pack())],
            [(t(lang, star[1]), Hist(v=star[0], c=c, p=p, m=m, r=gref).pack()),
             (t(lang, "hist_btn_hide"), Hist(v="gx", c=c, p=p, m=m, r=gref).pack())]]
    mp = H.paginate(members, m, H.GROUP_PAGE_SIZE)
    base = (mp.page - 1) * H.GROUP_PAGE_SIZE
    for i, x in enumerate(mp.items, start=base + 1):
        name = _short(x.name) if x.name else F_.num(i, fl)
        size = f" · {F_.size(x.size, fl)}" if x.size else ""
        rows.append([(f"{_ICON.get(x.kind, '📄')} {name}{size}",
                      Hist(v="sm", c=c, p=p, m=mp.page, r=x.ref).pack())])
    if mp.pages > 1:
        nav = []
        if mp.page > 1:
            nav.append((t(lang, "hist_btn_prev"),
                        Hist(v="g", c=c, p=p, m=mp.page - 1, r=gref).pack()))
        nav.append((f"{F_.num(mp.page, fl)}/{F_.num(mp.pages, fl)}", Hist(v="n").pack()))
        if mp.page < mp.pages:
            nav.append((t(lang, "hist_btn_next"),
                        Hist(v="g", c=c, p=p, m=mp.page + 1, r=gref).pack()))
        rows.append(nav)
    rows.append([(t(lang, "btn_back"), Hist(v="l", c=c, p=p).pack())])
    return "\n".join(x for x in lines if x is not None), _kb(rows)


def versions_view(f: File, vers, lang: str, c: str, p: int):
    fl = _fl(lang)
    text = t(lang, "hist_versions_title", name=escape(f.name or "—"))
    rows = []
    for v in vers:
        head = t(lang, "hist_version_original") if v.label is None else f"🕘 {_short(v.label)}"
        size = f" · {F_.size(v.size, fl)}" if v.size else ""
        rows.append([(f"{head}{size} · {F_.day_short(v.created_at, fl)}",
                      Hist(v="vr", c=c, p=p, r=str(v.id)).pack())])
    rows.append([(t(lang, "btn_back"), Hist(v="d", c=c, p=p, r=f.ref).pack())])
    return text, _kb(rows)


def confirm_view(lang: str, text_key: str, yes_key: str, yes_cb: str, no_cb: str):
    return t(lang, text_key), _kb([[(t(lang, yes_key), yes_cb)], [(t(lang, "hist_btn_no"), no_cb)]])


# ── کمکی‌های کنش ────────────────────────────────────────────────────
async def _edit(cq: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    if not isinstance(cq.message, Message):
        return
    try:
        await cq.message.edit_text(text, reply_markup=kb, link_preview_options=_NO_PREVIEW)
    except TelegramBadRequest:     # «message is not modified» یا پیامِ خیلی قدیمی
        pass


async def _search_query(redis, token: str) -> str | None:
    if redis is None or not token:
        return None
    try:
        raw = await redis.get(f"hsq:{token}")
    except Exception:  # noqa: BLE001
        return None
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else str(raw)


async def _render_list(session, user: User, lang: str, c: str, p: int, redis):
    """(متن، کیبورد)ِ فهرستِ `c` در صفحهٔ `p` — جست‌وجو هم، اگر توکنش زنده باشد."""
    cat, token = _split_cat(c)
    query = None
    if cat == H.CAT_SEARCH:
        query = await _search_query(redis, token)
        if query is None:
            return t(lang, "hist_search_expired"), _kb([
                [(t(lang, "hist_btn_search"), Hist(v="q").pack())],
                [(t(lang, "hist_btn_cats"), Hist(v="o").pack())]])
        c = H.CAT_SEARCH + token
    else:
        c = cat
    page = await H.list_page(session, user.id, cat, p, query=query)
    return list_view(page, c, lang, _cat_title(lang, cat, query))


def _album_item(f: File, caption: str | None):
    """عضوِ گروه → InputMedia با `file_id`.

    نوعِ **تلگرامیِ** `file_id` تعیین‌کننده است نه `kind`: کاروسلِ دانلودی عکس/ویدیو
    رفته و خروجیِ چندفایلیِ یک عملیات سند (حتی وقتی تصویر است، `kind="image"`). هر
    گروهی که `history` ثبت می‌کند یکی از این دو است، و تلگرام سند را با عکس در یک
    آلبوم نمی‌پذیرد — شکست به ارسالِ تکی می‌افتد.
    """
    kw = {"media": f.file_id}
    if caption:
        kw["caption"] = caption
    if f.source == "dl" and f.kind == "image":
        return InputMediaPhoto(**kw)
    if f.source == "dl" and f.kind == "video":
        return InputMediaVideo(**kw)
    return InputMediaDocument(**kw)


async def _send_group(bot, chat_id: int, members: list[File], lang: str) -> int:
    """گروه → آلبوم(ها)ی ده‌تایی؛ دستهٔ ردشده عضو به عضو. خروجی = تعدادِ نرسیده."""
    failed = 0
    cap = escape(members[0].post_caption) if members[0].post_caption else None
    for i in range(0, len(members), 10):
        chunk = members[i:i + 10]
        if len(chunk) >= 2:
            try:
                await bot.send_media_group(chat_id, media=[
                    _album_item(x, cap if (i == 0 and n == 0) else None)
                    for n, x in enumerate(chunk)])
                continue
            except Exception:  # noqa: BLE001
                log.warning("history album re-send failed; sending one by one", exc_info=True)
        for x in chunk:
            try:
                await send_card(bot, chat_id, x, lang)
            except Exception:  # noqa: BLE001
                failed += 1
                log.warning("history re-send of %s failed", x.ref, exc_info=True)
    return failed


async def _start_search(message: Message, session: AsyncSession, user: User, lang: str,
                        query: str, redis) -> None:
    """متنِ جست‌وجو → صفحهٔ اولِ نتیجه، به‌صورتِ پیامِ تازه."""
    query = " ".join(query.split())[:100]
    if len(query) < H.SEARCH_MIN:
        await message.answer(t(lang, "hist_search_short", n=F_.num(H.SEARCH_MIN, _fl(lang))))
        return
    token = H.new_ref()
    if redis is not None:
        try:
            await redis.set(f"hsq:{token}", query, ex=_SEARCH_TTL)
        except Exception:  # noqa: BLE001 — صفحهٔ اول بی‌توکن هم ساخته می‌شود
            log.warning("history search token not stored", exc_info=True)
    page = await H.list_page(session, user.id, H.CAT_SEARCH, 1, query=query)
    if not page.total:
        await message.answer(t(lang, "hist_search_none", q=escape(_short(query, 40))),
                             reply_markup=_kb([
                                 [(t(lang, "hist_btn_search"), Hist(v="q").pack())],
                                 [(t(lang, "hist_btn_cats"), Hist(v="o").pack())]]))
        return
    text, kb = list_view(page, H.CAT_SEARCH + token, lang,
                         _cat_title(lang, H.CAT_SEARCH, query))
    await message.answer(text, reply_markup=kb)


# ── هندلرها ─────────────────────────────────────────────────────────
@router.message(Command("history"))
async def cmd_history(message: Message, command: CommandObject, session: AsyncSession,
                      user: User | None, lang: str, state: FSMContext,
                      arq_pool=None) -> None:
    """`/history` = نمای کلی؛ `/history متن` = جست‌وجوی مستقیم."""
    if user is None:
        return
    await state.clear()
    if command.args and command.args.strip():
        await _start_search(message, session, user, lang, command.args, arq_pool)
        return
    text, kb = await overview_view(session, user, lang)
    await message.answer(text, reply_markup=kb)


@router.message(HistorySearch.waiting, F.text)
async def on_search_text(message: Message, session: AsyncSession, user: User | None,
                         lang: str, state: FSMContext, arq_pool=None) -> None:
    text = (message.text or "").strip()
    # کاربر نظرش عوض شد: لینک برای دانلود یا یک دستور — نباید «جست‌وجو» شود.
    if text.startswith("/") or find_url(text):
        await state.clear()
        raise SkipHandler
    await state.clear()
    if user is None:
        return
    await _start_search(message, session, user, lang, text, arq_pool)


@router.callback_query(Hist.filter())
async def on_history(cq: CallbackQuery, callback_data: Hist, session: AsyncSession,
                     user: User | None, lang: str, state: FSMContext,
                     arq_pool=None) -> None:
    d = callback_data
    v, c, p, m, r = d.v, d.c, max(1, d.p), max(1, d.m), d.r
    if user is None:
        await cq.answer()
        return
    if v == "n":
        await cq.answer()
        return
    if v != "q" and await state.get_state() == HistorySearch.waiting.state:
        await state.clear()          # از جست‌وجو بیرون آمد

    if v == "o":
        await cq.answer()
        await _edit(cq, *await overview_view(session, user, lang))
        return
    if v == "l":
        await cq.answer()
        await _edit(cq, *await _render_list(session, user, lang, c, p, arq_pool))
        return
    if v == "q":
        await state.set_state(HistorySearch.waiting)
        await cq.answer()
        await _edit(cq, t(lang, "hist_search_prompt"),
                    _kb([[(t(lang, "hist_btn_cancel"), Hist(v="o").pack())]]))
        return
    if v == "c":
        await cq.answer()
        await _edit(cq, *confirm_view(lang, "hist_confirm_clear", "hist_btn_yes_clear",
                                      Hist(v="cy").pack(), Hist(v="o").pack()))
        return
    if v == "cy":
        await H.clear_all(session, user.id)
        await cq.answer(t(lang, "hist_cleared"))
        await _edit(cq, *await overview_view(session, user, lang))
        return

    # ── یک فایل ──
    if v in ("d", "ss", "s1", "s0", "x", "xy", "vl"):
        f = await H.get_file(session, user.id, r)
        if f is None:
            await cq.answer(t(lang, "hist_missing"), show_alert=True)
            await _edit(cq, *await _render_list(session, user, lang, c, p, arq_pool))
            return
        if v == "ss":
            try:
                await send_card(cq.bot, cq.message.chat.id if cq.message else user.tg_user_id,
                                f, lang)
            except Exception:  # noqa: BLE001
                log.warning("history re-send of %s failed", f.ref, exc_info=True)
                await cq.answer(t(lang, "hist_send_failed"), show_alert=True)
                return
            await cq.answer(t(lang, "hist_sent"))
            return
        if v in ("s1", "s0"):
            await H.set_star(session, user.id, f.ref, v == "s1", group=False)
            await session.refresh(f)
            await cq.answer(t(lang, "hist_starred" if v == "s1" else "hist_unstarred"))
            await _edit(cq, *await detail_view(session, f, lang, c, p))
            return
        if v == "x":
            await cq.answer()
            await _edit(cq, *confirm_view(lang, "hist_confirm_hide", "hist_btn_yes_hide",
                                          Hist(v="xy", c=c, p=p, r=f.ref).pack(),
                                          Hist(v="d", c=c, p=p, r=f.ref).pack()))
            return
        if v == "xy":
            await H.hide(session, user.id, f.ref, group=False)
            await cq.answer(t(lang, "hist_hidden"))
            await _edit(cq, *await _render_list(session, user, lang, c, p, arq_pool))
            return
        if v == "vl":
            await cq.answer()
            await _edit(cq, *versions_view(f, await H.versions(session, user.id, f.ref),
                                           lang, c, p))
            return
        await cq.answer()
        await _edit(cq, *await detail_view(session, f, lang, c, p))
        return

    if v == "vr":
        try:
            vid = int(r)
        except ValueError:
            vid = 0
        newf = await H.restore_version(session, user.id, vid) if vid else None
        if newf is None:
            await cq.answer(t(lang, "hist_missing"), show_alert=True)
            return
        try:
            await send_card(cq.bot, cq.message.chat.id if cq.message else user.tg_user_id,
                            newf, lang)
        except Exception:  # noqa: BLE001 — ردیفِ نرسیده نماند (همان قاعدهٔ spawn)
            log.warning("history version restore of %s failed", vid, exc_info=True)
            await session.delete(newf)
            await session.commit()
            await cq.answer(t(lang, "hist_send_failed"), show_alert=True)
            return
        await cq.answer(t(lang, "hist_restored"))
        return

    if v == "sm":
        f = await H.get_file(session, user.id, r)
        if f is None:
            await cq.answer(t(lang, "hist_missing"), show_alert=True)
            return
        try:
            await send_card(cq.bot, cq.message.chat.id if cq.message else user.tg_user_id,
                            f, lang)
        except Exception:  # noqa: BLE001
            log.warning("history re-send of %s failed", f.ref, exc_info=True)
            await cq.answer(t(lang, "hist_send_failed"), show_alert=True)
            return
        await cq.answer(t(lang, "hist_sent"))
        return

    # ── یک گروه ──
    if v in ("g", "sa", "g1", "g0", "gx", "gxy"):
        members = await H.get_group(session, user.id, r)
        if not members:
            await cq.answer(t(lang, "hist_missing"), show_alert=True)
            await _edit(cq, *await _render_list(session, user, lang, c, p, arq_pool))
            return
        if v == "sa":
            chat_id = cq.message.chat.id if cq.message else user.tg_user_id
            failed = await _send_group(cq.bot, chat_id, members, lang)
            await cq.answer(t(lang, "hist_send_failed" if failed == len(members) else "hist_sent"),
                            show_alert=failed == len(members))
            return
        if v in ("g1", "g0"):
            await H.set_star(session, user.id, r, v == "g1", group=True)
            for x in members:
                await session.refresh(x)
            await cq.answer(t(lang, "hist_starred" if v == "g1" else "hist_unstarred"))
            await _edit(cq, *group_view(members, lang, c, p, m, r))
            return
        if v == "gx":
            await cq.answer()
            await _edit(cq, *confirm_view(lang, "hist_confirm_hide", "hist_btn_yes_hide",
                                          Hist(v="gxy", c=c, p=p, r=r).pack(),
                                          Hist(v="g", c=c, p=p, m=m, r=r).pack()))
            return
        if v == "gxy":
            await H.hide(session, user.id, r, group=True)
            await cq.answer(t(lang, "hist_hidden"))
            await _edit(cq, *await _render_list(session, user, lang, c, p, arq_pool))
            return
        await cq.answer()
        await _edit(cq, *group_view(members, lang, c, p, m, r))
        return

    await cq.answer()     # کنشِ ناشناخته (دکمهٔ نسخهٔ دیگری از ربات)
