"""لاگِ کارهای ادمین (`admin_actions`) — نوشته شود، راز نبرد، و خوانا رندر شود.

پیش‌زمینه: لاگ از بازطراحیِ ۲۰۲۶-۱۰ آمد (برگهٔ «لاگ ادمین» در فعالیت‌ها). سه ردهٔ خرابی
که این فایل می‌بندد، اولی **اجراشده** در همین کار:

* **پارامترِ همنام.** `_audit(request, action, target, admin_id, **detail)` — جزئیاتی
  به نامِ `action=` با خودِ پارامتر برخورد می‌کرد و `TypeError` می‌داد **پیش از** هر
  نوشتنی، پس دکمهٔ «استراحتِ ۳۰ دقیقه‌ای» کوکی همیشه ۵۰۰ می‌داد. گارد نام‌ها را از
  امضای خودِ `_audit` کشف می‌کند، نه فهرستِ دستی.
* **راز در لاگ.** مقدارِ کلیدِ `secret` و userinfoِ پروکسی هرگز نوشته نمی‌شود.
* **کارِ بی‌برچسب.** هر `action`ی که نوشته می‌شود برچسبِ `lg.<action>` و آیکون دارد.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

from pagefacts import shows
from sqlalchemy import select
from test_panel_css_classes import _fetch

SRC = pathlib.Path(__file__).resolve().parents[2] / "app" / "admin_web.py"


def _audit_calls() -> list[ast.Call]:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "_audit"]


def logged_actions() -> set[str]:
    """هر `action`ی که در سورس به `_audit` داده می‌شود — لفظی، یا `"prefix" + x`."""
    out: set[str] = set()
    for c in _audit_calls():
        a = c.args[1] if len(c.args) > 1 else None
        if isinstance(a, ast.Constant):
            out.add(a.value)
        elif isinstance(a, ast.BinOp) and isinstance(a.left, ast.Constant):
            out.add(a.left.value + "*")
    return out


# ── گاردهای ایستا ────────────────────────────────────────────────────────────
def test_no_audit_call_passes_a_detail_named_like_a_parameter():
    from app import admin_web as aw

    params = {p for p, v in inspect.signature(aw._audit).parameters.items()
              if v.kind is not inspect.Parameter.VAR_KEYWORD}
    assert {"action", "target", "admin_id", "request"} <= params
    calls = _audit_calls()
    assert len(calls) >= 15, "پیش‌شرط: فراخوانی‌ها کشف نشدند"
    bad = [(c.lineno, k.arg) for c in calls for k in c.keywords if k.arg in params - {"target", "admin_id"}]
    assert not bad, f"جزئیاتی همنامِ پارامترِ `_audit` (TypeError پیش از نوشتن): {bad}"


def test_every_logged_action_has_a_label_and_an_icon():
    from app import admin_web as aw
    from app.panel_i18n import STRINGS

    acts = logged_actions()
    assert {"setting", "login", "cookie_cooldown", "user_*"} <= acts, acts
    expanded = {a for a in acts if not a.endswith("*")} | {"user_block", "user_unblock"}
    missing_label = sorted(a for a in expanded if f"lg.{a}" not in STRINGS)
    missing_icon = sorted(a for a in expanded if a not in aw._LOG_ICON)
    assert not missing_label and not missing_icon, (missing_label, missing_icon)


# ── رفتار ────────────────────────────────────────────────────────────────────
async def _rows(panel, action: str):
    from app.models import AdminAction

    async with panel.maker() as s:
        return (await s.execute(select(AdminAction).where(AdminAction.action == action)
                                .order_by(AdminAction.id))).scalars().all()


async def test_resting_a_cookie_account_works_and_is_logged(seeded):
    """رگرسیونِ ۵۰۰: هر دو جهت (`set`/`clear`) کار می‌کنند و در لاگ می‌نشینند."""
    name = "cookies_healthy.txt"
    for mode in ("set", "clear"):
        r = await seeded.client.post("/cookies/cooldown", data={"name": name, "action": mode},
                                     cookies=seeded.cookies, allow_redirects=False)
        assert r.status == 302, (mode, r.status)
        assert bool(await seeded.redis.exists(f"ckcd:{name}")) is (mode == "set")
    rows = await _rows(seeded, "cookie_cooldown")
    assert [(x.target, x.detail) for x in rows] == [(name, {"mode": "set"}), (name, {"mode": "clear"})]


async def test_the_log_tab_renders_what_was_done(seeded):
    """برچسبِ کار + جزئیاتِ خوانا («۳۰ دقیقه استراحت»، تنظیم: از → به)."""
    from app.admin_web import Fmt

    await seeded.client.post("/cookies/cooldown", data={"name": "cookies_healthy.txt", "action": "set"},
                             cookies=seeded.cookies, allow_redirects=False)
    f = Fmt("fa")
    html = await _fetch(seeded, "/activity?tab=log")
    shows(html, f.t("lg.cookie_cooldown"), f.t("ck.m.rest"), f.t("lg.setting"),
          f.num(2000), f.num(1500), f.t("lg.login"))


async def test_a_secret_setting_is_logged_as_dots_never_as_its_value(panel):
    """`secret` در لاگ فقط «•••» است — حتی برای ادمینِ دیگری که لاگ را می‌خواند."""
    from test_settings_key_coverage import _payload, _settings_html, form_fields

    value = "SPOTIFY-SECRET-7781"
    payload = _payload(form_fields(await _settings_html(panel)))
    r = await panel.client.post("/settings/save", data={**payload, "spotify_client_secret": value},
                                cookies=panel.cookies, allow_redirects=False)
    assert r.status == 302 and "err=" not in r.headers["Location"]
    rows = [x for x in await _rows(panel, "setting") if x.target == "spotify_client_secret"]
    assert rows and rows[-1].detail == {"from": "", "to": "•••"}
    assert value not in await _fetch(panel, "/activity?tab=log")


async def test_proxy_credentials_never_reach_the_log(panel):
    """`user:pass@` در URLِ پروکسی هم راز است؛ میزبان و پورت می‌مانند (برای تشخیص)."""
    from test_settings_key_coverage import _payload, _settings_html, form_fields

    payload = _payload(form_fields(await _settings_html(panel)))
    r = await panel.client.post("/settings/save",
                                data={**payload, "proxy_url": "socks5h://bob:hunter2@exit.example:1080"},
                                cookies=panel.cookies, allow_redirects=False)
    assert r.status == 302 and "err=" not in r.headers["Location"]
    row = [x for x in await _rows(panel, "setting") if x.target == "proxy_url"][-1]
    assert "hunter2" not in str(row.detail) and "bob" not in str(row.detail)
    assert "exit.example:1080" in row.detail["to"]


async def test_an_unchanged_save_writes_no_log_rows(panel):
    """ذخیرهٔ بی‌تغییر نباید لاگ را با ده‌ها ردیفِ «از X به X» پر کند."""
    from test_settings_key_coverage import _payload, _settings_html, form_fields

    payload = _payload(form_fields(await _settings_html(panel)))
    r = await panel.client.post("/settings/save", data=payload, cookies=panel.cookies,
                                allow_redirects=False)
    assert r.status == 302 and "err=" not in r.headers["Location"]
    assert await _rows(panel, "setting") == []
