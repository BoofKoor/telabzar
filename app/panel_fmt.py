"""قالب‌بندیِ اعداد، تاریخ، حجم و زمان برای پنل — fa/en، خالص و بی‌وابستگی.

**تنها** پیاده‌سازیِ قالب‌بندیِ پنل است: قالب‌ها (Jinja) از این‌جا فیلتر می‌گیرند و
برچسب‌های نمودار هم **پیش‌قالب‌شده** از همین‌جا به JS می‌روند، پس دو پیاده‌سازیِ
«عددِ فارسی» (یکی در پایتون، یکی در مرورگر) وجود ندارد که واگرا شوند.

قراردادِ نمایش (تصمیمِ اپراتور): **کمیت** با رقمِ فارسی (۱٬۲۳۴ · ۹۶٪ · ۱٫۲ گیگابایت)،
**شناسه و رشتهٔ فنی** با رقمِ لاتین (شناسهٔ تلگرام، نسخه، IP، کلیدِ تنظیمات) — آن‌ها
را هیچ تابعی از این ماژول لمس نمی‌کند و قالب آن‌ها را در `<bdi class="ltr">` می‌گذارد.

ساعتِ نمایش **تهران** است با آفستِ ثابتِ ‎+۰۳:۳۰: ایران از ۱۴۰۱ (۲۰۲۲) ساعتِ تابستانی
ندارد، و ایمیجِ slimِ پایتون پایگاهِ داده‌ی منطقهٔ زمانی را تضمین نمی‌کند — آفستِ ثابت
هم درست است هم بی‌وابستگی. تاریخِ فارسی **شمسی** است (`to_jalali`).

بی‌دیتابیس و بی‌وابستگی به `admin_web`، تا jobِ اصلیِ تست بتواند بسنجدش (همان قاعدهٔ
`panel_i18n` و `langpack`).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

#: ساعتِ تهران — ثابت، چون ایران از ۲۰۲۲ تغییرِ ساعت ندارد.
TEHRAN = timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TO_FA = str.maketrans("0123456789", _FA_DIGITS)
#: فارسی **و** عربی به لاتین — کاربرِ فارسی‌زبان روی کیبوردِ گوشی هر دو را می‌زند.
_TO_ASCII = str.maketrans(_FA_DIGITS + _AR_DIGITS, "0123456789" * 2)

FA_THOUSANDS, FA_DECIMAL, FA_PERCENT = "٬", "٫", "٪"

FA_MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
             "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
EN_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December")
EN_MONTHS_SHORT = tuple(m[:3] for m in EN_MONTHS)
#: روزهای هفته با شنبه شروع می‌شوند (تقویمِ ایرانی)؛ اندیس = `(weekday()+2) % 7`.
FA_WEEKDAYS = ("شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه")
EN_WEEKDAYS = ("Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri")


def is_fa(lang: str) -> bool:
    return lang != "en"


# ── ارقام ──────────────────────────────────────────────────────────
def fa_digits(s) -> str:
    """رقم‌های لاتینِ یک رشته را فارسی کن (بقیهٔ نویسه‌ها دست‌نخورده)."""
    return str(s).translate(_TO_FA)


def ascii_digits(s: str) -> str:
    """رقمِ فارسی/عربی → لاتین. برای ورودیِ کاربر (کدِ ورود، شناسه، عددِ تنظیمات).

    `int('۱۲۳')` در پایتون کار می‌کند ولی مقایسهٔ رشته‌ای و کلیدِ Redis نه:
    `'۱۲۳' != '123'`، پس شمارندهٔ نرخِ ورود برای یک ادمین دو سطل می‌ساخت.
    """
    return str(s).translate(_TO_ASCII)


def digits(x, lang: str) -> str:
    """فقط ارقام (بدونِ جداکنندهٔ هزارگان) — برای «۱۰۸۰p» و شمارهٔ سال."""
    s = str(x)
    return fa_digits(s) if is_fa(lang) else s


def num(x, lang: str, d: int | None = None) -> str:
    """عدد با جداکنندهٔ هزارگان؛ `d` = تعدادِ رقمِ اعشار (پیش‌فرض: صحیح)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = f"{x:,.{d}f}" if d is not None else f"{round(x):,}"
    if not is_fa(lang):
        return s
    s = s.replace(",", "\x00").replace(".", FA_DECIMAL).replace("\x00", FA_THOUSANDS)
    return fa_digits(s).replace("-", "−")


