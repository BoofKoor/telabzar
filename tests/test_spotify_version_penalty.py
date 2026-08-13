"""جریمهٔ «نسخهٔ نادرست»: روی عنوانِ حافظِ براکت، با صورت‌های صریح.

`_norm` پنج کار می‌کند و یکی‌شان حذفِ متنِ داخلِ پرانتز است — و پرانتز دقیقاً
جایی است که یوتیوب نشانهٔ نسخه را می‌گذارد. `_match_score` همان `_norm` را برای
جست‌وجوی `_BAD_KW` به کار می‌برد، پس **۵ از ۶** عنوانِ واقعی جریمه‌شان صفر
می‌شد. اثرِ دومش بدتر بود: حذفِ براکت `_name_match` را هم به **۱۰۰** می‌رساند،
یعنی ریمیکس هم‌زمان تطبیقِ کاملِ عنوان می‌گرفت **و** جریمه نمی‌خورد —
اندازه‌گیری‌شده، ضبطِ اصلی و ریمیکس **هر دو دقیقاً ۱۰۶٫۰**.

**دو نرمال‌سازی، نه یکی.** `_norm` دست‌نخورده می‌ماند و تطبیقِ نام/هنرمند/آلبوم
همان‌جا می‌ماند — حذفِ براکت برای مقایسهٔ fuzzy **درست** است، وگرنه
«Faryad (Official Video)» دیگر با «Faryad» تطبیق نمی‌خورد. فقط جست‌وجوی
کلیدواژه به `_penalty_text` می‌رود که براکت را نگه می‌دارد. پس نامِ ریمیکس
همچنان ۱۰۰ است و چیزی که جدایش می‌کند **جریمه** است: ۱۰۶ → ۹۴.

**سه چیز که `_penalty_text` عمداً نمی‌کند** و هر سه اندازه‌گیری شده‌اند:
پرانتز را نگه می‌دارد؛ `_FEAT_RE` را اعمال نمی‌کند (آن الگو `.*$` دارد، پس
«Faryad (Live) feat. Haydeh» به `'faryad'` فرو می‌ریخت و نشانه گم می‌شد)؛ و
`_NOISE_RE` را اعمال نمی‌کند.

**صورت‌های صریح، نه قاعدهٔ عامِ صرف — این را اندازه‌گیری تعیین کرد.** روی ۲۰
عنوانِ واقعی، قاعدهٔ عامِ `(?:s|es|ed|ing)?` **ده** مثبتِ کاذب داد، یعنی دقیقاً
همان‌قدر که تطبیقِ زیررشته‌ایِ امروز — چون `lives`/`covered`/`covering`/
`reactions` خودشان کلمهٔ عادیِ انگلیسی‌اند (zipf ۴٫۲ تا ۵٫۱). فهرستِ صریحِ
`remixes/remixed/covers/sessions/mashups` صفر خطا داد. همین شکلِ
`safety.STRONG_TOKENS`/`WORD_TOKENS` است: فهرستِ صریح + تستِ رگرسیون.

**و یک باگِ امروز که همین رفع می‌بنددش:** تطبیقِ زیررشته‌ای «Nine Lives» را
−۱۲ می‌زند. آن ده مثبتِ کاذب ریسکِ این تغییر نیستند، وضعِ **فعلی**اند.
"""
from __future__ import annotations

import re

from app import downloader as D

TRACK = {"title": "Faryad", "artist": "Anoushirvan Rohani, Haydeh", "duration": 311}


def score(cand_title: str, track: dict | None = None, dur: int = 311) -> float:
    cand = {"id": "x", "title": cand_title, "artists": ["Anoushirvan Rohani", "Haydeh"],
            "duration_seconds": dur, "art_track": True}
    return D._match_score(cand, track or TRACK)


def penalty(cand_title: str, track_title: str = "Faryad") -> int:
    """جریمهٔ خالصِ نسخه، **از مسیرِ خودِ `_match_score`**.

    عمداً تابعِ تازه را صدا نمی‌زند: اگر می‌زد، روی سورسِ پیش از رفع
    `AttributeError` می‌داد و آن «نبودِ صفت» را نشان می‌دهد نه شکافِ رفتاری را
    (همان درسِ فیکسچرِ فاز ۳پ). به‌جایش با یک عنوانِ **بی‌نشانه** تفاضل می‌گیرد.

    این تفاضل تمیز است و دلیلش خودِ باگ است: `_norm` براکت را می‌ریزد، پس برای
    دو عنوانِ براکت‌دارِ همان ترک، نام و هنرمند و مدت **یکسان**اند و تنها چیزی
    که در `_match_score` تفاوت می‌کند جریمه است.
    """
    tr = {**TRACK, "title": track_title}
    return round(score(cand_title, tr) - score("Faryad", tr))


