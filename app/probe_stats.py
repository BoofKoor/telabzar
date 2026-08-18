"""شمارندهٔ فازِ probe — **فقط اندازه‌گیری**، صفر تغییرِ رفتار.

چرا هست: فازِ probe گران است و در هیچ شمارنده‌ای دیده نمی‌شود. بی‌قیدوشرط کوکی
برمی‌دارد (`tasks_download.run_download`، شاخهٔ `phase == "probe"`)، ولی
`note_spend` صدا زده نمی‌شود پس سطلِ ساعتیِ اکانت به آن کور است، از `dl_active`
و از `_charge` رد می‌شود، و probeِ **موفق** حتی یک `dlstat` هم نمی‌نویسد —
`_metric` در آن شاخه فقط روی شکست است. یعنی «۱۰۰ لینک = ۱۰۰ منو = ۱۰۰ کوکی =
صفر شارژ» امروز در هیچ عددی پیدا نیست.

تصمیم (اپراتور): **اول شمارنده، بعد رفع.** شکلِ رفع به نرخِ رهاشدن بستگی دارد
و آن عدد امروز وجود ندارد؛ ۲٪ یعنی تئوریک و ۶۰٪ یعنی فوری. این ماژول آن عدد را
می‌سازد و **هیچ‌چیزِ دیگری را عوض نمی‌کند** — نه `note_spend`، نه `dl_active`،
نه `_charge`.

این ماژول عمداً **هیچ وابستگی‌ای** ندارد (مثلِ `dl_active.py`): شمارنده هم در
ورکرِ دانلود نوشته می‌شود (`tasks_download`) هم در پروسهٔ ربات
(`routers/download.on_dl_pick`)، و ایمیجِ ربات استکِ پردازش را ندارد —
`tasks_download` سرِ import `processing`/`instagram_anon` می‌آورد، پس روتر
نمی‌تواند از آن‌جا قرض بگیرد. کپیِ دومِ دست‌نویسِ همان `INCR`+`EXPIRE` هم همان
واگرایی است که §۷ برای `remove_cookie_file` ثبت کرده. یک پیاده‌سازی، دو مصرف‌کننده.

── سطل‌ها ─────────────────────────────────────────────────────────────
    probeهای اجراشده = fail + blocked + menu
    رهاشده           = menu − pick − menucancel

`blocked` **باید** از `menu` جدا بماند و این نکتهٔ کلِ طراحی است: خروجی‌های
ردِ محتوای بزرگسال و «مدت زیاد» probeِ *موفق*اند که هرگز به منو نمی‌رسند، پس
هرگز pick‌شدنی نیستند. ریختنشان در یک سطلِ «ok» یعنی هر لینکِ سنی/بلند به‌عنوان
«رهاشده» شمرده شود — یعنی دقیقاً عددی که کلِ تصمیم رویش بناست غلط دربیاید.

`attempt` جدا از تعدادِ probe است، چون حلقهٔ چرخشِ کوکی تا
`dl_max_cookie_tries` بار موتور را صدا می‌زند. **سؤالِ واقعی مصرفِ منبع است**،
و واحدِ آن تلاش است نه جاب. روی سطلِ پرِ کوکی هر تلاش یک اکانت هم خرج می‌کند
(`_next_cookie` → `ck.pick` + `note_use`)، پس آن‌جا `attempt` = مصرفِ کوکی.

── چرا نشانگر، و نه تفاضلِ خام ────────────────────────────────────────
یک منو می‌تواند **چند** pick بدهد (کامنتِ خودِ `run_download`: «`on_dl_pick`
می‌تواند از یک منو چند کیفیت را پشتِ‌هم بفرستد»)، پس `menu − pick`ِ خام
می‌تواند منفی شود و خطایش کران ندارد. نشانگرِ `probemenu:{ref}` با `DELETE`ِ
یک‌بارمصرف این را دقیق می‌کند، و **یک ابهامِ دوم را هم رایگان حل می‌کند**:
`Dl(sel="cancel")` دو تولیدکننده دارد — `download_menu_kb` (منوی کیفیت) و
`download_cancel_kb` (لغوِ دانلودِ در حالِ اجرا، فازِ fetch) — و از روی خودِ
callback تفکیک‌پذیر نیستند. ولی cancelِ فازِ fetch نشانگر ندارد (یا مسیرِ quick
اصلاً نساخته، یا سرِ pick پاک شده)، پس خودبه‌خود شمرده نمی‌شود. `Dl`ِ
**غیرِcancel** ابهام ندارد: `download_menu_kb` تنها تولیدکننده‌اش است و تنها
محلِ فراخوانی‌اش همان شاخهٔ probe است.

`probe:{ref}`ِ موجود عمداً بازاستفاده **نشد** با اینکه هیچ‌کس نمی‌خواندش: §۷
آن را به‌عنوان سنجهٔ اپراتوری ثبت کرده (نسبتش با `dlctx:{ref}` = سهمِ probe)، و
پاک‌کردنش سرِ pick آن نسبت را بی‌صدا از «سهمِ probe» به «سهمِ probeِ رهاشده»
تغییرِ معنا می‌دهد — همان ردهٔ «معنای یک سنجه بی‌صدا عوض می‌شود». ضمناً آن کلید
به ناتهی‌بودنِ `options` گیت خورده، پس منوی بی‌گزینه نشانگر نمی‌گرفت.
"""
from __future__ import annotations

