"""ابزارِ `spotify_query_probe.py`: اصابتِ ضعیف نباید اصابتِ واقعی را بپوشاند.

این تست دربارهٔ **ابزارِ تشخیص** است، نه کدِ تولید — و دلیلش این است که نتیجهٔ
همین ابزار تعیین می‌کند دربارهٔ matcher چه نتیجه‌ای بگیریم. یک‌بار غلط گزارش
داد و کلِ تحلیل را منحرف کرد: `hits()` اصابت‌ها را به **ترتیبِ استخر** برمی‌گرداند
و صداکننده `idx[0]` را «هدف» می‌گیرد، پس یک مثبتِ کاذبِ «فقط مدت» که در فهرست
جلوتر باشد، اصابتِ واقعیِ «نام+مدت» را می‌پوشاند.

اندازه‌گیری‌شده روی همان سناریوی ثبت‌شده در §Open Questions — یک `Faryaad`ِ دیگر
در ۳۱۲ ثانیه که پیش از ضبطِ درستِ ۳۱۱ ثانیه‌ای می‌آید:

    hits() → [(0, 'فقط مدت …'), (2, 'نام+مدت')]

ابزار «✓ رتبهٔ ۱» چاپ می‌کرد و آن رتبه مالِ ضبطِ **غلط** بود؛ و در مسیرِ ادغام
`target = merged[midx[0][0]]` همان ویدیوی غلط را «هدف» می‌گرفت و رتبهٔ آن را
گزارش می‌کرد. این دقیقاً همان «رتبهٔ ۳»ی است که در گزارشِ قبلی مثبتِ کاذب بود.

**کدام تست روی سورسِ پیش از رفع می‌افتد:** دو تستِ ترتیبِ `hits()`. بقیه
یا کنترل‌اند (باید هر دو طرف سبز باشند) یا رفتارِ **تازه** را قفل می‌کنند
(`mark_of`/`describe` پیش از رفع وجود ندارند، پس نبودشان شکافِ رفتاری را ثابت
نمی‌کند — همان درسِ فیکسچرِ فاز ۳پ؛ این‌جا صریح گفته می‌شود تا با اثباتِ
واقعی اشتباه نشود).
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _probe():
    """`tools/spotify_query_probe.py` را بارگذاری می‌کند (`tools/` پکیج نیست)."""
    path = ROOT / "tools" / "spotify_query_probe.py"
    spec = importlib.util.spec_from_file_location("spotify_query_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def P():
    return _probe()


# ── سازندهٔ نامزد: همان کلیدهایی که `_norm_ytm` تولید می‌کند ────────────────
def cand(vid: str, title: str, artists: list[str], dur: int | None) -> dict:
    return {"id": vid, "title": title, "artists": artists,
            "duration_seconds": dur, "art_track": True}


WRONG = cand("wrongA", "Faryaad", ["Anoushirvan Rohani", "Maziar", "Kari"], 312)
RIGHT = cand("rightB", "Faryad", ["Haydeh"], 311)
NOISE = cand("noiseC", "Something Else", ["Someone"], 120)


# ── اثباتِ باگ: این دو روی سورسِ پیش از رفع می‌افتند ────────────────────────
def test_a_duration_only_hit_cannot_shadow_a_real_name_and_duration_hit(P):
    """اصابتِ «نام+مدت» باید اول باشد، حتی وقتی در استخر بعد از مثبتِ کاذب است."""
    idx = P.hits([WRONG, NOISE, RIGHT], "Haydeh", 311)
    assert idx, "هیچ اصابتی گزارش نشد"
    first_i, first_why = idx[0]
    assert first_i == 2, (
        f"اولین اصابت ایندکسِ {first_i} است (نامزدِ "
        f"{[WRONG, NOISE, RIGHT][first_i]['id']}) — ضبطِ درست ایندکسِ ۲ است")
    assert first_why.startswith("نام"), (
        f"اولین اصابت «{first_why}» است، یعنی صداکننده یک مثبتِ کاذب را "
        f"به‌عنوان هدف برمی‌دارد")


def test_the_merged_path_picks_the_right_video_as_the_target(P):
    """مسیرِ ادغام (`target = merged[midx[0][0]]`) باید ضبطِ درست را هدف بگیرد.

    این جدا از تستِ بالا نوشته شده چون **پیامدش** جداست: آن‌جا فقط یک عددِ
    رتبهٔ غلط چاپ می‌شد، این‌جا رتبه‌بندی روی ویدیوی غلط سنجیده می‌شود.
    """
    merged = [WRONG, RIGHT]
    midx = P.hits(merged, "Haydeh", 311)
    target = merged[midx[0][0]]
    assert target["id"] == "rightB", (
        f"هدف {target['id']!r} شد، نه ضبطِ درست")


# ── کنترل: باید هر دو طرف سبز باشند ────────────────────────────────────────
def test_a_duration_only_hit_is_still_reported_when_it_is_all_we_have(P):
    """هدفِ اصلیِ معیارِ «فقط مدت» حذف نشده باشد.

    اگر ضبطِ درست با نامِ **فارسی** فهرست شده باشد، معیارِ نام آن را نمی‌بیند و
    مدت تنها چیزی است که پیدایش می‌کند — پس رده‌بندی نباید حذفش کند، فقط
    باید بعد از اصابتِ قوی بیاید.
    """
    fa = cand("faD", "فریاد", ["هایده"], 311)
    idx = P.hits([NOISE, fa], "Haydeh", 311)
    assert [i for i, _ in idx] == [1]
    assert "فقط مدت" in idx[0][1]


def test_a_candidate_outside_the_tolerance_is_not_a_hit(P):
    """گیتِ مدت سرِ جایش بماند: ۲۰ ثانیه تلورانس، ۶۰ ثانیه اصابت نیست."""
    far = cand("farE", "Faryad", ["Haydeh"], 371)
    assert P.hits([far], "Haydeh", 311) == []


def test_pool_order_survives_inside_one_tier(P):
    """دو اصابتِ هم‌رده باید به ترتیبِ استخر بمانند (رده‌بندی، نه مرتب‌سازیِ کامل)."""
    a = cand("a", "Faryad", ["Haydeh"], 311)
    b = cand("b", "Faryad (Remastered)", ["Haydeh"], 310)
    assert [i for i, _ in P.hits([a, b], "Haydeh", 311)] == [0, 1]
    assert [i for i, _ in P.hits([b, a], "Haydeh", 311)] == [0, 1]


# ── قفلِ رفتارِ تازه (پیش از رفع وجود ندارد؛ اثباتِ رفتاری نیست) ────────────
def test_the_one_line_mark_never_reads_a_duration_only_hit_as_found(P):
    """نشانِ یک‌خطی باید «فقط مدت» را از «نام+مدت» تفکیک کند.

    همان چیزی که «رتبهٔ ۳»ِ مثبتِ کاذب را قابلِ خواندن به‌عنوانِ موفقیت کرد.
    """
    strong = P.mark_of(P.hits([RIGHT], "Haydeh", 311))
    weak = P.mark_of(P.hits([WRONG], "Haydeh", 311))
    none = P.mark_of([])
    assert "✓" in strong and "فقط مدت" not in strong
    assert "✓" not in weak and "فقط مدت" in weak
    assert "✗" in none


def test_a_version_marker_is_flagged_because_hits_cannot_see_it(P):
    """معیارِ `hits()` (هنرمند + مدت) ریمیکس را هم «هدف» می‌شمارد — پس باید علامت بخورد.

    **با اجرای خشکِ ابزار پیدا شد، نه با استدلال.** یک ریمیکسِ ۳۱۱ ثانیه‌ای از
    همان هنرمند واجدِ هر دو شرطِ «نام+مدت» است، پس `hits()` آن را هدف می‌گیرد و
    ابزار می‌گفت «برنده همان ضبطِ درست است» — همان جنسِ مثبتِ کاذبی که این کار
    برای بستنش است.
    """
    remix = cand("remixC", "Faryad (DJ Fere Remix)", ["Haydeh"], 311)
    idx = P.hits([remix], "Haydeh", 311)
    assert idx and idx[0][1].startswith("نام"), "ریمیکس واجدِ شرطِ قوی است (همین مسئله)"
    assert P.version_markers(remix["title"]) == ["remix"]
    assert "نشانهٔ نسخه" in P.describe(remix)
    assert "نشانهٔ نسخه" not in P.describe(RIGHT)


def test_the_marker_check_uses_word_boundaries(P):
    """`Delivery`/`Oliver`/`Discovery`/`Recovery` نباید نشانهٔ نسخه بشمارند.

    اینها زیررشته‌های تصادفی‌اند و مرزِ کلمه ردشان می‌کند.

    **`Sessions of Love` عمداً از این فهرست برداشته شد.** نسخهٔ اولِ این تست
    آن را «نباید» می‌دانست، چون طراحیِ آن لحظه مرزِ کلمهٔ **خالی** بود و جمع را
    نمی‌گرفت. اندازه‌گیریِ بعدی آن طراحی را رد کرد (مرزِ خالی ۱۰ نشانهٔ واقعی
    مثلِ «Abbey Road Sessions» را گم می‌کرد)، پس `sessions` حالا صورتِ صریح است
    و «Sessions of Love» جریمه می‌گیرد. این ابهامِ واقعی است و **تازه نیست**:
    `session`ِ مفرد از قبل در `_BAD_KW` بود، پس «Session of Love» امروز هم
    جریمه می‌خورد. جمعش رفتار را هم‌شکل می‌کند، نه بدتر.
    """
    for t in ["Delivery", "Oliver Twist", "Discovery", "Recovery", "Nine Lives"]:
        assert P.version_markers(t) == [], f"{t!r} اشتباهاً نشانهٔ نسخه شمرده شد"
    assert P.version_markers("Faryad (Live)") == ["live"]
    assert P.version_markers("Faryad (Remastered)") == [], "remaster جزوِ _BAD_KW نیست"
    assert P.version_markers("Abbey Road Sessions") == ["session"], "جمع باید نشانه باشد"


def test_describe_identifies_a_candidate_unambiguously(P):
    """شناسه، مدت و **همهٔ** هنرمندان باید در خروجی باشند، بی‌برش.

    خطِ برندهٔ نسخهٔ اول شناسه و مدت را چاپ نمی‌کرد و هنرمند را روی ۲۴
    کاراکتر می‌بُرید، پس نمی‌شد فهمید «برندهٔ ۱۰۳٫۲» کدام ویدیو است.
    """
    c = cand("vid123", "Faryad (Original 1980 Recording)",
             ["Anoushirvan Rohani", "Maziar", "Kari", "Someone Else"], 312)
    out = P.describe(c)
    assert "vid123" in out
    assert "312" in out
    assert "Faryad (Original 1980 Recording)" in out
    for a in c["artists"]:
        assert a in out, f"هنرمندِ {a!r} از خروجی افتاد (برش خورده؟)"
