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
_IGW = "tests/test_ig_anon_wiring.py"
_PCB = "tests/test_probe_cookie_blame.py"
_LNK = "tests/test_link_filter.py"
_SCP = "tests/test_soundcloud_path.py"
_DEM = "tests/test_deadend_messages.py"
_CBX = "tests/test_castbox_path.py"
_CAP = "tests/test_caption_html.py"
_COV = "tests/test_audio_cover.py"
_ORP = "tests/test_probe_orphan.py"
_HYG = "tests/test_repo_hygiene.py"
_PAL = "tests/test_panel_path_is_alive.py"
_CHR = "tests/panel/test_security_characterization.py"

# برگرداندنِ هارنسِ ساندکلاود به ctxِ دست‌سازِ پیش از رفع. یک خرابکاری با سه
# ادعای مستقل، پس به‌جای سه‌بار نوشتنِ همین رشته‌ها یک‌بار تعریف می‌شود —
# دو کپیِ دست‌نویس واگرا می‌شوند و آن‌وقت رجیستری چیزِ دیگری می‌سنجد.
_CTX_PATCH = {
    "path": _SCP,
    "old": "    got = ydl._select_formats(formats, ydl.build_format_selector(expr))",
    "new": ('    got = list(ydl.build_format_selector(expr)('
            '{"formats": formats, "incomplete_formats": False}))'),
}

