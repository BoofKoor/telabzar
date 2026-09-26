#!/usr/bin/env python3
"""سنجشِ زندهٔ مسیرِ **بی‌کوکیِ** یوتیوب روی همین سرور — کلاینت × نسخهٔ yt-dlp.

جوابِ سؤالی که هیچ منبعی نمی‌دهد (بررسیِ وابستگی به کوکی، ۲۰۲۶-۰۹): از **این**
IP، کدام کلاینتِ yt-dlp بدونِ کوکی واقعاً دانلود می‌کند؟ اندازه‌گیریِ ۱۶ اوت
(~۳۲٪ موفقیتِ بی‌کوکی) روی yt-dlp 2026.07.04 بود که کلاینتِ بی‌کوکی‌اش
(`android_vr`) از ۱۷ اوت برای همهٔ فرمت‌ها 403 می‌گیرد؛ 2026.08.19 به `visionos`
رفته و دربارهٔ آن روی IPِ دیتاسنتر فقط گزارشِ متناقضِ کاربران هست.

**هر خانه یک دانلودِ واقعیِ کوچک است** (`--test`: ~۱۰KB)، نه فقط `-J`: «استخراج
شد» با «دانلود می‌شود» یکی نیست — 403ِ googlevideo دقیقاً بعد از استخراجِ موفق
می‌آید. خروجی به تفکیکِ نسخه × کلاینت: ok / unsupported / bot_check / age_gate /
private / members_only / page_reload / rate_limit / http_403 / no_formats /
timeout / other.

**دو تلهٔ سنجش که ابزار دورشان می‌زند** (هر دو از سورسِ خودِ yt-dlp خوانده شد):

  * کلاینتی که نسخه نمی‌شناسد **بی‌صدا با پیش‌فرض جایگزین می‌شود**: 2026.07.04
    اصلاً `visionos` ندارد، پس `player_client=visionos` روی آن همان
    `android_vr,web_safari` را می‌سنجد و فقط یک WARNING می‌دهد — که `--no-warnings`ِ
    مسیرِ تولید همان را هم می‌بلعید. ابزار WARNINGها را نگه می‌دارد و چنین خانه‌ای
    را `unsupported` می‌خواند، نه نتیجهٔ کلاینتی که اصلاً اجرا نشد.
  * ۱۰KB ثابت نمی‌کند کلِ فایل می‌آید. برای کلاینتِ برنده یک‌بار با `--full`
    (دانلودِ کامل) تأیید کن.

**اجرا روی سرور** (بدونِ تزریقِ ماژول: این ابزار عمداً فقط stdlib است، پس روی
ایمیجِ *فعلی* هم اجرا می‌شود — برخلافِ `ig_anon_probe.py`):

    cd ~/telabzar && B=claude/laughing-mayer-2m7b3z && git fetch origin $B

    # نسخهٔ فعلیِ ایمیج در برابرِ 2026.08.19 (موقتاً در /tmp کانتینر نصب می‌شود)
    git show origin/$B:tools/yt_client_matrix.py \\
      | docker compose exec -T download-worker python - --versions current,2026.8.19

    # فقط شمارنده‌های تولید (dlstat:ytauth:*) در سه روزِ اخیر
    git show origin/$B:tools/yt_client_matrix.py \\
      | docker compose exec -T download-worker python - --stats 3

گزینه‌ها: `--videos ID,ID…` (بهتر: شناسه‌های واقعی از لاگ)، `--clients …`،
`--format "bv*[height<=720]"` (پیش‌فرض `ba/b`)، `--full`، `--no-pot`،
`--sleep ثانیه`، `--timeout ثانیه`، `--json /work/ytmatrix.json`، و
`--cookies مسیر` برای ستونِ مقایسهٔ «با کوکی» — آن یکی **یک اکانت خرج می‌کند** و
پیش‌فرض خاموش است.

**محدودیتِ نرخ سنجش را متوقف می‌کند** (مگر با `--keep-going`): از آن لحظه هر
خانه‌ای که بیاید دربارهٔ سشنِ محدودشدهٔ خودِ سنجش است، نه دربارهٔ کلاینت. فاصلهٔ
پیش‌فرضِ ۶ ثانیه بینِ خانه‌ها هم برای همین است — سقفِ سشنِ مهمان ~۳۰۰ ویدیو در ساعت
است (ویکیِ yt-dlp) و ترافیکِ واقعیِ ربات هم از همین IP می‌رود.
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

DEFAULT_VIDEOS = (
    "dQw4w9WgXcQ",   # موزیک‌ویدیو، قدیمی و پایدار
    "jNQXAC9IVRw",   # اولین ویدیوی یوتیوب، کوتاه
    "9bZkp7q19f0",   # پربازدید
    "YE7VzlLtp-4",   # Big Buck Bunny — ویدیوی تستِ خودِ yt-dlp
    "kJQP7kiw5Fk",   # پربازدید، ۴K
)
# `default` = پیش‌فرضِ همان نسخه (2026.07.04: android_vr,web_safari · 2026.08.19:
# visionos,web). `android_vr`/`web_safari` عمداً جدا سنجیده نمی‌شوند: روی نسخهٔ قدیم
# همان `default`اند، و سورسِ نسخهٔ نو صریحاً می‌گوید اولی از ۱۷ اوت 403 است و دومی
# HLS را فقط به سشنِ لاگین‌شده می‌دهد.
DEFAULT_CLIENTS = ("default", "visionos", "web", "web_embedded", "tv_simply", "mweb")
# پیش‌فرضِ با‌کوکیِ 2026.08.19 + خودِ `default` — فقط با `--cookies`
DEFAULT_COOKIE_CLIENTS = ("default", "web_embedded", "tv_downgraded", "web")

OUTCOMES = ("ok", "unsupported", "bot_check", "age_gate", "private", "members_only",
            "page_reload", "rate_limit", "http_403", "no_formats", "timeout", "other")

# WARNINGی که یعنی کلاینتِ خواسته‌شده اجرا **نشد** — هرچه بعدش آمد مالِ کلاینتِ
# دیگری است (`YoutubeIE._get_requested_clients`، در هر دو نسخه عیناً همین متن).
_UNSUPPORTED = ("skipping unsupported client", "since it does not support cookies")

# نشانه‌ها، به ترتیب. برای نوع‌های مشترک **عیناً** همان `downloader._YT_KIND_HINTS`
# است — ابزار عمداً `app` را import نمی‌کند تا روی ایمیجِ قدیمی هم اجرا شود، پس این
# کپیِ دوم است و `tests/test_yt_client_matrix.py` برابری‌اش را نگه می‌دارد.
# `http_403` عمداً گسترده‌تر است: برای سنجش هر ۴۰۳ی یعنی «این کلاینت از این‌جا کار
# نمی‌کند»، ولی تولید ۴۰۳ِ صفحهٔ API را از ۴۰۳ِ دانلودِ رسانه جدا می‌کند.
_HINTS = (
    ("bot_check", ("confirm you’re not a bot", "confirm you're not a bot",
                   "confirm you are not a bot")),
    ("age_gate", ("confirm your age", "age-restricted", "inappropriate for some users")),
    ("private", ("private video",)),
    ("members_only", ("members-only", "join this channel to get access")),
    ("page_reload", ("page needs to be reloaded",)),
    ("rate_limit", ("content isn't available, try again later",
                    "content isn’t available, try again later",
                    "rate-limited by youtube")),
    ("http_403", ("http error 403",)),
    ("no_formats", ("requested format is not available", "no video formats",
                    "only images are available", "no player clients have been requested")),
)


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def _lines(text: str | None) -> list[str]:
    """خطوطِ stderr — با این قید که `\\r` خط نمی‌شکند.

    yt-dlp شکستِ دانلود را `ERROR: \\r[download] Got error: HTTP Error 403: …`
    می‌نویسد (`FileDownloader.report_retry`)، و `splitlines()` همان را به یک
    «ERROR:»ِ خالی و یک خطِ بی‌برچسب می‌شکست: نه نشانه روی خطِ ERROR می‌ماند نه
    متنِ خطا در گزارش.
    """
    return [ln.strip() for ln in (text or "").replace("\r", " ").split("\n") if ln.strip()]


def _match(text: str | None) -> str | None:
    low = _norm(text)
    for outcome, hints in _HINTS:
        if any(h in low for h in hints):
            return outcome
    return None


def classify(rc: int | None, stderr: str, got_json: bool, file_ok: bool) -> str:
    """نتیجهٔ یک خانه.

    ترتیب باربر است: `unsupported` اول — حتی روی موفقیت، چون آن موفقیت مالِ
    کلاینتِ پیش‌فرض است نه کلاینتِ خواسته‌شده؛ بعد timeout؛ بعد «ok» که هم
    استخراج **و** هم بایتِ واقعی می‌خواهد؛ و آخر نشانه‌ها — اول روی خطوطِ
    `ERROR:` و فقط اگر چیزی نگرفت روی کلِ stderr، چون یک WARNING (مثلاً
    «Got error: HTTP Error 403 … Retrying») می‌تواند نشانهٔ دلیلِ دیگری را داشته
    باشد در حالی که شکستِ نهایی چیزِ دیگری است.
    """
    if any(h in _norm(stderr) for h in _UNSUPPORTED):
        return "unsupported"
    if rc is None:
        return "timeout"
    if rc == 0 and got_json and file_ok:
        return "ok"
    errs = "\n".join(ln for ln in _lines(stderr) if ln.startswith("ERROR:"))
    return _match(errs) or _match(stderr) or "other"


def build_cmd(base: list[str], url: str, client: str, outdir: str, pot: str | None,
              cookies: str | None, fmt: str = "ba/b", full: bool = False) -> list[str]:
    """خطِ فرمانِ یک خانه — همان پرچم‌های `downloader._common_flags` به‌جز
    `--no-warnings`، چون WARNING تنها نشانهٔ کلاینتِ ناشناخته است (بالا).

    `-j --no-simulate`: JSON پیش از دانلود چاپ می‌شود (`YoutubeDL.process_info`)
    و بعد دانلود واقعاً انجام می‌شود؛ بدونِ `--no-simulate`، `-j` شبیه‌سازی
    می‌کند و هیچ خانه‌ای هرگز «ok» نمی‌شد.
    """
    cmd = [*base, "-j", "--no-simulate", "--no-progress", "--no-playlist", "--no-part",
           "-f", fmt, "-o", os.path.join(outdir, "%(id)s.%(ext)s")]
    if not full:
        cmd.append("--test")
    if client != "default":
        cmd += ["--extractor-args", f"youtube:player_client={client}"]
    if pot:
        cmd += ["--extractor-args", f"youtubepot-bgutilhttp:base_url={pot}"]
    if cookies:
        cmd += ["--cookies", cookies]
    return [*cmd, url]


def _dec(raw: bytes | str | None) -> str:
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else (raw or "")


def _last_error(stderr: str) -> str:
    lines = _lines(stderr)
    errs = [ln for ln in lines if ln.startswith("ERROR:")]
    return (errs[-1] if errs else (lines[-1] if lines else ""))[:160]


def run_cell(base: list[str], env: dict, video: str, client: str, pot: str | None,
             cookies: str | None, timeout: float, fmt: str = "ba/b",
             full: bool = False) -> dict:
    url = video if video.startswith("http") else f"https://www.youtube.com/watch?v={video}"
    outdir = tempfile.mkdtemp(prefix="ytmx-")
    ck_copy = None
    if cookies:          # /cookies فقط‌خواندنی است و yt-dlp کوکی‌جار را برمی‌گرداند
        fd, ck_copy = tempfile.mkstemp(prefix="ytmx-ck-", suffix=".txt")
        os.close(fd)
        shutil.copyfile(cookies, ck_copy)
    t0 = time.monotonic()
    rc, out, err = None, "", ""
    try:
        # **بایت**، نه `text=True`: حالتِ متنیِ subprocess هر `\r` را `\n` می‌کند
        # (`_translate_newlines`) و همان `ERROR: \r[download] …` پیش از رسیدن به
        # `_lines` دو خط می‌شد. `downloader._run_dl` هم بایت می‌خواند.
        p = subprocess.run(build_cmd(base, url, client, outdir, pot, ck_copy, fmt, full),
                           capture_output=True, timeout=timeout, env=env)
        rc, out, err = p.returncode, _dec(p.stdout), _dec(p.stderr)
    except subprocess.TimeoutExpired as exc:
        err = _dec(exc.stderr)
    except OSError as exc:  # yt-dlp اصلاً اجرا نشد
        rc, err = -1, f"ERROR: {exc}"
    secs = round(time.monotonic() - t0, 1)
    info: dict = {}
    for line in (out or "").splitlines():
        if line.startswith("{"):
            try:
                info = json.loads(line)
                break
            except ValueError:
                pass
    fmts = info.get("formats") or []
    file_ok = any(os.path.getsize(os.path.join(outdir, n)) > 0
                  for n in os.listdir(outdir) if not n.endswith(".part"))
    shutil.rmtree(outdir, ignore_errors=True)
    if ck_copy:
        os.remove(ck_copy)
    return {"video": video, "client": client, "cookie": bool(cookies),
            "outcome": classify(rc, err, bool(info), file_ok), "secs": secs,
            "formats": len(fmts), "format_id": str(info.get("format_id") or ""),
            "max_height": max((f.get("height") or 0 for f in fmts), default=0),
            "error": "" if rc == 0 else _last_error(err)}


def summarize(results: list[dict]) -> dict:
    """(نسخه, حالت, کلاینت) → شمارشِ هر نتیجه + میانهٔ حداکثرِ ارتفاع و زمان."""
    out: dict = {}
    for r in results:
        key = (r["version"], "cookie" if r["cookie"] else "anon", r["client"])
        row = out.setdefault(key, {"n": 0, **{o: 0 for o in OUTCOMES},
                                   "_h": [], "_s": []})
        row["n"] += 1
        row[r["outcome"]] += 1
        if r["outcome"] == "ok":
            row["_h"].append(r["max_height"])
        row["_s"].append(r["secs"])
    for row in out.values():
        heights, secs = row.pop("_h"), row.pop("_s")
        row["height"] = int(statistics.median(heights)) if heights else 0
        row["secs"] = round(statistics.median(secs), 1) if secs else 0.0
    return out


def render(summary: dict) -> str:
    # فقط ستون‌هایی که جایی ناصفرند — ۱۱ ستونِ اکثراً صفر جدول را ناخوانا می‌کرد
    cols = [o for o in OUTCOMES if o != "ok" and any(r[o] for r in summary.values())]
    head = f"{'version':<11} {'mode':<6} {'client':<14} {'ok':>6} " + \
           " ".join(f"{c[:11]:>11}" for c in cols) + f" {'maxH':>5} {'secs':>5}"
    lines = [head, "-" * len(head)]
    for (ver, mode, client), row in sorted(summary.items()):
        lines.append(f"{ver:<11} {mode:<6} {client:<14} {row['ok']:>3}/{row['n']:<2} "
                     + " ".join(f"{row[c]:>11}" for c in cols)
                     + f" {row['height']:>5} {row['secs']:>5}")
    return "\n".join(lines)


# ── نسخهٔ دیگری از yt-dlp، کنارِ نسخهٔ ایمیج ─────────────────────────────────
def ytdlp_base(version: str, root: str = "/tmp") -> tuple[list[str], dict]:
    """(خطِ فرمان, env) برای اجرای یک نسخه. `current` = همان yt-dlpِ ایمیج.

    نسخهٔ دیگر با `[default]` نصب می‌شود — همان extraی تولید؛ بدونش `yt-dlp-ejs`
    (حل‌کنندهٔ چالشِ JSِ کلاینتِ `web`) نمی‌آید و خانه‌های `web` به دلیلِ غلط
    می‌افتادند (§۶: extraی غایب بی‌صداست).
    """
    env = dict(os.environ)
    if version == "current":
        return ["yt-dlp"], env
    target = os.path.join(root, f"ytdlp-{version}")
    if not os.path.isdir(os.path.join(target, "yt_dlp")):
        print(f"… نصبِ yt-dlp {version} در {target}", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                        "--disable-pip-version-check", "--target", target,
                        f"yt-dlp[default]=={version}"], check=True)
    # پلاگینِ bgutil از site-packagesِ ایمیج پیدا می‌شود (فضای‌نامِ yt_dlp_plugins)
    env["PYTHONPATH"] = target + os.pathsep + env.get("PYTHONPATH", "")
    return [sys.executable, "-m", "yt_dlp"], env


def version_of(base: list[str], env: dict) -> str:
    try:
        p = subprocess.run([*base, "--version"], capture_output=True, text=True,
                           timeout=60, env=env)
        return (p.stdout.strip().splitlines() or ["?"])[0] if p.returncode == 0 else "?"
    except Exception:  # noqa: BLE001 — تشخیص است
        return "?"


# ── شمارنده‌های تولید ───────────────────────────────────────────────────────────
def parse_stats(items: dict[str, int]) -> dict:
    """`dlstat:ytauth:<phase>:<mode>:<outcome>:<day>` → {day: {(phase, mode): {outcome: n}}}.

    قالبِ کلید کپیِ دومِ `tasks_download._ytauth_metric` است؛ تست همان کلیدی را که
    تولید واقعاً می‌نویسد از این‌جا رد می‌کند.
    """
    out: dict = {}
    for key, n in items.items():
        parts = key.split(":")
        if len(parts) != 6 or parts[:2] != ["dlstat", "ytauth"]:
            continue
        _, _, phase, mode, outcome, day = parts
        out.setdefault(day, {}).setdefault((phase, mode), {})[outcome] = int(n)
    return out


def render_stats(stats: dict) -> str:
    lines = []
    for day in sorted(stats):
        lines.append(f"── {day} (UTC)")
        for (phase, mode), counts in sorted(stats[day].items()):
            total = sum(counts.values())
            ok = counts.get("ok", 0)
            rest = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()) if k != "ok")
            lines.append(f"   {phase:<6} {mode:<6} ok {ok}/{total}"
                         f" ({round(ok / total * 100) if total else 0}%)  {rest}")
        fa = stats[day].get(("fetch", "anon"), {})
        fc = stats[day].get(("fetch", "cookie"), {})
        pc = stats[day].get(("probe", "cookie"), {})
        lines.append(f"   → fetch بی‌کوکی موفق: {fa.get('ok', 0)}/{sum(fa.values())}"
                     f" · تلاشِ با‌کوکی: fetch {sum(fc.values())}، probe {sum(pc.values())}")
    return "\n".join(lines) or "هیچ شمارنده‌ای نیست (هنوز دانلودِ یوتیوبی ثبت نشده، یا کد قدیمی است)."


def _stats(days: int) -> int:
    import redis                    # در ایمیجِ download-worker هست (requirements.txt)
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"),
                             decode_responses=True)
    items = {k: int(r.get(k) or 0) for k in r.scan_iter(match="dlstat:ytauth:*", count=500)}
    stats = parse_stats(items)
    keep = sorted(stats)[-days:]
    print(render_stats({d: stats[d] for d in keep}))
    return 0


def _arg(argv: list[str], name: str, default: str | None = None) -> str | None:
    if name in argv:
        i = argv.index(name)
        return argv[i + 1] if i + 1 < len(argv) else default
    return default


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--stats" in argv:
        return _stats(int(_arg(argv, "--stats", "3") or "3"))
    versions = (_arg(argv, "--versions", "current") or "current").split(",")
    videos = (_arg(argv, "--videos") or ",".join(DEFAULT_VIDEOS)).split(",")
    clients = (_arg(argv, "--clients") or ",".join(DEFAULT_CLIENTS)).split(",")
    cookies = _arg(argv, "--cookies")
    ck_clients = (_arg(argv, "--cookie-clients") or ",".join(DEFAULT_COOKIE_CLIENTS)).split(",")
    pot = None if "--no-pot" in argv else (os.environ.get("POT_PROVIDER_URL") or None)
    fmt = _arg(argv, "--format", "ba/b") or "ba/b"
    full = "--full" in argv
    keep_going = "--keep-going" in argv
    pause = float(_arg(argv, "--sleep", "6") or 6)
    timeout = float(_arg(argv, "--timeout", "120") or 120)
    dump = _arg(argv, "--json")
    if cookies and not os.path.isfile(cookies):
        print(f"✗ فایلِ کوکی پیدا نشد: {cookies}")
        return 2

    results: list[dict] = []
    seen: set[str] = set()
    stopped = False
    for ver in versions:
        try:
            base, env = ytdlp_base(ver)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"✗ نصبِ yt-dlp {ver} نشد ({exc}) — این نسخه رد شد", flush=True)
            continue
        label = version_of(base, env)
        if label == "?":
            print(f"✗ yt-dlp ({ver}) اجرا نشد — این نسخه رد شد", flush=True)
            continue
        if label in seen:       # بعد از استقرار، current همان 2026.08.19 است
            print(f"… {ver} همان {label} است که سنجیده شد — رد شد", flush=True)
            continue
        seen.add(label)
        plan = [(c, None) for c in clients] + ([(c, cookies) for c in ck_clients]
                                                if cookies else [])
        print(f"\n═══ yt-dlp {label}  ·  pot={'on' if pot else 'off'}  ·  -f {fmt}"
              f"{'  ·  full' if full else ''}  ·  {len(videos)} ویدیو × {len(plan)} حالت",
              flush=True)
        for client, ck in plan:
            for video in videos:
                res = run_cell(base, env, video, client, pot, ck, timeout, fmt, full)
                res["version"] = label
                results.append(res)
                print(f"  {'ck' if ck else '--'} {client:<14} {video:<12} {res['outcome']:<12} "
                      f"{res['secs']:>5}s  h={res['max_height']:<4} f={res['format_id']:<8} "
                      f"{res['error'][:60]}", flush=True)
                if res["outcome"] == "unsupported":
                    print(f"  ↳ yt-dlp {label} کلاینتِ «{client}» را نمی‌شناسد"
                          " (بی‌صدا به پیش‌فرض می‌افتاد) — بقیهٔ ویدیوها رد شد", flush=True)
                    break
                if res["outcome"] == "rate_limit" and not keep_going:
                    print("\n⛔ محدودیتِ نرخِ یوتیوب — از این‌جا به بعد هر نتیجه دربارهٔ سشنِ"
                          " محدودشدهٔ خودِ سنجش است، نه دربارهٔ کلاینت. متوقف شد؛ بعداً با"
                          " ویدیو/کلاینتِ کمتر دوباره اجرا کن (یا --keep-going).", flush=True)
                    stopped = True
                    break
                time.sleep(pause)
            if stopped:
                break
        if stopped:
            break
    if results:
        print("\n" + render(summarize(results)))
    if dump:
        with open(dump, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
        print(f"\nنتیجهٔ خام: {dump}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