# ── باگِ اصلی: نشانهٔ داخلِ براکت باید جریمه بخورد ──────────────────────────
def test_a_bracketed_version_marker_is_penalised():
    """۵ از ۶ عنوانِ واقعی که امروز جریمه‌شان صفر می‌شود."""
    for title in ["Faryad (DJ Fere Remix)",
                  "Faryad (Piano Version - Slowed + Reverb)",
                  "Faryad (Live at Vahdat Hall 1998)",
                  "Faryad (Radio Edit)",
                  "Faryad [Official Live Video]"]:
        assert penalty(title) <= -12, f"{title!r} جریمه نخورد"


def test_an_unbracketed_marker_still_fires():
    """تنها حالتی که امروز کار می‌کند نباید بشکند.

    این‌جا `<= -12` است نه `== -12`: عنوانِ بی‌براکت روی `_norm` هم عوض می‌شود
    (`'faryad remix'` در برابرِ `'faryad'`)، پس تفاضل علاوه بر جریمه، افتِ
    **واقعیِ** مؤلفهٔ نام را هم دارد. فرضِ «نام یکسان» فقط برای عنوانِ
    براکت‌دار برقرار است.
    """
    assert penalty("Faryad - Remix") <= -12


def test_the_remix_no_longer_ties_with_the_real_recording():
    """موردِ رگرسیونِ اجرای خشک: هر دو دقیقاً ۱۰۶٫۰ بودند."""
    original = score("Faryad")
    remix = score("Faryad (DJ Fere Remix)")
    assert original > remix, f"اصلی {original} در برابرِ ریمیکس {remix}"
    assert original - remix >= 12, f"فاصله فقط {original - remix:.1f}"


def test_several_distinct_markers_stack_as_before():
    """یک ۱۲− به‌ازای هر کلیدواژهٔ **پایه** — همان معنیِ قبلی."""
    assert penalty("Faryad (Live Remix)") == -24


# ── مرزِ کلمه: باید روی نسخهٔ بی‌مرز fail شود ────────────────────────────────
def test_an_accidental_substring_is_not_a_marker():
    """`feat. Oliver` و `album Recovery` نباید جریمه بگیرند.

    اینها امروز پشتِ حذفِ براکت پنهان‌اند؛ بازکردنِ براکت بدونِ مرزِ کلمه یک
    باگِ خفته را فعال می‌کند (`Oliver`→`live`، `Recovery`→`cover`).
    """
    for title in ["Faryad (feat. Oliver)",
                  "Faryad (from the album Recovery)",
                  "Faryad (Delivery Mix)",
                  "Faryad (Discovery)",
                  "Faryad (Coverdale Sings)"]:
        assert penalty(title) == 0, f"{title!r} اشتباهاً جریمه خورد"


def test_an_inflection_that_is_an_ordinary_word_is_not_a_marker():
    """`lives`/`covered`/`covering`/`reactions` کلمهٔ عادی‌اند، نه نشانهٔ نسخه.

    اندازه‌گیری‌شده با wordfreq: zipf ۵٫۱ / ۴٫۸ / ۴٫۵ / ۴٫۲. قاعدهٔ عامِ
    `(?:s|es|ed|ing)?` هر چهار را می‌گرفت و **همان ده مثبتِ کاذبِ** تطبیقِ
    زیررشته‌ای را بازتولید می‌کرد؛ فهرستِ صریح صفر خطا داد.

    داخلِ براکت آزمایش می‌شود تا `_norm` روی هر دو طرف یکی بماند و تفاضل **فقط**
    جریمه باشد. توجه: این تست روی سورسِ پیش از رفع هم **سبز** است، چون آن‌جا
    براکت پیش از جست‌وجو ریخته می‌شد؛ ارزشش در برابرِ **طراحیِ غلط** است، نه
    در برابرِ کدِ قدیم — با برداشتنِ `\\b` یا با قاعدهٔ عامِ صرف می‌افتد
    (سابوتاژ شد).
    """
    for inner in ["Nine Lives", "Where Love Lives", "Covered in Rain",
                  "Covering the Distance", "Chemical Reactions"]:
        assert penalty(f"Faryad ({inner})") == 0, f"{inner!r} اشتباهاً جریمه خورد"


def test_the_bare_ordinary_word_is_not_a_marker_either():
    """بی‌براکت هم نباید نشانه شمرده شود — این همان باگِ **امروز** است.

    تطبیقِ زیررشته‌ای «Nine Lives» را `live` می‌خواند و −۱۲ می‌زند
    (اندازه‌گیری‌شده: ۱۰ از ۱۰ عنوانِ گروهِ کنترل). این‌جا مستقیم روی
    `_version_markers` سنجیده می‌شود نه با تفاضلِ امتیاز، چون این عنوان‌ها
    براکتیِ همان ترک نیستند و مؤلفهٔ **نام** هم واقعاً عوض می‌شود — پس تفاضل
    جریمه را جدا نمی‌کند. (تلاشِ اولم همین اشتباه را داشت و `-35` گرفت.)
    """
    for title in ["Nine Lives", "Where Love Lives", "Covered in Rain",
                  "Covering the Distance", "Chemical Reactions"]:
        assert D._version_markers(title) == set(), f"{title!r} نشانه شمرده شد"