CASES: list[dict] = [
    # ── فاز ۲: مسیرِ ناشناسِ اینستاگرام. یکی به‌ازای هر قیدِ سخت. ──
    {"name": "ig-anon: the cookie loop runs anyway (constraint 1)",
     "path": "app/tasks_download.py",
     "old": "        while not anon_won:\n            if anon:",
     "new": "        while True:\n            if anon:",
     "target": _IGW,
     "expect": "test_a_successful_anonymous_pass_never_picks_or_materializes_a_cookie"},

    {"name": "ig-anon: a story link gets a shortcode and hits the network (constraint 1)",
     "path": "app/instagram_anon.py",
     "old": '    m = _SHORTCODE_RE.search(url or "")\n    return m.group(1) if m else None',
     "new": '    m = _SHORTCODE_RE.search(url or "")\n    return m.group(1) if m else "FAKESC"',
     "target": _IGW,
     "expect": "test_a_story_or_profile_link_never_touches_the_anonymous_network"
               "[https://www.instagram.com/stories/someuser/3512345678/]"},

    {"name": "ig-anon: a partial failure leaves its files behind (constraint 2)",
     "path": "app/instagram_anon.py",
     "old": "        if not done:\n            shutil.rmtree(outdir, ignore_errors=True)",
     "new": "        if False:\n            shutil.rmtree(outdir, ignore_errors=True)",
     "target": _IGW,
     "expect": "test_a_half_finished_anonymous_failure_leaves_no_file_behind"},

    {"name": "ig-anon: the flag ships on (constraint 3)",
     "path": "app/config.py",
     "old": "    dl_ig_anon_enabled: bool = False",
     "new": "    dl_ig_anon_enabled: bool = True",
     "target": _IGW,
     "expect": "test_the_flag_default_is_off"},

    {"name": "ig-anon: a failed verdict raises instead of falling through (constraint 4)",
     "path": "app/instagram_anon.py",
     "old": "        return InstagramAnonFetch(bucket=out.verdict)",
     "new": '        raise RuntimeError(f"anonymous path failed: {out.verdict}")',
     "target": _IGW,
     "expect": "test_a_failed_verdict_falls_through_to_the_cookie_path[403-blocked]"},

    {"name": "ig-anon: an anonymous failure is blamed on an account (decision d)",
     "path": "app/tasks_download.py",
     "old": "    await _iganon_metric(redis, got.bucket)\n    return got",
     "new": "    await _iganon_metric(redis, got.bucket)\n"
            "    if got.bucket != IGA.B_OK:\n"
            '        await ck.mark_fail(redis, "instagram_a.txt")\n'
            "    return got",
     "target": _IGW,
     "expect": "test_a_network_verdict_never_blames_an_account"},

    {"name": "ig-anon: the carousel comes back in the wrong order (decision a)",
     "path": "app/instagram_anon.py",
     "old": "    return InstagramAnonFetch(tuple(paths), res.caption, B_OK)",
     "new": "    return InstagramAnonFetch(tuple(reversed(paths)), res.caption, B_OK)",
     "target": _IGW,
     "expect": "test_the_carousel_order_is_preserved"},

    {"name": "ig-anon: the safety layer is skipped for the anonymous path",
     "path": "app/tasks_download.py",
     "old": "        pol = await safety.load_policy()\n        if pol.enabled:\n"
            '            why = ""',
     "new": "        pol = await safety.load_policy()\n"
            "        if pol.enabled and not anon_won:\n"
            '            why = ""',
     "target": _IGW,
     "expect": "test_the_safety_layer_still_blocks_media_from_the_anonymous_path"},

    {"name": "ig-anon: the time budget is not enforced (bound for a dribbling CDN)",
     "path": "app/instagram_anon.py",
     "old": "            path, info = await asyncio.wait_for(\n"
            "                D.download_direct(item.url, itemdir, opts, max_bytes=remaining,\n"
            "                                  progress=_slice_progress(progress, i, total),\n"
            "                                  cancel=cancel),\n"
            "                timeout=left)",
     "new": "            path, info = await D.download_direct(\n"
            "                item.url, itemdir, opts, max_bytes=remaining,\n"
            "                progress=_slice_progress(progress, i, total), cancel=cancel)",
     "target": _IGW,
     "expect": "test_the_time_budget_stops_a_dribbling_cdn"},

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

    # ── مسیرِ ناشناسِ اینستاگرام (فاز ۱) ─────────────────────────
    # اولی مهم‌ترینشان است: تلهٔ srcset روی فیکسچرِ واقعی **هم عرض و هم URLِ
    # برنده** را عوض می‌کند (۳۰۷۲ → ۹)، پس اگر این نیفتد یعنی تست چیزی
    # را نمی‌سنجد. توجه: شکلِ per-token + `re.search` باربر است —
    # `findall`+`max` روی کلِ رشته تصادفاً همان ۳۰۷۲ را می‌دهد و سابوتاژ
    # بی‌اثر می‌شود.
    {"name": "ig: srcset width regex unanchored (picks a number from inside the URL)",
     "path": "app/instagram_anon.py",
     "old": '_SRCSET_W_RE = re.compile(r"\\s(\\d+)w$")',
     "new": '_SRCSET_W_RE = re.compile(r"(\\d+)w")',
     "target": "tests/test_instagram_anon.py",
     "expect": "test_single_photo_comes_from_the_img_fallback_and_picks_the_widest_candidate"},

    # این یکی **باید هر دو گارد را با هم بردارد** و دلیلش خودش یک یافته است:
    # `if cj` و `isinstance(cj, str)` دو دفاعِ مستقل‌اند و هرکدام به‌تنهایی جلوی
    # کرش را می‌گیرد، پس یک سابوتاژِ تک‌گارده هیچ تستی را نمی‌اندازد و «نگرفت»
    # گزارش می‌شود — که از بیرون شبیهِ تستِ ضعیف است ولی نیست. شکلِ زیر همان
    # پیاده‌سازیِ ساده‌لوحانه‌ای است که واقعاً نوشته می‌شود.
    {"name": "ig: contextJSON parsed on key presence (both guards dropped)",
     "path": "app/instagram_anon.py",
     "old": "            if cj:\n                try:\n"
            "                    ctx = json.loads(cj) if isinstance(cj, str) else cj",
     "new": '            if "contextJSON" in init:\n                try:\n'
            "                    ctx = json.loads(cj)",
     "target": "tests/test_instagram_anon.py",
     "expect": "test_single_photo_comes_from_the_img_fallback_and_picks_the_widest_candidate"},

    {"name": "ig: only shortcode_media is read (the GraphQL key is dropped)",
     "path": "app/instagram_anon.py",
     "old": 'media = gql.get("shortcode_media") or gql.get("xdt_shortcode_media")',
     "new": 'media = gql.get("shortcode_media")',
     "target": "tests/test_instagram_anon.py",
     "expect": "test_xdt_shortcode_media_is_read_too"},

    {"name": "ig: media-host allow-list removed",
     "path": "app/instagram_anon.py",
     "old": '    if not host.endswith(_MEDIA_HOST_SUFFIXES):\n        return False\n'
            '    if host.startswith("static."):            # میزبانِ دارایی‌های ثابتِ اینستاگرام\n'
            "        return False\n"
            '    return "/rsrc.php/" not in (p.path or "")',
     "new": "    return True",
     "target": "tests/test_instagram_anon.py",
     "expect": "test_an_icon_url_in_a_structured_field_is_still_rejected"},

    {"name": "ig: a video child without video_url silently yields the poster (cobalt's behaviour)",
     "path": "app/instagram_anon.py",
     "old": "        if not vurl:\n"
            "            raise _VideoUrlMissing(\n"
            '                f"carousel child {index}: is_video but no video_url")\n'
            '        return InstagramAnonItem("video", vurl) if _is_media_url(vurl) else None',
     "new": "        if not vurl:\n"
            '            durl = node.get("display_url")\n'
            '            return InstagramAnonItem("photo", durl) if _is_media_url(durl) else None\n'
            '        return InstagramAnonItem("video", vurl) if _is_media_url(vurl) else None',
     "target": "tests/test_instagram_anon.py",
     "expect": "test_a_video_child_without_video_url_drops_the_whole_rung"},

    # ── حلقهٔ probe: کلاسِ خطا، خطِ لاگ، سقفِ تلاش ──
    # نکتهٔ الگو: `if max_tries and attempts >= max_tries:` حالا **دو بار** در
    # فایل است (fetch و probe)، پس شکلِ کوتاهش `SabotageError` می‌دهد — همان
    # تله‌ای که یک‌بار `trim_audio` را به‌جای `trim_video` خراب کرد. هر الگوی
    # این‌جا آن‌قدر بلند است که یکتا شود و `count` هم صریح داده شده.
    {"name": "probe: mark_fail loses the error class again (whole-pool bench)",
     "path": "app/tasks_download.py",
     "old": "await ck.mark_fail(redis, cname, error_class=cls, message=msg)",
     "new": "await ck.mark_fail(redis, cname)",
     "count": 1,
     "target": _PCB,
     "expect": "test_a_probe_transient_does_not_bench_the_whole_pool"},

    {"name": "probe: the class is passed but the message is forgotten",
     "path": "app/tasks_download.py",
     "old": "await ck.mark_fail(redis, cname, error_class=cls, message=msg)",
     "new": "await ck.mark_fail(redis, cname, error_class=cls)",
     "count": 1,
     "target": _PCB,
     # نامِ **پارامتری‌شده**، مثلِ موردِ استوریِ ig-anon بالاتر: دفترچه تطبیقِ
     # دقیق می‌خواهد. `transient` انتخاب شد چون همان کلاسی است که ادعای
     # «کلِ استخر» رویش سوار است.
     "expect": "test_a_probe_failure_records_why_in_the_panel[transient]"},

    # کنترلِ معکوس: همان خرابکاری **نباید** کنترلِ بات‌چک را بیندازد. بات‌چک
    # اکانت را می‌سوزاند و باید بسوزاند، پس رفع نباید آن را نرم کرده باشد.
    {"name": "probe: mark_fail loses the class — but the bot-check control stays green",
     "path": "app/tasks_download.py",
     "old": "await ck.mark_fail(redis, cname, error_class=cls, message=msg)",
     "new": "await ck.mark_fail(redis, cname)",
     "count": 1,
     "target": _PCB + "::test_a_probe_bot_check_is_punished_exactly_as_before",
     "expect": None},

    {"name": "probe: the checkpoint alert is dropped again",
     "path": "app/tasks_download.py",
     "old": "                    if ck.needs_human(cls):",
     "new": "                    if False:",
     "count": 1,
     "target": _PCB,
     "expect": "test_a_probe_checkpoint_tells_the_admin"},

    # کنترلِ معکوس: نبودِ DM نباید تستِ **فریز** را بیندازد — فریز کارِ
    # `mark_fail` است و DM کارِ `_alert_checkpoint`؛ دو ادعای جدا.
    {"name": "probe: checkpoint alert dropped — but the freeze test stays green",
     "path": "app/tasks_download.py",
     "old": "                    if ck.needs_human(cls):",
     "new": "                    if False:",
     "count": 1,
     "target": _PCB + "::test_a_probe_checkpoint_freezes_the_account",
     "expect": None},

    {"name": "probe: the attempt cap is removed (walks the whole pool)",
     "path": "app/tasks_download.py",
     "old": "                    if max_tries and attempts >= max_tries:\n"
            '                        log.info("probe: stopping after %d attempts '
            '(dl_max_cookie_tries)",',
     "new": "                    if False:\n"
            '                        log.info("probe: stopping after %d attempts '
            '(dl_max_cookie_tries)",',
     "count": 1,
     "target": _PCB,
     "expect": "test_the_probe_loop_stops_at_dl_max_cookie_tries"},

    {"name": "probe: the failure log line goes back to being message-less",
     "path": "app/tasks_download.py",
     "old": 'log.info("probe attempt %d failed (%s): %s", attempts, cls, msg[:90])',
     "new": 'log.info("probe: an attempt failed")',
     "count": 1,
     "target": _PCB,
     "expect": "test_a_probe_failure_is_greppable_in_the_log"},

    # کنترلِ معکوس: خطِ لاگ فقط تشخیصی است. برداشتنش نباید ادعای استخر را
    # بیندازد — اگر بیندازد یعنی آن تست دارد لاگ را می‌سنجد نه رفتار را.
    {"name": "probe: log line neutered — but the pool claim stays green",
     "path": "app/tasks_download.py",
     "old": 'log.info("probe attempt %d failed (%s): %s", attempts, cls, msg[:90])',
     "new": 'log.info("probe: an attempt failed")',
     "count": 1,
     "target": _PCB + "::test_a_probe_transient_does_not_bench_the_whole_pool",
     "expect": None},

    # ── درِ ورودیِ لینک: لنگرِ `regexp` ──
    # پیش‌فرضِ `magic_filter.regexp` برابرِ `pattern.match` است، پس بدونِ
    # `mode="search"` متن باید **با** لینک شروع شود.
    {"name": "link filter: back to the anchored default (match)",
     "path": "app/routers/download.py",
     "old": 'F.text.regexp(r"https?://", mode="search")',
     "new": 'F.text.regexp(r"https?://")',
     "target": _LNK,
     "expect": "test_a_link_anywhere_in_the_text_reaches_the_download_handler"
               "[soundcloud-app-two-line]"},

    # همان خرابکاری، این‌بار روی گاردِ کشف‌محور — تا اگر روزی تستِ رفتاری حذف
    # شود، هنوز چیزی جلوی برگشتنِ پیش‌فرض را بگیرد.
    {"name": "link filter: the AST guard notices the missing mode",
     "path": "app/routers/download.py",
     "old": 'F.text.regexp(r"https?://", mode="search")',
     "new": 'F.text.regexp(r"https?://")',
     "target": _LNK,
     "expect": "test_every_regexp_filter_states_its_mode_explicitly"},

    # کنترلِ معکوس ۱: `search=True` شکلِ **هم‌ارزِ** (deprecated) همان چیز است.
    # هیچ تستی نباید بیفتد — اگر بیفتد یعنی تست رشتهٔ `mode="search"` را
    # می‌سنجد نه رفتارِ فیلتر را، که همان تستِ توخالی است با ظاهرِ سالم.
    {"name": "link filter: the equivalent search=True form stays green",
     "path": "app/routers/download.py",
     "old": 'F.text.regexp(r"https?://", mode="search")',
     "new": 'F.text.regexp(r"https?://", search=True)',
     "target": _LNK,
     "expect": None},

    # کنترلِ معکوس ۲ (به‌شکلِ مثبت): برداشتنِ کلِ فیلتر باید تست را بیندازد.
    # این اثبات می‌کند `_link_filter()` واقعاً ثبتِ **زندهٔ** روتر را می‌خواند؛
    # اگر الگو را دستی در تست نوشته بودیم، این‌جا سبز می‌ماند.
    {"name": "link filter: the filter is read from the live registration",
     "path": "app/routers/download.py",
     "old": '@router.message(F.text.regexp(r"https?://", mode="search"))',
     "new": "@router.message()",
     "target": _LNK,
     "expect": "test_a_bare_link_still_reaches_the_handler[bare-short-link]"},

    # ── ساندکلاود: خودِ هارنس ──
    # این سه مورد دربارهٔ کدِ تولید نیستند، دربارهٔ **ابزارِ اندازه‌گیری**اند: یک
    # ctxِ دست‌ساز روی منبعِ تک‌نوع یک نقصِ خیالی می‌سازد (§۶، ردهٔ false fail).
    # هر سه یک خرابکاری‌اند (`_CTX_PATCH`) با سه ادعای متفاوت.
    {**_CTX_PATCH,
     "name": "harness: the yt-dlp ctx is hardcoded again",
     "target": _SCP,
     "expect": "test_a_hardcoded_ctx_invents_a_defect_that_does_not_exist[b]"},

    # ادعای دومِ همان ctx، جدا: کلیدِ **غایب** (نه مقدارِ غلط) — `[]` نه `.get()`.
    {**_CTX_PATCH,
     "name": "harness: hardcoded ctx — the omitted key is a KeyError, not falsy",
     "target": _SCP,
     "expect": "test_a_hardcoded_ctx_omits_a_key_the_selector_reads_directly"},

    # **کنترلِ معکوس، و مهم‌ترین موردِ این سه‌تا.** همان خرابکاری نباید ادعای
    # اصلیِ #۱۱۵ را بیندازد — اثباتِ اجراییِ اینکه نقصِ هارنس نتیجهٔ آن کار را
    # عوض نمی‌کند (`ba` بی‌اعتنا به این فلگ‌ها جور می‌شود). اگر روزی این بیفتد،
    # یعنی انتخابِ تولید به ctx حساس شده و باید دوباره اندازه گرفته شود.
    {**_CTX_PATCH,
     "name": "harness: hardcoded ctx — but the #115 production choice stays green",
     "target": _SCP + "::test_soundcloud_takes_progressive_mp3_when_it_exists",
     "expect": None},

    # ── ساندکلاود: انتخابگرِ فرمت ──
    {"name": "soundcloud: back to the generic ba/b (AAC + transcode)",
     "path": "app/downloader.py",
     "old": '        return _SOUNDCLOUD_AUDIO if platform == "soundcloud" else "ba/b"',
     "new": '        return "ba/b"',
     "target": _SCP,
     "expect": "test_soundcloud_takes_progressive_mp3_when_it_exists"},

    # کنترلِ معکوس: همان خرابکاری نباید ادعای **fallback** را بیندازد. اگر
    # بیفتد، آن تست دارد ترجیحِ mp3 را می‌سنجد نه بازگشت به AAC — یعنی روزی که
    # ساندکلاود mp3 را حذف کند چیزی از ما محافظت نمی‌کند.
    {"name": "soundcloud: generic selector — but the AAC fallback claim stays green",
     "path": "app/downloader.py",
     "old": '        return _SOUNDCLOUD_AUDIO if platform == "soundcloud" else "ba/b"',
     "new": '        return "ba/b"',
     "target": _SCP + "::test_soundcloud_falls_back_to_aac_when_mp3_is_gone",
     "expect": None},

    # تلهٔ خاموش: `acodec` به‌جای `ext`. روی فهرستِ امروز **تصادفاً** همان
    # فرمتِ درست درمی‌آید، پس فقط تستِ ترتیب می‌گیردش — که دقیقاً دلیلِ وجودِ
    # آن تست است.
    {"name": "soundcloud: acodec instead of ext (matches nothing, silently)",
     "path": "app/downloader.py",
     "old": '_SOUNDCLOUD_AUDIO = "ba[ext=mp3][protocol^=http]/ba[ext=mp3]/ba/b"',
     "new": '_SOUNDCLOUD_AUDIO = "ba[acodec^=mp3][protocol^=http]/ba[acodec^=mp3]/ba/b"',
     "target": _SCP,
     "expect": "test_the_choice_does_not_depend_on_the_order_yt_dlp_hands_us"},

    {"name": "soundcloud: drop the explicit protocol clause",
     "path": "app/downloader.py",
     "old": '_SOUNDCLOUD_AUDIO = "ba[ext=mp3][protocol^=http]/ba[ext=mp3]/ba/b"',
     "new": '_SOUNDCLOUD_AUDIO = "ba[ext=mp3]/ba/b"',
     "target": _SCP,
     "expect": "test_the_choice_does_not_depend_on_the_order_yt_dlp_hands_us"},

    {"name": "soundcloud: the engine stops passing the platform",
     "path": "app/downloader.py",
     "old": '"-o", outtmpl, "-f", _selector_to_format(selector, platform_of(url))]',
     "new": '"-o", outtmpl, "-f", _selector_to_format(selector)]',
     "target": _SCP,
     "expect": "test_the_engine_is_asked_for_the_platform_of_the_url"},

    # ── ساندکلاود: کلیدِ کش ──
    {"name": "cache: the sc: normaliser is gone",
     "path": "app/dl_cache.py",
     "old": "    m = _SC_RE.match(f\"{host}{p.path.rstrip('/')}\")\n    if m:",
     "new": "    m = _SC_RE.match(f\"{host}{p.path.rstrip('/')}\")\n    if False:",
     "target": _SCP,
     "expect": "test_the_second_key_goes_through_the_same_normaliser"},

    {"name": "cache: a match platform writes a youtube-keyed row",
     "path": "app/tasks_download.py",
     "old": "    if platform in D._MATCH_PLATFORMS:\n        return None",
     "new": "    if False:\n        return None",
     "target": _SCP,
     "expect": "test_a_match_platform_never_writes_a_youtube_keyed_row"},

    # ── پیام‌های بن‌بست ──
    {"name": "messages: promise another account even with an empty pool",
     "path": "app/tasks_download.py",
     "old": "                if cookie_name:\n                    await _edit(bot, chat_id, status_mid,\n"
            '                                progress_note(t(lang, "dl_retry_account")',
     "new": "                if True:\n                    await _edit(bot, chat_id, status_mid,\n"
            '                                progress_note(t(lang, "dl_retry_account")',
     "target": _DEM,
     "expect": "test_an_empty_pool_never_promises_another_account"},

    {"name": "messages: the unstockable-bucket branch is gone",
     "path": "app/tasks_download.py",
     "old": "            elif await _no_account_possible(redis, _cookie_platform(platform)) and (",
     "new": "            elif False and (",
     "target": _DEM,
     "expect": "test_an_unstockable_bucket_does_not_order_the_admin_to_add_cookies"},

    # کنترلِ معکوس: گارد روی «قابلِ‌استفاده» به‌جای «کل» — همان اشتباهی که
    # یک‌بار در `_alert_if_low` بود. باید استخرِ **سوخته** را هم «پشتیبانی
    # نمی‌شود» بخواند، یعنی سیگنالِ واقعی را خفه کند.
    {"name": "messages: guard on usable instead of total (silences a burned pool)",
     "path": "app/tasks_download.py",
     "old": "        total, _usable = await ck.pool_counts(redis, platform)\n"
            "        return not total and not await ck.was_stocked(redis, platform)",
     "new": "        _total, usable = await ck.pool_counts(redis, platform)\n"
            "        return not usable",
     "target": _DEM,
     "expect": "test_a_burned_pool_is_not_called_unsupported"},

    # کنترلِ معکوس: `ping` فقط برای fail-safe است. برداشتنش نباید هیچ ادعای
    # رفتاریِ دیگری را بیندازد — اگر بیندازد یعنی آن تست‌ها به Redisِ سالم
    # وابسته‌اند از راهی که فکر نمی‌کردیم.
    {"name": "messages: drop the liveness ping (only the fail-safe claim breaks)",
     "path": "app/tasks_download.py",
     "old": "        await redis.ping()\n        total, _usable = await ck.pool_counts(redis, platform)",
     "new": "        total, _usable = await ck.pool_counts(redis, platform)",
     "target": _DEM,
     "expect": "test_a_redis_failure_falls_back_to_todays_message"},

    # ── کست‌باکس: دو دفاعِ SSRF، تلهٔ دو-شناسه‌ای، و بقیهٔ قیدها ──
    # **دفاعِ اول، ایزوله** — بازسازیِ URL. اولین اجرای دفترچه نشان داد که هدفِ
    # این سابوتاژ نباید تستِ انتها‌به‌انتها باشد: با برداشتنِ دفاعِ اول، **گارد**
    # payload را می‌گیرد و آن تست سبز می‌ماند. پس هدف تستِ ایزوله است، وگرنه
    # یک سابوتاژِ کاملاً موفق «نگرفت» گزارش می‌شد.
    {"name": "castbox: pass the unwrapped link= through instead of rebuilding",
     "path": "app/downloader.py",
     "old": '    kind, cid = castbox_ids(url)\n'
            '    return f"https://castbox.fm/ep/{cid}" if kind == "ep" and cid else None',
     "new": '    from urllib.parse import parse_qs as _pq, urlsplit as _us\n'
            '    inner = (_pq(_us(url or "").query).get("link") or [""])[0]\n'
            '    if inner:\n'
            '        return inner\n'
            '    kind, cid = castbox_ids(url)\n'
            '    return f"https://castbox.fm/ep/{cid}" if kind == "ep" and cid else None',
     "target": _CBX,
     "expect": "test_the_rebuild_alone_rejects_the_payloads[cloud-metadata]"},

    # **هر دو لایه با هم** — تنها چیزی که ادعای انتها‌به‌انتها را می‌شکند.
    {"name": "castbox: drop BOTH the rebuild and the guard",
     "path": "app/downloader.py",
     "old": "    target = castbox_target(url)\n"
            "    if not target:\n"
            "        return None\n"
            "    if not await is_safe_url_resolved(target, proxy=proxy):\n"
            '        log.warning("castbox: rewritten target failed the safety gate: %s", target[:90])\n'
            "        return None\n"
            "    return target",
     "new": '    from urllib.parse import parse_qs as _pq, urlsplit as _us\n'
            '    inner = (_pq(_us(url or "").query).get("link") or [""])[0]\n'
            "    return inner or castbox_target(url)",
     "target": _CBX,
     "expect": "test_the_ssrf_payloads_never_reach_the_engine[cloud-metadata]"},

    # **دفاعِ دوم** — گارد. عمداً موردِ جدا: این تنها چیزی است که بازسازی
    # نمی‌گیردش (خودِ castbox.fm داخلی شود). اگر با موردِ بالا یکی بود،
    # برداشتنِ گارد «نگرفت» گزارش می‌شد در حالی که دفاعِ دیگری کار کرده بود.
    {"name": "castbox: drop the SSRF guard from resolve_castbox",
     "path": "app/downloader.py",
     "old": "    if not await is_safe_url_resolved(target, proxy=proxy):\n"
            '        log.warning("castbox: rewritten target failed the safety gate: %s", target[:90])\n'
            "        return None\n",
     "new": "",
     "target": _CBX,
     "expect": "test_the_guard_rejects_a_castbox_that_resolves_internal"},

    # تلهٔ دو-شناسه‌ای: الگوی ساده‌لوحانه شناسهٔ **کانال** را برمی‌دارد.
    {"name": "castbox: naive id pattern takes the channel id, not the episode",
     "path": "app/downloader.py",
     "old": r'_CB_EP_SLUG_RE = re.compile(r"^(?:www\.|m\.)?castbox\.fm/episode/.*-id(\d+)$")',
     "new": r'_CB_EP_SLUG_RE = re.compile(r"^(?:www\.|m\.)?castbox\.fm/episode/.*?id(\d+)")',
     "target": _CBX,
     "expect": "test_the_naive_id_pattern_would_take_the_channel_id"},

    # عمقِ بازکردن باید یک بماند.
    {"name": "castbox: unwrap link= recursively",
     "path": "app/downloader.py",
     "old": "    inner = (q.get(\"link\") or [\"\"])[0]\n"
            "    return _castbox_direct_ids(inner) if inner else (None, None)",
     "new": "    inner = (q.get(\"link\") or [\"\"])[0]\n"
            "    return castbox_ids(inner) if inner else (None, None)",
     "target": _CBX,
     "expect": "test_the_unwrap_depth_is_one"},

    # کلیدِ کش: بدونِ شاخهٔ `cb:` هر شکل کلیدِ خودش را می‌گیرد.
    {"name": "castbox: drop the cache-key normalisation",
     "path": "app/dl_cache.py",
     "old": '    kind, cid = castbox_ids(u)\n    if kind and cid:\n        return f"cb:{kind}:{cid}"\n',
     "new": "",
     "target": _CBX,
     "expect": "test_every_episode_form_reaches_one_cache_key[vb-short]"},

    # ردِ کانال: بدونش کاربر خطای خامِ yt-dlp می‌گیرد.
    {"name": "castbox: let a channel link fall through to the engine",
     "path": "app/routers/download.py",
     "old": '        if kind == "ch":',
     "new": "        if False:",
     "target": _CBX,
     "expect": "test_a_channel_link_gets_a_clear_message[va-short]"},

    # بازنویسی واقعاً باید اعمال شود، نه فقط محاسبه.
    {"name": "castbox: compute the rewrite but never apply it",
     "path": "app/routers/download.py",
     "old": "        url = target\n",
     "new": "",
     "target": _CBX,
     "expect": "test_a_short_episode_link_is_enqueued_rewritten"},

    # عضویت در `AUDIO_PLATFORMS` باید به selectorِ جاب برسد. توجه: این **انتخابِ
    # فرمت** را عوض نمی‌کند (اجراشده: `audio` و `best` هر دو همان تک‌فرمت را
    # می‌دهند، و خودِ `test_the_production_selector_…` هر دو را assert می‌کند)،
    # پس چیزی که این‌جا می‌شکند ادعای UX است نه ادعای انتخابگر.
    {"name": "castbox: not an audio platform (selector of the enqueued job)",
     "path": "app/downloader.py",
     "old": 'AUDIO_PLATFORMS = {"soundcloud", "bandcamp", "spotify", "apple", "castbox"}',
     "new": 'AUDIO_PLATFORMS = {"soundcloud", "bandcamp", "spotify", "apple"}',
     "target": _CBX,
     "expect": "test_a_short_episode_link_is_enqueued_rewritten"},

    # گاردِ **هارنس**، نه گاردِ سورس — و تنها موردی که فایلِ تست را خراب می‌کند.
    # هاردکدکردنِ فلگ دقیقاً همان false failی است که یک‌بار به یک مشکلِ خیالی
    # رساند؛ این مورد ثابت می‌کند آن گارد زنده است و دوباره نمی‌گذارد بلغزد.
    {"name": "castbox: hardcode incomplete_formats in the harness (harness guard)",
     "path": _CBX,
     "old": "    return seen",
     "new": '    return {**seen, "incomplete_formats": False}',
     "target": _CBX,
     "expect": "test_the_harness_computes_the_flag_like_yt_dlp_does"},

    # ── کپشنِ HTMLدار ──────────────────────────────────────────────
    # **گیت** — تنها چیزی که جلوی خراب‌شدنِ کپشنِ سادهٔ اینستاگرام را می‌گیرد.
    # این مهم‌ترین موردِ این دسته است: بدونِ گیت، رفع یک زشتیِ کوچک را با یک
    # باگِ واقعی در پرترافیک‌ترین مسیر عوض می‌کند.
    {"name": "caption: strip unconditionally (no HTML gate)",
     "path": "app/downloader.py",
     "old": "    if _HTML_GATE.search(text):\n        text = strip_html(text)",
     "new": "    text = strip_html(text)",
     "target": _CAP,
     "expect": "test_a_plain_caption_is_untouched[code-lt-b]"},

    # رجکسِ ساده‌لوحانه به‌جای پارسر — متنِ حاویِ `<` را می‌خورد.
    {"name": "caption: naive regex instead of the parser",
     "path": "app/downloader.py",
     "old": "    p = _HTMLStripper()\n    try:\n        p.feed(text)\n        p.close()\n"
            "    except Exception:  # noqa: BLE001 — HTMLِ خراب نباید کپشن را از بین ببرد\n"
            "        return text\n    out = p.value().replace(\"\\xa0\", \" \")",
     "new": "    out = re.sub(r\"<[^>]+>\", \"\", text).replace(\"\\xa0\", \" \")",
     "target": _CAP,
     "expect": "test_a_less_than_sign_in_prose_survives"},

    # تگِ بلوکی حذف شود به‌جای تبدیل به `\n` — پاراگراف‌ها به هم می‌چسبند.
    {"name": "caption: drop block tags instead of turning them into newlines",
     "path": "app/downloader.py",
     "old": "_BLOCK_TAGS = {\"p\", \"br\", \"div\", \"li\", \"tr\", \"ul\", \"ol\", \"blockquote\", \"section\",\n"
            "               \"h1\", \"h2\", \"h3\", \"h4\", \"h5\", \"h6\"}",
     "new": "_BLOCK_TAGS: set[str] = set()",
     "target": _CAP,
     "expect": "test_the_real_description_keeps_its_paragraphs_apart"},

    # ترتیبِ برعکس: اول unescape بعد حذفِ تگ → متنِ عمداً escapeشده خورده می‌شود.
    {"name": "caption: unescape before stripping (wrong order)",
     "path": "app/downloader.py",
     "old": "    p = _HTMLStripper()\n    try:\n        p.feed(text)",
     "new": "    import html as _h\n    text = _h.unescape(text)\n"
            "    p = _HTMLStripper()\n    try:\n        p.feed(text)",
     "target": _CAP,
     "expect": "test_deliberately_escaped_markup_stays_text"},

    # تصمیمِ «ب»: آدرس دور ریخته شود (رفتارِ گزینهٔ «الف»).
    {"name": "caption: drop the anchor URL (option A behaviour)",
     "path": "app/downloader.py",
     "old": "        if not text.strip():\n            self._out.append(href)\n"
            "        elif href not in text:\n            self._out.append(f\" ({href})\")",
     "new": "        return",
     "target": _CAP,
     "expect": "test_an_anchor_keeps_both_its_text_and_its_url"},

    # فاصلهٔ ابتدای خط جمع نشود — تورفتگیِ بی‌دلیل در توضیحاتِ واقعی.
    {"name": "caption: leave the leading indent on each line",
     "path": "app/downloader.py",
     "old": '    return "\\n".join(ln.strip() for ln in out.splitlines())',
     "new": '    return "\\n".join(ln.rstrip() for ln in out.splitlines())',
     "target": _CAP,
     "expect": "test_the_real_description_has_no_leading_indent"},

    # ── کاورِ صوتی ─────────────────────────────────────────────────
    {"name": "cover: drop --embed-thumbnail entirely",
     "path": "app/downloader.py",
     "old": 'cmd += ["-x", "--audio-format", "mp3", "--embed-thumbnail"]',
     "new": 'cmd += ["-x", "--audio-format", "mp3"]',
     "target": _COV,
     "expect": "test_the_audio_path_embeds_the_cover"},

    # گیتِ `audio_only` — قیدِ سختِ این کار. بدونش مسیرِ ویدیو روی منبعِ
    # فقط‌صوتی `opus`/`webm` می‌گیرد و `EmbedThumbnailPP` raise می‌کند، که با
    # نبودِ `--ignore-errors` یعنی کلِ دانلود می‌شکند.
    {"name": "cover: embed on the video path too (drops the audio_only gate)",
     "path": "app/downloader.py",
     "old": '        cmd += ["-S", _FORMAT_SORT,          # h264/aac/mp4 را در همان رزولوشن ترجیح بده\n'
            '                "--merge-output-format", "mp4",',
     "new": '        cmd += ["-S", _FORMAT_SORT, "--embed-thumbnail",\n'
            '                "--merge-output-format", "mp4",',
     "target": _COV,
     "expect": "test_the_video_path_never_embeds[best]"},

    # گاردِ **هارنس**: اگر ffprobeِ جعلی همیشه mp3 بدهد، کنترلِ منفی مرده است و
    # «ffmpeg صدا زده نشد» دیگر چیزی ثابت نمی‌کند.
    {"name": "cover: harness always reports mp3 (kills the negative control)",
     "path": "tests/test_audio_cover.py",
     "old": "    pp.get_audio_codec = lambda path: src_acodec",
     "new": '    pp.get_audio_codec = lambda path: "mp3"',
     "target": _COV,
     "expect": "test_the_harness_can_tell_a_transcode_from_a_copy"},

    # **کنترلِ معکوس:** جای فلگ در همان شاخه مهم نیست — تست‌ها **حضور** را
    # می‌سنجند نه ترتیب. اگر این چیزی را بیندازد یعنی تستی به ترتیبِ آرگومان
    # چسبیده که نباید.
    {"name": "cover: reorder the flag within the audio branch (must break nothing)",
     "path": "app/downloader.py",
     "old": 'cmd += ["-x", "--audio-format", "mp3", "--embed-thumbnail"]',
     "new": 'cmd += ["-x", "--embed-thumbnail", "--audio-format", "mp3"]',
     "target": _COV,
     "expect": None},

    # ── دو زیرفرایندِ یتیمِ باقی‌مانده ────────────────────────────────
    # الگوها عمداً با خطِ **قبلشان** لنگر می‌خورند: بلوکِ
    # `except BaseException:` عیناً دو بار در فایل هست (probe و جست‌وجوی
    # تطبیق) و الگوی کوتاه هر دو را می‌زد — یعنی همان تلهٔ `trim_video`/
    # `trim_audio` که `patch_source` برای گرفتنش ساخته شد.
    {"name": "orphan: probe stops killing its child (pre-fix form)",
     "path": "app/downloader.py",
     "old": '            raise RuntimeError("probe timed out") from None\n'
            '        except BaseException:\n'
            '            _P.kill_orphan(proc)\n'
            '            raise\n',
     "new": '            raise RuntimeError("probe timed out") from None\n',
     "target": _ORP,
     "expect": "test_probe_does_not_leave_yt_dlp_running_after_cancellation"},

    # کنترلِ معکوس: خرابکاریِ probe نباید ادعای **جست‌وجو** را بیندازد. اگر
    # بیفتد، دو مسیر یک assert مشترک دارند و هرکدام جدا اثبات نشده‌اند (§۷:
    # دفاع در عمق، تست در عمق).
    {"name": "orphan: probe unfixed — but the match-search claim stays green",
     "path": "app/downloader.py",
     "old": '            raise RuntimeError("probe timed out") from None\n'
            '        except BaseException:\n'
            '            _P.kill_orphan(proc)\n'
            '            raise\n',
     "new": '            raise RuntimeError("probe timed out") from None\n',
     "target": _ORP + "::test_the_match_search_does_not_leave_yt_dlp_running",
     "expect": None},

    {"name": "orphan: the match search stops killing its child (pre-fix form)",
     "path": "app/downloader.py",
     "old": '            return []\n'
            '        except BaseException:\n'
            '            _P.kill_orphan(proc)\n'
            '            raise\n',
     "new": '            return []\n',
     "target": _ORP,
     "expect": "test_the_match_search_does_not_leave_yt_dlp_running"},

    # هلپرِ مشترک باربر است، نه آرایش: خنثی‌کردنش باید **کنترلِ مثبت** را
    # بیندازد — یعنی مسیرِ از-قبل-رفع‌شدهٔ `_run_dl` هم واقعاً از آن رد می‌شود.
    {"name": "orphan: the shared kill_orphan helper is neutered",
     "path": "app/processing.py",
     "old": "    if proc.returncode is None:\n        try:\n            proc.kill()",
     "new": "    if False:\n        try:\n            proc.kill()",
     "target": _ORP,
     "expect": "test_the_harness_can_observe_a_kill"},

    # ── فاز ۳: مسیرِ تستِ رفتاریِ پنل ───────────────────────────────────────
    # این موردها فقط `tests/` را می‌خوانند و هیچ‌کدام به استکِ ادمین نیاز ندارند،
    # پس در همان محیطِ `requirements-dev.txt` اجرا می‌شوند. موردهایی که خودِ
    # `tests/panel/` را هدف بگیرند **به `requirements-admin.txt` نیاز دارند**،
    # چون `_run_case` واقعاً pytest را روی آن مسیر می‌دواند.
    {"name": "panel: drop the tests/panel exemption from the import guard",
     "path": "tests/test_repo_hygiene.py",
     "old": '_PANEL_DIR = "tests/panel"',
     "new": '_PANEL_DIR = "tests/nowhere"',
     "target": _HYG,
     "expect": "test_no_test_imports_a_module_the_ci_runner_does_not_have"},

    {"name": "panel: stop the guard reading conftest.py",
     "path": "tests/test_repo_hygiene.py",
     "old": 'return sorted({*tests_dir.rglob("test_*.py"), *tests_dir.rglob("conftest.py")})',
     "new": 'return sorted(tests_dir.rglob("test_*.py"))',
     "target": _HYG,
     "expect": "test_the_guard_also_reads_conftest_files"},

    {"name": "panel: blind the guard to the from-package import form again",
     "path": "tests/test_repo_hygiene.py",
     "old": "            for alias in node.names:\n"
            "                yield f\"{node.module}.{alias.name}\", node.lineno",
     "new": "            pass",
     "target": _HYG,
     "expect": "test_the_guard_sees_the_from_package_import_form"},

    {"name": "panel: make the CI panel job depend on the main job",
     "path": ".github/workflows/tests.yml",
     "old": "  panel:\n    runs-on: ubuntu-latest",
     "new": "  panel:\n    needs: pytest\n    runs-on: ubuntu-latest",
     "target": _PAL,
     "expect": "test_the_panel_job_runs_in_parallel_with_the_main_job"},

    {"name": "panel: drop the collected-count gate from the CI job",
     "path": ".github/workflows/tests.yml",
     "old": "          n=$(pytest tests/panel --collect-only -q | grep -c '::')",
     "new": "          n=5",
     "target": _PAL,
     "expect": "test_the_panel_job_asserts_a_nonzero_collection"},

    {"name": "panel: stop pytest.ini ignoring the panel dir by default",
     "path": "pytest.ini",
     "old": "addopts = --ignore=tests/panel",
     "new": "addopts =",
     "target": _PAL,
     "expect": "test_pytest_ini_keeps_the_panel_directory_out_of_the_default_run"},

    # **کنترلِ معکوس:** جابه‌جاییِ ترتیبِ دو کلیدِ requirements در همان دستور
    # نباید چیزی را بشکند — گاردها **حضور** را می‌سنجند نه ترتیب را. اگر این
    # چیزی بیندازد یعنی گاردی به شکلِ رشته چسبیده که نباید.
    {"name": "panel: reorder the two requirements files in the install step (must break nothing)",
     "path": ".github/workflows/tests.yml",
     "old": "pip install -r requirements-dev.txt -r requirements-admin.txt",
     "new": "pip install -r requirements-admin.txt -r requirements-dev.txt",
     "target": _PAL,
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
