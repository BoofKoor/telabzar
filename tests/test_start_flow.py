"""فاز C — انتخابِ زبان و منوهای کاربر، از مسیرِ **واقعیِ** هندلرها.

سه ادعای اصلی: فهرستِ زبان از جدولِ زنده می‌آید نه هاردکد؛ کاربرِ زبان‌دار
دوباره پرسیده نمی‌شود؛ و تغییرِ زبان از تنظیمات به همان تنظیمات برمی‌گردد،
به زبانِ تازه.

هندلرها با `Message`/`CallbackQuery`ِ **واقعیِ** aiogram رانده می‌شوند و باتْ
`ValidatingBot` است — یعنی هر فراخوانی همان اعتبارسنجیِ pydanticِ تولید را
می‌خورد. درسِ ثبت‌شدهٔ §۶ (بندِ ۴): داکلی که امضای خودش را اعلام کند، شکلِ
واقعیِ API را پنهان می‌کند و تست را بی‌صدا vacuous.

DB واقعی است (SQLite در حافظه) چون ادعای «کاربرِ قدیمی دوباره پرسیده نمی‌شود»
دربارهٔ یک **ردیفِ ذخیره‌شده** است، نه دربارهٔ یک متغیر.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from aiogram.types import CallbackQuery, Chat, Message, User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import i18n, textstore
from app.callbacks import Lang, Nav
from app.locales.en import MESSAGES as EN
from app.locales.fa import MESSAGES as FA
from app.models import Base, User
from app.routers.start import choose_lang, cmd_start, navigate

from tests.aiogram_double import ValidatingBot


class RecordingBot(ValidatingBot):
    """هر فراخوانی را نگه می‌دارد — بعد از اعتبارسنجی، نه به‌جایش."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _on(self, name: str, payload: dict[str, Any]) -> Any:
        self.calls.append((name, payload))
        return True

    def _last(self, name: str) -> dict[str, Any]:
        for n, p in reversed(self.calls):
            if n == name:
                return p
        raise AssertionError(f"هیچ {name}ی ثبت نشد؛ ثبت‌شده‌ها: "
                             f"{[n for n, _ in self.calls]}")

    def buttons(self, name: str) -> list[tuple[str, str]]:
        """[(متن, callback_data)] از کیبوردِ آخرین فراخوانیِ `name`."""
        kb = self._last(name).get("reply_markup")
        if kb is None:
            return []
        rows = kb["inline_keyboard"] if isinstance(kb, dict) else kb.inline_keyboard
        return [((b["text"], b["callback_data"]) if isinstance(b, dict)
                 else (b.text, b.callback_data))
                for row in rows for b in row]


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def added_langs(monkeypatch):
    """دو زبانِ **افزوده** در جدول — همان چیزی که `/langs` می‌سازد.

    `textstore.languages` وصله می‌خورد نه `i18n.available_languages`: ادعا این
    است که فهرست از **جدول** می‌آید، و وصله‌زدن به خودِ سازنده آن ادعا را
    توخالی می‌کرد.
    """
    async def fake() -> dict[str, str]:
        return {"es": "Español", "pt-BR": "Português (Brasil)"}
    monkeypatch.setattr(textstore, "languages", fake)
    return {"es": "Español", "pt-BR": "Português (Brasil)"}


@pytest.fixture
def no_added_langs(monkeypatch):
    async def fake() -> dict[str, str]:
        return {}
    monkeypatch.setattr(textstore, "languages", fake)


def _msg(bot) -> Message:
    return Message(message_id=7, date=datetime.now(timezone.utc),
                   chat=Chat(id=4242, type="private"), text="/start").as_(bot)


def _cq(bot, data: str) -> CallbackQuery:
    return CallbackQuery(
        id="cb1", from_user=TgUser(id=42, is_bot=False, first_name="u"),
        chat_instance="ci", data=data, message=_msg(bot)).as_(bot)


# ══ ۱) فهرستِ زبان از جدولِ زنده می‌آید ═══════════════════════════

async def test_a_language_added_from_the_panel_shows_up_in_the_start_menu(
        session, added_langs):
    """قلبِ فاز C: زبانی که ادمین import می‌کند باید همان‌جا انتخاب‌شدنی باشد."""
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user")
    session.add(user)
    await session.flush()

    await cmd_start(_msg(bot), user, "fa")

    codes = [cb for _txt, cb in bot.buttons("send_message")]
    assert codes == ["lang:fa", "lang:en", "lang:es", "lang:pt-BR"]
    labels = [txt for txt, _cb in bot.buttons("send_message")]
    assert "Español" in labels and "Português (Brasil)" in labels


