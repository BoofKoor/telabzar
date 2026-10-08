"""نصب‌کننده: دامنهٔ پنل، بررسیِ DNS/پورت، گرفتنِ سرتیفیکیت، و `.env`ی که می‌نویسد.

**تابع‌های واقعیِ `install.sh` اجرا می‌شوند، زیرِ همان `set -euo pipefail`ِ خودش** —
نه بازنویسیِ منطقشان در پایتون. فایل با `TELABZAR_INSTALL_LIB=1` source می‌شود (همهٔ
تابع‌ها تعریف می‌شوند و نصب شروع نمی‌شود)، و فقط چیزهایی که به ماشین بند است جعل
می‌شوند: `getent`، `curl`، `ss`، `ip` و `docker` به‌صورتِ اسکریپت‌های کوچک روی `PATH`.

**چرا زیرِ همان گزینه‌ها و نه یک bashِ ساده:** اولین نسخهٔ `check_dns` روی دامنه‌ای که
هنوز resolve نمی‌شود — یعنی رایج‌ترین حالتِ یک نصبِ تازه — **بی‌هیچ پیامی** خارج
می‌شد: `getent` کدِ ۲ می‌دهد، `pipefail` آن را به خطِ انتساب می‌رساند و `errexit`
اسکریپت را می‌بندد. فقط اجرا زیرِ همان گزینه‌ها این را می‌بیند.
"""
from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from app import settings_store as ss

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"

#: یک IPِ مستندسازی (RFC 5737) به‌جای IPِ «همین سرور».
HERE = "203.0.113.5"

_STUBS = {
    # A = $STUB_V4، AAAA = $STUB_V6 (فاصله‌جدا). بدونِ رکورد، مثلِ getentِ واقعی: کدِ ۲.
    "getent": r'''#!/bin/bash
case "$1" in
  ahostsv4) list="$STUB_V4" ;;
  ahostsv6) list="$STUB_V6"; for a in $STUB_V4; do list="$list ::ffff:$a"; done ;;
  *) exit 2 ;;
esac
[ -n "${list// /}" ] || exit 2
for a in $list; do echo "$a STREAM $2"; done
''',
    # هر فراخوانی در $STUB_LOG ثبت می‌شود تا تست بشمارد چند بار HTTPS زده شد.
    "curl": r'''#!/bin/bash
echo "curl $*" >> "$STUB_LOG"
case " $* " in
  *api.ipify.org*) [ -n "$STUB_IP" ] && { echo "$STUB_IP"; exit 0; }; exit 7 ;;
  *--resolve*) exit "${STUB_HTTPS_RC:-0}" ;;
esac
exit 0
''',
    "ip": "#!/bin/bash\nexit 2\n",
    # `ss -Hltnp "sport = :80"` → $STUB_SS_80
    "ss": r'''#!/bin/bash
for a in "$@"; do case "$a" in *":80") v="$STUB_SS_80" ;; *":443") v="$STUB_SS_443" ;; esac; done
[ -n "$v" ] && echo "$v"
exit 0
''',
    "docker": r'''#!/bin/bash
echo "docker $*" >> "$STUB_LOG"
[ "$*" = "compose ps -q caddy" ] && [ -n "$STUB_CADDY_ID" ] && echo "$STUB_CADDY_ID"
exit 0
''',
    "sleep": "#!/bin/bash\nexit 0\n",
}


