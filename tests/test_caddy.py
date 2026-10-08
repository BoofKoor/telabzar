"""Caddy، درِ ورودیِ HTTPS — گاردهای `docker-compose.yml` و `docker/caddy/Caddyfile`.

این دو فایل کد نیستند ولی پنل و لینک بدونِ آن‌ها HTTPS نمی‌شوند، و هر خرابیِ‌شان
**بی‌صدا** است: Caddy در حلقهٔ ری‌استارت می‌افتد، یا سرتیفیکیت هرگز نمی‌آید، یا
درخواست به سرویسِ اشتباه می‌رود — و هیچ تستِ پایتونی جز همین‌ها چیزی نمی‌بیند.

دو لایه، عمداً جدا:
* **ساختار** (همیشه): ادعاهای مشخص روی compose و Caddyfile، هرکدام با دلیلش.
* **پارسرِ واقعی** (وقتی باینریِ `caddy` با همان نسخهٔ پین‌شده روی `PATH` است):
  `caddy validate` همان چیزی را می‌سنجد که سرِ استارتِ کانتینر اجرا می‌شود. CI
  باینری را از ریلیزِ رسمی نصب می‌کند (`.github/workflows/tests.yml`)، و
  `test_the_caddy_validation_is_not_dead_weight` نمی‌گذارد آن گام بی‌صدا برود —
  همان درسِ `needs_7z`/`ffmpeg` در §۶: تستی که فقط skip می‌شود از هیچ چیز محافظت
  نمی‌کند.

**کامنت‌های Caddyfile پیش از هر ادعا دور ریخته می‌شوند.** کامنت‌های فارسیِ همان فایل
نامِ هر چیزی را که این‌جا جست‌وجو می‌شود می‌برند (`ask`، `PANEL_DOMAIN`، …)، و §۶
سه بار ثبت کرده که گاردی که توضیحاتِ خودش را اسکن کند برای همیشه سبز می‌ماند.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

from app.config import Settings

ROOT = pathlib.Path(__file__).resolve().parent.parent
CADDYFILE = ROOT / "docker" / "caddy" / "Caddyfile"
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
CADDY = COMPOSE["services"]["caddy"]
PIN = re.fullmatch(r"caddy:(\d+\.\d+\.\d+)-alpine", CADDY["image"])

_COMMENT = re.compile(r"(^|\s)#.*$")


def _code(text: str) -> str:
    """Caddyfile بدونِ کامنت (`#` در ابتدای یک توکن، مثلِ خودِ lexerِ Caddy)."""
    return "\n".join(_COMMENT.sub("", ln).rstrip() for ln in text.splitlines())


CODE = _code(CADDYFILE.read_text(encoding="utf-8"))


def test_the_comment_stripper_does_not_count_prose():
    """کنترلِ خودارجاعی: نامی که فقط در کامنت آمده نباید «در Caddyfile هست» خوانده شود."""
    assert "ask" not in _code("# ask http://admin:8080/tls/ask\n\t# reverse_proxy x")
    assert _code("\treverse_proxy admin:8080 # inline").strip() == "reverse_proxy admin:8080"


# ── ایمیج و پورت ─────────────────────────────────────────────────────────────
def test_caddy_is_pinned():
    """مثلِ بقیهٔ ایمیج‌ها: `latest` یعنی هر `telabzar update` ممکن است پارسرِ دیگری بیاورد."""
    assert PIN, f"ایمیجِ caddy باید نسخهٔ دقیق داشته باشد، نه {CADDY['image']!r}"


def test_caddy_publishes_80_and_443_over_tcp_only():
    """۸۰ برای چالشِ HTTP-01 و ریدایرکت، ۴۴۳ برای سرو و TLS-ALPN-01. UDPِ ۴۴۳ منتشر
    نمی‌شود، پس HTTP/3 هم باید خاموش باشد — وگرنه Alt-Svc مرورگر را به پورتی می‌فرستد که نیست."""
    assert sorted(CADDY["ports"]) == ["443:443", "80:80"]
    assert re.search(r"^\s*protocols h1 h2\s*$", CODE, re.M)


def test_caddy_binds_low_ports_with_every_other_capability_dropped():
    assert CADDY["cap_drop"] == ["ALL"] and CADDY["cap_add"] == ["NET_BIND_SERVICE"]
    assert "no-new-privileges:true" in CADDY["security_opt"]


def test_caddy_gets_no_secrets():
    """جز `PANEL_DOMAIN` چیزی لازم ندارد؛ `env_file` یعنی `BOT_TOKEN` و همهٔ اسرار در یک
    سرویسِ رو‌به‌اینترنت."""
    assert "env_file" not in CADDY
    assert set(CADDY["environment"]) == {"PANEL_DOMAIN"}


# ── دامنهٔ پنل ───────────────────────────────────────────────────────────────
def test_an_empty_panel_domain_is_replaced_before_caddy_sees_it():
    """`:-` نه `-`: نصبِ بدونِ دامنه `PANEL_DOMAIN=` (خالی) می‌نویسد، و Caddy با `host`ِ
    خالی اصلاً بالا نمی‌آید (`test_an_empty_panel_domain_would_crash_caddy`) — آن‌وقت
    دامنهٔ لینک هم با آن می‌خوابد. پیش‌فرضِ `{$VAR:…}`ِ خودِ Caddyfile فقط متغیرِ
    **نبوده** را می‌گیرد، نه خالی را."""
    assert CADDY["environment"]["PANEL_DOMAIN"] == "${PANEL_DOMAIN:-panel.invalid}"


def test_the_caddyfile_routes_the_panel_host_by_the_same_variable():
    m = re.search(r"@panel host \{\$(\w+):([\w.-]+)\}", CODE)
    assert m, "matcherِ میزبانِ پنل پیدا نشد"
    assert m.group(1) in CADDY["environment"]
    assert m.group(2).endswith(".invalid")       # هرگز resolve نمی‌شود، پس هرگز صادر نمی‌شود


# ── گیتِ صدور و مسیریابی ──────────────────────────────────────────────────────
def _registered_routes() -> set[str]:
    """مسیرهای GETِ پنل، از سورس با AST — `admin_web` در محیطِ تستِ اصلی import نمی‌شود."""
    tree = ast.parse((ROOT / "app" / "admin_web.py").read_text(encoding="utf-8"))
    return {n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_get"
            and n.args and isinstance(n.args[0], ast.Constant)}


def test_every_name_is_issued_on_demand_and_only_after_asking_the_panel():
    """بدونِ `ask`، هر کسی با یک SNIِ دلخواه سهمیهٔ صدورِ Let's Encrypt را می‌سوزاند."""
    m = re.search(r"on_demand_tls \{\s*ask (http://([\w-]+):(\d+)(/\S+))\s*\}", CODE)
    assert m, "گیتِ ask در بلوکِ سراسری نیست"
    _url, host, port, path = m.groups()
    assert host == "admin" and host in COMPOSE["services"]
    assert int(port) == Settings.model_fields["admin_port"].default
    assert path in _registered_routes(), f"پنل {path} را ثبت نکرده"
    assert re.search(r"tls \{\s*on_demand\s*\}", CODE)


