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

from pagefacts import page_text, shows
from test_panel_css_classes import _fetch


async def test_each_row_reports_the_telegram_id_it_is_about(seeded):
    """بدونِ شناسه، دکمهٔ «بلاک» روی ردیفی می‌نشیند که معلوم نیست کیست."""
    shows(await _fetch(seeded, "/users"), 901, 902)


async def test_each_row_reports_its_role_and_file_count(seeded):
    """دو ستونی که تصمیمِ ادمین را می‌سازند: نقش، و اینکه چقدر کار کرده."""
    html = await _fetch(seeded, "/users")
    shows(html, "user")
    # کاربرِ ۹۰۱ پنج فایل دارد (۴ دانلودی + ۱ آپلودی)، ۹۰۲ هیچ.
    text = page_text(html)
    assert "901" in text and " 5 " in text, (
        f"شمارِ فایلِ کاربرِ ۹۰۱ رندر نشد — متن: {text[:300]}…")


async def test_the_header_counts_total_and_blocked(seeded):
    """دو عددِ متفاوت که نباید یکی شوند: کلِ کاربران، و چندتاشان بلاک‌اند."""
    shows(await _fetch(seeded, "/users"), "2 کل", "1 بلاک")


async def test_the_pager_states_where_the_admin_is(seeded):
    """صفحه‌بندی بدونِ موقعیت یعنی ادمین نمی‌داند چیزی جا مانده یا نه."""
    shows(await _fetch(seeded, "/users"), "صفحهٔ 1 از 1")


async def test_a_search_that_matches_nothing_says_so(seeded):
    """کنترلِ معکوس: جدولِ تهی باید حرف بزند نه اینکه صفحه لخت شود."""
    shows(await _fetch(seeded, "/users?q=99999999"), "کاربری یافت نشد")
