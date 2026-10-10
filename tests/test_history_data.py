"""تاریخچهٔ فایل‌ها — لایهٔ داده (`app/history.py`) روی DBِ واقعی.

چهار ادعای اصلی، هر کدام جدا چون شکستشان بی‌صداست:

1. **فقط چیزی که ربات فرستاده دیده می‌شود.** ردیفِ پنهان، ردیفِ در حالِ ارسال
   (`file_id` تهی)، آپلودِ در انتظارِ فیلترِ محتوا و فایلِ کاربرِ دیگر هیچ‌جا
   نمی‌آیند — نه در شمارش، نه در فهرست، نه با `ref`ِ مستقیم.
2. **تکراری یکی است و حذف/نشان روی همه می‌نشیند.** وگرنه بعد از «حذف» نسخهٔ
   تکراریِ قدیمی‌تر دوباره ظاهر می‌شد — یعنی حذف کار نکرده بود.
3. **گروه یک مورد است** (در «همه»)، ولی اعضایش در دستهٔ نوعِ خودشان جدا می‌آیند؛
   و همان آلبوم که دوباره ثبت شود ردیفِ تکراری نمی‌سازد.
4. **حذف نرم است**: کارتی که در چت مانده هنوز با `crud.get_file_by_ref` کار می‌کند.

DB فایل‌محور است (نه `:memory:`) چون `record_safely` نشستِ خودش را باز می‌کند و
SQLiteِ درون‌حافظه‌ای برای هر اتصال یک DBِ خالیِ تازه می‌دهد.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import crud
from app import history as H
from app.filetypes import FileInfo
from app.models import Base, File, FileVersion, User

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'h.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    mk = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(H, "Sessionmaker", mk)
    yield mk
    await engine.dispose()


@pytest_asyncio.fixture
async def users(maker):
    async with maker() as s:
        a, b = User(tg_user_id=1, role="user"), User(tg_user_id=2, role="user")
        s.add_all([a, b])
        await s.commit()
        return a.id, b.id


_n = 0


def _row(owner: int, *, uid: str | None = None, kind: str = "video", name: str | None = "a.mp4",
         size: int = 100, minutes: int = 0, **kw) -> File:
    """ردیفِ تحویل‌شده. `minutes` = چند دقیقه بعد از `T0` ساخته شد (ترتیبِ قطعی)."""
    global _n
    _n += 1
    ref = kw.pop("ref", f"r{_n:07d}")
    return File(ref=ref, owner_id=owner, file_unique_id=uid if uid is not None else f"u{_n}",
                file_id=kw.pop("file_id", f"F{_n}"), kind=kind, name=name, size=size,
                changelog=kw.pop("changelog", []),
                created_at=T0 + timedelta(minutes=minutes), **kw)


async def _add(maker, *rows) -> list[File]:
    async with maker() as s:
        s.add_all(rows)
        await s.commit()
    return list(rows)


# ══ ۱) فقط چیزی که ربات فرستاده ═════════════════════════════════════

async def test_hidden_inflight_held_and_foreign_rows_never_show(maker, users):
    me, other = users
    held = _row(me, name="held.mp4")
    H.hold_for_screen(held)
    await _add(maker,
               _row(me, ref="Visible1", name="ok.mp4"),
               _row(me, name="hidden.mp4", hidden_at=T0),
               _row(me, name="inflight.mp4", file_id=""),          # کارتِ spawn پیش از ارسال
               held,                                               # آپلودِ غربال‌نشده
               _row(other, ref="Foreign1", name="theirs.mp4"))
    async with maker() as s:
        ov = await H.overview(s, me)
        page = await H.list_page(s, me, H.CAT_ALL, 1)
        assert ov.counts[H.CAT_ALL] == 1 and ov.files == 1
        assert [e.name for e in page.items] == ["ok.mp4"]
        assert await H.get_file(s, me, "Visible1") is not None
        assert await H.get_file(s, me, "Foreign1") is None, "فایلِ کاربرِ دیگر با ref رسید"
        assert await H.get_file(s, me, held.ref) is None, "آپلودِ غربال‌نشده دیده شد"


async def test_a_released_upload_becomes_visible(maker, users):
    me, _ = users
    f = _row(me, ref="Upl00001")
    H.hold_for_screen(f)
    await _add(maker, f)
    async with maker() as s:
        assert await H.get_file(s, me, "Upl00001") is None
        row = await s.get(File, f.id)
        H.release_after_screen(row)
        await s.commit()
        assert await H.get_file(s, me, "Upl00001") is not None


# ══ ۲) تکراری یکی؛ حذف و نشان روی همه ═══════════════════════════════

def test_build_entries_keeps_the_newest_duplicate():
    rows = [_row(1, uid="same", name="old.mp4", minutes=0),
            _row(1, uid="same", name="new.mp4", minutes=5),
            _row(1, uid="other", name="x.mp4", minutes=1)]
    for i, r in enumerate(rows, start=1):
        r.id = i
    out = H.build_entries(rows, collapse=True)
    assert [e.name for e in out] == ["new.mp4", "x.mp4"]


def test_last_at_beats_created_at_in_the_order():
    """عملیاتِ درجا (`touch`) فایلِ قدیمی را بالای فهرست می‌آورد."""
    old, new = _row(1, name="old.mp4", minutes=0), _row(1, name="new.mp4", minutes=10)
    old.id, new.id = 1, 2
    old.last_at = T0 + timedelta(minutes=30)
    assert [e.name for e in H.build_entries([new, old], collapse=True)] == ["old.mp4", "new.mp4"]


def test_rows_without_a_unique_id_do_not_merge():
    """ردیفِ کشِ خیلی قدیمی `file_unique_id` تهی دارد؛ دو تای آن دو فایلِ متفاوت‌اند."""
    a, b = _row(1, uid="", name="a"), _row(1, uid="", name="b")
    a.id, b.id = 1, 2
    assert len(H.build_entries([a, b], collapse=True)) == 2


async def test_hiding_hides_every_duplicate(maker, users):
    """بدونِ این، حذفِ تازه‌ترین ردیف تکراریِ قدیمی‌تر را دوباره ظاهر می‌کرد."""
    me, _ = users
    await _add(maker, _row(me, uid="dup", name="first.mp4", minutes=0),
               _row(me, uid="dup", ref="Dup00002", name="second.mp4", minutes=5))
    async with maker() as s:
        assert [e.ref for e in (await H.list_page(s, me, H.CAT_ALL, 1)).items] == ["Dup00002"]
        assert await H.hide(s, me, "Dup00002", group=False)
        page = await H.list_page(s, me, H.CAT_ALL, 1)
    assert page.total == 0, f"تکراریِ قدیمی دوباره ظاهر شد: {[e.name for e in page.items]}"


async def test_a_star_survives_a_newer_duplicate(maker, users):
    me, _ = users
    await _add(maker, _row(me, uid="dup", ref="Star0001", minutes=0))
    async with maker() as s:
        assert await H.set_star(s, me, "Star0001", True, group=False)
    await _add(maker, _row(me, uid="dup", ref="Star0002", minutes=9))   # همان فایل، دوباره
    async with maker() as s:
        page = await H.list_page(s, me, H.CAT_STAR, 1)
    assert [e.ref for e in page.items] == ["Star0002"]


async def test_a_star_set_on_an_album_member_survives_in_the_kind_view(maker, users):
    """در دستهٔ نوع، تکِ فایل و عضوِ آلبومِ همان فایل یک مورد‌اند؛ برداشتنِ نشان از
    همان‌جا باید هر دو را بزند، وگرنه مورد نشان‌دار می‌ماند."""
    me, _ = users
    await _add(maker,
               _row(me, uid="pic", kind="image", ref="Memb0001", group_ref="gBBBBBBBBBBB",
                    minutes=0),
               _row(me, uid="pic2", kind="image", group_ref="gBBBBBBBBBBB", minutes=0),
               _row(me, uid="pic", kind="image", ref="Solo0001", minutes=5))
    async with maker() as s:
        assert await H.set_star(s, me, "gBBBBBBBBBBB", True, group=True)
        imgs = await H.list_page(s, me, "i", 1)
        solo = next(e for e in imgs.items if e.ref == "Solo0001")
        assert solo.starred, "نشانِ عضوِ آلبوم در مورد یکی‌شدهٔ دستهٔ نوع دیده نشد"
        assert await H.set_star(s, me, "Solo0001", False, group=False)
        imgs = await H.list_page(s, me, "i", 1)
    assert not next(e for e in imgs.items if e.ref == "Solo0001").starred, (
        "برداشتنِ نشان از دستهٔ نوع اثر نکرد")


async def test_every_count_equals_the_length_of_its_list(maker, users):
    """عددِ روی دکمهٔ هر دسته همان تعدادی است که بازکردنش نشان می‌دهد.

    داده عمداً همهٔ لبه‌ها را دارد: تکراری با نشانِ روی ردیفِ قدیمی، آلبوم، آلبومِ
    نشان‌دار، دانلود، و تکراری‌ای که یکی دانلود است و یکی آپلود.
    """
    me, _ = users
    await _add(maker,
               _row(me, uid="d1", kind="video", minutes=0, starred_at=T0),
               _row(me, uid="d1", kind="video", minutes=4),
               _row(me, uid="m1", kind="image", group_ref="gCCCCCCCCCCC", source="dl", minutes=1),
               _row(me, uid="m2", kind="video", group_ref="gCCCCCCCCCCC", source="dl", minutes=1),
               _row(me, uid="m3", kind="image", group_ref="gDDDDDDDDDDD", minutes=2,
                    starred_at=T0),
               _row(me, uid="m4", kind="image", group_ref="gDDDDDDDDDDD", minutes=2),
               _row(me, uid="x1", kind="pdf", source="dl", minutes=3),
               _row(me, uid="x1", kind="pdf", minutes=6),
               _row(me, uid="y1", kind="audio", source="dl", minutes=7))
    async with maker() as s:
        ov = await H.overview(s, me)
        for cat in [H.CAT_ALL, H.CAT_STAR, H.CAT_ALBUM, H.CAT_LINK] + [c for c, _ in H.KIND_CATS]:
            page = await H.list_page(s, me, cat, 1)
            assert page.total == ov.counts[cat], f"دستهٔ {cat}: دکمه {ov.counts[cat]}، فهرست {page.total}"
    assert ov.counts[H.CAT_STAR] == 2, "نشانِ ردیفِ قدیمی‌ترِ تکراری یا آلبومِ نشان‌دار گم شد"


async def test_hide_is_soft_the_old_card_still_works(maker, users):
    me, _ = users
    await _add(maker, _row(me, ref="Card0001"))
    async with maker() as s:
        assert await H.hide(s, me, "Card0001", group=False)
        user = await s.get(User, me)
        assert await crud.get_file_by_ref(s, "Card0001", user) is not None, (
            "حذف از تاریخچه کارتِ موجود در چت را شکست")


async def test_clear_all_empties_the_history(maker, users):
    me, other = users
    await _add(maker, _row(me), _row(me, kind="image"), _row(other))
    async with maker() as s:
        assert await H.clear_all(s, me) == 2
        assert (await H.overview(s, me)).counts[H.CAT_ALL] == 0
        assert (await H.overview(s, other)).counts[H.CAT_ALL] == 1, "پاک‌کردن به دیگری رسید"


async def test_touch_brings_a_hidden_file_back(maker, users):
    """کار روی کارتِ فایلی که از تاریخچه حذف شده = دوباره لازمش دارد."""
    me, _ = users
    await _add(maker, _row(me, ref="Back0001", hidden_at=T0))
    async with maker() as s:
        f = (await s.execute(select(File).where(File.ref == "Back0001"))).scalar_one()
        H.touch(f)
        await s.commit()
        assert await H.get_file(s, me, "Back0001") is not None


# ══ ۳) گروه ═════════════════════════════════════════════════════════

async def test_a_group_is_one_entry_but_its_members_count_in_their_kind(maker, users):
    me, _ = users
    await _add(maker,
               _row(me, kind="image", name="1.jpg", group_ref="gAAAAAAAAAAA", source="dl"),
               _row(me, kind="image", name="2.jpg", group_ref="gAAAAAAAAAAA", source="dl"),
               _row(me, kind="video", name="3.mp4", group_ref="gAAAAAAAAAAA", source="dl"),
               _row(me, kind="image", name="solo.jpg"))
    async with maker() as s:
        ov = await H.overview(s, me)
        allp = await H.list_page(s, me, H.CAT_ALL, 1)
        imgs = await H.list_page(s, me, "i", 1)
        albums = await H.list_page(s, me, H.CAT_ALBUM, 1)
    assert ov.counts[H.CAT_ALL] == 2, "گروه باید یک مورد باشد"
    assert ov.counts["i"] == 3 and ov.counts["v"] == 1 and ov.counts[H.CAT_ALBUM] == 1
    assert ov.counts[H.CAT_LINK] == 1
    group = next(e for e in allp.items if e.is_group)
    assert group.n == 3 and group.size == 300
    assert sorted(e.name for e in imgs.items) == ["1.jpg", "2.jpg", "solo.jpg"]
    assert [e.ref for e in albums.items] == ["gAAAAAAAAAAA"]


async def test_a_group_action_never_touches_another_users_rows(maker, users):
    """نشان/حذفِ گروه از لایهٔ داده — جدا از روتر.

    روتر پیش از این‌ها `get_group` را با مالک صدا می‌زند و برای کاربرِ دیگر چیزی
    نمی‌یابد، پس از آن سطح شکستنِ فیلترِ مالکیتِ **این** لایه دیده نمی‌شد (دفاعِ
    لایه‌ای، §۶). این‌جا همان تابع مستقیم با کاربرِ دیگر صدا زده می‌شود.
    """
    me, other = users
    rows = await _add(maker, _row(me, group_ref="gOWNEROWNERO"), _row(me, group_ref="gOWNEROWNERO"))
    async with maker() as s:
        assert not await H.set_star(s, other, "gOWNEROWNERO", True, group=True)
        assert not await H.hide(s, other, "gOWNEROWNERO", group=True)
        got = (await s.execute(select(File).where(File.id.in_([r.id for r in rows])))).scalars().all()
    assert all(f.starred_at is None and f.hidden_at is None for f in got), (
        "کنشِ گروهیِ کاربرِ دیگر روی ردیف‌های من نشست")


def _info(n: int, kind: str = "image") -> FileInfo:
    return FileInfo(kind, f"FID{n}", f"UID{n}", None, 10 * n, "image/jpeg", width=8, height=8)


async def test_recording_one_file_is_a_single_and_many_are_a_group(maker, users):
    me, _ = users
    async with maker() as s:
        one = await H.record_infos(s, me, [_info(1)], source="op")
        many = await H.record_infos(s, me, [_info(2), _info(3)], source="dl",
                                    names=["a.jpg", "b.jpg"], platform="instagram",
                                    post_caption="cap", source_url="https://x.example/p/1")
    assert one[0].group_ref is None
    assert {f.group_ref for f in many} == {H.group_ref_for(me, ["UID2", "UID3"])}
    assert [f.name for f in many] == ["a.jpg", "b.jpg"]
    assert all(f.source == "dl" and f.platform == "instagram" for f in many)


async def test_the_same_album_recorded_twice_adds_no_rows(maker, users):
    """آلبومِ تکراری از کش: همان گروه بالا می‌آید، ردیفِ تازه ساخته نمی‌شود."""
    me, other = users
    async with maker() as s:
        first = await H.record_infos(s, me, [_info(1), _info(2)], source="dl")
        before = first[0].last_at
        again = await H.record_infos(s, me, [_info(2), _info(1)], source="dl")
        theirs = await H.record_infos(s, other, [_info(1), _info(2)], source="dl")
        n = (await s.execute(select(func.count()).select_from(File))).scalar()
    assert {f.id for f in again} == {f.id for f in first}
    assert again[0].last_at is not None and again[0].last_at != before
    assert theirs[0].group_ref != first[0].group_ref, "دو کاربر یک گروه گرفتند"
    assert n == 4


async def test_long_values_are_clipped_to_the_columns(maker, users):
    """Postgres طول را اعمال می‌کند؛ نوشتنِ بلندتر commitِ کلِ جاب را می‌شکست."""
    me, _ = users
    info = FileInfo("document", "F", "U", "n" * 400, 1, "m" * 300)
    async with maker() as s:
        (f,) = await H.record_infos(s, me, [info], source="op",
                                    source_url="https://x.example/" + "q" * 2000)
    assert len(f.name) == 256 and len(f.mime) == 128 and len(f.source_url) == H.URL_MAX


async def test_record_safely_writes_through_its_own_session(maker, users):
    me, _ = users
    rows = await H._record_safely_real(me, [_info(7)], source="dl")
    async with maker() as s:
        got = (await s.execute(select(File).where(File.file_id == "FID7"))).scalar_one()
    assert rows and got.owner_id == me and got.source == "dl"


async def test_record_safely_swallows_a_broken_database(monkeypatch, users):
    """تاریخچه هرگز تحویلِ انجام‌شده را نمی‌شکند."""
    me, _ = users

    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(H, "Sessionmaker", broken)
    assert await H._record_safely_real(me, [_info(1)], source="dl") == []


# ══ ۴) جست‌وجو ══════════════════════════════════════════════════════

async def test_search_folds_arabic_letters_and_zwnj(maker, users):
    """«گزارش مالي» با یِ عربی و «میشود» بی‌نیم‌فاصله باید پیدا شوند."""
    me, _ = users
    await _add(maker,
               _row(me, kind="pdf", name="گزارش مالی ۱۴۰۵.pdf"),
               _row(me, kind="image", name=None, post_caption="این ویدیو می‌شود دید"),
               _row(me, kind="audio", name="song.mp3"))
    async with maker() as s:
        a = await H.list_page(s, me, H.CAT_SEARCH, 1, query="مالي")
        b = await H.list_page(s, me, H.CAT_SEARCH, 1, query="میشود")
        c = await H.list_page(s, me, H.CAT_SEARCH, 1, query="SONG")
    assert [e.name for e in a.items] == ["گزارش مالی ۱۴۰۵.pdf"]
    assert b.total == 1 and c.total == 1


def test_the_bot_and_the_panel_fold_with_one_rule():
    """دو کپیِ دست‌نویسِ یک قاعده واگرا می‌شوند؛ پنل باید همان تابع را صدا بزند."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "app" / "admin_web.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    assert not any(isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_FOLD"
                                                       for t in n.targets)
                   for n in ast.walk(tree)), "admin_web جدولِ تاکردنِ خودش را دوباره ساخت"
    assert any(isinstance(n, ast.ImportFrom) and n.module == "textfold"
               for n in ast.walk(tree))


