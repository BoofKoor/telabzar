"""تاریخچه — **ثبتِ** هر فایلی که ربات فرستاد، از مسیرهای واقعیِ تحویل.

`test_history_data.py` قاعده‌های پرس‌وجو را می‌سنجد؛ این‌جا ادعا این است که هر مسیرِ
تحویل ردیفِ درست را می‌گذارد — و مهم‌تر، **فقط وقتی تحویل واقعاً انجام شد**:

- خروجیِ چندفایلی/رسانه‌ایِ یک عملیات (`run_op`)، فقط روی موفقیتِ **کامل**؛
- نسخهٔ پیش از یک عملیاتِ درجا، فقط وقتی تلگرام واقعاً فایلِ تازه‌ای گرفت؛
- آلبوم و پستِ Rich، فقط وقتی همه رسید (همان قاعدهٔ کش)؛
- آلبومِ تکراری از کش، بی ردیفِ تازه؛
- آپلودی که باید غربال شود، تا پیش از کارت **پنهان**.

پاسخِ بات `Message`ِ **واقعیِ** aiogram است، چون ثبت `file_id` را از همان پیام
برمی‌دارد (`history.infos_of` → `filetypes.detect`) — داکلی که پیامِ بی‌رسانه برگرداند
همان چیزی است که تست‌های قبلیِ `run_op` می‌دهند و ثبت را عمداً بی‌اثر می‌کند.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from aiogram.types import (
    Animation, Chat, Document, Message, PhotoSize, RichBlockPhoto, RichBlockSlideshow,
    RichBlockVideo, RichMessage, User as TgUser, Video,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import dl_cache
from app import history as H
from app import safety
from app import tasks as T
from app import tasks_download as TD
from app.models import Base, DownloadCache, File, FileVersion, Job, User
from app.routers import files as RF
from tests.aiogram_double import ValidatingBot
from tests.test_upload_ceiling import CARD_MID, CHAT, UNDER_MB, Bot, _sparse, env  # noqa: F401

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def _base(**kw) -> Message:
    return Message(message_id=kw.pop("message_id", 500), date=NOW,
                   chat=Chat(id=CHAT, type="private"), **kw)


def doc_msg(fid: str, uid: str, name: str, size: int = 10) -> Message:
    return _base(document=Document(file_id=fid, file_unique_id=uid, file_name=name,
                                   file_size=size, mime_type="application/pdf"))


def photo_msg(fid: str, uid: str) -> Message:
    return _base(photo=[PhotoSize(file_id=fid + "s", file_unique_id=uid + "s", width=1, height=1),
                        PhotoSize(file_id=fid, file_unique_id=uid, width=8, height=8,
                                  file_size=64)])


def video_msg(fid: str, uid: str, **kw) -> Message:
    return _base(video=Video(file_id=fid, file_unique_id=uid, width=kw.get("w", 4),
                             height=kw.get("h", 4), duration=kw.get("d", 3), file_size=99,
                             mime_type="video/mp4"))


# ══ ۱) run_op ═══════════════════════════════════════════════════════

class ReplyBot(Bot):
    """همان باتِ `test_upload_ceiling` (اعتبارسنج + ضبطِ آپلود)، ولی پاسخ‌ها پیامِ واقعی‌اند."""

    def __init__(self, fail: set[str] = frozenset()) -> None:
        super().__init__()
        self.fail = set(fail)
        self.n = 0
        self.calls: list[str] = []

    def _on(self, name, payload):
        self.calls.append(name)
        if name in self.fail:
            raise RuntimeError(f"network down during {name}")
        stub = super()._on(name, payload)
        self.n += 1
        if name == "send_document":
            doc = payload["document"]
            return doc_msg(f"DOC{self.n}", f"DU{self.n}", getattr(doc, "filename", "x"))
        if name == "send_media_group":
            return [doc_msg(f"DOC{self.n}{i}", f"DU{self.n}{i}", getattr(m.media, "filename", "x"))
                    for i, m in enumerate(payload["media"])]
        if name == "send_animation":
            return _base(animation=Animation(file_id="ANIM", file_unique_id="AU", width=4,
                                             height=4, duration=2, file_name="out.mp4"))
        if name == "edit_message_media":
            return video_msg("NEWFID", "NEWUID")
        return stub


def _two_files(album: bool = False):
    def shape(out):
        second = out + ".2.pdf"
        _sparse(second, UNDER_MB)
        res = {"files": [out, second], "label": "L"}
        if album:
            res["album"] = True
        return res
    return shape


def _install(monkeypatch, shape):
    async def _do_op(bot, op, args, file, inpath, workdir, lang, progress=None, cancel=None,
                     redis=None):
        return shape(_sparse(os.path.join(workdir, "out.pdf"), UNDER_MB))
    monkeypatch.setattr(T, "_do_op", _do_op)


async def _run(env, monkeypatch, shape, bot):
    maker, (job_id, file_id) = env
    _install(monkeypatch, shape)
    # ثبت در نشستِ خودش می‌رود (`record_safely`)، نه نشستِ جاب؛ ضبطِ درون‌حافظه‌ایِ
    # `conftest` این‌جا کنار می‌رود تا خودِ نوشتن در DB سنجیده شود.
    monkeypatch.setattr(H, "record_safely", H._record_safely_real)
    monkeypatch.setattr(H, "Sessionmaker", maker)
    await T.run_op({"bot": bot, "redis": None}, job_id, CHAT, CARD_MID, "fa")
    async with maker() as s:
        job = await s.get(Job, job_id)
        orig = await s.get(File, file_id)
        ops = (await s.execute(select(File).where(File.source == "op")
                               .order_by(File.id))).scalars().all()
        vers = (await s.execute(select(FileVersion))).scalars().all()
    return job, orig, ops, vers


@pytest.mark.parametrize("album", [False, True], ids=["one-by-one", "album"])
async def test_a_multi_file_output_becomes_one_history_group(env, monkeypatch, album):
    job, orig, ops, _v = await _run(env, monkeypatch, _two_files(album), ReplyBot())
    assert job.status == "done"
    assert len(ops) == 2, f"{len(ops)} ردیف — خروجیِ چندفایلی در تاریخچه نیامد"
    assert len({f.group_ref for f in ops}) == 1 and ops[0].group_ref
    assert all(f.owner_id == orig.owner_id and f.file_id.startswith("DOC") for f in ops)
    maker, _ids = env
    async with maker() as s:
        page = await H.list_page(s, orig.owner_id, H.CAT_ALBUM, 1)
    assert page.total == 1, "گروه در «آلبوم‌ها»ی تاریخچه دیده نشد"


async def test_a_partly_failed_output_records_nothing(env, monkeypatch):
    """جابِ ناموفق چیزی به تاریخچه نمی‌دهد — فایلی که کاربر نگرفت آن‌جا نیست."""
    class SecondFails(ReplyBot):
        def _on(self, name, payload):
            if name == "send_document" and self.calls.count("send_document") == 1:
                self.calls.append(name)
                raise RuntimeError("network down during send_document")
            return super()._on(name, payload)

    job, _orig, ops, _v = await _run(env, monkeypatch, _two_files(), SecondFails())
    assert job.status == "failed"
    assert ops == [], "خروجیِ نیمه‌رسیده در تاریخچه ثبت شد"


async def test_a_broken_history_never_fails_a_delivered_job(env, monkeypatch):
    """تاریخچه بعد از commitِ جاب و در نشستِ خودش ثبت می‌شود: اگر نوشتنش نشست را
    **مسموم** کند (flushِ ناموفق → نشستی که rollback می‌خواهد)، جابی که خروجی‌اش رسیده
    همچنان `done` است.

    شکلِ شکست عمداً همین است نه یک `raise`ِ ساده: در طراحیِ قبلی (ثبت در همان تراکنشِ
    جاب، داخلِ `try/except`) استثنا بلعیده می‌شد ولی نشستِ مسموم می‌ماند و commitِ نهاییِ
    جاب می‌ترکید — جاب برای همیشه `running`. یک `raise`ِ ساده آن را نمی‌دید.
    """
    maker, (job_id, _fid) = env
    _install(monkeypatch, _two_files())

    async def poisoned(session, owner_id, infos, **kw):
        session.add(File(ref=None, owner_id=owner_id, file_unique_id="x", file_id="x",
                         kind="video", changelog=[]))         # ref تهی → IntegrityError
        await session.flush()

    monkeypatch.setattr(H, "record_safely", H._record_safely_real)
    monkeypatch.setattr(H, "Sessionmaker", maker)
    monkeypatch.setattr(H, "record_infos", poisoned)
    await T.run_op({"bot": ReplyBot(), "redis": None}, job_id, CHAT, CARD_MID, "fa")
    async with maker() as s:
        job = await s.get(Job, job_id)
    assert job.status == "done" and job.finished_at is not None, (
        f"تاریخچهٔ شکسته جابِ تحویل‌شده را {job.status} جا گذاشت")


async def test_a_media_output_is_recorded_with_its_own_name(env, monkeypatch):
    shape = lambda out: {"send_media": {"as": "animation", "path": out,  # noqa: E731
                                        "filename": "loop.gif"}, "label": "L"}
    job, _orig, ops, _v = await _run(env, monkeypatch, shape, ReplyBot())
    assert job.status == "done"
    assert [(f.file_id, f.name, f.group_ref) for f in ops] == [("ANIM", "loop.gif", None)]


async def test_an_in_place_op_keeps_the_previous_version(env, monkeypatch):
    """نسخهٔ پیش از عملیات می‌ماند — پیامِ آپلودی پاک شده و ردیف بازنویسی می‌شود،
    پس بدونِ این فایلِ اصل برای همیشه می‌رفت."""
    shape = lambda out: {"path": out, "filename": "small.mp4", "label": "🗜"}  # noqa: E731
    job, orig, _ops, vers = await _run(env, monkeypatch, shape, ReplyBot())
    assert job.status == "done"
    assert orig.file_id == "NEWFID" and orig.last_at is not None, "فایل بالای تاریخچه نیامد"
    assert [(v.parent_id, v.file_id, v.file_unique_id, v.name, v.label) for v in vers] == [
        (orig.id, "F0", "u0", "lecture.mp4", None)], "نسخهٔ اصل ثبت نشد"


async def test_a_failed_in_place_op_keeps_no_version(env, monkeypatch):
    shape = lambda out: {"path": out, "filename": "small.mp4", "label": "🗜"}  # noqa: E731
    bot = ReplyBot(fail={"edit_message_media", "send_video", "send_document"})
    job, orig, _ops, vers = await _run(env, monkeypatch, shape, bot)
    assert job.status == "failed"
    assert vers == [], "نسخه‌ای ثبت شد در حالی که فایل عوض نشد"
    assert orig.file_id == "F0" and orig.last_at is None


# ══ ۲) دانلود: آلبوم و پستِ Rich ════════════════════════════════════

class AlbumBot(ValidatingBot):
    def __init__(self, fail_batch: int | None = None) -> None:
        self.batches = 0
        self.fail_batch = fail_batch

    def _on(self, name, payload):
        if name == "send_media_group":
            self.batches += 1
            if self.batches == self.fail_batch:
                raise RuntimeError("network down during send_media_group")
            out = []
            for i, m in enumerate(payload["media"]):
                fid = f"B{self.batches}M{i}"
                out.append(video_msg(fid, "U" + fid) if type(m).__name__ == "InputMediaVideo"
                           else photo_msg(fid, "U" + fid))
            return out
        if name == "send_rich_message":
            return _base(rich_message=RichMessage(blocks=[RichBlockSlideshow(blocks=[
                RichBlockPhoto(photo=[PhotoSize(file_id="RP", file_unique_id="RPU",
                                                width=8, height=8)]),
                RichBlockVideo(video=Video(file_id="RV", file_unique_id="RVU", width=4,
                                           height=4, duration=3)),
            ])]))
        return True


def _media_files(tmp_path, names):
    out = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"x" * 64)
        out.append(str(p))
    return out


async def test_a_delivered_album_is_recorded_as_one_group(tmp_path, history_rows):
    files = _media_files(tmp_path, ["a.jpg", "b.jpg", "c.mp4"])
    _items, err = await TD._deliver_album(AlbumBot(), CHAT, 7, files, "متنِ پست #tag", "fa",
                                          platform="instagram",
                                          source_url="https://www.instagram.com/p/X/")
    assert err is None
    (row,) = history_rows
    assert [i.file_id for i in row["infos"]] == ["B1M0", "B1M1", "B1M2"]
    assert [i.kind for i in row["infos"]] == ["image", "image", "video"]
    assert row["owner_id"] == 7 and row["source"] == "dl" and row["platform"] == "instagram"
    assert row["names"] == ["a.jpg", "b.jpg", "c.mp4"]
    assert row["source_url"] == "https://www.instagram.com/p/X/"
    assert "#tag" not in (row["post_caption"] or ""), "کپشنِ ثبت‌شده باید همان کپشنِ تمیز باشد"


async def test_a_partly_failed_album_is_not_recorded(tmp_path, history_rows):
    files = _media_files(tmp_path, [f"p{i:02}.jpg" for i in range(12)])
    _items, err = await TD._deliver_album(AlbumBot(fail_batch=2), CHAT, 7, files, None, "fa")
    assert err
    assert history_rows == [], "آلبومِ ناقص در تاریخچه ثبت شد"


async def test_a_rich_post_records_the_media_inside_its_blocks(tmp_path, history_rows):
    files = _media_files(tmp_path, ["a.jpg", "b.mp4"])
    await TD._deliver_rich_post(AlbumBot(), CHAT, 7, files, "cap", "fa", platform="instagram",
                                source_url="https://www.instagram.com/p/Y/")
    (row,) = history_rows
    assert [(i.file_id, i.kind) for i in row["infos"]] == [("RP", "image"), ("RV", "video")]
    assert row["platform"] == "instagram" and row["names"] == ["a.jpg", "b.mp4"]


def test_rich_infos_walks_nested_blocks_and_skips_the_rest():
    """اسلایدشو داخلِ اسلایدشو، و پیامی که اصلاً Rich نیست."""
    inner = RichBlockSlideshow(blocks=[RichBlockPhoto(photo=[
        PhotoSize(file_id="small", file_unique_id="s", width=1, height=1),
        PhotoSize(file_id="big", file_unique_id="b", width=9, height=9)])])
    msg = _base(rich_message=RichMessage(blocks=[RichBlockSlideshow(blocks=[inner])]))
    assert [i.file_id for i in H.rich_infos(msg)] == ["big"], "بزرگ‌ترین اندازهٔ عکس باید ثبت شود"
    assert H.rich_infos(_base(text="hi")) == []


# ══ ۳) کش ══════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def db(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'r.db'}")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    mk = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with mk() as s:
        u = User(tg_user_id=42, role="user")
        s.add(u)
        await s.commit()
        uid = u.id
    yield mk, uid
    await eng.dispose()


async def test_a_cached_album_twice_is_still_one_history_group(db):
    mk, uid = db
    async with mk() as s:
        cache = DownloadCache(key="k" * 8, file_id="", kind="album", platform="instagram",
                              post_caption="cap", items=[
                                  {"file_id": "B1M0", "kind": "image"},
                                  {"file_id": "B1M1", "kind": "video"}])
        s.add(cache)
        await s.commit()
        for _ in range(2):
            ok = await dl_cache.deliver_from_cache(AlbumBot(), s, CHAT, uid, cache, "fa",
                                                   source_url="https://ig.example/p/1")
            assert ok
        rows = (await s.execute(select(File).where(File.owner_id == uid))).scalars().all()
    assert len(rows) == 2, f"{len(rows)} ردیف — آلبومِ تکراری از کش دوباره ثبت شد"
    assert {r.source_url for r in rows} == {"https://ig.example/p/1"}
    assert rows[0].last_at is not None, "تحویلِ دوم آلبوم را بالای فهرست نیاورد"


async def test_a_cached_single_file_keeps_the_link_the_user_sent(db):
    mk, uid = db
    async with mk() as s:
        cache = DownloadCache(key="s" * 8, file_id="VIDFID", file_unique_id="VU",
                              kind="video", name="v.mp4", platform="youtube")
        s.add(cache)
        await s.commit()
        assert await dl_cache.deliver_from_cache(ValidatingBot(), s, CHAT, uid, cache, "fa",
                                                 source_url="https://youtu.be/abc")
        f = (await s.execute(select(File).where(File.owner_id == uid))).scalar_one()
    assert f.source_url == "https://youtu.be/abc" and f.source == "dl"


# ══ ۴) آپلودِ در انتظارِ غربال ═════════════════════════════════════

class Pool:
    def __init__(self) -> None:
        self.jobs: list[tuple] = []

    async def enqueue_job(self, *a, **kw):
        self.jobs.append(a)


class UploadBot(ValidatingBot):
    def __init__(self) -> None:
        self.names: list[str] = []

    def _on(self, name, payload):
        self.names.append(name)
        if name == "send_message":
            return _base(text="…", message_id=900)
        return True


def _upload(bot) -> Message:
    return Message(message_id=11, date=NOW, chat=Chat(id=CHAT, type="private"),
                   from_user=TgUser(id=42, is_bot=False, first_name="u"),
                   photo=[PhotoSize(file_id="UPL", file_unique_id="UPLU", width=8, height=8,
                                    file_size=64)]).as_(bot)


@pytest.mark.parametrize("screen", [True, False], ids=["screened", "not-screened"])
async def test_an_upload_is_hidden_until_its_screen_passes(db, monkeypatch, screen):
    mk, uid = db

    async def policy():
        return safety.Policy(enabled=screen, scan_pixels=True)
    monkeypatch.setattr(safety, "load_policy", policy)

    class State:
        async def clear(self):
            return None

    bot, pool = UploadBot(), Pool()
    async with mk() as s:
        user = await s.get(User, uid)
        await RF.on_file(_upload(bot), s, user, "fa", State(), pool)
    async with mk() as s:
        visible = await H.overview(s, uid)
    if screen:
        assert pool.jobs and pool.jobs[0][0] == "run_screen"
        assert visible.counts[H.CAT_ALL] == 0, "آپلودِ غربال‌نشده در تاریخچه دیده شد"
    else:
        assert not pool.jobs and "send_photo" in bot.names
        assert visible.counts[H.CAT_ALL] == 1, "آپلودِ بی‌غربال باید همان لحظه دیده شود"


async def _screen_env(monkeypatch, mk, uid, *, card_fails=False, hit=False):
    async with mk() as s:
        f = File(ref="Held0001", owner_id=uid, file_unique_id="HU", file_id="HF",
                 kind="image", name=None, size=1, changelog=[])
        H.hold_for_screen(f)
        s.add(f)
        await s.commit()
        row_id = f.id
    monkeypatch.setattr(T, "Sessionmaker", mk)

    async def _noop(*a, **kw):
        return None

    async def _card(*a, **kw):
        if card_fails:
            raise RuntimeError("telegram down")

    async def policy():
        return safety.Policy(enabled=True, scan_pixels=True)

    async def localize(bot, fid, workdir):
        return "/tmp/x.jpg"

    async def scan(path, kind, threshold, frames, workdir):
        return (True, 0.99, "FEMALE_GENITALIA_EXPOSED") if hit else (False, 0.0, "")

    monkeypatch.setattr(T, "send_card", _card)
    monkeypatch.setattr(T.textstore, "refresh_if_stale", _noop)
    monkeypatch.setattr(safety, "load_policy", policy)
    monkeypatch.setattr(safety, "scan_file", scan)
    monkeypatch.setattr(safety, "report_block", _noop)
    monkeypatch.setattr(T, "_localize", localize)
    return {"file_id_row": row_id, "chat_id": CHAT, "note_mid": None, "lang": "fa",
            "tg_user_id": 42}


async def test_a_clean_screen_releases_the_upload_after_its_card(db, monkeypatch, tmp_path):
    mk, uid = db
    monkeypatch.setattr(T.settings, "work_dir", str(tmp_path))
    payload = await _screen_env(monkeypatch, mk, uid)
    await T.run_screen({"bot": ValidatingBot(), "redis": None}, payload)
    async with mk() as s:
        assert await H.get_file(s, uid, "Held0001") is not None


async def test_an_upload_whose_card_never_went_out_stays_hidden(db, monkeypatch, tmp_path):
    mk, uid = db
    monkeypatch.setattr(T.settings, "work_dir", str(tmp_path))
    payload = await _screen_env(monkeypatch, mk, uid, card_fails=True)
    with pytest.raises(RuntimeError):
        await T.run_screen({"bot": ValidatingBot(), "redis": None}, payload)
    async with mk() as s:
        assert await H.get_file(s, uid, "Held0001") is None, (
            "کارت نرفت ولی تاریخچه آن را برای «دوباره بفرست» عرضه می‌کند")


async def test_a_blocked_upload_never_reaches_history(db, monkeypatch, tmp_path):
    mk, uid = db
    monkeypatch.setattr(T.settings, "work_dir", str(tmp_path))
    payload = await _screen_env(monkeypatch, mk, uid, hit=True)
    await T.run_screen({"bot": ValidatingBot(), "redis": None}, payload)
    async with mk() as s:
        n = (await s.execute(select(func.count()).select_from(File))).scalar()
        assert n == 0 and (await H.overview(s, uid)).counts[H.CAT_ALL] == 0
