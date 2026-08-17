"""درِ ورودیِ لینک: فیلترِ روتر باید هرجای متن دنبالِ URL بگردد، نه فقط اولش.

`app/routers/download.py` هندلرِ لینک را با `F.text.regexp(r"https?://")` ثبت
می‌کرد، و پیش‌فرضِ `magic_filter.regexp` برابرِ **`pattern.match`** است نه
`pattern.search` (شاخهٔ `if mode is None` در `magic_filter/magic.py`) — یعنی
لنگرخورده به موقعیتِ صفر. پس متن باید **با** `http` شروع می‌شد و این‌ها همه رد
می‌شدند:

    Listen to … by … on #SoundCloud\\nhttps://on.soundcloud.com/IdLs5FiDTkS6yljUe0
    Check out this video\\nhttps://youtu.be/…
    اینو برام بگیر https://…
     https://…                      ← فقط یک فاصله

و چون ترتیبِ روترها `start → admin → ops → download → files` است، پیام به
catch-allِ `files.py` می‌افتاد و کاربر در جوابِ یک لینکِ **کاملاً معتبر** پیامِ
«یک فایل بفرست» می‌گرفت — یعنی یک جوابِ فعالانه گمراه‌کننده، نه سکوت.

**چرا این تست در سطحِ فیلتر است و نه `find_url`:** `find_url` از روزِ اول سالم
بود (regexش `.search` می‌زند و `#SoundCloud` قبلِ لینک اذیتش نمی‌کند)، پس تستی
که آن را صدا بزند **از قبل سبز است** و هیچ‌چیز ثابت نمی‌کند. باگ یک لایه
بالاتر بود: اجرا هرگز به `find_url` نمی‌رسید.

**و چرا فیلترِ ثبت‌شده را از خودِ روتر بیرون می‌کشیم و الگو را دوباره
نمی‌نویسیم:** الگوی دست‌نویس در تست یک **کپیِ دوم** از قاعده است و روزی که
سورس عوض شود ساکت می‌ماند — همان «دو کپیِ دست‌نویس از یک قاعده واگرا می‌شوند»
که §۷ برای `remove_cookie_file` ثبت کرده. این‌جا `_link_filter()` همان شیئی را
برمی‌دارد که aiogram در زمانِ اجرا مصرف می‌کند.

**و عمداً هیچ fallbackِ ASTی ندارد.** اگر `app.routers.download` روی رانر import
نشود، این تست باید **بیفتد**؛ اگر بی‌صدا به خواندنِ سورس می‌افتاد، تستی داشتیم
که چیزِ دیگری می‌سنجد و کسی نمی‌فهمد — دقیقاً همان ردهٔ «سندباکس در برابر CI»
که §۶ سه نمونه‌اش را ثبت کرده (`cryptography`، مارکرِ `7z`، هارنسِ `:memory:`).
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest
from aiogram.types import Chat, Message

from app.routers import download

ROOT = Path(__file__).resolve().parents[1]

# لینکِ **واقعیِ** کپی‌شده از دکمهٔ Shareِ اپِ ساندکلاود، با همان متنِ دوخطی‌اش.
SHORT_LINK = "https://on.soundcloud.com/IdLs5FiDTkS6yljUe0"
SOUNDCLOUD_APP_TEXT = (
    "Listen to Siavash - Ghomeishi - Ey - Gharibe by Mossi Hashemi on #SoundCloud\n"
    + SHORT_LINK
)


def _link_filter():
    """فیلترِ **ثبت‌شدهٔ واقعیِ** `on_link` را از روتر بیرون می‌کشد.

    `FilterObject.magic` همان `MagicFilter`ِ اصلی است (aiogram در
    `dispatcher/event/handler.py` نگهش می‌دارد و `callback` را با `resolve`
    عوض می‌کند)، پس این دقیقاً همان شیئی است که در تولید تصمیم می‌گیرد.
    """
    handlers = [h for h in download.router.message.handlers
                if h.callback is download.on_link]
    assert len(handlers) == 1, (
        f"انتظار دقیقاً یک هندلرِ ثبت‌شده برای on_link، {len(handlers)} پیدا شد — "
        "ثبتِ روتر عوض شده و این تست دیگر چیزی را که فکر می‌کند نمی‌سنجد.")
    magics = [f.magic for f in (handlers[0].filters or []) if f.magic is not None]
    assert len(magics) == 1, (
        f"انتظار دقیقاً یک magic-filter روی on_link، {len(magics)} پیدا شد.")
    return magics[0]


def _msg(text: str) -> Message:
    """`Message`ِ **واقعیِ** aiogram، نه داکلی که `.text` را اعلام کند.

    درسِ `tests/aiogram_double.py`: داکلی که قراردادِ خودش را بازنویسی کند شکلِ
    APIِ واقعی را پنهان می‌کند. اگر روزی aiogram نحوهٔ در دسترس بودنِ `.text` را
    عوض کند، این تست باید بفهمد نه اینکه روی یک شیءِ ساختگی سبز بماند.
    """
    return Message(message_id=1, date=datetime.now(timezone.utc),
                   chat=Chat(id=4242, type="private"), text=text)


def _matches(text: str) -> bool:
    return bool(_link_filter().resolve(_msg(text)))


# ── ۱) شکل‌هایی که امروز رد می‌شوند و باید گرفته شوند ──────────────
# هر پنج‌تا روی سورسِ پیش از رفع **می‌افتند**.
@pytest.mark.parametrize("text", [
    pytest.param(SOUNDCLOUD_APP_TEXT, id="soundcloud-app-two-line"),
    pytest.param(" " + SHORT_LINK, id="leading-space"),
    pytest.param("اینو برام بگیر " + SHORT_LINK, id="persian-text-before"),
    pytest.param("Check out this video\nhttps://youtu.be/dQw4w9WgXcQ",
                 id="youtube-two-line-share"),
    pytest.param("track:\n\n" + SHORT_LINK + "\n", id="blank-lines-around"),
])
def test_a_link_anywhere_in_the_text_reaches_the_download_handler(text):
    assert _matches(text), (
        "فیلتر لینکی را که وسط/آخرِ متن است ندید — یعنی هندلرِ دانلود اجرا نمی‌شود "
        "و کاربر در جوابِ یک لینکِ معتبر «یک فایل بفرست» می‌گیرد.")


# ── ۲) کنترلِ مثبت: مسیرِ سالمِ امروز نباید بشکند ────────────────────
# باید **هر دو طرفِ** رفع سبز بماند.
@pytest.mark.parametrize("text", [
    pytest.param(SHORT_LINK, id="bare-short-link"),
    pytest.param("https://soundcloud.com/mossi-hashemi/siavash-ghomeishi",
                 id="bare-full-link"),
    pytest.param("http://example.com/file.pdf", id="bare-http"),
])
def test_a_bare_link_still_reaches_the_handler(text):
    assert _matches(text), "رگرسیون: لینکِ خامِ تک‌خطی از قبل کار می‌کرد."


# ── ۳) کنترلِ منفی: فیلترِ تازه نباید پرحرف شود ─────────────────────
# اگر این‌ها HIT بدهند، رفع بیش از اندازه باز شده. باید هر دو طرف سبز بماند.
@pytest.mark.parametrize("text", [
    pytest.param("سلام", id="plain-greeting"),
    pytest.param("این یک پیامِ بلندِ فارسی است که هیچ لینکی داخلش نیست و باید "
                 "دقیقاً مثلِ قبل به fallback برود.", id="long-text-no-link"),
    pytest.param("http یعنی پروتکلِ انتقالِ ابرمتن", id="word-http-without-scheme"),
    pytest.param("soundcloud.com/mossi-hashemi/track", id="link-without-scheme"),
    pytest.param("", id="empty"),
])
def test_text_without_a_url_still_falls_through(text):
    assert not _matches(text), (
        "فیلتر متنی بدونِ URL را گرفت — این پیام باید به fallbackِ files برود.")


# ── ۴) ترتیبِ روترها: دستورها دزدیده نمی‌شوند ───────────────────────
def _include_order() -> list[str]:
    """ترتیبِ `include_router` در `create_dispatcher` را از سورس می‌خواند.

    ساختِ `Dispatcher`ِ واقعی این‌جا ممکن نیست (`RedisStorage.from_url` می‌خواهد)،
    و ادعای این تست هم دربارهٔ **ترتیبِ ثبت** است نه رفتارِ زمانِ اجرا.
    """
    tree = ast.parse((ROOT / "app" / "bot.py").read_text(encoding="utf-8"))
    order: list[str] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router"
                and node.args
                and isinstance(node.args[0], ast.Attribute)
                and isinstance(node.args[0].value, ast.Name)):
            order.append(node.args[0].value.id)
    return order


def test_commands_carrying_a_link_are_not_stolen_by_the_download_router():
    """`/start …` و `/admin …`ِ حاوی لینک حالا با فیلتر **جور می‌شوند**، ولی
    هرگز به آن نمی‌رسند: روترِ دستورها قبل‌تر ثبت شده و انتشار همان‌جا می‌ایستد
    (`admin_cmd` برای غیرِادمین `return` می‌کند نه `SkipHandler`).

    این تست همان چیزی است که اثرِ جانبیِ `mode="search"` را مهار می‌کند؛ اگر
    روزی کسی ترتیب را عوض کند، این‌جا می‌شکند نه در تولید.
    """
    # پیش‌شرط را پین کن، وگرنه ادعا توخالی است: این متن‌ها **واقعاً** با فیلتر جور می‌شوند.
    assert _matches("/start https://example.com")
    assert _matches("/admin set proxy_url https://squid.example:3128")

    order = _include_order()
    for name in ("start", "admin", "ops", "download", "files"):
        assert name in order, f"روترِ {name} در create_dispatcher ثبت نشده: {order}"
    assert order.index("start") < order.index("download"), (
        "روترِ start باید قبل از download باشد وگرنه /start حاویِ لینک دزدیده می‌شود.")
    assert order.index("admin") < order.index("download"), (
        "روترِ admin باید قبل از download باشد وگرنه /admin حاویِ لینک دزدیده می‌شود.")
    assert order.index("ops") < order.index("download"), (
        "هندلرهای متنیِ ops به حالتِ FSM بند‌ند؛ باید قبل از download بمانند تا "
        "لینکی که وسطِ یک فلو پیست می‌شود در همان فلو بماند.")
    assert order.index("download") < order.index("files"), (
        "download باید قبل از fallbackِ files باشد وگرنه هیچ لینکی هرگز دانلود نمی‌شود.")


# ── ۵) گاردِ کشف‌محور: دامِ پیش‌فرض دوباره برنگردد ──────────────────
def _regexp_calls() -> list[tuple[str, int, set[str]]]:
    """هر فراخوانیِ `.regexp(` زیرِ `app/` → (فایل، خط، نامِ آرگومان‌های کلیدی)."""
    out: list[tuple[str, int, set[str]]] = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "regexp"):
                names = {kw.arg for kw in node.keywords if kw.arg}
                out.append((str(path.relative_to(ROOT)), node.lineno, names))
    return out


def test_every_regexp_filter_states_its_mode_explicitly():
    """پیش‌فرضِ `magic_filter.regexp` برابرِ `match` است، و این دام **پیش‌فرضِ
    کتابخانه** است نه اشتباهِ یک‌بارهٔ ما — پس هندلرِ بعدی هم همان را می‌خورد.

    گارد **کشف‌محور** است نه فهرستِ دستی، به همان دلیلِ `test_ownership` و
    `test_ssrf`: فهرستِ دستی خودش را به‌روز نمی‌کند.
    """
    calls = _regexp_calls()
    assert calls, ("هیچ فراخوانیِ regexp پیدا نشد — یا کاشف خراب است یا فیلتر "
                   "حذف شده؛ در هر دو حالت این گارد دیگر چیزی را محافظت نمی‌کند.")
    bad = [(f, ln) for f, ln, names in calls if not (names & {"mode", "search"})]
    assert not bad, (
        "این فراخوانی‌های regexp حالتشان را صریح نگفته‌اند و پیش‌فرضِ کتابخانه "
        f"(`match`، لنگرخورده به موقعیتِ صفر) را می‌گیرند: {bad}. "
        'برای «هرجای متن بگرد» صریح `mode="search"` بده.')