def pct(x, lang: str, d: int = 0) -> str:
    """کسرِ ۰..۱ → درصد («۹۶٪» / «96%»)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = num(x * 100, lang, d)
    return s + (FA_PERCENT if is_fa(lang) else "%")


_UNITS_FA = ("بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت")
_UNITS_EN = ("B", "KB", "MB", "GB", "TB")


def size(b, lang: str, d: int | None = None) -> str:
    """حجم (پایهٔ ۱۰۲۴)، با یک رقمِ اعشار زیرِ ۱۰۰ واحد."""
    if b is None:
        return "—"
    v, i = float(b), 0
    while v >= 1024 and i < 4:
        v /= 1024
        i += 1
    dd = d if d is not None else (0 if i == 0 or v >= 100 else 1)
    return f"{num(v, lang, dd)} {(_UNITS_FA if is_fa(lang) else _UNITS_EN)[i]}"


def mb(m, lang: str) -> str:
    return size((m or 0) * 1024 * 1024, lang)


def secs(s, lang: str) -> str:
    """مدتِ خوانا: «۳ دقیقه و ۲۰ ثانیه» / «3m 20s»."""
    if s is None:
        return "—"
    s = int(round(s))
    fa = is_fa(lang)
    if s < 60:
        return f"{num(s, lang)} ثانیه" if fa else f"{s}s"
    m, r = divmod(s, 60)
    if m < 60:
        if fa:
            return f"{num(m, lang)} دقیقه و {num(r, lang)} ثانیه" if r else f"{num(m, lang)} دقیقه"
        return f"{m}m {r}s" if r else f"{m}m"
    h, mm = divmod(m, 60)
    if h < 48:
        if fa:
            return f"{num(h, lang)} ساعت و {num(mm, lang)} دقیقه" if mm else f"{num(h, lang)} ساعت"
        return f"{h}h {mm}m" if mm else f"{h}h"
    days, hh = divmod(h, 24)
    if fa:
        return f"{num(days, lang)} روز و {num(hh, lang)} ساعت" if hh else f"{num(days, lang)} روز"
    return f"{days}d {hh}h" if hh else f"{days}d"


def secs_short(s, lang: str) -> str:
    """مدتِ فشرده برای جدول: «۴۲ ث» · «۳:۰۵» · «۱:۰۲:۰۷»."""
    if s is None:
        return "—"
    s = int(round(s))
    if s < 60:
        return f"{num(s, lang)} ث" if is_fa(lang) else f"{s}s"
    h, rem = divmod(s, 3600)
    m, r = divmod(rem, 60)
    out = f"{h}:{m:02d}:{r:02d}" if h else f"{m}:{r:02d}"
    return digits(out, lang)


# ── تقویم ──────────────────────────────────────────────────────────
def to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """میلادی → شمسی (الگوریتمِ حسابیِ ۳۳ساله؛ برای ۱۹۰۰–۲۱۰۰ دقیق)."""
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100
            + (gy2 + 399) // 400 + gd + g_d_m[gm - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def local(dt: datetime | None) -> datetime | None:
    """زمانِ آگاه یا ساده (فرضِ UTC) → ساعتِ تهران."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TEHRAN)


def weekday_index(d: date) -> int:
    """۰ = شنبه … ۶ = جمعه."""
    return (d.weekday() + 2) % 7


def weekday(d: date, lang: str) -> str:
    return (FA_WEEKDAYS if is_fa(lang) else EN_WEEKDAYS)[weekday_index(d)]


