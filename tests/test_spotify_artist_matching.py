"""تطبیقِ هنرمند: قاعدهٔ تناقض، وزنِ آهنگساز، و معافیتِ خطِ عنوان.

سه چیز که روی همان تابع می‌نشینند و با هم آمدند.

**۱ قاعدهٔ تناقض.** مسئله «چند هنرمند می‌خوانند» نیست، «آیا نامزد **کسِ دیگری**
را ادعا می‌کند» است: هنرمندی که در مرجع هست و در نامزد نیست (**جاافتاده**)
**و** هنرمندی که روی نامزد هست و در مرجع نیست (**اضافه**). فهرستِ زیرمجموعه —
یوتیوب که فقط خوانندهٔ اصلی را می‌نویسد — تناقض **نیست**. اندازه‌گیری‌شده ۸ از ۸؛
گیتِ ۴۰ِ قبلی ۷ از ۸، و آن یک شکست دقیقاً **جایگزینیِ خواننده** است که کلِ این
ماجرا از آن شروع شد.

**۲ وزنِ آهنگساز — باگ بود نه نکتهٔ وزنی.** `_artist_match` برای هر هنرمندِ
**مرجع** بهترین شباهت را می‌گرفت و بعد اولی را ۰٫۶ وزن می‌داد. اسپاتیفای برای
موسیقیِ کلاسیکِ ایرانی آهنگساز را اول فهرست می‌کند، پس «اولی» آهنگساز است نه
خواننده. نتیجه، اندازه‌گیری‌شده: وقتی یوتیوب فقط خواننده را فهرست می‌کند
(حالتِ رایج) ضبطِ **درست** ۵۰٫۰ می‌گرفت و ضبطِ **غلط** (همان آهنگساز، خوانندگانِ
دیگر) ۶۸٫۰ — یعنی مؤلفهٔ هنرمند فعالانه غلط را **۱۸ نمره ترجیح می‌داد**.
فرمولِ تازه `mean(cand-side)` است — «ادعاهای نامزد چقدر از مرجع پشتیبانی
می‌شود» — که روی پنج فرمولِ سنجیده‌شده تنها یکی بود که هم این معکوس‌شدگی را
می‌بست و هم زیرمجموعه‌ها را نگه می‌داشت: ۱۰۰٫۰ در برابرِ ۵۳٫۵ (حاشیهٔ ۴۶٫۵).

**۳ معافیتِ گیتِ نام برای خطِ متفاوت — فقط وقتی هنرمند قابلِ مقایسه است.**
اندازه‌گیریِ اولم روی نامزدِ **کاملاً** فارسی‌نویس بود و آن‌جا هم نام و هم
هنرمند صفر می‌شوند (امتیازِ ۳۵٫۳)، پس معافیت no-op بود. ولی حالتِ **مخلوط**
واقعاً وجود دارد و از دادهٔ خودمان آمد — نامزدِ ۱۳ در فهرستِ Faryad:
عنوانِ `'قطعه فریاد'` (فارسی) با هنرمندِ `'Anushiravan Ruhani'` (لاتین). آن‌جا
هنرمند سالم است (۸۸٫۹ با فرمولِ تازه) و **تنها** چیزی که می‌کشدش گیتِ نام است.
با معافیت به ۶۱٫۶ می‌رسد که از آستانهٔ ۵۵ رد می‌شود.

**و امتیازِ نام عمداً با مقدارِ خنثی جایگزین نمی‌شود** — اندازه‌گیری‌شده:
جایگزینی هدف و طعمه را **به یک اندازه** بالا می‌برد، پس هیچ تفکیکی نمی‌خرد و
فقط آستانه را ضعیف می‌کند؛ با نگه‌داشتنِ مقدارِ واقعی، طعمهٔ +۲۰ ثانیه‌ای
۳۶٫۲ می‌ماند (زیرِ آستانه) در حالی که با خنثیِ ۵۰ به ۵۵٫۹ می‌رسد و رد می‌شود.
همان ردهٔ درسِ `_TIME_UNKNOWN`، این‌بار در جهتِ مخالف.
"""
from __future__ import annotations

from app import downloader as D

