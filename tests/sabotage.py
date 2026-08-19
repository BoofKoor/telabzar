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
_SEC = "tests/panel/test_security_headers.py"
_SVF = "tests/panel/test_save_failures.py"
_LRL = "tests/panel/test_login_rate_limit.py"
_POT = "tests/panel/test_pot_health.py"
_USR = "tests/panel/test_users_page.py"
_SBD = "tests/test_settings_bounds.py"
_UPD = "tests/test_upload_direction.py"
_UPC = "tests/test_upload_ceiling.py"
_SBH = "tests/test_sabotage_helper.py"
_PCC = "tests/panel/test_panel_css_classes.py"
_CSB = "tests/panel/test_cookie_status_badges.py"
_SKC = "tests/panel/test_settings_key_coverage.py"
_SCL = "tests/panel/test_scope_labels.py"
_PST = "tests/test_probe_stats.py"
_HLT = "tests/panel/test_health_page.py"
_TXT = "tests/panel/test_texts_page.py"
_NDS = "tests/panel/test_nodes_page.py"
_BTN = "tests/panel/test_buttons_page.py"
_STC = "tests/panel/test_stats_cards.py"
_URW = "tests/panel/test_users_rows.py"
_PGF = "tests/panel/test_pagefacts.py"
_PCT = "tests/panel/test_page_contract.py"
_I18 = "tests/test_i18n_fallback.py"
_LPK = "tests/test_langpack.py"
_LNG = "tests/panel/test_langs_page.py"
_STF = "tests/test_start_flow.py"
_PAR = "tests/test_locale_parity.py"

