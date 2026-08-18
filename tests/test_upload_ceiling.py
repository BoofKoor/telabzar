"""پرتگاهِ آپلود: عملیاتی که کارش را تمام می‌کند و بعد سرِ ارسال می‌شکند.

سرورِ محلیِ Bot API دانلود را بی‌سقف می‌کند ولی آپلود را تا ۲۰۰۰ مگابایت
(`docs/telegram-api.md`). پس ربات فایلِ ۳٫۹ گیگی را می‌پذیرد — درست است، چون
کارتش با `file_id` می‌رود و صفر بایت آپلود می‌کند — ولی هر عملیاتی که خروجیِ
**تازه** می‌سازد بایت روی سیم می‌گذارد و می‌تواند از سقف رد کند.

رفتارِ اندازه‌گیری‌شدهٔ پیش از این رفع (با `run_op`ِ واقعی و باتی که مثلِ سرور
۴۱۳ می‌دهد) دو شکل داشت و **هیچ‌کدام قابلِ قبول نبود**:

    شاخهٔ `path` / `send_media`  → job=failed، پیامِ عمومیِ «پردازش ناموفق» با
                                   دُمِ خامِ انگلیسیِ Request Entity Too Large
    شاخهٔ `spawn` / `files`      → job=**done**، برچسب در changelog، و **هیچ
                                   فایلی نرسیده** — موفقیتِ کاذب

به‌علاوهٔ دو چیز که فقط با اجرا دیده شدند: شاخهٔ `spawn` ردیفِ `File` را **پیش
از** آپلود commit می‌کند (`tasks.py`, `session.add(newf)`)، پس شکستِ ارسال یک
ردیفِ یتیم با `file_id=""` در جدولِ `files` جا می‌گذارد؛ و اگر سرور به‌جای ۴۱۳
جوابِ ۴۰۰ بدهد، زنجیرهٔ fallbackِ `update_card` → `send_card` → `send_document`
بایت‌های بیش‌ازحد را **سه بار** می‌فرستد.

این‌جا آن‌ها اجرا می‌شوند، نه توصیف. فایلِ بزرگ **sparse** ساخته می‌شود
(`truncate`): `os.path.getsize` حجمِ کامل را می‌دهد و روی دیسک صفر بلوک
می‌گیرد، پس تست هم واقعی است هم ارزان.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy import func as sqfunc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aiogram.types import FSInputFile

from app import settings_store as ss
from app import tasks as T
from app.models import Base, File, Job, User
from tests.aiogram_double import ValidatingBot

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHAT, CARD_MID = 4242, 99

#: حجمِ خروجیِ «بیش‌ازحد» و «به‌اندازه» — هر دو نسبت به سقفِ واقعی، نه یک عددِ
#: کوچکِ ساختگی. سقف را وصله نمی‌کنیم تا تست دربارهٔ همان عددی باشد که تولید
#: استفاده می‌کند.
OVER_MB = ss.UPLOAD_CEILING_MB + 12
UNDER_MB = 3


def _sparse(path: str, mb: int) -> str:
    """فایلی که `getsize` آن را `mb` مگابایت می‌بیند و صفر بلوک روی دیسک دارد."""
    with open(path, "wb") as fh:
        fh.truncate(mb * 1024 * 1024)
    return path


def _carries_bytes(payload: dict) -> bool:
    """آیا این فراخوانی واقعاً بایت روی سیم می‌گذارد؟ (`cards._media_arg`)"""
    for v in payload.values():
        if isinstance(v, FSInputFile):
            return True
        if isinstance(getattr(v, "media", None), FSInputFile):
            return True
    return False


class Bot(ValidatingBot):
    """باتی که هر آپلود را ثبت می‌کند — تریپ‌وایرِ «اصلاً تلاش نشد».

    از `ValidatingBot` ارث می‌برد، پس هر فراخوانی با امضای خودِ aiogram bind و
    با pydantic اعتبارسنجی می‌شود؛ فراخوانیِ بدشکل این‌جا هم مثلِ تولید می‌ترکد.
    """

    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.captions: list[str] = []

    def _on(self, name: str, payload: dict):
        if _carries_bytes(payload):
            self.uploads.append(name)
        if name == "edit_message_caption" and payload.get("caption"):
            self.captions.append(payload["caption"])

        class M:  # پاسخِ حداقلی که `message_media_id` بتواند بخواند
            message_id = CARD_MID
            document = video = audio = animation = voice = video_note = photo = None
        return M()


# ── هارنس ────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def env(monkeypatch, tmp_path):
    """DBِ واقعی + `run_op`ِ واقعی؛ فقط `_do_op` و لایهٔ فایلِ ورودی جعلی‌اند."""
    monkeypatch.setattr(T.settings, "work_dir", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        u = User(tg_user_id=5, role="user")
        s.add(u)
        await s.flush()
        f = File(ref="Cliff001", owner_id=u.id, file_unique_id="u0", file_id="F0",
                 name="lecture.mp4", kind="video", size=3912 * 1024 * 1024, changelog=[])
        s.add(f)
        await s.flush()
        j = Job(file_id=f.id, op="compress", args={}, status="queued")
        s.add(j)
        await s.commit()
        ids = (j.id, f.id)

    monkeypatch.setattr(T, "Sessionmaker", maker)

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(T.textstore, "refresh_if_stale", _noop)
    monkeypatch.setattr(T, "_refresh_media_meta", _noop)      # بی‌ffprobe

    async def _no_poster(*a, **kw):
        return False

    monkeypatch.setattr(T.P, "video_poster", _no_poster)

    async def _localize(bot, file_id, workdir):
        os.makedirs(workdir, exist_ok=True)
        return _sparse(os.path.join(workdir, "in.mp4"), 1)

    monkeypatch.setattr(T, "_localize", _localize)
    yield maker, ids
    await engine.dispose()


def _install_result(monkeypatch, shape, mb: int):
    """`_do_op` را وادار کن خروجیِ `mb` مگابایتی با شکلِ خواسته‌شده برگرداند."""

    async def _do_op(bot, op, args, file, inpath, workdir, lang, progress=None, cancel=None):
        out = _sparse(os.path.join(workdir, "out.mp4"), mb)
        return shape(out)

    monkeypatch.setattr(T, "_do_op", _do_op)


#: چهار شکلِ خروجیِ حاملِ بایت، دقیقاً همان‌طور که `_do_op` می‌سازدشان.
SHAPES = {
    "path": lambda out: {"path": out, "filename": "out.mp4", "label": "L"},
    "spawn": lambda out: {"spawn": {"path": out, "name": "a.mp3", "kind": "audio"},
                          "label": "L"},
    "send_media": lambda out: {"send_media": {"as": "animation", "path": out,
                                              "filename": "a.gif"}, "label": "L"},
    "files": lambda out: {"files": [out], "label": "L"},
}


async def _run(maker, ids, monkeypatch, shape_key: str, mb: int):
    _install_result(monkeypatch, SHAPES[shape_key], mb)
    job_id, file_id = ids
    bot = Bot()
    await T.run_op({"bot": bot, "redis": None}, job_id, CHAT, CARD_MID, "fa")
    async with maker() as s:
        job = await s.get(Job, job_id)
        file = await s.get(File, file_id)
        rows = (await s.execute(select(sqfunc.count()).select_from(File))).scalar()
    return bot, job, file, rows


# ── ادعای اصلی، به‌ازای هر چهار شکلِ تحویل ────────────────────────
@pytest.mark.parametrize("shape", sorted(SHAPES), ids=sorted(SHAPES))
async def test_an_oversized_output_is_refused_before_any_upload(env, monkeypatch, shape):
    """هیچ بایتی روی سیم نمی‌رود، و کاربر می‌فهمد چه شد.

    تریپ‌وایر روی **تلاش** است نه نتیجه: ادعا این نیست که آپلود شکست خورد،
    این است که اصلاً شروع نشد. پیش از این رفع، هر چهار شکل تلاش می‌کردند.
    """
    maker, ids = env
    bot, job, file, rows = await _run(maker, ids, monkeypatch, shape, OVER_MB)

    assert bot.uploads == [], f"بایت روی سیم رفت: {bot.uploads}"
    assert job.status == "failed", "کار به مقصد نرسیده؛ done یعنی changelog دروغ می‌گوید"
    assert str(ss.UPLOAD_CEILING_MB) in (job.error or ""), (
        f"job.error باید علت را نام ببرد: {job.error!r}")


async def test_the_job_error_is_stable_so_the_panel_can_group_it(env, monkeypatch):
    """صفحهٔ آمار خطاها را با **متنِ دقیقشان** گروه می‌کند.

    پس اگر `job.error` حجمِ خروجی را حمل کند، هر ردِ حجمی یک کلیدِ یکتا با
    شمارِ ۱ می‌شود و این کلاس هرگز در «پرتکرارترین خطاها» بالا نمی‌آید —
    یعنی دقیقاً سیگنالی که ادمین برای تصمیم لازم دارد گم می‌شود. حجم در
    پیامِ کاربر و خطِ لاگ هست؛ آن‌جا متغیر بودنش درست است.

    **این تست روی سورسِ پیش از رفع هم سبز است و باید باشد** — آن‌جا اصلاً
    `job.error`ی ساخته نمی‌شود، پس ادعا بی‌موضوع است. غیرِتوخالی بودنش را
    موردِ سابوتاژِ «the job error carries the varying size again» ثابت می‌کند،
    نه اجرای pre-fix.
    """
    maker, ids = env
    _b, job_a, _f, _r = await _run(maker, ids, monkeypatch, "path", OVER_MB)
    first = job_a.error
    _b, job_b, _f, _r = await _run(maker, ids, monkeypatch, "path", OVER_MB + 900)
    assert job_b.error == first, (
        f"دو ردِ حجمی باید یک کلیدِ آماری بسازند: {first!r} در برابرِ {job_b.error!r}")
    assert str(OVER_MB) not in (first or ""), "حجمِ متغیر نباید در job.error باشد"


@pytest.mark.parametrize("shape", sorted(SHAPES), ids=sorted(SHAPES))
async def test_a_refused_op_claims_nothing_in_the_changelog(env, monkeypatch, shape):
    """کارت نباید بگوید کاری انجام شد که انجام نشده.

    شاخه‌های `spawn` و `files` پیش از این رفع برچسب را می‌نوشتند و job را
    `done` می‌کردند — یعنی کارت ادعای موفقیت داشت و فایلی نرسیده بود.
    """
    maker, ids = env
    _bot, _job, file, _rows = await _run(maker, ids, monkeypatch, shape, OVER_MB)
    assert file.changelog == [], f"changelog ادعای کاذب دارد: {file.changelog}"
    assert file.name == "lecture.mp4", "فایلِ اصلی باید دست‌نخورده بماند"


@pytest.mark.parametrize("shape", sorted(SHAPES), ids=sorted(SHAPES))
async def test_a_refused_op_leaves_no_orphan_row_in_files(env, monkeypatch, shape):
    """شاخهٔ `spawn` ردیفِ `File` را پیش از آپلود commit می‌کند.

    اندازه‌گیری‌شده روی سورسِ پیش از رفع: آن شاخه **۲** ردیف در `files` جا
    می‌گذاشت (اصلی + یتیمی با `file_id=""`) در حالی که سه شاخهٔ دیگر ۱ ردیف.
    گیت پیش از `session.add` می‌نشیند، پس یتیمی ساخته نمی‌شود.
    """
    maker, ids = env
    _bot, _job, _file, rows = await _run(maker, ids, monkeypatch, shape, OVER_MB)
    assert rows == 1, f"{rows} ردیف در files — یتیم جا مانده"


async def test_the_user_is_told_the_size_the_cap_and_that_the_file_is_safe(env, monkeypatch):
    """پیام سه جزء دارد، و سومی از همه مهم‌تر است.

    کاربری که ربع ساعت منتظر مانده و خطا گرفته اول فکر می‌کند فایلش از دست
    رفت؛ پیامِ عمومیِ «پردازش ناموفق» دقیقاً همان برداشت را می‌سازد.

    کپشن از مسیرِ **واقعیِ** `cards.set_card_note` می‌آید (یعنی یک
    `edit_message_caption`ِ اعتبارسنجی‌شده)، نه از یک داکلِ خوش‌بین.
    """
    maker, ids = env
    bot, _job, _file, _rows = await _run(maker, ids, monkeypatch, "path", OVER_MB)

    assert bot.captions, "هیچ کپشنی به کاربر نرفت"
    note = bot.captions[-1]
    assert str(OVER_MB) in note, "حجمِ واقعیِ خروجی باید در پیام باشد"
    assert str(ss.UPLOAD_CEILING_MB) in note, "سقف باید در پیام باشد"
    # جزء سوم: اطمینان‌دادن + کاری که می‌تواند بکند. به متنِ دقیق گره نمی‌خورد
    # (رشته از پنل قابلِ ویرایش است)، ولی هر دو ایده باید حاضر باشند.
    from app.i18n import t
    expected = t("fa", "op_too_large", mb=OVER_MB, cap=ss.UPLOAD_CEILING_MB)
    assert note.endswith(expected) or expected in note, "پیامِ op_too_large استفاده نشده"
    assert "دست‌نخورده" in expected, "کاربر باید بداند فایلِ اصلی سالم است"


# ── کنترلِ منفی: گارد نباید همه‌چیز را رد کند ─────────────────────
@pytest.mark.parametrize("shape", sorted(SHAPES), ids=sorted(SHAPES))
async def test_an_output_under_the_ceiling_is_still_delivered(env, monkeypatch, shape):
    """بدونِ این، یک گاردِ «همیشه رد کن» هم تست‌های بالا را سبز می‌کرد.

    این تست باید روی سورسِ پیش از رفع **هم** سبز باشد؛ اگر نبود، یعنی گارد
    مسیرِ سالم را شکسته.
    """
    maker, ids = env
    bot, job, file, _rows = await _run(maker, ids, monkeypatch, shape, UNDER_MB)

    assert bot.uploads, f"خروجیِ {UNDER_MB} مگی باید تحویل شود، شکل={shape}"
    assert job.status == "done", f"job باید done باشد: {job.status} / {job.error}"
    assert file.changelog == ["L"], "برچسبِ کارِ موفق باید ثبت شود"


async def test_the_ceiling_is_compared_in_bytes_not_rounded_megabytes():
    """دقیقاً روی مرز رد نشود؛ یک بایت بالاتر رد شود.

    اگر مقایسه روی مگابایتِ گردشده انجام شود، فایلِ ۲۰۰۰٫۴ مگی «۲۰۰۰» خوانده
    می‌شود و از گیت رد می‌شود — و بعد در تولید می‌شکند.
    """
    import tempfile
    limit = ss.UPLOAD_CEILING_MB * 1024 * 1024
    with tempfile.TemporaryDirectory() as d:
        exact = os.path.join(d, "exact.bin")
        with open(exact, "wb") as fh:
            fh.truncate(limit)
        assert T._too_big_to_send([exact]) is None, "فایلِ دقیقاً روی سقف باید بگذرد"

        over = os.path.join(d, "over.bin")
        with open(over, "wb") as fh:
            fh.truncate(limit + 1)
        assert T._too_big_to_send([over]) == ss.UPLOAD_CEILING_MB, (
            "یک بایت بالای سقف باید رد شود")


async def test_a_missing_output_is_not_treated_as_oversized():
    """مسیری که وجود ندارد نباید به «خیلی بزرگ» ترجمه شود.

    شکستِ واقعی‌اش جای دیگری گزارش می‌شود؛ این‌جا باید بی‌صدا رد شود وگرنه
    خطای غلط به کاربر می‌رسد.
    """
    assert T._too_big_to_send(["/nope/nothing/here.bin", ""]) is None


async def test_every_item_is_measured_on_its_own_not_summed():
    """شاخهٔ `files` هر فایل را با یک `send_document`ِ مستقل می‌فرستد.

    پس ادعا «مجموع زیرِ سقف است» نیست، «هیچ‌کدام از سقف رد نمی‌کنند» است —
    جمع‌کردنِ آن‌ها ده فایلِ ۳۰۰ مگی را به‌غلط رد می‌کرد.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        parts = [_sparse(os.path.join(d, f"p{i}.bin"), 800) for i in range(4)]
        assert T._too_big_to_send(parts) is None, "۴×۸۰۰ مگ جدا جدا مجازند"