@pytest.fixture
def sh(tmp_path):
    """`sh(script, stdin=..., **env)` → (کدِ خروج، stdout+stderr، لاگِ stubها)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in _STUBS.items():
        f = bindir / name
        f.write_text(body)
        f.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    log = tmp_path / "stub.log"

    def run(script: str, stdin: str = "", **env):
        log.write_text("")
        e = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
             "TELABZAR_INSTALL_LIB": "1", "STUB_LOG": str(log),
             "STUB_IP": HERE, "STUB_V4": "", "STUB_V6": "", "STUB_SS_80": "",
             "STUB_SS_443": "", "STUB_CADDY_ID": "", "STUB_HTTPS_RC": "0"}
        e.update({k: str(v) for k, v in env.items()})
        full = f'source "{INSTALL}"\nCOMPOSE="docker compose"\n{script}\n'
        r = subprocess.run(["bash", "-c", full], cwd=work, input=stdin, env=e,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout + r.stderr, log.read_text()

    run.work = work
    return run


def test_the_installer_parses():
    r = subprocess.run(["bash", "-n", str(INSTALL)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_sourcing_with_the_lib_flag_defines_without_installing(sh):
    rc, out, log = sh("type check_dns >/dev/null && echo DEFINED")
    assert rc == 0 and "DEFINED" in out
    assert "interactive setup" not in out and "docker" not in log


# ── نام ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,want", [
    ("panel.example.com", "panel.example.com"),
    ("HTTPS://Panel.Example.COM/", "panel.example.com"),
    ("http://panel.example.com", "panel.example.com"),
    ("  panel.example.com.  ", "panel.example.com"),
], ids=["plain", "url-case", "http", "spaces-dot"])
def test_clean_domain(sh, raw, want):
    rc, out, _ = sh(f'printf "[%s]" "$(clean_domain "{raw}")"')
    assert rc == 0 and out == f"[{want}]"


_CANDIDATES = ["panel.example.com", "a.bc", "x-y.example.co.uk", "xn--mgbpb7fjn.example.com",
               "localhost", "1.2.3.4", "panel_x.example.com", "-a.example.com", "a-.example.com",
               "a..example.com", "panel.example.com:2083", "panel.example.com/admin", "*.example.com",
               "panel.example.1", ("x" * 64) + ".example.com", "پنل.example.com"]


def _bash_valid(sh, names) -> dict[str, bool]:
    script = "\n".join(f'valid_domain "{n}" && echo "Y {n}" || echo "N {n}"' for n in names)
    rc, out, _ = sh(script)
    assert rc == 0, out
    return {ln[2:]: ln[0] == "Y" for ln in out.splitlines() if ln[:2] in ("Y ", "N ")}


def test_valid_domain_accepts_and_refuses(sh):
    got = _bash_valid(sh, _CANDIDATES)
    assert {n for n, ok in got.items() if ok} == {
        "panel.example.com", "a.bc", "x-y.example.co.uk", "xn--mgbpb7fjn.example.com"}


def test_every_name_the_installer_accepts_is_already_canonical_for_the_panel(sh):
    """`PANEL_DOMAIN` دو خواننده دارد که باید یک نام ببینند: Caddy (`@panel host`، مقدارِ
    خام) و `/tls/ask` (`settings_store.panel_domain()`، نرمال‌شده). اگر نصب‌کننده نامی
    بپذیرد که نرمال‌سازی عوضش کند، Caddy پنل را روی آن مسیر می‌دهد ولی `/tls/ask`
    سرتیفیکیتش را رد می‌کند — پنلی که هرگز HTTPS نمی‌شود، بی‌هیچ خطایی."""
    for name, ok in _bash_valid(sh, _CANDIDATES).items():
        if ok:
            assert ss.normalize_domain(name) == name, name


# ── DNS ─────────────────────────────────────────────────────────────────────
def test_a_domain_pointing_here_is_ok(sh):
    rc, out, _ = sh('check_dns panel.example.com; echo "STATE=$DNS_STATE"', STUB_V4=HERE)
    assert rc == 0 and "STATE=ok" in out
    assert "IPv6" not in out          # ::ffff:ِ getent رکوردِ AAAA نیست


def test_a_domain_that_does_not_resolve_yet_is_a_warning_not_a_silent_exit(sh):
    """رایج‌ترین حالتِ نصبِ تازه. نسخهٔ اول این‌جا بی‌هیچ پیامی خارج می‌شد."""
    rc, out, _ = sh('check_dns panel.example.com; echo "STATE=$DNS_STATE"; echo AFTER')
    assert rc == 0, out
    assert "STATE=missing" in out and "AFTER" in out
    assert "does not resolve" in out and HERE in out      # می‌گوید به کدام IP اشاره کند


def test_a_domain_pointing_elsewhere_names_both_addresses(sh):
    rc, out, _ = sh('check_dns panel.example.com; echo "STATE=$DNS_STATE"', STUB_V4="198.51.100.9")
    assert rc == 0 and "STATE=elsewhere" in out
    assert "198.51.100.9" in out and HERE in out and "DNS only" in out


def test_an_undetectable_server_ip_is_unknown_not_a_crash(sh):
    rc, out, _ = sh('check_dns panel.example.com; echo "STATE=$DNS_STATE"', STUB_IP="",
                    STUB_V4="198.51.100.9")
    assert rc == 0 and "STATE=unknown" in out


def test_a_stray_aaaa_record_is_flagged(sh):
    """Let's Encrypt اول IPv6 را می‌سنجد؛ AAAAی کهنه با A ی درست هم سرتیفیکیت را می‌شکند."""
    rc, out, _ = sh("check_dns panel.example.com", STUB_V4=HERE, STUB_V6="2001:db8::1")
    assert rc == 0 and "2001:db8::1" in out and "IPv6" in out