def test_the_panel_host_goes_to_the_panel_and_everything_else_to_the_gateway():
    """ترتیب باربر است: `handle`ِ بدونِ matcher همه چیز را می‌گیرد، پس باید آخر باشد."""
    panel = re.search(r"handle @panel \{\s*reverse_proxy ([\w-]+):(\d+)\s*\}", CODE)
    rest = re.search(r"handle \{\s*reverse_proxy ([\w-]+):(\d+)\s*\}", CODE)
    assert panel and rest and panel.start() < rest.start()
    assert panel.group(1) == "admin" and int(panel.group(2)) == Settings.model_fields["admin_port"].default
    assert rest.group(1) == "gateway" and int(rest.group(2)) == Settings.model_fields["gateway_port"].default
    assert {"admin", "gateway"} <= set(COMPOSE["services"])


# ── انبار و mountها ───────────────────────────────────────────────────────────
def test_certificates_survive_a_rebuild():
    """بدونِ volume هر بازسازیِ کانتینر یعنی صدورِ دوباره، و Let's Encrypt بیش از ۵
    سرتیفیکیتِ تکراری در هفته نمی‌دهد."""
    assert {"caddy-data:/data", "caddy-config:/config"} <= set(CADDY["volumes"])
    assert {"caddy-data", "caddy-config"} <= set(COMPOSE["volumes"])


def test_the_caddyfile_is_mounted_as_its_directory():
    """bindِ تک‌فایل به inodeِ لحظهٔ ساخت می‌چسبد و git فایل را با inodeِ تازه بازنویسی
    می‌کند، پس `telabzar update` نسخهٔ تازه را به Caddy نمی‌رساند."""
    assert "./docker/caddy:/etc/caddy:ro" in CADDY["volumes"]


