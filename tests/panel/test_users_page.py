"""صفحهٔ کاربران: ایندکسِ `last_seen` و کشِ صفحه (C-4).

**اعدادِ زیر روی Postgres 16.13 واقعی گرفته شده‌اند، نه SQLite** — `_MIGRATIONS`
نحوِ Postgres است و CI اصلاً Postgres ندارد (Open Questions همین را ثبت کرده).
پس این فایل *اثرِ* ایندکس را نمی‌سنجد؛ آن اندازه‌گیری دستی است و در پیامِ کامیت
و §۷ ثبت شده. چیزی که این‌جا سنجیده می‌شود کشِ صفحه و **همگام‌ماندنِ** ایندکس با
کوئری‌ای است که قرار است سریعش کند.

    ۱۶۶۸ ردیف (اندازهٔ امروزِ تولید): ساختِ ایندکس ۲٫۳–۳٫۴ ms
    ۲۰۰٬۰۰۰ ردیف: `Sort` → `Index Scan Backward`؛ کوئریِ صفحه ۳۷ → ۰٫۴۵ ms
    و تفکیکِ هزینه در همان مقیاس: دو `count(*)` روی‌هم ۲۵٫۳ ms در برابرِ
    ۰٫۴۵ ms برای کوئریِ صفحه — یعنی ۹۶٪ کارِ صفحه چیزی است که **کش**
    برمی‌داردش، نه ایندکس.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.models import User

_SRC = pathlib.Path("app/admin_web.py").read_text(encoding="utf-8")


async def _seed(panel, n: int = 3) -> list[int]:
    ids = []
    async with panel.aw.Sessionmaker() as s:
        for i in range(n):
            u = User(tg_user_id=500_000 + i, role="user", is_blocked=False)
            s.add(u)
        await s.commit()
        for i in range(n):
            row = await s.scalar(
                __import__("sqlalchemy").select(User).where(User.tg_user_id == 500_000 + i))
            ids.append(row.id)
    return ids


def _blocked_rows(body: str) -> int:
    """تعدادِ ردیف‌هایی که صفحه **بلاک‌شده** نشان می‌دهد.

    دکمهٔ «رفعِ بلاک» فقط برای کاربرِ بلاک‌شده رندر می‌شود؛ اندازه‌گیری‌شده روی
    خودِ صفحه با ۱ بلاک از ۳ کاربر: `رفعِ بلاک`→۱ · `فعال`→۲ · `>بلاک<`→۳.
    آن سومی تمایزدهنده **نیست** (هم در بج و هم در دکمهٔ کاربرِ آزاد می‌آید) و
    دقیقاً همین‌جور شرطِ سستی بود که سابوتاژ نسخهٔ اولِ این تست را رد کرد.
    """
    return body.count("رفعِ بلاک")


async def _users(panel, **q):
    qs = ("?" + "&".join(f"{k}={v}" for k, v in q.items())) if q else ""
    return await panel.client.get("/users" + qs, cookies=panel.cookies,
                                  allow_redirects=False)


@pytest.fixture
def counted(panel, monkeypatch):
    """می‌شمارد چند بار واقعاً به دیتابیس رفته‌ایم."""
    calls: list[tuple[int, str]] = []
    real = panel.aw._users_list

    async def spy(page, q):
        calls.append((page, q))
        return await real(page, q)

    monkeypatch.setattr(panel.aw, "_users_list", spy)
    return calls


# ── کش ────────────────────────────────────────────────────────────────────
async def test_a_repeat_load_does_not_hit_the_database(panel, counted):
    await _seed(panel)
    await _users(panel)
    await _users(panel)
    assert len(counted) == 1, f"صفحه {len(counted)} بار به دیتابیس رفت"


async def test_different_pages_and_queries_are_cached_separately(panel, counted):
    await _seed(panel)
    await _users(panel)
    await _users(panel, page=1)
    await _users(panel, q=500000)
    assert len(counted) == 3
    for _ in range(2):                       # همه از کش
        await _users(panel)
        await _users(panel, page=1)
        await _users(panel, q=500000)
    assert len(counted) == 3, f"کش به تفکیک نگه نداشت: {counted}"


async def test_the_cache_expires_on_the_modelled_clock(panel, clock, counted):
    await _seed(panel)
    await _users(panel)
    clock.advance(panel.aw._USERS_TTL - 1)
    await _users(panel)
    assert len(counted) == 1, "کش زودتر از موعد پرید"
    clock.advance(2)
    await _users(panel)
    assert len(counted) == 2, "کش پس از گذشتنِ TTL تازه نشد"


# ── درستی: کش نباید دربارهٔ کاری که همین الان انجام شد دروغ بگوید ─────────
async def test_blocking_a_user_shows_up_immediately(panel):
    """ادعای باربر — بدونِ باطل‌سازی، این کش یک باگِ دیدنی می‌سازد.

    ادمین «بلاک» را می‌زند، به `/users` ریدایرکت می‌شود و همان کاربر را هنوز
    آزاد می‌بیند. یعنی کش صفحه را از «کند» به **غلط** می‌برد، که بدتر است.
    """
    ids = await _seed(panel)
    assert _blocked_rows(await (await _users(panel)).text()) == 0   # کش را گرم کن

    r = await panel.client.post("/users/block", cookies=panel.cookies,
                                data={"id": str(ids[0]), "action": "block"},
                                allow_redirects=False)
    assert r.status == 302
    async with panel.aw.Sessionmaker() as s:
        assert (await s.get(User, ids[0])).is_blocked, "پیش‌شرط: بلاک در دیتابیس ننشست"

    assert _blocked_rows(await (await _users(panel)).text()) == 1, \
        "صفحه پس از بلاک هنوز نمای کهنه را نشان می‌دهد"


async def test_unblocking_is_visible_immediately_too(panel):
    ids = await _seed(panel)
    async with panel.aw.Sessionmaker() as s:
        u = await s.get(User, ids[0])
        u.is_blocked = True
        await s.commit()
    assert _blocked_rows(await (await _users(panel)).text()) == 1   # کش را گرم کن

    r = await panel.client.post("/users/block", cookies=panel.cookies,
                                data={"id": str(ids[0]), "action": "unblock"},
                                allow_redirects=False)
    assert r.status == 302
    async with panel.aw.Sessionmaker() as s:
        assert not (await s.get(User, ids[0])).is_blocked

    assert _blocked_rows(await (await _users(panel)).text()) == 0, \
        "صفحه پس از رفعِ بلاک هنوز نمای کهنه را نشان می‌دهد"


# ── تخریب‌ناپذیری ─────────────────────────────────────────────────────────
async def test_the_cache_degrades_to_a_plain_query_without_redis(panel, counted):
    """کش یک بهینه‌سازی است و نبودِ Redis نباید مسیر را بشکند.

    ادعا روی **خودِ `_users_cached`** است نه روی صفحه، و این تفکیک با اجرا
    آمد: نسخهٔ اولِ همین تست کلیدِ `redis` را از اپ برمی‌داشت و صفحه با
    `KeyError` می‌افتاد — ولی از `_pill_ok` که این تغییر لمسش نکرده و در تولید
    هم هرگز کلیدِ غایب نمی‌بیند (`_on_startup` همیشه ستش می‌کند). یعنی تست
    داشت چیزی را می‌سنجید که ادعایش نبود.
    """
    await _seed(panel)

    class NoRedis(dict):
        pass

    data = await panel.aw._users_cached(NoRedis(), 0, "")
    assert data["total"] >= 3
    assert len(counted) == 1

    # و خطای Redis هم نباید بالا بیاید: باطل‌سازی روی `None` بی‌صداست.
    await panel.aw._users_cache_bust(None)


async def test_a_cached_page_renders_the_same_thing(panel):
    """کنترل: مسیرِ کش نباید محتوا را عوض کند."""
    await _seed(panel)
    first = await (await _users(panel)).text()
    second = await (await _users(panel)).text()
    assert first == second


# ── ضدِ پوسیدگی: ایندکس و کوئری باید هم‌داستان بمانند ────────────────────
def test_the_index_matches_the_column_the_page_orders_by():
    """ایندکسی که کوئری از آن استفاده نکند، وزنِ مرده است.

    اگر روزی ترتیبِ صفحه به ستونِ دیگری برود، `ix_users_last_seen` بی‌مصرف
    می‌شود و هیچ‌چیز خبر نمی‌دهد — همان شکلِ «قاعده‌ای که در N نقطه دست‌نویس
    شده» که §۷ ثبت کرده. سورس با AST خوانده می‌شود، نه import: `app.db` سرِ
    import به Postgres وصل می‌شود.
    """
    migrations = pathlib.Path("app/db.py").read_text(encoding="utf-8")
    assert "CREATE INDEX IF NOT EXISTS ix_users_last_seen ON users (last_seen)" in migrations

    tree = ast.parse(_SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_users_list")
    ordered = [n.attr for n in ast.walk(fn)
               if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load)
               and isinstance(n.value, ast.Attribute) and n.value.attr == "last_seen"]
    assert "desc" in ordered, "صفحه دیگر با last_seen مرتب نمی‌شود — ایندکس را هم به‌روز کن"
