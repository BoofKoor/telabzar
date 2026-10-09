"""`/buttons` — هر opِ هر نوعِ فایل باید ردیفِ ویرایش بگیرد.

اندازه‌گیری روی `f00d37e`: پنج نگهبانِ محتوا داشت که چهارتایش بنرِ ok/err پس از
ذخیره بود و پنجمی CSP. سابوتاژِ `{% for b in row %}` → `{% for b in [] %}` هیچ
تستی را نینداخت، یعنی کلِ ویرایشگرِ چیدمان می‌توانست بی‌صدا خالی شود.

این صفحه جایی است که §۷ یک از‌دست‌رفتنِ **واقعیِ** داده را ثبت کرده: یک ذخیرهٔ
دسته‌ای از نمای کهنه، overrideهای واقعی را با پیش‌فرض بازنویسی می‌کرد. ردیفی که
رندر نشود در همان ذخیره «حذفِ override» خوانده می‌شود.

هر دو ادعا **کشف‌محور**ند (`OPS_BY_KIND` و `_KIND_ORDER`)، چون فهرستِ دستی
همان چیزی است که §۶ بارها ثبت کرده می‌پوسد — و opِ تازه دقیقاً همان چیزی است
که باید بی‌صدا از قلم نیفتد.

از بازطراحیِ ۲۰۲۶-۱۰ نامِ فنیِ op (`compress`) متنِ دیدنی نیست — ادمین دکمه را با
برچسبش می‌شناسد. پس هویتِ ردیف دو نشانه دارد: `data-op` (همان چیزی که JSِ
جابه‌جایی و فیلدِ `order` از آن می‌خوانند) و `placeholder`ی که برچسبِ **پیش‌فرض**
را نشان می‌دهد، تا دکمه‌ای که برچسبش عوض یا پاک شده هنوز شناختنی باشد.
"""
from __future__ import annotations

import re

import pytest
from pagefacts import shows
from test_panel_css_classes import _fetch


def _kinds() -> list[str]:
    from app.admin_web import _KIND_ORDER
    return list(_KIND_ORDER)


def _kind_label(kind: str) -> str:
    from app.admin_web import Fmt
    return Fmt("fa").kind(kind)


def _rows(html: str) -> list[str]:
    """`data-op`ِ ردیف‌های ویرایشگر، به ترتیبِ صفحه — فقط داخلِ فهرستِ ویرایش."""
    body = html.split('id="be-list"', 1)[1].split("</form>", 1)[0]
    return re.findall(r'class="be-row[^"]*" data-op="([\w-]+)"', body)


def _preview(html: str) -> str:
    """فقط بلوکِ پیش‌نمایشِ کیبورد — از `id="tg-kb"` تا یادداشتِ زیرِ آن."""
    return html.split('id="tg-kb"', 1)[1].split('class="tg-note"', 1)[0]


def test_every_kind_with_a_menu_is_editable():
    """kindی که منو دارد ولی در `_KIND_ORDER` نیست، از پنل ویرایش‌شدنی نیست."""
    from app.keyboards import OPS_BY_KIND

    missing = sorted(k for k, ops in OPS_BY_KIND.items() if ops and k not in _kinds())
    assert not missing, f"این نوع‌ها منو دارند ولی تبِ ویرایش ندارند: {missing}"


@pytest.mark.parametrize("kind", _kinds())
async def test_every_op_of_the_kind_renders_a_row(panel, kind):
    """هر opی که منوی این kind دارد باید ردیفِ ویرایش بگیرد — بی‌استثنا."""
    from app.keyboards import OPS_BY_KIND

    ops = [op for op, _key in OPS_BY_KIND.get(kind, [])]
    if not ops:
        pytest.skip(f"kindِ «{kind}» opی ندارد")
    html = await _fetch(panel, f"/buttons?kind={kind}")
    assert sorted(_rows(html)) == sorted(ops), f"ردیف‌های «{kind}» با منوی کد یکی نیست"
    for op in ops:
        assert f'name="text_{op}"' in html, f"«{op}» جعبهٔ برچسب ندارد"


async def test_every_kind_gets_a_tab(panel):
    """تبِ گم‌شده یعنی منویی که از پنل قابلِ ویرایش نیست."""
    html = await _fetch(panel, "/buttons")
    shows(html, *[_kind_label(k) for k in _kinds()])
    for k in _kinds():
        assert f'href="/buttons?kind={k}' in html, f"تبِ «{k}» لینک ندارد"


