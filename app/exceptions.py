"""استثناهای سبک و مشترک (بدونِ وابستگیِ سنگین).

جدا نگه‌داشته می‌شود تا ماژول‌هایی که فقط به استثنا نیاز دارند (مثلِ downloader
که در پروسهٔ bot/gateway هم import می‌شود) مجبور به کشیدنِ Pillow/processing نشوند.
"""
from __future__ import annotations


class ProcessingCancelled(Exception):
    """کاربر عملیات را وسطِ کار لغو کرد."""
