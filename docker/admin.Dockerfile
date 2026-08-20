# ایمیجِ لاغرِ پنلِ ادمینِ وب — فقط aiohttp/Jinja2/cryptography (بدونِ استکِ پردازش).
#
# ── چرا یک مرحلهٔ Node اضافه شد ────────────────────────────────────────────
# کنسولِ `/console` با Next.js نوشته شده، ولی **رانتایمِ Node در تولید وجود
# ندارد و قرار هم نیست باشد**: خروجی `output: 'export'` است، یعنی HTML+JSِ
# ایستا که همان پروسهٔ aiohttp سرو می‌کند. پس Node فقط در **زمانِ build**
# لازم است و این مرحله دقیقاً همان است — نتیجه‌اش چند فایلِ ایستا در
# `app/static/console/` است و مرحلهٔ Node در ایمیجِ نهایی نمی‌ماند.
#
# بدیلِ «خروجیِ build را کامیت کن» بررسی و رد شد: باندل‌های هش‌دار با هر
# تغییرِ طراحی عوض می‌شوند و دیفِ ریپو را بی‌معنا می‌کنند، در حالی که هزینهٔ
# این مرحله فقط زمانِ build است.
FROM node:22-slim AS console
WORKDIR /build
COPY panel/package.json panel/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY panel ./
# `next build` با `output: 'export'` مستقیم `out/` می‌دهد.
RUN npx next build


FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt requirements-admin.txt ./
RUN pip install --no-cache-dir -r requirements-admin.txt

COPY app ./app
# اسکریپتِ نصبِ نود را پنل سرو می‌کند (GET /node/install.sh) — پس باید در ایمیج باشد
COPY node ./node
# کنسولِ ساخته‌شده. زیرِ `app/` می‌نشیند چون `_STATIC_DIR` به `__file__` لنگر
# می‌خورد و هرچه بیرونِ `app/` باشد در ایمیج نیست.
COPY --from=console /build/out ./app/static/console

CMD ["python", "-m", "app.admin_web"]
