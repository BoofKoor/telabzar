"""خودِ هارنس را می‌سنجد — پیش از آنکه چیزی به آن تکیه کند.

اگر هارنس بی‌صدا خراب باشد (مثلاً به Postgresِ پیکربندی‌شده وصل شود یا کوکیِ
سشن را جدی نگیرد)، هر تستِ پنلی که بعداً نوشته شود دربارهٔ **هارنس** حرف می‌زند
نه دربارهٔ پنل. پس این فایل عمداً اول می‌آید.
"""
from __future__ import annotations

import sys


async def test_an_unauthenticated_request_is_redirected_to_login(panel):
    """پایه‌ای‌ترین ادعا: بدونِ کوکی، صفحه سرو نمی‌شود."""
    resp = await panel.client.get("/", allow_redirects=False)
    assert resp.status == 302
    assert resp.headers["Location"] == "/login"


async def test_an_authenticated_request_renders_a_database_backed_page(panel):
    """`/users` به DB می‌زند، پس ۲۰۰ گرفتن یعنی وصلهٔ `Sessionmaker` واقعاً کار کرد."""
    resp = await panel.client.get("/users", cookies=panel.cookies)
    assert resp.status == 200
    body = await resp.text()
    assert "کاربران" in body


async def test_the_harness_is_not_secretly_talking_to_postgres(panel):
    """کنترلِ منفیِ خودِ هارنس.

    اگر وصله کاری نمی‌کرد، تستِ بالا هم سبز می‌ماند **به شرطی که** یک Postgres
    اتفاقاً در دسترس باشد — و آن‌وقت سبزی دربارهٔ محیط حرف می‌زند نه دربارهٔ کد
    (همان ردهٔ §۶). پس صریح می‌سنجیم که پیکربندیِ ماژول هنوز Postgres است و
    چیزی که تست از آن می‌خواند SQLite شده.
    """
    import app.db as db
    from app import admin_web

    assert db.engine.url.drivername.startswith("postgresql"), (
        "پیکربندیِ ماژول باید همان چیزی بماند که conftestِ ریشه ست کرده؛ "
        "اگر این عوض شده یعنی تست دارد محیط را دست‌کاری می‌کند نه ماژول را.")
    assert admin_web.Sessionmaker.kw["bind"].url.drivername.startswith("sqlite")


async def test_the_sessionmaker_holder_list_is_complete(panel, sessionmaker_holders):
    """`_SESSIONMAKER_HOLDERS` باید همهٔ ماژول‌های واقعاً‌بارشده را بپوشاند.

    کشف‌محور است نه فهرستِ دستی: اگر روزی ماژولِ پنجمی `from .db import
    Sessionmaker` کند و در مسیرِ پنل بارگذاری شود، این تست می‌افتد — به‌جای
    اینکه آن ماژول بی‌صدا به Postgresِ واقعی وصل شود و شکستش به هارنس نسبت
    داده شود.
    """
    loaded = {name for name, mod in sys.modules.items()
              if name.startswith("app.") and hasattr(mod, "Sessionmaker")}
    missing = loaded - set(sessionmaker_holders)
    assert not missing, (
        f"این ماژول‌ها نامِ Sessionmaker دارند ولی وصله نمی‌شوند: {sorted(missing)} — "
        f"به _SESSIONMAKER_HOLDERS اضافه‌شان کن.")


async def test_a_session_cookie_for_a_non_admin_is_rejected(panel):
    """عضویت در `admin_id_set` سرِ **هر** درخواست دوباره چک می‌شود."""
    forged = {panel.aw._COOKIE: panel.aw._make_session(999)}
    resp = await panel.client.get("/", cookies=forged, allow_redirects=False)
    assert resp.status == 302
    assert resp.headers["Location"] == "/login"
