"""فاز ۴ / موارد ۲۲ و ۲۳ — فیلترِ کلیدواژه و دامنه: نه محتوای متعارف، نه دورزدن.

§۷ ادعا می‌کرد «هر برخوردِ کلیدواژه یک تستِ رگرسیون دارد» — ولی تا این فایل هیچ
تستی `check_text`/`check_url` را صدا نمی‌زد. پس این‌جا سه چیز هست:

1. **مثبتِ کاذب‌های اجراشده** (۲۲): عنوان‌های کاملاً متعارف که با زیررشته‌ای‌بودنِ
   چند توکن مسدود می‌شدند — و هر مسدودی یک strike است.
2. **همان برخوردهایی که §۷ و کامنتِ `safety.py` نام می‌برند** — کنترل؛ پیش و پس
   از رفع سبزند، ولی حالا ادعای «تست دارد» راست است.
3. **دورزدنِ فیلترِ دامنه** (۲۳) با نقطهٔ پایانی، حروفِ fullwidth و نقطهٔ CJK — که
   اتصالِ واقعی همه را به همان دامنه می‌برد.

idها عمداً بی‌فاصله‌اند (دفترچهٔ سابوتاژ نامِ تست را با شکستن روی فاصله می‌خواند).
"""
from __future__ import annotations

import pytest

from app import safety as S

# ── ۱. محتوای متعارف که نباید مسدود شود ─────────────────────────────
MAINSTREAM = {
    "xxxtentacion": "XXXTENTACION - SAD!.mp3",
    "xxx_film": "xXx: Return of Xander Cage - Official Trailer",
    "erotica": "Madonna - Erotica (Official Video)",
    "ceelo": "CeeLo Green - FUCK YOU (Official Video)",
    "nudity_warning": "Official Trailer — rated R, contains nudity and violence",
    "boobs_podcast": "Boobs and Bones podcast — episode 12",
    "milf_money": "Fergie - M.I.L.F. $ / Rick and Morty: MILF Money",
}


@pytest.mark.parametrize("key", sorted(MAINSTREAM), ids=sorted(MAINSTREAM))
def test_mainstream_titles_are_not_blocked(key):
    assert S.check_text(MAINSTREAM[key]) is None, MAINSTREAM[key]


def test_lyrics_in_a_description_do_not_block_the_video():
    info = {"title": "Rap Song (Official Video)", "description": "Lyrics: ... fuck that ...",
            "age_limit": 0}
    assert S.check_meta(info) is None


# ── ۲. برخوردهایی که مستندات از قبل ادعا می‌کرد تست دارند (کنترل) ─────
INNOCENT = {
    "sussex": "University of Sussex lecture", "essex": "Essex county news",
    "middlesex": "Middlesex hospital", "unisex": "unisex haircut tutorial",
    "analysis": "data analysis in python", "canal": "Panama canal documentary",
    "cumbria": "walking in Cumbria", "document": "document scanner app",
    "cocktail": "cocktail recipes", "peacock": "peacock feathers",
    "dickens": "Charles Dickens audiobook", "hardcoregaming": "hardcoregaming101 review",
    "pussycat": "The Pussycat Dolls - Buttons", "sexology": "sexology lecture notes",
    "ford_escort": "Ford Escorts rally 1972", "adult_education": "adult education class",
    "fa_sussex": "دانشگاه سوسکس", "fa_essex": "شهرستان اسکس",
}


@pytest.mark.parametrize("key", sorted(INNOCENT), ids=sorted(INNOCENT))
def test_documented_collisions_stay_unblocked(key):
    assert S.check_text(INNOCENT[key]) is None, INNOCENT[key]


# ── و آنچه باید همچنان بگیرد (کنترلِ مقابل: رفع نباید فیلتر را خاموش کند) ──
@pytest.mark.parametrize("text", [
    "free porn videos", "hentai compilation", "hot sex tape", "camgirl live",
    "فیلم سکس", "کلیپ پورن",
], ids=["porn", "hentai", "sex_word", "camgirl", "fa_sex", "fa_porn"])
def test_explicit_text_is_still_blocked(text):
    assert S.check_text(text)


@pytest.mark.parametrize("url", [
    "https://freexxxtube.example/v/1", "https://milfhub.example/", "https://eroticmonkey.example/",
    "https://fuckbook.example/", "https://bestboobs.example/", "https://nuditypics.example/",
], ids=["xxx", "milf", "erotic", "fuck", "boobs", "nudity"])
def test_the_moved_tokens_still_block_inside_a_hostname(url):
    """ردهٔ تازه: همان توکن‌ها، فقط در نامِ دامنه و به‌صورتِ زیررشته."""
    assert S.check_url(url)


def test_the_moved_tokens_are_host_only_not_path():
    """کنترلِ مرز: مسیرِ یک دامنهٔ متعارف (کانالِ XXXTENTACION) مسدود نشود."""
    assert S.check_url("https://www.youtube.com/@XXXTENTACION/videos") is None
    assert S.check_url("https://www.instagram.com/xxxtentacion/") is None


# ── ۳. نرمال‌سازیِ هاست ─────────────────────────────────────────────
@pytest.mark.parametrize("url", [
    "https://beeg.com./v/1",                        # نقطهٔ پایانی
    "https://chaturbate.com./",
    "https://ｃｈａｔｕｒｂａｔｅ.com/x",              # fullwidth
    "https://beeg。com/x",                          # نقطهٔ ایدئوگرافیک
    "https://WWW.Motherless.COM./",
], ids=["trailing_dot", "trailing_dot2", "fullwidth", "cjk_dot", "upper_www_dot"])
def test_a_base_domain_cannot_be_dodged(url):
    assert (S.check_url(url) or "").startswith("domain:"), url


def test_the_admin_block_list_survives_a_trailing_dot():
    block = S.parse_domains("bad.example")
    assert S.check_url("https://bad.example./x", block=block)
    assert S.check_url("https://ｂａｄ.example/x", block=block)


def test_the_admin_lists_are_normalised_like_urls():
    assert S.parse_domains("Bad.Example. https://www.Foo.example/x ｃｈａｔ.example") == \
        frozenset({"bad.example", "foo.example", "chat.example"})
    allow = S.parse_domains("Beeg.com.")
    assert S.check_url("https://beeg.com/v/1", allow=allow) is None


def test_a_punycode_host_is_matched_in_unicode():
    """کلیدواژهٔ فارسی روی نامِ IDN — اتصال `xn--…` را می‌بیند، مقایسه یونیکد را."""
    host = "پورن.com".encode("idna").decode()
    assert host.startswith("xn--")
    assert S.check_url(f"https://{host}/")


def test_an_ordinary_host_is_untouched():
    assert S.norm_host("www.YouTube.com.") == "youtube.com"
    assert S.check_url("https://youtu.be/dQw4w9WgXcQ") is None
