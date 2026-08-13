"""گاردِ drift: تغییرِ `_BAD_KW` نباید بی‌صدا از کنارِ فهرستِ صورت‌ها رد شود.

`_BAD_KW_EXTRA` **دستی نگهداری می‌شود** — همان ردهٔ `_KNOWN_UNREACHABLE` و
فهرستِ هاردکدِ کانکتورها که هر دو در این ریپو drift کردند. اگر کسی کلیدواژه‌ای
به `_BAD_KW` اضافه یا از آن حذف کند، هیچ‌چیز امروز مجبورش نمی‌کند دربارهٔ
صورت‌های صرف‌شدهٔ آن تصمیم بگیرد، و فهرست بی‌سروصدا کهنه می‌شود.

پس `_REVIEWED` پایین **تصمیمِ آگاهانه به‌ازای هر کلیدواژه** را ثبت می‌کند، نه
فقط یک عکسِ فوری: مقدارش صورت‌هایی است که نشانهٔ نسخه شمرده می‌شوند، و `()`
یعنی «بررسی شد، عمداً هیچ صورتی اضافه نمی‌شود». تستْ این را به `_BAD_KW` گره
می‌زند، پس افزودن/حذفِ یک کلمه تست را می‌شکند و نویسنده مجبور می‌شود ردیفش را
پر کند.

**اعدادِ zipf در کامنت‌ها ثبت شده‌اند تا `wordfreq` وابستگیِ دائمی نشود** —
اندازه‌گیری یک‌بار انجام شد (۲۰۲۶-۰۸-۱۳، `wordfreq`، انگلیسی) و نتیجه‌اش
همین‌جا نوشته شده؛ تست خودش هیچ وابستگیِ بیرونی ندارد.

**قاعدهٔ تصمیم:** یک صورتِ صرف‌شده وقتی اضافه می‌شود که در عنوانِ آهنگ واقعاً
نشانهٔ نسخه باشد **و** خودش کلمهٔ عادیِ انگلیسی نباشد. zipf ≈ ۴ به بالا یعنی
کلمهٔ عادی؛ روی ۲۰ عنوانِ واقعی، قاعدهٔ عامِ `(?:s|es|ed|ing)?` ده مثبتِ کاذب
داد — دقیقاً همان‌قدر که تطبیقِ زیررشته‌ای — و فهرستِ صریح صفر.
"""
from __future__ import annotations

from app import downloader as D

# کلیدواژه → صورت‌های اضافی که نشانه شمرده می‌شوند.
_REVIEWED: dict[str, tuple[str, ...]] = {
    # ── صورت‌هایی که عمداً اضافه شده‌اند ──────────────────────────────────
    "remix":        ("remixes", "remixed"),   # هیچ‌کدام کلمهٔ عادی نیستند
    "cover":        ("covers",),              # covers ۴٫۵ ولی در عنوان واقعاً «کاورها»ست؛
                                              # covered ۴٫۸ و covering ۴٫۵ عمداً بیرون
    "session":      ("sessions",),            # ۴٫۵؛ «Abbey Road Sessions» نشانه است.
                                              # ابهامِ «Sessions of Love» پذیرفته شده،
                                              # چون مفردش از قبل همین ابهام را داشت
    "mashup":       ("mashups",),

    # ── بررسی‌شده، عمداً بدونِ صورتِ اضافه ────────────────────────────────
    "live":         (),   # lives ۵٫۱ — «Nine Lives»، «Where Love Lives»
    "reaction":     (),   # reactions ۴٫۲ — «Chemical Reactions»
    "performance":  (),   # performances ۴٫۳؛ و «Live Performances» را `live` می‌گیرد
    "slowed":       (),   # خودش صرف‌شده است
    "reverb":       (),
    "karaoke":      (),
    "instrumental": (),   # instrumentals کم‌کاربرد، و ابهامش می‌ارزد؟ نه
    "8d":           (),
    "concert":      (),   # concerts نشانه نیست، مکان است
    "acoustic":     (),
    "tribute":      (),
    "parody":       (),
    "nightcore":    (),   # nightcored هست ولی صرفش `d` است نه `ed`؛ کم‌کاربرد
    "unplugged":    (),   # خودش صرف‌شده است
    "sped up":      (),   # چندکلمه‌ای
    "extended mix": (),   # چندکلمه‌ای؛ mixed/mixing کلمهٔ عادی‌اند (۴٫۶ / ۴٫۱)
    "radio edit":   (),   # چندکلمه‌ای؛ edited/editing کلمهٔ عادی‌اند (۴٫۳ / ۴٫۳)
}


