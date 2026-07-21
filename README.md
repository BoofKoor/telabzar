# تل‌ابزار — Telabzar

رباتِ مدیریت فایلِ تلگرام: هر فایلی بفرست، نوعش تشخیص داده می‌شود و یک منوی
عملیاتِ اینلاینِ تمیز می‌گیری. **کارت = خودِ فایل**؛ هر عملیات همان کارت را درجا
به‌روزرسانی می‌کند و یک لاگِ تغییرات در کپشن می‌ماند. دوزبانه (فارسی/انگلیسی).

> **وضعیت:** هستهٔ پردازش و تحویل کامل و روی سرور در حالِ کار است. گامِ بعدی
> افزودنِ **دانلودرِ رسانه** (لینک → دانلود → همان pipeline) و **پنلِ ادمینِ وب** است.

---

## چه کاری می‌کند (پیاده‌شده)
- فایل بفرست → تشخیصِ نوع (سند/تصویر/ویدیو/صوت/آرشیو/PDF/اپ) → **کارتِ عملیاتِ اینلاین**.
- **تصویر:** کاهش حجم · تبدیل فرمت · واترمارک · OCR (fa+en) · تغییرِ اندازه · چرخش/آینه · بهبود · حذفِ پس‌زمینه · عکس‌ها→PDF.
- **ویدیو:** کاهش حجمِ هوشمند · تبدیل · واترمارک · کاور · استخراجِ صدا · GIF · برش · اسکرین‌شات · بی‌صدا.
- **صوت:** ویرایشِ اطلاعات (تگ‌ها + کاور) · **رونویسی (Whisper، متن/SRT)** · برش · نرمال‌سازی · سرعت · تبدیل.
- **PDF/سند/آرشیو:** تبدیل فرمت · ادغامِ PDF · تبدیل به PDF · لیست/استخراجِ آرشیو.
- **اسکنِ بدافزار** (ClamAV) برای فایل‌های نصبی/اجرایی و غیره.
- **لینکِ دانلود/استریم** برای هر فایل (سرویسِ gateway، پخشِ Range-based).
- **نوارِ پیشرفتِ زنده** + **دکمهٔ لغو** برای عملیاتِ سنگین.
- **پنلِ ادمینِ سبک** (`/admin`): تنظیماتِ زمانِ‌اجرا (سقف‌ها، مدلِ Whisper) و هلث — بدونِ ری‌استارت.

## معماری (وضعیتِ واقعیِ کد)
- ربات با **long-polling** به **سرورِ محلیِ Bot API** (`aiogram/telegram-bot-api` با `TELEGRAM_LOCAL=1`) وصل می‌شود؛ فایل‌ها روی دیسکِ همان سرور می‌مانند و ورکر/گیت‌وی مستقیم از دیسک می‌خوانند (تا سقفِ ~۲ گیگ).
- **تحویل** = از طریقِ همان Bot API محلی (بدونِ MTProto). لینک/استریم را سرویسِ **gateway** (aiohttp، پشتیبانیِ HTTP Range) از روی همان فایلِ لوکال سرو می‌کند.
- **صف:** ARQ روی Redis؛ پردازش در سرویسِ **worker** (ffmpeg / Pillow / tesseract / rembg / faster-whisper / LibreOffice / poppler / 7-Zip).
- **داده:** Postgres (SQLAlchemy async) برای `users`/`files`/`jobs`/`settings`؛ Redis برای FSM، صف، سقف‌ها و تنظیماتِ زمانِ‌اجرا.
- سرویس‌ها روی Docker Compose: `local-bot-api · postgres · redis · bot · worker · gateway · clamav`.

> **روڈمپ (هنوز در کد نیست):** معماریِ توزیع‌شدهٔ Master/Node روی WireGuard، تحویلِ >۲ گیگ با MTProto/Kurigram، و پنلِ ادمینِ **وب** — این‌ها اهدافِ آینده‌اند، نه بخشِ کدِ فعلی.

## پیش‌نیازها
- سرور (VPS) با Docker و Docker Compose.
- توکنِ ربات از [@BotFather](https://t.me/BotFather).
- `api_id`/`api_hash` از [my.telegram.org](https://my.telegram.org).
- (اختیاری، برای لینک/استریم) یک دامنه + سرتیفیکیتِ Origin کلودفلر.

## نصب
```bash
git clone <repo-url> telabzar && cd telabzar
bash install.sh
```
installer مقادیر را می‌پرسد، `.env` را با اسرارِ تصادفی می‌سازد، و استک را بالا می‌آورد.
سپس در تلگرام به ربات `/start` بده.

### دستورهای روزمره
```bash
telabzar status      # وضعیت سرویس‌ها
telabzar logs bot    # لاگ زنده
telabzar update      # git pull + rebuild + up
telabzar reconfigure
```

### پنلِ ادمین (سبک)
`ADMIN_IDS` را در `.env` با شناسهٔ عددیِ تلگرامِ خودت ست کن، بعد در چت:
```
/admin list                 نمایشِ تنظیماتِ فعلی
/admin set rate_per_min 20  فعال‌کردنِ سقفِ نرخ (بدونِ ری‌استارت)
/admin set whisper_model small
/admin reset rate_per_min   بازگشت به پیش‌فرضِ env
/admin health               وضعیتِ Postgres/Redis/صف
```
کلیدها و پیش‌فرض‌ها در [`docs/ADMIN_PANEL.md`](docs/ADMIN_PANEL.md).

## نقشهٔ راه
| مرحله | محتوا | وضعیت |
|---|---|---|
| هسته | پردازش + صفِ ARQ + عملیاتِ همهٔ نوع‌ها | ✅ انجام‌شده |
| امنیت | اسکنِ بدافزار + سقف‌ها (خاموش، قابلِ‌فعال‌سازی از `/admin`) | ✅ انجام‌شده |
| لینک/استریم | gateway با دانلود/پخش | ✅ انجام‌شده |
| admin-lite | تنظیماتِ زمانِ‌اجرا + هلث (`/admin`) | ✅ انجام‌شده |
| **دانلودر** | لینک → دانلود (yt-dlp/gallery-dl) → همان pipeline | ⏳ در دست |
| پنلِ ادمینِ وب | مدیریتِ کاملِ تنظیمات/سهمیه/سلامت | 🗺 روڈمپ |
| توزیع‌شده | نودها روی WireGuard + تحویلِ >۲ گیگ | 🗺 روڈمپ |

## ساختار
```
app/
  routers/      هندلرها (start, admin, ops, files)
  locales/      کاتالوگِ دوزبانه (fa, en)
  processing.py پردازشِ رسانه/سند (ورکر)
  tasks.py      تابعِ ARQ (run_op) و تحویلِ درجا
  gateway.py    سرویسِ لینک/استریم (aiohttp)
  settings_store.py  تنظیماتِ زمانِ‌اجرا (Redis read-through + Postgres)
docker/         Dockerfileهای bot و worker
docker-compose.yml
install.sh      نصبِ تعاملی
docs/ADMIN_PANEL.md
```

## توسعه
پایتون ۳.۱۲، aiogram 3.30، SQLAlchemy async + Postgres، Redis (FSM/صف/تنظیمات)، ARQ.
