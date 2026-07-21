# ایمیجِ لاغرِ ورکرِ دانلود — فقط ffmpeg + Deno + yt-dlp/gallery-dl.
# جدا از worker.Dockerfileِ سنگین (LibreOffice/rembg/whisper/tesseract + مدل‌ها)
# تا دیسکِ سرور با دو کپیِ چند‌گیگی پر نشود.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg (merge/‏-x برای yt-dlp) + curl برای نصبِ Deno
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Deno — رانتایمِ JS که yt-dlp از ۲۰۲۵.۱۱ برای امضا/nsigِ یوتیوب لازم دارد.
ENV DENO_INSTALL=/usr/local
RUN curl -fsSL https://deno.land/install.sh | sh -s -- -y \
    && /usr/local/bin/deno --version

WORKDIR /srv

COPY requirements.txt requirements-worker-dl.txt ./
RUN pip install --no-cache-dir -r requirements-worker-dl.txt

COPY app ./app

CMD ["arq", "app.worker.DownloadWorkerSettings"]