async def test_picking_an_added_language_is_stored_and_not_coerced_to_fa(
        session, added_langs):
    """`start.py` قبلاً هر کدی جز fa/en را به fa می‌کوباند."""
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user")
    session.add(user)
    await session.flush()

    await choose_lang(_cq(bot, "lang:es"), Lang(code="es"), session, user)

    assert user.lang == "es"


async def test_an_unknown_language_code_still_falls_back_to_the_default(
        session, added_langs):
    """کنترل: دکمهٔ کهنه برای زبانی که حذف شده نباید کدِ مرده را ذخیره کند."""
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user")
    session.add(user)
    await session.flush()

    await choose_lang(_cq(bot, "lang:zz"), Lang(code="zz"), session, user)

    assert user.lang == i18n.DEFAULT


async def test_the_language_list_is_built_in_exactly_one_place(added_langs):
    """پنل باید همان سازنده را صدا بزند، نه فهرستِ خودش را بسازد.

    `routers/` نمی‌تواند `admin_web` را import کند (ایمیجِ ربات jinja2 ندارد)،
    پس دو کپیِ دست‌نویس واگرا می‌شوند و هیچ‌کدام دیگری را خبر نمی‌کند — همان
    الگوی `remove_cookie_file`. این‌جا با AST سنجیده می‌شود نه با import،
    چون `app.admin_web` روی رانرِ CI نصب‌شدنی نیست.
    """
    import ast
    import pathlib

    src = pathlib.Path("app/admin_web.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_languages")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "i18n_available_languages" in called, (
        "_languages باید به i18n.available_languages واگذار کند، نه بازسازی")
    # و بازسازی نکند: نه BUILTIN_NAMES بخواند نه مستقیم textstore.languages
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "BUILTIN_NAMES" not in names, "_languages دارد فهرست را دوباره می‌سازد"


async def test_the_added_languages_come_back_in_a_stable_order(monkeypatch):
    """ترتیبِ غیرقطعی در منویی که کاربر می‌بیند یک باگ است، نه بی‌نظمی.

    روی **DBِ واقعی** سنجیده می‌شود نه با grep روی سورس: ردیف‌ها عمداً
    برعکسِ الفبا درج می‌شوند، پس اگر `ORDER BY` برداشته شود SQLite همان ترتیبِ
    درج را می‌دهد و تست می‌افتد. (`Sessionmaker` در **همان ماژولی** وصله
    می‌خورد که می‌خواندش — الگوی جاافتادهٔ `tests/panel`.)
    """
    from app.models import Language

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(textstore, "Sessionmaker", maker)

    async with maker() as s:
        s.add_all([Language(code="zu", name="Zulu"),
                   Language(code="pt-BR", name="Português (Brasil)"),
                   Language(code="es", name="Español"),
                   Language(code="ar", name="العربية")])
        await s.commit()

    got = await textstore.languages()
    assert list(got.values()) == sorted(got.values()), (
        f"فهرست باید به نامِ نمایشی مرتب باشد، دیده شد: {list(got.values())}")
    await engine.dispose()


# ══ ۲) کاربرِ قدیمی هرگز دوباره پرسیده نمی‌شود ════════════════════

async def test_a_user_who_already_chose_is_never_asked_again(
        session, added_langs):
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user", lang="en")
    session.add(user)
    await session.flush()

    await cmd_start(_msg(bot), user, "en")

    payload = bot._last("send_message")
    assert payload["text"] == EN["welcome"]
    assert [cb for _t, cb in bot.buttons("send_message")] == ["nv:settings", "nv:help"]
    assert not any(cb.startswith("lang:") for _t, cb in bot.buttons("send_message"))


async def test_a_user_with_no_language_yet_is_asked(session, no_added_langs):
    """کنترلِ متقابلِ تستِ بالا: ~۳٪ کاربرانِ تولید `lang=NULL` دارند."""
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user")
    session.add(user)
    await session.flush()

    await cmd_start(_msg(bot), user, "fa")

    assert bot._last("send_message")["text"] == FA["choose_language"]
    assert all(cb.startswith("lang:") for _t, cb in bot.buttons("send_message"))


# ══ ۳) منوها ═════════════════════════════════════════════════════

