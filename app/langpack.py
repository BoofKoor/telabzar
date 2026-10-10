"""بستهٔ زبان — ساخت/خواندن/سنجشِ فایلِ export/importِ ترجمه.

**عمداً خالص و بی‌دیتابیس.** مصرف‌کننده‌اش `admin_web` است، ولی منطقِ واقعی
(نرمال‌سازیِ کدِ زبان، پاکت، اعتبارسنجیِ ورودی) این‌جاست تا jobِ **اصلیِ** تست
بتواند بسنجدش؛ `tests/panel` یک jobِ جداست که `jinja2`/`cryptography` می‌خواهد،
و قاعده‌ای که فقط آن‌جا تست شود نصفِ CI را بی‌پوشش می‌گذارد. همان دلیلی که
`cookies.py` و `dl_active.py` را سرِ جایشان نشانده.

**مصرف‌کنندهٔ فایل یک چت‌بات است، نه یک برنامه.** پس شکلش JSON با یک پاکت است
(`readme` داخلِ خودِ فایل، تا دستور همراهِ داده سفر کند)، و خواندنش نسبت به
کارهایی که یک مدل با متن می‌کند بردبار است: فنسِ ```‎ (هرجای پاسخ)، جمله‌ای پیش یا
پس از JSON، BOM، فاصلهٔ اضافه، شکستنِ خطِ واقعی داخلِ یک متن، ویرگولِ آخرِ فهرست،
و پاکتی که مدل انداخته (فقط `texts`، یا خودِ متن‌ها). همهٔ این‌ها بی‌خطرند چون
**هر کلید و هر متن** بعد از خواندن جداگانه سنجیده می‌شود (`review`)؛ بردباری فقط
دربارهٔ «JSON کجاست» است، نه دربارهٔ «چه چیزی پذیرفته می‌شود».
"""
from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field

from . import textstore
from .i18n import CATALOG, DEFAULT, default_text

#: نسخهٔ پاکت. فقط برای اینکه فایلِ نسلِ بعد بی‌صدا اشتباه خوانده نشود.
PACK_VERSION = 1

#: همهٔ کلیدهای متن — از **کاتالوگِ کد**، نه از دیتابیس. کلیدها را توسعه‌دهنده
#: می‌سازد نه ادمین، پس این تنها منبعِ درست است. `admin_web` هم از همین می‌خواند.
TEXT_KEYS: tuple[str, ...] = tuple(sorted(set(CATALOG["fa"]) | set(CATALOG["en"])))
_KNOWN = frozenset(TEXT_KEYS)

#: سقفِ ستونِ کدِ زبان (`models.LANG_LEN`). کرانِ **واقعی** الگوی زیر است؛ این
#: فقط عرضِ ذخیره‌سازی است و باید با ستون یکی بماند.
MAX_CODE_LEN = 16

#: کدِ زبان به سبکِ BCP 47: زیرتگِ اصلیِ ۲–۳ حرفی، به‌علاوهٔ زیرتگ‌های ۲–۸
#: حرفی/عددی. عمداً روی **فرمت** است نه طول: `pt-BR` و `zh-Hant-TW` کدهای
#: واقعی‌اند و قفل‌کردنِ دو کاراکتر یعنی اولین زبانِ این‌شکلی یک مهاجرت می‌خواهد.
_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