# ── پورت‌ها ──────────────────────────────────────────────────────────────────
_NGINX = 'LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=812,fd=6))'
_PROXY = 'LISTEN 0 4096 0.0.0.0:443 0.0.0.0:* users:(("docker-proxy",pid=99,fd=4))'


def test_free_ports_pass_silently(sh):
    rc, out, _ = sh("check_ports; echo AFTER")
    assert rc == 0 and out.strip() == "AFTER"


def test_docker_proxy_is_not_a_conflict(sh):
    rc, out, _ = sh("check_ports; echo AFTER", STUB_SS_443=_PROXY)
    assert rc == 0 and "in use" not in out


def test_another_web_server_stops_the_install_by_default(sh):
    rc, out, _ = sh("check_ports; echo AFTER", stdin="\n", STUB_SS_80=_NGINX)
    assert rc == 1 and "AFTER" not in out
    assert "Port 80" in out and "Free ports 80/443" in out


def test_the_admin_may_continue_anyway(sh):
    rc, out, _ = sh("check_ports; echo AFTER", stdin="y\n", STUB_SS_80=_NGINX)
    assert rc == 0 and "AFTER" in out


def test_a_reconfigure_with_our_own_caddy_running_is_not_a_conflict(sh):
    """`ss -p` نامِ پروسه را فقط به root نشان می‌دهد؛ پس «caddyِ خودمان» از compose پرسیده می‌شود."""
    rc, out, _ = sh("check_ports; echo AFTER", STUB_SS_80="LISTEN 0 4096 0.0.0.0:80 0.0.0.0:*",
                    STUB_CADDY_ID="abc123")
    assert rc == 0 and "in use" not in out


# ── گرفتنِ سرتیفیکیت ─────────────────────────────────────────────────────────
def _https_calls(log: str) -> list[str]:
    return [ln for ln in log.splitlines() if "--resolve" in ln]


def test_the_certificate_is_requested_once_through_the_local_caddy(sh):
    rc, out, log = sh("DNS_STATE=ok; issue_panel_cert panel.example.com")
    assert rc == 0 and "HTTPS works" in out
    calls = _https_calls(log)
    assert len(calls) == 1
    assert "panel.example.com:443:127.0.0.1" in calls[0] and "https://panel.example.com/" in calls[0]


