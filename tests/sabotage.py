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
_DFN = "tests/test_direct_filename.py"
_DLC = "tests/test_cache_poison.py"
_GWI = "tests/test_gateway_inline.py"
_WGK = "tests/test_wg_pubkey.py"
_ARB = "tests/test_archive_bomb.py"
_SIC = "tests/test_safety_image_cap.py"
_ORT = "tests/test_ops_rate_ttl.py"
_DTO = "tests/test_dl_ticker_orphan.py"
_EPM = "tests/test_exit_pin_master.py"
_NUR = "tests/test_new_user_race.py"
_EBC = "tests/test_exit_blame_content.py"
_DLF = "tests/test_delivery_failures.py"
_DDF = "tests/test_dl_delivery_failures.py"
_DQB = "tests/test_dl_quota_burst.py"
_CSG = "tests/panel/test_csrf_guard.py"
# فاز ۳ِ ممیزی — رسانه/پردازش
_PXF = "tests/test_delivery_pix_fmt.py"
_ORI = "tests/test_image_orientation.py"
_TRR = "tests/test_trim_range.py"
_AMC = "tests/test_audio_meta_container.py"
_RAR = "tests/test_rar_extract.py"
_WDJ = "tests/test_dl_workdir_per_job.py"
_HTC = "tests/test_heavy_thread_cancel.py"
_PLC = "tests/test_playlist_cap.py"
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
_TXI = "tests/panel/test_texts_inplace.py"
_TVL = "tests/test_text_validate_lang.py"
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
_TPF = "tests/panel/test_template_files.py"
_YEK = "tests/test_youtube_error_kinds.py"
_PIN = "tests/test_ytdlp_pins.py"
_YCM = "tests/test_yt_client_matrix.py"
# فاز ۴ِ ممیزی — پیام/اعتبارسنجی/امنیتیِ پایین‌تر
_MIM = "tests/test_mime_refresh.py"
_LPD = "tests/test_langpack_defaults.py"
_LPP = "tests/panel/test_langs_defaults.py"
_SCR = "tests/test_settings_cache_race.py"
_GNP = "tests/test_gateway_node_pool.py"
_SKW = "tests/test_safety_keywords.py"
_CLV = "tests/test_clamav_errors.py"
_PRF = "tests/panel/test_prefs_redirect.py"
_MFZ = "tests/test_max_file_zero.py"
_LEX = "tests/test_link_expiry.py"
_TPH = "tests/test_text_placeholders.py"
_CKP = "tests/test_cookie_paste_length.py"
_EXS = "tests/test_exit_stats_content.py"
_IMM = "tests/test_image_modes.py"
_STW = "tests/test_strike_window.py"
_ARE = "tests/test_admin_report_escape.py"
_RMX = "tests/test_remux_orphan.py"
_PAC = "tests/panel/test_panel_actions.py"
_ADL = "tests/panel/test_admin_log.py"
_ICN = "tests/panel/test_panel_icons.py"
_TGD = "tests/panel/test_template_guards.py"
_STU = "tests/panel/test_strict_undefined.py"

# «گروهِ خودکار را بردار» — یک خرابکاری با **سه** ادعای متفاوت، پس یک‌بار
# تعریف می‌شود. دو تا باید بیفتند و یکی عمداً **نباید**، که کلِ نکته است:
# شش ردیفِ دست‌نویس پوشش را نگه می‌دارند، ولی دوام از این گروه می‌آید.
_AUTO_GROUP_PATCH = {
    "path": "app/admin_web.py",
    "old": '    auto = _settings_auto_keys()\n    if auto:',
    "new": '    auto = _settings_auto_keys()\n    if False:',
}