def test_the_panel_reads_caddys_storage_read_only():
    """کارتِ HTTPSِ سلامت تاریخِ انقضا را از همین انبار می‌خواند — فقط‌خواندنی."""
    admin = COMPOSE["services"]["admin"]
    tree = ast.parse((ROOT / "app" / "admin_web.py").read_text(encoding="utf-8"))
    data = next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_CADDY_DATA")
    assert f"caddy-data:{data}:ro" in admin["volumes"]


def test_the_plain_ports_keep_the_old_behaviour_unless_told_otherwise():
    """نصب‌کننده با دامنه `ADMIN_BIND`/`GATEWAY_BIND` را `127.0.0.1` می‌نویسد؛ نبودنِ کلید
    (نصبِ پیش از ۲۰۲۶-۱۰) همان `0.0.0.0`ِ قبلی است، وگرنه پنلِ آن نصب بعد از
    `telabzar update` بی‌صدا از اینترنت ناپدید می‌شد."""
    assert COMPOSE["services"]["admin"]["ports"] == ["${ADMIN_BIND:-0.0.0.0}:${ADMIN_HTTPS_PORT:-2083}:8080"]
    assert COMPOSE["services"]["gateway"]["ports"] == [
        "${GATEWAY_BIND:-0.0.0.0}:${GATEWAY_HTTPS_PORT:-8443}:8080"]


# ── پارسرِ واقعی ───────────────────────────────────────────────────────────────
def _pinned_caddy() -> str | None:
    exe = shutil.which("caddy")
    if not exe or not PIN:
        return None
    out = subprocess.run([exe, "version"], capture_output=True, text=True).stdout
    return exe if out.startswith(f"v{PIN.group(1)} ") else None


needs_caddy = pytest.mark.skipif(_pinned_caddy() is None,
                                 reason="باینریِ caddy با نسخهٔ پین‌شده روی PATH نیست")


def _validate(env_patch: dict[str, str | None]):
    env = {k: v for k, v in os.environ.items() if k != "PANEL_DOMAIN"}
    env.update({k: v for k, v in env_patch.items() if v is not None})
    return subprocess.run([_pinned_caddy(), "validate", "--config", str(CADDYFILE),
                           "--adapter", "caddyfile"], capture_output=True, text=True,
                          env=env, timeout=60)


@needs_caddy
@pytest.mark.parametrize("value", ["panel.example.com", None], ids=["domain", "unset"])
def test_the_caddyfile_is_valid_for_the_pinned_caddy(value):
    r = _validate({"PANEL_DOMAIN": value})
    assert r.returncode == 0, r.stderr[-800:]


@needs_caddy
def test_an_empty_panel_domain_would_crash_caddy():
    """کنترلِ منفی: ثابت می‌کند هارنس می‌تواند «نامعتبر» بگوید، و دلیلِ `:-`ِ compose را
    با خودِ پارسر نگه می‌دارد نه با یک کامنت."""
    r = _validate({"PANEL_DOMAIN": ""})
    assert r.returncode != 0 and "cannot be null" in r.stderr


@needs_caddy
def test_the_caddyfile_is_formatted():
    """فایلِ نامرتب در هر استارت یک WARN در `telabzar logs caddy` می‌گذارد — همان‌جا که
    ادمین دنبالِ علتِ نیامدنِ سرتیفیکیت می‌گردد."""
    r = subprocess.run([_pinned_caddy(), "fmt", str(CADDYFILE)], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == CADDYFILE.read_text(encoding="utf-8")


def test_the_caddy_validation_is_not_dead_weight():
    """jobِ اصلیِ CI باید همان نسخهٔ پین‌شده را **پیش از** pytest نصب کند، وگرنه سه تستِ
    بالا روی رانر skip می‌شوند و پارسرِ واقعی هیچ‌جا اجرا نمی‌شود."""
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["pytest"]["steps"]
    runs = [s.get("run", "") for s in steps]
    install = next((i for i, r in enumerate(runs)
                    if "caddyserver/caddy/releases/download" in r and "docker-compose.yml" in r), None)
    tests = next((i for i, r in enumerate(runs) if r.strip().startswith("pytest")), None)
    assert install is not None, "گامِ نصبِ caddy (با نسخهٔ خوانده‌شده از compose) در jobِ pytest نیست"
    assert tests is not None and install < tests
