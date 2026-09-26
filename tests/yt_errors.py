"""متنِ خطاهای یوتیوب **همان‌طور که خودِ yt-dlp می‌سازد** — مشترک بینِ تست‌ها.

دو مصرف‌کننده دارد و هر دو باید یک متن را ببینند: `test_youtube_error_kinds`
(دسته‌بندیِ تولید) و `test_yt_client_matrix` (دسته‌بندیِ ابزارِ سنجش). اگر هرکدام
کپیِ خودش را داشت، یکی می‌توانست روی متنی سبز شود که دیگری هرگز نمی‌بیند.

ساختِ متن با `ExtractorError` + همان `_youtube_login_hint` + همان ترکیبِ
`reason`/`subreason`ِ `YoutubeIE._real_extract` (شاخهٔ `if reason:` بعد از
`if not formats:`) است، نه رشتهٔ دست‌نویس — §۶: «دابلی که قرارداد را خودش
بازنویسی کند شکلِ API را پنهان می‌کند». فقط متنِ دلیل‌ها (مالِ خودِ یوتیوب، نه
yt-dlp) دست‌نویس است. `test_ytdlp_pins` تضمین می‌کند yt-dlpِ نصب‌شده همان نسخهٔ
تولید است.
"""
from __future__ import annotations


def yt_error(reason: str, subreason: str | None = None) -> str:
    """خطِ `ERROR:` دقیقاً همان‌طور که yt-dlp (2026.08.19) می‌سازد."""
    from yt_dlp.extractor.youtube import YoutubeIE
    from yt_dlp.utils import ExtractorError, remove_end

    if subreason:
        reason += f". {subreason}"
    if "sign in" in reason.lower():
        reason = remove_end(reason, "This helps protect our community. Learn more")
        reason = f'{remove_end(reason.strip(), ".")}. {YoutubeIE()._youtube_login_hint}'
    elif "This content isn't available, try again later" in reason:
        reason = (f'{remove_end(reason.strip(), ".")}. The current session has been '
                  "rate-limited by YouTube for up to an hour. It is recommended to use "
                  "`-t sleep` to add a delay between video requests to avoid exceeding "
                  "the rate limit.")
    return "ERROR: " + str(ExtractorError(reason, video_id="abc", ie="youtube",
                                          expected=True))


# متنِ دلیل‌ها مالِ خودِ یوتیوب است (در سورسِ yt-dlp نیست).
BOT = yt_error("Sign in to confirm you’re not a bot",
               "This helps protect our community. Learn more")
AGE = yt_error("Sign in to confirm your age",
               "This video may be inappropriate for some users.")
PRIVATE = yt_error("Private video", "Sign in if you've been granted access to this video")
MEMBERS = yt_error("Join this channel to get access to members-only content like "
                   "this video, and other exclusive perks.")
RELOAD = yt_error("The page needs to be reloaded.")
RATE = yt_error("This content isn't available, try again later.")
def fragment_error(err: str = "HTTP Error 403: Forbidden", retries: int = 10) -> str:
    """شکستِ دانلودِ **تکه‌ای** (HLS/DASH) همان‌طور که yt-dlp می‌نویسد.

    مسیرِ واقعی اجرا می‌شود — `FileDownloader.report_retry` → `RetryManager.
    report_retry` → `report_error('\\r[download] Got error: …')` — نه رشتهٔ
    دست‌نویس، چون نکتهٔ این متن همان `\\r`ِ بعد از `ERROR:` است که
    `splitlines()` را می‌شکند؛ اگر yt-dlp روزی قالب را عوض کند تست همراهش حرکت
    می‌کند. (دانلودِ غیرتکه‌ای ۴۰۳ را تکرار نمی‌کند و همان `GVS_403`ِ پایین را
    می‌دهد.)
    """
    from yt_dlp import YoutubeDL
    from yt_dlp.downloader.common import FileDownloader

    out: list[str] = []

    class _Log:
        def debug(self, msg):
            pass

        info = debug

        def warning(self, msg):
            out.append(msg)

        error = warning

    ydl = YoutubeDL({"logger": _Log(), "quiet": True, "ignoreerrors": True})
    FileDownloader(ydl, ydl.params).report_retry(
        Exception(err), retries + 1, retries, frag_index=1, fatal=True)
    assert len(out) == 1, out
    return out[0]


# این یکی از `YoutubeDL.process_info` می‌آید (`unable to download video data: …`)
GVS_403 = "ERROR: unable to download video data: HTTP Error 403: Forbidden"
# همان ۴۰۳ روی تکه‌ای از HLS/DASH — با `\r` بعد از `ERROR:`
FRAG_403 = fragment_error()
# کنترل: ۴۰۳ روی **خودِ API**، نه دانلودِ رسانه — رفتارش نباید عوض شود
API_403 = "ERROR: [youtube] abc: Unable to download API page: HTTP Error 403: Forbidden"
TRACEBACK = ("Traceback (most recent call last):\n"
             '  File "/usr/local/lib/python3.12/site-packages/x.py", line 9, in f\n'
             "KeyError: 'challenge'")