from datetime import datetime, timezone

# TTLِ سطل‌ها: **دقیقاً** همان ۲ روزِ `_metric`/`_iganon_metric`. هر عددِ دیگری
# یعنی این کلیدها با بقیهٔ `dlstat:*` هم‌پنجره نباشند.
TTL = 172800

# TTLِ نشانگر: همان ۱۸۰۰ ثانیهٔ `probe:{ref}` و `dlctx:{ref}` — منو بعد از آن
# به‌هرحال `dl_expired` می‌گیرد، پس نشانگری که بیشتر زنده بماند چیزی نمی‌خرد.
MENU_TTL = 1800

ATTEMPT = "attempt"          # هر فراخوانِ موتور (= مصرفِ کوکی روی سطلِ پر)
FAIL = "fail"                # probe چیزی نداد (حلقهٔ چرخش تمام شد)
BLOCKED = "blocked"          # موفق، ولی سیاست کشتش → هرگز منو نمی‌بیند
MENU = "menu"                # منوی کیفیت به کاربر رسید
PICK = "pick"                # کاربر کیفیت انتخاب کرد (اولین بار روی این منو)
REPICK = "repick"            # pickِ بعدیِ همان منو، یا pick پس از انقضای نشانگر
MENU_CANCEL = "menucancel"   # cancelِ خودِ منو — ردِ صریح، نه رهاشدن

BUCKETS = (ATTEMPT, FAIL, BLOCKED, MENU, PICK, REPICK, MENU_CANCEL)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def key(bucket: str, day: str | None = None) -> str:
    """`dlstat:probe:<bucket>:<YYYYMMDD>` — زیرفضای نام‌دار، مثلِ `dlstat:iganon:*`.

    برخوردی با کارتِ per-platformِ صفحهٔ سلامت ندارد: آن حلقه روی
    `KNOWN_PLATFORMS` می‌گردد (تاپلی از `PLATFORM_LABELS`) و `probe` عضوش نیست —
    همان دلیلی که `iganon` تا امروز تداخل نکرده.
    """
    return f"dlstat:probe:{bucket}:{day or _today()}"


def menu_key(ref: str) -> str:
    return f"probemenu:{ref}"


async def note(redis, bucket: str) -> None:
    """یک سطل را یک واحد بالا ببر — هم‌شکلِ `_metric`.

    مثلِ هر مسیرِ تله‌متریِ این پروژه best-effort است: خطای Redis بلعیده می‌شود،
    چون یک شمارنده هرگز نباید دانلودِ کاربر را بشکند.
    """
    if redis is None:
        return
    k = key(bucket)
    try:
        n = await redis.incr(k)
        if n == 1:
            await redis.expire(k, TTL)
    except Exception:  # noqa: BLE001
        pass


async def _claim(redis, ref: str) -> bool:
    """نشانگر را یک‌بارمصرف بردار: True یعنی این اولین رویدادِ همان منوست."""
    if redis is None:
        return False
    try:
        return bool(await redis.delete(menu_key(ref)))
    except Exception:  # noqa: BLE001
        return False


async def mark_menu(redis, ref: str) -> None:
    """منوی کیفیت رفت: سطلِ `menu` + نشانگرِ گذرا برای dedupeِ pick."""
    await note(redis, MENU)
    if redis is None:
        return
    try:
        await redis.set(menu_key(ref), "1", ex=MENU_TTL)
    except Exception:  # noqa: BLE001
        pass


async def note_pick(redis, ref: str) -> None:
    """کاربر روی منو کیفیت انتخاب کرد.

    عمداً **پیش از** هر گارد دیگری در `on_dl_pick` صدا زده می‌شود: منقضی‌شدنِ
    `dlctx`، سقفِ روزانه و اصابتِ کش هر سه «کاربر دکمه را زد»اند، و شمردنشان در
    جای دیرتر یعنی نشتِ همان‌ها به «رهاشده».
    """
    await note(redis, PICK if await _claim(redis, ref) else REPICK)


async def note_cancel(redis, ref: str) -> None:
    """cancel — فقط وقتی شمرده می‌شود که نشانگر زنده باشد.

    یعنی «cancel روی منویی که هنوز pick نشده». cancelِ یک دانلودِ در حالِ اجرا
    (`download_cancel_kb`) نشانگری ندارد و ساکت رد می‌شود.
    """
    if await _claim(redis, ref):
        await note(redis, MENU_CANCEL)
