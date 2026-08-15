"""مسیرِ **ناشناسِ** اینستاگرام — بدونِ کوکی، بدونِ حالت، بدونِ اثرِ جانبی.

چرا وجود دارد: امروز اینستاگرام ۱۰۰٪ کوکی‌محور است (`engine_for` هر لینکِ
اینستاگرام را به gallery-dl می‌دهد و extractorِ آن به `sessionid` بند است — در
حالتِ ناشناس هر سه لینکِ آزمایشی `HTTP redirect to login page` دادند). سشن‌ها
چند بار در روز می‌میرند و گران‌ترین منبعِ عملیاتیِ این پروژه‌اند. این ماژول یک
مسیرِ **دوم** است که هیچ اکانتی خرج نمی‌کند؛ **جایگزینِ gallery-dl نیست** و در
فاز ۱ هیچ‌کس صدایش نمی‌زند (اتصال به `run_download` فاز ۲ است).

قواعدی که این ماژول را تعریف می‌کنند:

* **هرگز کوکی نمی‌فرستد.** کلیدِ `cookies` در `opts` عمداً **خوانده نمی‌شود** —
  فراخوان می‌تواند همان دیکشنریِ `tasks_download._opts()` را بدهد بدونِ اینکه
  چیزی نشت کند. تستِ اختصاصی همین را روی یک سرورِ واقعی می‌سنجد.
* **شکست ≠ خطای شبکه.** `InstagramAnonOutcome.verdict` این دو را جدا می‌کند، چون
  فاز ۲ باید بتواند تصمیم بگیرد: یک قطعیِ شبکه نباید به `mark_fail` روی یک
  اکانتِ سالم تبدیل شود (همان درسِ `_resolve_blame` در §۷ — تقصیر را به متنِ
  خطا نسپار).
* **گذار بی‌صدا نیست.** وقتی کلِ نردبون می‌افتد **یک** `log.warning` می‌آید که
  هر رده را با علت و کدِ HTTP نام می‌برد؛ همان الگوی هشدارِ سقوط به oEmbed در
  `downloader._spotify_scrape`، که وجود نداشتنش یک پارسرِ مرده را هفته‌ها
  پنهان کرد.

**نردبون (فاز ۱ فقط دو رده دارد):**

    A) oEmbed  →  media_id      — فقط تشخیصی، پیش‌فرض **خاموش** (`with_oembed`).
                                  رسانه از این‌جا نمی‌آید و این رده هرگز گیت
                                  نمی‌کند. مسیرِ `api/v1/media/<id>/info/` عمداً
                                  ساخته نشده: از IPِ ما `HTTP 403 login_required`
                                  می‌دهد (اندازه‌گیری‌شده روی مستر).
    B) embed   →  رسانه          — دو زیرشاخهٔ **ترتیبی**:
         ۱) `contextJSON` → `gql_data` (ویدیو / کاروسل / بیشترِ تک‌عکسی‌ها)
         ۲) اگر ۱ چیزی نداد → `<img class="EmbeddedMediaImage" srcset>`

ردهٔ GraphQL (`doc_id`) ساخته نشد و دیگر نامزد هم نیست: نسخهٔ کاهش‌یافته‌اش روی چهار
شورت‌کدِ واقعی از IPِ مستر اجرا شد و هر چهار `HTTP 403 not-logged-in` دادند — به‌همراهِ
یک کنترلِ منفی که از مسیرِ embed **موفق** دانلود می‌شود و همان ۴۰۳ را گرفت، پس گیت
مالِ اندپوینت است نه مالِ آن پست‌ها. جزئیات و اعداد در §۷ (REFUTED).
"""
from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import downloader as D
from .exceptions import ProcessingCancelled

log = logging.getLogger("telabzar.ig_anon")

# ── ثابت‌های شبکه ────────────────────────────────────────────────
_OEMBED = "https://i.instagram.com/api/v1/oembed/?url=https://www.instagram.com/p/{sc}/"
_EMBED = "https://www.instagram.com/p/{sc}/embed/captioned/"
# شناسهٔ اپِ وبِ اینستاگرام. عددِ عمومی و ثابتی است (همان که cobalt هم می‌فرستد)؛
# راز نیست و به هیچ حسابی بند نیست. بدونش oEmbed از IPِ ما جواب نمی‌دهد.
_IG_APP_ID = "936619743392459"
_OEMBED_TIMEOUT = 20.0
_EMBED_TIMEOUT = 25.0

# هدرهای صفحهٔ embed. مجموعهٔ «مرورگرِ واقعی» که روی مستر HTTP 200 داد؛ UA از
# `downloader._BROWSER_HEADERS` می‌آید تا دو نسخهٔ دست‌نویسِ UA در ریپو نماند.
_EMBED_HEADERS = {
    "User-Agent": D._BROWSER_HEADERS["User-Agent"],
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
               "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"),
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "max-age=0",
    "Dnt": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