FARYAD = {"title": "Faryad", "artist": "Anoushirvan Rohani, Haydeh", "duration": 311}
COHEN = {"title": "Hallelujah", "artist": "Leonard Cohen", "duration": 275}


def cand(title: str, artists: list[str], dur: int = 311) -> dict:
    return {"id": "".join(artists)[:8] or "x", "title": title, "artists": artists,
            "album": None, "duration_seconds": dur, "art_track": True, "source": "ytmusic"}


# ── ۱ قاعدهٔ تناقض ──────────────────────────────────────────────────────────
def test_a_different_singer_is_a_contradiction():
    """جایگزینیِ خواننده: آهنگسازِ مشترک، خوانندهٔ دیگر → رد.

    **این تنها سناریویی است که گیتِ ۴۰ِ قبلی از دستش می‌داد** (am=۶۸ → نگه
    می‌داشت)، و همان باگی است که کاربر گزارش کرد.
    """
    c = cand("Faryaad", ["Anoushirvan Rohani", "Maziar", "Kari"], 312)
    assert D._artist_contradiction(FARYAD, c) is True


def test_the_contradiction_rule_is_actually_wired_into_the_gate():
    """قاعده باید در `_rank_candidates` **اعمال** شود، نه فقط وجود داشته باشد.

    نسخهٔ اولِ این فایل تناقض را تنها به‌صورتِ **تابع** می‌سنجید، پس برداشتنِ
    گیت از `_rank_candidates` هیچ تستی را نمی‌انداخت — با سابوتاژ لو رفت. و
    این‌جا کفِ عددی کمکی نمی‌کند: امتیازِ هنرمندِ همین نامزد ۵۳٫۵ است، یعنی
    بالای کفِ ۴۰، پس **تنها** چیزی که ردش می‌کند همین قاعده است.
    """
    wrong = cand("Faryaad", ["Anoushirvan Rohani", "Maziar", "Kari"], 312)
    assert D._artist_match(FARYAD, wrong) > D._ARTIST_MIN, "کفِ عددی خودش ردش نمی‌کند"
    assert D._rank_candidates([wrong], FARYAD) == []


def test_a_bilingual_artist_listing_is_still_exempted():
    """`'هایده Haydeh'` در برابرِ مرجعِ فارسی — هنرمند واقعاً می‌خواند.

    نسخهٔ اول یک چکِ «خطِ نامِ هنرمند» داشت که این را رد می‌کرد (خط را
    «متفاوت» می‌دید) در حالی که شباهت ۵۸٫۸ است. سابوتاژ نشان داد آن چک هم
    زیادی است و هم در تنها حالتِ قابلِ‌دسترسش غلط؛ حذف شد و امتیازِ هنرمند
    خودش کار را می‌کند.
    """
    tr = {"title": "فریاد", "artist": "هایده", "duration": 311}
    c = cand("Faryad", ["هایده Haydeh"])
    assert D._scripts_differ(tr["title"], c["title"]) is True
    assert D._name_gate_exempt(tr, c) is True
    # و نامزدِ کاملاً بی‌ربطِ لاتین همچنان معاف نمی‌شود
    assert D._name_gate_exempt(tr, cand("Faryad", ["Someone Else"])) is False


def test_a_subset_listing_is_not_a_contradiction():
    """یوتیوب فقط خوانندهٔ اصلی را می‌نویسد — نباید رد شود.

    هر قاعدهٔ پوشش‌محور این را اشتباه رد می‌کند؛ همین سناریو بود که `min` و
    میانگین و جریمه-به‌ازای-جاافتاده را باطل کرد.
    """
    lucky = {"title": "Get Lucky",
             "artist": "Daft Punk, Pharrell Williams, Nile Rodgers", "duration": 248}
    assert D._artist_contradiction(lucky, cand("Get Lucky", ["Daft Punk"], 248)) is False
    assert D._artist_contradiction(FARYAD, cand("Faryad", ["Haydeh"])) is False


def test_a_guest_added_by_youtube_is_not_a_contradiction():
    """اضافه‌ی تنها، بدونِ جاافتاده، تناقض نیست."""
    c = cand("Faryad", ["Anoushirvan Rohani", "Haydeh", "Some Guest"])
    assert D._artist_contradiction(FARYAD, c) is False


