"""متن‌های قابلِ‌ویرایشِ زمانِ‌اجرا (لایهٔ override روی locales).

`t()` (در i18n) sync است و روی مسیرِ داغ صدا زده می‌شود؛ پس override‌ها در یک
دیکشنریِ **درون‌پروسه** نگه‌داری می‌شوند و وقتی یک شمارندهٔ نسخه در Redis
(`txtver`) عوض شود، هر پروسه (bot/worker) خودش را از Postgres تازه می‌کند —
بی‌ری‌استارت و بین‌پروسه‌ای، بدونِ async کردنِ `t()`.

منبعِ ماندگار = Postgres (`text_overrides`)؛ Redis فقط شمارندهٔ ابطال است.
اعتبارسنجی هنگامِ ذخیره: placeholderها حفظ شوند (`{n}` و…)، HTMLِ تلگرام معتبر
باشد، طول محدود. زمانِ اجرا اگر override‌ای بشکند، `t()` بی‌صدا به پیش‌فرض برمی‌گردد.
"""
from __future__ import annotations

import logging
import string
from html.parser import HTMLParser

from sqlalchemy import delete as sa_delete, select

from . import settings_store
from .db import Sessionmaker
from .models import ButtonStyle, MenuButton, TextOverride

log = logging.getLogger("telabzar.textstore")

_VER_KEY = "txtver"  # شمارندهٔ ابطالِ مشترکِ متن‌ها + استایل + چیدمانِ منو
_overrides: dict[tuple[str, str], str] = {}
_button_styles: dict[str, tuple[str | None, str | None]] = {}  # op → (style, icon_emoji_id)
_menu_layout: dict[str, list[dict]] = {}  # kind → [{op, hidden, width}] به ترتیبِ position
_loaded_ver: int | None = None  # None = هنوز لود نشده

_BUTTON_STYLES = ("primary", "success", "danger")  # رنگ‌های مجازِ Bot API
BUTTON_WIDTHS = ("full", "half", "third")           # عرضِ کلید در ردیف

# تگ‌های مجازِ HTMLِ تلگرام (bot messages).
_ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "a", "code", "pre", "blockquote", "span", "tg-spoiler", "tg-emoji",
}
_FORMATTER = string.Formatter()
_MAX_LEN = 3900  # زیرِ سقفِ ۴۰۹۶ پیام (کپشن‌ها کوتاه‌ترند؛ این سقفِ ایمن است)


def get_override(lang: str, key: str) -> str | None:
    """override را برمی‌گرداند؛ None یعنی از پیش‌فرضِ locale استفاده کن. (sync، داغ)"""
    return _overrides.get((lang, key))


def snapshot() -> dict[tuple[str, str], str]:
    return dict(_overrides)


def get_button_style(op: str) -> tuple[str | None, str | None]:
    """(style, icon_emoji_id) برای یک op؛ (None, None) اگر تنظیم نشده. (sync، داغ)"""
    return _button_styles.get(op, (None, None))


def button_snapshot() -> dict[str, tuple[str | None, str | None]]:
    return dict(_button_styles)


def get_menu_layout(kind: str) -> list[dict] | None:
    """چیدمانِ منوی یک kind؛ None یعنی از پیش‌فرضِ کد (OPS_BY_KIND) استفاده کن. (sync، داغ)"""
    return _menu_layout.get(kind)


def menu_snapshot() -> dict[str, list[dict]]:
    return {k: list(v) for k, v in _menu_layout.items()}


def _redis():
    store = settings_store.get_store()
    return store.r if store is not None else None


async def _load_from_db() -> None:
    global _overrides, _button_styles, _menu_layout
    async with Sessionmaker() as s:
        rows = (await s.execute(select(TextOverride))).scalars().all()
        brows = (await s.execute(select(ButtonStyle))).scalars().all()
        mrows = (await s.execute(select(MenuButton))).scalars().all()
    _overrides = {(r.lang, r.key): r.value for r in rows}
    _button_styles = {b.op: (b.style, b.icon_emoji_id) for b in brows}
    layout: dict[str, list[dict]] = {}
    for m in sorted(mrows, key=lambda x: (x.kind, x.position)):
        layout.setdefault(m.kind, []).append(
            {"op": m.op, "hidden": bool(m.hidden), "width": m.width or "third"})
    _menu_layout = layout


async def _redis_ver() -> int:
    r = _redis()
    if r is None:
        return 0
    try:
        v = await r.get(_VER_KEY)
        return int(v) if v is not None else 0
    except Exception:  # noqa: BLE001
        return 0


async def load() -> None:
    """لودِ اجباری از DB + همگام‌سازیِ نسخهٔ کش‌شده (در startup صدا زده می‌شود)."""
    global _loaded_ver
    await _load_from_db()
    _loaded_ver = await _redis_ver()


async def refresh_if_stale() -> None:
    """ارزان: فقط نسخه را می‌خواند؛ اگر عوض شده بود از DB تازه می‌کند. best-effort."""
    global _loaded_ver
    try:
        ver = await _redis_ver()
        if _loaded_ver is None or ver != _loaded_ver:
            await _load_from_db()
            _loaded_ver = ver
    except Exception as exc:  # noqa: BLE001  — هیچ‌وقت مسیرِ اصلی را نشکن
        log.debug("text refresh skipped: %s", exc)


async def _bump_and_reload() -> None:
    global _loaded_ver
    r = _redis()
    if r is not None:
        try:
            newv = await r.incr(_VER_KEY)
            await _load_from_db()
            _loaded_ver = int(newv)
            return
        except Exception:  # noqa: BLE001
            pass
    await _load_from_db()  # بدونِ Redis: دستِ‌کم پروسهٔ خودمان تازه شود