async def test_the_welcome_screen_offers_settings_and_help(
        session, no_added_langs):
    """قراردادِ امروز، با هدفِ **لفظی** — عمداً از `HOME_ITEMS` مشتق نمی‌شود.

    سابوتاژ این را نشان داد و ارزشش از خودِ تست بیشتر بود: تستِ زیر انتظارش
    را از همان فهرستی می‌سازد که سابوتاژ ویرایش می‌کند، پس با حذفِ یک آیتم
    **هر دو طرف** کوچک می‌شوند و سبز می‌ماند. همان تلهٔ «گارد توضیحاتِ خودش
    را می‌خواند» در شکلِ تازه: ادعا از دادهٔ زیرِ سؤال مشتق شده بود.

    پس دو ادعای جدا لازم است — این یکی می‌گوید **چه چیزی** هست، آن یکی
    می‌گوید از کجا و به چه ترتیبی می‌آید.
    """
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user", lang="fa")
    session.add(user)
    await session.flush()

    await cmd_start(_msg(bot), user, "fa")

    assert bot.buttons("send_message") == [
        (FA["btn_settings"], "nv:settings"),
        (FA["btn_help"], "nv:help"),
    ]


async def test_the_welcome_keys_come_from_the_declarative_list(
        session, no_added_langs):
    """افزودنِ کلیدِ سوم باید **یک ردیف** باشد، پس ادعا روی خودِ فهرست است:
    برچسب از کاتالوگ می‌آید و ترتیب از فهرست. (حذفِ آیتم را نمی‌گیرد — تستِ
    بالا برای همان است.)"""
    from app import keyboards

    bot = RecordingBot()
    user = User(tg_user_id=42, role="user", lang="fa")
    session.add(user)
    await session.flush()

    await cmd_start(_msg(bot), user, "fa")

    got = bot.buttons("send_message")
    assert got == [(FA[key], f"nv:{to}") for to, key in keyboards.HOME_ITEMS]
    assert len(got) == len(keyboards.HOME_ITEMS) >= 2


async def test_settings_opens_with_the_language_item_and_a_back_key(
        session, no_added_langs):
    from app import keyboards

    bot = RecordingBot()
    user = User(tg_user_id=42, role="user", lang="fa")

    await navigate(_cq(bot, "nv:settings"), Nav(to="settings"), user, "fa")

    assert bot._last("edit_message_text")["text"] == FA["settings_title"]
    got = bot.buttons("edit_message_text")
    # هدفِ لفظی، به همان دلیلِ تستِ خوش‌آمد: ادعایی که از `SETTINGS_ITEMS`
    # مشتق شود، خالی‌شدنِ همان فهرست را نمی‌گیرد.
    assert (FA["btn_change_language"], "nv:lang") in got
    assert got[:-1] == [(FA[key], f"nv:{to}") for to, key in keyboards.SETTINGS_ITEMS]
    assert got[-1] == (FA["btn_back"], "nv:home")


async def test_help_shows_the_guide_and_can_go_back(session, no_added_langs):
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user", lang="en")

    await navigate(_cq(bot, "nv:help"), Nav(to="help"), user, "en")

    assert bot._last("edit_message_text")["text"] == EN["help_text"]
    assert bot.buttons("edit_message_text") == [(EN["btn_back"], "nv:home")]


async def test_back_from_settings_returns_to_the_welcome_screen(
        session, no_added_langs):
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user", lang="fa")

    await navigate(_cq(bot, "nv:home"), Nav(to="home"), user, "fa")

    assert bot._last("edit_message_text")["text"] == FA["welcome"]
    assert [cb for _t, cb in bot.buttons("edit_message_text")] == ["nv:settings", "nv:help"]


async def test_the_settings_language_menu_ticks_the_current_language(
        session, added_langs):
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user", lang="es")

    await navigate(_cq(bot, "nv:lang"), Nav(to="lang"), user, "es")

    got = bot.buttons("edit_message_text")
    assert ("✅ Español", "lang:es") in got
    assert got[-1][1] == "nv:settings", "بازگشتِ منوی زبان باید به تنظیمات باشد"


# ══ ۴) تغییر از تنظیمات ← تنظیمات، به زبانِ تازه ═════════════════

async def test_changing_the_language_from_settings_returns_to_settings(
        session, added_langs):
    """تأییدِ **بصری**: منوی تنظیمات به زبانِ تازه رندر می‌شود."""
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user", lang="fa")
    session.add(user)
    await session.flush()

    await choose_lang(_cq(bot, "lang:en"), Lang(code="en"), session, user)

    assert user.lang == "en"
    assert bot._last("edit_message_text")["text"] == EN["settings_title"]
    assert (EN["btn_change_language"], "nv:lang") in bot.buttons("edit_message_text")


