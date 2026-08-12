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
from app.i18n import t as t_
from app.models import Base, File, User
from tests.aiogram_double import ValidatingBot

CHAT, NOTE_MID = 991, 5150


class FakeBot(ValidatingBot):
    """امضای خودش را تعریف نمی‌کند — `ValidatingBot` شکلِ واقعیِ aiogram را
    تحمیل می‌کند. نسخهٔ قبلی `(text, chat_id, message_id)` را موضعی می‌پذیرفت و
    دقیقاً همین باگی را پنهان کرد که در تولید ticker را بی‌اثر کرده بود."""

    def __init__(self) -> None:
        self.edits: list[str] = []
        self.deleted: list[int] = []
        self.sent: list[str] = []
        self.edit_error: Exception | None = None

    def _on(self, name, payload):
        if name == "edit_message_text":
            if self.edit_error is not None:
                raise self.edit_error
            self.edits.append(payload["text"])
        elif name == "delete_message":
            self.deleted.append(payload["message_id"])
        elif name == "send_message":
            self.sent.append(payload["text"])
        return True


@pytest_asyncio.fixture
async def env(monkeypatch, tmp_path):
    # `run_screen` زیرِ `settings.work_dir` دایرکتوری می‌سازد و پیش‌فرضش `/work`
    # است. این را CI پیدا کرد نه محیطِ محلی: من root اجرا می‌شوم و `/work`
    # ساخته می‌شد، ولی رانر نمی‌تواند و `PermissionError` داخلِ `except Exception`
    # بلعیده می‌شد — یعنی غربالگری اصلاً اجرا نمی‌شد و تست‌های «سریع» به دلیلِ
    # **غلط** سبز می‌ماندند. برای همین پایین‌تر هم اجرا شدنِ مراحل assert می‌شود.
    monkeypatch.setattr(T.settings, "work_dir", str(tmp_path))
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


def _stage(monkeypatch, fetch: float = 0.0, scan: float = 0.0) -> list[str]:
    """مراحل را کند می‌کند و **ثبت** می‌کند که واقعاً اجرا شده‌اند.

    ثبت لازم است چون «صفر ویرایش» به‌تنهایی مبهم است: اگر غربالگری اصلاً اجرا
    نشود هم صفر ویرایش می‌گیریم. دقیقاً همین روی CI اتفاق افتاد.
    """
    ran: list[str] = []

    async def _localize(bot, fid, workdir):
        ran.append("fetch")
        await asyncio.sleep(fetch)
        return "/tmp/whatever.mp4"

    async def _scan_file(path, kind, threshold, frames, workdir):
        ran.append("scan")
        await asyncio.sleep(scan)
        return False, 0.0, ""

    monkeypatch.setattr(T, "_localize", _localize)
    monkeypatch.setattr(safety, "scan_file", _scan_file)
    return ran


# ── قلبِ خواستهٔ اپراتور: سریع = صفر ویرایش ────────────────────────────────
async def test_a_fast_screen_produces_no_edits_at_all(env, monkeypatch):
    """فایلِ کوچک (~۱٫۴ ثانیه در واقعیت) نباید هیچ ویرایشی بگیرد."""
    bot = FakeBot()
    ran = _stage(monkeypatch, fetch=0.02, scan=0.02)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env))
    assert ran == ["fetch", "scan"], "غربالگری اصلاً اجرا نشد — «صفر ویرایش» بی‌معنا می‌شود"
    assert bot.edits == [], f"غربالگریِ سریع ویرایش تولید کرد: {bot.edits}"
    assert bot.deleted == [NOTE_MID], "یادداشت باید در پایان پاک شود"


async def test_a_burst_of_fast_screens_stays_silent(env, monkeypatch):
    """رگبارِ آلبوم: ده آپلودِ سریعِ هم‌زمان → صفر ویرایش، نه ۱۰ تا."""
    bot = FakeBot()
    ran = _stage(monkeypatch, fetch=0.02, scan=0.02)
    await asyncio.gather(*[
        T.run_screen({"bot": bot, "redis": None}, _payload(env)) for _ in range(10)
    ])
    assert ran.count("scan") == 10, "هر ده غربالگری باید واقعاً اجرا شده باشند"
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


# ── ردِ محتوا: کاربر **باید** بفهمد چرا فایلش رفت ─────────────────────────
def _blocking_stage(monkeypatch) -> None:
    async def _localize(bot, fid, workdir):
        return "/tmp/whatever.mp4"

    async def _scan_file(path, kind, threshold, frames, workdir):
        return True, 0.97, "EXPOSED"

    async def _report(*a, **kw):
        return False                       # به آستانهٔ بن نرسیده

    monkeypatch.setattr(T, "_localize", _localize)
    monkeypatch.setattr(safety, "scan_file", _scan_file)
    monkeypatch.setattr(safety, "report_block", _report)


async def test_a_blocked_upload_actually_tells_the_user(env, monkeypatch):
    """سه هفته این کار نمی‌کرد: ویرایش `ValidationError` می‌داد، `except`
    یادداشت را پاک می‌کرد، و شاخهٔ `else` هم اجرا نمی‌شد چون `note_mid` هست —
    یعنی فایل بی‌صدا ناپدید می‌شد و کاربر هیچ توضیحی نمی‌گرفت."""
    bot = FakeBot()
    _blocking_stage(monkeypatch)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env))

    told = bot.edits + bot.sent
    assert told, "کاربرِ ردشده هیچ پیامی نگرفت"
    assert any(t_("fa", "nsfw_blocked") == m for m in told), \
        f"پیامِ رد نیامد؛ آنچه فرستاده شد: {told!r}"


async def test_the_block_message_survives_a_failing_edit(env, monkeypatch):
    """اگر ویرایش شکست خورد (۴۲۹/پیامِ پاک‌شده)، باید پیامِ تازه فرستاده شود —
    نه اینکه فقط یادداشت پاک شود و کاربر با سکوت بماند."""
    bot = FakeBot()
    bot.edit_error = RuntimeError("Telegram says no")
    _blocking_stage(monkeypatch)
    await T.run_screen({"bot": bot, "redis": None}, _payload(env))
    assert bot.sent and bot.sent[-1] == t_("fa", "nsfw_blocked"), \
        f"روی شکستِ ویرایش باید پیام فرستاده شود؛ sent={bot.sent!r}"


# ── گاردِ خودِ عدد (وگرنه تست‌های بالا با تأخیرِ ۰٫۵ هم سبز می‌مانند) ──────
def test_the_initial_delay_is_wide_of_the_measured_fast_path():
    """فایلِ کوچک ~۱٫۴ ثانیه غربال می‌شود (اندازه‌گیریِ ۲۰۲۶-۰۸-۱۰).

    تأخیر باید با حاشیهٔ معنادار بالاتر باشد، وگرنه هدف — «آپلودِ عادی هیچ
    ویرایشی نگیرد» — از بین می‌رود.
    """
    assert T._SCREEN_NOTE_DELAY >= 3.0, "تأخیرِ اولیه برای مسیرِ سریع کم است"
    assert T._SCREEN_NOTE_EVERY >= 3.0, "فاصلهٔ ویرایش کم است — سقفِ نرخِ تلگرام"