def test_the_explicit_inflected_forms_are_still_markers():
    """پوششی که تطبیقِ زیررشته‌ای داشت و نباید از دست برود."""
    for title in ["Faryad (Remixes)", "Faryad (Remixed)", "Faryad (The Covers)",
                  "Faryad (Abbey Road Sessions)", "Faryad (Summer Mashups)"]:
        assert penalty(title) <= -12, f"{title!r} نشانه شمرده نشد"


# ── تقارن: هر دو طرف باید یک نرمال‌سازی ببینند ──────────────────────────────
def test_a_live_reference_does_not_penalise_a_live_candidate():
    """اگر خودِ ترکِ اسپاتیفای لایو است، نامزدِ لایو جریمه ندارد.

    امروز متقارن است (هر دو طرف براکت را می‌ریزند). عوض‌کردنِ **فقط** سمتِ
    نامزد این را می‌شکست: `tt='faryad'` ولی `ct='faryad live in tehran'` →
    جریمهٔ ناحقِ `['live']`. اندازه‌گیری‌شده پیش از پیاده‌سازی.
    """
    assert penalty("Faryad (Live in Tehran)", track_title="Faryad (Live at Vahdat)") == 0
    # و برعکس: مرجعِ غیرِلایو همچنان نامزدِ لایو را جریمه می‌کند
    assert penalty("Faryad (Live in Tehran)", track_title="Faryad") == -12


def test_the_feat_tail_no_longer_hides_a_marker():
    """`_FEAT_RE` تا آخرِ رشته را پاک می‌کند، پس نشانهٔ بعدِ feat گم می‌شد."""
    assert D._norm("Faryad (Live) feat. Haydeh") == "faryad"   # رفتارِ `_norm`، دست‌نخورده
    assert penalty("Faryad (Live) feat. Haydeh") == -12


# ── کنترل: `_norm` نباید عوض شده باشد ───────────────────────────────────────
def test_name_matching_still_ignores_brackets():
    """حذفِ براکت برای مقایسهٔ fuzzy **درست** است و باید بماند."""
    assert D._name_match(TRACK, {"title": "Faryad (Official Video)"}) == 100.0
    assert D._name_match(TRACK, {"title": "Faryad (DJ Fere Remix)"}) == 100.0


def test_remastered_scores_high_and_takes_no_penalty():
    """کنترلِ خواسته‌شده: `remaster` در `_NOISE_RE` است نه `_BAD_KW`."""
    assert D._name_match(TRACK, {"title": "Faryad (Remastered)"}) == 100.0
    assert penalty("Faryad (Remastered)") == 0
    assert "remaster" not in D._BAD_KW


def test_a_clean_title_is_untouched():
    assert penalty("Faryad") == 0
    assert penalty("Faryad (Official Video)") == 0


# ── ساختار: یک قاعده، یک جا ─────────────────────────────────────────────────
def test_the_marker_rule_is_word_bounded():
    """الگو باید `\\b` داشته باشد — گاردِ ساختاری در برابرِ بازگشتِ زیررشته‌ای."""
    assert D._BAD_KW_RE.pattern.startswith(r"\b")
    assert D._BAD_KW_RE.pattern.endswith(r")\b")


def test_every_extra_form_maps_back_to_a_real_base_keyword():
    """هر صورتِ اضافی باید به کلیدواژهٔ پایهٔ موجود نگاشت شود.

    وگرنه شمارشِ ۱۲− از معنیِ «یکی به‌ازای هر کلیدواژه» خارج می‌شود.
    """
    for form, base in D._BAD_BASE.items():
        assert base in D._BAD_KW, f"{form!r} به پایهٔ ناموجودِ {base!r} نگاشت شد"
        assert re.fullmatch(r"[\w' ]+", form), f"صورتِ {form!r} نویسهٔ غیرمنتظره دارد"


def test_the_probe_tool_shares_the_production_rule():
    """ابزارِ probe نباید نسخهٔ دومِ این قاعده را دست‌نویس کند.

    دو کپیِ دست‌نویس از یک قاعده واگرا می‌شوند — همان درسِ `remove_cookie_file`.
    """
    import importlib.util
    import pathlib
    path = pathlib.Path(__file__).resolve().parent.parent / "tools" / "spotify_query_probe.py"
    spec = importlib.util.spec_from_file_location("spotify_query_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.version_markers("Nine Lives") == []
    assert mod.version_markers("Faryad (DJ Fere Remix)") == ["remix"]
    assert mod.version_markers("Faryad (feat. Oliver)") == []
