# ایمیجِ لاغرِ پنلِ ادمینِ وب — فقط aiohttp/Jinja2/cryptography (بدونِ استکِ پردازش).
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

CMD ["python", "-m", "app.admin_web"]
