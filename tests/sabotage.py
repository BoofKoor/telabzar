"""ابزارِ سابوتاژ — «آیا این تست واقعاً چیزی را می‌گیرد؟» با ضمانتِ اعمال‌شدن.

روالِ سابوتاژ این است: رفع را عمداً خراب کن، سوییت را بزن، و ببین **همان** تستی
که باید، می‌افتد. مشکلْ خودِ روال نیست، این است که «۲۰ passed» دو معنی دارد و
از بیرون یکی به‌نظر می‌رسند:

  ۱) خرابکاری اعمال شد و تست‌ها نگرفتندش  → تست‌ها بی‌ارزش‌اند
  ۲) خرابکاری **اصلاً اعمال نشد**          → اندازه‌گیری بی‌معناست

حالتِ دوم دو بار در این ریپو اتفاق افتاد (۲۰۲۶-۰۸-۱۰ روی `trim_video`/`trim_audio`
که خطِ فرمانشان یکسان شده بود، و ۲۰۲۶-۰۸-۱۴ روی `del_meta` که رشتهٔ هدفش چند
ویرایش قبل عوض شده بود) و هر دو بار «سبز» گزارش شد. قاعده‌ای که دو بار فراموش
شود بارِ سوم هم فراموش می‌شود، پس این‌جا **ساختاری** است نه انضباطی: تعدادِ
تطبیق بررسی می‌شود و ناهماهنگی `SabotageError` می‌دهد، و فایل در `finally`
برمی‌گردد تا یک اجرای نیمه‌کاره درخت را کثیف نگذارد.

    from tests.sabotage import sabotage

    with sabotage("app/cookies.py", "if not total:", "if False:"):
        subprocess.run(["pytest", "-q", "tests/test_cookie_alert.py"])

عمداً در `tests/` است نه در `app/`: ابزارِ توسعه است، نه کدِ اجرایی. و عمداً
هیچ‌جای سوییت این را صدا نمی‌زند جز تستِ خودش — سوییت نباید سورس را عوض کند.
"""
from __future__ import annotations

import contextlib
from pathlib import Path

__all__ = ["SabotageError", "sabotage", "patch_source"]


class SabotageError(AssertionError):
    """خرابکاری آن‌طور که خواسته شده اعمال نشد — نتیجهٔ اجرا بی‌اعتبار است."""


def patch_source(path: str | Path, old: str, new: str, *, count: int = 1) -> str:
    """`old` را با `new` عوض می‌کند و متنِ **قبلی** را برمی‌گرداند.

    اگر تعدادِ تطبیق دقیقاً `count` نباشد `SabotageError` می‌دهد — نه صفر (هدف
    عوض شده) و نه بیشتر (داری جای دیگری را هم می‌زنی؛ همان چیزی که یک‌بار
    `trim_audio` را به‌جای `trim_video` خراب کرد).
    """
    p = Path(path)
    before = p.read_text(encoding="utf-8")
    found = before.count(old)
    if found != count:
        raise SabotageError(
            f"{p}: الگو {found} بار پیدا شد، انتظار {count} بود — "
            f"خرابکاری اعمال نشد، پس نتیجهٔ اجرا چیزی ثابت نمی‌کند.\n"
            f"  الگو: {old!r}")
    p.write_text(before.replace(old, new), encoding="utf-8")
    return before


@contextlib.contextmanager
def sabotage(path: str | Path, old: str, new: str, *, count: int = 1):
    """`patch_source` به‌صورتِ context manager؛ فایل همیشه برمی‌گردد."""
    p = Path(path)
    before = patch_source(p, old, new, count=count)
    try:
        yield p
    finally:
        p.write_text(before, encoding="utf-8")