def test_a_failed_certificate_is_reported_and_not_retried(sh):
    """یک تلاش: Let's Encrypt در هر ساعت ۵ شکستِ اعتبارسنجی برای هر نام می‌پذیرد."""
    rc, out, log = sh("DNS_STATE=ok; issue_panel_cert panel.example.com; echo AFTER",
                      STUB_HTTPS_RC=35)
    assert rc == 0 and "AFTER" in out and "No certificate yet" in out
    assert len(_https_calls(log)) == 1


@pytest.mark.parametrize("state", ["missing", "elsewhere"])
def test_no_request_is_spent_on_a_name_that_does_not_point_here(sh, state):
    rc, out, log = sh(f"DNS_STATE={state}; issue_panel_cert panel.example.com")
    assert rc == 0 and _https_calls(log) == []
    assert "does not point to this server" in out


# ── سرتاسری: `install_master` و `.env`ی که می‌نویسد ─────────────────────────────
_ANSWERS = ["123456:ABC", "1234567", "hash", "111", "", ""]   # توکن، API ID/HASH، ادمین، زبان، حجم


def _install(sh, domain_answers: list[str], **env):
    stdin = "\n".join(_ANSWERS + domain_answers + ["y", "n"]) + "\n"   # تأیید، نودها
    rc, out, log = sh("install_cli() { :; }\ninstall_master", stdin=stdin, **env)
    dotenv = (sh.work / ".env").read_text() if (sh.work / ".env").exists() else ""
    return rc, out, log, dict(ln.split("=", 1) for ln in dotenv.splitlines()
                              if ln and not ln.startswith("#"))


def test_a_domain_install_writes_https_and_keeps_the_plain_ports_local(sh):
    rc, out, log, env = _install(sh, ["HTTPS://Panel.Example.com/"], STUB_V4=HERE)
    assert rc == 0, out
    assert env["PANEL_DOMAIN"] == "panel.example.com"
    assert env["ADMIN_BASE"] == "https://panel.example.com"
    assert env["ADMIN_BIND"] == "127.0.0.1" and env["GATEWAY_BIND"] == "127.0.0.1"
    assert not {"PUBLIC_BASE", "TLS_CERT", "TLS_KEY", "GATEWAY_HTTPS_PORT"} & env.keys()
    assert "docker compose up -d --build" in log
    assert len(_https_calls(log)) == 1 and "HTTPS works" in out


def test_a_bad_domain_is_asked_again(sh):
    rc, out, _, env = _install(sh, ["panel.example.com:2083", "panel.example.com"], STUB_V4=HERE)
    assert rc == 0, out
    assert "not a valid domain" in out and env["PANEL_DOMAIN"] == "panel.example.com"


def test_an_install_without_a_domain_keeps_the_old_reachable_panel(sh):
    rc, out, log, env = _install(sh, [""])
    assert rc == 0, out
    assert env["PANEL_DOMAIN"] == "" and env["ADMIN_BASE"] == ""
    assert env["ADMIN_BIND"] == "0.0.0.0"          # پنل روی http://IP:2083 — وگرنه هیچ راهی نبود
    assert _https_calls(log) == []


def test_a_reconfigure_keeps_the_domain_and_the_secrets(sh):
    rc, out, _, first = _install(sh, ["panel.example.com"], STUB_V4=HERE)
    assert rc == 0, out
    rc, out, _, again = _install(sh, [""], STUB_V4=HERE)           # Enter = نگه‌داشتن
    assert rc == 0, out
    assert again["PANEL_DOMAIN"] == "panel.example.com"
    assert again["ADMIN_SECRET"] == first["ADMIN_SECRET"]
    assert again["POSTGRES_PASSWORD"] == first["POSTGRES_PASSWORD"]


def test_a_reconfigure_can_remove_the_domain(sh):
    rc, out, _, _ = _install(sh, ["panel.example.com"], STUB_V4=HERE)
    assert rc == 0, out
    rc, out, _, env = _install(sh, ["-"])
    assert rc == 0, out
    assert env["PANEL_DOMAIN"] == "" and env["ADMIN_BIND"] == "0.0.0.0"
