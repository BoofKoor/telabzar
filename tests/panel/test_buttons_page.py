"""`/buttons` — ردیفِ **هیچ** opی نگهبان نداشت.

اندازه‌گیری روی `f00d37e`: پنج نگهبانِ محتوا داشت که چهارتایش بنرِ ok/err پس از
ذخیره بود و پنجمی CSP. سابوتاژِ `{% for b in row %}` → `{% for b in [] %}` هیچ
تستی را نینداخت، یعنی کلِ ویرایشگرِ چیدمان می‌توانست بی‌صدا خالی شود.

این صفحه جایی است که §۷ یک از‌دست‌رفتنِ **واقعیِ** داده را ثبت کرده: یک ذخیرهٔ
دسته‌ای از نمای کهنه، overrideهای واقعی را با پیش‌فرض بازنویسی می‌کرد. ردیفی که
رندر نشود در همان ذخیره «حذفِ override» خوانده می‌شود.

هر دو ادعا **کشف‌محور**ند (`OPS_BY_KIND` و `_KIND_TABS`)، چون فهرستِ دستی
همان چیزی است که §۶ بارها ثبت کرده می‌پوسد — و opِ تازه دقیقاً همان چیزی است
که باید بی‌صدا از قلم نیفتد.
"""
from __future__ import annotations

import pytest
from pagefacts import shows
from test_panel_css_classes import _fetch


def _kinds():
    from app.admin_web import _KIND_TABS
    return [k for k, _label in _KIND_TABS]


@pytest.mark.parametrize("kind", _kinds())
async def test_every_op_of_the_kind_renders_a_row(panel, kind):
    """هر opی که منوی این kind دارد باید ردیفِ ویرایش بگیرد — بی‌استثنا."""
    from app.keyboards import OPS_BY_KIND

    ops = [op for op, _key in OPS_BY_KIND.get(kind, [])]
    if not ops:
        pytest.skip(f"kindِ «{kind}» opی ندارد")
    shows(await _fetch(panel, f"/buttons?kind={kind}"), *ops)


async def test_every_kind_gets_a_tab(panel):
    """تبِ گم‌شده یعنی منویی که از پنل قابلِ ویرایش نیست."""
    from app.admin_web import _KIND_TABS

    shows(await _fetch(panel, "/buttons"), *[label for _k, label in _KIND_TABS])


async def test_the_selected_kind_is_the_one_rendered(panel):
    """کنترل: تب فقط لینک نیست، واقعاً محتوای صفحه را عوض می‌کند.

    بدونِ این، تستِ بالا با صفحه‌ای که همیشه یک kind را نشان بدهد هم سبز
    می‌ماند — چون فهرستِ opها را از همان kind می‌گیرد.
    """
    from app.admin_web import _KIND_LABEL

    shows(await _fetch(panel, "/buttons?kind=audio"), _KIND_LABEL["audio"])


async def test_each_row_carries_the_current_label_of_its_button(panel):
    """متنِ فعلیِ دکمه باید داخلِ جعبه باشد، نه فقط نامِ op.

    این همان نیمه‌ای است که از‌دست‌رفتنِ داده را ممکن می‌کند: جعبهٔ تهی در
    ذخیرهٔ دسته‌ای «این override را پاک کن» معنی می‌دهد.
    """
    from app import textstore
    from app.keyboards import OPS_BY_KIND

    op, key = OPS_BY_KIND["video"][0]
    await textstore.set_text("fa", key, "برچسبِ نگهبانِ ۹۱۷۳")
    shows(await _fetch(panel, "/buttons?kind=video"), op, "برچسبِ نگهبانِ ۹۱۷۳")