async def test_the_first_ever_choice_lands_on_the_welcome_screen(
        session, added_langs):
    """و مسیرِ اول همچنان خوش‌آمد می‌دهد، نه تنظیمات."""
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user")  # هنوز زبانی ندارد
    session.add(user)
    await session.flush()

    await choose_lang(_cq(bot, "lang:en"), Lang(code="en"), session, user)

    assert bot._last("edit_message_text")["text"] == EN["welcome"]
    assert [cb for _t, cb in bot.buttons("edit_message_text")] == ["nv:settings", "nv:help"]


async def test_no_language_set_toast_is_sent_any_more(session, added_langs):
    """گزینهٔ (پ): متنِ `language_set` لفظیِ per-language بود و برای زبانِ
    ترجمه‌نشده به انگلیسی می‌افتاد — به کسی که اسپانیایی زده بود می‌گفت
    «Language set to English». اجراشده روی سورس:

        t('es', 'language_set') == 'Language set to English ✅'

    پس تأیید بصری شد. `answer()` خالی می‌ماند چون تلگرام چرخشِ دکمه را
    می‌خواهد بسته شود.
    """
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user")
    session.add(user)
    await session.flush()

    await choose_lang(_cq(bot, "lang:es"), Lang(code="es"), session, user)

    answers = [p for n, p in bot.calls if n == "answer_callback_query"]
    assert answers, "callback باید answer شود وگرنه دکمه می‌چرخد"
    assert all(not p.get("text") for p in answers), (
        f"هیچ متنی نباید فرستاده شود، دیده شد: {answers}")


def test_the_lie_this_replaced_is_real(added_langs):
    """کنترلِ معکوسِ تستِ بالا: اگر این ادعا دیگر صادق نباشد، حذفِ تأییدیهٔ
    متنی بی‌دلیل شده و باید بازبینی شود."""
    assert i18n.t("es", "language_set") == EN["language_set"]
    assert "English" in EN["language_set"]


# ══ ۵) زبانی که از /langs حذف شده ═════════════════════════════════

async def test_a_user_pinned_to_a_deleted_language_can_still_reach_settings(
        session, no_added_langs):
    """اجراشده: `remove_language` ردیف‌های متن را پاک می‌کند ولی `users.lang`
    دست‌نخورده می‌ماند، پس کاربر بی‌صدا انگلیسی می‌شود. پیش از فاز C راهِ
    برگشتی نداشت (`cmd_start` چون lang ناتهی است منو نشان نمی‌دهد) — منوی
    تنظیمات دقیقاً همین را می‌بندد.
    """
    bot = RecordingBot()
    user = User(tg_user_id=42, role="user", lang="es")  # 'es' دیگر وجود ندارد
    session.add(user)
    await session.flush()

    await cmd_start(_msg(bot), user, "es")
    assert [cb for _t, cb in bot.buttons("send_message")] == ["nv:settings", "nv:help"]

    await navigate(_cq(bot, "nv:lang"), Nav(to="lang"), user, "es")
    codes = [cb for _t, cb in bot.buttons("edit_message_text")]
    assert "lang:fa" in codes and "lang:en" in codes
    assert "lang:es" not in codes, "زبانِ حذف‌شده نباید در فهرست باشد"
    marks = [txt for txt, _cb in bot.buttons("edit_message_text")]
    assert not any(m.startswith("✅") for m in marks), "هیچ ردیفی نباید تیک بگیرد"


# ══ ۶) سازگاریِ عقب‌رو و سقفِ بایت ═══════════════════════════════

def test_the_lang_callback_stayed_single_field():
    """افزودنِ فیلد به `Lang` دکمه‌های در پرواز را می‌شکند (اندازه‌گیری‌شده روی
    aiogram 3.30: `unpack('lang:fa')` روی کلاسِ دوفیلدی `TypeError` می‌دهد،
    حتی با مقدارِ پیش‌فرضِ پایتونی). پس دکمهٔ کهنه باید هنوز باز شود."""
    assert Lang.unpack("lang:fa").code == "fa"
    assert set(Lang.model_fields) == {"code"}


def test_every_callback_this_flow_emits_fits_the_64_byte_cap():
    from app import keyboards

    longest = max(len(Nav(to=to).pack())
                  for to, _k in keyboards.HOME_ITEMS + keyboards.SETTINGS_ITEMS)
    longest = max(longest, len(Nav(to="home").pack()),
                  len(Lang(code="z" * 16).pack()))
    assert longest <= 64, longest
