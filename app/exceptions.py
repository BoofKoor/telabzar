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


class UserFacingError(RuntimeError):
    """شکستی که **پیامِ کاربرِ خودش** را دارد: کلیدِ locale + پارامترها.

    `run_op` این را جدا از `Exception`ِ عمومی می‌گیرد و به‌جای «❌ ناموفق» +
    دُمِ خامِ انگلیسیِ ابزار، `t(lang, key, **kw)` را نشان می‌دهد — مثلاً «این PDF
    رمز دارد؛ اول رمزش را بردار» به‌جای `qpdf: invalid password`.

    `str(exc)` عمداً **همان کلید** است نه متنِ پیام: `job.error` از آن ساخته
    می‌شود و صفحهٔ آمار خطاها را با متنِ دقیقشان گروه می‌کند، پس کلیدِ ثابت یعنی
    همهٔ «رمز لازم است»ها یک ردیف می‌شوند (همان قیدِ `op_too_large`). `detail` اگر
    باشد زیرِ پیام در `<code>` می‌آید — برای وقتی که دلیلِ فنی به کاربر کمک می‌کند.
    """

    def __init__(self, key: str, detail: str | None = None, **kw):
        super().__init__(key)
        self.key = key
        self.detail = detail
        self.kw = kw
