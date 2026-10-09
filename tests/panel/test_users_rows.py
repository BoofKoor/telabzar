"""`/users` — جدول وضعیتِ بلاک را می‌گفت، **هویت** را نه.

اندازه‌گیری روی `f00d37e`: دو نگهبانِ محتوا داشت (`test_blocking_a_user_shows_up_
immediately` و جفتش)، و هر دو فقط دربارهٔ بجِ «بلاک/فعال» بودند. سابوتاژِ
ریزدانه سه حذفِ **خاموش** پیدا کرد: شناسهٔ تلگرام، شمارِ کل، و کلِ صفحه‌بندی.

یعنی جدول می‌توانست ردیف‌هایی بدهد که وضعیتشان درست است و معلوم نیست **مالِ
کی**‌اند. برای صفحه‌ای که تنها ابزارِ بلاک‌کردن است، این از خالی‌بودن بدتر است.

عمداً فایلِ جدا از `test_users_page.py`: آن‌جا دربارهٔ کش و ایندکس است، این‌جا
دربارهٔ چیزی که رندر می‌شود — همان تفکیکی که `test_scope_labels` و
`test_cookie_status_badges` هم دارند.
"""
from __future__ import annotations

from pagefacts import shows
from test_panel_css_classes import _fetch


def _f():
    from app.admin_web import Fmt
    return Fmt("fa")


def _row(html: str, tg: int) -> str:
    """ردیفِ جدولِ همین کاربر — از `<tr` تا `</tr>`ی که شناسه‌اش را دارد."""
    at = html.index(f'<bdi class="mono">{tg}</bdi>')
    return html[html.rindex("<tr", 0, at):html.index("</tr>", at)]


async def test_each_row_reports_the_telegram_id_it_is_about(seeded):
    """بدونِ شناسه، دکمهٔ «مسدود کردن» روی ردیفی می‌نشیند که معلوم نیست کیست."""
    shows(await _fetch(seeded, "/users"), 901, 902)


async def test_each_row_reports_its_file_count(seeded):
    """ستونی که تصمیمِ ادمین را می‌سازد: این کاربر چقدر کار کرده.

    ستونِ «نقش» از بازطراحیِ ۲۰۲۶-۱۰ نیست: `User.role` همیشه `"user"` است (§۳)،
    پس ستونی بود که هیچ‌وقت چیزی نمی‌گفت. ادعا **به ردیف** محدود است: «۵» هرجای
    صفحه می‌تواند باشد (شمارِ اعلان، عمقِ صف).
    """
    html = await _fetch(seeded, "/users")
    f = _f()
    # کاربرِ ۹۰۱ پنج فایل دارد (۴ دانلودی + ۱ آپلودی)، ۹۰۲ هیچ.
    assert f'data-l="{f.t("us.col.files")}">{f.num(5)}</td>' in _row(html, 901)
    assert f'data-l="{f.t("us.col.files")}">{f.num(0)}</td>' in _row(html, 902)


async def test_the_header_counts_total_active_and_blocked(seeded):
    """سه عددِ متفاوت که نباید یکی شوند — از همان تابعی که صفحه می‌خواند."""
    from app import panel_data as PD

    d = await PD.users_list("", "", "", "seen", 1)
    assert (d["all"], d["blocked"]) == (2, 1), f"پیش‌شرطِ کاشت: {d['all']}/{d['blocked']}"
    f = _f()
    shows(await _fetch(seeded, "/users"),
          f.t("us.sub", n=f.num(d["all"]), a=f.num(d["active7"]), b=f.num(d["blocked"])))


async def test_the_pager_states_where_the_admin_is(seeded):
    """صفحه‌بندی بدونِ موقعیت یعنی ادمین نمی‌داند چیزی جا مانده یا نه."""
    f = _f()
    shows(await _fetch(seeded, "/users"), f.t("c.range", a=f.num(1), b=f.num(2), n=f.num(2)))


async def test_the_blocked_filter_shows_only_the_blocked(seeded):
    """فیلترِ وضعیت واقعاً فیلتر می‌کند: یک ردیف، و همان کاربرِ مسدود."""
    html = await _fetch(seeded, "/users?st=blocked")
    assert html.count('<tr class="click"') == 1
    assert html.count('name="action" value="unblock"') == 1


async def test_a_search_that_matches_nothing_says_so(seeded):
    """کنترلِ معکوس: جدولِ تهی باید حرف بزند نه اینکه صفحه لخت شود."""
    shows(await _fetch(seeded, "/users?q=99999999"), _f().t("c.no_results"))
