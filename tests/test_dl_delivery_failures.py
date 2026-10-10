"""فاز ۲ / موردِ ۸ (سمتِ دانلود) — شکستِ ارسال نباید «دانلود موفق» ثبت شود.

سه تابعِ تحویلِ `tasks_download` هر خطای ارسال را می‌بلعیدند:

    _deliver_single  → ردیفِ `files` یتیم، پیامِ لنگرگاه روی «در حالِ ارسال…»
    _spawn           → ردیفِ `files` یتیم، و فراخوان پیامِ وضعیت را **پاک** می‌کرد
                       — یعنی کاربر نه فایل داشت نه خطا
    _deliver_album   → دستهٔ شکست‌خورده لاگ می‌شد و آیتم‌های رسیده **کش** می‌شدند،
                       پس آلبومِ ناقص برای همیشه از کش بازپخش می‌شد

و فراخوان در هر سه حالت `dlstat:<p>:ok` و `note_exit(ok)` ثبت می‌کرد.

دو سطح (§۶): خودِ توابع روی DBِ واقعی (SQLiteِ فایل‌محور)، و اتصالِ آن‌ها در
`run_download`ِ واقعی با موتورِ اجراییِ جعلیِ **موفق** — فقط مرزِ تحویل جایگزین
شده، چون همان چیزی است که این ادعا درباره‌اش است.
"""
from __future__ import annotations

import json
import os
import stat
import textwrap
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import tasks_download as TD
from app.i18n import t
from app.models import Base, File, User
from tests.aiogram_double import ValidatingBot


class Bot(ValidatingBot):
    def __init__(self, fail_on: set[str] = frozenset()) -> None:
        self.fail_on = set(fail_on)
        self.calls: list[str] = []
        self.edits: list[str] = []

    def _on(self, name, payload):
        self.calls.append(name)
        if name in self.fail_on:
            raise RuntimeError(f"network down during {name}")
        if name in ("edit_message_text", "edit_message_caption"):
            self.edits.append(payload.get("text") or payload.get("caption") or "")
        if name == "send_media_group":
            return []

        class M:
            message_id = 77
            document = video = audio = animation = voice = video_note = None
            photo = None
        return M()


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'd.db'}")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        u = User(tg_user_id=42, role="user")
        s.add(u)
        await s.commit()
        uid = u.id
    monkeypatch.setattr(TD, "Sessionmaker", maker)

    async def _meta(path, kind, info, thumb):          # بی‌ffprobe/Pillow
        return path, info, thumb
    monkeypatch.setattr(TD, "_media_meta", _meta)
    yield maker, uid
    await eng.dispose()


async def _rows(maker) -> int:
    async with maker() as s:
        return (await s.execute(select(func.count()).select_from(File))).scalar_one()


def _file(tmp_path, name="clip.mp4") -> str:
    p = tmp_path / name
    p.write_bytes(b"x" * 64)
    return str(p)


# ── سطحِ ۱: خودِ توابع ────────────────────────────────────────────────
async def test_a_failed_spawn_reports_and_leaves_no_row(db, tmp_path):
    maker, uid = db
    err = await TD._spawn(Bot({"send_video"}), 7, uid, _file(tmp_path), "clip.mp4",
                          "video", {}, "fa")
    assert err and "network down" in err
    assert await _rows(maker) == 0, "ردیفِ کارتِ نرسیده باید پاک شود"


async def test_a_failed_in_place_delivery_reports_and_leaves_no_row(db, tmp_path):
    maker, uid = db
    bot = Bot({"edit_message_media", "send_video"})
    err = await TD._deliver_single(bot, 7, 9, uid, _file(tmp_path), "clip.mp4", "video",
                                   {}, "fa", None, "https://example.com/v", "best")
    assert err and "network down" in err
    assert await _rows(maker) == 0


async def test_a_cache_failure_does_not_undo_a_delivered_card(db, tmp_path, monkeypatch):
    """کش بهینه‌سازی است: شکستش نباید تحویلِ انجام‌شده را «ناموفق» بخواند."""
    maker, uid = db

    async def boom(*a, **kw):
        raise RuntimeError("cache down")
    monkeypatch.setattr(TD.dl_cache, "put_cached", boom)
    err = await TD._deliver_single(Bot(), 7, 9, uid, _file(tmp_path), "clip.mp4", "video",
                                   {}, "fa", None, "https://example.com/v", "best")
    assert err is None
    assert await _rows(maker) == 1


async def test_a_clean_spawn_is_still_a_success(db, tmp_path):
    """کنترل."""
    maker, uid = db
    assert await TD._spawn(Bot(), 7, uid, _file(tmp_path), "clip.mp4",
                           "video", {}, "fa") is None
    assert await _rows(maker) == 1


async def test_a_partly_failed_album_says_so(db, tmp_path):
    """۱۲ آیتم = دو دسته؛ دستهٔ دوم می‌افتد ⇒ خطا با شمارِ نرسیده‌ها."""
    _maker, uid = db
    files = [_file(tmp_path, f"p{i:02}.jpg") for i in range(12)]

    class Half(Bot):
        n = 0

        def _on(self, name, payload):
            if name == "send_media_group":
                Half.n += 1
                if Half.n == 2:
                    raise RuntimeError("network down during send_media_group")
            return super()._on(name, payload)

    _items, err = await TD._deliver_album(Half(), 7, uid, files, None, "fa")
    assert err and err.startswith("2/12 not sent"), err


async def test_a_clean_album_has_no_error(db, tmp_path):
    _maker, uid = db
    files = [_file(tmp_path, f"p{i}.jpg") for i in range(3)]
    _items, err = await TD._deliver_album(Bot(), 7, uid, files, None, "fa")
    assert err is None


