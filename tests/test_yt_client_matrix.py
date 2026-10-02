"""ابزارِ `tools/yt_client_matrix.py`: سنجشِ زندهٔ مسیرِ بی‌کوکیِ یوتیوب روی سرور.

این تست دربارهٔ **ابزارِ سنجش** است نه کدِ تولید، و دلیلش همان درسِ
`spotify_query_probe`: عددی که این ابزار می‌دهد تصمیمِ فازِ ۲ (probeِ بی‌کوکی،
کلیدِ `player_client`) را می‌سازد، و ابزاری که جوابِ غلطِ مطمئن بدهد از نبودنش
بدتر است.

**سه تله که با اجرا پیدا شد، نه با خواندنِ ابزار** — هر سه در نسخهٔ اولِ خودِ
همین ابزار بودند و هر سه این‌جا با **خودِ** yt-dlp بازتولید می‌شوند:

  1. کلاینتی که نسخه نمی‌شناسد بی‌صدا با **پیش‌فرض** جایگزین می‌شود و فقط یک
     WARNING می‌دهد (`YoutubeIE._get_requested_clients`). 2026.07.04 — نسخهٔ
     فعلیِ تولید — اصلاً `visionos` ندارد، پس ردیفِ «visionos» روی نسخهٔ فعلی در
     واقع `android_vr,web_safari` را می‌سنجید. نسخهٔ اول `--no-warnings` داشت
     (همان پرچمِ `_common_flags`) و دقیقاً همان WARNING را می‌بلعید.
  2. شکستِ دانلودِ تکه‌ای (HLS/DASH) `ERROR: \\r[download] Got error: …` است
     (`FileDownloader.report_retry`)؛ `splitlines()` آن را به «ERROR:»ِ خالی و
     متنی بی‌برچسب می‌شکند. **همین باگ در `downloader._stderr_summary`ِ تولید
     هم بود** و آن‌جا هم رفع شد (`test_youtube_error_kinds`).
  3. `subprocess.run(text=True)` پیش از هر چیز `\\r` را `\\n` می‌کند، پس رفعِ
     (۲) بدونِ خواندنِ بایت بی‌اثر می‌ماند — فقط تستِ انتها‌به‌انتها با زیرفرایندِ
     واقعی این را می‌بیند.

به‌علاوه: «ok» یعنی بایتِ واقعی (استخراجِ موفق + ۴۰۳ِ دانلود «ok» نیست)؛ ابزار
عمداً `app` را import نمی‌کند (روی ایمیجِ فعلی هم باید اجرا شود) پس نشانه‌ها و
قالبِ کلیدِ شمارنده کپیِ دوم‌اند و برابری‌شان **کشف‌محور** با تولید سنجیده
می‌شود؛ و ارکستراسیون (نسخهٔ تکراری، کلاینتِ ناشناخته، محدودیتِ نرخ).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import textwrap
import time
import types

import pytest

from app import downloader as D
from app import tasks_download as TD
from tests.yt_errors import (
    AGE, API_403, BOT, FRAG_403, GVS_403, MEMBERS, PRIVATE, RATE, RELOAD)

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "yt_client_matrix.py"


def _load():
    """`tools/` پکیج نیست — همان الگوی `test_spotify_query_probe`."""
    spec = importlib.util.spec_from_file_location("yt_client_matrix", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()


# ── ۰) روی ایمیجِ فعلی اجرا می‌شود ───────────────────────────────────────────
def _imports(tree: ast.AST) -> list[tuple[str, bool]]:
    """(ریشهٔ ماژول، سطحِ بالا؟) برای هر import — AST، پس کامنت شمرده نمی‌شود."""
    top = {id(n) for n in tree.body}
    out: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name.split(".")[0], id(node) in top) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            root = "." if node.level else (node.module or "").split(".")[0]
            out.append((root, id(node) in top))
    return out


def test_the_tool_needs_nothing_but_the_standard_library():
    """ابزار باید **قبل از** استقرار روی ایمیجِ فعلی اجرا شود، پس `app` ممنوع است.

    `redis` تنها استثناست و فقط تنبل (داخلِ `_stats`): در `requirements.txt`ِ
    پایه است، پس در هر ایمیجِ download-worker هست.
    """
    imports = _imports(ast.parse(TOOL.read_text(encoding="utf-8")))
    top = {m for m, is_top in imports if is_top}
    lazy = {m for m, is_top in imports if not is_top}
    stdlib = set(sys.stdlib_module_names)
    assert len(top) >= 5, top                    # کنترل: پیمایش واقعاً import می‌بیند
    assert top <= stdlib, top - stdlib
    assert lazy <= stdlib | {"redis"}, lazy - stdlib
    assert "redis" in lazy and "redis" not in top
    assert not ({"app", "."} & (top | lazy))


# ── ۱) تلهٔ کلاینتِ ناشناخته، با خودِ yt-dlp ─────────────────────────────────
def _requested_clients(client: str) -> tuple[list[str], list[str], set[str]]:
    """همان تابعی که yt-dlp برای `player_client` صدا می‌زند — بدونِ شبکه."""
    from yt_dlp import YoutubeDL

    warnings: list[str] = []

    class _Log:
        def debug(self, msg):
            pass

        info = debug

        def warning(self, msg):
            warnings.append(msg)

        error = warning

    ydl = YoutubeDL({"extractor_args": {"youtube": {"player_client": [client]}},
                     "logger": _Log(), "quiet": True})
    ie = ydl.get_info_extractor("Youtube")
    ie.initialize()
    got = ie._get_requested_clients("https://www.youtube.com/watch?v=jNQXAC9IVRw", {}, False)
    defaults = {*ie._DEFAULT_CLIENTS, *ie._DEFAULT_JSLESS_CLIENTS}
    return list(got), warnings, defaults


def test_yt_dlp_silently_swaps_an_unknown_client_for_the_defaults():
    """خودِ تله، روی نسخهٔ تولید: کلاینتِ ناشناخته → پیش‌فرض، فقط با یک WARNING."""
    got, warnings, defaults = _requested_clients("no_such_client")
    assert got and set(got) <= defaults, got
    assert any('skipping unsupported client "no_such_client"' in w.lower()
               for w in warnings), warnings


def test_a_known_client_is_not_swapped():
    """کنترلِ معکوس: بدونِ این، تستِ بالا با yt-dlpی که *همه‌چیز* را به پیش‌فرض
    برگرداند هم سبز می‌ماند."""
    got, warnings, _ = _requested_clients("web_embedded")
    assert got == ["web_embedded"]
    assert not any("unsupported client" in w.lower() for w in warnings)


def test_a_run_for_a_client_that_never_ran_is_not_ok():
    """استخراج و دانلود «موفق» بودند — ولی برای کلاینتِ پیش‌فرض. «ok» دروغ بود."""
    _, warnings, _ = _requested_clients("no_such_client")
    stderr = "\n".join(f"WARNING: {w}" for w in warnings)
    assert M.classify(0, stderr, True, True) == "unsupported"
    assert M.classify(0, "", True, True) == "ok"     # کنترل: بدونِ WARNING همان ok


def test_the_unsupported_markers_are_yt_dlp_s_own_text():
    """هر دو نشانه در سورسِ خودِ yt-dlp هست. دومی («بدونِ پشتیبانیِ کوکی»، مثلِ
    `visionos` با کوکی) بدونِ کوکیِ لاگینِ واقعی اجراشدنی نیست، پس روی متن."""
    import yt_dlp.extractor.youtube._video as V
    src = pathlib.Path(V.__file__).read_text(encoding="utf-8").lower()
    for marker in M._UNSUPPORTED:
        assert marker in src, marker


def test_the_tool_keeps_the_warnings_production_hides():
    """فرقِ **عمدی** با تولید — بدونش WARNINGِ بالا هرگز به ابزار نمی‌رسید."""
    cmd = M.build_cmd(["yt-dlp"], "u", "visionos", "/o", None, None)
    assert "--no-warnings" not in cmd
    assert "--no-warnings" in D._common_flags({})    # کنترل: تولید واقعاً دارد


# ── ۲) خواندنِ نتیجهٔ یک خانه ────────────────────────────────────────────────
@pytest.mark.parametrize("msg,outcome", [
    (BOT, "bot_check"), (AGE, "age_gate"), (PRIVATE, "private"),
    (MEMBERS, "members_only"), (RELOAD, "page_reload"), (RATE, "rate_limit"),
    (GVS_403, "http_403"), (FRAG_403, "http_403"), (API_403, "http_403"),
], ids=["bot", "age", "private", "members", "reload", "rate", "gvs403", "frag403", "api403"])
def test_real_yt_dlp_errors_are_read_right(msg, outcome):
    """`age`/`private` همان `--cookies`ی را دارند که تولید را گول می‌زد — این‌جا نه.
    `api403` عمداً `http_403` است (تولید آن را جدا می‌کند؛ برای سنجش هر ۴۰۳ی یعنی
    «این کلاینت از این‌جا کار نمی‌کند»)."""
    assert M.classify(1, msg, True, False) == outcome


def test_ok_needs_real_bytes_not_just_extraction():
    assert M.classify(0, "", True, True) == "ok"
    assert M.classify(0, "", True, False) != "ok"    # استخراج شد، بایتی نیامد
    assert M.classify(0, "", False, True) != "ok"    # فایلِ بی‌JSON: نمی‌دانیم چه سنجیدیم


def test_a_timeout_is_its_own_outcome():
    assert M.classify(None, "", False, False) == "timeout"


def test_the_final_error_wins_over_an_earlier_warning():
    """ساختگی (نه ضبط‌شده): یک کلاینت هشدارِ bot-check بدهد و دیگری استخراج کند و
    در دانلودِ تکه‌ای ۴۰۳ بخورد. پیش از رفعِ `\\r` خطِ ERROR خالی بود و ترتیبِ
    `_HINTS` (bot-check اول) کلِ خانه را bot-check می‌خواند."""
    stderr = "WARNING: [youtube] abc: Sign in to confirm you’re not a bot\n" + FRAG_403
    assert M.classify(1, stderr, True, False) == "http_403"
    assert "HTTP Error 403" in M._last_error(stderr)


def test_a_hint_outside_the_error_line_is_still_read():
    """نشانه فقط وقتی از کلِ stderr خوانده می‌شود که خطِ ERROR چیزی نگوید."""
    stderr = "WARNING: The page needs to be reloaded.\nERROR: [youtube] abc: odd failure"
    assert M.classify(1, stderr, False, False) == "page_reload"
    assert M.classify(1, "ERROR: [youtube] abc: odd failure", False, False) == "other"


# ── ۳) کپیِ دومِ نشانه‌ها برابرِ تولید می‌ماند ───────────────────────────────
_KIND_TO_OUTCOME = {
    D.YT_BOT_CHECK: "bot_check", D.YT_AGE_GATE: "age_gate", D.YT_PRIVATE: "private",
    D.YT_MEMBERS: "members_only", D.YT_RELOAD: "page_reload",
    D.YT_RATE_LIMIT: "rate_limit", D.YT_GVS_403: "http_403",
}
_PROD_HINTS = [(kind, hint) for kind, hints in D._YT_KIND_HINTS for hint in hints]
_TOOL_HINTS = [(o, h) for o, hints in M._HINTS for h in hints
               if o in set(_KIND_TO_OUTCOME.values()) - {"http_403"}]


def test_every_production_kind_has_a_tool_outcome():
    """کشف‌محور: نوعِ تازه در تولید این را قرمز می‌کند تا ابزار هم تصمیم بگیرد."""
    assert {kind for kind, _ in D._YT_KIND_HINTS} == set(_KIND_TO_OUTCOME)
    assert set(_KIND_TO_OUTCOME.values()) <= set(M.OUTCOMES)


@pytest.mark.parametrize("kind,hint", _PROD_HINTS,
                         ids=[f"{k}-{i}" for i, (k, _) in enumerate(_PROD_HINTS)])
def test_each_production_hint_reads_the_same_in_the_tool(kind, hint):
    assert M.classify(1, f"ERROR: [youtube] abc: {hint}", False, False) \
        == _KIND_TO_OUTCOME[kind]


@pytest.mark.parametrize("outcome,hint", _TOOL_HINTS,
                         ids=[f"{o}-{i}" for i, (o, _) in enumerate(_TOOL_HINTS)])
def test_each_tool_hint_means_the_same_in_production(outcome, hint):
    """جهتِ برعکس — به‌جز `http_403` که عمداً گسترده‌تر است (بالا)."""
    back = {v: k for k, v in _KIND_TO_OUTCOME.items()}
    assert D.youtube_error_kind(f"ERROR: [youtube] abc: {hint}") == back[outcome]


# ── ۴) خطِ فرمانِ یک خانه ────────────────────────────────────────────────────
def test_a_cell_really_downloads_a_little():
    """بدونِ `--no-simulate`، `-j` شبیه‌سازی می‌کند و هیچ خانه‌ای «ok» نمی‌شد."""
    cmd = M.build_cmd(["yt-dlp"], "https://y/v", "default", "/o", None, None)
    assert {"-j", "--no-simulate", "--test"} <= set(cmd)
    assert cmd[-1] == "https://y/v"
    assert "--test" not in M.build_cmd(["yt-dlp"], "u", "default", "/o", None, None, full=True)


def test_default_means_no_player_client_and_a_name_means_exactly_that():
    assert not any("player_client" in a for a in
                   M.build_cmd(["yt-dlp"], "u", "default", "/o", None, None))
    cmd = M.build_cmd(["yt-dlp"], "u", "web_embedded", "/o", None, None)
    assert cmd[cmd.index("youtube:player_client=web_embedded") - 1] == "--extractor-args"


def test_the_pot_argument_is_the_one_production_sends():
    prod = D._common_flags({"pot_provider": "http://pot:4416"})
    i = prod.index("--extractor-args")
    cmd = M.build_cmd(["yt-dlp"], "u", "default", "/o", "http://pot:4416", None)
    j = cmd.index(prod[i + 1])
    assert cmd[j - 1:j + 1] == prod[i:i + 2]
    assert not any(a.startswith("youtubepot") for a in
                   M.build_cmd(["yt-dlp"], "u", "default", "/o", None, None))


def test_cookies_and_format_are_passed_through():
    cmd = M.build_cmd(["yt-dlp"], "u", "web", "/o", None, "/tmp/c.txt", fmt="bv*[height<=720]")
    assert cmd[cmd.index("--cookies") + 1] == "/tmp/c.txt"
    assert cmd[cmd.index("-f") + 1] == "bv*[height<=720]"
    assert "--cookies" not in M.build_cmd(["yt-dlp"], "u", "web", "/o", None, None)


# ── ۵) یک خانهٔ واقعی با زیرفرایندِ واقعی ────────────────────────────────────
_STUB = r'''
import json, os, sys, time
argv = sys.argv[1:]
mode = os.environ["STUB_MODE"]
out = argv[argv.index("-o") + 1]
ck = argv[argv.index("--cookies") + 1] if "--cookies" in argv else ""
with open(os.environ["STUB_LOG"], "w") as fh:
    json.dump({"argv": argv, "outdir": os.path.dirname(out), "cookie": ck,
               "cookie_text": open(ck).read() if ck else ""}, fh)
if mode == "hang":                  # هرگز خودش تمام نمی‌شود — «timeout» فقط یعنی کُشتن
    while True:
        time.sleep(1)
if mode == "unsupported":
    sys.stderr.write('WARNING: [youtube] Skipping unsupported client "visionos"\n')
print(json.dumps({"id": "abc", "format_id": "140",
                  "formats": [{"format_id": "18", "height": 360},
                              {"format_id": "137", "height": 1080},
                              {"format_id": "140"}]}), flush=True)
target = out.replace("%(id)s", "abc").replace("%(ext)s", "m4a")
if mode in ("ok", "unsupported"):
    with open(target, "wb") as fh:
        fh.write(b"x" * 64)
    sys.exit(0)
if mode == "empty":
    open(target, "wb").close()
    sys.exit(0)
sys.stderr.buffer.write(os.environ["STUB_ERR"].encode() + b"\n")
sys.exit(1)
'''


@pytest.fixture
def stub(tmp_path, monkeypatch):
    path = tmp_path / "fake_ytdlp.py"
    path.write_text(textwrap.dedent(_STUB))
    log = tmp_path / "stub.json"

    def _cell(mode: str, *, err: str = "", cookies: str | None = None,
              timeout: float = 30, client: str = "web") -> dict:
        env = dict(os.environ, STUB_MODE=mode, STUB_LOG=str(log), STUB_ERR=err)
        return M.run_cell([sys.executable, str(path)], env, "abc", client, None,
                          cookies, timeout)

    _cell.log = lambda: json.loads(log.read_text())          # type: ignore[attr-defined]
    return _cell


def test_a_real_download_is_ok_and_reports_the_formats(stub):
    res = stub("ok")
    assert res["outcome"] == "ok", res
    assert (res["formats"], res["max_height"], res["format_id"]) == (3, 1080, "140")
    assert res["error"] == ""
    assert not os.path.exists(stub.log()["outdir"]), "پوشهٔ موقت باید پاک شود"


def test_extraction_without_bytes_is_not_ok(stub):
    res = stub("empty")
    assert res["outcome"] != "ok" and res["formats"] == 3


def test_a_download_403_after_extraction_is_a_403(stub):
    res = stub("fail", err=GVS_403)
    assert (res["outcome"], res["formats"]) == ("http_403", 3), res


def test_a_fragment_403_survives_the_pipe(stub):
    """تلهٔ (۳): از زیرفرایندِ واقعی. با `text=True` یا `splitlines()` خطای نهایی
    «ERROR:» می‌شد و هشدارِ bot-checkِ قبلی کلِ خانه را برچسب می‌زد."""
    err = "WARNING: [youtube] abc: Sign in to confirm you’re not a bot\n" + FRAG_403
    res = stub("fail", err=err)
    assert res["outcome"] == "http_403", res
    assert "HTTP Error 403" in res["error"], res["error"]


def test_an_unsupported_client_run_is_flagged_even_though_it_succeeded(stub):
    assert stub("unsupported")["outcome"] == "unsupported"


def test_a_hung_cell_times_out(stub):
    t0 = time.monotonic()
    res = stub("hang", timeout=1)
    assert res["outcome"] == "timeout"
    assert time.monotonic() - t0 < 15


def test_the_cookie_file_is_copied_not_handed_over(stub, tmp_path):
    """`/cookies` فقط‌خواندنی است و yt-dlp کوکی‌جار را بازنویسی می‌کند: نسخهٔ موقت
    به موتور می‌رود و بعد پاک می‌شود؛ اصل دست‌نخورده می‌ماند."""
    original = tmp_path / "cookies_youtube-a.txt"
    original.write_text("# Netscape HTTP Cookie File\n")
    res = stub("ok", cookies=str(original))
    seen = stub.log()
    assert res["cookie"] is True
    assert seen["cookie"] != str(original)
    assert seen["cookie_text"] == "# Netscape HTTP Cookie File\n"
    assert not os.path.exists(seen["cookie"])
    assert original.read_text() == "# Netscape HTTP Cookie File\n"


# ── ۶) جدولِ خلاصه ───────────────────────────────────────────────────────────
def _r(ver, client, outcome, h=0, secs=1.0, cookie=False):
    return {"version": ver, "client": client, "cookie": cookie, "outcome": outcome,
            "max_height": h, "secs": secs}


def test_the_summary_counts_each_outcome_per_version_and_client():
    s = M.summarize([
        _r("2026.08.19", "visionos", "ok", 1080, 3.0),
        _r("2026.08.19", "visionos", "ok", 720, 5.0),
        _r("2026.08.19", "visionos", "bot_check", 0, 2.0),
        _r("2026.08.19", "visionos", "ok", 360, 4.0, cookie=True),
        _r("2026.07.04", "visionos", "unsupported"),
    ])
    row = s[("2026.08.19", "anon", "visionos")]
    assert (row["n"], row["ok"], row["bot_check"]) == (3, 2, 1)
    assert (row["height"], row["secs"]) == (900, 3.0)     # ارتفاع فقط از خانه‌های ok
    assert s[("2026.08.19", "cookie", "visionos")]["ok"] == 1
    assert s[("2026.07.04", "anon", "visionos")]["unsupported"] == 1


def test_the_table_shows_only_the_outcomes_that_happened():
    text = M.render(M.summarize([_r("v", "web", "ok", 720), _r("v", "web", "bot_check")]))
    head = text.splitlines()[0]
    assert "bot_check" in head and "members_only" not in head
    assert "1/2" in text


# ── ۷) شمارنده‌های تولید ─────────────────────────────────────────────────────
async def test_the_stats_reader_parses_what_production_writes(redis):
    """کپیِ دومِ قالبِ کلید: همان کلیدی که `_ytauth_metric`ِ **واقعی** می‌نویسد."""
    await TD._ytauth_metric(redis, "youtube", "fetch", None, "ok")
    await TD._ytauth_metric(redis, "youtube", "fetch", None, D.YT_BOT_CHECK)
    await TD._ytauth_metric(redis, "youtube", "fetch", "cookies_youtube-a.txt", "ok")
    await TD._ytauth_metric(redis, "youtube", "probe", "cookies_youtube-a.txt", "ok")
    items = {k: int(await redis.get(k)) for k in await redis.keys("dlstat:ytauth:*")}

    stats = M.parse_stats(items)

    day = TD._today()
    assert stats == {day: {("fetch", "anon"): {"ok": 1, "bot_check": 1},
                           ("fetch", "cookie"): {"ok": 1},
                           ("probe", "cookie"): {"ok": 1}}}
    text = M.render_stats(stats)
    assert "ok 1/2 (50%)" in text and "bot_check=1" in text
    assert "fetch بی‌کوکی موفق: 1/2" in text


def test_other_counters_are_ignored():
    assert M.parse_stats({"dlstat:youtube:ok:20260926": 5,
                          "dlstat:probe:menu:20260926": 2,
                          "dlstat:ytauth:fetch:anon:ok": 1}) == {}
    assert "هیچ شمارنده‌ای نیست" in M.render_stats({})


# ── ۸) نسخهٔ دیگرِ yt-dlp ───────────────────────────────────────────────────
def test_the_current_image_version_needs_no_install():
    assert M.ytdlp_base("current")[0] == ["yt-dlp"]


def test_an_installed_version_is_reused_and_put_first_on_the_path(tmp_path, monkeypatch):
    (tmp_path / "ytdlp-2026.8.19" / "yt_dlp").mkdir(parents=True)
    monkeypatch.setattr(M.subprocess, "run",
                        lambda *a, **k: pytest.fail("نصبِ دوباره"))
    base, env = M.ytdlp_base("2026.8.19", root=str(tmp_path))
    assert base == [sys.executable, "-m", "yt_dlp"]
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "ytdlp-2026.8.19")


def test_a_new_version_is_installed_with_the_production_extra(tmp_path, monkeypatch):
    """`[default]` همان extraی `requirements-worker-dl.txt` است — بدونش
    `yt-dlp-ejs` نمی‌آید و خانه‌های `web` به دلیلِ غلط می‌افتادند."""
    seen: list[list[str]] = []
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **k: seen.append(cmd))
    M.ytdlp_base("2026.8.19", root=str(tmp_path))
    assert seen and seen[0][-1] == "yt-dlp[default]==2026.8.19"
    assert "--target" in seen[0]


# ── ۹) ارکستراسیون ───────────────────────────────────────────────────────────
@pytest.fixture
def orchestra(monkeypatch):
    """`main()` بدونِ زیرفرایند: هر خانه ثبت می‌شود و نتیجه‌اش از `plan` می‌آید."""
    calls: list[tuple[str, str, str]] = []
    labels = {"current": "2026.07.04", "2026.8.19": "2026.08.19"}
    plan: dict = {}

    def _run_cell(base, env, video, client, pot, cookies, timeout, fmt="ba/b", full=False):
        ver = base[0]
        calls.append((ver, client, video))
        outcome = plan.get((ver, client, video)) or plan.get((ver, client)) or "ok"
        return {"video": video, "client": client, "cookie": bool(cookies),
                "outcome": outcome, "secs": 0.1, "formats": 1, "format_id": "18",
                "max_height": 360, "error": "", "pot": pot}

    def _base(ver, root="/tmp"):
        if ver == "broken":
            raise subprocess.CalledProcessError(1, ["pip"])
        return [labels.get(ver, ver)], {}

    monkeypatch.setattr(M, "run_cell", _run_cell)
    monkeypatch.setattr(M, "ytdlp_base", _base)
    monkeypatch.setattr(M, "version_of", lambda base, env: base[0])
    monkeypatch.setattr(M, "time", types.SimpleNamespace(sleep=lambda s: None,
                                                         monotonic=time.monotonic))
    return types.SimpleNamespace(calls=calls, plan=plan, labels=labels)


_ARGS = ["--videos", "v1,v2,v3", "--clients", "default,visionos,web"]


def test_one_run_measures_every_client_on_every_video(orchestra):
    assert M.main([*_ARGS, "--versions", "2026.8.19"]) == 0
    assert len(orchestra.calls) == 9


def test_a_version_equal_to_one_already_measured_is_not_counted_twice(orchestra):
    """بعد از استقرار `current` همان 2026.08.19 است؛ دوبار شمردن n را دوبرابر می‌کرد."""
    orchestra.labels["current"] = "2026.08.19"
    M.main([*_ARGS, "--versions", "current,2026.8.19"])
    assert len(orchestra.calls) == 9


def test_an_unknown_client_costs_one_request_not_one_per_video(orchestra):
    orchestra.plan[("2026.07.04", "visionos")] = "unsupported"
    M.main([*_ARGS, "--versions", "current"])
    assert [c for _, c, _ in orchestra.calls].count("visionos") == 1
    assert len(orchestra.calls) == 7


def test_a_rate_limit_stops_the_measurement(orchestra):
    """از آن لحظه هر نتیجه دربارهٔ سشنِ محدودشدهٔ خودِ سنجش است، نه کلاینت."""
    orchestra.plan[("2026.08.19", "default", "v2")] = "rate_limit"
    M.main([*_ARGS, "--versions", "2026.8.19,current"])
    assert len(orchestra.calls) == 2


def test_keep_going_overrides_the_stop(orchestra):
    orchestra.plan[("2026.08.19", "default", "v2")] = "rate_limit"
    M.main([*_ARGS, "--versions", "2026.8.19", "--keep-going"])
    assert len(orchestra.calls) == 9


def test_a_version_that_cannot_be_installed_is_skipped(orchestra):
    assert M.main([*_ARGS, "--versions", "broken,2026.8.19"]) == 0
    assert {v for v, _, _ in orchestra.calls} == {"2026.08.19"}


def test_a_missing_cookie_file_is_refused_before_any_request(orchestra):
    assert M.main([*_ARGS, "--cookies", "/nonexistent/cookies.txt"]) == 2
    assert orchestra.calls == []


def test_the_pot_provider_comes_from_the_environment(orchestra, monkeypatch, capsys):
    monkeypatch.setenv("POT_PROVIDER_URL", "http://pot:4416")
    M.main([*_ARGS, "--versions", "2026.8.19"])
    assert "pot=on" in capsys.readouterr().out
    M.main([*_ARGS, "--versions", "2026.8.19", "--no-pot"])
    assert "pot=off" in capsys.readouterr().out


def test_arg_reads_a_value_and_falls_back():
    assert M._arg(["--sleep", "3"], "--sleep", "6") == "3"
    assert M._arg([], "--sleep", "6") == "6"
    assert M._arg(["--sleep"], "--sleep", "6") == "6"