def test_hallelujah_is_the_benchmark_substitution():
    """کوهن در برابرِ باکلی — هنرمندِ کاملاً متفاوت، همان عنوان، مدتِ نزدیک.

    **کنترل است نه شکستِ امروز:** گیتِ ۴۰ هم ردش می‌کند (am=۱۶). ارزشش این است
    که با قاعدهٔ تازه رگرسیون نکند.
    """
    assert D._artist_contradiction(COHEN, cand("Hallelujah", ["Jeff Buckley"], 273)) is True
    assert D._artist_contradiction(COHEN, cand("Hallelujah", ["Pentatonix"], 280)) is True
    assert D._artist_contradiction(COHEN, cand("Hallelujah", ["Leonard Cohen"], 275)) is False


def test_a_romanisation_variant_is_not_a_contradiction():
    """آستانهٔ فازیِ ۴۵ باید تفاوتِ رومی‌سازی را جذب کند.

    اندازه‌گیری‌شده روی ۱۵ جفت: ۱۴ تا از ۴۵ رد می‌شوند (۵۷٫۱ تا ۹۷٫۸).
    """
    for a, b in [("Haydeh", "Hayedeh"), ("Googoosh", "Gugush"),
                 ("Shajarian", "Shajaryan"), ("Moein", "Mo'in"),
                 ("Dariush", "Daryoush"), ("Anoushirvan Rohani", "Anushirvan Rohani")]:
        tr = {"title": "X", "artist": a, "duration": 300}
        assert D._artist_contradiction(tr, cand("X", [b], 300)) is False, f"{a}/{b}"


def test_a_stage_name_is_a_known_limit_not_a_solved_case():
    """`Ebi` ↔ `Ebrahim Hamedi` = ۳۵٫۳ — نامِ مستعار، نه رومی‌سازی.

    ردهٔ مسئلهٔ دیگری است و در این گام حل نمی‌شود؛ ثبت می‌شود تا کسی فکر نکند
    آستانه فقط باید پایین بیاید.
    """
    tr = {"title": "X", "artist": "Ebi", "duration": 300}
    assert D._artist_contradiction(tr, cand("X", ["Ebrahim Hamedi"], 300)) is True


# ── ۲ وزنِ آهنگساز ──────────────────────────────────────────────────────────
def test_the_right_recording_now_outscores_the_wrong_one_on_artist():
    """۵۰٫۰ در برابرِ ۶۸٫۰ معکوس بود — شکستِ رفتاری روی سورسِ پیش از رفع."""
    right = D._artist_match(FARYAD, cand("Faryad", ["Haydeh"]))
    wrong = D._artist_match(FARYAD, cand("Faryaad", ["Anoushirvan Rohani", "Maziar", "Kari"]))
    assert right > wrong, f"درست {right:.1f} در برابرِ غلط {wrong:.1f}"
    assert right == 100.0
    assert wrong < 60


def test_a_subset_listing_still_scores_high():
    """زیرمجموعه نباید جریمه شود، وگرنه Art Trackِ درست رد می‌شود."""
    lucky = {"title": "Get Lucky",
             "artist": "Daft Punk, Pharrell Williams, Nile Rodgers", "duration": 248}
    assert D._artist_match(lucky, cand("Get Lucky", ["Daft Punk"], 248)) == 100.0


def test_a_wrong_artist_still_scores_low():
    assert D._artist_match(COHEN, cand("Hallelujah", ["Jeff Buckley"], 273)) < 40


def test_a_candidate_with_no_explicit_artists_keeps_the_title_fallback():
    """شاخهٔ کانال‌محورِ ytsearch دست‌نخورده بماند."""
    c = {"id": "y", "title": "Haydeh - Faryad", "channel": "Haydeh - Topic",
         "duration": 311}
    assert D._artist_match(FARYAD, c) is not None
    assert D._artist_match({"title": "X", "artist": "", "duration": 1}, c) is None