# ── دفترچهٔ سابوتاژها ─────────────────────────────────────────────
# سابوتاژ یک‌بارمصرف بود: هر سشن می‌زد و می‌رفت. ولی تستی که امروز غیرِvacuous
# اثبات شده فردا می‌تواند vacuous شود — همان اتفاقی که برای رشتهٔ `del_meta`
# افتاد. این‌جا هر سابوتاژ به‌صورتِ **داده** ثبت می‌شود و با یک فرمان دوباره
# اجرا می‌شود، پس برگشت به vacuousness دیده می‌شود:
#
#     python -m tests.sabotage          # همه
#     python -m tests.sabotage cookie   # فقط موارد شاملِ این رشته
#
# دستی است، **نه CI**: سورس را عوض می‌کند و اجرای موازی را نمی‌شود اعتماد کرد.
# `expect` = تستی که باید **بیفتد**. `expect=None` یعنی کنترلِ معکوس: این
# خرابکاری نباید آن تست را بیندازد (اثباتِ اینکه تست هدفِ درست را می‌سنجد).
#
#: (نام, فایل, الگو, جایگزین, تعدادِ تطبیق, تستِ هدف, تستی که باید بیفتد)
CASES: list[dict] = [
    {"name": "alert: guard removed entirely",
     "path": "app/tasks_download.py",
     "old": "        total, left = await ck.pool_counts(redis, platform)\n"
            "        if not total and not await ck.was_stocked(redis, platform):\n"
            "            return          # سطل هرگز پر نشده — این «سوختن» نیست\n",
     "new": "        _t, left = await ck.pool_counts(redis, platform)\n",
     "target": "tests/test_cookie_alert.py",
     "expect": "test_a_bucket_that_was_never_stocked_is_silent"},

    {"name": "alert: guard written on healthy_count (silences a burned pool)",
     "path": "app/tasks_download.py",
     "old": "        if not total and not await ck.was_stocked(redis, platform):\n"
            "            return          # سطل هرگز پر نشده",
     "new": "        if not left:\n"
            "            return          # سطل هرگز پر نشده",
     "target": "tests/test_cookie_alert.py",
     "expect": "test_a_burned_pool_still_screams"},

    {"name": "log: ERROR emitted before the guard (the pre-fix form)",
     "path": "app/tasks_download.py",
     "old": "        if not total and not await ck.was_stocked(redis, platform):\n"
            "            # سطل هرگز پر نشده؛ دانلود بی‌کوکی ادامه می‌دهد و ممکن است موفق شود\n"
            "            log.info(\"cookieless attempt on %s from exit %s — the pool has no account\",\n"
            "                     platform, ck.exit_label(node))\n"
            "            return                       # واقعاً اکانتی نیست؛ پیامِ عادی درست است\n",
     "new": "",
     "target": "tests/test_cookie_alert.py",
     "expect": "test_an_unstocked_bucket_does_not_log_an_error"},

    {"name": "trace: del_meta clears the durable mark",
     "path": "app/cookies.py",
     "old": "        await redis.delete(_CK_CD + name)\n        # `_CK_SEEN` عمداً",
     "new": "        await redis.delete(_CK_CD + name)\n"
            "        await redis.delete(_CK_SEEN + ((await get_meta(redis, name)).get('platform') or ''))\n"
            "        # `_CK_SEEN` عمداً",
     "target": "tests/test_cookie_alert.py",
     "expect": "test_deleting_the_last_account_leaves_a_durable_trace"},

    {"name": "trace: an expiry is attached to the mark",
     "path": "app/cookies.py",
     "old": 'await redis.set(_CK_SEEN + str(meta["platform"]), "1")',
     "new": 'await redis.set(_CK_SEEN + str(meta["platform"]), "1", ex=3600)',
     "target": "tests/test_cookie_alert.py",
     "expect": "test_the_trace_has_no_expiry"},

    {"name": "cold start: worker.startup stops backfilling",
     "path": "app/worker.py",
     "old": "        n = await ck.backfill_seen(",
     "new": "        n = 0 * await ck.pool_counts(",
     "target": "tests/test_cookie_alert.py",
     "expect": "test_worker_startup_backfills_the_seen_marks"},

    {"name": "delete: the sequence is open-coded again in routers/admin.py",
     "path": "app/routers/admin.py",
     "old": "        await ck.delete_account(arq_pool, name)   # همان سه گامِ مسیرِ پنل، از یک جا",
     "new": "        await ck.del_meta(arq_pool, name)\n"
            "        ck.remove_cookie_file(name)\n"
            "        await ck._unmirror_cookie(arq_pool, name)",
     "target": "tests/test_repo_hygiene.py",
     "expect": "test_only_delete_account_open_codes_the_delete_sequence"},

    {"name": "trim: output seeking in trim_video",
     "path": "app/processing.py",
     "old": '"-ss", f"{start}", "-to", f"{end}", "-i", inp,\n        "-c:v"',
     "new": '"-i", inp, "-ss", f"{start}", "-to", f"{end}",\n        "-c:v"',
     "target": "tests/test_phase2b.py",
     "expect": "test_trim_video_seeks_before_input"},

    {"name": "trim: CONTROL — breaking trim_audio must NOT fail the trim_video test",
     "path": "app/processing.py",
     "old": '"-ss", f"{start}", "-to", f"{end}", "-i", inp,\n                "-vn"',
     "new": '"-i", inp, "-ss", f"{start}", "-to", f"{end}",\n                "-vn"',
     "target": "tests/test_phase2b.py::test_trim_video_seeks_before_input",
     "expect": None},
]


def _run_case(case: dict) -> tuple[bool, str]:
    import subprocess
    import sys
    with sabotage(case["path"], case["old"], case["new"],
                  count=case.get("count", 1)):
        r = subprocess.run([sys.executable, "-m", "pytest", case["target"], "-q",
                            "--no-header", "-p", "no:cacheprovider"],
                           capture_output=True, text=True)
    failed = {ln.split("::")[-1].split(" ")[0]
              for ln in r.stdout.splitlines() if ln.startswith("FAILED")}
    want = case["expect"]
    if want is None:
        return (not failed), f"expected no failure, got {sorted(failed) or 'none'}"
    return (want in failed), f"expected {want} to fail, failures: {sorted(failed) or 'none'}"


def main(argv: list[str] | None = None) -> int:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    needle = argv[0] if argv else ""
    cases = [c for c in CASES if needle in c["name"]]
    if not cases:
        print(f"هیچ موردی با «{needle}» جور نشد.")
        return 1
    bad = 0
    for c in cases:
        try:
            ok, detail = _run_case(c)
        except SabotageError as exc:
            ok, detail = False, f"الگو رُت کرده: {exc}"
        print(f"  {'✓' if ok else '✗'} {c['name']}")
        if not ok:
            bad += 1
            print(f"      {detail}")
    print(f"\n{len(cases) - bad}/{len(cases)} سابوتاژ همان‌طور که ثبت شده رفتار کرد.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
