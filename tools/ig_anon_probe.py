#!/usr/bin/env python3
"""سنجشِ زندهٔ مسیرِ **ناشناسِ** اینستاگرام — روی سرور، بدونِ کوکی.

جوابِ دو سؤالی که هیچ تستِ آفلاینی نمی‌دهد:

  ۱) از **این** IP، صفحهٔ embed هنوز رسانه می‌دهد؟ (یا اینستاگرام بسته‌اش؟)
  ۲) URLهایی که بیرون می‌آیند واقعاً **قابلِ دانلود**اند؟ — با یک range-GETِ
     کوچک روی هر آیتم سنجیده می‌شود، نه با نگاه‌کردن به شکلِ URL.

سؤالِ دوم مهم‌تر از آن است که به‌نظر می‌رسد: یک URLِ امضاشده می‌تواند کاملاً
سالم به‌نظر برسد و ۴۰۳ بدهد. «پارس شد» با «دانلود می‌شود» یکی نیست.

**اجرا روی سرور — دو گام، و گامِ اول اختیاری نیست:**

    cd ~/telabzar && B=claude/cookie-dependency-audit-9ioyzu && git fetch origin $B

    # ۱) ماژول را داخلِ کانتینر بگذار  ← بدونِ این، ImportError می‌گیری
    git show origin/$B:app/instagram_anon.py \\
      | docker compose exec -T download-worker sh -c 'cat > /srv/app/instagram_anon.py'

    # ۲) ابزار را اجرا کن
    git show origin/$B:tools/ig_anon_probe.py \\
      | docker compose exec -T download-worker python - "<POST_URL>"

**چرا گامِ اول لازم است** (و چرا این ابزار خودکفا نوشته **نشده**): ایمیجِ
download-worker یک عکسِ فوریِ `app/` در زمانِ build است، پس هر ماژولِ **تازه**
تا rebuildِ بعدی داخلش نیست — الگوی جاافتادهٔ `git show … | docker compose exec`
فقط برای ابزارهایی کار می‌کند که ماژول‌های *موجود* را صدا می‌زنند (مثلِ
`spotify_embed_dump.py` که `app.downloader` می‌خواهد). راهِ جایگزین این بود که
نردبون این‌جا دوباره نوشته شود، ولی آن‌وقت ابزار یک **کپیِ** منطق را می‌سنجید نه
تولید را — همان واگراییِ دو نسخهٔ دست‌نویس که §۷ دربارهٔ `remove_cookie_file`
ثبت کرده. پس ماژولِ واقعی تزریق می‌شود و ابزار همان را اجرا می‌کند.
(بعد از merge و یک `telabzar update` این گام دیگر لازم نیست.)

با `--dump <dir>` پاسخِ **خام** را هم ذخیره می‌کند (برای فیکسچرِ تست):

    … | docker compose exec -T download-worker python - "<POST_URL>" --dump /work/igdump
    docker compose cp download-worker:/work/igdump ./igdump

هیچ وابستگیِ تازه‌ای نمی‌خواهد: فقط aiohttp که `requirements-worker-dl.txt` از
قبل دارد. کوکی هرگز نمی‌فرستد — نه خودش و نه ماژولی که صدا می‌زند.
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


async def _read_capped(content, cap: int) -> int:
    """بایت‌های بدنه را تا سقفِ `cap` بشمار.

    **یک `await content.read(n)` کافی نیست و این‌جا گزارشِ غلط داد.** خوانندهٔ
    aiohttp «تا سقفِ n» می‌دهد، نه «دقیقاً n»: هرچه در بافر است برمی‌گرداند، پس
    روی یک پاسخِ چندتکه‌ای عددی مثلِ `got=1B` چاپ می‌شد در حالی که status و
    Content-Type و total درست بودند (اندازه‌گیری‌شده روی مستر).

    چرا تا سقف و نه `read(-1)`: اگر سروری هدرِ Range را نادیده بگیرد و ۲۰۰ با
    کلِ فایل بدهد، `read(-1)` یک ویدیوی چندمگابایتی را کامل می‌کشد — و این
    ابزار قرار است **سنجشِ دسترسی** باشد نه دانلود.
    """
    total = 0
    async for part in content.iter_chunked(16384):
        total += len(part)
        if total >= cap:
            break
    return total


async def _range_get(session, url: str, opts) -> str:
    """یک range-GETِ کوچک → «HTTP <status> · <content-type> · <total size>»."""
    import aiohttp
    from app import downloader as D
    try:
        async with session.get(url, headers={"Range": f"bytes=0-{_RANGE_BYTES}",
                                             **D._BROWSER_HEADERS},
                               proxy=D._http_proxy(opts.get("proxy")),
                               timeout=aiohttp.ClientTimeout(total=30)) as r:
            got = await _read_capped(r.content, _RANGE_BYTES + 1)
            # Content-Range: bytes 0-65535/12345678  → حجمِ کلِ فایل
            total = None
            cr = r.headers.get("Content-Range", "")
            if "/" in cr and cr.rsplit("/", 1)[-1].isdigit():
                total = int(cr.rsplit("/", 1)[-1])
            elif r.headers.get("Content-Length", "").isdigit():
                total = int(r.headers["Content-Length"])
            ok = "✅" if r.status in (200, 206) and got else "❌"
            return (f"{ok} HTTP {r.status} · {r.headers.get('Content-Type')} · "
                    f"total={_fmt(total)} · got={_fmt(got)}")
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
    try:
        from app import instagram_anon as IA
    except ImportError as exc:
        # ایمیجْ عکسِ فوریِ زمانِ build است، پس ماژولِ تازه داخلش نیست. خطای خامِ
        # `cannot import name 'instagram_anon' from 'app'` علت را نمی‌گوید و
        # وقت می‌گیرد؛ این‌جا دقیقاً دستورِ لازم چاپ می‌شود.
        print(f"❌ {exc}\n\n"
              "ماژول داخلِ کانتینر نیست (ایمیج در زمانِ build ساخته شده). یک‌بار بزن:\n\n"
              "  B=claude/cookie-dependency-audit-9ioyzu\n"
              "  git show origin/$B:app/instagram_anon.py \\\n"
              "    | docker compose exec -T download-worker sh -c "
              "'cat > /srv/app/instagram_anon.py'\n\n"
              "بعد همین ابزار را دوباره اجرا کن. (پس از merge و `telabzar update` لازم نیست.)")
        return 2

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