async def set_text(lang: str, key: str, value: str) -> None:
    async with Sessionmaker() as s:
        row = (await s.execute(select(TextOverride).where(
            TextOverride.lang == lang, TextOverride.key == key))).scalar_one_or_none()
        if row is None:
            s.add(TextOverride(lang=lang, key=key, value=value))
        else:
            row.value = value
        await s.commit()
    await _bump_and_reload()


async def reset_text(lang: str, key: str) -> None:
    async with Sessionmaker() as s:
        await s.execute(sa_delete(TextOverride).where(
            TextOverride.lang == lang, TextOverride.key == key))
        await s.commit()
    await _bump_and_reload()


# ── استایلِ کلیدها (رنگ + آیکونِ ایموجیِ پرمیوم) ────────────────
def clean_button(style: str, emoji: str) -> tuple[str | None, str | None]:
    """ورودیِ خام → مقادیرِ معتبر (style مجاز، emoji فقط رقمی)؛ نامعتبر → None."""
    s = style.strip() if style else ""
    e = emoji.strip() if emoji else ""
    return (s if s in _BUTTON_STYLES else None, e if e.isdigit() else None)


async def set_button_styles(mapping: dict[str, tuple[str | None, str | None]]) -> None:
    """چند op را یک‌جا ست/ریست می‌کند و فقط یک‌بار نسخه را bump می‌کند."""
    async with Sessionmaker() as s:
        for op, (style, emoji) in mapping.items():
            row = await s.get(ButtonStyle, op)
            if not style and not emoji:          # هیچ‌کدام → حذفِ ردیف
                if row is not None:
                    await s.delete(row)
            elif row is None:
                s.add(ButtonStyle(op=op, style=style, icon_emoji_id=emoji))
            else:
                row.style, row.icon_emoji_id = style, emoji
        await s.commit()
    await _bump_and_reload()


def clean_width(w: str) -> str:
    return w if w in BUTTON_WIDTHS else "third"


async def set_menu_layout(kind: str, entries: list[dict]) -> None:
    """کلِ چیدمانِ یک kind را جایگزین می‌کند. entries = [{op, hidden, width}] به ترتیب."""
    async with Sessionmaker() as s:
        await s.execute(sa_delete(MenuButton).where(MenuButton.kind == kind))
        for pos, e in enumerate(entries):
            s.add(MenuButton(kind=kind, op=e["op"], position=pos,
                             hidden=bool(e.get("hidden")), width=clean_width(e.get("width", "third"))))
        await s.commit()
    await _bump_and_reload()


async def reset_menu_layout(kind: str) -> None:
    async with Sessionmaker() as s:
        await s.execute(sa_delete(MenuButton).where(MenuButton.kind == kind))
        await s.commit()
    await _bump_and_reload()


# ── اعتبارسنجی (خالص، تست‌پذیر) ─────────────────────────────────
def _fields(text: str) -> set[str]:
    """نامِ placeholderهای {name} در متن (بدونِ index/attr)."""
    out: set[str] = set()
    for _lit, field, _spec, _conv in _FORMATTER.parse(text):
        if field:
            out.add(field.split(".")[0].split("[")[0])
    return out


class _HTMLCheck(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.err: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if self.err:
            return
        if tag not in _ALLOWED_TAGS:
            self.err = f"تگِ غیرمجاز: <{tag}>"
            return
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:  # <br/> و…
        if not self.err and tag not in _ALLOWED_TAGS:
            self.err = f"تگِ غیرمجاز: <{tag}>"

    def handle_endtag(self, tag: str) -> None:
        if self.err:
            return
        if tag not in _ALLOWED_TAGS:
            self.err = f"تگِ غیرمجاز: </{tag}>"
            return
        if not self.stack or self.stack[-1] != tag:
            self.err = f"تگِ ناهماهنگ: </{tag}>"
            return
        self.stack.pop()


def _html_error(value: str) -> str | None:
    p = _HTMLCheck()
    try:
        p.feed(value)
        p.close()
    except Exception as exc:  # noqa: BLE001
        return f"HTMLِ نامعتبر: {exc}"
    if p.err:
        return p.err
    if p.stack:
        return f"تگِ بسته‌نشده: <{p.stack[-1]}>"
    return None


def validate(default_text: str, value: str) -> str | None:
    """پیامِ خطا (فارسی) اگر value نامعتبر است، وگرنه None."""
    if not value.strip():
        return "متن نمی‌تواند خالی باشد (برای حذفِ override از «بازگشت به پیش‌فرض» استفاده کن)."
    if len(value) > _MAX_LEN:
        return f"متن خیلی بلند است (بیشینه {_MAX_LEN})."
    # placeholderها: فقط از placeholderهای موجود در پیش‌فرض استفاده شود
    try:
        vfields = _fields(value)
    except ValueError:
        return "نحوِ placeholder نادرست است ({ } را بررسی کن)."
    extra = vfields - _fields(default_text)
    if extra:
        return "placeholderِ ناشناخته: " + ", ".join("{" + e + "}" for e in sorted(extra))
    # با مقادیرِ ساختگی تمیز فرمت شود (کشفِ { } خراب)
    try:
        value.format(**{f: "" for f in _fields(default_text)})
    except (KeyError, IndexError, ValueError):
        return "متن تمیز فرمت نمی‌شود ({ } را بررسی کن)."
    return _html_error(value)