# ── گاردِ ساختاری: شکلِ پنجم نباید بی‌صدا از گیت رد شود ───────────
def _do_op_source() -> ast.Module:
    return ast.parse((ROOT / "app" / "tasks.py").read_text(encoding="utf-8"))


def _result_keys() -> set[str]:
    """کلیدهای هر dictی که `_do_op`/`_convert_pdf` برمی‌گردانند — کشف‌محور."""
    tree = _do_op_source()
    keys: set[str] = set()
    for fn in ast.walk(tree):
        if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                and fn.name in ("_do_op", "_convert_pdf")):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                keys.update(k.value for k in node.value.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str))
    assert keys, "هیچ کلیدی پیدا نشد — تحلیلگر شکسته، نه کد"
    return keys


#: کلیدهایی که امروز `_do_op` برمی‌گرداند. `_BYTE_KEYS` زیرمجموعهٔ آپلودی است؛
#: بقیه فقط متن/وضعیت‌اند و بایتی نمی‌فرستند.
_KNOWN_RESULT_KEYS = {
    # حاملِ بایت
    "path", "spawn", "send_media", "files",
    # متادیتای همان تحویل
    "filename", "kind", "label", "new_meta",
    # بی‌بایت
    "editor", "message", "note_only",
}


def test_no_new_result_shape_slips_past_the_ceiling_gate():
    """شکلِ تازه‌ای که به `_do_op` اضافه شود، این‌جا قرمز می‌شود.

    گارد عمداً روی **شکلِ خروجی** است نه روی نامِ op: opِ تازه‌ای که شکلِ
    موجود را بردارد خودکار پوشش می‌گیرد، و ریسکِ واقعی شکلِ **پنجم** است که
    از کنارِ `_outgoing_paths` رد شود.
    """
    found = _result_keys()
    assert found == _KNOWN_RESULT_KEYS, (
        "مجموعهٔ کلیدهای نتیجهٔ _do_op عوض شده.\n"
        f"  تازه: {sorted(found - _KNOWN_RESULT_KEYS)}\n"
        f"  رفته: {sorted(_KNOWN_RESULT_KEYS - found)}\n"
        "اگر کلیدِ تازه یک مسیرِ فایل حمل می‌کند، هم به `tasks._BYTE_KEYS` و هم "
        "به `tasks._outgoing_paths` اضافه‌اش کن و یک تستِ رفتاری برایش بنویس؛ "
        "وگرنه فقط این فهرست را به‌روز کن.")


def test_the_gate_reads_every_byte_carrying_key():
    """`_outgoing_paths` باید هر کلیدِ آپلودی را بخواند.

    برداشتنِ یکی از آن‌ها همان پرتگاه را برای آن شاخه بازمی‌گرداند، بی‌آنکه
    هیچ چیزِ دیگری تغییر کند.
    """
    tree = _do_op_source()
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, ast.FunctionDef) and f.name == "_outgoing_paths")
    read = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert set(T._BYTE_KEYS) <= read, (
        f"_outgoing_paths این کلیدها را نمی‌خواند: {sorted(set(T._BYTE_KEYS) - read)}")
    assert set(T._BYTE_KEYS) <= _KNOWN_RESULT_KEYS, "_BYTE_KEYS کلیدی دارد که _do_op نمی‌سازد"
