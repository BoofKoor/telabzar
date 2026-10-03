"""فاز ۴ / موردِ ۱۴ — mimeِ فایل همان بایت‌هایی باشد که گیت‌وی سرو می‌کند.

دو باگ با یک ریشه: `File.mime` هرگز از خروجی خوانده نمی‌شد.

1. بعد از تبدیل (PDF→TXT، DOCX→PDF، تبدیلِ ویدیو) ردیف همان mimeِ قدیمی را
   نگه می‌داشت، پس `/s/` بایت‌های تازه را با `Content-Type`ِ کهنه سرو می‌کرد.
2. هر ردیفی که دانلود یا کارتِ spawn می‌ساخت `mime=None` داشت، و از فاز ۱
   گیت‌وی mimeِ خالی را **attachment** می‌کند — یعنی لینکِ `/s/`ِ ویدیوی دانلودی
   به‌جای پخش در مرورگر دانلود می‌شد. (این دومی رگرسیونِ خودِ فاز ۱ بود.)

رفع: mime از پیامی که تلگرام واقعاً نگه داشت (`message_media_mime`)، و در گیت‌وی
برای ردیف‌های قدیمیِ بی‌mime حدس از نام — که باز از فهرستِ امنِ inline رد می‌شود.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import gateway as G
from app import tasks as T
from app import tasks_download as TD
from app.filetypes import mime_from_name
from app.models import Base, File, Job, User
from tests.test_upload_ceiling import (  # noqa: F401 — `env` یک fixture است
    CARD_MID, CHAT, UNDER_MB, Bot, _install_result, env)


def _replying(media_attr: str, mime: str):
    """باتی که پیامِ ارسال‌شده را با رسانه و mimeِ مشخص برمی‌گرداند."""

    class _Media:
        file_id = "NEWFID"
        file_unique_id = "NEWU"
        mime_type = mime

    class B(Bot):
        def _on(self, name, payload):
            super()._on(name, payload)

            class M:
                message_id = CARD_MID
                document = video = audio = animation = voice = video_note = photo = None
            setattr(M, media_attr, _Media())
            return M()
    return B()


async def _run(env, monkeypatch, shape, bot):
    maker, (job_id, file_id) = env
    _install_result(monkeypatch, shape, UNDER_MB)
    async with maker() as s:
        f = await s.get(File, file_id)
        f.mime = "application/pdf"            # ورودیِ «قبل از تبدیل»
        await s.commit()
    await T.run_op({"bot": bot, "redis": None}, job_id, CHAT, CARD_MID, "fa")
    async with maker() as s:
        return await s.get(Job, job_id), await s.get(File, file_id), maker


async def test_a_converted_file_carries_the_new_mime(env, monkeypatch):
    shape = lambda out: {"path": out, "filename": "doc.txt", "label": "L"}  # noqa: E731
    job, file, _ = await _run(env, monkeypatch, shape, _replying("document", "text/plain"))
    assert job.status == "done"
    assert file.mime == "text/plain", f"mime کهنه ماند: {file.mime}"


async def test_a_failed_delivery_restores_the_old_mime(env, monkeypatch):
    """کنترل: روی شکستِ ارسال، فایلِ اصلی (و mimeش) دست‌نخورده می‌ماند."""
    class Failing(Bot):
        def _on(self, name, payload):
            if name in ("edit_message_media", "send_document", "send_video"):
                raise RuntimeError("network down")
            return super()._on(name, payload)
    shape = lambda out: {"path": out, "filename": "doc.txt", "label": "L"}  # noqa: E731
    job, file, _ = await _run(env, monkeypatch, shape, Failing())
    assert job.status == "failed"
    assert file.mime == "application/pdf"


async def test_a_spawned_card_has_a_mime(env, monkeypatch):
    shape = lambda out: {"spawn": {"path": out, "name": "a.mp3", "kind": "audio"},  # noqa: E731
                         "label": "L"}
    job, _file, maker = await _run(env, monkeypatch, shape, _replying("audio", "audio/mpeg"))
    from sqlalchemy import select
    async with maker() as s:
        new = (await s.execute(select(File).where(File.name == "a.mp3"))).scalar_one()
    assert job.status == "done"
    assert new.mime == "audio/mpeg"


@pytest_asyncio.fixture
async def dl_db(tmp_path, monkeypatch):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'd.db'}")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        u = User(tg_user_id=42, role="user")
        s.add(u)
        await s.commit()
        uid = u.id
    monkeypatch.setattr(TD, "Sessionmaker", maker)

    async def _meta(path, kind, info, thumb):
        return path, info, thumb
    monkeypatch.setattr(TD, "_media_meta", _meta)
    yield maker, uid
    await eng.dispose()


async def test_a_downloaded_file_has_a_mime(dl_db, tmp_path):
    """پیش از رفع `mime=None` — و گیت‌وی آن را attachment می‌کرد."""
    maker, uid = dl_db
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"x" * 64)
    err = await TD._spawn(_replying("video", "video/mp4"), 7, uid, str(p), "clip.mp4",
                          "video", {}, "fa")
    assert err is None
    from sqlalchemy import select
    async with maker() as s:
        row = (await s.execute(select(File))).scalar_one()
    assert row.mime == "video/mp4"


# ── گیت‌وی: ردیف‌های قدیمیِ بی‌mime ─────────────────────────────────────
class _TgFile:
    def __init__(self, path):
        self.file_path = path


class _GBot:
    def __init__(self, path):
        self.path = path

        class _S:
            async def close(self):
                return None
        self.session = _S()

    async def get_file(self, _fid):
        return _TgFile(self.path)


@pytest.mark.parametrize("name,want_inline", [
    ("clip.mp4", True), ("song.mp3", True), ("evil.html", False), ("pic.svg", False),
], ids=["video", "audio", "html", "svg"])
async def test_an_old_row_without_mime_streams_by_name(tmp_path, monkeypatch, name, want_inline):
    p = tmp_path / "blob"
    p.write_bytes(b"\x00" * 32)
    G._meta_cache.clear()

    async def lookup(token):
        return File(ref="r", owner_id=1, file_unique_id="u", file_id="F", kind="video",
                    name=name, mime=None, dl_token=token)
    monkeypatch.setattr(G, "_lookup", lookup)
    app = G.build_app()
    app["bot"] = _GBot(str(p))
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/s/tok1")
        await resp.read()
    disp = resp.headers.get("Content-Disposition", "")
    assert disp.startswith("inline") is want_inline, disp
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_mime_from_name_does_not_depend_on_the_host_table():
    """`.mkv`/`.opus`/`.m4a` در `/etc/mime.types`ِ ایمیجِ slim تضمین‌شده نیستند."""
    assert mime_from_name("a.mkv") == "video/x-matroska"
    assert mime_from_name("a.opus") == "audio/ogg"
    assert mime_from_name("a.M4A") == "audio/mp4"
    assert mime_from_name("noext") is None
    assert mime_from_name(None) is None
    assert os.path.splitext("x.tar.gz")[1] == ".gz"
