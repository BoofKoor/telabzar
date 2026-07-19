FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ابزارها: ffmpeg (ویدیو/صوت) · 7-Zip + unrar (آرشیو) · LibreOffice (سند→PDF) + فونت‌ها
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        p7zip-full unrar-free \
        libreoffice-writer libreoffice-calc libreoffice-impress \
        fonts-liberation fonts-dejavu fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt requirements-worker.txt ./
RUN pip install --no-cache-dir -r requirements-worker.txt

COPY app ./app

CMD ["arq", "app.worker.WorkerSettings"]
