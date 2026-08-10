"""استثناهای سبک و مشترک (بدونِ وابستگیِ سنگین).

جدا نگه‌داشته می‌شود تا ماژول‌هایی که فقط به استثنا نیاز دارند (مثلِ downloader
که در پروسهٔ bot/gateway هم import می‌شود) مجبور به کشیدنِ Pillow/processing نشوند.
"""
from __future__ import annotations


class ProcessingCancelled(Exception):
    """کاربر عملیات را وسطِ کار لغو کرد."""


class ProcessingTimeout(RuntimeError):
    """اجرای ffmpeg از `timeout` گذشت و کشته شد.

    عمداً زیرکلاسِ `RuntimeError` است تا هر `except RuntimeError`ِ موجود دقیقاً
    مثلِ امروز رفتار کند؛ چیزی که اضافه می‌شود توانِ **تفکیک** است. لازمش شد چون
    fallbackِ انکودر (`compress_video`) روی `RuntimeError` به x264 برمی‌گشت و
    تایم‌اوت هم همان را می‌داد: یک انکودِ nvencِ تایم‌اوت‌شده یک اجرای **کاملِ**
    دیگر می‌ساخت و مجموع از `job_timeout`ِ ARQ رد می‌شد. تایم‌اوت یعنی «وقت کم
    آمد»، نه «این انکودر کار نمی‌کند» — پس نباید fallback بدهد.
    """
