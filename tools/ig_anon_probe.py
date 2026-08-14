#!/usr/bin/env python3
"""سنجشِ زندهٔ مسیرِ **ناشناسِ** اینستاگرام — روی سرور، بدونِ کوکی.

جوابِ دو سؤالی که هیچ تستِ آفلاینی نمی‌دهد:

  ۱) از **این** IP، صفحهٔ embed هنوز رسانه می‌دهد؟ (یا اینستاگرام بسته‌اش؟)
  ۲) URLهایی که بیرون می‌آیند واقعاً **قابلِ دانلود**اند؟ — با یک range-GETِ
     کوچک روی هر آیتم سنجیده می‌شود، نه با نگاه‌کردن به شکلِ URL.

سؤالِ دوم مهم‌تر از آن است که به‌نظر می‌رسد: یک URLِ امضاشده می‌تواند کاملاً
سالم به‌نظر برسد و ۴۰۳ بدهد. «پارس شد» با «دانلود می‌شود» یکی نیست.

**اجرا روی سرور:**

    cd ~/telabzar && git fetch origin claude/cookie-dependency-audit-9ioyzu \\
      && git show origin/claude/cookie-dependency-audit-9ioyzu:tools/ig_anon_probe.py \\
         | docker compose exec -T download-worker python - "<POST_URL>"

با `--dump <dir>` پاسخِ **خام** را هم ذخیره می‌کند (برای فیکسچرِ تست):

    … | docker compose exec -T download-worker python - "<POST_URL>" --dump /work/igdump
    docker compose cp download-worker:/work/igdump ./igdump

این ابزار در ایمیجِ داکر نیست و هیچ وابستگیِ تازه‌ای نمی‌خواهد: فقط aiohttp که
`requirements-worker-dl.txt` از قبل دارد. کوکی هرگز نمی‌فرستد — نه خودش و نه
ماژولی که صدا می‌زند.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, "/srv")     # مسیرِ کدِ درونِ کانتینر
sys.path.insert(0, ".")        # اجرا از ریشهٔ ریپو هم کار کند

_RANGE_BYTES = 65535           # فقط سرِ فایل؛ سنجشِ دسترسی است نه دانلود


def _fmt(n: int | None) -> str:
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return "?"


async def _range_get(session, url: str, opts) -> str:
    """یک range-GETِ کوچک → «HTTP <status> · <content-type> · <total size>»."""
    import aiohttp
    from app import downloader as D
    try:
        async with session.get(url, headers={"Range": f"bytes=0-{_RANGE_BYTES}",
                                             **D._BROWSER_HEADERS},
                               proxy=D._http_proxy(opts.get("proxy")),
                               timeout=aiohttp.ClientTimeout(total=30)) as r:
            chunk = await r.content.read(_RANGE_BYTES + 1)
            # Content-Range: bytes 0-65535/12345678  → حجمِ کلِ فایل
            total = None
            cr = r.headers.get("Content-Range", "")
            if "/" in cr and cr.rsplit("/", 1)[-1].isdigit():
                total = int(cr.rsplit("/", 1)[-1])
            elif r.headers.get("Content-Length", "").isdigit():
                total = int(r.headers["Content-Length"])
            ok = "✅" if r.status in (200, 206) and chunk else "❌"
            return (f"{ok} HTTP {r.status} · {r.headers.get('Content-Type')} · "
                    f"total={_fmt(total)} · got={_fmt(len(chunk))}")
    except Exception as exc:                       # noqa: BLE001 — تشخیص است
        return f"❌ {type(exc).__name__}: {str(exc)[:110]}"


async def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    url = argv[1]
    dump = None
    if "--dump" in argv:
        i = argv.index("--dump")
        dump = argv[i + 1] if len(argv) > i + 1 else "/work/igdump"
        os.makedirs(dump, exist_ok=True)

    import aiohttp
    from app import downloader as D
    from app import instagram_anon as IA

    # opts عمداً همان شکلی است که `tasks_download._opts()` می‌سازد — **با** یک
    # کوکیِ جعلی داخلش، تا اگر روزی این ماژول کوکی بفرستد، این‌جا دیده شود.
    opts = {"proxy": os.environ.get("PROXY_URL") or None,
            "user_agent": None, "direct_proxy": True,
            "cookies": "/nonexistent/probe-must-never-send-this.txt"}

    print(f"url        = {url}")
    print(f"shortcode  = {IA.shortcode_of(url)}")
    print(f"PROXY_URL  = {opts['proxy']!r}   (خالی = خروجیِ مستقیمِ همین ماشین)")

    if dump:                                        # پاسخِ خام، پیش از هر تفسیری
        sc = IA.shortcode_of(url)
        async with IA._new_session(opts) as s:
            for label, tmpl, headers in (("oembed", IA._OEMBED, IA._OEMBED_HEADERS),
                                         ("embed", IA._EMBED, IA._EMBED_HEADERS)):
                st, body, err = await IA._get_text(s, tmpl.format(sc=sc), headers,
                                                   opts, 30.0)
                ext = "json" if label == "oembed" else "html"
                path = os.path.join(dump, f"{sc}.{label}.{ext}")
                if st is not None:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(body)
                print(f"  dump {label:7} HTTP {st} {len(body)} chars"
                      f"{' → ' + path if st is not None else '  ' + err}")

    print("\n── نردبون ─────────────────────────────────────────────")
    out = await IA.resolve_detailed(url, opts, with_oembed=True)
    for r in out.rungs:
        print(f"  {r}")
    print(f"\n  verdict = {out.verdict}")

    if out.result is None:
        print("\n❌ مسیرِ ناشناس نشد → فاز ۲ به کوکی برمی‌گردد.")
        print("   (verdict=network یعنی تقصیرِ هیچ اکانتی نیست و نباید ضربه بخورد)")
        return 1

    res = out.result
    print(f"\n  content  = {res.content}")
    print(f"  via      = {res.via}")
    print(f"  media_id = {res.media_id}")
    print(f"  caption  = {(res.caption or '')[:70]!r}")
    print(f"  items    = {len(res.items)}")

    print("\n── دسترسیِ واقعیِ هر آیتم (range-GET) ──────────────────")
    bad = 0
    async with aiohttp.ClientSession(connector=D._direct_connector(opts)) as s:
        for i, item in enumerate(res.items):
            verdict = await _range_get(s, item.url, opts)
            print(f"  [{i:2}] {item.kind:5} {verdict}")
            print(f"       {item.url[:118]}")
            bad += verdict.startswith("❌")

    print(f"\n{'✅ همهٔ آیتم‌ها دانلودشدنی‌اند.' if not bad else f'❌ {bad} از {len(res.items)} آیتم نشد.'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv)))