# «گروهِ خودکار را بردار» — یک خرابکاری با **سه** ادعای متفاوت، پس یک‌بار
# تعریف می‌شود. دو تا باید بیفتند و یکی عمداً **نباید**، که کلِ نکته است:
# شش ردیفِ دست‌نویس پوشش را نگه می‌دارند، ولی دوام از این گروه می‌آید.
_AUTO_GROUP_PATCH = {
    "path": "app/admin_web.py",
    "old": "    return [*GROUPS, (_AUTO_GROUP, leftover)] if leftover else list(GROUPS)",
    "new": "    return list(GROUPS)",
}

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

    # ── تست‌های characterization ────────────────────────────────────────────
    # این‌ها شکلِ **معکوس** دارند: «خرابکاری» در واقع همان **رفعِ فاز ۲** است، و
    # ادعا این است که تستِ `..._TODAY_...` مربوطه آشکارا قرمز می‌شود. اگر یکی از
    # این‌ها «نگرفت» بدهد یعنی آن تست رفتارِ امروز را pin نمی‌کند و فاز ۲
    # می‌تواند بی‌صدا از کنارش رد شود.
    #
    # ⚠️ این چهار مورد `tests/panel/` را هدف می‌گیرند، پس **به
    # `requirements-admin.txt` نیاز دارند**؛ در محیطِ فقط-dev با خطای collect
    # می‌افتند و نتیجه بی‌معناست.


    {"name": "char: A-2 fix — stop returning service config from /node/join",
     "path": "app/admin_web.py",
     "old": "    cfg = node_mod.node_config(role, ip)",
     "new": '    cfg = {"services": {}}',
     "target": _CHR,
     "expect": "test_an_unauthenticated_caller_can_still_redeem_a_valid_token"},


    # ── فاز ۲: بستنِ زنجیرهٔ راز ────────────────────────────────────────────
    # ⚠️ موردهای `tests/panel/` به `requirements-admin.txt` نیاز دارند.
    {"name": "phase2 A-1: restore the bot-token fallback in _fernet",
     "path": "app/admin_web.py",
     "old": "    seed = settings.admin_secret\n    if not seed:\n        raise RuntimeError(_NO_SECRET)",
     "new": "    seed = settings.admin_secret or settings.bot_token",
     "target": _CHR,
     "expect": "test_an_empty_admin_secret_no_longer_yields_a_usable_key"},

    {"name": "phase2 A-1: let an empty secret 500 instead of failing closed",
     "path": "app/admin_web.py",
     "old": "    except RuntimeError:\n        # رازِ خالی.",
     "new": "    except (ValueError,):\n        # رازِ خالی.",
     "target": _CHR,
     "expect": "test_a_bot_token_cookie_is_rejected_when_the_secret_is_empty"},

    {"name": "phase2 A-1: main() serves anyway with an empty secret",
     "path": "app/admin_web.py",
     "old": "    _require_admin_secret()      # پیش از هر کاری",
     "new": "    pass                         # پیش از هر کاری",
     "target": _HYG,
     "expect": "test_main_refuses_to_serve_without_the_session_secret"},

    {"name": "phase2 A-1: drop the actionable command from the refusal message",
     "path": "app/admin_web.py",
     "old": "openssl rand -hex 32",
     "new": "some random value",
     "target": _CHR,
     "expect": "test_the_refusal_message_tells_the_operator_what_to_run"},

    {"name": "phase2 A-1: installer stops generating the secret",
     "path": "install.sh",
     "old": '  ADMIN_SECRET=$(env_get ADMIN_SECRET); [[ -n "$ADMIN_SECRET" ]] || ADMIN_SECRET=$(rand 32)',
     "new": '  ADMIN_SECRET=$(env_get ADMIN_SECRET)',
     "target": _HYG,
     "expect": "test_every_generated_secret_is_actually_generated_by_the_installer"},

    # ── فاز ۲: A-2 (توکن از URL بیرون) + C-2 (Referrer-Policy) ─────────────
    # الگو با خطِ **قبلش** لنگر می‌خورد: `raise web.HTTPFound("/nodes")` سه بار
    # در فایل هست و الگوی کوتاه هر سه را می‌زد — همان چیزی که `patch_source`
    # برای گرفتنش ساخته شد، و همین‌جا هم گرفتش.
    {"name": "phase2 A-2: put the join token back in the redirect URL",
     "path": "app/admin_web.py",
     "old": '    await _stash_join_view(request.app["redis"], _session_admin(request), tok)\n'
            '    raise web.HTTPFound("/nodes")',
     "new": '    raise web.HTTPFound(f"/nodes?tok={tok}")',
     "target": _CHR,
     "expect": "test_the_join_token_never_appears_in_a_url"},

    # ادعای مستقل و مهم‌ترین: لاگ. جدا از تستِ بالا، چون آن یکی دربارهٔ
    # `Location` است و این یکی دربارهٔ چیزی که روی دیسکِ سرور می‌نشیند.
    {"name": "phase2 A-2: the token lands in the access log again",
     "path": "app/admin_web.py",
     "old": '    await _stash_join_view(request.app["redis"], _session_admin(request), tok)\n'
            '    raise web.HTTPFound("/nodes")',
     "new": '    await _stash_join_view(request.app["redis"], _session_admin(request), tok)\n'
            '    raise web.HTTPFound(f"/nodes?tok={tok}")',
     "target": _CHR,
     "expect": "test_the_token_never_reaches_the_access_log"},

    {"name": "phase2 A-2: show the install command on every refresh",
     "path": "app/admin_web.py",
     "old": '        return await redis.getdel(f"{_JOIN_VIEW}{admin_id}") or ""',
     "new": '        return await redis.get(f"{_JOIN_VIEW}{admin_id}") or ""',
     "target": _CHR,
     "expect": "test_the_install_command_is_shown_once_from_the_session"},

    {"name": "phase2 A-2: stash the token under a shared key, not per-admin",
     "path": "app/admin_web.py",
     "old": '        await redis.set(f"{_JOIN_VIEW}{admin_id}", token, ex=_JOIN_VIEW_TTL)',
     "new": '        await redis.set(f"{_JOIN_VIEW}shared", token, ex=_JOIN_VIEW_TTL)',
     "target": _CHR,
     "expect": "test_another_admin_cannot_pick_up_the_token"},

    {"name": "phase2 C-2: drop Referrer-Policy from redirects and errors",
     "path": "app/admin_web.py",
     "old": '    except web.HTTPException as exc:\n        exc.headers.update(headers)\n        raise',
     "new": "    except web.HTTPException:\n        raise",
     "target": _CHR,
     "expect": "test_every_response_carries_a_referrer_policy"},

    # ── فاز ۲: A-3 (اعتبارسنجی پیش از مصرف) ────────────────────────────────
    {"name": "phase2 A-3: consume the token before validating again",
     "path": "app/admin_web.py",
     "old": '    if not pubkey or len(pubkey) > 64:\n        return web.json_response({"error": "missing pubkey"}, status=400)\n    payload = await node_mod.consume_join_token(request.app["redis"], token)\n    if payload is None:\n        return web.json_response({"error": "invalid or used token"}, status=403)',
     "new": '    payload = await node_mod.consume_join_token(request.app["redis"], token)\n    if payload is None:\n        return web.json_response({"error": "invalid or used token"}, status=403)\n    if not pubkey or len(pubkey) > 64:\n        return web.json_response({"error": "missing pubkey"}, status=400)',
     "target": _CHR,
     "expect": "test_a_malformed_join_does_not_burn_the_token"},

    # نیمهٔ دومِ همان `if`. اگر فقط شاخهٔ «غایب» تست می‌شد، یک نصفه‌رفع بی‌صدا
    # از کنارش رد می‌شد.
    {"name": "phase2 A-3: drop the length half of the pubkey check",
     "path": "app/admin_web.py",
     "old": "    if not pubkey or len(pubkey) > 64:",
     "new": "    if not pubkey:",
     "target": _CHR,
     "expect": "test_an_oversized_pubkey_also_leaves_the_token_usable"},

    # ── فاز ۲: بقیهٔ هدرهای امنیتی ─────────────────────────────────────────
    {"name": "phase2 headers: drop X-Frame-Options (panel becomes frameable)",
     "path": "app/admin_web.py",
     "old": '    "X-Frame-Options": "DENY",',
     "new": "",
     "target": _SEC,
     "expect": "test_the_hardening_headers_are_on_an_ordinary_page"},

    {"name": "phase2 headers: send HSTS unconditionally",
     "path": "app/admin_web.py",
     "old": '    if request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https":\n'
            '        headers["Strict-Transport-Security"] = _HSTS',
     "new": '    headers["Strict-Transport-Security"] = _HSTS',
     "target": _SEC,
     "expect": "test_hsts_is_sent_only_over_https"},

    {"name": "phase2 headers: a CSP that would blank the panel",
     "path": "app/admin_web.py",
     "old": '"default-src \'self\'; img-src \'self\' data:; style-src \'self\' \'unsafe-inline\'; "',
     "new": '"default-src \'self\'; img-src \'self\' data:; style-src \'self\'; "',
     "target": _SEC,
     "expect": "test_the_csp_permits_what_the_panel_actually_serves"},

    # **کنترلِ معکوس:** یک منبعِ خارجی که CSP بلاکش می‌کند باید گرفته شود.
    {"name": "phase2 headers: add an external CDN reference",
     "path": "app/admin_web.py",
     "old": "<title>{% block title %}پنلِ مدیریت{% endblock %}",
     "new": '<script src="https://cdn.example.com/x.js"></script>'
            "<title>{% block title %}پنلِ مدیریت{% endblock %}",
     "target": _SEC,
     "expect": "test_the_panel_has_no_external_resources_for_the_csp_to_break"},

    # **کنترلِ معکوس:** تغییری در همان تابع که هیچ ادعای ثبت‌شده‌ای را جابه‌جا
    # نمی‌کند. اگر چیزی بیندازد یعنی تستی به جزئیاتِ بی‌ربط چسبیده.
    {"name": "char: rename a local in node_join (must break nothing)",
     "path": "app/admin_web.py",
     "old": '        nid = secrets.token_urlsafe(9)[:12]',
     "new": '        nid = secrets.token_urlsafe(9)[:12]  # noqa',
     "target": _CHR,
     "expect": None},

    # ── خوشهٔ شکستِ خاموش (B-1/B-3/B-4/B-5) ──
    # گاردِ واگرایی: یک محلِ فراخوانی دوباره دستی نوشته شود.
    {"name": "panel: a result redirect goes back to being hand-written",
     "path": "app/admin_web.py",
     "old": 'raise _result("/cookies", ok="del")',
     "new": 'raise web.HTTPFound("/cookies?ok=del")',
     "target": _HYG,
     "expect": "test_the_panel_has_one_result_redirect"},

    # B-1: متنِ ردشده دوباره به «حذفِ override» ترجمه شود (شکلِ پیش از رفع).
    {"name": "buttons: a rejected label goes back to resetting the override",
     "path": "app/admin_web.py",
     "old": '            errors.append(f"«{default}»: {err}")',
     "new": '            texts.append((key, None))',
     "target": _SVF,
     "expect": "test_a_rejected_label_does_not_delete_the_healthy_one"},

    # B-1: خطا جمع شود ولی نادیده گرفته شود — ادعای گزارش‌دادن و اتمیک‌بودن را
    # جدا از ادعای حذف می‌سنجد (این یکی overrideِ سالم را پاک **نمی‌کند**).
    {"name": "buttons: the collected errors stop being reported",
     "path": "app/admin_web.py",
     "old": "    if errors:\n        # هیچ نوشتنی انجام نشده",
     "new": "    if False:  # noqa\n        # هیچ نوشتنی انجام نشده",
     "target": _SVF,
     "expect": "test_a_rejected_label_is_reported_not_celebrated"},

    # B-4: کفِ عددی برداشته شود.
    {"name": "settings: the numeric floor stops being enforced",
     "path": "app/settings_store.py",
     "old": "        if n < lo:",
     "new": "        if False:  # noqa",
     "target": _SBD,
     "expect": "test_a_negative_number_is_refused[max_file_mb]"},

    # B-4: سقف برداشته شود.
    {"name": "settings: the numeric ceiling stops being enforced",
     "path": "app/settings_store.py",
     "old": "        if hi is not None and n > hi:",
     "new": "        if False:  # noqa",
     "target": _SBD,
     "expect": "test_a_percent_over_a_hundred_is_refused[safety_threshold]"},

    # B-4: سقفِ حجم از سقفِ واقعیِ Bot API جدا شود — عدد باید به مستندش گره
    # بخورد، وگرنه یک ثابتِ دستیِ دیگر است که می‌پوسد.
    {"name": "settings: the upload ceiling drifts from the documented one",
     "path": "app/settings_store.py",
     "old": "UPLOAD_CEILING_MB = 2000",
     "new": "UPLOAD_CEILING_MB = 20000",
     "target": _SBD,
     "expect": "test_the_upload_ceiling_matches_what_the_docs_state"},

    # سقفِ آپلود دوباره روی یک کلیدِ سمتِ **دریافت** گذاشته شود — همان اشتباهی
    # که نسخهٔ اولِ این کار کرد و شاهدِ تولید (۴۴ ردیفِ بالای ۲۰۰۰ مگ) ردش کرد.
    {"name": "settings: the receive-side key gets an upload ceiling again",
     "path": "app/settings_store.py",
     "old": '    "dl_max_size_mb": (0, UPLOAD_CEILING_MB),',
     "new": ('    "max_file_mb": (0, UPLOAD_CEILING_MB),\n'
             '    "dl_max_size_mb": (0, UPLOAD_CEILING_MB),'),
     "target": _SBD,
     "expect": "test_a_receive_side_limit_has_no_telegram_ceiling"},

    # سند دوباره یک عدد را برای هر دو جهت بفروشد. پین‌کردنِ **عدد** به‌تنهایی
    # این را نمی‌گیرد — به همین دلیل تست جهت را هم می‌سنجد.
    {"name": "docs: the two directions collapse back into one number",
     "path": "docs/telegram-api.md",
     "old": "| **Download** (Telegram DC → our server) | **no size limit** |",
     "new": "| Download (Telegram DC to our server) | up to 2000 MB |",
     "target": _SBD,
     "expect": "test_the_upload_ceiling_matches_what_the_docs_state"},

    # مکانیزمِ تفکیک: اگر کارتِ فایلِ دریافتی هم بایت آپلود کند، کلِ استدلالِ
    # «سمتِ دریافت سقف ندارد» می‌ریزد.
    {"name": "cards: a received file starts uploading its bytes too",
     "path": "app/cards.py",
     "old": '    return FSInputFile(path, filename=file.name or "file") if path else file.file_id',
     "new": '    return FSInputFile(path or "/dev/null", filename=file.name or "file")',
     "target": _UPD,
     "expect": "test_a_path_uploads_bytes_and_a_file_id_does_not"},

    # B-3: پنل دیگر اعتبارسنجی را صدا نزند — ادعای «وصل است» جدا از ادعای
    # «تابع درست است».
    {"name": "settings: the panel stops calling the validator",
     "path": "app/admin_web.py",
     "old": "            err = settings_store.validate_value(k, val)",
     "new": "            err = None",
     "target": _SVF,
     "expect": "test_an_invalid_setting_is_refused_not_swallowed[max_file_mb=-1-negative]"},

    # B-3/B-4: مسیرِ تلگرام دوباره از قاعدهٔ مشترک جدا شود.
    {"name": "settings: the telegram path stops sharing the rule",
     "path": "app/routers/admin.py",
     "old": '    return escape(settings_store.validate_value(key, value) or "") or None',
     "new": "    return None",
     "target": _SBD,
     "expect": "test_the_telegram_path_refuses_what_the_panel_refuses[negative]"},

    # **کنترلِ معکوس:** مرتب‌سازیِ حلقهٔ `/save` جزئیاتِ بی‌ربط است؛ اگر چیزی
    # بیندازد یعنی تستی به ترتیبِ پیمایش چسبیده، نه به رفتار.
    {"name": "settings: iterate the form in set order (must break nothing)",
     "path": "app/admin_web.py",
     "old": "    for k in sorted(rendered):",
     "new": "    for k in rendered:",
     "target": _SVF,
     "expect": None},

    # ── پرتگاهِ آپلود: خروجیِ بالای سقف، پیش از آپلود ──────────────
    # گیت اصلاً اجرا نشود — پرتگاه دقیقاً همان‌طور که بود برمی‌گردد.
    {"name": "upload-cliff: the ceiling gate stops running",
     "path": "app/tasks.py",
     "old": "            oversize_mb = _too_big_to_send(_outgoing_paths(res))",
     "new": "            oversize_mb = None",
     "target": _UPC,
     "expect": "test_an_oversized_output_is_refused_before_any_upload[path]"},

    # شکلِ `spawn` از گیت بیفتد. تنها شاخه‌ای که ردیفِ `File` را **پیش از**
    # آپلود commit می‌کند، پس افتادنش هم آپلود را برمی‌گرداند هم ردیفِ یتیم را.
    {"name": "upload-cliff: the spawn shape drops out of the gate",
     "path": "app/tasks.py",
     "old": '    if res.get("spawn"):\n        out.append(res["spawn"]["path"])',
     "new": '    if False:\n        out.append(res["spawn"]["path"])',
     "target": _UPC,
     "expect": "test_an_oversized_output_is_refused_before_any_upload[spawn]"},

    # شکلِ `files` از گیت بیفتد. امروز عملاً غیرقابلِ‌رسیدن است
    # (`max_extract_mb=500`)، و **دقیقاً به همین دلیل** مستعدترین شکل برای
    # پوسیدنِ بی‌صداست — یعنی کیسی که بیش از همه لازم است ثبت شود.
    {"name": "upload-cliff: the files shape drops out of the gate",
     "path": "app/tasks.py",
     "old": '    out.extend(res.get("files") or [])',
     "new": "    out.extend([])",
     "target": _UPC,
     "expect": "test_an_oversized_output_is_refused_before_any_upload[files]"},

    # مقایسه روی مگابایتِ گردشده به‌جای بایت — فایلِ ۲۰۰۰٫۴ مگی «۲۰۰۰» خوانده
    # می‌شود و از گیت رد می‌شود.
    {"name": "upload-cliff: the ceiling is compared in rounded megabytes",
     "path": "app/tasks.py",
     "old": "        if size > limit:",
     "new": "        if round(size / 1024 / 1024) > settings_store.UPLOAD_CEILING_MB:",
     "target": _UPC,
     "expect": "test_the_ceiling_is_compared_in_bytes_not_rounded_megabytes"},

    # جمع‌زدن به‌جای سنجشِ هر آیتم. شاخهٔ `files` هر فایل را جدا می‌فرستد، پس
    # جمع، ده فایلِ ۳۰۰ مگی را به‌غلط رد می‌کند.
    {"name": "upload-cliff: the items are summed instead of measured apart",
     "path": "app/tasks.py",
     "old": "        size = os.path.getsize(p)",
     "new": "        size = sum(os.path.getsize(q) for q in paths if q and os.path.exists(q))",
     "target": _UPC,
     "expect": "test_every_item_is_measured_on_its_own_not_summed"},

    # پیامِ عمومی به‌جای پیامِ اختصاصی — همان «پردازش ناموفق» که کاربر را
    # نگرانِ ازدست‌رفتنِ فایل می‌کند.
    {"name": "upload-cliff: the user gets the generic failure note again",
     "path": "app/tasks.py",
     "old": '                                    note=t(lang, "op_too_large", mb=oversize_mb, cap=cap),',
     "new": '                                    note=t(lang, "failed"),',
     "target": _UPC,
     "expect": "test_the_user_is_told_the_size_the_cap_and_that_the_file_is_safe"},

    # جزءِ سومِ پیام برداشته شود. دو عددِ اول بمانند و فقط اطمینان‌دادن برود —
    # اگر این نیفتد یعنی تست فقط اعداد را می‌سنجد و مهم‌ترین جزء پین نشده.
    {"name": "upload-cliff: the message stops saying the original is safe",
     "path": "app/locales/fa.py",
     "old": '        "✅ فایلِ اصلی دست‌نخورده است، همینی که روی این کارت می‌بینی. اول "',
     "new": '        "✅ اول "',
     "target": _UPC,
     "expect": "test_the_user_is_told_the_size_the_cap_and_that_the_file_is_safe"},

    # `job.error` دوباره حجم را حمل کند — هر ردِ حجمی یک کلیدِ یکتا در آمار.
    {"name": "upload-cliff: the job error carries the varying size again",
     "path": "app/tasks.py",
     "old": '                job.error = f"output exceeds the {cap}MB upload limit"',
     "new": '                job.error = f"output {oversize_mb}MB exceeds the {cap}MB upload limit"',
     "target": _UPC,
     "expect": "test_the_job_error_is_stable_so_the_panel_can_group_it"},

    # شکلِ پنجم به `_do_op` اضافه شود بی‌آنکه کسی به گیت خبر بدهد.
    {"name": "upload-cliff: a fifth result shape appears unnoticed",
     "path": "app/tasks.py",
     "old": '        return {"note_only": True, "label": t(lang, "cl_scan_clean")}',
     "new": '        return {"note_only": True, "label": t(lang, "cl_scan_clean"), "attachment": None}',
     "target": _UPC,
     "expect": "test_no_new_result_shape_slips_past_the_ceiling_gate"},

    # **کنترلِ معکوس:** ترتیبِ خواندنِ شکل‌ها در `_outgoing_paths` جزئیاتِ
    # بی‌ربط است — `_too_big_to_send` «آیا چیزی از سقف رد می‌کند» را می‌پرسد،
    # نه «کدام‌یک اول». اگر این چیزی بیندازد یعنی تستی به ترتیب چسبیده.
    {"name": "upload-cliff: read the shapes in another order (must break nothing)",
     "path": "app/tasks.py",
     "old": '    out.extend(res.get("files") or [])\n    return out',
     "new": '    out.extend(res.get("files") or [])\n    out.reverse()\n    return out',
     "target": _UPC,
     "expect": None},

    # ── خودِ دفترچه: «اجرا نشد» نباید «نگرفت» خوانده شود ───────────
    # این را همین کار پیدا کرد: موردِ پنلی از venvی بدونِ jinja2 صفر خطِ
    # `FAILED` و ۳۱ خطِ `ERROR` داد و «نگرفت» گزارش شد — یعنی ابزارِ سنجش
    # یک نتیجهٔ درست را غلط خواند، همان ردهٔ §۷.
    # الگو عمداً **دو خطی** است: تک‌خطی‌اش دو بار در همین فایل پیدا می‌شود —
    # یک‌بار در `_run_case` و یک‌بار داخلِ همین ورودیِ رجیستری. گاردِ `count`
    # گرفتش، که خودش نمونهٔ زندهٔ همان چیزی است که برایش ساخته شده.
    {"name": "notebook: a target that cannot run is read as 'not caught' again",
     "path": "tests/sabotage.py",
     "old": '    errored = [ln for ln in summary if ln.startswith("ERROR")]\n    if errored:',
     "new": "    errored = []\n    if errored:",
     "target": _SBH,
     "expect": "test_a_target_that_cannot_even_run_is_not_reported_as_not_caught"},

    # و نیمهٔ دومش: کنترلِ معکوسی که روی هدفِ خالی سبز می‌شد.
    {"name": "notebook: an empty run passes as a clean reverse control again",
     "path": "tests/sabotage.py",
     "old": ('    if any(ln.startswith("no tests ran") for ln in lines):\n'
             '        return False, "هیچ تستی'),
     "new": '    if False:\n        return False, "هیچ تستی',
     "target": _SBH,
     "expect": "test_an_empty_run_is_not_reported_as_a_clean_reverse_control"},

    # و نیمهٔ سوم، که خودِ همین اجرا پیدایش کرد: تطبیقِ زیررشته‌ای به‌جای
    # ابتدای خط، یک اجرای سالم را «هدف خالی بود» می‌خواند — چون تستی که این
    # عبارت را ورودی می‌دهد، آن را در تریس‌بک چاپ می‌کند.
    {"name": "notebook: the empty-run check goes back to substring matching",
     "path": "tests/sabotage.py",
     "old": '    if any(ln.startswith("no tests ran") for ln in lines):\n        return False, "هیچ تستی',
     "new": '    if "no tests ran" in r.stdout:\n        return False, "هیچ تستی',
     "target": _SBH,
     "expect": "test_the_empty_run_check_does_not_fire_on_test_content"},

    # و نیمهٔ چهارم، که اجرای کاملِ دفترچه پیدایش کرد: خواندنِ کلِ stdout
    # به‌جای بخشِ خلاصه. لاگِ خودِ تست هم می‌تواند با `ERROR` شروع شود، پس سه
    # اجرای **سالم** «هدف اجرا نشد» خوانده شدند.
    {"name": "notebook: the summary section stops bounding the scan",
     "path": "tests/sabotage.py",
     "old": ('    head = next((i for i, ln in enumerate(lines) if "short test summary info" in ln), None)\n'
             "    summary = lines[head + 1:] if head is not None else []"),
     "new": ('    head = next((i for i, ln in enumerate(lines) if "short test summary info" in ln), None)\n'
             "    summary = lines"),
     "target": _SBH,
     "expect": "test_a_log_line_starting_with_error_is_not_a_collection_error"},

    # B-5: پنل دوباره نامِ فرم را نخواند (شکلِ پیش از رفع).
    {"name": "nodes: the panel stops reading the name field",
     "path": "app/admin_web.py",
     "old": '    name = (form.get("name") or "").strip()[:node_mod.NAME_MAX]',
     "new": '    name = ""',
     "target": _SVF,
     "expect": "test_the_node_name_the_admin_typed_is_the_one_that_sticks"},

    # B-5: نام حمل شود ولی نودِ خودگزارش دوباره برنده شود.
    {"name": "nodes: the node's own hostname wins again",
     "path": "app/admin_web.py",
     "old": '    chosen = (payload.get("name") or "").strip() or name',
     "new": "    chosen = name",
     "target": _SVF,
     "expect": "test_the_node_name_the_admin_typed_is_the_one_that_sticks"},

    # B-5: نقشِ نامعتبر دوباره بی‌صدا برگردد.
    {"name": "nodes: an invalid role goes back to a silent redirect",
     "path": "app/admin_web.py",
     "old": 'raise _result("/nodes", err="نقشِ نامعتبر.")',
     "new": 'raise web.HTTPFound("/nodes")',
     "target": _SVF,
     "expect": "test_an_invalid_role_says_so"},

    # ── محدودیتِ نرخِ مسیرِ لاگین ──────────────────────────────────────────
    # ⚠️ این موارد `tests/panel/` را هدف می‌گیرند، پس به `requirements-admin.txt`
    # نیاز دارند؛ بدونِ آن، هدف اصلاً اجرا نمی‌شود (که دفترچه آن را به‌عنوان
    # حالتِ سومِ «اجرا نشد» گزارش می‌کند، نه «نگرفت»).
    #
    # یکی به‌ازای هر لایه، چون سه دفاعِ مستقل روی یک مسیرند و یک سابوتاژِ
    # تک‌لایه‌ای در حضورِ لایهٔ دیگر «نگرفت» گزارش می‌شود (§۶).
    # الگو **دو خطی** است چون بلوکِ کامنتِ بالای همین ثابت هم `_CODE_TRIES = 3`
    # را نقل می‌کند — همان خودارجاعی که یک‌بار یک گاردِ ASTی داکس‌استرینگِ خودش
    # را گرفت. اولین اجرای دفترچه با «الگو ۲ بار پیدا شد» گرفتش.
    {"name": "login: the per-code guess budget goes back to six",
     "path": "app/admin_web.py",
     "old": "_CODE_TTL = 300\n_CODE_TRIES = 3",
     "new": "_CODE_TTL = 300\n_CODE_TRIES = 6",
     "target": _LRL,
     "expect": "test_the_guess_budget_per_issued_code_is_three"},

    # لایهٔ ریست، تنها جایی که خودش به‌تنهایی تصمیم می‌گیرد (مصرفِ ناقص).
    {"name": "login: a fresh code inherits the half-spent guess counter",
     "path": "app/admin_web.py",
     "old": '    await r.delete(f"paneltry:{admin_id}")',
     "new": "    pass",
     "target": _LRL,
     "expect": "test_a_fresh_code_starts_with_a_full_guess_budget"},

    # کنترلِ معکوسِ همان: برداشتنِ **یک** لایه ادعای انتها‌به‌انتها را نمی‌اندازد،
    # چون پاک‌شدنِ کد هم همان کلید را می‌برد. اولین اجرای دفترچه همین را نشان داد.
    {"name": "login: dropping only the reset must NOT fail the end-to-end claim",
     "path": "app/admin_web.py",
     "old": '    await r.delete(f"paneltry:{admin_id}")',
     "new": "    pass",
     "target": _LRL + "::test_exhausting_the_guesses_leaves_a_fresh_code_working",
     "expect": None},

    # ── C-4: ایندکسِ `last_seen` و کشِ صفحهٔ کاربران ───────────────────────
    {"name": "users: the last_seen index goes away",
     "path": "app/db.py",
     "old": '    "CREATE INDEX IF NOT EXISTS ix_users_last_seen ON users (last_seen)",\n',
     "new": "",
     "target": _USR,
     "expect": "test_the_index_matches_the_column_the_page_orders_by"},

    {"name": "users: the page queries the database on every load again",
     "path": "app/admin_web.py",
     "old": '    data = await _users_cached(request.app, page, request.query.get("q", ""))',
     "new": '    data = await _users_list(page, request.query.get("q", ""))',
     "target": _USR,
     "expect": "test_a_repeat_load_does_not_hit_the_database"},

    # باطل‌سازی برداشته شود: کش صفحه را از «کند» به **غلط** می‌برد.
    {"name": "users: blocking no longer busts the cache",
     "path": "app/admin_web.py",
     "old": '                await _users_cache_bust(request.app.get("redis"))',
     "new": "                pass",
     "target": _USR,
     "expect": "test_blocking_a_user_shows_up_immediately"},

    {"name": "users: the cache key drops the version counter",
     "path": "app/admin_web.py",
     "old": '    key = f"userscache:{await _users_cache_ver(redis)}:{page}:{q}"',
     "new": '    key = f"userscache:{page}:{q}"',
     "target": _USR,
     "expect": "test_unblocking_is_visible_immediately_too"},

    {"name": "users: every page and query share one cache key",
     "path": "app/admin_web.py",
     "old": '    key = f"userscache:{await _users_cache_ver(redis)}:{page}:{q}"',
     "new": '    key = f"userscache:{await _users_cache_ver(redis)}"',
     "target": _USR,
     "expect": "test_different_pages_and_queries_are_cached_separately"},

    {"name": "users: the cached page never expires",
     "path": "app/admin_web.py",
     "old": "        await redis.set(key, json.dumps(data, default=str), ex=_USERS_TTL)",
     "new": "        await redis.set(key, json.dumps(data, default=str))",
     "target": _USR,
     "expect": "test_the_cache_expires_on_the_modelled_clock"},

    # ── C-3: سلامتِ pot-provider نباید صفحه را نگه دارد ────────────────────
    # ⚠️ این موارد هم `tests/panel/` را هدف می‌گیرند (به `requirements-admin.txt`
    # نیاز دارند).
    #
    # برگرداندنِ پروبِ درجا — شکلِ دقیقِ پیش از رفع. تنها ادعایی که با سوکتِ
    # **واقعی** و ساعتِ واقعی سنجیده می‌شود، پس تنها ادعایی هم هست که این
    # سابوتاژ می‌تواند بیندازد.
    {"name": "pot: the health check blocks the page again",
     "path": "app/admin_web.py",
     "old": '    h["pot"] = await _pot_health(app)',
     "new": ('    h["pot"] = None\n'
             "    if settings.pot_provider_url:\n"
             '        h["pot"] = False\n'
             "        try:\n"
             "            async with aiohttp.ClientSession("
             "timeout=aiohttp.ClientTimeout(total=3)) as s:\n"
             '                async with s.get(settings.pot_provider_url + "/ping") as resp:\n'
             '                    h["pot"] = resp.status == 200\n'
             "        except Exception:  # noqa: BLE001\n"
             '            h["pot"] = False'),
     "target": _POT,
     "expect": "test_a_really_hung_provider_does_not_slow_the_dashboard"},

    {"name": "pot: a fresh cache no longer skips the probe",
     "path": "app/admin_web.py",
     "old": "    if not fresh:\n        _schedule_pot_refresh(app)",
     "new": "    _schedule_pot_refresh(app)",
     "target": _POT,
     "expect": "test_a_fresh_cached_result_makes_no_probe_at_all"},

    # دو کلید به یکی تا شود: آن‌وقت کهنه‌شدنِ کش مقدارِ شناخته‌شده را هم می‌برد.
    {"name": "pot: the last-known value expires with the freshness key",
     "path": "app/admin_web.py",
     "old": '        await r.set(_POT_LAST, "1" if ok else "0")',
     "new": '        await r.set(_POT_LAST, "1" if ok else "0", ex=_POT_FRESH_TTL)',
     "target": _POT,
     "expect": "test_the_last_known_value_outlives_the_freshness_window"},

    {"name": "pot: background refreshes pile up on every page load",
     "path": "app/admin_web.py",
     "old": "    task = app.get(_POT_TASK)\n    if task is not None and not task.done():\n        return",
     "new": "    pass",
     "target": _POT,
     "expect": "test_only_one_background_refresh_runs_at_a_time"},

    # «نسنجیده» دوباره با «پیکربندی‌نشده» یکی شود — یعنی پنل دربارهٔ سرویسی که
    # پیکربندی **شده** دروغ بگوید.
    {"name": "pot: an unprobed provider is reported as unconfigured again",
     "path": "app/admin_web.py",
     "old": "    return POT_UNKNOWN if last is None else last == \"1\"",
     "new": "    return None if last is None else last == \"1\"",
     "target": _POT,
     "expect": "test_a_configured_but_unprobed_provider_is_not_called_unconfigured"},

    {"name": "pot: cleanup stops cancelling the background refresh",
     "path": "app/admin_web.py",
     "old": "    task = app.get(_POT_TASK)\n    if task is not None and not task.done():\n        task.cancel()",
     "new": "    pass",
     "target": _POT,
     "expect": "test_the_cleanup_hook_cancels_a_running_refresh"},

    # ⚠️ **موردِ «هر دو لایه با هم» این‌جا ثبت نشد، و دلیلش محدودیتِ ابزار است.**
    # هر مورد یک وصلهٔ **پیوسته** می‌خورد (`_run_case` یک `sabotage()` می‌سازد)، و
    # دو موردِ دولایهٔ موجود (castbox و ig) هر دو یک بلوکِ پیوسته را بازنویسی
    # می‌کنند. این‌جا دو لایه در **دو تابعِ متفاوت** نشسته‌اند
    # (`auth_request` و `auth_verify`)، پس با این ابزار یک‌جا برداشته نمی‌شوند.
    # نتیجه: ادعای انتها‌به‌انتها (`test_exhausting_…`) کنترل است نه ادعای
    # سابوتاژشده — همان‌طور که داکس‌استرینگش می‌گوید. پشتیبانی از وصلهٔ چندنقطه‌ای
    # کارِ خودش را می‌خواهد (به‌علاوهٔ یک سلف‌تست در `test_sabotage_helper`) و
    # عمداً سوارِ این تغییر نشد.

    {"name": "login: verify stops checking the id against admin_id_set",
     "path": "app/admin_web.py",
     "old": '    if not _is_admin_id(admin_id):\n        return _login_page(error="نامعتبر.")',
     "new": '    if not admin_id.isdigit():\n        return _login_page(error="نامعتبر.")',
     "target": _LRL,
     "expect": "test_verify_rejects_an_id_that_is_not_an_admin"},

    {"name": "login: the per-IP ceiling on verify disappears",
     "path": "app/admin_web.py",
     "old": ('    if not await _rate_limit(r, f"panelip:ver:{_client_ip(request)}",\n'
             "                             _RL_VERIFY_PER_IP, _RL_WINDOW):"),
     "new": "    if False:",
     "target": _LRL,
     "expect": "test_the_per_ip_verify_ceiling_fires"},

    # کنترلِ معکوس: همان سابوتاژ روی سقفِ **درخواست** نباید ادعای verify را
    # بیندازد — اثباتِ اینکه آن تست دربارهٔ لایهٔ خودش حرف می‌زند، نه همسایه‌اش.
    {"name": "login: the per-IP ceiling on the code request disappears",
     "path": "app/admin_web.py",
     "old": ('    if not await _rate_limit(r, f"panelip:req:{_client_ip(request)}",\n'
             "                             _RL_REQ_PER_IP, _RL_WINDOW):"),
     "new": "    if False:",
     "target": _LRL,
     "expect": "test_the_per_ip_request_ceiling_fires"},
    {"name": "login: dropping the request ceiling must NOT fail the verify claim",
     "path": "app/admin_web.py",
     "old": ('    if not await _rate_limit(r, f"panelip:req:{_client_ip(request)}",\n'
             "                             _RL_REQ_PER_IP, _RL_WINDOW):"),
     "new": "    if False:",
     "target": _LRL + "::test_the_per_ip_verify_ceiling_fires",
     "expect": None},

    {"name": "login: the limiter stops repairing a counter that lost its TTL",
     "path": "app/admin_web.py",
     "old": "    if n == 1 or await r.ttl(key) < 0:",
     "new": "    if n == 1:",
     "target": _LRL,
     "expect": "test_the_limiter_repairs_a_counter_that_lost_its_ttl"},

    # مقایسه روی رشته به‌جای بایت: `compare_digest` روی strِ غیرASCII
    # `TypeError` می‌دهد، پس کدِ با رقمِ فارسی ۵۰۰ می‌شود نه «کد نادرست».
    {"name": "login: the code comparison goes back to comparing str",
     "path": "app/admin_web.py",
     "old": "    ok = bool(real) and secrets.compare_digest(code.encode(), real.encode())",
     "new": "    ok = bool(real) and secrets.compare_digest(code, real)",
     "target": _LRL,
     "expect": "test_a_persian_digit_code_is_wrong_not_a_crash"},

    {"name": "login: the admin-id length guard disappears",
     "path": "app/admin_web.py",
     "old": "    return (admin_id.isdigit() and len(admin_id) <= _ADMIN_ID_MAXLEN\n",
     "new": "    return (admin_id.isdigit()\n",
     "target": _LRL,
     "expect": "test_an_over_long_admin_id_is_rejected_not_a_crash"},

    # کنترلِ منفیِ هارنس: اگر ساعتِ fakeredis وصل نباشد، هر ادعای پنجره‌ای به
    # دلیلِ غلط سبز می‌ماند. این تست همان را می‌گیرد.
    {"name": "login: the modelled clock stops driving fakeredis expiry",
     "path": "tests/panel/conftest.py",
     "old": "    monkeypatch.setattr(bfs, \"time\", c)",
     "new": "    pass",
     "target": _LRL,
     "expect": "test_the_clock_fixture_really_drives_redis_expiry"},

    # ── باگ ۱: بجِ بی‌رنگ در /cookies ──────────────────────────────────────
    # همان خرابکاری، دو هدف: یکی ادعای مشخصِ محصولی («بجِ باطل رنگ دارد») و
    # یکی گاردِ کشف‌محور. هر دو لازم‌اند — گارد کلاسِ مردهٔ **بعدی** را می‌گیرد
    # ولی نمی‌گوید قاعده‌اش واقعاً رنگ می‌دهد یا فقط `display:inline` است.
    {"name": "cookies: the danger badge has no rule again (product claim)",
     "path": "app/admin_web.py",
     "old": ".err{background:#fef2f2;color:#b91c1c}",
     "new": ".ignored-by-nobody{color:red}",
     "target": _CSB,
     "expect": "test_the_invalid_badge_is_actually_painted"},

    {"name": "cookies: the danger badge has no rule again (discovery guard)",
     "path": "app/admin_web.py",
     "old": ".err{background:#fef2f2;color:#b91c1c}",
     "new": ".ignored-by-nobody{color:red}",
     "target": _PCC,
     "expect": "test_every_class_a_page_renders_has_a_rule[/cookies]"},

    # گاردِ خودش یک‌بار کور بود و «نگرفت» گزارش داد در حالی که خرابکاری کاملاً
    # اعمال شده بود: کامنتِ CSS داخلِ `<style>` ارسال می‌شود و چک، نامِ کلاسی
    # را که فقط در **نثرِ** کامنت آمده «تعریف‌شده» می‌خواند. ردهٔ سومِ §۶ —
    # ابزارِ سنجش نتیجهٔ درست را غلط می‌خواند. این مورد رفعِ همان را قفل می‌کند.
    {"name": "cookies: the class checker counts CSS comments as rules again",
     "path": _PCC,
     "old": '    return _CSS_COMMENT.sub(" ", "\\n".join(_STYLE_BLOCK.findall(html)))',
     "new": '    return "\\n".join(_STYLE_BLOCK.findall(html))',
     "target": _PCC,
     "expect": "test_a_class_named_only_inside_a_css_comment_does_not_count"},

    {"name": "cookies: a disabled account goes back to the undefined `mute`",
     "path": "app/admin_web.py",
     "old": "ck_pool.COOLDOWN: \"warn\", ck_pool.DISABLED: \"dim\",",
     "new": "ck_pool.COOLDOWN: \"warn\", ck_pool.DISABLED: \"mute\",",
     "target": _CSB,
     "expect": "test_a_deliberately_disabled_account_is_grey"},

    # «حالتِ ناشناخته بی‌صدا شبیهِ حالتِ عادی دیده می‌شود» — یکی‌کردنِ پیش‌فرض
    # با `dim` کلاسِ تعریف‌شده‌ای می‌دهد (پس گاردِ کشف‌محور ساکت می‌ماند) و
    # فقط این تست تفاوتِ معنا را می‌گیرد.
    {"name": "cookies: an unknown status is painted like a deliberate one",
     "path": "app/admin_web.py",
     "old": '_BADGE_UNKNOWN = "unk"',
     "new": '_BADGE_UNKNOWN = "dim"',
     "target": _CSB,
     "expect": "test_an_unknown_status_does_not_look_like_a_deliberate_one"},

    {"name": "cookies: the unproven dot loses its rule",
     "path": "app/admin_web.py",
     "old": ".s-unproven{background:#f59e0b}",
     "new": ".s-unproven-typo{background:#f59e0b}",
     "target": _CSB,
     "expect": "test_the_unproven_status_dot_is_visible"},

    # ── باگ ۲: کلیدهای غایبِ صفحهٔ تنظیمات ─────────────────────────────────
    # سه مورد با **یک** خرابکاری. دو تای اول باید بیفتند و سومی عمداً نه:
    # با برداشتنِ گروهِ خودکار، شش ردیفِ دست‌نویس هنوز پوشش را کامل نگه
    # می‌دارند، پس «هر کلید ورودی دارد» سبز می‌ماند — و دقیقاً همین نشان
    # می‌دهد که دوام از آن گروه می‌آید نه از فهرست.
    {**_AUTO_GROUP_PATCH,
     "name": "settings: a brand-new runtime key has nowhere to be rendered",
     "target": _SKC,
     "expect": "test_a_brand_new_runtime_key_shows_up_without_touching_the_panel"},

    {**_AUTO_GROUP_PATCH,
     "name": "settings: the auto row stops nagging for a label",
     "target": _SKC,
     "expect": "test_the_auto_row_says_it_needs_a_label"},

    {**_AUTO_GROUP_PATCH,
     "name": "settings: … and today's coverage is unaffected (reverse control)",
     "target": _SKC + "::test_every_runtime_key_has_an_input_on_the_settings_page",
     "expect": None},

    # صفحه از `_setting_groups()` رندر می‌شود ولی `save()` از `GROUPS`ِ خام —
    # ردیفِ خودکار دیده می‌شود و مقدارش بی‌صدا دور ریخته می‌شود، یعنی همان
    # «بنرِ سبز روی کاری که انجام نشد».
    {"name": "settings: save() reads a different list than the page rendered",
     "path": "app/admin_web.py",
     "old": "    rendered = {key for _title, fields in _setting_groups() "
            "for key, _l, _h in fields}",
     "new": "    rendered = {key for _title, fields in GROUPS for key, _l, _h in fields}",
     "target": _SKC,
     "expect": "test_a_value_typed_into_an_auto_rendered_row_actually_saves"},

    # برداشتنِ یکی از شش ردیفِ دست‌نویس: گروهِ خودکار جذبش می‌کند، پس پوشش
    # نمی‌شکند — ولی کنترلِ «امروز همه برچسب دارند» می‌افتد. اثباتِ اینکه آن
    # کنترل زنده است و ردیف‌های دستی واقعاً کار می‌کنند.
    {"name": "settings: proxy_url loses its hand-written row",
     "path": "app/admin_web.py",
     "old": '        ("proxy_url", "خروجیِ شبکه (PROXY_URL)",',
     "new": '        ("dl_direct_enabled", "تکراری — جای proxy_url",',
     "target": _SKC,
     "expect": "test_the_auto_group_is_absent_when_every_key_has_a_label"},

    # ── باگ ۳: برچسبِ دامنه ────────────────────────────────────────────────
    {"name": "stats: the ops KPI goes back to the unqualified label",
     "path": "app/admin_web.py",
     "old": "  <div class=b><em>عملیات روی فایل</em><strong>{{s.ops}}</strong>",
     "new": "  <div class=b><em>عملیات</em><strong>{{s.ops}}</strong>",
     "target": _SCL,
     "expect": "test_the_operations_kpi_states_its_scope"},

    {"name": "stats: the jobs-backed cards lose their tag",
     "path": "app/admin_web.py",
     "old": "<h3>⚙️ پرکاربردترین عملیات <span class=tag>بدونِ دانلود</span></h3>",
     "new": "<h3>⚙️ پرکاربردترین عملیات</h3>",
     "target": _SCL,
     "expect": "test_the_jobs_backed_cards_are_tagged"},

    {"name": "stats: the explainer block disappears",
     "path": "app/admin_web.py",
     "old": "<b>دانلودها در این عددها نیستند</b>",
     "new": "<b>و بس</b>",
     "target": _SCL,
     "expect": "test_the_stats_page_says_which_numbers_exclude_downloads"},

    # کنترلِ معکوس: تستِ برچسب نباید «رشته هرجای صفحه باشد» را بسنجد. اگر یک
    # کارتِ files-محور — که دانلودها را **دارد** — همان برچسب را بگیرد، باید
    # بیفتد؛ وگرنه «همه‌جا برچسب بزن» هم سبز می‌شد.
    {"name": "stats: a files-backed card is wrongly tagged ops-only",
     "path": "app/admin_web.py",
     "old": "<h3>📥 پلتفرمِ دانلود <span class=tag>از این پس ثبت می‌شود</span></h3>",
     "new": "<h3>📥 پلتفرمِ دانلود <span class=tag>بدونِ دانلود</span></h3>",
     "target": _SCL,
     "expect": "test_the_file_side_cards_are_not_tagged_as_ops_only"},

    {"name": "health: the download-rate card drops its timezone",
     "path": "app/admin_web.py",
     "old": "<span class=tag>امروز (UTC)</span>",
     "new": "<span class=tag>امروز</span>",
     "target": _SCL,
     "expect": "test_the_download_rate_card_names_its_timezone"},

    # کنترلِ معکوس برای همان برچسب: برچسب فقط وقتی ارزش دارد که راست بگوید.
    # اگر پنجرهٔ کارت جابه‌جا شود، «امروز (UTC)» خودش یک ادعای نادرستِ تازه
    # می‌شود — و تنها چیزی که این را می‌گیرد تستی است که کلیدِ **دیروز** را
    # می‌کارد و انتظار دارد کارت تکان نخورد.
    {"name": "health: the download-rate window quietly shifts off today",
     "path": "app/admin_web.py",
     "old": '    day = datetime.now(timezone.utc).strftime("%Y%m%d")\n    hosts = []',
     "new": '    day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")'
            '\n    hosts = []',
     "target": _SCL,
     "expect": "test_the_download_rate_card_really_reads_one_utc_day"},

    # ── شمارندهٔ فازِ probe ────────────────────────────────────────
    # ادعای مرکزی: probeِ موفق تا امروز هیچ ردی نمی‌گذاشت.
    {"name": "probe-stats: a successful probe goes uncounted again",
     "path": "app/tasks_download.py",
     "old": "                await PS.mark_menu(redis, ref)\n                return",
     "new": "                return",
     "target": _PST,
     "expect": "test_a_probe_that_shows_a_menu_is_counted"},

    # کنترلِ **اصلی**: probeِ موفقِ بی‌منو نباید در مخرجِ نرخِ رهاشدن بیفتد.
    # اگر `blocked` به `menu` تبدیل شود، هر لینکِ سنی «رهاشده» شمرده می‌شود.
    {"name": "probe-stats: an age-blocked probe is filed as a menu",
     "path": "app/tasks_download.py",
     "old": "                await PS.note(redis, PS.BLOCKED)\n"
            "                await _nsfw_stop(",
     "new": "                await PS.mark_menu(redis, ref)\n"
            "                await _nsfw_stop(",
     "target": _PST,
     "expect": "test_an_age_blocked_probe_is_not_counted_as_a_menu"},

    {"name": "probe-stats: a too-long probe is filed as a menu",
     "path": "app/tasks_download.py",
     "old": "            await PS.note(redis, PS.BLOCKED)      # همان: موفق ولی بی‌منو",
     "new": "            await PS.mark_menu(redis, ref)",
     "target": _PST,
     "expect": "test_a_too_long_probe_is_not_counted_as_a_menu"},

    # واحدِ مصرفِ منبع «تلاش» است نه «جاب» — بیرون‌بردنِ شمارنده از حلقه
    # دقیقاً همان تفکیکی را می‌کشد که سطلِ `attempt` برایش هست.
    {"name": "probe-stats: attempts are counted per job, not per cookie burned",
     "path": "app/tasks_download.py",
     "old": "            await PS.note(redis, PS.ATTEMPT)\n            try:",
     "new": "            try:",
     "target": _PST,
     "expect": "test_a_failed_probe_counts_one_attempt_per_cookie_it_burned"},

    # بدونِ dedupe، یک منو می‌تواند چند pick بدهد و تفاضل منفی می‌شود.
    {"name": "probe-stats: the pick is not deduped against the menu marker",
     "path": "app/probe_stats.py",
     "old": "    await note(redis, PICK if await _claim(redis, ref) else REPICK)",
     "new": "    await note(redis, PICK)",
     "target": _PST,
     "expect": "test_a_pick_is_counted_once_and_the_second_is_a_repick"},

    # ابهامِ cancel: هر دو تولیدکننده همان `Dl(sel="cancel")` را می‌سازند، پس
    # تنها چیزی که لغوِ یک دانلودِ در حالِ اجرا را کنار می‌گذارد نشانگر است.
    {"name": "probe-stats: every cancel is counted, even a running download's",
     "path": "app/probe_stats.py",
     "old": "    if await _claim(redis, ref):\n        await note(redis, MENU_CANCEL)",
     "new": "    await _claim(redis, ref)\n    await note(redis, MENU_CANCEL)",
     "target": _PST,
     "expect": "test_a_cancel_of_a_running_download_is_not_counted"},

    # جای شمارنده در `on_dl_pick` باربر است: پایین‌تر از گاردِ `dlctx`، مسیرِ
    # منقضی/سقف/کش به «رهاشده» نشت می‌کند.
    {"name": "probe-stats: the pick is counted only after the dlctx guard",
     "path": "app/routers/download.py",
     "old": "    await probe_stats.note_pick(arq_pool, ref)\n\n    raw = None",
     "new": "    raw = None",
     "target": _PST,
     "expect": "test_a_pick_is_counted_even_when_the_menu_context_expired"},

    # تلهٔ شمارندهٔ جاودانِ §۷ — `INCR` بدونِ `EXPIRE`.
    {"name": "probe-stats: the buckets lose their TTL and live forever",
     "path": "app/probe_stats.py",
     "old": "        if n == 1:\n            await redis.expire(k, TTL)",
     "new": "        if False:\n            await redis.expire(k, TTL)",
     "target": _PST,
     "expect": "test_the_buckets_carry_the_same_two_day_ttl_as_dlstat"},

    # پرچمِ `sent`: بدونش شاخهٔ عکسیِ موفق به مسیرِ متنی هم می‌افتد و منو دوبار
    # می‌رود — همان چیزی که شمارنده را از داخلِ `try` بیرون برد.
    {"name": "probe-stats: the photo menu falls through to the text menu",
     "path": "app/tasks_download.py",
     "old": "            if sent:",
     "new": "            if False:",
     "target": _PST,
     "expect": "test_a_photo_menu_does_not_also_send_the_text_menu"},

    # کنترلِ تریپ‌وایرِ «فقط اندازه‌گیری»: اگر کسی بعداً یکی از چهار هزینهٔ
    # ثبت‌شدهٔ فازِ probe را بی‌صدا ببندد، باید قرمز شود نه اینکه سوارِ یک
    # PRِ اندازه‌گیری برود.
    {"name": "probe-stats: someone quietly starts charging the hourly bucket",
     "path": "app/tasks_download.py",
     "old": "                info = await D.probe(url, await _opts(redis, platform, workdir, cpath))\n"
            "                await ck.mark_ok(redis, cname)",
     "new": "                info = await D.probe(url, await _opts(redis, platform, workdir, cpath))\n"
            "                await ck.note_spend(redis, cname)\n"
            "                await ck.mark_ok(redis, cname)",
     "target": _PST,
     "expect": "test_the_probe_phase_still_costs_exactly_what_it_did"},

    # کنترلِ معکوس: برداشتنِ شمارندهٔ `menu` نباید ادعاهای سمتِ **روتر** را
    # بیندازد — آن‌ها نشانگر را خودشان می‌کارند. اگر بیفتند یعنی تست‌های pick
    # در واقع دارند مسیرِ ورکر را می‌سنجند، نه چیزی که ادعا می‌کنند.
    {"name": "probe-stats: menu counter removed (reverse control for the pick tests)",
     "path": "app/tasks_download.py",
     "old": "                await PS.mark_menu(redis, ref)\n                return",
     "new": "                return",
     "target": f"{_PST}::test_a_pick_is_counted_once_and_the_second_is_a_repick",
     "expect": None},

    # ── پوششِ قالب‌های پنل: یک واقعیتِ رندرشده را بردار ─────────────────
    # هر مورد یکی از سیزده حذفِ **اندازه‌گیری‌شده‌ای** است که روی `f00d37e`
    # هیچ تستی را نمی‌انداخت. سابوتاژ عمداً **ریزدانه** است نه «بدنه را خالی
    # کن»، و این یک قیدِ روشی است نه سلیقه: خالی‌کردنِ بدنه هم‌زمان کفِ
    # ضدِتوخالیِ گاردِ کلاس (`len(used) >= 15`) را می‌شکند، پس نمی‌شود فهمید
    # کدام لایه گرفته است. اندازه‌گیری نشان داد گاردِ کلاس **هیچ‌کدام** از این
    # سیزده را نمی‌گیرد، پس هر مورد دقیقاً یک لایه را جدا اثبات می‌کند —
    # همان «دفاع در عمق یعنی تست در عمق»ِ §۶.
    {"name": "panel/health: the processing queue depth vanishes",
     "path": "app/admin_web.py",
     "old": "<b>{{health.q_main}}</b>", "new": "<b></b>",
     "target": _HLT, "expect": "test_every_queue_depth_reaches_the_page"},

    {"name": "panel/health: the live-download count vanishes",
     "path": "app/admin_web.py",
     "old": "<b>{{health.dl_active}}</b>", "new": "<b></b>",
     "target": _HLT, "expect": "test_every_queue_depth_reaches_the_page"},

    {"name": "panel/health: the engine versions vanish",
     "path": "app/admin_web.py",
     "old": "gallery-dl {{ e['gallery-dl'] or '—' }}", "new": "",
     "target": _HLT, "expect": "test_the_engine_versions_reach_the_page"},

    {"name": "panel/health: the cookie-pool count vanishes",
     "path": "app/admin_web.py",
     "old": "<bdi>{{p.live}}</bdi> سالم", "new": "",
     "target": _HLT,
     "expect": "test_the_cookie_pool_line_reports_each_platform_and_its_count"},

    {"name": "panel/health: the disk meter vanishes",
     "path": "app/admin_web.py",
     "old": "{{health.disk_used}}/{{health.disk_total}}G", "new": "",
     "target": _HLT, "expect": "test_the_disk_meter_reports_what_it_measured"},

    {"name": "panel/health: the redis service row vanishes",
     "path": "app/admin_web.py",
     "old": "  <div class=svc>⚡ Redis <span class=\"badge {{'ok' if health.redis else 'warn'}}\">"
            "{{'آنلاین' if health.redis else 'خطا'}}</span></div>\n",
     "new": "",
     "target": _HLT, "expect": "test_every_boolean_service_reports_its_state"},

    {"name": "panel/health: the disk meter renders unconditionally (reverse control)",
     "path": "app/admin_web.py",
     "old": "{% if health.disk_total %}<div class=stat><b>دیسکِ ‎/work</b>",
     "new": "{% if True %}<div class=stat><b>دیسکِ ‎/work</b>",
     "target": _HLT, "expect": "test_an_unmeasurable_disk_hides_the_meter"},

    {"name": "panel/users: the telegram id vanishes from the row",
     "path": "app/admin_web.py",
     "old": "{{u.tg}}{% if u.is_admin %}", "new": "{% if u.is_admin %}",
     "target": _URW, "expect": "test_each_row_reports_the_telegram_id_it_is_about"},

    {"name": "panel/users: the pager loses its position",
     "path": "app/admin_web.py",
     "old": "صفحهٔ {{page+1}} از {{pages}}", "new": "",
     "target": _URW, "expect": "test_the_pager_states_where_the_admin_is"},

    # الگو تا فاز B یکتا بود و بعد **پیشوندِ** یک رشتهٔ تازه شد: صفحهٔ `/langs`
    # سربرگِ «{{total}} کلیدِ متن» را آورد، پس `{{total}} کل` دو بار جور می‌شد و
    # مورد با `SabotageError` می‌افتاد — دقیقاً همان چیزی که آن استثنا برایش
    # هست، ولی تا امروز کسی دفترچه را بعد از #۱۲۹ کامل replay نکرده بود.
    # لنگرِ `{%` دوباره یکتایش می‌کند. (نه باگِ محصول است نه ادعای عوض‌شده.)
    {"name": "panel/users: the header stops counting",
     "path": "app/admin_web.py",
     "old": "{{total}} کل{%", "new": "{%",
     "target": _URW, "expect": "test_the_header_counts_total_and_blocked"},

    {"name": "panel/nodes: the node list renders empty",
     "path": "app/admin_web.py",
     "old": "{% for n in nodes %}\n    <div class=nd>",
     "new": "{% for n in [] %}\n    <div class=nd>",
     "target": _NDS,
     "expect": "test_a_registered_node_is_listed_with_its_identifying_facts"},

    {"name": "panel/texts: the whole catalogue renders empty",
     "path": "app/admin_web.py",
     "old": "{% for g in groups %}\n  <details class=tx-cat",
     "new": "{% for g in [] %}\n  <details class=tx-cat",
     "target": _TXT, "expect": "test_every_category_renders_its_title"},

    {"name": "panel/texts: the editor box loses the current value",
     "path": "app/admin_web.py",
     "old": "<textarea name=value rows=2>{{it.current}}</textarea>",
     "new": "<textarea name=value rows=2></textarea>",
     "target": _TXT, "expect": "test_a_key_is_editable_with_its_current_value"},

    {"name": "panel/texts: search stops filtering",
     "path": "app/admin_web.py",
     "old": "        if ql and ql not in key.lower() and ql not in default.lower() "
            "and ql not in current.lower():\n            continue",
     "new": "        if False:\n            continue",
     "target": _TXT,
     "expect": "test_the_search_narrows_the_list_to_what_matches"},

    {"name": "panel/buttons: the op rows render empty",
     "path": "app/admin_web.py",
     "old": "      {% for it in items %}\n        <div class=bt-row data-op=\"{{it.op}}\">",
     "new": "      {% for it in [] %}\n        <div class=bt-row data-op=\"{{it.op}}\">",
     "target": _BTN, "expect": "test_every_op_of_the_kind_renders_a_row[video]"},

    {"name": "panel/buttons: the kind tabs vanish",
     "path": "app/admin_web.py",
     "old": "{% for k, label in kinds %}", "new": "{% for k, label in [] %}",
     "target": _BTN, "expect": "test_every_kind_gets_a_tab"},

    # متنِ دکمه **دو بار** رندر می‌شود (جعبهٔ ویرایش + پیش‌نمایشِ زنده). یک
    # ادعای انتها‌به‌انتها هیچ‌کدام را اثبات نمی‌کند، چون لایهٔ دیگر برآورده‌اش
    # می‌کند و «نگرفت» شبیهِ تستِ ضعیف به‌نظر می‌رسد. اندازه‌گیری‌شده: نسخهٔ اول
    # دقیقاً همین‌طور رد شد. پس دو مورد، هرکدام برای یک لایه.
    {"name": "panel/buttons: the editor box loses the button's current label",
     "path": "app/admin_web.py",
     "old": 'name="text_{{it.op}}" value="{{it.text}}"',
     "new": 'name="text_{{it.op}}" value=""',
     "target": _BTN, "expect": "test_the_editor_box_carries_the_current_label"},

    {"name": "panel/buttons: the live preview stops showing the label",
     "path": "app/admin_web.py",
     "old": '<span class="tgb {{b.cls}}" {% if b.color %}style="background:{{b.color}};'
            'color:#fff"{% endif %}>{{b.text}}</span>',
     "new": '<span class="tgb {{b.cls}}" {% if b.color %}style="background:{{b.color}};'
            'color:#fff"{% endif %}></span>',
     "target": _BTN, "expect": "test_the_live_preview_shows_the_current_label"},

    {"name": "panel/stats: the errors card renders empty",
     "path": "app/admin_web.py",
     "old": "{% for e in s.errors %}", "new": "{% for e in [] %}",
     "target": _STC, "expect": "test_the_recorded_error_reaches_the_errors_card"},

    # همان دو-لایگی، با یک پیچِ اضافه: برچسب‌های فارسیِ op در **سه** جا
    # می‌آیند — کارتِ `by_op`، جدولِ `op_perf` (که `op`ش از قبل فارسی است،
    # `admin_web.py:1694`)، و متنِ توضیحیِ خودِ صفحه که همان‌ها را به‌عنوان
    # مثال می‌نویسد. پس هر ادعا باید به **کارتِ** خودش محدود شود.
    {"name": "panel/stats: the per-op card renders empty",
     "path": "app/admin_web.py",
     "old": "{% if s.by_op %}{% for r in s.by_op %}", "new": "{% if s.by_op %}{% for r in [] %}",
     "target": _STC, "expect": "test_the_per_op_rows_name_their_operations"},

    {"name": "panel/stats: the op-performance table renders empty",
     "path": "app/admin_web.py",
     "old": "{% for r in s.op_perf %}", "new": "{% for r in [] %}",
     "target": _STC, "expect": "test_the_op_performance_table_names_its_operations"},

    # §۴٫۵ سند، موردهای ۱ و ۵. فرگمنتِ مشترک با الحاقِ **رشته‌ایِ پایتون** در دو
    # جا نشانده می‌شود، پس شکستنِ یک‌طرفه‌اش کاملاً ممکن است — و تا امروز هیچ
    # تستی نیمهٔ داشبورد را نمی‌زد.
    {"name": "panel/contract: the shared health partial drops off the dashboard",
     "path": "app/admin_web.py",
     "old": '<div class=col>""" + _HEALTH_CARDS + """</div>\n</div>{% endblock %}"""\n\n_COOKIES',
     "new": '<div class=col></div>\n</div>{% endblock %}"""\n\n_COOKIES',
     "target": _PCT,
     "expect": "test_the_shared_health_partial_renders_on_both_pages[/]"},

    # شکلِ واقع‌بینانه: درصدی که روی مخرجِ صفر حساب شود. `pool[0]` عمداً استفاده
    # **نشد** — جینجا اندیسِ خارج از بازه را `Undefined` می‌دهد و بی‌صدا تهی
    # رندر می‌کند، پس اصلاً ۵۰۰ نمی‌شود و سابوتاژ چیزی ثابت نمی‌کرد.
    {"name": "panel/contract: a page 500s on an empty deployment",
     "path": "app/admin_web.py",
     "old": "    {% if pool %}{% for p in pool %}",
     "new": "    {{ 100 // (pool|length) }}{% if pool %}{% for p in pool %}",
     "target": _PCT,
     "expect": "test_every_page_answers_on_an_empty_deployment[/health]"},

    {"name": "panel/cookies: a status dot is defined but never rendered",
     "path": "app/admin_web.py",
     "old": '      <span class="sdot s-{{c.status}}"></span>\n', "new": "", "count": 2,
     "target": _CSB,
     "expect": "test_every_seeded_status_paints_a_dot_on_a_real_row"},

    # ── هلپرِ `pagefacts`: خودارجاعی، نه صرفاً «چک می‌تواند بیفتد» ─────────
    # کامنتِ CSS داخلِ `<style>` **ارسال می‌شود** و یک‌بار گاردِ کلاس را کور
    # کرد. اگر `page_text` استایل را دور نریزد، هر ادعایی می‌تواند از داخلِ
    # نثرِ توضیحیِ خودمان برآورده شود.
    {"name": "pagefacts: stylesheets and comments are scanned as visible text",
     "path": "tests/panel/pagefacts.py",
     "old": '_DROP = re.compile(r"<!--.*?-->|<style[^>]*>.*?</style>|'
            '<script[^>]*>.*?</script>", re.S | re.I)',
     "new": '_DROP = re.compile(r"(?!x)x")',
     "target": _PGF,
     "expect": "test_a_fact_named_only_inside_a_css_comment_is_reported_missing"},

    {"name": "pagefacts: tags are dropped without a separator",
     "path": "tests/panel/pagefacts.py",
     "old": "    without_tags = _TAG.sub(\" \", without_noise)",
     "new": "    without_tags = _TAG.sub(\"\", without_noise)",
     "target": _PGF, "expect": "test_two_numbers_in_adjacent_tags_do_not_fuse"},

    {"name": "pagefacts: entities are expanded before tags are stripped",
     "path": "tests/panel/pagefacts.py",
     "old": "    without_noise = _DROP.sub(\" \", html)",
     "new": "    without_noise = _DROP.sub(\" \", _html.unescape(html))",
     "target": _PGF,
     "expect": "test_escaped_markup_the_page_shows_literally_survives"},

    # ── فاز B: چندزبانه‌سازی از راهِ export/import ──────────────────
    # یکی به‌ازای هر قاعده‌ای که اگر بی‌صدا برگردد، خرابی‌اش **دیدنی نیست**.
    {"name": "i18n: an untranslated key falls back to Persian again",
     "path": "app/i18n.py",
     "old": "        CATALOG.get(lang or DEFAULT, {}).get(key)\n"
            "        or CATALOG[FALLBACK].get(key)",
     "new": "        CATALOG.get(lang or DEFAULT, CATALOG[DEFAULT]).get(key)",
     "target": _I18,
     "expect": "test_an_untranslated_key_falls_back_to_english_not_persian"},

    # کنترلِ معکوسِ **دامنه**: برگرداندنِ سقوط به فارسی باید ادعاهای خودِ
    # fallback را بیندازد (موردِ بالا) و مسیرِ export/import را **نیندازد** —
    # چون آن مسیر مبدأش `fa` است و `fa` کاتالوگ دارد، پس هر دو زنجیره یک جواب
    # می‌دهند. هدفش عمداً فایلِ **دیگری** است: `expect: None` یعنی «هیچ تستی در
    # فایلِ هدف نیفتد»، پس اگر هدف را همان `_I18` بگذاری، سه تستی که دقیقاً
    # دربارهٔ همین سقوط‌اند می‌افتند و کنترل به دلیلِ غلط «نگرفت» می‌دهد.
    # (این اشتباه یک‌بار ثبت شد و همین‌جا تصحیح شد.)
    {"name": "i18n: the fallback change does not disturb the fa-sourced pack (reverse control)",
     "path": "app/i18n.py",
     "old": "        CATALOG.get(lang or DEFAULT, {}).get(key)\n"
            "        or CATALOG[FALLBACK].get(key)",
     "new": "        CATALOG.get(lang or DEFAULT, CATALOG[DEFAULT]).get(key)",
     "target": _LPK,
     "expect": None},

    {"name": "i18n: the panel writes its own copy of the fallback chain",
     "path": "app/admin_web.py",
     "old": "    return default_text(lang, key)",
     "new": '    return CATALOG.get(lang, {}).get(key) or CATALOG["fa"].get(key) or key',
     "target": _I18,
     "expect": "test_the_panel_and_the_bot_share_one_fallback_chain"},

    {"name": "langpack: the language code is length-gated instead of format-gated",
     "path": "app/langpack.py",
     "old": r'_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")',
     "new": r'_TAG_RE = re.compile(r"^[A-Za-z]{2}$")',
     "target": _LPK,
     "expect": "test_a_real_language_tag_is_accepted_and_canonicalised[pt-br]"},

    {"name": "langpack: the code is stored as typed, so pt-BR and pt-br split",
     "path": "app/langpack.py",
     "old": '    parts = code.split("-")\n    out = [parts[0].lower()]',
     "new": '    parts = [code]\n    out = [parts[0]]',
     "target": _LPK,
     "expect": "test_case_only_variants_collapse_to_one_language"},

    {"name": "langpack: the column bound is dropped as dead code",
     "path": "app/langpack.py",
     "old": "    if len(code) > MAX_CODE_LEN:",
     "new": "    if False:",
     "target": _LPK,
     "expect": "test_a_tag_longer_than_the_column_is_refused"},

    {"name": "langpack: a code-fenced reply is no longer unwrapped",
     "path": "app/langpack.py",
     "old": "    m = _FENCE_RE.match(text)",
     "new": "    m = None",
     "target": _LPK,
     "expect": "test_parsing_survives_what_a_chat_reply_does_to_text[json-fence]"},

    {"name": "langpack: a dropped placeholder is accepted again",
     "path": "app/langpack.py",
     "old": "        err = textstore.validate(src, value, require_all_placeholders=True)",
     "new": "        err = textstore.validate(src, value)",
     "target": _LPK,
     "expect": "test_a_dropped_placeholder_is_refused_even_though_the_editor_allows_it"},

    {"name": "textstore: the missing-placeholder branch never fires",
     "path": "app/textstore.py",
     "old": "    if require_all_placeholders:\n        gone = dfields - vfields",
     "new": "    if False:\n        gone = dfields - vfields",
     "target": _LPK,
     "expect": "test_a_dropped_placeholder_is_refused_even_though_the_editor_allows_it"},

    {"name": "textstore: the plain editor rule silently got stricter (reverse control)",
     "path": "app/textstore.py",
     "old": "def validate(default_text: str, value: str, *, require_all_placeholders: bool = False)",
     "new": "def validate(default_text: str, value: str, *, require_all_placeholders: bool = True)",
     "target": "tests/test_phase2a.py",
     "expect": None},   # قاعدهٔ پایه نباید از این تغییر خبردار شود…

    {"name": "textstore: …but the import rule must notice it",
     "path": "app/textstore.py",
     "old": "def validate(default_text: str, value: str, *, require_all_placeholders: bool = False)",
     "new": "def validate(default_text: str, value: str, *, require_all_placeholders: bool = True)",
     "target": _LPK,
     "expect": "test_a_dropped_placeholder_is_refused_even_though_the_editor_allows_it"},

    {"name": "langpack: the placeholder contract comes from the catalog, not the source",
     "path": "app/langpack.py",
     "old": "        src = source_texts.get(key, default_text(rv.source, key))",
     "new": "        src = default_text(rv.source, key)",
     "target": _LPK,
     "expect": "test_the_placeholder_contract_comes_from_the_source_text_not_the_catalog"},

    {"name": "langpack: an unknown key is skipped instead of blocking the pack",
     "path": "app/langpack.py",
     "old": '            rv.errors.append((key, "کلیدِ ناشناخته — در کاتالوگِ ربات نیست."))',
     "new": "            pass",
     "target": _LPK,
     "expect": "test_an_unknown_key_is_named_and_blocks_the_whole_pack"},

    {"name": "panel: import writes what it validated even when something failed",
     "path": "app/admin_web.py",
     "old": "    if not rv.ok:\n        return await _langs_render(request, review=rv, raw=raw, replace=replace)",
     "new": "    if False:\n        return await _langs_render(request, review=rv, raw=raw, replace=replace)",
     "target": _LNG,
     "expect": "test_a_rejected_pack_writes_nothing_at_all"},

    {"name": "panel: the default language is overwritten without asking",
     "path": "app/admin_web.py",
     "old": '    if code == i18n_DEFAULT and form.get("confirm") != "yes":',
     "new": "    if False:",
     "target": _LNG,
     "expect": "test_importing_over_the_default_language_asks_first"},

    {"name": "panel: every language needs confirmation, not just the default (reverse control)",
     "path": "app/admin_web.py",
     "old": '    if code == i18n_DEFAULT and form.get("confirm") != "yes":',
     "new": '    if form.get("confirm") != "yes":',
     "target": _LNG,
     "expect": "test_a_non_default_language_needs_no_confirmation"},

    {"name": "panel: merge silently becomes replace",
     "path": "app/admin_web.py",
     "old": "    await textstore.set_texts(code, rv.entries, replace=replace)",
     "new": "    await textstore.set_texts(code, rv.entries, replace=True)",
     "target": _LNG,
     "expect": "test_merge_leaves_the_keys_the_pack_does_not_mention"},

    {"name": "panel: replace silently becomes merge",
     "path": "app/admin_web.py",
     "old": "    await textstore.set_texts(code, rv.entries, replace=replace)",
     "new": "    await textstore.set_texts(code, rv.entries, replace=False)",
     "target": _LNG,
     "expect": "test_replace_drops_the_keys_the_pack_does_not_mention"},

    {"name": "panel: a pack retargeted by the model is trusted",
     "path": "app/admin_web.py",
     "old": "        if in_file and langpack.normalize_code(in_file) != code:",
     "new": "        if False:",
     "target": _LNG,
     "expect": "test_a_pack_retargeted_by_the_model_is_caught"},

    {"name": "panel: export ships the code default instead of the admin's own text",
     "path": "app/admin_web.py",
     "old": "        texts=langpack.effective_texts(source, textstore.lang_texts(source)))",
     "new": "        texts=langpack.effective_texts(source, {}))",
     "target": _LNG,
     "expect": "test_the_export_carries_the_admins_own_edits_not_the_code_default"},

    {"name": "panel: re-export restarts from the default language instead of continuing",
     "path": "app/admin_web.py",
     "old": '<a class=btn-sm href="/langs/export?lang={{r.code}}&source={{r.code}}">',
     "new": '<a class=btn-sm href="/langs/export?lang={{r.code}}&source={{default_lang}}">',
     "target": _LNG,
     "expect": "test_re_exporting_a_half_translated_language_carries_what_is_done"},

    {"name": "panel: deleting a language leaves its texts behind",
     "path": "app/textstore.py",
     "old": "        await s.execute(sa_delete(TextOverride).where(TextOverride.lang == code))\n"
            "        await s.execute(sa_delete(Language).where(Language.code == code))",
     "new": "        await s.execute(sa_delete(Language).where(Language.code == code))",
     "target": _LNG,
     "expect": "test_deleting_a_language_takes_its_texts_with_it"},

    # فاز C سازندهٔ فهرست را از `admin_web._languages` به
    # `i18n.available_languages` برد (ربات نمی‌تواند `admin_web` را import کند)،
    # پس این مورد هم به همان‌جا منتقل شد. ادعا عوض نشده: زبانِ import‌شده باید
    # روی صفحه‌های دیگرِ پنل انتخاب‌شدنی باشد.
    {"name": "panel: the language list goes back to a hardcoded pair",
     "path": "app/i18n.py",
     "old": "    langs = dict(BUILTIN_NAMES)\n    langs.update(await textstore.languages())",
     "new": "    langs = dict(BUILTIN_NAMES)",
     "target": _LNG,
     "expect": "test_the_imported_language_becomes_selectable_on_the_other_pages"},

    {"name": "panel: coverage is a fixed label instead of a computed number",
     "path": "app/admin_web.py",
     "old": "        done = total if builtin else len(textstore.lang_texts(code))",
     "new": "        done = total",
     "target": _LNG,
     "expect": "test_the_page_states_how_many_keys_a_language_still_lacks"},

    # ── فاز C: انتخابِ زبان و منوهای کاربر، سمتِ ربات ──
    {"name": "phase-c: /start goes back to the hardcoded fa/en menu",
     "path": "app/routers/start.py",
     "old": "    langs = await available_languages()\n    return t(lang, \"choose_language\")",
     "new": "    langs = {\"fa\": \"فارسی\", \"en\": \"English\"}\n    return t(lang, \"choose_language\")",
     "target": _STF,
     "expect": "test_a_language_added_from_the_panel_shows_up_in_the_start_menu"},

    {"name": "phase-c: the keyboard ignores the list it was handed",
     "path": "app/keyboards.py",
     "old": "    for code, name in langs.items():\n        mark = \"✅ \" if code == current else \"\"",
     "new": "    for code, name in {\"fa\": \"فارسی\", \"en\": \"English\"}.items():\n"
            "        mark = \"✅ \" if code == current else \"\"",
     "target": _STF,
     "expect": "test_a_language_added_from_the_panel_shows_up_in_the_start_menu"},

    {"name": "phase-c: an added language code is coerced back to the default",
     "path": "app/routers/start.py",
     "old": "    code = callback_data.code if callback_data.code in langs else DEFAULT",
     "new": "    code = callback_data.code if callback_data.code in (\"fa\", \"en\") else DEFAULT",
     "target": _STF,
     "expect": "test_picking_an_added_language_is_stored_and_not_coerced_to_fa"},

    {"name": "phase-c: the panel rebuilds the list instead of delegating",
     "path": "app/admin_web.py",
     "old": "    return await i18n_available_languages()",
     "new": "    langs = dict(BUILTIN_NAMES)\n    langs.update(await textstore.languages())\n    return langs",
     "target": _STF,
     "expect": "test_the_language_list_is_built_in_exactly_one_place"},

    {"name": "phase-c: the language list loses its ORDER BY",
     "path": "app/textstore.py",
     "old": "            select(Language).order_by(Language.name, Language.code)",
     "new": "            select(Language)",
     "target": _STF,
     "expect": "test_the_added_languages_come_back_in_a_stable_order"},

    {"name": "phase-c: an existing user is asked for their language again",
     "path": "app/routers/start.py",
     "old": "    if user is None or not user.lang:",
     "new": "    if True:",
     "target": _STF,
     "expect": "test_a_user_who_already_chose_is_never_asked_again"},

    {"name": "phase-c: a settings-initiated change lands on welcome, not settings",
     "path": "app/routers/start.py",
     "old": "    from_settings = bool(user is not None and user.lang)",
     "new": "    from_settings = False",
     "target": _STF,
     "expect": "test_changing_the_language_from_settings_returns_to_settings"},

    {"name": "phase-c: the lying language_set toast comes back",
     "path": "app/routers/start.py",
     "old": "    await cq.answer()\n\n\n@router.callback_query(Nav.filter())",
     "new": "    await cq.answer(t(code, \"language_set\"))\n\n\n@router.callback_query(Nav.filter())",
     "target": _STF,
     "expect": "test_no_language_set_toast_is_sent_any_more"},

    # این مورد یک ضعفِ واقعی در تستِ خودم پیدا کرد و بعد اصلاح شد: ادعای
    # `…come_from_the_declarative_list` انتظارش را از همان `HOME_ITEMS` می‌سازد
    # که این سابوتاژ ویرایشش می‌کند، پس هر دو طرف با هم کوچک می‌شدند و سبز
    # می‌ماند. حالا یک ادعای **لفظیِ** جدا هست و `expect` به آن اشاره می‌کند.
    {"name": "phase-c: a welcome key is dropped from the declarative list",
     "path": "app/keyboards.py",
     "old": "    (\"settings\", \"btn_settings\"),\n    (\"help\", \"btn_help\"),",
     "new": "    (\"help\", \"btn_help\"),",
     "target": _STF,
     "expect": "test_the_welcome_screen_offers_settings_and_help"},

    {"name": "phase-c: the settings menu loses its only item",
     "path": "app/keyboards.py",
     "old": "SETTINGS_ITEMS: tuple[tuple[str, str], ...] = (\n    (\"lang\", \"btn_change_language\"),\n)",
     "new": "SETTINGS_ITEMS: tuple[tuple[str, str], ...] = ()",
     "target": _STF,
     "expect": "test_settings_opens_with_the_language_item_and_a_back_key"},

    # ── فاز C: گاردِ پاریتیِ کاتالوگ (باگِ زندهٔ فاز B) ──
    {"name": "parity: a key exists in fa but not in en",
     "path": "app/locales/en.py",
     "old": '    "btn_help": "📘 How to use",\n',
     "new": "",
     "target": _PAR,
     "expect": "test_the_two_catalogs_hold_exactly_the_same_keys"},

    {"name": "parity: a placeholder is dropped on one side only",
     "path": "app/locales/en.py",
     "old": '"detected_image": "🖼 <b>Image</b> detected\\n{name} · {size}',
     "new": '"detected_image": "🖼 <b>Image</b> detected\\n{name}',
     "target": _PAR,
     "expect": "test_every_key_carries_the_same_placeholders_in_both_languages"},

    {"name": "parity: an HTML tag is dropped on one side only",
     "path": "app/locales/en.py",
     "old": '"settings_title": "⚙️ <b>Settings</b>',
     "new": '"settings_title": "⚙️ Settings',
     "target": _PAR,
     "expect": "test_every_key_carries_the_same_html_tags_in_both_languages"},

    {"name": "parity: a new bot string never reaches the translation pack",
     "path": "app/langpack.py",
     "old": 'TEXT_KEYS: tuple[str, ...] = tuple(sorted(set(CATALOG["fa"]) | set(CATALOG["en"])))',
     "new": 'TEXT_KEYS: tuple[str, ...] = tuple(\n'
            '    k for k in sorted(set(CATALOG["fa"]) | set(CATALOG["en"]))\n'
            '    if k != "help_text")',
     "target": _PAR,
     "expect": "test_the_new_phase_c_strings_reach_the_translation_pack"},

    # کنترلِ معکوسِ ۱ — گاردِ پاریتی دربارهٔ **کاتالوگ** است نه دربارهٔ جریان.
    # برداشتنِ منوی زبان از `/start` نباید هیچ ادعای پاریتی‌ای را بیندازد؛
    # اگر بیندازد یعنی آن تست‌ها دارند چیزِ دیگری می‌سنجند.
    {"name": "parity control: gutting the /start menu leaves the catalog guard green",
     "path": "app/routers/start.py",
     "old": "        text, kb = await _lang_menu(lang, current=None, back_to=None)\n"
            "        await message.answer(text, reply_markup=kb)",
     "new": "        await message.answer(t(lang, \"choose_language\"))",
     "target": _PAR,
     "expect": None},

    # کنترلِ معکوسِ ۲ — تست‌ها روی **ساختار** assert می‌کنند نه روی copy.
    # بازنویسیِ واژه‌های یک رشتهٔ فارسی نباید هیچ‌چیز را بیندازد، وگرنه هر
    # ویرایشِ متنِ ادمین به یک تستِ قرمز تبدیل می‌شود و کسی تست را حذف می‌کند.
    {"name": "phase-c control: rewording a Persian string breaks nothing",
     "path": "app/locales/fa.py",
     "old": '    "btn_settings": "⚙️ تنظیمات",',
     "new": '    "btn_settings": "⚙️ پیکربندی و تنظیمات",',
     "target": _STF,
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
    lines = r.stdout.splitlines()
    # فقط **بخشِ خلاصهٔ خودِ pytest** خوانده می‌شود، نه هر جای stdout. این قید
    # با اجرا آمد نه با احتیاط: خطِ لاگِ یک تست هم می‌تواند با `ERROR` شروع شود
    # (`ERROR    telabzar.dl:tasks_download.py:201 cookieless attempt on …`)،
    # پس تطبیقِ ابتدای خط سه اجرای کاملاً **سالم** را «هدف اجرا نشد» خواند.
    # قاعدهٔ عام: هارنسی که خروجیِ یک رانرِ دیگر را طبقه‌بندی می‌کند باید به
    # **گرامرِ خلاصهٔ همان رانر** گره بخورد، نه به متنی که می‌تواند از payload
    # آمده باشد. خلاصه با `short test summary info` شروع می‌شود و اگر اصلاً
    # چاپ نشده باشد یعنی نه شکستی بوده نه خطایی.
    head = next((i for i, ln in enumerate(lines) if "short test summary info" in ln), None)
    summary = lines[head + 1:] if head is not None else []

    # **اجرا نشدن با نگرفتن یکی نیست، و از بیرون یکی به‌نظر می‌رسند.** فقط
    # خطوطِ `FAILED` خوانده می‌شدند، پس هدفی که سرِ collect می‌ترکید (وابستگیِ
    # غایب — مثلاً موردی که به `tests/panel/` اشاره می‌کند و از venvی بدونِ
    # jinja2/cryptography اجرا شود) صفر `FAILED` می‌داد و «نگرفت» گزارش
    # می‌شد. یعنی دقیقاً همان برداشتی که §۷ می‌گوید باعث می‌شود کسی یک تستِ
    # سالم را ضعیف بخواند و پاکش کند. حالا این حالت **سومی** است، نه «نگرفت».
    errored = [ln for ln in summary if ln.startswith("ERROR")]
    if errored:
        return False, (
            f"هدف اجرا نشد: {len(errored)} خطای collect. نتیجه **بی‌اعتبار** است، "
            f"نه «نگرفت». اولی: {errored[0][:120]}\n"
            f"      (موردهای `tests/panel/` را با venvی اجرا کن که "
            f"requirements-admin.txt هم نصب دارد.)")
    # همین‌طور «هیچ تستی اجرا نشد»: نسخهٔ اولش زیررشته‌ای بود و با متنِ خودِ
    # تست‌ها برخورد می‌کرد — تستی که این عبارت را **ورودی** می‌دهد، در
    # تریس‌بکِ pytest چاپش می‌کند. خطِ خلاصهٔ واقعی همیشه ابتدای خط است.
    if any(ln.startswith("no tests ran") for ln in lines):
        return False, "هیچ تستی اجرا نشد — هدف یا الگو عوض شده؛ نتیجه بی‌اعتبار است."

    failed = {ln.split("::")[-1].split(" ")[0]
              for ln in summary if ln.startswith("FAILED")}
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