# ── سطحِ ۲: اتصال در run_download ────────────────────────────────────
_OK_YTDLP = r'''#!/usr/bin/env python3
import json, os, sys
if "--version" in sys.argv:
    print("2026.07.04"); sys.exit(0)
tmpl = sys.argv[sys.argv.index("-o") + 1]
d = os.path.dirname(tmpl)
os.makedirs(d, exist_ok=True)
open(os.path.join(d, "clip [abc].mp4"), "wb").write(b"x" * 64)
json.dump({"title": "clip", "id": "abc"}, open(os.path.join(d, "clip [abc].info.json"), "w"))
print("dl:100.0%")
'''

_OK_GALLERYDL = r'''#!/usr/bin/env python3
import os, sys
d = sys.argv[sys.argv.index("-D") + 1]
os.makedirs(d, exist_ok=True)
for i in range(int(os.environ.get("FAKE_N", "3"))):
    open(os.path.join(d, "p%d.jpg" % i), "wb").write(b"x" * 64)
'''


@pytest.fixture
def engines(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("yt-dlp", _OK_YTDLP), ("gallery-dl", _OK_GALLERYDL)):
        s = bindir / name
        s.write_text(textwrap.dedent(body))
        s.chmod(s.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setattr(TD.settings, "work_dir", str(tmp_path / "work"))
    monkeypatch.setattr(TD.settings, "safety_enabled", False)   # همان شیءِ config
    monkeypatch.setattr(TD.settings, "dl_rich_posts", False)


def _payload(platform, engine, url):
    return {"ref": "dlv00001", "chat_id": 7, "status_mid": 9, "lang": "fa", "url": url,
            "platform": platform, "engine": engine, "phase": "fetch", "selector": "best",
            "owner_id": 1, "tg_user_id": 42}


async def _stat(redis, platform, ok):
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return int(await redis.get(f"dlstat:{platform}:{'ok' if ok else 'fail'}:{day}") or 0)


async def test_a_failed_single_delivery_tells_the_user(engines, redis, monkeypatch):
    async def fail(*a, **kw):
        return "network down during edit_message_media"
    monkeypatch.setattr(TD, "_deliver_single", fail)
    bot = Bot()
    await TD.run_download({"bot": bot, "redis": redis},
                          _payload("youtube", "ytdlp", "https://www.youtube.com/watch?v=abc"))
    assert bot.edits and t("fa", "dl_failed") in bot.edits[-1], bot.edits[-1:]
    assert await _stat(redis, "youtube", ok=True) == 0, "دانلودِ نرسیده موفق ثبت شد"
    assert await _stat(redis, "youtube", ok=False) == 1


async def test_a_failed_spawn_does_not_delete_the_status_message(engines, redis, monkeypatch):
    """تک‌عکسیِ گالری → شاخهٔ `_spawn`. پیش از رفع، پیامِ وضعیت **پاک** می‌شد —
    کاربر نه فایل داشت نه خطا."""
    monkeypatch.setenv("FAKE_N", "1")
    spawned = []

    async def fail(*a, **kw):
        spawned.append(a)
        return "network down during send_photo"
    monkeypatch.setattr(TD, "_spawn", fail)
    bot = Bot()
    await TD.run_download({"bot": bot, "redis": redis},
                          _payload("pinterest", "gallerydl", "https://www.pinterest.com/pin/1/"))
    assert spawned, "پیش‌شرط: باید واقعاً از شاخهٔ spawn رد شده باشد"
    assert "delete_message" not in bot.calls, "پیامِ وضعیت پاک شد و کاربر هیچ ندید"
    assert t("fa", "dl_failed") in bot.edits[-1]
    assert await _stat(redis, "pinterest", ok=True) == 0


async def test_a_partial_album_is_not_cached_and_not_a_success(engines, redis, monkeypatch):
    cached = []

    async def album(bot, chat_id, owner_id, media_paths, caption, lang, **kw):
        return [{"t": "photo", "id": "A"}], "2/3 not sent: network down"

    async def put_album_cached(*a, **kw):
        cached.append(a)
    monkeypatch.setattr(TD, "_deliver_album", album)
    monkeypatch.setattr(TD.dl_cache, "put_album_cached", put_album_cached)
    bot = Bot()
    await TD.run_download({"bot": bot, "redis": redis},
                          _payload("pinterest", "gallerydl", "https://www.pinterest.com/pin/1/"))
    assert not cached, "آلبومِ ناقص کش شد — برای همیشه ناقص بازپخش می‌شود"
    assert t("fa", "dl_failed") in bot.edits[-1]
    assert "delete_message" not in bot.calls
    assert await _stat(redis, "pinterest", ok=True) == 0


async def test_a_clean_album_is_still_cached_and_a_success(engines, redis, monkeypatch):
    """کنترل."""
    cached = []

    async def album(bot, chat_id, owner_id, media_paths, caption, lang, **kw):
        return [{"t": "photo", "id": "A"}], None

    async def put_album_cached(*a, **kw):
        cached.append(a)
    monkeypatch.setattr(TD, "_deliver_album", album)
    monkeypatch.setattr(TD.dl_cache, "put_album_cached", put_album_cached)
    bot = Bot()
    await TD.run_download({"bot": bot, "redis": redis},
                          _payload("pinterest", "gallerydl", "https://www.pinterest.com/pin/1/"))
    assert cached
    assert "delete_message" in bot.calls
    assert await _stat(redis, "pinterest", ok=True) == 1