_OEMBED_HEADERS = {"User-Agent": D._BROWSER_HEADERS["User-Agent"], "x-ig-app-id": _IG_APP_ID}

# ── الگوها ──────────────────────────────────────────────────────
# شورت‌کد از هر چهار شکلِ لینک. `/stories/` عمداً نیست: استوریِ ناشناس وجود
# ندارد (cobalt هم بی‌کوکی ردش می‌کند) — ببین §۷.
_SHORTCODE_RE = re.compile(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
# بلاکِ راه‌اندازیِ صفحهٔ embed. `re.DOTALL` عمدی است: یک newline وسطِ بلاک
# کلِ پارس را بی‌صدا می‌شکست — دقیقاً همان تله‌ای که `>(\{.*?\})</script>`ِ
# اسپاتیفای داشت و در §۷ ثبت است.
_INIT_RE = re.compile(r'"init",\[\],\[(.*?)\]\],', re.DOTALL)
# تگِ عکسِ اصلیِ فرمِ PolarisEmbedSimple. **هدف‌گیریِ کلاس لازم است، نه احتیاط:**
# در همان HTML دو `<img srcset>`ِ دیگر هم هست که هر دو روی
# `scontent-…cdninstagram.com`اند، پس فیلترِ هاست نمی‌گیردشان.
_EMBEDDED_IMG_RE = re.compile(
    r'<img[^>]*\bclass="[^"]*\bEmbeddedMediaImage\b[^"]*"[^>]*>', re.I)
_SRCSET_RE = re.compile(r'\bsrcset="([^"]*)"', re.I)
_SRC_RE = re.compile(r'\bsrc="([^"]*)"', re.I)
# عرضِ کاندید، **مقید به انتهای توکن**. رجکسِ شلِ `(\d+)w` عددِ داخلِ URLِ
# امضاشده را می‌گیرد: روی فیکسچرِ واقعی کاندیدِ ۳۰۷۲w را `9` می‌خواند و در
# نتیجه URLِ دیگری برنده می‌شود. اندازه‌گیری‌شده، نه فرض.
_SRCSET_W_RE = re.compile(r"\s(\d+)w$")

# میزبان‌های مجازِ رسانه. این **لایهٔ دوم** است نه دفاع: URLها فقط از فیلدهای
# ساخت‌یافته (`video_url`/`display_url`/`srcset`ِ تگِ هدف) برداشته می‌شوند، پس
# آیکون‌های `static.cdninstagram.com/rsrc.php/*.webp` اصلاً واردِ مسیر نمی‌شوند.
_MEDIA_HOST_SUFFIXES = (".cdninstagram.com", ".fbcdn.net")

CONTENT_SINGLE_VIDEO = "single_video"
CONTENT_SINGLE_PHOTO = "single_photo"
CONTENT_CAROUSEL = "carousel"

#: علت‌های `RungReport.reason` — فاز ۲ روی این‌ها تله‌متری می‌گذارد، پس رشته‌های
#: پایداری‌اند نه متنِ آزاد.
R_OK, R_SKIPPED, R_BAD_URL = "ok", "skipped", "bad_url"
R_NETWORK, R_HTTP_ERROR, R_LOGIN_REQUIRED = "network", "http_error", "login_required"
R_PARSE_FAILED, R_NO_MEDIA = "parse_failed", "no_media"

#: حکمِ کلی — چیزی که فاز ۲ روی آن تصمیم می‌گیرد.
V_OK, V_UNSUPPORTED, V_BLOCKED, V_NETWORK = "ok", "unsupported", "blocked", "network"

#: سطلِ تله‌متریِ `download_anonymous`. چهارتای اول همان `verdict`ِ resolve‌اند و
#: دوتای آخر چیزهایی که resolve دربارهٔ‌شان حرفی ندارد:
#:
#: * `B_SKIPPED` — لینک اصلاً موردِ ناشناس نیست (استوری/پروفایل: شورت‌کد ندارد).
#:   **بدونِ هیچ درخواستِ شبکه‌ای** شمرده می‌شود.
#: * `B_FETCH_FAILED` — resolve موفق بود ولی بایت‌ها نیامدند (URLِ امضاشدهٔ
#:   منقضی، سقفِ تجمعی وسطِ کاروسل، قطعیِ شبکه، اتمامِ بودجهٔ زمانی). این سطل
#:   **نباید** با `B_OK` جمع شود: در این حالت به مسیرِ کوکی افتاده‌ایم و کوکی
#:   سوخته، پس شمردنش به‌عنوان موفقیت ادعای «این‌قدر دانلود کوکی لمس نکرد» را
#:   دروغ می‌کند.
B_OK, B_SKIPPED, B_FETCH_FAILED = V_OK, "skipped", "fetch_failed"
BUCKETS = (V_OK, V_UNSUPPORTED, V_BLOCKED, V_NETWORK, B_SKIPPED, B_FETCH_FAILED)


@dataclass(frozen=True)
class InstagramAnonItem:
    kind: str          # "video" | "photo"
    url: str


@dataclass(frozen=True)
class InstagramAnonResult:
    shortcode: str
    content: str                              # single_video | single_photo | carousel
    items: tuple[InstagramAnonItem, ...]
    via: str                                  # "embed" — کدام رده برد (لاگِ گذارِ فاز ۲)
    media_id: str | None = None               # از رده A؛ فقط تشخیصی
    caption: str | None = None


@dataclass(frozen=True)
class RungReport:
    rung: str                                 # "oembed" | "embed"
    ok: bool
    reason: str
    status: int | None = None
    detail: str = ""

    def __str__(self) -> str:                 # برای خطِ هشدارِ یک‌جا
        st = f" HTTP {self.status}" if self.status is not None else ""
        d = f" ({self.detail})" if self.detail else ""
        return f"{self.rung}={self.reason}{st}{d}"


@dataclass(frozen=True)
class InstagramAnonOutcome:
    result: InstagramAnonResult | None
    rungs: tuple[RungReport, ...] = field(default_factory=tuple)
    verdict: str = V_UNSUPPORTED


class _VideoUrlMissing(Exception):
    """آیتمی خودش را ویدیو اعلام کرده ولی `video_url` ندارد.

    cobalt این حالت را بی‌صدا با `display_url` (یعنی **فریمِ پوستر**) جواب
    می‌دهد. برای ما این «فایلِ غلط» است نه «فایلِ کوچک‌تر»، و §۷ صریح است که
    fallbackی که بی‌صدا به دادهٔ کمتر تنزل کند از خطا بدتر است. پس کلِ رده
    می‌افتد و کار به مسیرِ کوکی می‌رود که درست می‌گیردش.

    `detail` علتِ **مشخص** را حمل می‌کند (کدام فرزند)، نه یک no_mediaِ ژنریک، تا
    تله‌متریِ فاز ۲ بتواند drift را از انتظارِ عادی تفکیک کند.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


# ── کمکی‌های خالص (بی‌شبکه، قابلِ تست بدونِ I/O) ──────────────────
def shortcode_of(url: str) -> str | None:
    """`/p/` `/reel/` `/reels/` `/tv/` → شورت‌کد. وگرنه None."""
    m = _SHORTCODE_RE.search(url or "")
    return m.group(1) if m else None


def _is_media_url(url: object) -> bool:
    """آیا این یک URLِ رسانهٔ اینستاگرام است (نه آیکون/اسپینر)؟"""
    if not isinstance(url, str) or not url:
        return False
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host.endswith(_MEDIA_HOST_SUFFIXES):
        return False
    if host.startswith("static."):            # میزبانِ دارایی‌های ثابتِ اینستاگرام
        return False
    return "/rsrc.php/" not in (p.path or "")


def _caption_of(media: dict) -> str | None:
    """کپشنِ پست از `edge_media_to_caption`. تمیزکاری با همان
    `downloader.clean_caption` انجام می‌شود تا دو قاعدهٔ دست‌نویس نداشته باشیم."""
    try:
        edges = ((media.get("edge_media_to_caption") or {}).get("edges")) or []
        text = edges[0]["node"]["text"] if edges else None
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    return D.clean_caption(text) if text else None


def _child_item(node: dict, index: int) -> InstagramAnonItem | None:
    """یک فرزندِ کاروسل → آیتم (یا None اگر URLش رسانه نبود).

    **تفکیکِ نوع با فلگِ `is_video` است، نه با وجودِ `video_url`** — در فیکسچرِ
    واقعی هر ۱۱ فرزند `display_url` دارند (حتی اگر ویدیو باشند)، پس «آیا
    `video_url` هست» معیارِ غلطی است.
    """
    if node.get("is_video"):
        vurl = node.get("video_url")
        if not vurl:
            raise _VideoUrlMissing(
                f"carousel child {index}: is_video but no video_url")
        return InstagramAnonItem("video", vurl) if _is_media_url(vurl) else None
    durl = node.get("display_url")
    return InstagramAnonItem("photo", durl) if _is_media_url(durl) else None


def extract_from_gql(gql: dict | None) -> tuple[str, tuple[InstagramAnonItem, ...], str | None] | None:
    """`gql_data` → (نوعِ محتوا، آیتم‌ها، کپشن) یا None اگر چیزی نبود.

    **هر دو کلید خوانده می‌شود:** `shortcode_media` (پاسخِ embed) و
    `xdt_shortcode_media` (پاسخِ GraphQL). تک‌کلیده نوشتنش ردهٔ آیندهٔ GraphQL را
    بی‌صدا می‌شکند — `instagram.js:301`ِ cobalt هم هر دو را می‌خواند.
    """
    if not isinstance(gql, dict):
        return None
    media = gql.get("shortcode_media") or gql.get("xdt_shortcode_media")
    if not isinstance(media, dict):
        return None
    caption = _caption_of(media)

    sidecar = media.get("edge_sidecar_to_children")
    if isinstance(sidecar, dict):
        edges = sidecar.get("edges")
        if isinstance(edges, list) and edges:
            items: list[InstagramAnonItem] = []
            for i, edge in enumerate(edges):
                node = (edge or {}).get("node") if isinstance(edge, dict) else None
                if not isinstance(node, dict):
                    continue
                item = _child_item(node, i)
                if item is not None:
                    items.append(item)
            if items:
                return CONTENT_CAROUSEL, tuple(items), caption
            return None

    # تک‌آیتم. همان قاعدهٔ `_child_item` این‌جا هم اعمال می‌شود: پستی که خودش را
    # ویدیو اعلام کند ولی `video_url` نداشته باشد نباید به‌صورتِ عکس تحویل شود.
    if media.get("is_video") and not media.get("video_url"):
        raise _VideoUrlMissing("single: is_video but no video_url")
    vurl = media.get("video_url")
    if _is_media_url(vurl):
        return CONTENT_SINGLE_VIDEO, (InstagramAnonItem("video", vurl),), caption
    durl = media.get("display_url")
    if _is_media_url(durl):
        return CONTENT_SINGLE_PHOTO, (InstagramAnonItem("photo", durl),), caption
    return None


def _best_srcset(srcset: str) -> str | None:
    """بزرگ‌ترین کاندیدِ `srcset` → URL (بدونِ escapeهای HTML).

    دو چیز این‌جا باربر است و هر دو اندازه‌گیری شده‌اند:

    **۱) عرض باید به انتهای توکن مقید باشد.** هر کاندید جدا می‌شود و عرضش با
    `\\s(\\d+)w$` از **آخرِ** همان توکن خوانده می‌شود. با رجکسِ شلِ `(\\d+)w` و
    `re.search` (که اولین تطبیق را می‌دهد) عددِ داخلِ URLِ امضاشده برداشته
    می‌شود: روی فیکسچرِ واقعی کاندیدِ `3072w` را `9` می‌خواند و برندهٔ نهایی
    URLِ دیگری می‌شود.

    **۲) خروجی باید unescape شود.** `srcset` داخلِ HTML است، پس `&` در آن
    `&amp;` نوشته شده؛ بدونِ `html.unescape` پارامترهای امضا خراب به CDN
    می‌رفتند. (مسیرِ `gql_data` این مشکل را **ندارد** — آن‌جا `json.loads`
    خودش escapeها را باز کرده، و اندازه‌گیری‌شده هیچ entity‌ای نمانده.)
    """
    best_w, best_url = -1, None
    for token in (srcset or "").split(","):
        token = token.strip()
        if not token:
            continue
        m = _SRCSET_W_RE.search(token)
        if not m:
            continue
        width = int(m.group(1))
        if width > best_w:
            best_w, best_url = width, token[:m.start()].strip()
    return _html.unescape(best_url) if best_url else None


def extract_from_img(page: str) -> tuple[str, tuple[InstagramAnonItem, ...], str | None] | None:
    """fallbackِ فرمِ PolarisEmbedSimple: عکس از `<img class="EmbeddedMediaImage">`.

    **فقط وقتی صدا زده می‌شود که `gql_data` چیزی نداده باشد** — مسیرِ موازی
    نیست. در فیکسچرِ واقعیِ این حالت `contextJSON` مقدارش `null` است (نه غایب)
    و `isRichEmbed` هم `False` است، پس نه گیت روی فلگ‌ها درست است و نه چکِ
    «کلید موجود است».

    کپشن این‌جا `None` می‌ماند: متنش در HTML هست (`class="Caption"`) ولی
    استخراجش کارِ خودش را می‌خواهد — ببین §۷.
    """
    tag = _EMBEDDED_IMG_RE.search(page or "")
    if not tag:
        return None
    tag_text = tag.group(0)
    ss = _SRCSET_RE.search(tag_text)
    url = _best_srcset(ss.group(1)) if ss else None
    if not url:                                # بدونِ srcset (یا همه بی‌توصیف‌گر) → src
        m = _SRC_RE.search(tag_text)
        url = _html.unescape(m.group(1)) if m else None
    if not _is_media_url(url):
        return None
    return CONTENT_SINGLE_PHOTO, (InstagramAnonItem("photo", url),), None


def parse_embed_page(page: str) -> tuple[tuple[str, tuple[InstagramAnonItem, ...], str | None] | None, str]:
    """صفحهٔ embed → (رسانه، علتِ شکست). دو زیرشاخهٔ **ترتیبی**.

    شکستِ بلاکِ `init` مسیرِ img را نمی‌بندد: تگِ عکس در خودِ HTML است و مستقل
    از آن بلاک خوانده می‌شود.
    """
    gql: dict | None = None
    parse_note = ""
    m = _INIT_RE.search(page or "")
    if m:
        try:
            init = json.loads(m.group(1))
        except ValueError as exc:
            init, parse_note = None, f"init block is not JSON: {exc}"[:150]
        if isinstance(init, dict):
            cj = init.get("contextJSON")
            # `if cj` عمدی است، نه «کلید موجود است»: در فرمِ تک‌عکسی کلید
            # **هست** ولی مقدارش `null` است.
            #
            # نکته‌ای که سرِ سابوتاژ درآمد و ارزشِ ماندن دارد: این خط و
            # `isinstance(cj, str)` پایین **دو دفاعِ مستقل**اند و هرکدام
            # به‌تنهایی جلوی `json.loads(None)` را می‌گیرد. یعنی خراب‌کردنِ
            # فقط یکی‌شان هیچ تستی را نمی‌اندازد — و آن «نگرفت» شبیهِ تستِ
            # ضعیف به‌نظر می‌رسد در حالی که نیست. ورودیِ سابوتاژ عمداً هر دو
            # را با هم برمی‌دارد.
            if cj:
                try:
                    ctx = json.loads(cj) if isinstance(cj, str) else cj
                    gql = ctx.get("gql_data") if isinstance(ctx, dict) else None
                except ValueError as exc:
                    parse_note = f"contextJSON is not JSON: {exc}"[:150]
    else:
        parse_note = "no init block in the embed page"

    media = extract_from_gql(gql)               # `_VideoUrlMissing` عمداً بالا می‌رود
    if media is not None:
        return media, ""
    media = extract_from_img(page)              # ← فقط حالا، نه موازی
    if media is not None:
        return media, ""
    return None, parse_note


def _verdict_of(rungs: tuple[RungReport, ...]) -> str:
    """حکمِ کلی از روی ردهٔ embed. فاز ۲ روی همین تصمیم می‌گیرد."""
    embed = next((r for r in rungs if r.rung == "embed"), None)
    if embed is None:
        return V_UNSUPPORTED
    if embed.ok:
        return V_OK
    if embed.reason == R_NETWORK:
        return V_NETWORK
    if embed.reason == R_LOGIN_REQUIRED:
        return V_BLOCKED
    if embed.reason == R_HTTP_ERROR:
        st = embed.status or 0
        if st in (401, 403, 429):
            return V_BLOCKED
        if st >= 500:
            # خطای سمتِ سرور تقصیرِ ما و تقصیرِ هیچ اکانتی نیست؛ مثلِ قطعیِ شبکه
            # رفتار می‌کند تا فاز ۲ ضربه‌ای به استخر نزند.
            return V_NETWORK
    return V_UNSUPPORTED


# ── شبکه ────────────────────────────────────────────────────────
def _new_session(opts: dict):
    """سشنِ aiohttp با **همان** سیاستِ ضدِ SSRFِ موتورِ `direct`.

    `_direct_connector` سه‌حالته است (بی‌پروکسی → رزولورِ وتوکننده · http → بدونِ
    آن · socks → `ProxyConnector`). استفادهٔ دوباره از آن عمدی است: یک سیاست،
    نه دو کپیِ دست‌نویس که واگرا می‌شوند.
    """
    import aiohttp
    return aiohttp.ClientSession(connector=D._direct_connector(opts))


async def _get_text(session, url: str, headers: dict, opts: dict,
                    timeout: float) -> tuple[int | None, str, str]:
    """(status, body, transport_error). `status is None` یعنی اصلاً جواب نگرفتیم."""
    import aiohttp
    try:
        async with session.get(url, headers=headers,
                               proxy=D._http_proxy(opts.get("proxy")),
                               timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            return resp.status, await resp.text(), ""
    except asyncio.TimeoutError:
        return None, "", "timeout"
    except (aiohttp.ClientError, OSError) as exc:   # OSError = وتوی رزولورِ SSRF
        return None, "", f"{type(exc).__name__}: {exc}"[:150]


async def _rung_oembed(session, shortcode: str, opts: dict) -> tuple[str | None, RungReport]:
    """رده A — `media_id`. **هرگز نردبون را نمی‌شکند**؛ فقط تشخیصی."""
    status, body, err = await _get_text(session, _OEMBED.format(sc=shortcode),
                                        _OEMBED_HEADERS, opts, _OEMBED_TIMEOUT)
    if status is None:
        return None, RungReport("oembed", False, R_NETWORK, None, err)
    if status != 200:
        reason = R_LOGIN_REQUIRED if "login_required" in body.lower() else R_HTTP_ERROR
        return None, RungReport("oembed", False, reason, status, body[:150])
    try:
        media_id = json.loads(body).get("media_id")
    except (ValueError, AttributeError):
        return None, RungReport("oembed", False, R_PARSE_FAILED, status, "body is not JSON")
    if not media_id:
        return None, RungReport("oembed", False, R_NO_MEDIA, status, "no media_id in response")
    return str(media_id), RungReport("oembed", True, R_OK, status)


async def _rung_embed(session, shortcode: str, opts: dict):
    """رده B — رسانه از صفحهٔ embed. → (رسانه|None، RungReport)."""
    status, body, err = await _get_text(session, _EMBED.format(sc=shortcode),
                                        _EMBED_HEADERS, opts, _EMBED_TIMEOUT)
    if status is None:
        return None, RungReport("embed", False, R_NETWORK, None, err)
    if status != 200:
        reason = R_LOGIN_REQUIRED if "login_required" in body.lower() else R_HTTP_ERROR
        return None, RungReport("embed", False, reason, status, body[:150])
    try:
        media, note = parse_embed_page(body)
    except _VideoUrlMissing as exc:
        # علتِ **مشخص**، نه یک no_mediaِ ژنریک: تله‌متریِ فاز ۲ باید بتواند این
        # را از «پستی که اصلاً رسانه ندارد» جدا کند.
        log.warning("instagram anon: dropping %s to the cookie path — %s "
                    "(delivering the poster frame instead would be the wrong file)",
                    shortcode, exc.detail)
        return None, RungReport("embed", False, R_NO_MEDIA, status, exc.detail)
    if media is None:
        return None, RungReport("embed", False,
                                R_PARSE_FAILED if note else R_NO_MEDIA, status, note)
    return media, RungReport("embed", True, R_OK, status)


async def resolve_detailed(url: str, opts: dict | None = None, *, session=None,
                           with_oembed: bool = False) -> InstagramAnonOutcome:
    """نسخهٔ کاملِ نردبون + گزارشِ هر رده (برای تله‌متری و ابزارِ probe).

    `opts` همان دیکشنریِ `tasks_download._opts()` است — از آن فقط `proxy`،
    `user_agent` و `direct_proxy` خوانده می‌شود. **کلیدِ `cookies` عمداً نادیده
    گرفته می‌شود**، تا فراخوان بتواند بدونِ فکرکردن همان opts را پاس بدهد.

    `with_oembed` پیش‌فرض خاموش است: `media_id` را هیچ‌کس مصرف نمی‌کند (رده
    `api/v1/media/<id>/info/` از IPِ ما ۴۰۳ می‌دهد و ساخته نشد) و یک
    رفت‌وبرگشتِ اضافه روی **هر** دانلود هزینه دارد. ابزارِ probe روشنش می‌کند.
    """
    opts = opts or {}
    shortcode = shortcode_of(url)
    if not shortcode:
        rungs = (RungReport("embed", False, R_BAD_URL, None, "no shortcode in the url"),)
        log.info("instagram anon: %r carries no post shortcode — not an anonymous case", url[:120])
        return InstagramAnonOutcome(None, rungs, V_UNSUPPORTED)

    own_session = session is None
    session = session if session is not None else _new_session(opts)
    rungs: list[RungReport] = []
    try:
        media_id = None
        if with_oembed:
            media_id, report = await _rung_oembed(session, shortcode, opts)
            rungs.append(report)
        else:
            rungs.append(RungReport("oembed", False, R_SKIPPED, None, "with_oembed=False"))
        media, report = await _rung_embed(session, shortcode, opts)
        rungs.append(report)
    finally:
        if own_session:
            await session.close()

    tup = tuple(rungs)
    if media is None:
        # تنها هشدارِ «کلِ مسیرِ ناشناس افتاد» — یک خط، با علتِ هر رده. سکوت
        # این‌جا یعنی گذار به کوکی نامرئی شود، و §۷ صریح است که همان سکوت یک
        # پارسرِ مردهٔ اسپاتیفای را هفته‌ها پنهان کرد.
        verdict = _verdict_of(tup)
        log.warning("instagram anon failed for %s (verdict=%s): %s",
                    shortcode, verdict, " | ".join(str(r) for r in tup))
        return InstagramAnonOutcome(None, tup, verdict)

    content, items, caption = media
    result = InstagramAnonResult(shortcode=shortcode, content=content, items=items,
                                 via="embed", media_id=media_id, caption=caption)
    log.info("instagram anon ok: %s → %s, %d item(s) via embed",
             shortcode, content, len(items))
    return InstagramAnonOutcome(result, tup, V_OK)


async def resolve(url: str, opts: dict | None = None, *,
                  session=None) -> InstagramAnonResult | None:
    """لینکِ اینستاگرام → رسانه، **بدونِ کوکی**. None یعنی «مسیرِ ناشناس نشد».

    فاز ۲ روی `None` به مسیرِ کوکی برمی‌گردد. اگر لازم است بداند **چرا** نشد
    (که برای تصمیمِ «آیا این شکست را پای اکانت بنویسم؟» لازم است)،
    `resolve_detailed` را صدا بزند و `verdict` را بخواند.
    """
    return (await resolve_detailed(url, opts, session=session)).result


# ── فاز ۲: از URL به بایت ────────────────────────────────────────
#: زیرشاخهٔ اختصاصیِ پاسِ ناشناس داخلِ workdirِ جاب. **جداسازی، نه سلیقه**: اگر
#: ۶ آیتم از ۱۱ تا بیاید و بعد بیفتد، آن فایل‌ها نباید در workdir بمانند تا
#: مسیرِ کوکی هم رویش بریزد و تحویل یک مخلوطِ خراب ببیند.
ANON_DIR = "igan"

#: کرانِ زمانیِ **کلِ** حلقهٔ دانلود (رزولو جداست و خودش ۲۵ ثانیه سقف دارد).
#: چرا لازم است: `download_direct` با `ClientTimeout(total=None, connect=30,
#: sock_read=120)` کار می‌کند، یعنی هیچ کرانِ کلی per-item ندارد — برای یک فایلِ
#: تکی درست است، ولی این‌جا در N آیتم ضرب می‌شود و تنها کرانِ باقی‌مانده
#: `job_timeout`ِ ۵۴۰۰ ثانیه‌ایِ ورکر است. این پاس **گمانه‌زنی** است: اگر نگرفت
#: باید سریع کنار برود تا مسیرِ کوکی وقت داشته باشد، نه اینکه اسلاتِ دانلود را
#: یک ساعت نگه دارد و بعد تازه مسیرِ اصلی شروع شود.
ANON_FETCH_BUDGET = 300.0


@dataclass(frozen=True)
class InstagramAnonFetch:
    """خروجیِ `download_anonymous` — شکلی که `run_download` مستقیم مصرف می‌کند."""

    #: دقیقاً شکلِ `paths`ِ `run_download`: (مسیر، info، thumb)
    paths: tuple[tuple[str, dict, None], ...] = ()
    caption: str | None = None
    bucket: str = B_SKIPPED

    @property
    def won(self) -> bool:
        return self.bucket == B_OK and bool(self.paths)


def _slice_progress(progress, index: int, total: int):
    """درصدِ per-item را به درصدِ کلِ پست تبدیل می‌کند.

    بدونِ این، کاروسلِ ۱۱تایی نوار را یازده بار از ۰ تا ۹۹ می‌بَرد.
    """
    if progress is None or total <= 0:
        return None

    async def _cb(pct: float) -> None:
        await progress((index * 100.0 + max(0.0, min(100.0, pct))) / total)

    return _cb


def _ordered_name(path: str, shortcode: str, index: int) -> str:
    """فایل را به `<shortcode>_<NN><ext>` تغییرِ نام می‌دهد و مسیرِ تازه را می‌دهد.

    نامی که `direct_filename` از مسیرِ CDN درمی‌آورد **مرتب نیست** (اندازه‌گیری‌شده:
    `469847721_18072_n.jpg`)، پس نه روی کارت خوانا است و نه ترتیبِ کاروسل را
    نگه می‌دارد. ترتیبِ واقعی از **ساختِ** فهرست می‌آید نه از `sorted()` — این
    نام‌گذاری فقط برای خوانایی و برای اینکه دو آیتم نامِ یکسان نگیرند است.
    """
    ext = os.path.splitext(path)[1] or ".bin"
    dest = os.path.join(os.path.dirname(path), f"{shortcode}_{index:02d}{ext}")
    if dest != path:
        os.replace(path, dest)
    return dest


async def download_anonymous(url: str, workdir: str, opts: dict | None = None, *,
                             max_bytes: int = 0, progress=None, cancel=None,
                             session=None,
                             budget: float = ANON_FETCH_BUDGET) -> InstagramAnonFetch:
    """لینکِ اینستاگرام → فایل‌های روی دیسک، **بدونِ لمسِ هیچ اکانتی**.

    بایت‌ها را `downloader.download_direct` می‌کشد، نه یک لوپِ دست‌نویس. چه چیزی
    از آن ارث می‌رسد: `_direct_connector` (همان رزولورِ ضدِTOCTOU/پروکسیِ سیاستِ
    موتورِ `direct`)، `_follow` (هر پرشِ ریدایرکت دوباره `is_safe_url` می‌خورد)،
    سقفِ **دولایه** با حذفِ فایلِ نیمه‌کاره، و قراردادِ progress/cancel. و مهم‌تر:
    آن تابع کلیدِ `opts["cookies"]` را **اصلاً نمی‌خواند**، پس قاعدهٔ بنیادیِ این
    ماژول رایگان حفظ می‌شود. نوشتنِ یک لوپِ جدا یعنی چکِ per-hopِ `_follow`
    بازنویسی شود — همان «دو کپیِ دست‌نویس از یک قاعده واگرا می‌شوند» که §۷ برای
    `remove_cookie_file` ثبت کرده.

    `max_bytes` سقفِ **تجمعی** است: بودجهٔ باقی‌مانده به هر آیتم پاس داده می‌شود،
    پس کاروسلِ پرحجم وسطِ راه می‌ایستد به‌جای اینکه ۱۱ فایل بکشد و بعد در چکِ
    حجمِ `run_download` بیفتد.

    شکست هیچ‌وقت استثنا نمی‌دهد (جز لغو، که باید بالا برود): `bucket` را بخوان.
    """
    opts = opts or {}
    shortcode = shortcode_of(url)
    if not shortcode:
        # استوری و لینکِ پروفایل: **قبل از هر کاری** بیرون. نه سشنی ساخته
        # می‌شود، نه درخواستی می‌رود — این حالت‌ها مسیرِ ناشناس ندارند (cobalt هم
        # استوری را بی‌کوکی رد می‌کند) و باید مستقیم به کوکی بروند.
        return InstagramAnonFetch(bucket=B_SKIPPED)

    out = await resolve_detailed(url, opts, session=session)
    if out.result is None:
        # `resolve_detailed` خودش یک `log.warning` با علتِ هر رده زده است.
        return InstagramAnonFetch(bucket=out.verdict)

    res = out.result
    outdir = os.path.join(workdir, ANON_DIR)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget
    paths: list[tuple[str, dict, None]] = []
    done = False
    try:
        os.makedirs(outdir, exist_ok=True)
        remaining, total = max_bytes, len(res.items)
        for i, item in enumerate(res.items):
            left = deadline - loop.time()
            if left <= 0:
                raise TimeoutError(
                    f"anonymous fetch budget of {budget:.0f}s exhausted at item {i}")
            # هر آیتم در زیرشاخهٔ خودش: نامِ CDN می‌تواند تکراری باشد و آن‌وقت
            # آیتمِ دوم روی اولی می‌نوشت — **حینِ** دانلود، یعنی پیش از تغییرِ نام.
            itemdir = os.path.join(outdir, f"{i:02d}")
            os.makedirs(itemdir, exist_ok=True)
            path, info = await asyncio.wait_for(
                D.download_direct(item.url, itemdir, opts, max_bytes=remaining,
                                  progress=_slice_progress(progress, i, total),
                                  cancel=cancel),
                timeout=left)
            path = _ordered_name(path, res.shortcode, i)
            if remaining:
                # هرگز به ۰ نرسد: در `download_direct` صفر یعنی «بی‌سقف».
                # ۱ یعنی آیتمِ بعدی قطعاً `DirectTooLarge` می‌گیرد، که همان
                # چیزی است که می‌خواهیم — سقف واقعاً تمام شده.
                remaining = max(1, remaining - os.path.getsize(path))
            paths.append((path, info, None))
        done = True
    except ProcessingCancelled:
        raise                       # لغوِ کاربر مالِ `run_download` است، نه ما
    except Exception as exc:  # noqa: BLE001
        # resolve موفق بود ولی بایت‌ها نیامدند. سطلِ جدا، چون این حالت **کوکی
        # می‌سوزاند** (به مسیرِ کوکی می‌افتیم) و نباید با `ok` قاطی شود.
        log.warning("instagram anon: %s resolved but the fetch failed (%s) — "
                    "falling through to the cookie path",
                    res.shortcode, f"{type(exc).__name__}: {exc}"[:150])
        return InstagramAnonFetch(bucket=B_FETCH_FAILED)
    finally:
        # قیدِ جداسازی: هر خروجی‌ای جز موفقیتِ **کامل** باید workdir را دقیقاً
        # به حالتِ قبل از خودش برگرداند. در `finally` است تا لغو و
        # `CancelledError` (که `except Exception` نمی‌گیردش) هم پوشش بگیرند.
        if not done:
            shutil.rmtree(outdir, ignore_errors=True)

    return InstagramAnonFetch(tuple(paths), res.caption, B_OK)
