"""گاردِ پینِ yt-dlp و pot-provider — تا «ارتقا» دوباره بی‌صدا یخ نزند.

**مسئله‌ای که این فایل می‌بندد (بررسیِ وابستگیِ یوتیوب به کوکی، ۲۰۲۶-۰۹):**
`yt-dlp[default]` در `requirements-worker-dl.txt` پین نشده بود و Docker لایهٔ
`pip install` را تا وقتی همان فایل عوض نشود از کش برمی‌دارد. پس «همیشه آخرین
نسخه» در عمل یعنی «نسخهٔ روزِ آخرین تغییرِ فایل» (۱۲ اوت → 2026.07.04)، و
`telabzar update` هرگز ارتقایش نمی‌داد. همان نسخه‌ای است که کلاینتِ بی‌کوکی‌اش
(`android_vr`) از ۱۷ اوت برای همهٔ فرمت‌ها 403 می‌گیرد — یعنی مسیرِ بی‌کوکی بی‌صدا
مرد و همهٔ دانلودها به کوکی افتادند.

سه ادعا، هرکدام جدا:
  ۱) تولید yt-dlp را **دقیق** پین کرده (`==`)، وگرنه همان یخ‌زدن برمی‌گردد.
  ۲) محیطِ تست همان نسخهٔ تولید است — وگرنه تستِ انتخابگرها روی موتوری سبز
     می‌شود که در تولید نیست.
  ۳) پلاگینِ bgutil و تگِ ایمیجِ سرورش هم‌نسخه‌اند و `latest` نیستند. 2.0.0 سرور
     را سخت‌گیر کرد (JSON اجباری، ردِ درخواستِ مرورگری)؛ ناهم‌نسخگی خطای بی‌صدا
     می‌دهد، نه کرشِ پرسروصدا.

متنِ فایل‌ها **پس از حذفِ کامنت** خوانده می‌شود: همین فایل‌ها توضیحِ پین را در
کامنت دارند و گاردی که کامنت را بشمارد با حذفِ خودِ پین هم سبز می‌ماند (§۶:
«هر گاردی که متن اسکن می‌کند سرانجام توضیحاتِ خودش را می‌خواند»).
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROD_REQ = ROOT / "requirements-worker-dl.txt"
DEV_REQ = ROOT / "requirements-dev.txt"
COMPOSE = ROOT / "docker-compose.yml"
POT_SERVICE = "bgutil-pot-provider"


def _pins(text: str) -> dict[str, str]:
    """نامِ بسته (بدونِ extra، حروفِ کوچک) → نسخهٔ `==`. خطوطِ بدونِ `==` نمی‌آیند.

    کامنت **قبل** از تطبیق دور ریخته می‌شود؛ یک `yt-dlp==1.0` داخلِ کامنت پین نیست.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*==\s*([0-9][0-9A-Za-z.\-]*)$", line)
        if m:
            out[m.group(1).lower()] = m.group(3)
    return out


def _vtuple(v: str) -> tuple[int, ...]:
    """`2026.08.19` و `2026.8.19` یکی‌اند (PEP 440 صفرِ پیشرو را می‌ریزد)."""
    return tuple(int(p) for p in re.findall(r"\d+", v))


def _pot_image_tag() -> str:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    image = services[POT_SERVICE]["image"]
    assert ":" in image, f"ایمیجِ {POT_SERVICE} تگِ صریح ندارد: {image!r}"
    return image.rsplit(":", 1)[1]


# ── ادعای ۱ ───────────────────────────────────────────────────────────────────
def test_production_pins_yt_dlp_exactly():
    pins = _pins(PROD_REQ.read_text(encoding="utf-8"))
    assert "yt-dlp" in pins, (
        "yt-dlp در requirements-worker-dl.txt با `==` پین نشده — Docker لایهٔ pip را "
        "از کش برمی‌دارد و ارتقا هرگز اعمال نمی‌شود")


def test_production_pins_the_pot_plugin_exactly():
    pins = _pins(PROD_REQ.read_text(encoding="utf-8"))
    assert "bgutil-ytdlp-pot-provider" in pins


# ── ادعای ۲ ───────────────────────────────────────────────────────────────────
def test_the_test_environment_pins_the_production_yt_dlp():
    prod = _pins(PROD_REQ.read_text(encoding="utf-8"))["yt-dlp"]
    dev = _pins(DEV_REQ.read_text(encoding="utf-8")).get("yt-dlp")
    assert dev is not None, "requirements-dev.txt نسخهٔ yt-dlp را پین نکرده"
    assert _vtuple(dev) == _vtuple(prod), (dev, prod)


def test_the_installed_yt_dlp_is_the_pinned_one():
    """محیطی که همین حالا تست را اجرا می‌کند واقعاً همان نسخه را دارد.

    بدونِ این، یک venvِ کهنه تست‌های انتخابگر را روی موتورِ دیگری سبز می‌کند —
    همان «سبزیِ محلی شاهدی دربارهٔ محیطِ محلی است، نه کد» (§۶).
    """
    import yt_dlp.version

    prod = _pins(PROD_REQ.read_text(encoding="utf-8"))["yt-dlp"]
    assert _vtuple(yt_dlp.version.__version__) == _vtuple(prod), (
        f"yt-dlp نصب‌شده {yt_dlp.version.__version__} است ولی تولید {prod} — "
        f"`pip install -r requirements-dev.txt` را دوباره بزن")


# ── ادعای ۳ ───────────────────────────────────────────────────────────────────
def test_the_pot_server_image_is_pinned_not_latest():
    tag = _pot_image_tag()
    assert tag not in ("latest", "node", "deno", "master-node", "master-deno"), (
        f"تگِ متحرکِ {tag!r} فقط سرِ اولین pull خوانده می‌شود و بعد یخ می‌زند")


def test_the_pot_plugin_and_server_are_the_same_version():
    plugin = _pins(PROD_REQ.read_text(encoding="utf-8"))["bgutil-ytdlp-pot-provider"]
    tag = _pot_image_tag()
    base = tag.split("-", 1)[0]                   # `2.0.0-node` → `2.0.0`
    assert _vtuple(base) == _vtuple(plugin), (plugin, tag)


# ── کنترل‌ها: خودِ پارسر ────────────────────────────────────────────────────────
def test_an_unpinned_requirement_is_not_read_as_a_pin():
    assert "yt-dlp" not in _pins("yt-dlp[default]            # موتورِ اصلی\n")
    assert "yt-dlp" not in _pins("yt-dlp>=2026.1\n")


def test_a_pin_written_only_in_a_comment_does_not_count():
    """کنترلِ خودارجاعی: کامنتِ همین فایل‌ها عددِ پین را توضیح می‌دهد."""
    assert "yt-dlp" not in _pins("# yt-dlp[default]==2026.8.19 را پین کن\nyt-dlp[default]\n")


def test_the_parser_reads_a_pin_with_an_extra_and_a_trailing_comment():
    assert _pins("yt-dlp[default]==2026.8.19   # توضیح\n") == {"yt-dlp": "2026.8.19"}
