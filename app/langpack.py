"""بستهٔ زبان — ساخت/خواندن/سنجشِ فایلِ export/importِ ترجمه.

**عمداً خالص و بی‌دیتابیس.** مصرف‌کننده‌اش `admin_web` است، ولی منطقِ واقعی
(نرمال‌سازیِ کدِ زبان، پاکت، اعتبارسنجیِ ورودی) این‌جاست تا jobِ **اصلیِ** تست
بتواند بسنجدش؛ `tests/panel` یک jobِ جداست که `jinja2`/`cryptography` می‌خواهد،
و قاعده‌ای که فقط آن‌جا تست شود نصفِ CI را بی‌پوشش می‌گذارد. همان دلیلی که
`cookies.py` و `dl_active.py` را سرِ جایشان نشانده.

**مصرف‌کنندهٔ فایل یک چت‌بات است، نه یک برنامه.** پس شکلش JSON با یک پاکت است
(`readme` داخلِ خودِ فایل، تا دستور همراهِ داده سفر کند)، و خواندنش نسبت به
کارهایی که یک مدل با متن می‌کند بردبار است: فنسِ ```‎، BOM، فاصلهٔ اضافه.
"""
from __future__ import annotations

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

#: سقفِ ستونِ کدِ زبان (`models.LANG_LEN`). کرانِ **واقعی** الگوی زیر است؛ این
#: فقط عرضِ ذخیره‌سازی است و باید با ستون یکی بماند.
MAX_CODE_LEN = 16

#: کدِ زبان به سبکِ BCP 47: زیرتگِ اصلیِ ۲–۳ حرفی، به‌علاوهٔ زیرتگ‌های ۲–۸
#: حرفی/عددی. عمداً روی **فرمت** است نه طول: `pt-BR` و `zh-Hant-TW` کدهای
#: واقعی‌اند و قفل‌کردنِ دو کاراکتر یعنی اولین زبانِ این‌شکلی یک مهاجرت می‌خواهد.
_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n(.*?)\n?\s*```\s*$", re.S)


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
        "Return the COMPLETE file. Do not drop, add, reorder or summarise entries.",
        "A value already written in the target language should be reviewed, not re-translated.",
        "Reply with the JSON only.",
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


def parse_pack(raw: str) -> dict:
    """متنِ چسبانده‌شده → پاکت. بردبار نسبت به فنس/BOM/فاصله؛ وگرنه `PackError`."""
    text = (raw or "").replace("﻿", "").strip()
    if not text:
        raise PackError("چیزی چسبانده نشده.")
    m = _FENCE_RE.match(text)
    if m:                                   # مدل‌ها معمولاً داخلِ ```json می‌گذارند
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PackError(f"JSONِ نامعتبر (خط {exc.lineno}، ستون {exc.colno}): {exc.msg}") from exc
    if not isinstance(data, dict):
        raise PackError("ریشهٔ فایل باید یک شیءِ JSON باشد.")
    ver = data.get("telabzar_i18n")
    if ver is None:
        raise PackError("کلیدِ «telabzar_i18n» نیست — این فایلِ بستهٔ زبانِ تل‌ابزار نیست.")
    if ver != PACK_VERSION:
        raise PackError(f"نسخهٔ بسته {ver} است، این نسخه {PACK_VERSION} را می‌شناسد.")
    texts = data.get("texts")
    if not isinstance(texts, dict):
        raise PackError("کلیدِ «texts» نیست یا شیء نیست.")
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

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def total(self) -> int:
        return len(TEXT_KEYS)

    @property
    def coverage(self) -> int:
        """درصدِ کلیدهایی که این بسته ترجمه‌شان می‌کند (گرد به پایین)."""
        return len(self.entries) * 100 // self.total if self.total else 0

    @property
    def untouched(self) -> int:
        """کلیدهایی که بسته اصلاً به آن‌ها اشاره نکرده (در حالتِ ادغام دست‌نخورده)."""
        return len(self.missing)


def review(
    pack: dict,
    *,
    source_texts: dict[str, str],
    current: dict[str, str],
) -> Review:
    """بسته را می‌سنجد. هیچ‌چیز نمی‌نویسد.

    `source_texts` = متنِ مؤثرِ زبانِ **مبدأ** (همان که مترجم دیده) و قراردادِ
    placeholder از همان می‌آید نه از کاتالوگِ کد — چون ادمین ممکن است متنِ مبدأ
    را از `/texts` عوض کرده و placeholderی را عمداً انداخته باشد؛ سنجیدن در
    برابرِ کاتالوگ آن‌وقت یک ترجمهٔ **درست** را رد می‌کرد.

    `current` = متنِ مؤثرِ زبانِ **مقصد** امروز، برای شمارشِ «چند تا عوض می‌شود».
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
        if value == src:
            rv.untranslated.append(key)
        if value == current.get(key):
            rv.same += 1
        else:
            rv.changed += 1
    rv.missing = [k for k in TEXT_KEYS if k not in pack["texts"]]
    rv.unknown.sort()
    return rv
