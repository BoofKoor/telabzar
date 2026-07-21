FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ابزارها: ffmpeg (ویدیو/صوت) · 7-Zip + unrar (آرشیو) · LibreOffice (سند↔PDF)
#          · poppler-utils (تبدیل/ادغامِ PDF) · tesseract + فارسی/انگلیسی (OCR) + فونت‌ها
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        p7zip-full unrar-free \
        libreoffice-writer libreoffice-calc libreoffice-impress \
        poppler-utils \
        tesseract-ocr tesseract-ocr-fas tesseract-ocr-eng \
        libgomp1 libglib2.0-0 \
        fonts-liberation fonts-dejavu fonts-noto-core fonts-hosny-amiri \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt requirements-worker.txt ./
RUN pip install --no-cache-dir -r requirements-worker.txt

# مدلِ حذفِ پس‌زمینه (rembg/u2net) را در ایمیج کش کن تا هنگامِ اجرا دانلود
# نشود و پس از ری‌استارتِ کانتینر هم موجود بماند.
ENV U2NET_HOME=/opt/models/u2net
RUN mkdir -p /opt/models/u2net \
    && python -c "from rembg import new_session; new_session('u2net')" \
    && chmod -R a+rX /opt/models

COPY app ./app

CMD ["arq", "app.worker.WorkerSettings"]
