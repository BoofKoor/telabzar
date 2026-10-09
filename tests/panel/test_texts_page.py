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

import re

from pagefacts import missing_facts, page_text, shows
from test_panel_css_classes import _fetch

#: مقدارِ نگهبان: عمداً ASCII و بی‌همتاست تا هم در متن پیدا شود هم به‌عنوان
#: کوئریِ جست‌وجو دقیقاً یک آیتم را بگیرد.
SENTINEL = "SENTINEL-9173"


def _some_key() -> str:
    from app import admin_web as aw
    return aw._TEXT_KEYS[0]


def _cats():
    """دسته‌ها و شمارِ هرکدام — از همان تابعی که هندلر صدا می‌زند، نه بازسازیِ دستی."""
    from app import admin_web as aw

    _rows, counts = aw._texts_rows("fa", "", "all", False)
    return aw, counts


async def test_every_category_renders_its_title(panel):
    """کشف‌محور: هر دسته‌ای که صفحه دارد باید تراشه‌اش را با برچسب داشته باشد."""
    aw, counts = _cats()
    real = [c for c in aw._TEXT_CAT_IDS if counts.get(c)]
    assert len(real) >= 3, f"پیش‌شرط: چند دستهٔ ناتهی باید باشد، {real}"
    f = aw.Fmt("fa")
    shows(await _fetch(panel, "/texts"), *[f.t("tx.cat." + c) for c in ("all",) + aw._TEXT_CAT_IDS])


async def test_every_category_states_how_many_keys_it_holds(panel):
    """شمارِ هر دسته روی تراشه‌اش — وگرنه «فهرست خالی شد» دیده نمی‌شود."""
    aw, counts = _cats()
    f = aw.Fmt("fa")
    text = page_text(await _fetch(panel, "/texts"))
    for c in ("all",) + aw._TEXT_CAT_IDS:
        label = f"{f.t('tx.cat.' + c)} {f.num(counts.get(c, 0))}"
        assert label in text, f"تراشهٔ «{c}» شمارش را نمی‌گوید: «{label}»"


def test_no_key_falls_outside_every_category():
    """جمعِ دسته‌ها = کلِ کلیدها؛ کلیدی که در هیچ دسته‌ای نیفتد از فیلتر گم می‌شود."""
    aw, counts = _cats()
    assert counts["all"] == len(aw._TEXT_KEYS)
    assert sum(counts.get(c, 0) for c in aw._TEXT_CAT_IDS) == counts["all"]


_ROW_TAG = re.compile(r'<div class="txt-row[^"]*" data-f="([^"]+)"[^>]*>')


def _rows_shown(html: str) -> tuple[list[str], list[str]]:
    """(کلیدهای دیدنی، کلیدهای پنهان) — هر ردیف رندر می‌شود، فیلتر فقط `hidden` می‌گذارد."""
    shown, hidden = [], []
    for m in _ROW_TAG.finditer(html):
        (hidden if re.search(r"\shidden(?=[\s>])", m.group(0)) else shown).append(m.group(1))
    return shown, hidden


async def test_a_category_filter_shows_exactly_its_keys(panel):
    """تراشه فقط لینک نیست: `?cat=` واقعاً همان تعداد ردیف **نشان** می‌دهد.

    از ۲۰۲۶-۱۰-۰۹ همهٔ ردیف‌ها در صفحه‌اند و فیلتر فقط `hidden` می‌گذارد — تا
    `panel.js` درجا فیلتر کند و ویرایشِ ذخیره‌نشده با عوض‌کردنِ دسته از دست نرود. پس
    ادعا دو نیمه دارد: دیدنی‌ها دقیقاً همان دسته‌اند، و بقیه **هستند** ولی پنهان.
    """
    aw, counts = _cats()
    cat = max(aw._TEXT_CAT_IDS, key=lambda c: counts.get(c, 0))
    shown, hidden = _rows_shown(await _fetch(panel, f"/texts?cat={cat}"))
    assert len(shown) == counts[cat]
    assert {aw._text_cat(k) for k in shown} == {cat}
    assert len(shown) + len(hidden) == len(aw._TEXT_KEYS)


async def test_a_key_is_editable_with_its_current_value(panel):
    """کلید و **مقدارِ فعلی‌اش** هر دو باید رندر شوند.

    فقط کلید کافی نیست: جعبه‌ای که مقدارِ کهنه یا تهی نشان بدهد همان چیزی است
    که یک ذخیرهٔ دسته‌ای را به از‌دست‌رفتنِ داده تبدیل می‌کند.
    """
    from app import textstore

    key = _some_key()
    await textstore.set_text("fa", key, SENTINEL)
    shows(await _fetch(panel, "/texts"), key, SENTINEL)


def _row(html: str, key: str) -> str:
    """مارک‌آپِ ردیفِ همین کلید — از `<div class="txt-row` تا ردیفِ بعدی."""
    at = html.index(f'data-f="{key}"')
    start = html.rindex('<div class="txt-row', 0, at)
    nxt = html.find('<div class="txt-row', at)
    return html[start:nxt if nxt != -1 else len(html)]


async def test_an_edited_key_is_marked_as_edited(panel):
    """ادمین باید بتواند ویرایش‌شده را از پیش‌فرض تفکیک کند — **روی همان ردیف**.

    نشانهٔ دیدنی سه‌تاست: خطِ «پیش‌فرض: …» با متنِ اصلی، دکمهٔ «برگرداندن»، و
    کلاسِ `edited` (نقطهٔ کنارِ کلید). ادعا به ردیف محدود است، چون «ویرایش‌شده» در
    نوارِ ابزار (`فقط ویرایش‌شده‌ها`) و زیرعنوانِ صفحه هم هست — همان «سه منبع برای
    یک توکن» که §۶ ثبت کرده.
    """
    from app import admin_web as aw
    from app import textstore

    key = _some_key()
    other = next(k for k in aw._TEXT_KEYS if k != key)
    await textstore.set_text("fa", key, SENTINEL)
    html = await _fetch(panel, "/texts")
    f = aw.Fmt("fa")
    mine = _row(html, key)
    assert 'class="txt-row edited"' in mine
    shows(mine, f.t("tx.default"), aw._text_default("fa", key), f.t("tx.reset"))
    # کنترلِ معکوس: ردیفِ دست‌نخورده هیچ‌کدام را ندارد
    theirs = _row(html, other)
    assert 'class="txt-row edited"' not in theirs
    assert missing_facts(theirs, [f.t("tx.reset")]) == [f.t("tx.reset")]


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
