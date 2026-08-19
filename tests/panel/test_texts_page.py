"""`/texts` — تنها صفحه‌ای که **صفر** نگهبانِ محتوا داشت.

اندازه‌گیری روی `f00d37e`: خالی‌کردنِ کلِ بدنهٔ `_TEXTS` فقط **یک** تست
می‌انداخت، و آن یکی گاردِ کلاس بود که روی کفِ `len(used) >= 15` می‌افتد نه روی
محتوا. یعنی پوششِ واقعی صفر بود. سابوتاژِ ریزدانه هم تأیید کرد: حذفِ **کلِ**
حلقهٔ دسته‌ها هیچ تستی را نینداخت.

این صفحه ~۲۰۵ رشتهٔ رابطِ کاربری را ویرایش‌پذیر می‌کند و §۷ از قبل ثبت کرده که
یک نمای کهنه در همین صفحه چطور می‌تواند overrideهای واقعی را با پیش‌فرض
بازنویسی کند. پس «فهرست بی‌صدا خالی شد» این‌جا فقط زشتی نیست.
"""
from __future__ import annotations

from pagefacts import missing_facts, page_text, shows
from test_panel_css_classes import _fetch

#: مقدارِ نگهبان: عمداً ASCII و بی‌همتاست تا هم در متن پیدا شود هم به‌عنوان
#: کوئریِ جست‌وجو دقیقاً یک آیتم را بگیرد.
SENTINEL = "SENTINEL-9173"


def _some_key() -> str:
    from app import admin_web as aw
    return aw._TEXT_KEYS[0]


async def test_every_category_renders_its_title(panel):
    """کشف‌محور: هر دسته‌ای که `_texts_groups` می‌سازد باید در صفحه باشد."""
    from app import admin_web as aw

    groups = aw._texts_groups("fa", "")
    assert len(groups) >= 3, f"پیش‌شرط: چند دسته باید باشد، {len(groups)} بود"
    shows(await _fetch(panel, "/texts"), *[g["title"] for g in groups])


async def test_every_category_states_how_many_keys_it_holds(panel):
    """شمارِ هر دسته کنارِ عنوانش — وگرنه «فهرست خالی شد» دیده نمی‌شود."""
    from app import admin_web as aw

    html = await _fetch(panel, "/texts")
    text = page_text(html)
    for g in aw._texts_groups("fa", ""):
        assert f"{g['title']} ({g['n']})" in text, (
            f"دستهٔ «{g['title']}» شمارش ({g['n']}) را نمی‌گوید")


async def test_a_key_is_editable_with_its_current_value(panel):
    """کلید و **مقدارِ فعلی‌اش** هر دو باید رندر شوند.

    فقط کلید کافی نیست: جعبه‌ای که مقدارِ کهنه یا تهی نشان بدهد همان چیزی است
    که یک ذخیرهٔ دسته‌ای را به از‌دست‌رفتنِ داده تبدیل می‌کند.
    """
    from app import textstore

    key = _some_key()
    await textstore.set_text("fa", key, SENTINEL)
    shows(await _fetch(panel, "/texts"), key, SENTINEL)


async def test_an_edited_key_is_marked_as_edited(panel):
    """ادمین باید بتواند ویرایش‌شده را از پیش‌فرض تفکیک کند."""
    from app import textstore

    await textstore.set_text("fa", _some_key(), SENTINEL)
    shows(await _fetch(panel, "/texts"), "ویرایش‌شده")


async def test_the_search_narrows_the_list_to_what_matches(panel):
    """جست‌وجو باید واقعاً فیلتر کند، نه اینکه فقط جعبه‌اش رندر شود."""
    from app import admin_web as aw
    from app import textstore

    key = _some_key()
    other = next(k for k in aw._TEXT_KEYS if k != key)
    await textstore.set_text("fa", key, SENTINEL)

    html = await _fetch(panel, f"/texts?q={SENTINEL}")
    shows(html, key, SENTINEL)
    assert missing_facts(html, [other]) == [other], (
        f"جست‌وجوی «{SENTINEL}» باید «{other}» را کنار بگذارد")


async def test_a_search_that_matches_nothing_says_so(panel):
    """کنترلِ معکوس: فهرستِ تهی باید حرف بزند، نه اینکه صفحه لخت شود."""
    shows(await _fetch(panel, "/texts?q=NOTHINGMATCHESTHIS"), "پیدا نشد")


async def test_the_language_switch_changes_what_is_shown(panel):
    """دو زبان دو مجموعه متن‌اند؛ سوییچ باید واقعاً عوضشان کند."""
    from app import textstore

    key = _some_key()
    await textstore.set_text("fa", key, SENTINEL)
    fa = await _fetch(panel, "/texts?lang=fa")
    en = await _fetch(panel, "/texts?lang=en")
    assert missing_facts(fa, [SENTINEL]) == []
    assert missing_facts(en, [SENTINEL]) == [SENTINEL], (
        "overrideِ فارسی نباید در نمای انگلیسی دیده شود")