# ── وابستگیِ یوتیوب به کوکی (۲۰۲۶-۰۹) ── سه خرابکاری که هرکدام بیش از یک
# ادعا (یا یک کنترلِ معکوس) دارند، پس یک‌بار تعریف می‌شوند.
_POT_GATE_PATCH = {
    "path": "app/tasks_download.py",
    "old": '                        if opts.get("pot_provider") and D.is_pot_crash(str(ytdlp_exc)):',
    "new": '                        if opts.get("pot_provider"):',
}
_SUMMARY_CR_PATCH = {
    "path": "app/downloader.py",
    "old": '    text = text.replace("\\r", " ")\n',
    "new": "",
}
_MATRIX_NOWARN_PATCH = {
    "path": "tools/yt_client_matrix.py",
    "old": '    cmd = [*base, "-j", "--no-simulate", "--no-progress", "--no-playlist", "--no-part",',
    "new": ('    cmd = [*base, "-j", "--no-simulate", "--no-progress", "--no-warnings", '
            '"--no-playlist", "--no-part",'),
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
     "old": '"-ss", f"{start}", "-to", f"{end}", "-i", inp, "-vf", _DELIVERY_VF,\n        "-c:v"',
     "new": '"-i", inp, "-ss", f"{start}", "-to", f"{end}", "-vf", _DELIVERY_VF,\n        "-c:v"',
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
     # بازلنگر ۲۰۲۶-۰۹-۲۶: چک از داخلِ شاخهٔ کوکی بیرون آمد (یک پله کم‌عمق‌تر)
     # تا شکستِ بی‌کوکی (reload) هم سقف بخورد — الگوی قدیمی ۰ تطبیق داشت.
     "old": "                if max_tries and attempts >= max_tries:\n"
            '                    log.info("probe: stopping after %d attempts '
            '(dl_max_cookie_tries)",',
     "new": "                if False:\n"
            '                    log.info("probe: stopping after %d attempts '
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
     "old": '    except RuntimeError:\n        # رازِ خالی:',
     "new": '    except (ValueError,):\n        # رازِ خالی:',
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
     "old": '    await _stash_join_view(request.app["redis"], admin_id, tok)\n    await _audit(request, "node_add", target=name, role=role)\n    raise web.HTTPFound("/nodes?dlg=nd-made")',
     "new": '    await _audit(request, "node_add", target=name, role=role)\n    raise web.HTTPFound(f"/nodes?dlg=nd-made&tok={tok}")',
     "target": _CHR,
     "expect": "test_the_join_token_never_appears_in_a_url"},

    # ادعای مستقل و مهم‌ترین: لاگ. جدا از تستِ بالا، چون آن یکی دربارهٔ
    # `Location` است و این یکی دربارهٔ چیزی که روی دیسکِ سرور می‌نشیند.
    {"name": "phase2 A-2: the token lands in the access log again",
     "path": "app/admin_web.py",
     "old": '    await _stash_join_view(request.app["redis"], admin_id, tok)\n    await _audit(request, "node_add", target=name, role=role)\n    raise web.HTTPFound("/nodes?dlg=nd-made")',
     "new": '    await _stash_join_view(request.app["redis"], admin_id, tok)\n    await _audit(request, "node_add", target=name, role=role)\n    raise web.HTTPFound(f"/nodes?dlg=nd-made&tok={tok}")',
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
     "old": '    if not node_mod.valid_pubkey(pubkey):\n        return web.json_response({"error": "missing pubkey"}, status=400)\n    payload = await node_mod.consume_join_token(request.app["redis"], token)\n    if payload is None:\n        return web.json_response({"error": "invalid or used token"}, status=403)',
     "new": '    payload = await node_mod.consume_join_token(request.app["redis"], token)\n    if payload is None:\n        return web.json_response({"error": "invalid or used token"}, status=403)\n    if not node_mod.valid_pubkey(pubkey):\n        return web.json_response({"error": "missing pubkey"}, status=400)',
     "target": _CHR,
     "expect": "test_a_malformed_join_does_not_burn_the_token"},

    # نیمهٔ دومِ همان `if`. اگر فقط شاخهٔ «غایب» تست می‌شد، یک نصفه‌رفع بی‌صدا
    # از کنارش رد می‌شد. از فاز ۱ِ ممیزی (۲۰۲۶-۱۰) آن `if` یک چکِ **فرمت**ِ
    # کامل است (`valid_pubkey`)، پس «نیمهٔ طول» حالا یعنی برداشتنِ کلِ چکِ فرمت.
    {"name": "phase2 A-3: drop the length half of the pubkey check",
     "path": "app/admin_web.py",
     "old": "    if not node_mod.valid_pubkey(pubkey):",
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
     "old": '    if _https(request):\n        headers["Strict-Transport-Security"] = _HSTS',
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
    # قالب از `admin_web.py` به `app/templates/base.html` رفت؛ الگوی قبلی از آن
    # روز رُت کرده بود (فاز ۱ِ ممیزی پیدایش کرد، نه ساختش).
    {"name": "phase2 headers: add an external CDN reference",
     "path": "app/templates/base.html",
     "old": '<title>{% block title %}',
     "new": '<script src="https://cdn.example.com/x.js"></script><title>{% block title %}',
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
     "old": 'raise _result("/cookies", ok="ck.del.ok")',
     "new": 'raise web.HTTPFound("/cookies?ok=ck.del.ok")',
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

    # بازنشسته (۲۰۲۶-۱۰): «settings: iterate the form in set order (must break nothing)»
    #   save() walks a fixed field list now, not a set — there is no order to scramble.

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
     "old": '        raise _result("/nodes", err=pt(lang, "nd.bad_role"))',
     "new": '        raise web.HTTPFound("/nodes")',
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
     "old": '    data = await _users_cached(request.app, text, status, ulang, sort, page)',
     "new": '    data = await PD.users_list(text, status, ulang, sort, page)',
     "target": _USR,
     "expect": "test_a_repeat_load_does_not_hit_the_database"},

    # باطل‌سازی برداشته شود: کش صفحه را از «کند» به **غلط** می‌برد.
    {"name": "users: blocking no longer busts the cache",
     "path": "app/admin_web.py",
     "old": '            await _users_cache_bust(request.app.get("redis"))',
     "new": '            pass',
     "target": _USR,
     "expect": "test_blocking_a_user_shows_up_immediately"},

    {"name": "users: the cache key drops the version counter",
     "path": "app/admin_web.py",
     "old": '    key = f"userscache:{await _users_cache_ver(redis)}:{status}:{lang}:{sort}:{page}:{q}"',
     "new": '    key = f"userscache:{status}:{lang}:{sort}:{page}:{q}"',
     "target": _USR,
     "expect": "test_unblocking_is_visible_immediately_too"},

    {"name": "users: every page and query share one cache key",
     "path": "app/admin_web.py",
     "old": '    key = f"userscache:{await _users_cache_ver(redis)}:{status}:{lang}:{sort}:{page}:{q}"',
     "new": '    key = f"userscache:{await _users_cache_ver(redis)}"',
     "target": _USR,
     "expect": "test_different_pages_and_queries_are_cached_separately"},

    {"name": "users: the cached page never expires",
     "path": "app/admin_web.py",
     "old": '    return await _cached(redis, key, _USERS_TTL,',
     "new": '    return await _cached(redis, key, 10 ** 9,',
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
     "old": '    pot = await _pot_health(app)',
     "new": ('    pot = None\n    if settings.pot_provider_url:\n        pot = False\n        try:\n            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:\n                async with s.get(settings.pot_provider_url + "/ping") as resp:\n                    pot = resp.status == 200\n        except Exception:  # noqa: BLE001\n            pot = False'),
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
     # از ۲۰۲۶-۱۰ پاک‌سازی روی هر دو تسکِ پس‌زمینه حلقه می‌زند (pot و گرم‌کردنِ
     # سرتیفیکیت)؛ همان ادعا، بازلنگرشده: pot از حلقه بیرون می‌افتد.
     "old": '    for key in (_POT_TASK, _TLS_WARM_TASK, _SVC_TASK):',
     "new": '    for key in (_TLS_WARM_TASK, _SVC_TASK):',
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
     "old": '    if not _is_admin_id(admin_id):\n        raise web.HTTPFound("/login")',
     "new": '    if not admin_id.isdigit():\n        raise web.HTTPFound("/login")',
     "target": _LRL,
     "expect": "test_verify_rejects_an_id_that_is_not_an_admin"},

    {"name": "login: the per-IP ceiling on verify disappears",
     "path": "app/admin_web.py",
     "old": ('    if not await _rate_limit(r, f"panelip:ver:{_client_ip(request)}", _RL_VERIFY_PER_IP, _RL_WINDOW):'),
     "new": '    if False:',
     "target": _LRL,
     "expect": "test_the_per_ip_verify_ceiling_fires"},

    # کنترلِ معکوس: همان سابوتاژ روی سقفِ **درخواست** نباید ادعای verify را
    # بیندازد — اثباتِ اینکه آن تست دربارهٔ لایهٔ خودش حرف می‌زند، نه همسایه‌اش.
    {"name": "login: the per-IP ceiling on the code request disappears",
     "path": "app/admin_web.py",
     "old": ('    if not await _rate_limit(r, f"panelip:req:{_client_ip(request)}", _RL_REQ_PER_IP, _RL_WINDOW):'),
     "new": '    if False:',
     "target": _LRL,
     "expect": "test_the_per_ip_request_ceiling_fires"},
    {"name": "login: dropping the request ceiling must NOT fail the verify claim",
     "path": "app/admin_web.py",
     "old": ('    if not await _rate_limit(r, f"panelip:req:{_client_ip(request)}", _RL_REQ_PER_IP, _RL_WINDOW):'),
     "new": '    if False:',
     "target": _LRL + "::test_the_per_ip_verify_ceiling_fires",
     "expect": None},

    {"name": "login: the limiter stops repairing a counter that lost its TTL",
     "path": "app/counters.py",
     "old": "    if n == amount or await redis.ttl(key) < 0:",
     "new": "    if n == amount:",
     "target": _LRL,
     "expect": "test_the_limiter_repairs_a_counter_that_lost_its_ttl"},

    # مقایسه روی رشته به‌جای بایت: `compare_digest` روی strِ غیرASCII
    # `TypeError` می‌دهد. از ۲۰۲۶-۱۰ رقمِ فارسی پیش از مقایسه لاتین می‌شود، پس
    # تستِ رقمِ فارسی دیگر به این گارد نمی‌رسد (دو دفاع روی یک مسیر) — هدف
    # تستی است که حرفِ غیرِرقمی می‌فرستد و فقط همین گارد نجاتش می‌دهد.
    {"name": "login: the code comparison goes back to comparing str",
     "path": "app/admin_web.py",
     "old": '    ok = secrets.compare_digest(code.encode(), real.encode())',
     "new": '    ok = secrets.compare_digest(code, real)',
     "target": _LRL,
     "expect": 'test_a_non_ascii_code_is_wrong_not_a_crash'},

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
    # از ۲۰۲۶-۱۰ وضعیت یک «پیل» است (`.pill.<شدت>`) و ادعای محصولی («پیلِ باطل
    # رنگ دارد») تنها هدف است؛ نیمهٔ کشف‌محورش بازنشسته شد — پایین‌تر.
    {"name": "cookies: the danger badge has no rule again (product claim)",
     "path": 'app/static/css/panel.css',
     "old": '.pill.bad{background:var(--bad-soft);color:var(--bad-ink)}',
     "new": '.pill.bad-typo{background:var(--bad-soft);color:var(--bad-ink)}',
     "target": _CSB,
     "expect": 'test_the_invalid_pill_is_actually_painted'},

    # بازنشسته (۲۰۲۶-۱۰): «cookies: the danger badge has no rule again (discovery guard)»
    #   severity tokens (.bad/.warn) are shared by pills, meters and text, so the
    #   per-token guard cannot see a pill-only loss by construction;
    #   test_cookie_status_badges does.

    # گاردِ خودش یک‌بار کور بود و «نگرفت» گزارش داد در حالی که خرابکاری کاملاً
    # اعمال شده بود: کامنتِ CSS داخلِ `<style>` ارسال می‌شود و چک، نامِ کلاسی
    # را که فقط در **نثرِ** کامنت آمده «تعریف‌شده» می‌خواند. ردهٔ سومِ §۶ —
    # ابزارِ سنجش نتیجهٔ درست را غلط می‌خواند. این مورد رفعِ همان را قفل می‌کند.
    {"name": "cookies: the class checker counts CSS comments as rules again",
     "path": _PCC,
     "old": '    return _CSS_COMMENT.sub(" ", "\\n".join(parts))',
     "new": '    return "\\n".join(parts)',
     "target": _PCC,
     "expect": "test_a_class_named_only_inside_a_css_comment_does_not_count"},

    {"name": "cookies: a disabled account goes back to the undefined `mute`",
     "path": "app/admin_web.py",
     "old": '            "disabled": ("neutral", "pause")}',
     "new": '            "disabled": ("mute", "pause")}',
     "target": _CSB,
     "expect": "test_a_deliberately_disabled_account_is_grey"},

    # «حالتِ ناشناخته بی‌صدا شبیهِ حالتِ عادی دیده می‌شود» — یکی‌کردنِ پیش‌فرض
    # با `dim` کلاسِ تعریف‌شده‌ای می‌دهد (پس گاردِ کشف‌محور ساکت می‌ماند) و
    # فقط این تست تفاوتِ معنا را می‌گیرد.
    {"name": "cookies: an unknown status is painted like a deliberate one",
     "path": "app/admin_web.py",
     "old": '        cls, icon = _CK_PILL.get(status, ("info", "circle-help"))',
     "new": '        cls, icon = _CK_PILL.get(status, ("neutral", "circle-help"))',
     "target": _CSB,
     "expect": "test_an_unknown_status_does_not_look_like_a_deliberate_one"},

    {"name": 'cookies: the warning pill (unproven/suspect) loses its rule',
     "path": 'app/static/css/panel.css',
     "old": '.pill.warn{background:var(--warn-soft);color:var(--warn-ink)}',
     "new": '.pill.warn-typo{background:var(--warn-soft);color:var(--warn-ink)}',
     "target": _CSB,
     "expect": 'test_every_seeded_status_paints_a_pill_on_a_real_row'},

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

    # صفحه از `_settings_sections()` رندر می‌شود ولی `save()` از `PS.fields()`ِ خام
    # (فقط ردیف‌های برچسب‌دار) — ردیفِ خودکار دیده می‌شود و مقدارش بی‌صدا دور
    # ریخته می‌شود، یعنی همان «بنرِ سبز روی کاری که انجام نشد».
    {"name": "settings: save() reads a different list than the page rendered",
     "path": "app/admin_web.py",
     "old": '    pending, errors, first_bad = [], [], ""\n    for fld in _settings_fields():',
     "new": '    pending, errors, first_bad = [], [], ""\n    for fld in PS.fields():',
     "target": _SKC,
     "expect": "test_a_value_typed_into_an_auto_rendered_row_actually_saves"},

    # برداشتنِ یکی از شش ردیفِ دست‌نویس: گروهِ خودکار جذبش می‌کند، پس پوشش
    # نمی‌شکند — ولی کنترلِ «امروز همه برچسب دارند» می‌افتد. اثباتِ اینکه آن
    # کنترل زنده است و ردیف‌های دستی واقعاً کار می‌کنند.
    {"name": "settings: proxy_url loses its hand-written row",
     "path": 'app/panel_settings.py',
     "old": '            _f("proxy_url", "str", ("پروکسی خروجی", "Outbound proxy"),',
     "new": '            _f("dl_direct_enabled", "str", ("پروکسی خروجی", "Outbound proxy"),',
     "target": _SKC,
     "expect": "test_the_auto_group_is_absent_when_every_key_has_a_label"},

    # ── باگ ۳: برچسبِ دامنه — کلِ بخش بازنشسته شد: `/stats` و کارتِ dlstatِ یک‌روزه
    # دیگر نیستند و گزارش‌ها دانلود را از لاگِ خودش جدا می‌شمارند (موردهای
    # «reports: …» در انتهای فهرست).
    # بازنشسته (۲۰۲۶-۱۰): «stats: the ops KPI goes back to the unqualified label»
    #   the /stats page is gone (→ /reports).

    # بازنشسته (۲۰۲۶-۱۰): «stats: the jobs-backed cards lose their tag»
    #   the /stats page is gone (→ /reports).

    # بازنشسته (۲۰۲۶-۱۰): «stats: the explainer block disappears»
    #   the /stats page is gone (→ /reports).

    # بازنشسته (۲۰۲۶-۱۰): «stats: a files-backed card is wrongly tagged ops-only»
    #   the /stats page is gone (→ /reports).

    # بازنشسته (۲۰۲۶-۱۰): «health: the download-rate card drops its timezone»
    #   the dlstat-day card is gone; rates come from the download log.

    # بازنشسته (۲۰۲۶-۱۰): «health: the download-rate window quietly shifts off today»
    #   the dlstat-day card is gone; rates come from the download log.

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
     # بازلنگر ۲۰۲۶-۰۹-۲۶: شاخهٔ گیتِ سنیِ **پیش از** منو (خطای «confirm your
     # age» در خودِ probe) همین دو خط را دارد، پس الگوی کوتاه دو تطبیق داشت؛
     # `why, url` این را به شاخهٔ `check_meta` (هدفِ اصلیِ این مورد) می‌بندد.
     "old": '                await PS.note(redis, PS.BLOCKED)\n                EV.settle(ev, EV.BLOCKED, "nsfw", why)',
     "new": '                await PS.mark_menu(redis, ref)\n                EV.settle(ev, EV.BLOCKED, "nsfw", why)',
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
    {"name": "panel/system: a queue's depth vanishes from the list",
     "path": 'app/templates/system.html',
     "old": '<span class="num">{{ f.num(queues.get(k, 0)) }}</span>', "new": '<span class="num"></span>',
     "target": _PCT, "expect": 'test_the_system_page_lists_every_queue'},

    {"name": 'panel/system: the live-download count vanishes',
     "path": 'app/templates/system.html',
     "old": '<b class="fw-6">{{ t(\'c.of\', a=f.num(dl_active), b=f.num(dl_conc)) if dl_conc else f.num(dl_active) }}</b>', "new": '<b class="fw-6"></b>',
     "target": _HLT, "expect": 'test_the_live_download_count_reaches_the_page'},

    {"name": 'panel/system: the engine versions vanish',
     "path": 'app/templates/system.html',
     "old": '      <tbody>{% for e in engines %}<tr>', "new": '      <tbody>{% for e in [] %}<tr>',
     "target": _HLT, "expect": "test_the_engine_versions_reach_the_page"},

    {"name": 'panel/dashboard: the cookie-pool card stops counting ready accounts',
     "path": 'app/templates/dashboard.html',
     "old": '          <span class="v num">{{ t(\'d.pool.ready\', a=f.num(r.ready), b=f.num(r.n)) }}</span></div>{% endfor %}', "new": '          <span class="v num"></span></div>{% endfor %}',
     "target": _HLT,
     "expect": 'test_the_cookie_pool_card_reports_each_platform_and_its_ready_count'},

    {"name": 'panel/system: the disk meter vanishes',
     "path": 'app/templates/system.html',
     "old": '    <div class="card-b">{% if disk %}', "new": '    <div class="card-b">{% if False %}',
     "target": _HLT, "expect": "test_the_disk_meter_reports_what_it_measured"},

    {"name": 'panel/system: the redis service card vanishes',
     "path": 'app/templates/system.html',
     "old": '<div class="svc-grid">{% for s in services %}',
     "new": '<div class="svc-grid">{% for s in services if s.key != \'redis\' %}',
     "target": _HLT, "expect": 'test_every_service_reports_its_state'},

    {"name": 'panel/system: the disk meter renders even when nothing was measured',
     "path": 'app/templates/system.html',
     "old": '    <div class="card-b">{% if disk %}',
     "new": '    <div class="card-b">{% if True %}',
     "target": _HLT, "expect": 'test_an_unmeasurable_disk_says_so'},

    {"name": "panel/users: the telegram id vanishes from the row",
     "path": 'app/templates/users.html',
     "old": '<td data-l="{{ t(\'us.col.id\') }}"><bdi class="mono">{{ u.tg }}</bdi></td>', "new": '<td data-l="{{ t(\'us.col.id\') }}"><bdi class="mono"></bdi></td>',
     "target": _URW, "expect": "test_each_row_reports_the_telegram_id_it_is_about"},

    {"name": "panel/users: the pager loses its position",
     "path": 'app/templates/users.html',
     "old": '  {{ m.pager(pager) }}\n', "new": '',
     "target": _URW, "expect": "test_the_pager_states_where_the_admin_is"},

    # الگو تا فاز B یکتا بود و بعد **پیشوندِ** یک رشتهٔ تازه شد: صفحهٔ `/langs`
    # سربرگِ «{{total}} کلیدِ متن» را آورد، پس `{{total}} کل` دو بار جور می‌شد و
    # مورد با `SabotageError` می‌افتاد — دقیقاً همان چیزی که آن استثنا برایش
    # هست، ولی تا امروز کسی دفترچه را بعد از #۱۲۹ کامل replay نکرده بود.
    # لنگرِ `{%` دوباره یکتایش می‌کند. (نه باگِ محصول است نه ادعای عوض‌شده.)
    {"name": "panel/users: the header stops counting",
     "path": 'app/templates/users.html',
     "old": "{{ t('us.sub', n=f.num(data.all), a=f.num(data.active7), b=f.num(data.blocked)) }}", "new": "{{ t('us.sub', n=f.num(0), a=f.num(0), b=f.num(0)) }}",
     "target": _URW, "expect": 'test_the_header_counts_total_active_and_blocked'},

    {"name": "panel/nodes: the node list renders empty",
     "path": 'app/templates/nodes.html',
     "old": '  {% for n in nodes %}',
     "new": '  {% for n in [] %}',
     "target": _NDS,
     "expect": "test_a_registered_node_is_listed_with_its_identifying_facts"},

    # بازلنگرِ ۲۰۲۶-۱۰-۰۹: قالب از نو نوشته شد (همهٔ ردیف‌ها رندر، فیلتر = `hidden`)
    {"name": "panel/texts: the whole catalogue renders empty",
     "path": 'app/templates/texts.html',
     "old": '      {% for g in groups %}',
     "new": '      {% for g in [] %}',
     "target": _TXT, "expect": 'test_a_category_filter_shows_exactly_its_keys'},

    {"name": "panel/texts: the editor box loses the current value",
     "path": 'app/templates/texts.html',
     "old": 'data-tx>\n{{ r.current }}</textarea>',
     "new": 'data-tx>\n</textarea>',
     "target": _TXT, "expect": "test_a_key_is_editable_with_its_current_value"},

    {"name": "panel/texts: search stops filtering",
     "path": "app/admin_web.py",
     "old": "        hit = (not ql or any(ql in _fold(x) for x in (key, default, current))) \\",
     "new": "        hit = True \\",
     "target": _TXT,
     "expect": "test_the_search_narrows_the_list_to_what_matches"},

    # ── /texts بی رفرش (۲۰۲۶-۱۰-۰۹): یکی به‌ازای هر قراردادی که `panel.js` رویش بنا شده ──
    {"name": "panel/texts: a category filter no longer hides the other rows",
     "path": "app/admin_web.py",
     "old": '"shown": hit and cat in ("all", c),',
     "new": '"shown": True,',
     "target": _TXT, "expect": "test_a_category_filter_shows_exactly_its_keys"},

    {"name": "panel/texts: the template drops the hidden attribute of a filtered row",
     "path": "app/templates/texts.html",
     "old": "{% if not r.shown %} hidden{% endif %}",
     "new": "",
     "target": _TXT, "expect": "test_a_category_filter_shows_exactly_its_keys"},

    {"name": "panel/texts: a fetch save gets a redirect instead of JSON",
     "path": "app/admin_web.py",
     "old": '    if not as_json:\n        raise _result("/texts", ok="tx.saved.ok", **back)',
     "new": '    if True:\n        raise _result("/texts", ok="tx.saved.ok", **back)',
     "target": _TXI, "expect": "test_a_fetch_save_answers_with_the_saved_rows"},

    {"name": "panel/texts: an expired session redirects a fetch to the login page",
     "path": "app/admin_web.py",
     "old": "    if as_json and not _session_admin(request):",
     "new": "    if False and not _session_admin(request):",
     "target": _TXI, "expect": "test_an_expired_session_gets_401_json_not_the_login_page"},

    {"name": "panel/texts: a refusal no longer names its key",
     "path": "app/admin_web.py",
     "old": "        if err:\n            errors[key] = err",
     "new": "        if err:\n            errors['_'] = err",
     "target": _TXI, "expect": "test_a_refused_fetch_save_writes_nothing_and_names_each_key"},

    {"name": "panel/texts: the refusal is Persian on an English panel again",
     "path": "app/admin_web.py",
     "old": "        err = textstore.validate(default, value, lang=ui)",
     "new": "        err = textstore.validate(default, value)",
     "target": _TXI, "expect": "test_the_refusal_speaks_the_panel_language"},

    {"name": "panel/texts: a restore through save is logged as an edit",
     "path": "app/admin_web.py",
     "old": '            await _audit(request, "text_reset", target=clears[0] if len(clears) == 1 else "",',
     "new": '            await _audit(request, "text_save", target=clears[0] if len(clears) == 1 else "",',
     "target": _TXI, "expect": "test_restoring_through_save_clears_the_override_and_logs_a_reset"},

    {"name": "panel/texts: a hook panel.js reads is renamed in the template",
     "path": "app/templates/texts.html",
     "old": '<div class="tx-def" data-tx-defbox>',
     "new": '<div class="tx-def" data-txdefbox>',
     "target": _TXI, "expect": "test_every_hook_the_texts_script_reads_is_rendered"},

    {"name": "panel/texts: the row's pill drifts from the one panel.js clones",
     "path": "app/templates/texts.html",
     "old": "{% if r.edited %}{{ edited_pill() }}{% endif %}",
     "new": "{% if r.edited %}<span class=\"pill tx-pill\" data-tx-pill>{{ t('tx.edited') }}</span>{% endif %}",
     "target": _TXI, "expect": "test_the_template_row_parts_match_the_server_markup"},

    {"name": "panel/texts: the server stops folding the zero-width non-joiner",
     "path": "app/admin_web.py",
     "old": '"\\u200c": None, "\\u200d": None,',
     "new": '"\\u200d": None,',
     "target": _TXI, "expect": "test_the_in_place_filter_folds_like_the_server"},

    {"name": "panel/buttons: the op rows render empty",
     "path": 'app/templates/buttons.html',
     "old": '<div class="be-list" id="be-list">{% for it in items %}',
     "new": '<div class="be-list" id="be-list">{% for it in [] %}',
     "target": _BTN, "expect": "test_every_op_of_the_kind_renders_a_row[video]"},

    {"name": "panel/buttons: the kind tabs vanish",
     "path": 'app/templates/buttons.html',
     "old": '<div class="tabs" role="tablist">{% for k, n in kinds %}', "new": '<div class="tabs" role="tablist">{% for k, n in [] %}',
     "target": _BTN, "expect": "test_every_kind_gets_a_tab"},

    # متنِ دکمه **دو بار** رندر می‌شود (جعبهٔ ویرایش + پیش‌نمایشِ زنده). یک
    # ادعای انتها‌به‌انتها هیچ‌کدام را اثبات نمی‌کند، چون لایهٔ دیگر برآورده‌اش
    # می‌کند و «نگرفت» شبیهِ تستِ ضعیف به‌نظر می‌رسد. اندازه‌گیری‌شده: نسخهٔ اول
    # دقیقاً همین‌طور رد شد. پس دو مورد، هرکدام برای یک لایه.
    {"name": "panel/buttons: the editor box loses the button's current label",
     "path": 'app/templates/buttons.html',
     "old": 'name="text_{{ it.op }}" value="{{ it.text }}"',
     "new": 'name="text_{{ it.op }}" value=""',
     "target": _BTN, "expect": "test_the_editor_box_carries_the_current_label"},

    {"name": "panel/buttons: the live preview stops showing the label",
     "path": 'app/templates/buttons.html',
     "old": '<span class="b {{ b.style }}">{{ b.text }}</span>',
     "new": '<span class="b {{ b.style }}"></span>',
     "target": _BTN, "expect": "test_the_live_preview_shows_the_current_label"},

    {"name": 'panel/reports: the errors card renders empty',
     "path": 'app/templates/reports.html',
     "old": '      <tbody>{% for e in d.errors %}', "new": '      <tbody>{% for e in [] %}',
     "target": _STC, "expect": "test_the_recorded_error_reaches_the_errors_card"},

    # بازنشسته (۲۰۲۶-۱۰): «panel/stats: the per-op card renders empty»
    #   merged into the one ops table on /reports.

    {"name": 'panel/reports: the op-performance table renders empty',
     "path": 'app/templates/reports.html',
     "old": '      <tbody>{% for o in d.ops %}', "new": '      <tbody>{% for o in [] %}',
     "target": _STC, "expect": 'test_the_op_performance_table_names_and_counts_its_operations'},

    # بازنشسته (۲۰۲۶-۱۰): «panel/contract: the shared health partial drops off the dashboard»
    #   no shared health partial any more; test_the_services_strip_and_the_system_page_agree.

    # شکلِ واقع‌بینانه: درصدی که روی مخرجِ صفر حساب شود. `pool[0]` عمداً استفاده
    # **نشد** — جینجا اندیسِ خارج از بازه را `Undefined` می‌دهد و بی‌صدا تهی
    # رندر می‌کند، پس اصلاً ۵۰۰ نمی‌شود و سابوتاژ چیزی ثابت نمی‌کرد.
    {"name": "panel/contract: a page 500s on an empty deployment",
     "path": 'app/templates/system.html',
     "old": '      <tbody>{% for e in engines %}<tr>',
     "new": '      <tbody>{{ 100 // (engines|length) }}{% for e in engines %}<tr>',
     "target": _PCT,
     "expect": 'test_every_page_answers_on_an_empty_deployment[/system]'},

    {"name": 'panel/cookies: a status pill is defined but never rendered on its row',
     "path": 'app/templates/cookies.html',
     "old": '<td data-l="{{ t(\'c.status\') }}">{{ m.pill(r.pill) }}', "new": '<td data-l="{{ t(\'c.status\') }}">', "count": 1,
     "target": _CSB,
     "expect": 'test_every_seeded_status_paints_a_pill_on_a_real_row'},

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
     "old": "    without_noise = _DROP.sub(\" \", drop_hidden(html))",
     "new": "    without_noise = _DROP.sub(\" \", _html.unescape(drop_hidden(html)))",
     "target": _PGF,
     "expect": "test_escaped_markup_the_page_shows_literally_survives"},

    {"name": "pagefacts: a hidden subtree is read as visible text",
     "path": "tests/panel/pagefacts.py",
     "old": '    return "".join(p.out)',
     "new": '    return html',
     "target": _PGF, "expect": "test_a_fact_inside_a_hidden_subtree_is_reported_missing"},

    {"name": "pagefacts: a nested element ends the hidden subtree early",
     "path": "tests/panel/pagefacts.py",
     "old": "            self.depth += tag == self.skip",
     "new": "            self.depth += 0",
     "target": _PGF, "expect": "test_a_fact_inside_a_hidden_subtree_is_reported_missing"},

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
     "old": "def validate(default_text: str, value: str, *, require_all_placeholders: bool = False,",
     "new": "def validate(default_text: str, value: str, *, require_all_placeholders: bool = True,",
     "target": "tests/test_phase2a.py",
     "expect": None},   # قاعدهٔ پایه نباید از این تغییر خبردار شود…

    {"name": "textstore: …but the import rule must notice it",
     "path": "app/textstore.py",
     "old": "def validate(default_text: str, value: str, *, require_all_placeholders: bool = False,",
     "new": "def validate(default_text: str, value: str, *, require_all_placeholders: bool = True,",
     "target": _LPK,
     "expect": "test_a_dropped_placeholder_is_refused_even_though_the_editor_allows_it"},

    # پیامِ اعتبارسنجی به زبانِ پنل (۲۰۲۶-۱۰-۰۹)
    {"name": "textstore: validation messages are Persian whatever the panel asks",
     "path": "app/textstore.py",
     "old": '    return (en if lang == "en" else fa).format(**kw)',
     "new": '    return fa.format(**kw)',
     "target": _TVL, "expect": "test_every_message_speaks_the_requested_language[tag]"},

    {"name": "textstore: the default validation language is no longer Persian",
     "path": "app/textstore.py",
     "old": '             lang: str = "fa") -> str | None:',
     "new": '             lang: str = "en") -> str | None:',
     "target": _TVL, "expect": "test_the_default_language_is_still_persian"},

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
     "old": '    if not rv.ok:\n        return await _langs_render(request, review=rv, raw=raw, replace=replace, form=fvals,',
     "new": '    if False:\n        return await _langs_render(request, review=rv, raw=raw, replace=replace, form=fvals,',
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
     "old": "    await textstore.set_texts(code, rv.overrides, replace=replace, clear=rv.defaulted)",
     "new": "    await textstore.set_texts(code, rv.overrides, replace=True, clear=rv.defaulted)",
     "target": _LNG,
     "expect": "test_merge_leaves_the_keys_the_pack_does_not_mention"},

    {"name": "panel: replace silently becomes merge",
     "path": "app/admin_web.py",
     "old": "    await textstore.set_texts(code, rv.overrides, replace=replace, clear=rv.defaulted)",
     "new": "    await textstore.set_texts(code, rv.overrides, replace=False, clear=rv.defaulted)",
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
     "path": 'app/templates/langs.html',
     "old": '&amp;source={{ l.code|urlencode }}"',
     "new": '&amp;source=fa"',
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
     "old": '        done = total if builtin else len([k for k in textstore.lang_texts(code) if k in langpack.TEXT_KEYS])',
     "new": '        done = total',
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

    # ── استخراجِ قالب‌ها به `app/templates/` ────────────────────────────
    # مهم‌ترین یافتهٔ آن فاز: خودِ استخراج یک گاردِ موجود را بی‌اثر می‌کرد.
    # اندازه‌گیری‌شده: هر ۲۰ موردِ `href=`/`src=` در ثابت‌های قالب بود و صفر در
    # بقیهٔ `admin_web.py`، پس آن تست پس از استخراج فایلی را اسکن می‌کرد که
    # هیچ‌کدام را ندارد و **برای همیشه سبز** می‌ماند.
    {"name": "templates: a CDN planted in a template is not noticed",
     "path": "tests/panel/test_security_headers.py",
     "old": '*app.glob("templates/*.html"),\n',
     "new": "",
     "target": _SEC,
     "expect": "test_the_scope_really_covers_the_templates"},

    # و کنترلِ همان از سمتِ داده: با دامنهٔ درست، یک CDNِ واقعی باید بیفتد.
    {"name": "templates: an external script really is caught",
     "path": "app/templates/base.html",
     "old": '<meta charset="utf-8">',
     "new": '<meta charset="utf-8"><script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
     "target": _SEC,
     "expect": "test_the_panel_has_no_external_resources_for_the_csp_to_break"},

    # قالبی بیرونِ `app/` = ۵۰۰ روی تولید با CIِ سبز.
    {"name": "templates: the template dir moves outside app/",
     "path": "app/admin_web.py",
     "old": 'os.path.dirname(os.path.abspath(__file__)), "templates")',
     "new": 'os.path.dirname(os.path.abspath(__file__)), "..", "templates")',
     "target": _TPF,
     "expect": "test_every_runtime_asset_dir_ships_in_the_admin_image"},

    # Jinja **یک** خطِ پایانی می‌خورد؛ دومی به هر صفحه یک `\n` اضافه می‌کند.
    {"name": "templates: a second trailing newline leaks into every page",
     "path": "app/templates/base.html",
     "old": '</body>\n</html>\n',
     "new": '</body>\n</html>\n\n',
     "target": _TPF,
     "expect": "test_a_template_file_ends_with_exactly_one_newline[base.html]"},

    # کامنتِ Dockerfile نباید پوشش شمرده شود (تلهٔ خودارجاعی).
    {"name": "templates: the COPY parser stops stripping comments",
     "path": "tests/panel/test_template_files.py",
     "old": 'lines = [re.sub(r"#.*$", "", ln) for ln in',
     "new": 'lines = [ln for ln in',
     "target": _TPF,
     "expect": "test_the_copy_parser_ignores_comments"},

    # بازنشسته (۲۰۲۶-۱۰): «templates: the shared health fragment is dropped from the dashboard»
    #   no shared health partial any more; test_the_services_strip_and_the_system_page_agree.

    # ── استخراجِ CSS به `app/static/css/panel.css` ─────────────────────
    # CSS از فایل خوانده می‌شود ولی همچنان درون‌خطی می‌رود. رفتن به `<link>`
    # باید تصمیمِ آگاهانه باشد، نه اثرِ جانبی — اندازه‌گیری‌شده ۱۵ تا ۱۹ شکست.
    {"name": 'css: the page stops linking the versioned stylesheet',
     "path": "app/templates/base.html",
     "old": '<link rel="stylesheet" href="{{ asset(\'css/panel.css\') }}">',
     "new": '<link rel="stylesheet" href="/static/css/panel.css">',
     "target": _TPF,
     "expect": 'test_the_stylesheet_that_ships_is_the_file_on_disk'},

    # و کنترلِ اینکه فایل واقعاً منبع است، نه یک کپیِ جاافتاده در پایتون.
    {"name": 'assets: the version stops being derived from the file',
     "path": "app/admin_web.py",
     "old": '        self.ver = hashlib.sha256(data).hexdigest()[:10]',
     "new": '        self.ver = "0123456789"',
     "target": _TPF,
     "expect": "test_the_stylesheet_that_ships_is_the_file_on_disk"},
    # ── فاز ۱: شش رفعِ امنیتی (بحرانی/بالا) ──────────────────────────
    {"name": "phase1 downloader filename escape",
     "path": "app/downloader.py",
     "old": "    name = (name or \"\").strip().strip('\"')\n    for _ in range(3):                        # تا decodeِ تثبیت‌شده (double-encoding)\n        dec = unquote(name)\n        if dec == name:\n            break\n        name = dec\n    name = name.replace(\"\\\\\", \"/\").split(\"/\")[-1]     # حالا جداکردنِ مسیر امن است\n    name = re.sub(r'[\\x00-\\x1f<>:\"|?*/\\\\]+', \"\", name).strip(\" .\")",
     "new": "    name = unquote((name or \"\").strip().strip('\"').replace(\"\\\\\", \"/\").split(\"/\")[-1])\n    name = re.sub(r'[\\x00-\\x1f<>:\"|?*]+', \"\", name).strip(\" .\")",
     "target": _DFN,
     "expect": "test_disposition_filename_is_never_a_path[abs-star]"},
    {"name": "phase1 cache poison host gate",
     "path": "app/dl_cache.py",
     "old": "    plat = platform_of(u)\n    for prefix, platform, rx in ((\"yt\", \"youtube\", _YT_RE), (\"ig\", \"instagram\", _IG_RE),\n                                 (\"x\", \"twitter\", _X_RE), (\"tt\", \"tiktok\", _TT_RE)):\n        if plat != platform:\n            continue\n        m = rx.search(u)\n        if m:\n            return f\"{prefix}:{m.group(1)}\"",
     "new": "    for prefix, rx in ((\"yt\", _YT_RE), (\"ig\", _IG_RE), (\"x\", _X_RE), (\"tt\", _TT_RE)):\n        m = rx.search(u)\n        if m:\n            return f\"{prefix}:{m.group(1)}\"",
     "target": _DLC,
     "expect": "test_foreign_host_does_not_collide_with_real_platform[https://attacker.example/promo.bin?r=youtu.be/dQw4w9WgXcQ-https://youtu.be/dQw4w9WgXcQ]"},
    {"name": "phase1 gateway inline-safe gate",
     "path": "app/gateway.py",
     "old": "    disp = \"inline\" if (inline and _is_inline_safe(mime)) else \"attachment\"",
     "new": "    disp = \"inline\" if inline else \"attachment\"",
     "target": _GWI,
     "expect": "test_stream_forces_attachment_and_sets_security_headers[text/html-True]"},
    {"name": "phase1 wg peer pubkey guard",
     "path": "app/nodes.py",
     "old": "    return \"\".join(peer_block(pk, ip) for pk, ip in sorted(peers) if valid_pubkey(pk))",
     "new": "    return \"\".join(peer_block(pk, ip) for pk, ip in sorted(peers) if pk)",
     "target": _WGK,
     "expect": "test_render_peers_drops_injected_key"},
    {"name": "phase1 archive bomb in-flight cap",
     "path": "app/processing.py",
     "old": "                if _dir_size(exdir) > max_bytes:        # از بودجه رد شد → بکُش",
     "new": "                if False:        # sabotage",
     "target": _ARB,
     "expect": "test_extraction_is_killed_when_it_exceeds_the_cap"},
    {"name": "phase1 safety image size cap",
     "path": "app/safety.py",
     "old": "    if kind == \"image\" or path.lower().endswith(_IMAGE_EXTS):\n        wd = workdir or os.path.dirname(path) or \".\"\n        dims = _image_dims(path)\n        if dims and dims[0] * dims[1] > _MAX_SCAN_PIXELS:",
     "new": "    if kind == \"image\" or path.lower().endswith(_IMAGE_EXTS):\n        wd = workdir or os.path.dirname(path) or \".\"\n        dims = None\n        if dims and dims[0] * dims[1] > _MAX_SCAN_PIXELS:",
     "target": _SIC,
     "expect": "test_huge_image_is_never_handed_raw_to_the_detector"},


    # ── وابستگیِ یوتیوب به کوکی (۲۰۲۶-۰۹): دسته‌بندیِ خطا ───────────────────
    # هر خطای «sign in»ِ یوتیوب جملهٔ `--cookies`ِ yt-dlp را دارد؛ هر نشانه‌ای که
    # به آن تکیه کند ویدیوی سنی/خصوصی را bot-check می‌خواند و اکانت می‌سوزاند.
    {"name": "yt-auth: 'sign in to confirm' is a bot-check hint again (age gate strikes)",
     "path": "app/cookies.py",
     "old": '    (BOT_CHECK, ("confirm you\\u2019re not a bot", "confirm you\'re not a bot",',
     "new": ('    (BOT_CHECK, ("sign in to confirm", "confirm you\\u2019re not a bot", '
             '"confirm you\'re not a bot",'),
     "target": _YEK,
     "expect": "test_the_generic_classifier_no_longer_calls_an_age_gate_a_bot_check"},

    {"name": "yt-auth: --cookies reads as a bot-check again (age/private misfiled)",
     "path": "app/downloader.py",
     "old": '    (YT_BOT_CHECK, ("confirm you’re not a bot", "confirm you\'re not a bot",',
     "new": '    (YT_BOT_CHECK, ("--cookies", "confirm you’re not a bot", "confirm you\'re not a bot",',
     "target": _YEK,
     "expect": "test_each_youtube_error_reads_as_its_own_kind[age]"},

    # ۴۰۳ِ googlevideo بدونِ این نگاشت به `classify_error` می‌افتد که «403» را
    # لاگین می‌خواند — همان ضربه به اکانتِ سالم.
    {"name": "yt-auth: a media-download 403 strikes the account again",
     "path": "app/tasks_download.py",
     "old": "    D.YT_GVS_403: ck.TRANSIENT,\n",
     "new": "",
     "target": _YEK,
     "expect": "test_fetch_download_403_does_not_strike_the_account"},

    # ── probe ──
    {"name": "yt-auth: probe age gate spends a second account again",
     "path": "app/tasks_download.py",
     "old": ("                if kind == D.YT_AGE_GATE and pol.enabled:\n"
             "                    break           # فیلتر"),
     "new": ("                if False:\n"
             "                    break           # فیلتر"),
     "target": _YEK,
     "expect": "test_probe_age_gate_is_blocked_without_a_second_account"},

    # کنترلِ معکوس: تستِ «فیلترِ خاموش» اصلاً از آن `break` رد نمی‌شود — پس سبز
    # ماندنش نشان می‌دهد دو تستِ سنی دو شاخهٔ جدا را می‌سنجند، نه یکی را دوبار.
    {"name": "yt-auth: CONTROL — dropping the probe age break must NOT fail the safety-off test",
     "path": "app/tasks_download.py",
     "old": ("                if kind == D.YT_AGE_GATE and pol.enabled:\n"
             "                    break           # فیلتر"),
     "new": ("                if False:\n"
             "                    break           # فیلتر"),
     "target": _YEK + "::test_probe_age_gate_with_safety_off_rotates_without_strikes",
     "expect": None},

    {"name": "yt-auth: a probe age block is filed as a probe failure",
     "path": "app/tasks_download.py",
     "old": ('                await PS.note(redis, PS.BLOCKED)\n                EV.settle(ev, EV.BLOCKED, "age_limit", attempts=attempts)'),
     "new": ('                await PS.note(redis, PS.FAIL)\n                EV.settle(ev, EV.BLOCKED, "age_limit", attempts=attempts)'),
     "target": _YEK,
     "expect": "test_probe_age_gate_is_blocked_without_a_second_account"},

    {"name": "yt-auth: probe page-reload is not retried without a cookie",
     "path": "app/tasks_download.py",
     "old": "                if kind == D.YT_RELOAD and cname and not anon_tried:",
     "new": "                if False:",
     "target": _YEK,
     "expect": "test_probe_page_reload_with_a_cookie_is_retried_once_without_one"},

    {"name": "yt-auth: a private video counts against the exit again (probe)",
     "path": "app/tasks_download.py",
     "old": ("            if not _says_nothing_about_exit(msg, kind):\n"
             "                # ویدیوی خصوصی/سنی دربارهٔ خروجی"),
     "new": ("            if True:\n"
             "                # ویدیوی خصوصی/سنی دربارهٔ خروجی"),
     "target": _YEK,
     "expect": "test_probe_private_video_costs_one_attempt_and_no_account"},

    # ── fetch ──
    {"name": "yt-auth: a private video escalates to a cookie again (fetch)",
     "path": "app/tasks_download.py",
     "old": ("                if kind in D.YT_CONTENT_KINDS:\n"
             "                    # خصوصی/فقط-اعضا"),
     "new": ("                if False:\n"
             "                    # خصوصی/فقط-اعضا"),
     "target": _YEK,
     "expect": "test_fetch_private_video_never_escalates_to_a_cookie"},

    {"name": "yt-auth: a fetch age gate goes to a cookie before the filter",
     "path": "app/tasks_download.py",
     "old": ("                if kind == D.YT_AGE_GATE:\n"
             "                    pol = await safety.load_policy()"),
     "new": ("                if False:\n"
             "                    pol = await safety.load_policy()"),
     "target": _YEK,
     "expect": "test_fetch_age_gate_is_blocked_before_any_cookie"},

    {"name": "yt-auth: an age-gated account failure blames the exit again",
     "path": "app/tasks_download.py",
     "old": ("                    if kind != D.YT_AGE_GATE:\n"
             "                        # سنی نه تقصیرِ اکانت"),
     "new": ("                    if True:\n"
             "                        # سنی نه تقصیرِ اکانت"),
     "target": _YEK,
     "expect": "test_fetch_age_gate_with_safety_off_rotates_but_blames_nobody"},

    {"name": "yt-auth: fetch page-reload is not retried without a cookie",
     "path": "app/tasks_download.py",
     "old": "                if (kind == D.YT_RELOAD and cookie_name and not anon_tried\n",
     "new": "                if (False\n",
     "target": _YEK,
     "expect": "test_fetch_page_reload_with_a_cookie_tries_once_without_one"},

    {"name": "yt-auth: a private video counts against the exit again (fetch)",
     "path": "app/tasks_download.py",
     "old": ("            if not _says_nothing_about_exit(msg, kind):\n"
             "                await ck.note_exit(redis, settings.node_id, platform, ok=False)\n"
             "            if exit_bad:"),
     "new": ("            if True:\n"
             "                await ck.note_exit(redis, settings.node_id, platform, ok=False)\n"
             "            if exit_bad:"),
     "target": _YEK,
     "expect": "test_fetch_private_video_never_escalates_to_a_cookie"},

    # ── تکرارِ «بدونِ pot» فقط برای کرشِ پلاگین ──
    {"name": "yt-auth: fetch retries without pot on any error again",
     **_POT_GATE_PATCH,
     "target": _YEK,
     "expect": "test_a_clean_youtube_error_is_not_repeated_without_pot"},

    # کنترلِ معکوس: تستِ کرش از آن گیت مستقل است — سبزش یعنی مسیرِ کرش را
    # می‌سنجد، نه صرفاً «گیت هست».
    {"name": "yt-auth: CONTROL — an open pot gate must NOT fail the plugin-crash test",
     **_POT_GATE_PATCH,
     "target": _YEK + "::test_a_plugin_crash_is_still_retried_without_pot",
     "expect": None},

    {"name": "yt-auth: matched tracks retry without pot on any error again",
     "path": "app/downloader.py",
     "old": ('            if (opts.get("pot_provider") and not isinstance(exc, AgeRestricted)\n'
             "                    and is_pot_crash(str(exc))):"),
     "new": '            if (opts.get("pot_provider") and not isinstance(exc, AgeRestricted)):',
     "target": _YEK,
     "expect": "test_a_matched_track_is_not_repeated_without_pot_on_a_clean_error"},

    # ── تله‌متری ──
    {"name": "yt-auth: other platforms land in the youtube counter",
     "path": "app/tasks_download.py",
     "old": ('    if redis is None or platform != "youtube":\n'
             "        return\n"
             '    mode = "cookie" if cookie_name else "anon"'),
     "new": ("    if redis is None:\n"
             "        return\n"
             '    mode = "cookie" if cookie_name else "anon"'),
     "target": _YEK,
     "expect": "test_other_platforms_write_no_youtube_counter"},

    {"name": "yt-auth: the youtube counter expires in two days like _metric",
     "path": "app/tasks_download.py",
     "old": "_YTAUTH_TTL = 8 * 86400",
     "new": "_YTAUTH_TTL = 2 * 86400",
     "target": _YEK,
     "expect": "test_each_attempt_lands_in_its_own_counter"},

    # ── `_stderr_summary`: `\r`ِ خطای دانلودِ تکه‌ای ──
    {"name": "yt-auth: the summary splits on the carriage return again (HLS 403 → 'ERROR:')",
     **_SUMMARY_CR_PATCH,
     "target": _YEK,
     "expect": "test_a_fragment_download_error_keeps_its_text[alone]"},

    {"name": "yt-auth: a fragment 403 is no longer escalated end to end",
     **_SUMMARY_CR_PATCH,
     "target": _YEK,
     "expect": "test_fetch_fragment_403_escalates_and_shows_its_cause"},

    # ── پین‌ها ──
    {"name": "yt-pins: production yt-dlp floats again (Docker freezes it silently)",
     "path": "requirements-worker-dl.txt",
     "old": "yt-dlp[default]==2026.8.19 ",
     "new": "yt-dlp[default] ",
     "target": _PIN,
     "expect": "test_production_pins_yt_dlp_exactly"},

    {"name": "yt-pins: the test environment floats yt-dlp again",
     "path": "requirements-dev.txt",
     "old": "yt-dlp==2026.8.19\n",
     "new": "yt-dlp\n",
     "target": _PIN,
     "expect": "test_the_test_environment_pins_the_production_yt_dlp"},

    {"name": "yt-pins: the pot server image floats on :latest again",
     "path": "docker-compose.yml",
     "old": "    image: brainicism/bgutil-ytdlp-pot-provider:2.0.0",
     "new": "    image: brainicism/bgutil-ytdlp-pot-provider:latest",
     "target": _PIN,
     "expect": "test_the_pot_server_image_is_pinned_not_latest"},

    # ── ابزارِ سنجش (`tools/yt_client_matrix.py`) ──
    # کلاینتِ ناشناخته بی‌صدا پیش‌فرض می‌شود و فقط WARNING گواهِ آن است.
    {"name": "yt-matrix: --no-warnings is back (an unknown client is silently the default)",
     **_MATRIX_NOWARN_PATCH,
     "target": _YCM,
     "expect": "test_the_tool_keeps_the_warnings_production_hides"},

    # کنترلِ معکوس: استابِ `run_cell` WARNING را بی‌اعتنا به پرچم‌ها می‌نویسد، پس
    # همان خرابکاری آن را نمی‌اندازد — نگهبانِ پرچم تستِ ساختاریِ بالاست، نه این.
    {"name": "yt-matrix: CONTROL — --no-warnings back must NOT fail the stub's unsupported test",
     **_MATRIX_NOWARN_PATCH,
     "target": _YCM + "::test_an_unsupported_client_run_is_flagged_even_though_it_succeeded",
     "expect": None},

    {"name": "yt-matrix: a run for a client that never ran reads as ok",
     "path": "tools/yt_client_matrix.py",
     "old": ("    if any(h in _norm(stderr) for h in _UNSUPPORTED):\n"
             '        return "unsupported"\n'),
     "new": "",
     "target": _YCM,
     "expect": "test_a_run_for_a_client_that_never_ran_is_not_ok"},

    {"name": "yt-matrix: the carriage return splits the error line again",
     "path": "tools/yt_client_matrix.py",
     "old": ('    return [ln.strip() for ln in (text or "").replace("\\r", " ").split("\\n") '
             "if ln.strip()]"),
     "new": '    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]',
     "target": _YCM,
     "expect": "test_the_final_error_wins_over_an_earlier_warning"},

    {"name": "yt-matrix: a text-mode pipe turns the carriage return into a newline",
     "path": "tools/yt_client_matrix.py",
     "old": "                           capture_output=True, timeout=timeout, env=env)",
     "new": "                           capture_output=True, text=True, timeout=timeout, env=env)",
     "target": _YCM,
     "expect": "test_a_fragment_403_survives_the_pipe"},

    {"name": "yt-matrix: a warning outranks the final error",
     "path": "tools/yt_client_matrix.py",
     "old": '    return _match(errs) or _match(stderr) or "other"',
     "new": '    return _match(stderr) or "other"',
     "target": _YCM,
     "expect": "test_the_final_error_wins_over_an_earlier_warning"},

    {"name": "yt-matrix: no fallback to the whole stderr",
     "path": "tools/yt_client_matrix.py",
     "old": '    return _match(errs) or _match(stderr) or "other"',
     "new": '    return _match(errs) or "other"',
     "target": _YCM,
     "expect": "test_a_hint_outside_the_error_line_is_still_read"},

    {"name": "yt-matrix: extraction alone counts as ok",
     "path": "tools/yt_client_matrix.py",
     "old": "    if rc == 0 and got_json and file_ok:",
     "new": "    if rc == 0 and got_json:",
     "target": _YCM,
     "expect": "test_ok_needs_real_bytes_not_just_extraction"},

    # کپیِ دومِ نشانه‌ها: واگرایی از تولید در هر دو جهت دیده می‌شود.
    {"name": "yt-matrix: a tool hint drifts from production",
     "path": "tools/yt_client_matrix.py",
     "old": ('    ("bot_check", ("confirm you’re not a bot", "confirm you\'re not a bot",\n'
             '                   "confirm you are not a bot")),'),
     "new": '    ("bot_check", ("confirm you’re not a bot", "confirm you\'re not a bot")),',
     "target": _YCM,
     "expect": "test_each_production_hint_reads_the_same_in_the_tool[bot_check-2]"},

    {"name": "yt-matrix: a new production kind goes unnoticed",
     "path": "app/downloader.py",
     "old": '    (YT_PRIVATE, ("private video",)),',
     "new": '    ("x_new", ("zzzz-never-seen",)),\n    (YT_PRIVATE, ("private video",)),',
     "target": _YCM,
     "expect": "test_every_production_kind_has_a_tool_outcome"},

    {"name": "yt-matrix: the stats reader drifts from the production key",
     "path": "tools/yt_client_matrix.py",
     "old": '        if len(parts) != 6 or parts[:2] != ["dlstat", "ytauth"]:',
     "new": '        if len(parts) != 6 or parts[:2] != ["dlstat", "yt_auth"]:',
     "target": _YCM,
     "expect": "test_the_stats_reader_parses_what_production_writes"},

    # ارکستراسیون
    {"name": "yt-matrix: a version already measured is counted twice",
     "path": "tools/yt_client_matrix.py",
     "old": "        if label in seen:",
     "new": "        if False:",
     "target": _YCM,
     "expect": "test_a_version_equal_to_one_already_measured_is_not_counted_twice"},

    {"name": "yt-matrix: an unknown client is tried on every video",
     "path": "tools/yt_client_matrix.py",
     "old": '                if res["outcome"] == "unsupported":',
     "new": "                if False:",
     "target": _YCM,
     "expect": "test_an_unknown_client_costs_one_request_not_one_per_video"},

    {"name": "yt-matrix: a rate limit does not stop the measurement",
     "path": "tools/yt_client_matrix.py",
     "old": '                if res["outcome"] == "rate_limit" and not keep_going:',
     "new": "                if False:",
     "target": _YCM,
     "expect": "test_a_rate_limit_stops_the_measurement"},

    {"name": "yt-matrix: the other version is installed without the production extra",
     "path": "tools/yt_client_matrix.py",
     "old": '                        f"yt-dlp[default]=={version}"], check=True)',
     "new": '                        f"yt-dlp=={version}"], check=True)',
     "target": _YCM,
     "expect": "test_a_new_version_is_installed_with_the_production_extra"},
    # ── فاز ۲: درستی/پایداری ─────────────────────────────────────────
    {"name": 'audit2 ops rate counter goes back to expire-on-first-only',
     "path": 'app/routers/ops.py',
     "old": '        r = await counters.incr_window(pool, f"rate:{user_id}", 60)',
     "new": '        r = await pool.incr(f"rate:{user_id}")\n        if r == 1:\n            await pool.expire(f"rate:{user_id}", 60)',
     "target": _ORT,
     "expect": 'test_a_rate_counter_that_lost_its_ttl_is_repaired'},
    {"name": 'audit2 shared counter stops repairing lost TTL (bot side)',
     "path": 'app/counters.py',
     "old": '    if n == amount or await redis.ttl(key) < 0:',
     "new": '    if n == amount:',
     "target": _ORT,
     "expect": 'test_incr_window_repairs_and_returns_the_new_value'},
    {"name": 'audit2 download ticker safety net removed from finally',
     "path": 'app/tasks_download.py',
     "old": '        if ticker is not None and not ticker.done():\n            ticker.cancel()\n        if beat is not None:',
     "new": '        if beat is not None:',
     "target": _DTO,
     "expect": 'test_a_cancelled_download_leaves_no_live_ticker'},
    # فرمِ «طبیعی»ترِ همان رفع: awaitِ تیکر در finally. لغوِ جاب را دوباره raise می‌کند و آزادکردنِ اسلات را قطع می‌کند.
    {"name": 'audit2 download ticker awaited in finally (aborts the cleanup)',
     "path": 'app/tasks_download.py',
     "old": '        if ticker is not None and not ticker.done():\n            ticker.cancel()\n        if beat is not None:',
     "new": '        if ticker is not None:\n            await P.stop_task(ticker)\n        if beat is not None:',
     "target": _DTO,
     "expect": 'test_the_cancelled_job_still_frees_its_slot'},
    {"name": 'audit2 exit pin goes back to ignoring pins on the master',
     "path": 'app/cookies.py',
     "old": '             and str(a.get("node_id") or "") in ("", here)]',
     "new": '             and not (str(a.get("node_id") or "") and node_id\n                      and str(a.get("node_id")) != node_id)]',
     "target": _EPM,
     "expect": 'test_the_master_never_uses_an_account_pinned_to_a_node'},
    {"name": 'audit2 omitted exit means ignore pins again',
     "path": 'app/cookies.py',
     "old": '    here = str((settings.node_id if node_id is None else node_id) or "")',
     "new": '    here = str(node_id or "")',
     "target": _EPM,
     "expect": 'test_an_omitted_exit_means_this_process_not_any'},
    {"name": 'audit2 new user race goes back to crashing',
     "path": 'app/middlewares.py',
     "old": '        except IntegrityError:\n            await session.rollback()\n            user = await _find_user(session, tg_user.id)\n            if user is None:      # تعارض از جای دیگری بود — پنهانش نکن\n                raise',
     "new": '        except IntegrityError:\n            raise',
     "target": _NUR,
     "expect": 'test_a_concurrent_first_update_does_not_crash'},
    {"name": 'audit2 new user race hides an unrelated integrity error',
     "path": 'app/middlewares.py',
     "old": '            if user is None:      # تعارض از جای دیگری بود — پنهانش نکن\n                raise',
     "new": '            if user is None:      # تعارض از جای دیگری بود — پنهانش نکن\n                return None',
     "target": _NUR,
     "expect": 'test_an_unrelated_integrity_error_is_not_hidden'},
    {"name": 'audit2 a 404 benches the exit again',
     "path": 'app/tasks_download.py',
     "old": '    blame_exit = ((not won) and not reached_content\n                  and len({n for n, _m, _c in failures}) >= 2)',
     "new": '    blame_exit = ((not won)\n                  and len({n for n, _m, _c in failures}) >= 2)',
     "target": _EBC,
     "expect": 'test_run_download_does_not_bench_a_working_exit_on_a_404'},
    {"name": 'audit2 run_op spawn failure keeps its orphan row',
     "path": 'app/tasks.py',
     "old": '                    log.exception("job %s spawn-card send failed", job_id)\n                    await session.delete(newf)\n',
     "new": '                    log.exception("job %s spawn-card send failed", job_id)\n',
     "target": _DLF,
     "expect": 'test_a_failed_spawn_leaves_no_orphan_row'},
    {"name": 'audit2 run_op extracted files counted done whatever was sent',
     "path": 'app/tasks.py',
     "old": '                if failed_n:\n                    total_n = len(res["files"])',
     "new": '                if False:\n                    total_n = len(res["files"])',
     "target": _DLF,
     "expect": 'test_a_failed_send_is_a_failed_job[files]'},
    {"name": 'audit2 run_op card move unguarded again',
     "path": 'app/tasks.py',
     "old": '    try:\n        await move_card_below(bot, chat_id, card_mid, file, lang, collapsed=False)\n    except Exception:  # noqa: BLE001',
     "new": '    await move_card_below(bot, chat_id, card_mid, file, lang, collapsed=False)\n    if False:  # noqa: BLE001',
     "target": _DLF,
     "expect": 'test_a_card_move_failure_after_delivery_is_still_done[files]'},
    {"name": 'audit2 download spawn failure keeps its orphan row',
     "path": 'app/tasks_download.py',
     "old": '            log.exception("dl spawn-card send failed")\n            await s.delete(f)\n',
     "new": '            log.exception("dl spawn-card send failed")\n',
     "target": _DDF,
     "expect": 'test_a_failed_spawn_reports_and_leaves_no_row'},
    {"name": 'audit2 a partial album is cached again',
     "path": 'app/tasks_download.py',
     "old": '                if items and not deliver_err:   # کاروسل هم کش می\u200cشود → بارِ بعد آنی',
     "new": '                if items:   # کاروسل هم کش می\u200cشود → بارِ بعد آنی',
     "target": _DDF,
     "expect": 'test_a_partial_album_is_not_cached_and_not_a_success'},
    {"name": 'audit2 a failed download delivery is counted a success again',
     "path": 'app/tasks_download.py',
     "old": '        if deliver_err:\n            # ارسال به کاربر شکست خورد.',
     "new": '        if False:\n            # ارسال به کاربر شکست خورد.',
     "target": _DDF,
     "expect": 'test_a_failed_single_delivery_tells_the_user'},
    {"name": 'audit2 download cooldown is check-then-set again',
     "path": 'app/routers/download.py',
     "old": '        if cd > 0 and not await pool.set(cd_key, "1", ex=cd, nx=True):',
     "new": '        if cd > 0 and await pool.exists(cd_key):',
     "target": _DQB,
     "expect": 'test_concurrent_reservations_respect_the_cooldown'},
    {"name": 'audit2 a rejected download keeps its charge',
     "path": 'app/routers/download.py',
     "old": '            await pool.decr(cnt_key)          # رد شد → شارژ برگردد\n',
     "new": '',
     "target": _DQB,
     "expect": 'test_concurrent_reservations_respect_the_daily_cap'},
    {"name": 'audit2 the quality pick only checks the quota again',
     "path": 'app/routers/download.py',
     "old": '    block = await _reserve(arq_pool, uid, lang)       # چک + شارژ، اتمی',
     "new": '    block = await _precheck(arq_pool, uid, lang)',
     "target": _DQB,
     "expect": 'test_simultaneous_picks_cannot_exceed_the_daily_cap'},
    {"name": 'audit2 panel csrf accepts same-site (the gateway port) again',
     "path": 'app/admin_web.py',
     "old": '            ok = sfs == "same-origin"',
     "new": '            ok = sfs in ("same-origin", "same-site")',
     "target": _CSG,
     "expect": 'test_a_cross_site_post_does_not_act[same-site]'},
    {"name": 'audit2 panel csrf ignores the Origin header',
     "path": 'app/admin_web.py',
     "old": '            ok = urlsplit(origin).netloc.lower() in _origin_netlocs(request)',
     "new": '            ok = True',
     "target": _CSG,
     "expect": 'test_a_cross_site_post_does_not_act[foreign-origin]'},
    {"name": 'audit2 panel csrf guard not installed',
     "path": 'app/admin_web.py',
     "old": '    app = web.Application(middlewares=[_compress, _security_headers, _csrf_guard, _panel_prefs],',
     "new": '    app = web.Application(middlewares=[_compress, _security_headers, _panel_prefs],',
     "target": _CSG,
     "expect": 'test_a_cross_site_post_does_not_act[cross-site]'},
    # ── فاز ۳: رسانه/پردازش ─────────────────────────────────────────
    {"name": 'audit3 convert keeps the source pixel format',
     "path": 'app/processing.py',
     "old": 'args = [FFMPEG, "-y", "-i", inp, "-vf", _DELIVERY_VF]',
     "new": 'args = [FFMPEG, "-y", "-i", inp]',
     "target": _PXF,
     "expect": 'test_a_10bit_source_comes_out_8bit[convert-mkv]'},
    {"name": 'audit3 trim keeps the source pixel format',
     "path": 'app/processing.py',
     "old": '"-i", inp, "-vf", _DELIVERY_VF,\n        "-c:v", "libx264"',
     "new": '"-i", inp,\n        "-c:v", "libx264"',
     "target": _PXF,
     "expect": 'test_a_10bit_source_comes_out_8bit[trim]'},
    {"name": 'audit3 half fix: yuv420p without even dimensions',
     "path": 'app/processing.py',
     "old": '_DELIVERY_VF = "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"',
     "new": '_DELIVERY_VF = "format=yuv420p"',
     "target": _PXF,
     "expect": 'test_an_odd_sized_444_source_still_encodes[trim]'},
    {"name": 'audit3 watermark keeps the source pixel format',
     "path": 'app/processing.py',
     "old": '    fc += f",{_DELIVERY_VF}"\n',
     "new": '',
     "target": _PXF,
     "expect": 'test_an_odd_sized_444_source_still_encodes[watermark]'},
    {"name": 'audit3 compress ignores EXIF orientation',
     "path": 'app/processing.py',
     "old": '    _flatten_rgb(_upright(inp)).save(out, "JPEG", quality=70, optimize=True)',
     "new": '    _flatten_rgb(Image.open(inp)).save(out, "JPEG", quality=70, optimize=True)',
     "target": _ORI,
     "expect": 'test_compress_keeps_a_portrait_photo_upright'},
    {"name": 'audit3 convert ignores EXIF orientation',
     "path": 'app/processing.py',
     "old": '    img = _upright(inp)\n    fmt = fmt.lower()',
     "new": '    img = Image.open(inp)\n    fmt = fmt.lower()',
     "target": _ORI,
     "expect": 'test_convert_keeps_a_portrait_photo_upright[png]'},
    {"name": 'audit3 a raw Image.open comes back (bg remove)',
     "path": 'app/processing.py',
     "old": '    res = remove(_upright(inp).convert("RGBA"))',
     "new": '    res = remove(Image.open(inp).convert("RGBA"))',
     "target": _ORI,
     "expect": 'test_every_pillow_open_in_processing_goes_through_upright'},
    {"name": 'audit3 trim_video accepts a range past the end',
     "path": 'app/processing.py',
     "old": '    await _check_trim_range(inp, start)\n    await _run([\n        FFMPEG,',
     "new": '    await _run([\n        FFMPEG,',
     "target": _TRR,
     "expect": 'test_a_range_past_the_end_is_an_error[video-far-past]'},
    {"name": 'audit3 trim_audio accepts a range past the end',
     "path": 'app/processing.py',
     "old": '    await _check_trim_range(inp, start)\n    await _run([FFMPEG, "-y", "-ss"',
     "new": '    await _run([FFMPEG, "-y", "-ss"',
     "target": _TRR,
     "expect": 'test_a_range_past_the_end_is_an_error[audio-at-end]'},
    {"name": 'audit3 trim router stops checking the card duration',
     "path": 'app/routers/ops.py',
     "old": '    if file.duration and rng[0] >= file.duration:',
     "new": '    if False:',
     "target": _TRR,
     "expect": 'test_the_router_refuses_a_range_past_the_card_duration'},
    {"name": 'audit3 time parser accepts infinity',
     "path": 'app/routers/ops.py',
     "old": '    return sec if sec >= 0 and math.isfinite(sec) else None',
     "new": '    return sec if sec >= 0 else None',
     "target": _TRR,
     "expect": 'test_non_finite_times_are_not_a_range[inf]'},
    {"name": 'audit3 aac tags go into an mp3 container again',
     "path": 'app/processing.py',
     "old": '    "aac": (".m4a", True),',
     "new": '    "aac": (".mp3", True),',
     "target": _AMC,
     "expect": 'test_tags_are_written_without_a_cover[aac-nameless]'},
    {"name": 'audit3 ogg is trusted to hold a cover',
     "path": 'app/processing.py',
     "old": '        if holds_cover or not want_cover:',
     "new": '        if True:',
     "target": _AMC,
     "expect": 'test_a_cover_is_embedded_whatever_the_source[voice-opus]'},
    {"name": 'audit3 a wav with a cover drops to mp3',
     "path": 'app/processing.py',
     "old": '        return ".flac", ["-c:a", "flac"]',
     "new": '        return ".mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]',
     "target": _AMC,
     "expect": 'test_a_lossless_source_stays_lossless_with_a_cover'},
    {"name": 'audit3 safe stem strips any dotted suffix again',
     "path": 'app/tasks.py',
     "old": '    stem = base if (base and _REAL_EXT.fullmatch(ext)) else name',
     "new": '    stem = base or name',
     "target": _AMC,
     "expect": 'test_only_a_real_extension_is_stripped[dotted-title]'},
    {"name": 'audit3 meta_write stops passing cancel',
     "path": 'app/tasks.py',
     "old": 'cover_path=cover_path, cancel=cancel)',
     "new": 'cover_path=cover_path)',
     "target": "tests/test_phase2b.py",
     "expect": 'test_mute_and_metadata_accept_cancel'},
    {"name": 'audit3 rar goes back to 7z extraction',
     "path": 'app/processing.py',
     "old": '    if _is_rar(path):\n        # همان سقف و همان kill',
     "new": '    if False:\n        # همان سقف و همان kill',
     "target": _RAR,
     "expect": 'test_a_compressed_rar_extracts'},
    {"name": 'audit3 every tool failure is called ffmpeg again',
     "path": 'app/processing.py',
     "old": '        tool = os.path.basename(cmd[0]) or "process"',
     "new": '        tool = "ffmpeg"',
     "target": _RAR,
     "expect": 'test_a_failing_tool_is_named_in_the_error'},
    {"name": 'audit3 unrar listing keeps directories',
     "path": 'app/processing.py',
     "old": '            if "D" not in m.group(2):',
     "new": '            if True:',
     "target": _RAR,
     "expect": 'test_the_unrar_listing_parser'},
    {"name": 'audit3 download workdir shared by every pick of a menu',
     "path": 'app/tasks_download.py',
     "old": '    workdir = os.path.join(settings.work_dir, f"dl-{ref}-{secrets.token_hex(4)}")',
     "new": '    workdir = os.path.join(settings.work_dir, f"dl-{ref}")',
     "target": _WDJ,
     "expect": 'test_two_picks_from_one_menu_do_not_share_a_workdir'},
    {"name": 'audit3 heavy-model slot freed when the await is abandoned',
     "path": 'app/processing.py',
     "old": '    except BaseException:\n        stop.set()                    # لغوِ جاب',
     "new": '    except BaseException:\n        sem.release()\n        stop.set()                    # لغوِ جاب',
     "target": _HTC,
     "expect": 'test_a_cancelled_job_keeps_the_slot_until_its_thread_ends[transcribe]'},
    {"name": 'audit3 heavy-model wait ignores the cancel button',
     "path": 'app/processing.py',
     "old": '            if cancel is not None and await cancel():',
     "new": '            if False:',
     "target": _HTC,
     "expect": 'test_the_cancel_button_stops_the_wait[transcribe]'},
    {"name": 'audit3 whisper stops checking between segments',
     "path": 'app/processing.py',
     "old": '        if stop is not None and stop.is_set():\n            raise _Stopped()\n        done.append(seg)',
     "new": '        done.append(seg)',
     "target": _HTC,
     "expect": 'test_real_transcribe_stops_between_segments'},
    {"name": 'audit3 yt-dlp downloads the whole playlist again',
     "path": 'app/downloader.py',
     "old": '    flags = ["--no-warnings", "--no-playlist", "--playlist-items", "1"]',
     "new": '    flags = ["--no-warnings", "--no-playlist"]',
     "target": _PLC,
     "expect": 'test_a_playlist_link_downloads_one_item'},
    {"name": 'audit3 probe describes the playlist shell, not its item',
     "path": 'app/downloader.py',
     "old": '    if data.get("_type") in ("playlist", "multi_video"):',
     "new": '    if False:',
     "target": _PLC,
     "expect": 'test_normalize_probe_unwraps_a_single_entry_playlist'},
    {"name": 'audit3 gallery-dl pulls a whole profile again',
     "path": 'app/downloader.py',
     "old": '           "--range", f"1-{GALLERY_MAX_ITEMS}"]',
     "new": '           ]',
     "target": _PLC,
     "expect": 'test_a_gallery_link_is_capped'},
    # ── فاز ۴: پیام/اعتبارسنجی/امنیتیِ پایین‌تر ─────────────────────────
    {"name": 'audit4 converted file keeps its old mime',
     "path": 'app/tasks.py',
     "old": '                    file.mime = message_media_mime(sent, file.name)\n',
     "new": '',
     "target": _MIM,
     "expect": 'test_a_converted_file_carries_the_new_mime'},
    {"name": 'audit4 downloaded files get no mime again',
     "path": 'app/tasks_download.py',
     "old": '        f.mime = message_media_mime(sent, f.name)\n',
     "new": '',
     "count": 2,
     "target": _MIM,
     "expect": 'test_a_downloaded_file_has_a_mime'},
    {"name": 'audit4 gateway serves a mime-less row as attachment',
     "path": 'app/gateway.py',
     "old": '    mime = file.mime or mime_from_name(name)\n',
     "new": '    mime = file.mime\n',
     "target": _MIM,
     "expect": 'test_an_old_row_without_mime_streams_by_name[video]'},
    {"name": 'audit4 langpack review no longer marks default values',
     "path": 'app/langpack.py',
     "old": '        if defaults is not None and value == defaults.get(key):\n            rv.defaulted.append(key)\n',
     "new": '',
     "target": _LPD,
     "expect": 'test_an_unchanged_round_trip_overrides_nothing'},
    {"name": 'audit4 panel import writes every pack value again',
     "path": 'app/admin_web.py',
     "old": '    await textstore.set_texts(code, rv.overrides, replace=replace, clear=rv.defaulted)',
     "new": '    await textstore.set_texts(code, rv.entries, replace=replace)',
     "target": _LPP,
     "expect": 'test_an_unchanged_round_trip_writes_no_rows'},
    {"name": 'audit4 merge import ignores keys reset to default',
     "path": 'app/textstore.py',
     "old": '            for key in clear:\n                row = existing.pop(key, None)\n                if row is not None:\n                    await s.delete(row)\n',
     "new": '',
     "target": _LPP,
     "expect": 'test_setting_a_key_back_to_default_removes_its_override'},
    {"name": 'audit4 settings read-through fill clobbers a concurrent save',
     "path": 'app/settings_store.py',
     "old": '            await self.r.set(_PREFIX + key, _MISSING if val is None else val,\n                             nx=True, ex=_CACHE_TTL)\n',
     "new": '            await self.r.set(_PREFIX + key, _MISSING if val is None else val,\n                             ex=_CACHE_TTL)\n',
     "target": _SCR,
     "expect": 'test_a_cold_read_does_not_bury_a_concurrent_save'},
    {"name": 'audit4 settings cache entries never expire again',
     "path": 'app/settings_store.py',
     "old": '_CACHE_TTL = 3600\n',
     "new": '_CACHE_TTL = None\n',
     "target": _SCR,
     "expect": 'test_every_cache_entry_expires[missing]'},
    {"name": 'audit4 gateway node back to the default 100-connection pool',
     "path": 'app/gateway_node.py',
     "old": '_UPSTREAM_LIMIT = 0\n',
     "new": '_UPSTREAM_LIMIT = 100\n',
     "target": _GNP,
     "expect": 'test_the_hundred_and_first_stream_is_served'},
    {"name": 'audit4 gateway node waits on a stalled client forever',
     "path": 'app/gateway_node.py',
     "old": '        await asyncio.wait_for(resp.write(chunk), _CLIENT_STALL)\n',
     "new": '        await resp.write(chunk)\n',
     "target": _GNP,
     "expect": 'test_a_stalled_client_releases_its_upstream'},
    {"name": 'audit4 ambiguous keywords match free text again',
     "path": 'app/safety.py',
     "old": '    for s in STRONG_TOKENS + (HOST_STRONG_TOKENS if host else ()):\n',
     "new": '    for s in STRONG_TOKENS + HOST_STRONG_TOKENS:\n',
     "target": _SKW,
     "expect": 'test_mainstream_titles_are_not_blocked[xxxtentacion]'},
    {"name": 'audit4 a trailing dot dodges the domain list',
     "path": 'app/safety.py',
     "old": '.lower().strip().rstrip(".")\n',
     "new": '.lower().strip()\n',
     "target": _SKW,
     "expect": 'test_a_base_domain_cannot_be_dodged[trailing_dot]'},
    {"name": 'audit4 fullwidth letters dodge the domain list',
     "path": 'app/safety.py',
     "old": '    h = unicodedata.normalize("NFKC", host or "")',
     "new": '    h = (host or "")',
     "target": _SKW,
     "expect": 'test_a_base_domain_cannot_be_dodged[fullwidth]'},
    {"name": 'audit4 panel domain lists skip host normalisation',
     "path": 'app/safety.py',
     "old": '        part = norm_host(part.strip("."))\n',
     "new": '        part = part.strip(".").lower()\n',
     "target": _SKW,
     "expect": 'test_the_admin_lists_are_normalised_like_urls'},
    {"name": 'audit4 a clamd ERROR reply is reported as infected again',
     "path": 'app/security.py',
     "old": '    if status not in ("OK", "FOUND"):\n',
     "new": '    if status is None:\n',
     "target": _CLV,
     "expect": 'test_a_clamd_failure_is_not_reported_as_infected[clamd_error]'},
    {"name": 'audit4 prefs redirect accepts control characters again',
     "path": 'app/admin_web.py',
     "old": '    if any(c <= " " or c == "\\x7f" for c in value):\n        return "/"\n',
     "new": '',
     "target": _PRF,
     "expect": 'test_a_control_character_cannot_smuggle_a_foreign_host[tab]'},
    {"name": 'audit4 max_file_mb zero blocks every op again',
     "path": 'app/routers/ops.py',
     "old": '    return bool(size and cap > 0 and size > cap * 1024 * 1024)\n',
     "new": '    return bool(size and size > cap * 1024 * 1024)\n',
     "target": _MFZ,
     "expect": 'test_zero_means_no_cap'},
    {"name": "audit4 a blocked owner's public link is served again",
     "path": 'app/gateway.py',
     "old": '    if blocked:\n        return None\n',
     "new": '',
     "target": _LEX,
     "expect": 'test_a_blocked_owners_link_is_dead'},
    {"name": 'audit4 public links never expire again',
     "path": 'app/gateway.py',
     "old": '    if link_expired(file.dl_token_at, days):\n        return None\n',
     "new": '',
     "target": _LEX,
     "expect": 'test_an_expired_link_is_dead'},
    {"name": 'audit4 asking again revives an expired token',
     "path": 'app/routers/ops.py',
     "old": '    if not file.dl_token or link_expired(file.dl_token_at, days, now):\n',
     "new": '    if not file.dl_token:\n',
     "target": _LEX,
     "expect": 'test_asking_again_rotates_an_expired_token'},
    {"name": 'audit4 text validation accepts attribute/spec placeholders again',
     "path": 'app/textstore.py',
     "old": '    bad = unsafe_placeholder(value)\n    if bad:\n',
     "new": '    bad = unsafe_placeholder(value)\n    if False:\n',
     "target": _TPH,
     "expect": 'test_validate_rejects_anything_but_a_bare_name[attr]'},
    {"name": 'audit4 a stored unsafe override renders again',
     "path": 'app/i18n.py',
     "old": '    if textstore.unsafe_placeholder(template):\n        return None\n',
     "new": '',
     "target": _TPH,
     "expect": 'test_a_stored_unsafe_override_falls_back_to_the_default[attr]'},
    {"name": 'audit4 a cookie paste cut at the Telegram limit is saved again',
     "path": 'app/routers/admin.py',
     "old": '    if len(message.text.encode("utf-16-le")) // 2 >= _TG_TEXT_MAX:\n',
     "new": '    if False:\n',
     "target": _CKP,
     "expect": 'test_a_paste_at_the_telegram_limit_is_not_saved'},
    {"name": 'audit4 the paste limit counts code points not UTF-16 units',
     "path": 'app/routers/admin.py',
     "old": '    if len(message.text.encode("utf-16-le")) // 2 >= _TG_TEXT_MAX:\n',
     "new": '    if len(message.text) >= _TG_TEXT_MAX:\n',
     "target": _CKP,
     "expect": 'test_the_limit_is_counted_in_utf16_units'},
    {"name": 'audit4 deleted posts count against the exit again',
     "path": 'app/tasks_download.py',
     "old": '    return kind in _YT_NOT_ACCOUNT_KINDS or _content_error(msg)\n',
     "new": '    return kind in _YT_NOT_ACCOUNT_KINDS\n',
     "target": _EXS,
     "expect": 'test_deleted_posts_do_not_mark_the_exit_blocked[fetch]'},
    {"name": 'audit4 CMYK and 16-bit images skip normalisation again',
     "path": 'app/processing.py',
     "old": '    return _to_8bit(ImageOps.exif_transpose(Image.open(path)))\n',
     "new": '    return ImageOps.exif_transpose(Image.open(path))\n',
     "target": _IMM,
     "expect": 'test_a_cmyk_jpeg_converts[png]'},
    {"name": 'audit4 enhance drops transparency again',
     "path": 'app/processing.py',
     "old": '    if alpha is not None:\n        img.putalpha(alpha)\n',
     "new": '',
     "target": _IMM,
     "expect": 'test_enhance_keeps_transparency[png]'},
    {"name": 'audit4 16-bit images are clipped instead of scaled',
     "path": 'app/processing.py',
     "old": '            img = img.point(lambda v: v * k)\n',
     "new": '            pass\n',
     "target": _IMM,
     "expect": 'test_a_16bit_image_keeps_its_tones[jpg]'},
    {"name": 'audit4 old strikes stay in the window forever again',
     "path": 'app/safety.py',
     "old": '        pipe.zremrangebyscore(k, "-inf", now - STRIKE_WINDOW)\n',
     "new": '',
     "target": _STW,
     "expect": 'test_old_strikes_fall_out_of_the_window'},
    {"name": 'audit4 raw user text in the admin report again',
     "path": 'app/routers/download.py',
     "old": "{escape((message.text or '')[:80])}",
     "new": "{(message.text or '')[:80]}",
     "target": _ARE,
     "expect": 'test_the_users_text_is_escaped_in_the_admin_report'},
    {"name": 'audit4 the block reason is not escaped again',
     "path": 'app/safety.py',
     "old": '{_html_escape(reason)}',
     "new": '{reason}',
     "target": _ARE,
     "expect": 'test_the_reason_is_escaped'},
    {"name": 'audit4 a cancelled remux leaves ffmpeg running again',
     "path": 'app/downloader.py',
     "old": '        if proc is not None:\n            _P.kill_orphan(proc)\n        if not isinstance(exc, Exception):\n',
     "new": '        if not isinstance(exc, Exception):\n',
     "target": _RMX,
     "expect": 'test_a_cancelled_remux_kills_ffmpeg'},
    {"name": 'janitor: the bot session dir is swept too',
     "path": 'app/tg_janitor.py',
     "old": '        if depth < 2:\n            continue\n',
     "new": '        if depth < 1:\n            continue\n',
     "target": 'tests/test_tg_janitor.py',
     "expect": 'test_the_bot_session_is_never_a_candidate_however_old'},
    {"name": 'janitor: the floor rule ignores the guard window',
     "path": 'app/tg_janitor.py',
     "old": '                if mtime >= guard:\n                    break',
     "new": '                if False:\n                    break',
     "target": 'tests/test_tg_janitor.py',
     "expect": 'test_the_floor_never_touches_the_guard_window'},
    {"name": 'janitor: the floor rule does not stop at the floor',
     "path": 'app/tg_janitor.py',
     "old": '                    if free_fn(root) >= floor:\n                        break\n',
     "new": '',
     "target": 'tests/test_tg_janitor.py',
     "expect": 'test_below_the_floor_the_oldest_go_first_and_it_stops_at_the_floor'},
    {"name": 'janitor: the age rule ignores the guard window',
     "path": 'app/tg_janitor.py',
     "old": '        cutoff = min(now - max_age_hours * 3600, guard)',
     "new": '        cutoff = now - max_age_hours * 3600 + 3600',
     "target": 'tests/test_tg_janitor.py',
     "expect": 'test_a_file_written_in_the_guard_window_survives_a_tiny_max_age'},
    {"name": 'janitor: a broken settings store kills the sweep',
     "path": 'app/tg_janitor.py',
     "old": '    except Exception as exc:  # noqa: BLE001\n        log.warning("janitor: reading',
     "new": '    except asyncio.TimeoutError as exc:  # noqa: BLE001\n        log.warning("janitor: reading',
     "target": 'tests/test_tg_janitor.py',
     "expect": 'test_a_broken_settings_store_falls_back_to_the_defaults'},
    {"name": 'janitor: the settings read is unbounded',
     "path": 'app/tg_janitor.py',
     "old": '        return await asyncio.wait_for(settings_store.get_int(key, default), _SETTINGS_TIMEOUT)',
     "new": '        return await settings_store.get_int(key, default)',
     "target": 'tests/test_tg_janitor.py',
     "expect": 'test_a_hanging_settings_store_does_not_stall_the_sweep'},
    {"name": 'janitor: the service waits for a healthy database',
     "path": 'docker-compose.yml',
     "old": '    command: ["python", "-m", "app.tg_janitor"]\n',
     "new": '    command: ["python", "-m", "app.tg_janitor"]\n    depends_on:\n      postgres:\n        condition: service_healthy\n',
     "target": 'tests/test_tg_janitor.py',
     "expect": 'test_the_janitor_does_not_wait_for_a_healthy_database'},
    {"name": 'janitor: protected names are swept too',
     "path": 'app/tg_janitor.py',
     "old": '            if _protected(name):\n                continue\n',
     "new": '',
     "target": 'tests/test_tg_janitor.py',
     "expect": 'test_the_bot_session_is_never_a_candidate_however_old'},
    {"name": 'janitor: the bot gets a writable api dir',
     "path": 'docker-compose.yml',
     "old": '      - tg-bot-api-data:/var/lib/telegram-bot-api:ro\n      - ./cookies:/cookies     # نوشتنی',
     "new": '      - tg-bot-api-data:/var/lib/telegram-bot-api\n      - ./cookies:/cookies     # نوشتنی',
     "target": 'tests/test_tg_janitor.py',
     "expect": 'test_only_the_server_and_the_janitor_may_write_the_api_dir'},
    {"name": 'diag: the read-only tool gains a delete',
     "path": 'tools/tg_disk_diag.sh',
     "old": 'export TZ=UTC   # every time in UTC',
     "new": 'rm -f "$FS"; export TZ=UTC   # every time in UTC',
     "target": 'tests/test_tg_disk_diag.py',
     "expect": 'test_the_script_is_read_only'},
    {"name": 'diag: the per-day summary keys on the epoch instead of the day',
     "path": 'tools/tg_disk_diag.sh',
     "old": '{k=$3" "day($2); c[k]++',
     "new": '{k=$3" "$2; c[k]++',
     "target": 'tests/test_tg_disk_diag.py',
     "expect": 'test_the_report_counts_files_per_day_and_hour'},
    {"name": 'diag: the bot token is printed unmasked',
     "path": 'tools/tg_disk_diag.sh',
     "old": '} 2>&1 | mask > "$OUT"',
     "new": '} 2>&1 > "$OUT"',
     "target": 'tests/test_tg_disk_diag.py',
     "expect": 'test_the_bot_token_never_reaches_the_report'},
    {"name": 'diag: log grep without -a stops at the first NUL byte',
     "path": 'tools/tg_disk_diag.sh',
     "old": "grep -aE '→ [^ ]+:(run_screen|run_op|run_download)",
     "new": "grep -E '→ [^ ]+:(run_screen|run_op|run_download)",
     "target": 'tests/test_tg_disk_diag.py',
     "expect": 'test_a_nul_byte_in_the_logs_does_not_hide_later_jobs'},
    {"name": 'diag: a saved list is ignored and the empty directory is listed',
     "path": 'tools/tg_disk_diag.sh',
     "old": 'if [ -n "$FS_LIST" ]; then',
     "new": 'if false; then',
     "target": 'tests/test_tg_disk_diag.py',
     "expect": 'test_a_saved_list_stands_in_for_deleted_files'},

    # ── HTTPSِ خودکار (Caddy): گیتِ صدور، دامنهٔ لینک، IPِ کلاینت، نصب‌کننده ──
    # موردهای `tests/panel/` را با venvی اجرا کن که requirements-admin.txt هم دارد؛
    # موردِ «needs caddy» باینریِ caddy با نسخهٔ پین‌شده را روی PATH می‌خواهد (مثلِ CI).
    {"name": "https: the ask gate approves any name",
     "path": "app/admin_web.py",
     "old": "        allowed = name == settings_store.panel_domain()\n        if not allowed:",
     "new": "        allowed = bool(name)\n        if not allowed:",
     "target": "tests/panel/test_tls.py",
     "expect": "test_every_other_name_is_refused[stranger]"},
    {"name": "https: the panel domain waits on the settings store too",
     "path": "app/admin_web.py",
     "old": "        allowed = name == settings_store.panel_domain()\n        if not allowed:",
     "new": "        allowed = name == settings_store.panel_domain()\n        if True:",
     "target": "tests/panel/test_tls.py",
     "expect": "test_the_panel_domain_needs_neither_redis_nor_postgres"},
    {"name": "https: a hanging settings read holds the handshake",
     "path": "app/admin_web.py",
     "old": "link = await asyncio.wait_for(settings_store.link_domain(), _TLS_ASK_TIMEOUT)",
     "new": "link = await settings_store.link_domain()",
     "target": "tests/panel/test_tls.py",
     "expect": "test_a_hanging_settings_read_refuses_quickly"},
    {"name": "https: the gate compares the raw SNI",
     "path": "app/admin_web.py",
     "old": '    name = settings_store.normalize_domain(request.query.get("domain", "")) or ""',
     "new": '    name = request.query.get("domain", "")',
     "target": "tests/panel/test_tls.py",
     "expect": "test_the_comparison_is_on_the_canonical_name"},
    {"name": 'https: the /system page lost its certificate rows',
     "path": 'app/templates/system.html',
     "old": '      <tbody>{% for c in tls %}<tr>',
     "new": '      <tbody>{% for c in [] %}<tr>',
     "target": "tests/panel/test_tls.py",
     "expect": "test_the_card_shows_each_domain_and_its_certificate"},
    {"name": "https: the earlier-expiring certificate is shown",
     "path": "app/admin_web.py",
     "old": 'if best is None or exp > best["expires"]:',
     "new": 'if best is None or exp < best["expires"]:',
     "target": "tests/panel/test_tls.py",
     "expect": "test_of_two_issuers_the_later_expiry_wins"},
    {"name": "https: saving the link domain no longer requests its certificate",
     "path": "app/admin_web.py",
     "old": "        _schedule_tls_warm(request.app, domain)",
     "new": "        pass",
     "target": "tests/panel/test_tls.py",
     "expect": "test_saving_a_link_domain_requests_its_certificate_now"},
    {"name": "https: the warm-up handshake sends no SNI",
     "path": "app/admin_web.py",
     "old": "ssl=ctx, server_hostname=domain),",
     "new": "ssl=ctx, server_hostname=None),",
     "target": "tests/panel/test_tls.py",
     "expect": "test_the_warm_up_handshake_carries_the_domain_as_sni"},
    {"name": "https: cleanup leaves the warm-up task running",
     "path": "app/admin_web.py",
     "old": '    for key in (_POT_TASK, _TLS_WARM_TASK, _SVC_TASK):',
     "new": '    for key in (_POT_TASK, _SVC_TASK):',
     "target": "tests/panel/test_tls.py",
     "expect": "test_cleanup_cancels_a_pending_warm_up"},
    {"name": "client ip: X-Forwarded-For trusted from a public peer",
     "path": "app/admin_web.py",
     "old": "    if _is_internal_peer(peer):",
     "new": "    if True:",
     "target": "tests/panel/test_tls.py",
     "expect": "test_the_client_ip_trusts_forwarding_only_from_inside[public-peer]"},
    {"name": "client ip: X-Forwarded-For never trusted (the pre-Caddy form)",
     "path": "app/admin_web.py",
     "old": "    if _is_internal_peer(peer):",
     "new": "    if False:",
     "target": "tests/panel/test_tls.py",
     "expect": "test_two_clients_behind_caddy_get_two_login_buckets"},
    {"name": "client ip: the first forwarded entry, which the client wrote",
     "path": "app/admin_web.py",
     "old": 'request.headers.get("X-Forwarded-For", "").split(",")[-1].strip()',
     "new": 'request.headers.get("X-Forwarded-For", "").split(",")[0].strip()',
     "target": "tests/panel/test_tls.py",
     "expect": "test_the_client_ip_trusts_forwarding_only_from_inside[chain-last]"},
    {"name": "link domain: the panel domain is accepted as the link domain",
     "path": "app/settings_store.py",
     "old": "    if norm and norm == panel_domain():",
     "new": "    if False:",
     "target": "tests/test_link_domain.py",
     "expect": "test_the_link_domain_cannot_be_the_panel_domain"},
    {"name": "link domain: a port is silently dropped",
     "path": "app/settings_store.py",
     "old": 'p.scheme.lower() not in ("http", "https") or port is not None or p.username',
     "new": 'p.scheme.lower() not in ("http", "https") or p.username',
     "target": "tests/test_link_domain.py",
     "expect": "test_a_domain_that_cannot_get_a_certificate_is_refused[url-port]"},
    {"name": "link domain: a legacy Origin-certificate install is not warned",
     "path": "app/settings_store.py",
     "old": "    if norm and settings.tls_cert:",
     "new": "    if False:",
     "target": "tests/test_link_domain.py",
     "expect": "test_a_legacy_origin_certificate_install_is_told_to_reconfigure"},
    {"name": "link domain: links ignore it",
     "path": "app/routers/ops.py",
     "old": '    if domain:\n        return f"https://{domain}"',
     "new": '    if False:\n        return f"https://{domain}"',
     "target": "tests/test_link_domain.py",
     "expect": "test_the_link_domain_builds_https_links"},
    {"name": "installer: an unresolvable domain ends the install silently (first version)",
     "path": "install.sh",
     "old": "  ips=$(getent ahostsv4 \"$d\" 2>/dev/null | awk '{print $1}' | sort -u | tr '\\n' ' ' || true)",
     "new": "  ips=$(getent ahostsv4 \"$d\" 2>/dev/null | awk '{print $1}' | sort -u | tr '\\n' ' ')",
     "target": "tests/test_installer.py",
     "expect": "test_a_domain_that_does_not_resolve_yet_is_a_warning_not_a_silent_exit"},
    {"name": "installer: v4-mapped addresses read as AAAA records",
     "path": "install.sh",
     "old": "grep -v '^::ffff:' | ",
     "new": "",
     "target": "tests/test_installer.py",
     "expect": "test_a_domain_pointing_here_is_ok"},
    {"name": "installer: a certificate request is spent on a name that points elsewhere",
     "path": "install.sh",
     "old": '  if [[ "$DNS_STATE" == missing || "$DNS_STATE" == elsewhere ]]; then',
     "new": "  if false; then",
     "target": "tests/test_installer.py",
     "expect": "test_no_request_is_spent_on_a_name_that_does_not_point_here[missing]"},
    {"name": "installer: a domain install leaves the plain-HTTP panel public",
     "path": "install.sh",
     "old": '    ADMIN_BIND="127.0.0.1"',
     "new": '    ADMIN_BIND="0.0.0.0"',
     "target": "tests/test_installer.py",
     "expect": "test_a_domain_install_writes_https_and_keeps_the_plain_ports_local"},
    {"name": "installer: our own caddy reads as a port conflict on reconfigure",
     "path": "install.sh",
     "old": '  [[ -n "$($COMPOSE ps -q caddy 2>/dev/null || true)" ]] && return 0\n',
     "new": "",
     "target": "tests/test_installer.py",
     "expect": "test_a_reconfigure_with_our_own_caddy_running_is_not_a_conflict"},
    {"name": "installer: a reconfigure cannot remove the domain",
     "path": "install.sh",
     "old": '    [[ "$PANEL_DOMAIN" == "-" ]] && PANEL_DOMAIN=""\n',
     "new": "",
     "target": "tests/test_installer.py",
     "expect": "test_a_reconfigure_can_remove_the_domain"},
    {"name": "caddy: an empty PANEL_DOMAIN reaches Caddy",
     "path": "docker-compose.yml",
     "old": "      PANEL_DOMAIN: ${PANEL_DOMAIN:-panel.invalid}",
     "new": "      PANEL_DOMAIN: ${PANEL_DOMAIN-panel.invalid}",
     "target": "tests/test_caddy.py",
     "expect": "test_an_empty_panel_domain_is_replaced_before_caddy_sees_it"},
    {"name": "caddy: certificates do not survive a rebuild",
     "path": "docker-compose.yml",
     "old": "      - caddy-data:/data\n",
     "new": "",
     "target": "tests/test_caddy.py",
     "expect": "test_certificates_survive_a_rebuild"},
    {"name": "caddy: on-demand issuance without asking the panel",
     "path": "docker/caddy/Caddyfile",
     "old": "\t\task http://admin:8080/tls/ask\n",
     "new": "",
     "target": "tests/test_caddy.py",
     "expect": "test_every_name_is_issued_on_demand_and_only_after_asking_the_panel"},
    {"name": "caddy (needs caddy on PATH): the panel host has no default",
     "path": "docker/caddy/Caddyfile",
     "old": "\t@panel host {$PANEL_DOMAIN:panel.invalid}",
     "new": "\t@panel host {$PANEL_DOMAIN}",
     "target": "tests/test_caddy.py",
     "expect": "test_the_caddyfile_is_valid_for_the_pinned_caddy[unset]"},
    {"name": "caddy: CI stops installing the pinned caddy",
     "path": ".github/workflows/tests.yml",
     "old": 'base="https://github.com/caddyserver/caddy/releases/download/v${ver}"',
     "new": 'base="https://example.invalid/v${ver}"',
     "target": "tests/test_caddy.py",
     "expect": "test_the_caddy_validation_is_not_dead_weight"},

    # ── بازطراحیِ پنل (۲۰۲۶-۱۰): گاردهای تازهٔ همین کار ───────────────────────
    # هرکدام یک ادعای مشخص؛ کاری که بازطراحی اضافه کرد (لاگِ ادمین، گاردِ اکانتِ
    # ناشناخته، خروجِ فقط-POST، اسپرایت، `|safe`، کلیدِ همنامِ متدِ dict، حالتِ
    # strict، اجتماعِ پلتفرم‌ها، شدتِ یکسانِ گواهی) بدونِ یکی از این‌ها اثبات‌نشده بود.

    {'name': 'panel-actions: an unknown cookie account gets a ghost meta again',
     'path': 'app/admin_web.py',
     'old': '    names, _local = await ck_pool.list_names(redis)\n    return name if name in names else None',
     'new': '    return name',
     'target': _PAC,
     'expect': 'test_an_unknown_account_leaves_no_trace[toggle]'},

    {'name': 'panel-actions: replace resurrects a deleted account again',
     'path': 'app/admin_web.py',
     'old': '    names, _local = await ck_pool.list_names(redis)\n    return name if name in names else None',
     'new': '    return name',
     'target': _PAC,
     'expect': 'test_replacing_an_account_that_is_gone_does_not_resurrect_it'},

    {'name': "panel-actions: the account lookup asks the disk instead of the page's list",
     'path': 'app/admin_web.py',
     'old': '    names, _local = await ck_pool.list_names(redis)\n    return name if name in names else None',
     'new': '    return name if os.path.isfile(os.path.join(settings.cookies_dir, name)) else None',
     'target': _PAC,
     'expect': 'test_a_mirror_only_account_can_still_be_deleted'},

    {'name': 'panel-actions: a plain link signs the admin out again',
     'path': 'app/admin_web.py',
     'old': '    post("/logout", logout)',
     'new': '    add("/logout", logout)\n    post("/logout", logout)',
     'target': _PAC,
     'expect': 'test_a_plain_link_cannot_sign_the_admin_out'},

    {'name': 'panel-actions: a reset that cannot happen is reported as done',
     'path': 'app/admin_web.py',
     'old': '    if raw_lang not in langs:\n        raise _result("/texts", err=pt(ui, "tx.err.lang", l=raw_lang), **back)\n    if key not in langpack.TEXT_KEYS:\n        raise _result("/texts", err=pt(ui, "tx.err.key", k=key[:60]), **back)\n    if textstore.get_override(lang, key) is not None:',
     'new': '    if raw_lang in langs and key in langpack.TEXT_KEYS and textstore.get_override(lang, key) is not None:',
     'target': _PAC,
     'expect': 'test_a_reset_that_cannot_happen_is_not_reported_as_done[unknown-key]'},

    {'name': 'panel-actions: removing a node that is gone is silent again',
     'path': 'app/admin_web.py',
     'old': '            raise _result("/nodes", err=pt(_PREFS.get()[0], "nd.rm.none"))',
     'new': '            raise _result("/nodes")',
     'target': _PAC,
     'expect': 'test_removing_a_node_that_is_gone_says_so'},

    {'name': 'admin-log: a detail named like an `_audit` parameter is back',
     'path': 'app/admin_web.py',
     'old': '    await _audit(request, "cookie_cooldown", target=name, mode=action)',
     'new': '    await _audit(request, "cookie_cooldown", target=name, action=action)',
     'target': _ADL,
     'expect': 'test_resting_a_cookie_account_works_and_is_logged'},

    {'name': 'admin-log: … and the static guard sees the same call',
     'path': 'app/admin_web.py',
     'old': '    await _audit(request, "cookie_cooldown", target=name, mode=action)',
     'new': '    await _audit(request, "cookie_cooldown", target=name, action=action)',
     'target': _ADL,
     'expect': 'test_no_audit_call_passes_a_detail_named_like_a_parameter'},

    {'name': 'admin-log: a secret setting is logged in clear',
     'path': 'app/admin_web.py',
     'old': '        return "•••" if value not in ("", None) else ""',
     'new': '        return "" if value is None else str(value)',
     'target': _ADL,
     'expect': 'test_a_secret_setting_is_logged_as_dots_never_as_its_value'},

    {'name': 'admin-log: proxy credentials reach the log',
     'path': 'app/admin_web.py',
     'old': '    return _USERINFO.sub("•••@", s)[:200]',
     'new': '    return s[:200]',
     'target': _ADL,
     'expect': 'test_proxy_credentials_never_reach_the_log'},

    {'name': 'admin-log: an unchanged save writes a row per field',
     'path': 'app/admin_web.py',
     'old': '            if str(before) != str(val):',
     'new': '            if True:',
     'target': _ADL,
     'expect': 'test_an_unchanged_save_writes_no_log_rows'},

    {'name': 'icons: a symbol a Python map names leaves the sprite (static layer)',
     'path': 'app/static/icons.svg',
     'old': 'id="i-snowflake"',
     'new': 'id="i-snowflake-gone"',
     'target': _ICN,
     'expect': 'test_every_python_icon_exists[admin_web.py]'},

    {'name': 'icons: … and the rendered layer sees it on the page',
     'path': 'app/static/icons.svg',
     'old': 'id="i-snowflake"',
     'new': 'id="i-snowflake-gone"',
     'target': _ICN,
     'expect': 'test_every_icon_a_page_renders_exists[/cookies]'},

    {'name': 'templates: a `|safe` slips into a template',
     'path': 'app/templates/reports.html',
     'old': 'title="{{ e.msg }}">{{ e.msg }}</div>',
     'new': 'title="{{ e.msg }}">{{ e.msg|safe }}</div>',
     'target': _TGD,
     'expect': 'test_no_template_marks_data_as_safe[reports.html]'},

    {'name': 'templates: a dict key named like a dict method is read with a dot again',
     'path': 'app/templates/search.html',
     'old': "{% for x in g['items'] %}",
     'new': '{% for x in g.items %}',
     'target': _TGD,
     'expect': 'test_no_template_reads_a_dict_key_named_like_a_dict_method[search.html]'},

    {'name': 'strict: an optional key is read with a dot again',
     'path': 'app/templates/system.html',
     'old': "{{ f.ago(e.at) if e.get('at') else '—' }}",
     'new': "{{ f.ago(e.at) if e.at else '—' }}",
     'target': _STU,
     'expect': 'test_every_page_renders_strictly_with_data[/system]'},

    {'name': 'reports: a platform that only fails drops out of the list again',
     'path': 'app/panel_data.py',
     'old': '                 for p in sorted(set(plat_b) | set(ev_att),',
     'new': '                 for p in sorted(set(plat_b),',
     'target': _SCL,
     'expect': 'test_a_platform_that_only_fails_is_still_reported'},

    {'name': 'reports: a refused download counts as a failure',
     'path': 'app/panel_data.py',
     'old': '        if outcome in ("ok", "fail"):\n            ev_att[p] = ev_att.get(p, 0) + 1',
     'new': '        if outcome in ("ok", "fail", "refused"):\n            ev_att[p] = ev_att.get(p, 0) + 1',
     'target': _SCL,
     'expect': 'test_refused_downloads_are_not_failures'},

    {'name': 'system: a dead database reads as healthy',
     'path': 'app/admin_web.py',
     'old': '    rows = [{"key": "postgres", "icon": "database", "tint": "t6", "ok": pg_ok, "ms": pg_ms},',
     'new': '    rows = [{"key": "postgres", "icon": "database", "tint": "t6", "ok": True, "ms": pg_ms},',
     'target': _HLT,
     'expect': 'test_a_dead_database_is_reported_as_down'},

    {'name': 'tls: the alert goes back to its own expiry threshold',
     'path': 'app/admin_web.py',
     'old': '        elif _cert_sev(row):\n            alerts.append({"sev": _cert_sev(row), "icon": "lock",',
     'new': '        elif row.get("days", 99) <= 7:\n            alerts.append({"sev": "bad", "icon": "lock",',
     'target': 'tests/panel/test_tls.py',
     'expect': 'test_a_soon_expiring_certificate_is_a_warning'},

    {'name': 'tls: the warning window shrinks back to a week',
     'path': 'app/admin_web.py',
     'old': '_CERT_WARN_DAYS = 14',
     'new': '_CERT_WARN_DAYS = 7',
     'target': 'tests/panel/test_tls.py',
     'expect': 'test_the_card_and_the_alert_agree_on_severity'},

    {'name': 'login: Persian digits are no longer converted before comparing',
     'path': 'app/admin_web.py',
     'old': '    return re.sub(r"[\\s٬,]", "", F.ascii_digits(str(value or "")))[:64]',
     'new': '    return re.sub(r"[\\s٬,]", "", str(value or ""))[:64]',
     'target': _LRL,
     'expect': 'test_a_persian_digit_code_signs_in'},
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