# ── ۳ معافیتِ خطِ عنوان ─────────────────────────────────────────────────────
def test_a_persian_title_with_a_latin_artist_survives_the_name_gate():
    """نامزدِ ۱۳ی واقعی: عنوانِ فارسی، هنرمندِ لاتین.

    امروز گیتِ نام (۴٫۸ < ۴۵) می‌کشدش در حالی که هنرمندش سالم است.
    """
    c = cand("قطعه فریاد", ["Anushiravan Ruhani"])
    assert D._name_match(FARYAD, c) < 45          # نام واقعاً پایین است
    # هنرمند سالم است. آستانه ۷۰ است نه ۶۰، چون مقدارِ **قبلِ** رفع دقیقاً ۶۰٫۰
    # بود و `> 60` روی همان عدد به خطای شکستِ ممیز شناور می‌خورد نه به ادعای واقعی.
    assert D._artist_match(FARYAD, c) > 70
    ranked = D._rank_candidates([c], FARYAD)
    assert ranked, "گیتِ نام هنوز می‌کشدش"


def test_a_fully_persian_candidate_is_still_gated():
    """هنرمند هم که فارسی باشد، چیزی برای تکیه نمی‌ماند → معافیت نه."""
    c = cand("قطعه فریاد", ["هایده"])
    assert D._rank_candidates([c], FARYAD) == []


def test_an_unrelated_latin_title_is_still_gated():
    """معافیت فقط برای **خطِ متفاوت** است، نه برای هر نامِ بی‌ربط."""
    assert D._rank_candidates([cand("Completely Different Song", ["Haydeh"])], FARYAD) == []


def test_the_exempted_candidate_stays_below_threshold_when_the_duration_is_off():
    """طعمه: همان آهنگساز، عنوانِ فارسیِ دیگر، مدتِ متفاوت → زیرِ آستانه.

    امتیازِ نام عمداً با خنثی جایگزین **نمی‌شود**؛ اندازه‌گیری‌شده، جایگزینی
    طعمهٔ +۲۰ ثانیه‌ای را به ۵۵٫۹ می‌رساند و از آستانه ردش می‌کند.
    """
    on = D._match_score(cand("قطعه فریاد", ["Anushiravan Ruhani"], 311), FARYAD)
    off = D._match_score(cand("قطعهٔ دیگر", ["Anushiravan Ruhani"], 331), FARYAD)
    assert on >= 55.0, f"هدف {on:.1f} زیرِ آستانه افتاد"
    assert off < 55.0, f"طعمهٔ +۲۰ ثانیه {off:.1f} از آستانه رد شد"


def test_the_romanised_correct_recording_still_wins_when_present():
    """معافیت نباید ضبطِ رومی‌شدهٔ درست را از تخت پایین بکشد."""
    ranked = D._rank_candidates(
        [cand("قطعه فریاد", ["Anushiravan Ruhani"], 311),
         cand("Faryad", ["Anoushirvan Rohani", "Haydeh"], 312)], FARYAD)
    assert ranked[0][1]["title"] == "Faryad"


def test_the_script_helpers_are_general_not_persian_specific():
    """تشخیصِ خط با شمارشِ لاتین در برابرِ غیرِلاتین است، نه بازهٔ هاردکدِ عربی."""
    assert D._scripts_differ("Faryad", "قطعه فریاد") is True
    assert D._scripts_differ("Faryad", "Фарьяд") is True          # سیریلیک
    assert D._scripts_differ("Faryad", "ハレルヤ") is True          # کاتاکانا
    assert D._scripts_differ("Faryad", "Faryaad") is False
    assert D._scripts_differ("قطعه", "فریاد") is False
    assert D._scripts_differ("", "Faryad") is False               # نامعلوم ≠ متفاوت
    assert D._scripts_differ("311", "٣١١") is False               # رقم، نه حرف


def test_a_low_confidence_match_is_reported_not_silent():
    """وقتی نام قابلِ مقایسه نیست، سیستم باید بداند روی سیگنالِ کمتری قضاوت کرده."""
    weak = cand("قطعه فریاد", ["Anushiravan Ruhani"])
    strong = cand("Faryad", ["Anoushirvan Rohani", "Haydeh"], 312)
    assert D.match_confidence_note(FARYAD, weak)
    assert D.match_confidence_note(FARYAD, strong) is None
