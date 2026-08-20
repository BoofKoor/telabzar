"""متن‌های **خودِ پنل** (نه متن‌های ربات).

سه چیز این ماژول را از `app/i18n.py` جدا می‌کند و هر سه قید‌اند نه سلیقه:

* **مخاطبش فرق دارد.** `i18n`/`textstore` متنی را می‌دهد که *کاربرِ ربات*
  می‌بیند و ادمین از `/texts` ویرایشش می‌کند. این‌جا رابطِ خودِ پنل است —
  ادمین نباید بتواند نامِ منوی پنل را عوض کند و بعد راهِ برگشت را گم کند.
* **بدونِ دیتابیس و بدونِ Redis.** یک دیکشنریِ خالصِ پایتون است، پس رندرِ هر
  صفحه صفر رفت‌وبرگشت اضافه می‌کند و تست می‌تواند بدونِ هیچ سرویسی بسنجدش.
* **بدونِ وابستگی به `admin_web`.** آن ماژول `jinja2`/`cryptography` می‌خواهد
  که در `requirements-dev.txt` نیستند، پس هر چیزی که تستِ jobِ اصلی باید
  ببیند نمی‌تواند آن‌جا زندگی کند — همان قیدی که `cookies.py`، `dl_active.py`
  و `langpack.py` را سرِ جایشان نشانده.

`fa` پیش‌فرض است و **رفتارِ امروز را عوض نمی‌کند**: کلیدِ بدونِ ترجمهٔ انگلیسی
به فارسی برنمی‌گردد بلکه به خودِ کلید می‌افتد، تا جاافتادگی **دیده** شود نه
اینکه بی‌صدا فارسی رندر شود روی صفحه‌ای که کاربرش انگلیسی خواسته.
"""
from __future__ import annotations

#: زبان‌های رابطِ پنل. عمداً بسته است: این فهرست با `/langs` (زبان‌های ربات)
#: هیچ نسبتی ندارد و نباید داشته باشد.
LANGS: dict[str, str] = {"fa": "فارسی", "en": "English"}
DEFAULT = "fa"
#: جهتِ نوشتار، برای `<html dir>` — سرورساید رندر می‌شود تا FOUC نداشته باشیم.
DIR = {"fa": "rtl", "en": "ltr"}

#: پوسته‌ها. `auto` یعنی «هرچه سیستمِ کاربر می‌گوید» (هیچ `data-theme`ی روی
#: `<html>` نمی‌نشیند و مدیا-کوئری تصمیم می‌گیرد).
THEMES = ("auto", "light", "dark")