def day_short(d: date | datetime, lang: str) -> str:
    """«۱۶ مهر» / «Oct 8»."""
    if isinstance(d, datetime):
        d = local(d).date()
    if is_fa(lang):
        _y, m, dd = to_jalali(d.year, d.month, d.day)
        return f"{num(dd, lang)} {FA_MONTHS[m - 1]}"
    return f"{EN_MONTHS_SHORT[d.month - 1]} {d.day}"


def day_long(d: date | datetime, lang: str) -> str:
    """«۱۶ مهر ۱۴۰۵» / «October 8, 2026»."""
    if isinstance(d, datetime):
        d = local(d).date()
    if is_fa(lang):
        y, m, dd = to_jalali(d.year, d.month, d.day)
        return f"{num(dd, lang)} {FA_MONTHS[m - 1]} {digits(y, lang)}"
    return f"{EN_MONTHS[d.month - 1]} {d.day}, {d.year}"


def month_label(d: date, lang: str) -> str:
    """«مهر ۱۴۰۵» / «October 2026» — برای برچسبِ نمودارِ ماهانه."""
    if is_fa(lang):
        y, m, _ = to_jalali(d.year, d.month, d.day)
        return f"{FA_MONTHS[m - 1]} {digits(y, lang)}"
    return f"{EN_MONTHS[d.month - 1]} {d.year}"


def hm(dt: datetime | None, lang: str) -> str:
    """«۱۴:۳۰» در ساعتِ تهران."""
    if dt is None:
        return "—"
    return digits(local(dt).strftime("%H:%M"), lang)


def when(dt: datetime | None, lang: str, now: datetime | None = None) -> str:
    """زمانِ مطلقِ کوتاه: امروز → ساعت؛ امسال → روز و ساعت؛ وگرنه تاریخِ کامل."""
    if dt is None:
        return "—"
    now = local(now or datetime.now(timezone.utc))
    lt = local(dt)
    sep = "، " if is_fa(lang) else ", "
    if lt.date() == now.date():
        return hm(dt, lang)
    if abs((now.date() - lt.date()).days) < 300:
        return day_short(lt, lang) + sep + hm(dt, lang)
    return day_long(lt, lang)


def full(dt: datetime | None, lang: str) -> str:
    """«۱۶ مهر ۱۴۰۵، ۱۴:۳۰»."""
    if dt is None:
        return "—"
    return day_long(local(dt), lang) + ("، " if is_fa(lang) else ", ") + hm(dt, lang)


def ago(dt: datetime | float | None, lang: str, now: datetime | None = None) -> str:
    """زمانِ نسبی: «۵ دقیقه پیش» / «5 minutes ago»؛ آینده: «۳ روز دیگر» / «in 3 days»."""
    if dt is None:
        return "—"
    now = now or datetime.now(timezone.utc)
    if isinstance(dt, (int, float)):
        dt = datetime.fromtimestamp(dt, timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = (dt - now).total_seconds()
    a = abs(diff)
    fa = is_fa(lang)
    if a < 45:
        return "همین الان" if fa else "just now"
    for limit, unit, fa_u, en_u in ((3600, 60, "دقیقه", "minute"),
                                    (86400, 3600, "ساعت", "hour"),
                                    (86400 * 30, 86400, "روز", "day"),
                                    (86400 * 365, 86400 * 30, "ماه", "month"),
                                    (math.inf, 86400 * 365, "سال", "year")):
        if a < limit:
            n = max(1, round(a / unit))
            break
    if unit == 86400 and n == 1:
        if fa:
            return "دیروز" if diff < 0 else "فردا"
        return "yesterday" if diff < 0 else "tomorrow"
    if fa:
        return f"{num(n, lang)} {fa_u} {'پیش' if diff < 0 else 'دیگر'}"
    word = en_u + ("" if n == 1 else "s")
    return f"{n} {word} ago" if diff < 0 else f"in {n} {word}"
