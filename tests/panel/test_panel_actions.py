"""کارهای پنل که تا بازطراحیِ ۲۰۲۶-۱۰ **هیچ** تستی نداشتند — هرکدام روی اثرش.

سرشماریِ مسیرهای POST نشان داد این‌ها هرگز صدا زده نشده بودند: افزودن/جایگزینی/حذف/
آزادسازی/هویت/روشن‌خاموش/همگام‌سازیِ کوکی، حذفِ نود، ذخیره و برگرداندنِ متن،
برگرداندنِ چیدمانِ دکمه، و خروج. هر ادعا روی **حالتِ بعد از کار** است (فایل، متا،
آینه، ردیفِ DB، override) نه روی کدِ وضعیت: ۳۰۲ دربارهٔ کار هیچ نمی‌گوید.

و یک ردهٔ خرابیِ واقعی که همین سرشماری پیدا کرد — **اکانتِ شبح**. هندلرهای کوکی
نام را فقط امن می‌کردند و وجودش را نمی‌سنجیدند. `get_meta` برای نامِ ناموجود متای
تازه می‌سازد و `set_meta` آن را می‌نویسد، پس یک فرمِ کهنه (اکانتی که در تبِ دیگر
حذف شده) متای شبح می‌گذاشت و — چون `set_meta` ردِ ماندگارِ `ckseen:<پلتفرم>` را هم
می‌نویسد — سطلی که هرگز پر نشده «زمانی پر بوده» خوانده می‌شد و هشدارِ کاذبِ «کوکی
نمانده» می‌گرفت. جایگزینی بدترش را داشت: برای نامِ ناموجود **فایلِ تازه** می‌ساخت،
یعنی اکانتِ حذف‌شده از راهِ «جایگزینی» بی‌صدا برمی‌گشت.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from test_admin_log import _rows

#: کوکیِ Netscapeِ کوچک ولی معتبر برای اینستاگرام (`sessionid` کوکیِ کلیدی است).
IG_COOKIE = ("# Netscape HTTP Cookie File\n"
             ".instagram.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\tS3SS10N\n")
IG_COOKIE_2 = IG_COOKIE.replace("S3SS10N", "FR3SH")


def _q(resp) -> dict[str, str]:
    """مسیر و پارامترهای ریدایرکت — `ok`/`err` همان چیزی است که بنر نشان می‌دهد."""
    loc = urlsplit(resp.headers["Location"])
    return {"_path": loc.path, **{k: v[0] for k, v in parse_qs(loc.query).items()}}


def _pt(key: str, **kw) -> str:
    from app.panel_i18n import pt
    return pt("fa", key, **kw)


async def _post(panel, path: str, data: dict):
    r = await panel.client.post(path, data=data, cookies=panel.cookies, allow_redirects=False)
    assert r.status == 302, (path, r.status, await r.text())
    return r


def _cdir(panel):
    import pathlib
    return pathlib.Path(panel.aw.settings.cookies_dir)


async def _meta(panel, name: str) -> dict | None:
    raw = await panel.redis.get(f"ckmeta:{name}")
    return json.loads(raw) if raw else None


# ── کوکی: افزودن ─────────────────────────────────────────────────────────────
async def test_adding_an_account_writes_the_file_meta_and_mirror(panel):
    r = await _post(panel, "/cookies/add", {"platform": "instagram", "label": "main",
                                            "content": IG_COOKIE, "proxy": "socks5h://u:p@x:1"})
    assert _q(r).get("ok") == "ck.added.ok", _q(r)
    name = "instagram_main.txt"
    assert (_cdir(panel) / name).read_text(encoding="utf-8") == IG_COOKIE.strip()
    meta = await _meta(panel, name)
    assert (meta["label"], meta["platform"], meta["fail_streak"]) == ("main", "instagram", 0)
    assert meta["proxy"] == "socks5h://u:p@x:1"
    # آینهٔ Redis — نودِ دانلود فقط همین را می‌بیند
    assert await panel.redis.sismember("ckfiles", name)
    assert await panel.redis.get(f"ckfile:{name}") == IG_COOKIE.strip()
    rows = await _rows(panel, "cookie_add")
    assert [(x.target, x.detail) for x in rows] == [("main", {"platform": "instagram"})]


async def test_a_second_account_with_the_same_label_does_not_overwrite_the_first(panel):
    for content in (IG_COOKIE, IG_COOKIE_2):
        await _post(panel, "/cookies/add", {"platform": "instagram", "label": "main",
                                            "content": content})
    files = sorted(p.name for p in _cdir(panel).glob("*.txt"))
    assert len(files) == 2 and files[0] == "instagram_main.txt", files
    assert {(_cdir(panel) / f).read_text(encoding="utf-8") for f in files} \
        == {IG_COOKIE.strip(), IG_COOKIE_2.strip()}


async def test_a_cookie_without_the_key_cookie_is_refused_and_writes_nothing(panel):
    r = await _post(panel, "/cookies/add", {"platform": "instagram", "label": "x",
                                            "content": IG_COOKIE.replace("sessionid", "csrftoken")})
    q = _q(r)
    assert "sessionid" in q.get("err", "") and q.get("dlg") == "ck-add", q
    assert list(_cdir(panel).glob("*.txt")) == []
    assert not await panel.redis.smembers("ckfiles")
    assert await _rows(panel, "cookie_add") == []


# ── کوکی: جایگزینی ───────────────────────────────────────────────────────────
async def test_replacing_a_cookie_keeps_the_account_and_clears_its_failures(seeded):
    name = "cookies_suspect.txt"          # fail_streak=1 در fixture
    r = await _post(seeded, "/cookies/replace", {"name": name, "content": IG_COOKIE})
    assert _q(r).get("ok") == "ck.replaced.ok", _q(r)
    assert (_cdir(seeded) / name).read_text(encoding="utf-8") == IG_COOKIE.strip()
    meta = await _meta(seeded, name)
    assert (meta["label"], meta["fail_streak"], meta["last_error"]) == ("suspect", 0, "")
    assert meta["last_ok"] > 0
    assert await seeded.redis.get(f"ckfile:{name}") == IG_COOKIE.strip()
    assert [x.target for x in await _rows(seeded, "cookie_replace")] == ["suspect"]


async def test_replacing_an_account_that_is_gone_does_not_resurrect_it(seeded):
    """فرمِ کهنه پس از حذف: پیش از گارد، فایل از نو ساخته می‌شد."""
    name = "instagram_deleted.txt"
    r = await _post(seeded, "/cookies/replace", {"name": name, "content": IG_COOKIE})
    assert _q(r).get("err") == _pt("ck.bad_acct"), _q(r)
    assert not (_cdir(seeded) / name).exists()
    assert not await seeded.redis.sismember("ckfiles", name)
    assert await _meta(seeded, name) is None
    assert await _rows(seeded, "cookie_replace") == []


# ── کوکی: حذف ────────────────────────────────────────────────────────────────
async def test_deleting_an_account_removes_file_mirror_and_meta(seeded):
    name = "cookies_invalid.txt"
    await seeded.redis.sadd("ckfiles", name)
    await seeded.redis.set(f"ckfile:{name}", "x")
    r = await _post(seeded, "/cookies/delete", {"name": name})
    assert _q(r).get("ok") == "ck.del.ok"
    assert not (_cdir(seeded) / name).exists()
    assert not await seeded.redis.sismember("ckfiles", name)
    assert not await seeded.redis.exists(f"ckfile:{name}")
    assert await _meta(seeded, name) is None
    # ردِ ماندگارِ «این سطل زمانی پر بود» عمداً می‌ماند (`del_meta`)
    assert await seeded.redis.exists("ckseen:instagram")
    assert [x.target for x in await _rows(seeded, "cookie_delete")] == ["invalid"]


async def test_a_mirror_only_account_can_still_be_deleted(panel):
    """«شناخته‌شده» = فهرستی که صفحه نشان می‌دهد، نه «فایل روی دیسک هست».

    دیسکِ خالی یعنی `list_names` به آینه می‌افتد و صفحه این اکانت را **نشان
    می‌دهد**؛ گاردی که فقط دیسک را بپرسد دکمهٔ حذفِ همین ردیف را بی‌اثر می‌کرد.
    """
    name = "instagram_mirror.txt"
    await panel.redis.sadd("ckfiles", name)
    await panel.redis.set(f"ckfile:{name}", IG_COOKIE)
    html = await (await panel.client.get("/cookies", cookies=panel.cookies)).text()
    assert "instagram_mirror" in html, "پیش‌شرط: صفحه اکانتِ فقط‌آینه را نشان نداد"
    r = await _post(panel, "/cookies/delete", {"name": name})
    assert _q(r).get("ok") == "ck.del.ok", _q(r)
    assert not await panel.redis.sismember("ckfiles", name)


# ── کوکی: آزادسازی، هویت، روشن/خاموش ───────────────────────────────────────
async def test_unfreezing_puts_the_account_back_and_rearms_the_alert(seeded):
    name = "cookies_frozen.txt"
    await seeded.redis.set(f"ckcheck:{name}", "1")
    r = await _post(seeded, "/cookies/unfreeze", {"name": name})
    assert _q(r).get("ok") == "ck.unfrozen"
    meta = await _meta(seeded, name)
    assert (meta["frozen"], meta["fail_streak"]) == (False, 0)
    assert not await seeded.redis.exists(f"ckcheck:{name}")
    assert [x.target for x in await _rows(seeded, "cookie_unfreeze")] == ["frozen"]


async def test_the_identity_form_pins_exit_proxy_and_agent(seeded):
    name = "cookies_healthy.txt"
    r = await _post(seeded, "/cookies/identity", {"name": name, "node_id": "n1",
                                                  "proxy": "http://bob:hunter2@exit.example:3128",
                                                  "user_agent": "UA/1.0"})
    assert _q(r).get("ok") == "ck.saved"
    meta = await _meta(seeded, name)
    assert (meta["node_id"], meta["proxy"], meta["user_agent"]) == \
        ("n1", "http://bob:hunter2@exit.example:3128", "UA/1.0")
    assert meta["label"] == "healthy", "متای موجود باید ادغام شود، نه بازنویسی"
    (row,) = await _rows(seeded, "cookie_identity")
    assert row.detail["exit"] == "n1"
    assert "hunter2" not in str(row.detail) and "exit.example:3128" in row.detail["proxy"]


async def test_toggling_flips_disabled_both_ways(seeded):
    name = "cookies_healthy.txt"
    states = []
    for _ in range(2):
        await _post(seeded, "/cookies/toggle", {"name": name})
        states.append((await _meta(seeded, name))["disabled"])
    assert states == [True, False]
    assert [x.detail for x in await _rows(seeded, "cookie_toggle")] == \
        [{"state": "off"}, {"state": "on"}]


# ── کوکی: نامِ ناشناخته هرگز متای شبح نمی‌سازد ──────────────────────────────
_PER_ACCOUNT = (
    ("/cookies/toggle", {}),
    ("/cookies/identity", {"node_id": "n1", "proxy": "", "user_agent": ""}),
    ("/cookies/unfreeze", {}),
    ("/cookies/cooldown", {"action": "set"}),
    ("/cookies/delete", {}),
    ("/cookies/replace", {"content": IG_COOKIE}),
)


@pytest.mark.parametrize("path,extra", _PER_ACCOUNT, ids=[p.rsplit("/", 1)[1] for p, _ in _PER_ACCOUNT])
async def test_an_unknown_account_leaves_no_trace(panel, path, extra):
    """روی پنلِ **بی‌اکانت**: هیچ متا، هیچ `ckseen`، هیچ فایل، هیچ ردیفِ لاگ.

    `ckseen:instagram` همان چیزی است که `_alert_if_low` را از «هرگز پر نشده (سکوت)»
    به «زمانی پر بوده (هشدار)» می‌برد — پس متای شبح یعنی زنگِ خطرِ کاذب.
    """
    name = "instagram_ghost.txt"
    r = await _post(panel, path, {"name": name, **extra})
    assert _q(r).get("err") == _pt("ck.bad_acct"), _q(r)
    assert await _meta(panel, name) is None
    assert not await panel.redis.exists("ckseen:instagram")
    assert not await panel.redis.exists(f"ckcd:{name}")
    assert list(_cdir(panel).glob("*")) == []
    async with panel.maker() as s:
        from sqlalchemy import func, select

        from app.models import AdminAction
        assert (await s.execute(select(func.count()).select_from(AdminAction))).scalar() == 0


async def test_a_traversal_name_is_neutralised_before_the_lookup(seeded):
    """`../` به basename تبدیل می‌شود و بعد وجودش سنجیده می‌شود — نه برعکس."""
    r = await _post(seeded, "/cookies/toggle", {"name": "../cookies/cookies_healthy.txt"})
    assert _q(r).get("ok") == "ck.saved", _q(r)
    assert (await _meta(seeded, "cookies_healthy.txt"))["disabled"] is True
    assert not await seeded.redis.exists("ckmeta:../cookies/cookies_healthy.txt")


async def test_an_unknown_rest_action_changes_nothing(seeded):
    name = "cookies_healthy.txt"
    r = await _post(seeded, "/cookies/cooldown", {"name": name, "action": "forever"})
    assert _q(r) == {"_path": "/cookies"}
    assert not await seeded.redis.exists(f"ckcd:{name}")
    assert await _rows(seeded, "cookie_cooldown") == []


# ── کوکی: همگام‌سازیِ آینه ─────────────────────────────────────────────────────
async def test_resync_mirrors_the_disk_and_drops_stale_entries(seeded):
    await seeded.redis.sadd("ckfiles", "cookies_removed_long_ago.txt")
    await seeded.redis.set("ckfile:cookies_removed_long_ago.txt", "old")
    r = await _post(seeded, "/cookies/resync", {})
    assert _q(r).get("ok") == "ck.synced"
    disk = {p.name for p in _cdir(seeded).glob("*.txt")}
    assert len(disk) == 7
    assert set(await seeded.redis.smembers("ckfiles")) == disk
    assert not await seeded.redis.exists("ckfile:cookies_removed_long_ago.txt")
    assert await seeded.redis.get("ckfile:cookies_healthy.txt") == "# Netscape HTTP Cookie File\n"
    assert len(await _rows(seeded, "cookie_resync")) == 1


# ── نودها ────────────────────────────────────────────────────────────────────
async def test_removing_a_node_drops_its_row_peer_and_heartbeat(seeded, tmp_path, monkeypatch):
    from app import nodes as node_mod
    from app.models import Node

    conf = tmp_path / "wg0.conf"
    conf.write_text("[Interface]\nPrivateKey = k\n\n"
                    "[Peer]\nPublicKey = pubkey=\nAllowedIPs = 10.51.0.2/32\n\n"
                    "[Peer]\nPublicKey = other=\nAllowedIPs = 10.51.0.3/32\n", encoding="utf-8")
    monkeypatch.setattr(node_mod.settings, "wg_config_path", str(conf))
    synced = []
    monkeypatch.setattr(node_mod, "_syncconf", lambda: synced.append(True))
    await seeded.redis.set("node:n1", json.dumps({"role": "download"}), ex=45)
    await seeded.redis.set("nodeseen:n1", "1700000000")

    r = await _post(seeded, "/nodes/remove", {"id": "n1"})
    assert _q(r).get("ok") == "nd.rm.ok", _q(r)
    async with seeded.maker() as s:
        assert await s.get(Node, "n1") is None
    text = conf.read_text(encoding="utf-8")
    assert "PublicKey = pubkey=" not in text and "PublicKey = other=" in text and synced
    assert not await seeded.redis.exists("node:n1", "nodeseen:n1")
    assert [(x.target, x.detail) for x in await _rows(seeded, "node_remove")] == \
        [("edge", {"role": "download"})]


async def test_removing_a_node_that_is_gone_says_so(seeded):
    r = await _post(seeded, "/nodes/remove", {"id": "no-such-node"})
    assert _q(r).get("err") == _pt("nd.rm.none"), _q(r)
    assert await _rows(seeded, "node_remove") == []


# ── متن‌ها ───────────────────────────────────────────────────────────────────
def _plain_key() -> str:
    """کلیدی که پیش‌فرضش نه placeholder دارد نه HTML — کشف‌شده، نه هاردکد."""
    from app import langpack
    from app.i18n import default_text

    return next(k for k in sorted(langpack.TEXT_KEYS)
                if not any(c in default_text("fa", k) for c in "{<\n"))


async def test_saving_a_text_stores_the_override_and_logs_it(panel):
    from app import textstore

    key = _plain_key()
    r = await _post(panel, "/texts/save", {"lang": "fa", f"v:{key}": "متنِ تازهٔ ادمین"})
    assert _q(r).get("ok") == "tx.saved.ok", _q(r)
    assert textstore.get_override("fa", key) == "متنِ تازهٔ ادمین"
    (row,) = await _rows(panel, "text_save")
    assert (row.target, row.detail) == (key, {"lang": "fa", "n": 1})


async def test_saving_the_default_text_removes_the_override(panel):
    from app import textstore
    from app.i18n import default_text

    key = _plain_key()
    await textstore.set_text("fa", key, "موقت")
    await _post(panel, "/texts/save", {"lang": "fa", f"v:{key}": default_text("fa", key)})
    assert textstore.get_override("fa", key) is None


async def test_an_invalid_text_is_refused_and_nothing_is_written(panel):
    from app import textstore

    key = _plain_key()
    r = await _post(panel, "/texts/save", {"lang": "fa", f"v:{key}": "با {placeholder_نامعتبر}"})
    assert key in _q(r).get("err", ""), _q(r)
    assert textstore.get_override("fa", key) is None
    assert await _rows(panel, "text_save") == []


async def test_resetting_a_text_brings_back_the_default(panel):
    from app import textstore

    key = _plain_key()
    await textstore.set_text("fa", key, "موقت")
    r = await _post(panel, "/texts/reset", {"lang": "fa", "reset": key})
    assert _q(r).get("ok") == "tx.reset.ok"
    assert textstore.get_override("fa", key) is None
    assert [(x.target, x.detail) for x in await _rows(panel, "text_reset")] == [(key, {"lang": "fa"})]


@pytest.mark.parametrize("form,err_key", [
    ({"lang": "xx", "reset": "start"}, "tx.err.lang"),
    ({"lang": "fa", "reset": "no_such_key_at_all"}, "tx.err.key"),
], ids=["unknown-lang", "unknown-key"])
async def test_a_reset_that_cannot_happen_is_not_reported_as_done(panel, form, err_key):
    r = await _post(panel, "/texts/reset", form)
    q = _q(r)
    assert "ok" not in q, q
    want = _pt(err_key, l=form["lang"]) if err_key == "tx.err.lang" else _pt(err_key, k=form["reset"])
    assert q.get("err") == want, q


# ── دکمه‌ها ──────────────────────────────────────────────────────────────────
async def test_resetting_a_menu_removes_its_saved_layout(panel):
    from app import textstore

    await textstore.set_menu_layout("video", [{"op": "compress", "hidden": True, "width": "full"}])
    assert textstore.get_menu_layout("video"), "پیش‌شرط: چیدمان ذخیره نشد"
    r = await _post(panel, "/buttons/reset", {"kind": "video", "lang": "fa"})
    assert _q(r).get("ok") == "bt.reset.ok"
    assert textstore.get_menu_layout("video") is None
    assert [x.target for x in await _rows(panel, "buttons_reset")] == ["video"]


async def test_resetting_an_unknown_menu_does_nothing(panel):
    from app import textstore

    await textstore.set_menu_layout("video", [{"op": "compress", "hidden": True, "width": "full"}])
    r = await _post(panel, "/buttons/reset", {"kind": "spaceship"})
    assert _q(r) == {"_path": "/buttons"}
    assert textstore.get_menu_layout("video")
    assert await _rows(panel, "buttons_reset") == []


# ── خروج ─────────────────────────────────────────────────────────────────────
async def test_signing_out_clears_the_session_cookie(panel):
    r = await _post(panel, "/logout", {})
    assert _q(r) == {"_path": "/login"}
    morsel = r.cookies.get(panel.aw._COOKIE)
    assert morsel is not None and morsel.value == "" and morsel["max-age"] == "0", r.headers


async def test_a_plain_link_cannot_sign_the_admin_out(panel):
    """`<img src=…/logout>` در هر سایتی کافی بود؛ حالا GET خروج نیست."""
    r = await panel.client.get("/logout", cookies=panel.cookies, allow_redirects=False)
    assert r.status == 405
    assert panel.aw._COOKIE not in r.cookies


async def test_a_cross_site_post_cannot_sign_the_admin_out(panel):
    r = await panel.client.post("/logout", cookies=panel.cookies, allow_redirects=False,
                                headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status == 403
    assert panel.aw._COOKIE not in r.cookies