#: بلوکِ کد در پاسخِ چت‌بات — **هرجای** متن، نه فقط وقتی کلِ متن است: مدل معمولاً یک
#: جمله پیش یا پس از فنس می‌نویسد («Here is the translated file:»). اگر پاسخ بریده
#: شده باشد فنسِ پایانی هم نیست، پس انتهای متن هم پایانِ بلوک حساب می‌شود.
_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\r?\n(.*?)(?:\r?\n[ \t]*```|\Z)", re.S)

#: آغازِ شیء در **ابتدای یک خط**. «{»ِ وسطِ جمله معمولاً placeholderی در نثرِ مدل است
#: («I kept every {placeholder}»)، نه آغازِ JSON — پس این‌ها پیش از «اولین {» امتحان می‌شوند.
_LINE_BRACE_RE = re.compile(r"(?m)^[ \t]*\{")
_MAX_STARTS = 8          # کران، تا متنِ بزرگِ خراب به ده‌ها بار پارس نکشد

#: `strict=False` شکستنِ خطِ **واقعی** (و تب) داخلِ یک رشته را می‌پذیرد. مدل گاهی به‌جای
#: `\n` خودِ خط را می‌شکند؛ JSONِ سخت‌گیر آن را «Invalid control character» می‌خواند، در
#: حالی که منظور همان است و مقدار با همان شکستِ خط ذخیره می‌شود.
_DECODER = json.JSONDecoder(strict=False)

#: فیلدهای پاکت. در شیئی که مدل پاکتش را انداخته، هر کلیدِ دیگر یک متن است.
_ENVELOPE = ("telabzar_i18n", "lang", "name", "source", "readme")


class PackError(ValueError):
    """خطای سطحِ **فایل** — یعنی هیچ‌چیز خوانده نشد. (خطای سطحِ کلید در `Review`)"""


def normalize_code(raw: str) -> str:
    """کدِ زبان را به شکلِ کانونیکِ BCP 47 می‌آورد؛ نامعتبر → `PackError`.

    نرمال‌سازیِ حروف شرطِ **درستی** است نه آراستگی: بدونش `pt-BR` و `pt-br` دو
    زبانِ جدا می‌شوند و ترجمه‌ها بینشان نصف می‌شود.
    """
    code = (raw or "").strip()
    if not code:
        raise PackError("کدِ زبان خالی است.")
    if not _TAG_RE.match(code):
        raise PackError(
            f"کدِ زبانِ نامعتبر: «{code}». نمونه‌های معتبر: es · de · pt-BR · zh-Hant-TW")
    parts = code.split("-")
    out = [parts[0].lower()]
    for p in parts[1:]:
        if len(p) == 4 and p.isalpha():      # اسکریپت → Titlecase
            out.append(p.title())
        elif len(p) == 2 and p.isalpha():    # منطقه → UPPER
            out.append(p.upper())
        else:
            out.append(p.lower())
    code = "-".join(out)
    if len(code) > MAX_CODE_LEN:
        raise PackError(f"کدِ زبان از {MAX_CODE_LEN} کاراکتر بلندتر است: «{code}».")
    return code


def effective_texts(lang: str, overrides: dict[str, str]) -> dict[str, str]:
    """مقدارِ **مؤثرِ** هر کلید برای یک زبان: override اگر هست، وگرنه پیش‌فرض."""
    return {k: overrides.get(k) or default_text(lang, k) for k in TEXT_KEYS}


def _readme(lang: str, name: str) -> list[str]:
    return [
        f"Translate every value inside \"texts\" into {name} ({lang}).",
        "NEVER change a key (the left-hand side). Keys are identifiers, not text.",
        "Keep every {placeholder} exactly as it appears — same name, same count.",
        "Keep HTML tags (<b>, <i>, <code>, <a href=...>) and emoji exactly as they are.",
        "Line breaks stay \\n inside the string. Never add <br>, Markdown (**bold**) or any new tag.",
        "Return the COMPLETE file. Do not drop, add, reorder or summarise entries.",
        "If it does not fit in one reply, send several complete JSON parts with this same envelope.",
        "A value already written in the target language should be reviewed, not re-translated.",
        "Reply with the JSON only — no text before or after it.",
    ]


def build_pack(*, lang: str, name: str, source: str, texts: dict[str, str]) -> str:
    """پاکتِ JSON برای دادن به یک چت‌بات. همین شکل، عیناً، دوباره import می‌شود."""
    payload = {
        "telabzar_i18n": PACK_VERSION,
        "lang": lang,
        "name": name,
        "source": source,
        "readme": _readme(lang, name),
        "texts": {k: texts[k] for k in TEXT_KEYS if k in texts},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _tokens(s: str):
    """(اندیس, نویسه)ِ هر نویسهٔ **بیرونِ** رشته‌های JSON، به‌علاوهٔ گیومهٔ بستهٔ هر رشته.

    گیومهٔ بسته عمداً برگردانده می‌شود: نشان می‌دهد یک «مقدار» آمده، وگرنه ویرگولِ
    میانِ دو رشته (`"a", "b"`) شبیهِ ویرگولِ آخرِ فهرست دیده می‌شد.
    """
    in_str = esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
                yield i, '"'
        elif ch == '"':
            in_str = True
        else:
            yield i, ch


def _drop_trailing_commas(s: str) -> str:
    """ویرگولِ پیش از «}» یا «]» را برمی‌دارد — فقط بیرونِ رشته‌ها؛ متن دست نمی‌خورد.

    مدل وقتی فهرست را کوتاه یا جابه‌جا می‌کند ویرگولِ آخر را جا می‌گذارد و JSON آن را
    نمی‌پذیرد. اگر چیزی برای برداشتن نبود **همان شیء** برمی‌گردد.
    """
    drop: set[int] = set()
    last = -1
    for i, ch in _tokens(s):
        if ch in "}]" and last >= 0 and s[last] == ",":
            drop.add(last)
        if not ch.isspace():
            last = i
    return "".join(c for i, c in enumerate(s) if i not in drop) if drop else s


def _cut_off(sub: str, exc: json.JSONDecodeError) -> bool:
    """پاسخِ بریده‌شده؟ — خطا **در انتهای** متن، یا رشته‌ای که هرگز بسته نشده.

    با `strict=False` خطِ جدید داخلِ رشته مجاز است، پس «Unterminated string» فقط یعنی
    متن وسطِ یک رشته تمام شده؛ و JSONِ کاملی که جایی وسطش خراب است هرگز به انتهای
    متن نمی‌رسد. برای همین این دو شرط کافی‌اند و شمارشِ آکولاد لازم نیست.
    """
    return exc.pos >= len(sub.rstrip()) or exc.msg.startswith("Unterminated string")


def _line_at(text: str, pos: int, width: int = 70) -> str:
    """خطِ دربرگیرندهٔ `pos`، کوتاه‌شده حولِ همان ستون — تا ادمین جای خطا را ببیند."""
    a = text.rfind("\n", 0, pos) + 1
    b = text.find("\n", pos)
    line = text[a:b if b >= 0 else len(text)]
    if len(line) > width:
        lo = max(0, min(pos - a - width // 2, len(line) - width))
        line = ("…" if lo else "") + line[lo:lo + width] + ("…" if lo + width < len(line) else "")
    return line.strip()


def _load_object(text: str) -> dict:
    """اولین شیءِ JSONِ کامل در متن — با هر چیزی که یک چت‌بات دورش گذاشته باشد.

    نامزدها به ترتیب: محتوای اولین بلوکِ ```‎ (اگر هست)، بعد کلِ متن. در هر نامزد،
    «{»هایی که خط را شروع می‌کنند و بعد اولین «{». `raw_decode` یک شیء می‌خواند و
    **هرچه بعدش آمده** (فنسِ پایانی، «Let me know if…») را نادیده می‌گیرد. اگر نشد،
    همان کار بعد از برداشتنِ ویرگول‌های آخرِ فهرست.

    خطا از تلاشی گزارش می‌شود که **بیشترین پیشروی** را داشته — یعنی خودِ JSON، نه
    جمله‌ای از نثرِ مدل که با «{» شروع شده بود — با شمارهٔ خط در **متنِ چسبانده‌شده**.
    """
    cands = []
    fence = _FENCE_RE.search(text)
    if fence:
        cands.append((fence.start(1), fence.group(1)))
    cands.append((0, text))
    best = None                       # (پیشروی, آفستِ آغاز در متن, زیررشته, خطا)
    tried: set[int] = set()
    for off, cand in cands:
        starts = [m.end() - 1 for m in itertools.islice(_LINE_BRACE_RE.finditer(cand), _MAX_STARTS)]
        starts.append(cand.find("{"))
        for st in starts:
            if st < 0 or off + st in tried:
                continue
            tried.add(off + st)
            sub = cand[st:]
            fixed = _drop_trailing_commas(sub)
            for body in (sub,) if fixed is sub else (sub, fixed):
                try:
                    return _DECODER.raw_decode(body)[0]
                except json.JSONDecodeError as exc:
                    if body is sub and (best is None or exc.pos > best[0]):
                        best = (exc.pos, off + st, sub, exc)
    if best is None:
        raise PackError("در این متن هیچ شیءِ JSONی ({ … }) پیدا نشد.")
    _p, base, sub, exc = best
    if _cut_off(sub, exc):
        raise PackError(
            "فایل ناقص است: پیش از بسته‌شدنِ JSON تمام شده — ابزارِ ترجمه وسطِ پاسخ قطع کرده. "
            "بخواه بقیه را هم بدهد، یا متن‌ها را در چند بخش ترجمه و هر بخش را جدا بارگذاری کن "
            "(در حالتِ «ادغام» هر بخش فقط کلیدهای خودش را عوض می‌کند).")
    pos = base + exc.pos
    line = text.count("\n", 0, pos) + 1
    col = pos - (text.rfind("\n", 0, pos) + 1) + 1
    near = _line_at(text, pos)
    # FSI…PDI: جداسازیِ دوجهتهٔ متنِ ساده (معادلِ <bdi>)، تا تکهٔ JSON داخلِ پیامِ فارسی جابه‌جا نشود.
    raise PackError(f"JSONِ نامعتبر (خط {line}، ستون {col}): {exc.msg}"
                    + (f" — «\u2068{near}\u2069»" if near else ""))


def parse_pack(raw: str) -> dict:
    """متنِ چسبانده‌شده → پاکت. بردبار نسبت به آنچه چت‌بات با فایل می‌کند؛ وگرنه `PackError`.

    پاکت **اختیاری** شده: مدلی که «فقط JSON» را جدی گرفته گاهی فقط `texts` را برمی‌گرداند،
    یا خودِ متن‌ها را بی هیچ پوششی. هر دو پذیرفته می‌شوند — زبان را به‌هرحال کدِ فرم تعیین
    می‌کند و هر کلید/متن جداگانه سنجیده می‌شود. شیئی که نه `texts` دارد نه **هیچ** کلیدِ
    متنِ ربات، فایلِ ما نیست. نشانگرِ `telabzar_i18n` اگر هست باید همین نسخه باشد.
    """
    text = (raw or "").replace("\ufeff", "").strip()
    if not text:
        raise PackError("چیزی چسبانده نشده.")
    data = _load_object(text)
    ver = data.get("telabzar_i18n")
    if ver is not None and str(ver).strip() != str(PACK_VERSION):
        raise PackError(f"نسخهٔ بسته {ver} است، این نسخه {PACK_VERSION} را می‌شناسد.")
    if "texts" not in data:
        flat = {k: v for k, v in data.items() if k not in _ENVELOPE}
        if not _KNOWN.intersection(flat):
            raise PackError("این فایلِ بستهٔ زبانِ تل‌ابزار نیست: نه کلیدِ «texts» دارد "
                            "نه هیچ‌کدام از کلیدهای متنِ ربات.")
        data = {**{k: data[k] for k in _ENVELOPE if k in data}, "texts": flat}
    texts = data["texts"]
    if not isinstance(texts, dict):
        raise PackError("«texts» باید یک شیء باشد: { \"کلید\": \"متن\", … }")
    if not texts:
        raise PackError("«texts» خالی است.")
    bad = [k for k, v in texts.items() if not isinstance(v, str)]
    if bad:
        raise PackError("مقدارِ غیرمتنی در: " + ", ".join(sorted(bad)[:5]))
    return data


@dataclass
class Review:
    """نتیجهٔ سنجشِ یک بسته — همان چیزی که به ادمین نشان داده می‌شود.

    `entries` فقط وقتی نوشته می‌شود که `errors` خالی باشد: import **اتمیک** است.
    دلیلش همان استدلالِ نوشته‌شده در `buttons_save` است — «۲۱۱ از ۲۱۴ ذخیره شد»
    یعنی زبانی نیمه‌کاره که برای کلیدهای جاافتاده به انگلیسی می‌افتد و ادمین
    نمی‌داند کدام‌ها؛ ردِ اتمیک با فهرستِ کلید+دلیل، حلقهٔ «بده به چت‌بات، درست
    کن، دوباره بچسبان» را می‌بندد.
    """

    lang: str
    name: str
    source: str
    entries: dict[str, str] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    untranslated: list[str] = field(default_factory=list)
    changed: int = 0
    same: int = 0
    #: کلیدهایی که مقدارشان **عیناً** پیش‌فرضِ کدِ همین زبان است — override نمی‌شوند.
    defaulted: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def overrides(self) -> dict[str, str]:
        """آنچه واقعاً باید در `text_overrides` نوشته شود.

        مقدارِ برابر با پیش‌فرض نوشته نمی‌شود، وگرنه یک رفت‌وبرگشتِ ساده (export و
        بعد import بی‌تغییر) ۲۱۴ ردیف می‌ساخت که پیش‌فرض را **منجمد** می‌کرد: هر
        اصلاحِ بعدیِ `locales/*.py` دیگر به کاربر نمی‌رسید، چون override برنده است.
        """
        skip = set(self.defaulted)
        return {k: v for k, v in self.entries.items() if k not in skip}

    @property
    def total(self) -> int:
        return len(TEXT_KEYS)

    @property
    def coverage(self) -> int:
        """درصدِ کلیدهایی که این بسته ترجمه‌شان می‌کند (گرد به پایین)."""
        return len(self.entries) * 100 // self.total if self.total else 0

    @property
    def errors_text(self) -> str:
        """همهٔ خطاها، یکی در هر خط — همان چیزی که ادمین کپی و به ابزارِ ترجمه برمی‌گرداند."""
        return "\n".join(f"{key}: {why}" for key, why in self.errors)

    @property
    def untouched(self) -> int:
        """کلیدهایی که بسته اصلاً به آن‌ها اشاره نکرده (در حالتِ ادغام دست‌نخورده)."""
        return len(self.missing)


def review(
    pack: dict,
    *,
    source_texts: dict[str, str],
    current: dict[str, str],
    defaults: dict[str, str] | None = None,
) -> Review:
    """بسته را می‌سنجد. هیچ‌چیز نمی‌نویسد.

    `source_texts` = متنِ مؤثرِ زبانِ **مبدأ** (همان که مترجم دیده) و قراردادِ
    placeholder از همان می‌آید نه از کاتالوگِ کد — چون ادمین ممکن است متنِ مبدأ
    را از `/texts` عوض کرده و placeholderی را عمداً انداخته باشد؛ سنجیدن در
    برابرِ کاتالوگ آن‌وقت یک ترجمهٔ **درست** را رد می‌کرد.

    `current` = متنِ مؤثرِ زبانِ **مقصد** امروز، برای شمارشِ «چند تا عوض می‌شود».

    `defaults` = پیش‌فرضِ **کدِ** زبانِ مقصد (`effective_texts(lang, {})`)؛ مقدارِ
    برابر با آن در `defaulted` می‌رود نه در `overrides`.
    """
    lang = str(pack.get("lang") or "")
    rv = Review(lang=lang, name=str(pack.get("name") or lang),
                source=str(pack.get("source") or DEFAULT))
    known = set(TEXT_KEYS)
    for key, value in pack["texts"].items():
        if key not in known:
            rv.unknown.append(key)
            rv.errors.append((key, "کلیدِ ناشناخته — در کاتالوگِ ربات نیست."))
            continue
        src = source_texts.get(key, default_text(rv.source, key))
        err = textstore.validate(src, value, require_all_placeholders=True)
        if err:
            rv.errors.append((key, err))
            continue
        rv.entries[key] = value
        if defaults is not None and value == defaults.get(key):
            rv.defaulted.append(key)
        if value == src:
            rv.untranslated.append(key)
        if value == current.get(key):
            rv.same += 1
        else:
            rv.changed += 1
    rv.missing = [k for k in TEXT_KEYS if k not in pack["texts"]]
    rv.unknown.sort()
    return rv
