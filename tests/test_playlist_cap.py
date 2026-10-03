"""فاز ۳ / موردِ ۳۱ — لینکِ پلی‌لیست/کانال/پروفایل کلِ مجموعه را نکشد.

`--no-playlist` فقط لینکی را می‌گیرد که **هم** ویدیو **هم** پلی‌لیست است
(`watch?v=…&list=…`). لینکِ خالصِ پلی‌لیست هنوز همهٔ آیتم‌ها را دانلود می‌کرد، و
`--max-filesize` سقفِ **هر فایل** است نه مجموع — پس تا پرشدنِ دیسک چیزی جلویش
نبود. gallery-dl هم روی لینکِ پروفایل کلِ پست‌ها را می‌کشید، با کوکیِ اکانت.

yt-dlpِ **واقعی** (همان نسخهٔ پین‌شده در `requirements-dev.txt`) روی یک سرورِ
محلی: اکسترکتورِ generic صفحه‌ای با سه `<video>` را پلی‌لیستِ سه‌تایی می‌خواند —
بی‌نیاز به شبکه، و همان مسیری که هر سایتِ ناشناخته‌ای از آن رد می‌شود.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import textwrap

import pytest
from aiohttp import web

from app import downloader as D

needs_ffmpeg = pytest.mark.ffmpeg
_YTDLP = shutil.which("yt-dlp") or os.path.join(os.path.dirname(sys.executable), "yt-dlp")
needs_ytdlp = pytest.mark.skipif(not os.path.exists(_YTDLP), reason="yt-dlp لازم است")

PAGE = ("<html><head><title>pl</title></head><body>"
        '<video src="v1.mp4"></video><video src="v2.mp4"></video><video src="v3.mp4"></video>'
        "</body></html>")


@pytest.fixture
async def playlist_site(tmp_path, monkeypatch):
    clips = {}
    for i in (1, 2, 3):
        p = tmp_path / f"v{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        "testsrc=size=64x48:rate=10:duration=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)],
                       check=True, capture_output=True, timeout=120)
        clips[f"/v{i}.mp4"] = p.read_bytes()

    async def handle(request: web.Request) -> web.Response:
        if request.path == "/page.html":
            return web.Response(text=PAGE, content_type="text/html")
        body = clips.get(request.path)
        if body is None:
            raise web.HTTPNotFound()
        return web.Response(body=body, content_type="video/mp4")

    app = web.Application()
    app.router.add_get("/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    for var in ("NO_PROXY", "no_proxy"):          # پروکسیِ محیطِ توسعه نباید لوپ‌بک را بگیرد
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    monkeypatch.setattr(D, "YTDLP", _YTDLP)
    yield f"http://127.0.0.1:{port}/page.html"
    await runner.cleanup()


def _media(workdir) -> list[str]:
    return sorted(n for n in os.listdir(workdir) if n.endswith((".mp4", ".mkv", ".webm")))


@needs_ffmpeg
@needs_ytdlp
async def test_a_playlist_link_downloads_one_item(tmp_path, playlist_site):
    work = tmp_path / "work"
    work.mkdir()
    await D.download_ytdlp(playlist_site, str(work), "best", {"timeout": 120})
    assert len(_media(work)) == 1, f"کلِ پلی‌لیست کشیده شد: {_media(work)}"


@needs_ffmpeg
@needs_ytdlp
async def test_a_playlist_probe_describes_the_item_that_will_download(playlist_site):
    """probe همان آیتمی را توصیف کند که دانلود می‌شود، نه پوستهٔ پلی‌لیست را."""
    info = await D.probe(playlist_site, {})
    assert info["title"] == "pl (1)", info["title"]


def test_normalize_probe_unwraps_a_single_entry_playlist():
    """بی‌شبکه: شکلِ `-J` با `--playlist-items 1` — متادیتای ایمنی مالِ همان ویدیو."""
    data = {"_type": "playlist", "title": "a playlist", "age_limit": 0,
            "entries": [{"title": "first", "duration": 12, "age_limit": 18,
                         "formats": [{"height": 360, "vcodec": "avc1", "tbr": 500}]}]}
    out = D.normalize_probe(data)
    assert out["title"] == "first"
    assert out["age_limit"] == 18
    assert [o["sel"] for o in out["options"]] == ["360"]


def test_a_single_video_probe_is_unchanged():
    """کنترل."""
    data = {"title": "solo", "duration": 5,
            "formats": [{"height": 720, "vcodec": "avc1", "tbr": 900}]}
    assert D.normalize_probe(data)["title"] == "solo"


_FAKE_GDL = textwrap.dedent("""\
    #!%s
    import json, os, sys
    argv = sys.argv[1:]
    d = argv[argv.index("-D") + 1]
    os.makedirs(d, exist_ok=True)
    json.dump(argv, open(os.path.join(os.path.dirname(d), "argv.json"), "w"))
    lo, hi = 1, 200                                   # «پروفایل»: ۲۰۰ فایل
    if "--range" in argv:
        lo, hi = (int(x) for x in argv[argv.index("--range") + 1].split("-"))
    for i in range(lo, hi + 1):
        open(os.path.join(d, "p%%03d.jpg" %% i), "wb").write(b"x")
    """) % sys.executable


async def test_a_gallery_link_is_capped(tmp_path, monkeypatch):
    """gallery-dlِ جعلی که `--range` را مثلِ نسخهٔ واقعی تفسیر می‌کند."""
    script = tmp_path / "gallery-dl"
    script.write_text(_FAKE_GDL)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    monkeypatch.setattr(D, "GALLERY_DL", str(script))
    work = tmp_path / "work"
    work.mkdir()
    files, _cap = await D.download_gallerydl("https://www.instagram.com/someone/", str(work), {})
    assert len(files) <= 20, f"{len(files)} فایل از یک لینکِ پروفایل"


def test_the_cap_never_truncates_a_real_carousel():
    """کنترل: سقفِ کاروسلِ اینستاگرام ۲۰ آیتم است."""
    assert D.GALLERY_MAX_ITEMS >= 20