STRINGS: dict[str, dict[str, str]] = {
    # ── پوسته ──────────────────────────────────────────────────
    "brand":            {"fa": "تل‌ابزار",            "en": "TELABZAR"},
    "brand.sub":        {"fa": "پنلِ مدیریت",          "en": "admin console"},
    "chrome.admin":     {"fa": "ادمین",               "en": "admin"},
    "chrome.logout":    {"fa": "خروج",                "en": "logout"},
    "chrome.all_ok":    {"fa": "همه سرویس‌ها آنلاین",  "en": "all systems nominal"},
    "chrome.degraded":  {"fa": "بررسیِ سرویس‌ها",      "en": "check services"},
    "chrome.theme":     {"fa": "پوسته",               "en": "theme"},
    "chrome.lang":      {"fa": "زبان",                "en": "language"},
    "chrome.uptime":    {"fa": "آپ‌تایم",              "en": "uptime"},
    "chrome.disk":      {"fa": "دیسک",                "en": "disk"},
    "chrome.queue":     {"fa": "صف",                  "en": "queue"},
    "chrome.active":    {"fa": "فعال",                "en": "active"},
    "chrome.nodes":     {"fa": "نودها",               "en": "nodes"},
    "chrome.mesh":      {"fa": "شبکهٔ نودها",          "en": "node mesh"},
    "chrome.none":      {"fa": "بدونِ نود",            "en": "no nodes"},

    # ── منو ────────────────────────────────────────────────────
    "grp.control":      {"fa": "کنترل",               "en": "control"},
    "grp.system":       {"fa": "سیستم",               "en": "system"},
    "grp.content":      {"fa": "محتوا",               "en": "content"},
    "grp.data":         {"fa": "داده",                "en": "data"},
    "nav.settings":     {"fa": "تنظیمات",             "en": "settings"},
    "nav.users":        {"fa": "کاربران",             "en": "users"},
    "nav.cookies":      {"fa": "کوکی‌ها",              "en": "sessions"},
    "nav.health":       {"fa": "سلامت",               "en": "health"},
    "nav.nodes":        {"fa": "نودها",               "en": "nodes"},
    "nav.texts":        {"fa": "متن‌ها",               "en": "texts"},
    "nav.buttons":      {"fa": "کلیدها",              "en": "buttons"},
    "nav.langs":        {"fa": "زبان‌ها",              "en": "languages"},
    "nav.stats":        {"fa": "آمار",                "en": "stats"},

    # ── عنوانِ صفحه ────────────────────────────────────────────
    "page.settings":    {"fa": "تنظیمات",             "en": "Settings"},
    "page.users":       {"fa": "کاربران",             "en": "Users"},
    "page.cookies":     {"fa": "اکانت‌های کوکی",       "en": "Session accounts"},
    "page.health":      {"fa": "سلامتِ سیستم",         "en": "System health"},
    "page.nodes":       {"fa": "نودهای توزیع‌شده",     "en": "Distributed nodes"},
    "page.texts":       {"fa": "متن‌ها و لیبل‌ها",      "en": "Texts and labels"},
    "page.buttons":     {"fa": "استایل و چیدمانِ کلیدها", "en": "Button style and layout"},
    "page.langs":       {"fa": "زبان‌ها",              "en": "Languages"},
    "page.stats":       {"fa": "آمار",                "en": "Stats"},
    "page.login":       {"fa": "ورود",                "en": "Sign in"},

    # ── مشترک ─────────────────────────────────────────────────
    "c.saved":          {"fa": "ذخیره شد",            "en": "saved"},
    "c.search":         {"fa": "جست‌وجو",              "en": "search"},
    "c.clear":          {"fa": "پاک‌کردن",             "en": "clear"},
    "c.delete":         {"fa": "حذف",                 "en": "delete"},
    "c.save":           {"fa": "ذخیره",               "en": "save"},
    "c.cancel":         {"fa": "انصراف",              "en": "cancel"},
    "c.total":          {"fa": "کل",                  "en": "total"},
    "c.today":          {"fa": "امروز",               "en": "today"},
    "c.none":           {"fa": "چیزی نیست",           "en": "nothing here"},

    # ── واژگانِ دامنه ─────────────────────────────────────────
    # این‌ها عمداً **ترجمه** می‌شوند و به لاتین کوتاه نمی‌شوند: «آنلاین» و
    # «خطا» چیزی است که ادمینِ فارسی‌زبان با یک نگاه می‌خواند، و جایگزینیِ
    # آن با `UP`/`ERR` به‌خاطرِ ظاهر، یک ازدست‌رفتنِ کاربردی است نه یک تصمیمِ
    # بصری. تست‌های `tests/panel` دقیقاً همین جفت‌ها را می‌سنجند.
    "h.online":         {"fa": "آنلاین",               "en": "online"},
    "h.error":          {"fa": "خطا",                  "en": "error"},
    "h.unset":          {"fa": "پیکربندی‌نشده",         "en": "not configured"},
    "h.probing":        {"fa": "در حالِ بررسی…",        "en": "probing…"},
    "h.healthy":        {"fa": "سالم",                 "en": "healthy"},
    "h.offline":        {"fa": "آفلاین",               "en": "offline"},
    "h.blocked":        {"fa": "بلاک",                 "en": "blocked"},
    "h.active":         {"fa": "فعال",                 "en": "active"},
    "h.node":           {"fa": "نود",                  "en": "nodes"},
    "h.page_of":        {"fa": "صفحهٔ {a} از {b}",      "en": "page {a} of {b}"},
    "h.no_users":       {"fa": "کاربری یافت نشد.",      "en": "no users found."},
    "h.no_nodes":       {"fa": "هنوز نودی وصل نشده. با «افزودن نود» یک دستورِ نصب بساز.",
                         "en": "no node has joined yet — build an install command below."},
    "h.no_cookies":     {"fa": "کوکی‌ای ثبت نشده.",      "en": "no session account yet."},
    "h.no_engine":      {"fa": "هنوز ورکرِ دانلودی نسخه‌اش را گزارش نکرده (پس از ری‌استارتِ بعدی می‌آید).",
                         "en": "no download worker has reported a version yet (arrives after the next restart)."},
    "h.no_errors":      {"fa": "خطایی ثبت نشده.",       "en": "no error recorded."},
    "h.no_match":       {"fa": "چیزی مطابقِ «{q}» پیدا نشد.",
                         "en": "nothing found matching «{q}»."},
    "h.today_utc":      {"fa": "امروز (UTC)",           "en": "today (UTC)"},
    "h.no_downloads":   {"fa": "بدونِ دانلود",           "en": "excludes downloads"},
    "h.file_source":    {"fa": "منبعِ فایل",             "en": "file source"},
    "h.upload":         {"fa": "آپلودِ کاربر",           "en": "user upload"},
    "h.from_link":      {"fa": "دانلود از لینک",         "en": "downloaded from link"},
}


def pt(lang: str, key: str, **kw) -> str:
    """متنِ پنل. زبانِ ناشناخته → پیش‌فرض؛ کلیدِ ناشناخته → خودِ کلید.

    برگرداندنِ **خودِ کلید** عمدی است: یک کلیدِ جاافتاده باید روی صفحه دیده
    شود، نه اینکه بی‌صدا به فارسی بیفتد روی پنلی که کاربر انگلیسی خواسته —
    همان تفکیکی که §۷ برای «fallbackی که بی‌صدا به دادهٔ بی‌مصرف تنزل می‌کند»
    ثبت کرده.
    """
    row = STRINGS.get(key)
    if row is None:
        return key
    txt = row.get(lang) or row.get(DEFAULT) or key
    if kw:
        try:
            return txt.format(**kw)
        except (KeyError, IndexError, ValueError):
            return txt
    return txt


def normalize_lang(value: str | None) -> str:
    return value if value in LANGS else DEFAULT


def normalize_theme(value: str | None) -> str:
    return value if value in THEMES else "auto"