# ══ ۵) صفحه‌بندی و نسخه‌ها ══════════════════════════════════════════

def test_a_page_past_the_end_lands_on_the_last_page():
    entries = H.build_entries([_row(1, minutes=i) for i in range(20)], collapse=True)
    page = H.paginate(entries, 99)
    assert page.page == page.pages == 3 and len(page.items) == 20 - 2 * H.PAGE_SIZE


async def test_the_scan_cap_is_announced_not_silent(maker, users, monkeypatch):
    me, _ = users
    monkeypatch.setattr(H, "SCAN_MAX", 3)
    await _add(maker, *[_row(me, minutes=i) for i in range(5)])
    async with maker() as s:
        ov = await H.overview(s, me)
    assert ov.capped and ov.files == 3


async def test_a_version_is_restored_as_a_new_card_row(maker, users):
    me, other = users
    (f,) = await _add(maker, _row(me, ref="Ver00001", name="cut.mp4", file_id="NEW",
                                  changelog=["✂️ برش"], source="dl", platform="youtube"))
    async with maker() as s:
        s.add(H.version_row(f.id, file_id="ORIG", file_unique_id="uo", kind="video",
                            mime="video/mp4", name="orig.mp4", size=900, width=None,
                            height=None, duration=60, changelog=[]))
        await s.commit()
        vers = await H.versions(s, me, "Ver00001")
        assert [v.label for v in vers] == [None], "نسخهٔ اول باید «اصل» باشد"
        assert await H.restore_version(s, other, vers[0].id) is None, "نسخهٔ دیگری بازگشت"
        new = await H.restore_version(s, me, vers[0].id)
    assert new.file_id == "ORIG" and new.name == "orig.mp4" and new.ref != "Ver00001"
    assert new.source == "op", "بازگردانی آپلود شمرده می‌شد (پنل: source نه dl و نه op)"
    assert new.platform == "youtube"


def test_a_version_label_is_the_last_step_of_that_version():
    v = H.version_row(1, file_id="x", file_unique_id=None, kind="video", mime=None,
                      name=None, size=None, width=None, height=None, duration=None,
                      changelog=["a", "b"])
    assert v.label == "b" and v.changelog == ["a", "b"] and v.file_unique_id == ""


async def test_versions_only_for_the_owner(maker, users):
    me, other = users
    (f,) = await _add(maker, _row(me, ref="Own00001"))
    async with maker() as s:
        s.add(FileVersion(parent_id=f.id, file_id="X", kind="video"))
        await s.commit()
        assert len(await H.versions(s, me, "Own00001")) == 1
        assert await H.versions(s, other, "Own00001") == []