def test_every_keyword_has_a_recorded_decision_about_its_forms():
    """افزودن/حذفِ یک کلیدواژه باید این تست را بشکند.

    این همان نکته است: فهرستِ صورت‌ها دستی است، پس تغییرِ `_BAD_KW` نباید
    بی‌صدا از کنارش رد شود.
    """
    reviewed, actual = set(_REVIEWED), set(D._BAD_KW)
    missing, extra = actual - reviewed, reviewed - actual
    assert not missing, (
        f"کلیدواژهٔ تازه در `_BAD_KW` بدونِ تصمیم دربارهٔ صورت‌هایش: {sorted(missing)}. "
        f"ردیفش را به `_REVIEWED` اضافه کن — `()` اگر عمداً صورتی ندارد.")
    assert not extra, (
        f"این کلیدواژه‌ها از `_BAD_KW` حذف شده‌اند ولی هنوز در `_REVIEWED`اند: "
        f"{sorted(extra)}. ردیفشان را بردار (و صورت‌هایشان را از `_BAD_KW_EXTRA`).")


def test_the_reviewed_forms_are_exactly_the_shipped_forms():
    """جمعِ صورت‌های ثبت‌شده باید دقیقاً `_BAD_KW_EXTRA` باشد."""
    reviewed = sorted(f for forms in _REVIEWED.values() for f in forms)
    assert reviewed == sorted(D._BAD_KW_EXTRA), (
        f"`_REVIEWED` می‌گوید {reviewed} ولی تولید {sorted(D._BAD_KW_EXTRA)} دارد")


def test_every_form_maps_to_the_keyword_it_was_reviewed_under():
    """`_BAD_BASE` باید با تصمیمِ ثبت‌شده بخواند.

    وگرنه شمارشِ ۱۲− از معنیِ «یکی به‌ازای هر کلیدواژه» خارج می‌شود.
    """
    for kw, forms in _REVIEWED.items():
        for f in forms:
            assert D._BAD_BASE.get(f) == kw, (
                f"صورتِ {f!r} زیرِ {kw!r} بررسی شد ولی `_BAD_BASE` می‌گوید "
                f"{D._BAD_BASE.get(f)!r}")


def test_no_extra_form_is_already_a_keyword():
    """صورتِ اضافه نباید خودش در `_BAD_KW` باشد — افزونگیِ بی‌معنی."""
    assert not (set(D._BAD_KW_EXTRA) & set(D._BAD_KW))


def test_the_forms_list_stays_out_of_the_ordinary_word_trap():
    """صورت‌هایی که اندازه‌گیری ردشان کرده نباید برگردند.

    اینها zipf ≈ ۴ به بالا دارند، یعنی کلمهٔ عادیِ انگلیسی‌اند؛ روی گروهِ
    کنترلِ ۲۰عنوانی هر کدام مثبتِ کاذب می‌دادند.
    """
    for banned in ("lives", "covered", "covering", "reactions", "performances",
                   "mixed", "mixing", "edited", "editing"):
        assert banned not in D._BAD_KW_EXTRA, (
            f"{banned!r} کلمهٔ عادیِ انگلیسی است و اندازه‌گیری ردش کرد")
        assert D._version_markers(banned) == set(), f"{banned!r} نشانه شمرده شد"
