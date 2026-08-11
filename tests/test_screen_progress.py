"""فاز ۳پ / موردِ ۱۳الف — برچسبِ فاز روی یادداشتِ «در حالِ بررسی».

`run_screen` یک‌بار «🔎 در حالِ بررسی…» می‌فرستد و تا پایانِ کار دست‌نخورده
می‌ماند؛ روی ویدیوی بزرگ یعنی تا ~۹۴ ثانیه سکوت.

دو تصمیم که این‌جا تست می‌شوند و هر دو از عددِ اندازه‌گیری‌شده آمده‌اند
(دریافت ۱۰٫۳ ثانیه · فریم ۱٫۱ · استنتاج ۰٫۳):

* **درصد و شمارندهٔ فریم نمی‌سازیم** — کار عملاً یک انتظارِ شبکه است، پس فقط
  «کجاییم» و «چند ثانیه گذشته».
* **ticker با تأخیر شروع می‌شود** — غربالگریِ یک فایلِ کوچک ~۱٫۴ ثانیه است، پس
  شروعِ بی‌تأخیر یعنی اکثریتِ مطلقِ آپلودها یک ویرایشِ بی‌فایده می‌گیرند و
  رگبارِ آلبوم به سقفِ نرخِ تلگرام نزدیک می‌شود.

رفتار با مقادیرِ کوچک‌شده سنجیده می‌شود (تا suite کند نشود) و **جدا** یک گارد
روی مقدارِ واقعیِ ثابت هست، وگرنه تست‌ها با یک تأخیرِ ۰٫۵ ثانیه‌ای هم سبز
می‌مانند در حالی که هدف از بین رفته.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import safety
from app import tasks as T
from app.models import Base, File, User

CHAT, NOTE_MID = 991, 5150


class FakeBot:
    def __init__(self) -> None:
        self.edits: list[str] = []
        self.deleted: list[int] = []

    async def edit_message_text(self, text: str, chat_id=None, message_id=None, **kw):
        self.edits.append(text)
        return True

    async def delete_message(self, chat_id, message_id, **kw):
        self.deleted.append(message_id)
        return True


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        u = User(tg_user_id=5, role="user")
        s.add(u)
        await s.flush()
        f = File(ref="ScReeN01", owner_id=u.id, file_unique_id="s0", file_id="s0",
                 name="clip.mp4", kind="video", size=1024)
        s.add(f)
        await s.commit()
        row_id = f.id

    monkeypatch.setattr(T, "Sessionmaker", maker)
    monkeypatch.setattr(T, "send_card", _noop)
    monkeypatch.setattr(T.textstore, "refresh_if_stale", _anoop)

    async def _policy(*a, **kw):
        return safety.Policy(enabled=True, scan_pixels=True)

    monkeypatch.setattr(safety, "load_policy", _policy)
    # ticker را تندتر کن تا suite کند نشود؛ نسبتِ «سریع < تأخیر < کند» حفظ می‌شود.
    # `raising=False` عمدی است: روی سورسِ **پیش از رفع** این ثابت‌ها وجود ندارند و
    # بدونِ آن، تست‌ها با `AttributeError` سرِ setup می‌افتادند — یعنی «نبودِ صفت»
    # را نشان می‌دادند نه شکافِ رفتاری را. با این پرچم، نسخهٔ قدیمی واقعاً اجرا
    # می‌شود و روی ادعای درست می‌افتد: کارِ کند هیچ بازخوردی نمی‌دهد.
    monkeypatch.setattr(T, "_SCREEN_NOTE_DELAY", 0.3, raising=False)
    monkeypatch.setattr(T, "_SCREEN_NOTE_EVERY", 0.15, raising=False)
    yield row_id
    await engine.dispose()


async def _noop(*a, **kw):
    return None


async def _anoop(*a, **kw):
    return None


def _payload(row_id: int, note: int | None = NOTE_MID) -> dict:
    return {"file_id_row": row_id, "chat_id": CHAT, "note_mid": note,
            "lang": "fa", "tg_user_id": 5}


def _stage(monkeypatch, fetch: float = 0.0, scan: float = 0.0) -> None:
    async def _localize(bot, fid, workdir):
        await asyncio.sleep(fetch)
        return "/tmp/whatever.mp4"

    async def _scan_file(path, kind, threshold, frames, workdir):
        await asyncio.sleep(scan)
        return False, 0.0, ""

    monkeypatch.setattr(T, "_localize", _localize)
    monkeypatch.setattr(safety, "scan_file", _scan_file)


# ── قلبِ خواستهٔ اپراتور: سریع = صفر ویرایش ────────────────────────────────
async def test_a_fast_screen_produces_no_edits_at_all(env, monkeypatch):
    """فایلِ کوچک (~۱٫۴ ثانیه در واقعیت) نباید هیچ ویرایشی بگیرد."""
    bot = FakeBot()
    _stage(monkeypatch, fetch=0.02, scan=0.02)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env))
    assert bot.edits == [], f"غربالگریِ سریع ویرایش تولید کرد: {bot.edits}"
    assert bot.deleted == [NOTE_MID], "یادداشت باید در پایان پاک شود"


async def test_a_burst_of_fast_screens_stays_silent(env, monkeypatch):
    """رگبارِ آلبوم: ده آپلودِ سریعِ هم‌زمان → صفر ویرایش، نه ۱۰ تا."""
    bot = FakeBot()
    _stage(monkeypatch, fetch=0.02, scan=0.02)
    await asyncio.gather(*[
        T.run_screen({"bot": bot, "redis": None}, _payload(env)) for _ in range(10)
    ])
    assert bot.edits == [], f"رگبار {len(bot.edits)} ویرایش تولید کرد"


# ── فقط کارِ واقعاً کند پیشرفت می‌بیند ────────────────────────────────────
async def test_a_slow_fetch_reports_the_fetch_phase(env, monkeypatch):
    bot = FakeBot()
    _stage(monkeypatch, fetch=0.8, scan=0.02)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env))
    assert bot.edits, "دریافتِ کند باید بازخورد بدهد"
    assert "دریافت" in bot.edits[0], f"برچسبِ فازِ دریافت نیامد: {bot.edits[0]!r}"


async def test_a_slow_scan_reports_the_scan_phase(env, monkeypatch):
    bot = FakeBot()
    _stage(monkeypatch, fetch=0.02, scan=0.8)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env))
    assert bot.edits, "بررسیِ کند باید بازخورد بدهد"
    assert "بررسیِ محتوا" in bot.edits[-1], f"برچسبِ فازِ بررسی نیامد: {bot.edits[-1]!r}"


async def test_both_phases_are_reported_in_order(env, monkeypatch):
    """فازها باید جابه‌جا شوند، نه اینکه روی اولی گیر کنند."""
    bot = FakeBot()
    _stage(monkeypatch, fetch=0.5, scan=0.5)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env))
    assert any("دریافت" in e for e in bot.edits), "فازِ دریافت گزارش نشد"
    assert any("بررسیِ محتوا" in e for e in bot.edits), "فازِ بررسی گزارش نشد"
    first_scan = next(i for i, e in enumerate(bot.edits) if "بررسیِ محتوا" in e)
    assert all("دریافت" in e for e in bot.edits[:first_scan]), "ترتیبِ فازها به‌هم خورد"


async def test_the_elapsed_seconds_are_shown_and_grow(env, monkeypatch):
    """ثانیهٔ سپری‌شده — و هیچ درصدِ ساختگی‌ای."""
    bot = FakeBot()
    _stage(monkeypatch, fetch=1.0, scan=0.02)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env))
    assert len(bot.edits) >= 2, "برای کارِ یک‌ثانیه‌ای باید چند به‌روزرسانی باشد"
    assert "%" not in " ".join(bot.edits), "درصدِ ساختگی نباید ساخته شود"
    digits = [sum(c.isdigit() for c in e) for e in bot.edits]
    assert all(d > 0 for d in digits), "ثانیهٔ سپری‌شده در متن نیست"


# ── انضباطِ ticker ────────────────────────────────────────────────────────
async def test_the_ticker_does_not_outlive_the_job(env, monkeypatch):
    bot = FakeBot()
    _stage(monkeypatch, fetch=0.5, scan=0.02)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env))
    after = len(bot.edits)
    await asyncio.sleep(0.5)
    assert len(bot.edits) == after, "ticker بعد از پایانِ جاب هنوز ویرایش می‌کند"


async def test_no_note_means_no_ticker(env, monkeypatch):
    """بدونِ `note_mid` چیزی برای ویرایش نیست — نباید تسکی ساخته شود."""
    bot = FakeBot()
    _stage(monkeypatch, fetch=0.8, scan=0.02)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env, note=None))
    assert bot.edits == []


async def test_cancelling_the_job_still_propagates(env, monkeypatch):
    """درسِ ۲-۷: بستنِ ticker نباید لغوِ خودِ جاب را ببلعد."""
    bot = FakeBot()
    _stage(monkeypatch, fetch=5.0, scan=0.02)
    task = asyncio.create_task(T.run_screen({"bot": bot, "redis": None}, _payload(env)))
    await asyncio.sleep(0.4)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── گاردِ خودِ عدد (وگرنه تست‌های بالا با تأخیرِ ۰٫۵ هم سبز می‌مانند) ──────
def test_the_initial_delay_is_wide_of_the_measured_fast_path():
    """فایلِ کوچک ~۱٫۴ ثانیه غربال می‌شود (اندازه‌گیریِ ۲۰۲۶-۰۸-۱۰).

    تأخیر باید با حاشیهٔ معنادار بالاتر باشد، وگرنه هدف — «آپلودِ عادی هیچ
    ویرایشی نگیرد» — از بین می‌رود.
    """
    assert T._SCREEN_NOTE_DELAY >= 3.0, "تأخیرِ اولیه برای مسیرِ سریع کم است"
    assert T._SCREEN_NOTE_EVERY >= 3.0, "فاصلهٔ ویرایش کم است — سقفِ نرخِ تلگرام"
