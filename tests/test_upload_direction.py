"""کدام تنظیم بایت آپلود می‌کند و کدام نه — با اجرا، نه با شباهتِ نام.

`--local` دو محدودیتِ **متفاوت** دارد (`docs/telegram-api.md`): دانلود بی‌سقف،
آپلود تا ۲۰۰۰ مگابایت. پس «سقفِ ۲۰۰۰» فقط به کلیدی می‌خورد که بایتِ تازه‌ای به
تلگرام می‌فرستد، و گذاشتنش روی یک کلیدِ سمتِ **دریافت** مسیری را می‌بندد که در
تولید کار می‌کند — همان چیزی که نسخهٔ اولِ `BOUNDS` انجام داد و ۴۴ ردیفِ بالای
۲۰۰۰ مگابایتِ جدولِ `files` (بزرگ‌ترین ۳۹۱۲ مگ) ردش کردند.

مکانیزم یک نقطه است و این‌جا **اجرا** می‌شود، نه توصیف: `cards._media_arg`.
`FSInputFile` یعنی بایت روی سیم می‌رود؛ `str` یعنی `file_id` و تلگرام سمتِ خودش
کپی می‌کند.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from app import settings_store as ss

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _file(**kw):
    from app.models import File
    base = dict(ref="abcd1234", owner_id=1, file_unique_id="u", file_id="",
                kind="document", name="thing.bin", changelog=[], source="dl")
    base.update(kw)
    return File(**base)


# ── مکانیزم ──────────────────────────────────────────────────────
def test_a_path_uploads_bytes_and_a_file_id_does_not(tmp_path):
    """قلبِ تفکیک، اجراشده."""
    from aiogram.types import FSInputFile

    from app import cards
    p = tmp_path / "thing.bin"
    p.write_bytes(b"x" * 1024)

    produced = cards._media_arg(_file(), str(p))
    assert isinstance(produced, FSInputFile), "فایلِ تولیدشده باید آپلود شود"

    received = cards._media_arg(_file(file_id="CACHED"), None)
    assert isinstance(received, str) and received == "CACHED", (
        "کارتِ فایلِ دریافتی باید با file_id برود، یعنی صفر بایتِ آپلود")


async def test_send_card_of_a_received_file_uploads_nothing(tmp_path):
    """یک پله بالاتر: خودِ `send_card` هم روی مسیرِ دریافت بایتی نمی‌فرستد.

    داکلی که آرگومان‌ها را با امضای واقعیِ aiogram bind می‌کند (§۶، درسِ
    `aiogram_double`) — نه یک ماکِ خوش‌بین.
    """
    from aiogram.types import FSInputFile

    from app import cards

    seen = []

    class Bot:
        def __getattr__(self, name):
            async def call(*a, **kw):
                seen.append((name, a, kw))
                class M:
                    message_id = 1
                    document = type("D", (), {"file_id": "F", "file_unique_id": "U"})()
                    video = audio = animation = voice = video_note = photo = None
                return M()
            return call

    await cards.send_card(Bot(), 1, _file(kind="document", file_id="CACHED"), "fa")
    assert seen, "کارتی فرستاده نشد"
    flat = [x for _n, a, kw in seen for x in (*a, *kw.values())]
    assert not any(isinstance(m, FSInputFile) for m in flat), (
        "کارتِ فایلِ دریافتی نباید FSInputFile بفرستد")
    assert "CACHED" in flat, "باید با همان file_id رفته باشد"


# ── طبقه‌بندیِ کلیدها ────────────────────────────────────────────
def _reader_files(key: str) -> set[str]:
    """فایل‌هایی زیرِ `app/` که این کلید را از فروشگاهِ تنظیمات می‌خوانند."""
    out = set()
    for path in (ROOT / "app").rglob("*.py"):
        if path.name in ("settings_store.py", "admin_web.py", "config.py"):
            continue
        src = path.read_text(encoding="utf-8")
        if f'"{key}"' in src or f"'{key}'" in src:
            out.add(path.relative_to(ROOT / "app").as_posix())
    return out


def test_the_receive_side_key_is_only_read_where_it_gates_an_op():
    """`max_file_mb` نه intake را می‌بندد نه چیزی آپلود می‌کند.

    اگر روزی جای دیگری خوانده شود، این تست می‌افتد و طبقه‌بندی باید دوباره
    بررسی شود — نه اینکه بی‌صدا سقفِ غلط بگیرد.
    """
    assert _reader_files("max_file_mb") == {"routers/ops.py"}
    src = (ROOT / "app" / "routers" / "ops.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    consumers = {
        fn.name for fn in ast.walk(tree)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_max_mb" for n in ast.walk(fn))}
    # بقیهٔ مصرف‌کننده‌ها هندلرهای `op_*`اند که فقط عدد را داخلِ پیامِ
    # «too_large» می‌گذارند؛ تصمیم در `_too_large` گرفته می‌شود.
    assert {"_too_large", "_vjoin_cap_mb"} <= consumers
    # intake هیچ سقفی اعمال نمی‌کند — همین است که ۳۹۱۲ مگ را ممکن کرده.
    assert "max_file_mb" not in (ROOT / "app" / "routers" / "files.py").read_text(
        encoding="utf-8")
    # و هیچ‌کدام از ماژول‌هایی که واقعاً بایت آپلود می‌کنند آن را نمی‌خوانند.
    for mod in ("tasks.py", "tasks_download.py", "cards.py"):
        assert "max_file_mb" not in (ROOT / "app" / mod).read_text(encoding="utf-8"), (
            f"{mod} بایت آپلود می‌کند؛ خواندنِ max_file_mb آن‌جا یعنی طبقه‌بندی عوض شده")


@pytest.mark.parametrize("key,where", [
    ("dl_max_size_mb", "tasks_download.py"),
    ("dl_direct_max_mb", "tasks_download.py"),
    ("compress_tiny_target_mb", "tasks.py"),
    ("vjoin_max_mb", "routers/ops.py"),
])
def test_every_upload_capped_key_is_read_where_bytes_are_produced(key, where):
    assert where in _reader_files(key), f"{key} دیگر در {where} خوانده نمی‌شود"
    assert key in ss.BOUNDS and ss.BOUNDS[key][1] == ss._UPLOAD_CEILING_MB


def test_the_download_engines_deliver_by_uploading_a_path():
    """چرا `dl_max_size_mb`/`dl_direct_max_mb` سمتِ آپلودند.

    هر دو مسیرِ تحویلِ دانلود `send_card(..., path=…)` صدا می‌زنند، و طبقِ تستِ
    مکانیزمِ بالا یعنی `FSInputFile`. **این ادعا شهودی نیست** — انتظارِ اولیه
    این بود که موتورِ direct از گیت‌وی `/dl` سرو شود و اصلاً از تلگرام رد نشود؛
    اجرا خلافش را نشان داد، و `op_link` (تنها نویسندهٔ `dl_token`) روی فایلی کار
    می‌کند که از قبل کارت شده.
    """
    src = (ROOT / "app" / "tasks_download.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for name in ("_spawn", "_deliver_single"):
        fn = next(f for f in ast.walk(tree)
                  if isinstance(f, ast.AsyncFunctionDef) and f.name == name)
        # `_spawn` از `send_card` می‌رود و `_deliver_single` از `update_card`
        # (ویرایشِ درجای پیامِ لنگرگاه). هر دو `_media_arg(file, path)` را صدا
        # می‌زنند، پس هر دو یعنی آپلود؛ اولین نسخهٔ این تست فقط `send_card` را
        # می‌شناخت و به همین دلیل افتاد.
        calls = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") in ("send_card", "update_card")]
        assert calls, f"{name} دیگر کارت نمی‌فرستد"
        assert all(any(k.arg == "path" for k in c.keywords) for c in calls), (
            f"{name} باید path بدهد — یعنی بایتِ تازه آپلود می‌کند")