async def test_the_selected_kind_is_the_one_rendered(panel):
    """کنترل: تب فقط لینک نیست، واقعاً محتوای صفحه را عوض می‌کند.

    همهٔ تب‌ها روی هر صفحه هستند، پس «نامِ نوع در صفحه هست» چیزی نمی‌گوید.
    ادعای درست: opی که **فقط** مالِ ویدیو است روی صفحهٔ صوت ردیف نمی‌گیرد.
    """
    from app.keyboards import OPS_BY_KIND

    video_only = {o for o, _ in OPS_BY_KIND["video"]} - {o for o, _ in OPS_BY_KIND["audio"]}
    assert video_only, "پیش‌شرط: ویدیو باید opِ اختصاصی داشته باشد"
    rows = set(_rows(await _fetch(panel, "/buttons?kind=audio")))
    assert rows and not rows & video_only, f"صفحهٔ صوت opهای ویدیو را نشان داد: {rows & video_only}"


#: نگهبانِ متن — بی‌همتا، تا «در صفحه هست» واقعاً همین را بگوید.
LABEL = "برچسبِ نگهبانِ ۹۱۷۳"


async def _with_label(panel, kind: str = "video") -> tuple[str, str, str]:
    """یک برچسبِ نگهبان روی اولین opِ این kind بنشان و صفحه را برگردان."""
    from app import textstore
    from app.keyboards import OPS_BY_KIND

    op, key = OPS_BY_KIND[kind][0]
    await textstore.set_text("fa", key, LABEL)
    return op, key, await _fetch(panel, f"/buttons?kind={kind}")


# ── دو لایهٔ **مستقل** که یک واقعیت را نشان می‌دهند ─────────────────────────
# متنِ فعلیِ دکمه دو بار رندر می‌شود: یک‌بار در جعبهٔ ویرایش و یک‌بار در
# پیش‌نمایشِ زنده. با یک ادعای انتها‌به‌انتها («برچسب در صفحه هست») سابوتاژِ
# هر لایه بی‌اثر می‌ماند، چون لایهٔ دیگر آن ادعا را برآورده می‌کند — و از
# بیرون شبیهِ «تستِ ضعیف» است. اندازه‌گیری‌شده: نسخهٔ اولِ این تست دقیقاً
# همین‌طور شکست خورد. پس هر لایه ادعای خودش و سابوتاژِ خودش را دارد.
async def test_the_editor_box_carries_the_current_label(panel):
    """جعبهٔ ویرایش باید متنِ فعلی را داشته باشد.

    این همان نیمه‌ای است که از‌دست‌رفتنِ داده را ممکن می‌کند: جعبهٔ تهی در
    ذخیرهٔ دسته‌ای «این override را پاک کن» معنی می‌دهد — همان باگی که §۷ ثبت
    کرده. پس ادعا روی خودِ `value=` بسته می‌شود، نه روی «جایی در صفحه».
    """
    op, _key, html = await _with_label(panel)
    assert f'name="text_{op}" value="{LABEL}"' in html, (
        f"جعبهٔ ویرایشِ «{op}» متنِ فعلی را حمل نمی‌کند")


async def test_the_live_preview_shows_the_current_label(panel):
    """پیش‌نمایش باید همان چیزی را نشان بدهد که کاربر در تلگرام می‌بیند."""
    _op, _key, html = await _with_label(panel)
    assert LABEL in _preview(html), "پیش‌نمایش برچسبِ فعلی را نشان نمی‌دهد"


async def test_a_renamed_button_is_still_identifiable(panel):
    """برچسبِ پیش‌فرض در `placeholder` می‌ماند — هم هویتِ دکمه، هم معنیِ «خالی».

    ذخیرهٔ جعبهٔ خالی یعنی «برگرد به پیش‌فرض»؛ `placeholder` همان را نشان می‌دهد،
    پس ادمین بعد از پاک‌کردن می‌بیند چه چیزی جایش می‌نشیند.
    """
    from app.admin_web import _text_default

    op, key, html = await _with_label(panel)
    default = _text_default("fa", key)
    assert default and default != LABEL
    assert re.search(rf'name="text_{op}" value="{re.escape(LABEL)}" placeholder="{re.escape(default)}"',
                     html), f"ردیفِ «{op}» برچسبِ پیش‌فرضش را نشان نمی‌دهد"
