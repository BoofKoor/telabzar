"""‏`/api/console/<page>` — دادهٔ اختصاصیِ نُه صفحهٔ دیگر.

همان دو قاعدهٔ `test_console_api.py`: روی **HTTPِ واقعی**، و با ردیف‌های
**کاشته‌شده** نه DBِ خالی — چون «صفر» با «نرسید» تفکیک‌ناپذیر است.

و یک ادعای مشترکِ مهم: هر سازنده باید محاسبه را از همان توابعی **قرض
بگیرد** که صفحاتِ Jinja می‌خوانند. اگر کنسول فهرستِ خودش را بسازد، کلیدِ
تازه در یکی ظاهر می‌شود و در دیگری نه — همان یک‌طرفه‌بودنی که شش کلیدِ
تنظیمات را ماه‌ها نامرئی نگه داشت.
"""
from __future__ import annotations

import pytest

PAGES = ("traffic", "health", "nodes", "users", "cookies",
         "settings", "strings", "keyboard", "langs")


async def _get(panel, path: str, *, auth: bool = True):
    ck = {panel.aw._COOKIE: panel.aw._make_session(panel.admin_id)} if auth else {}
    return await panel.client.get(path, cookies=ck)


@pytest.mark.parametrize("page", PAGES)
async def test_every_page_answers_json(seeded, page):
    r = await _get(seeded, f"/api/console/{page}")
    assert r.status == 200, await r.text()
    assert r.content_type == "application/json"
    assert await r.json()


@pytest.mark.parametrize("page", PAGES)
async def test_every_page_needs_a_session(panel, page):
    """۴۰۱ JSON، نه ریدایرکت — همان دلیلِ `/api/console`."""
    r = await _get(panel, f"/api/console/{page}", auth=False)
    assert r.status == 401


async def test_an_unknown_page_is_404_not_a_crash(seeded):
    """نگاشت **صریح** است نه `getattr` روی نامِ صفحه، وگرنه یک مسیرِ کاربر
    می‌تواند هر تابعی را در ماژول صدا بزند."""
    r = await _get(seeded, "/api/console/_page_health")
    assert r.status == 404


async def test_users_reports_the_seeded_rows(seeded):
    body = await (await _get(seeded, "/api/console/users")).json()
    assert body["total"] == 2
    assert body["blocked"] == 1
    tgs = {r["tg"] for r in body["rows"]}
    assert tgs == {"901", "902"}
    assert [r["blocked"] for r in body["rows"] if r["tg"] == "901"] == [True]


async def test_users_search_reaches_the_server(seeded):
    """فیلترِ کلاینتی فقط صفحهٔ جاری را می‌گردد، پس جست‌وجو باید سمتِ سرور
    باشد — وگرنه کاربری که در صفحهٔ دوم است «پیدا نشد» می‌گیرد."""
    body = await (await _get(seeded, "/api/console/users?q=901")).json()
    assert [r["tg"] for r in body["rows"]] == ["901"]


async def test_cookies_groups_every_seeded_account(seeded):
    body = await (await _get(seeded, "/api/console/cookies")).json()
    files = {a["file"] for g in body["groups"] for a in g["accounts"]}
    assert len(files) == 7, files
    # فریز و باطل باید در صفِ رسیدگی باشند و بقیه نه.
    assert len(body["attention"]) == 2, body["attention"]


async def test_cookies_separates_never_stocked_from_burned(seeded):
    """سطلی که هرگز پر نشده «سوخته» نیست — §۷.

    فرمِ افزودن باید **همهٔ** سطل‌های ممکن را بدهد، نه فقط پرشده‌ها، وگرنه
    اولین اکانتِ یک سطلِ خالی از پنل اضافه‌شدنی نیست.
    """
    body = await (await _get(seeded, "/api/console/cookies")).json()
    assert "instagram" not in body["unstocked"]      # کاشته شده
    assert "youtube" in body["unstocked"]            # هرگز پر نشده
    assert set(body["unstocked"]) <= set(body["platforms"])
    assert len(body["platforms"]) > len(body["groups"])


async def test_nodes_reports_the_seeded_node_as_down(seeded):
    body = await (await _get(seeded, "/api/console/nodes")).json()
    assert [n["name"] for n in body["rows"]] == ["edge"]
    assert body["rows"][0]["up"] is False
    assert body["roles"], "نقش‌ها باید از nodes.ROLES بیایند، نه فهرستِ دستی"


async def test_health_carries_the_pool_summary_and_hosts(seeded):
    body = await (await _get(seeded, "/api/console/health")).json()
    assert body["health"]["redis"] is True
    assert any(p["platform"] == "instagram" for p in body["pool"])
    assert any(h["name"] == "soundcloud" for h in body["hosts"])


async def test_health_reports_a_stuck_job(seeded, panel):
    """جابی که از هر `job_timeout`ی پیرتر است و هنوز تمام نشده.

    تا امروز فقط در «در صف» جمع می‌شد و از یک صفِ واقعی تفکیک‌ناپذیر بود —
    یعنی «همیشه یکی هست» که همان «هیچ‌وقت نگاهش نکن» است.
    """
    from datetime import datetime, timedelta, timezone

    from app.models import File, Job

    async with panel.maker() as s:
        f = (await s.execute(__import__("sqlalchemy").select(File).limit(1))).scalars().first()
        old = datetime.now(timezone.utc) - timedelta(seconds=panel.aw._STUCK_AFTER.total_seconds() + 60)
        s.add(Job(file_id=f.id, op="compress", status="running", created_at=old))
        await s.commit()

    body = await (await _get(seeded, "/api/console/health")).json()
    assert len(body["stuck"]) == 1, body["stuck"]
    assert body["stuck"][0]["status"] == "running"


async def test_a_fresh_job_is_not_reported_as_stuck(seeded):
    """کنترلِ معکوس: fixture سه جابِ **تازه** دارد و هیچ‌کدام نباید گیرکرده
    خوانده شوند، وگرنه کارت هر صفِ سالمی را هم قرمز می‌کند."""
    body = await (await _get(seeded, "/api/console/health")).json()
    assert body["stuck"] == []


async def test_settings_groups_come_from_the_panel_not_a_second_list(seeded):
    """کلیدها باید **همان** مجموعهٔ `RUNTIME_KEYS` باشند.

    اگر کنسول فهرستِ خودش را می‌ساخت، کلیدِ تازه در یکی ظاهر می‌شد و در
    دیگری نه — همان یک‌طرفه‌بودنی که شش کلید را ماه‌ها نامرئی نگه داشت.
    """
    from app.settings_store import RUNTIME_KEYS

    body = await (await _get(seeded, "/api/console/settings")).json()
    keys = {r["key"] for g in body["groups"] for r in g["rows"]}
    assert keys == set(RUNTIME_KEYS), sorted(set(RUNTIME_KEYS) - keys)
    assert body["total"] == len(RUNTIME_KEYS)


async def test_strings_marks_an_override(seeded, panel):
    from app import textstore

    await textstore.set_text("fa", "btn_compress", "فشرده‌سازیِ من")
    body = await (await _get(seeded, "/api/console/strings?lang=fa")).json()
    rows = {r["key"]: r for g in body["groups"] for r in g["rows"]}
    assert rows["btn_compress"]["overridden"] is True
    assert rows["btn_compress"]["val"] == "فشرده‌سازیِ من"
    assert body["edited"] >= 1


async def test_strings_search_narrows_the_groups(seeded):
    body = await (await _get(seeded, "/api/console/strings?lang=fa&q=btn_compress")).json()
    keys = {r["key"] for g in body["groups"] for r in g["rows"]}
    assert keys == {"btn_compress"}, keys


async def test_the_keyboard_layout_uses_the_bot_s_own_resolver(seeded):
    """چیدمان و بسته‌بندی باید از `keyboards` بیاید، نه بازنویسی.

    CLAUDE.md ثبت کرده که این قرارداد از قبل **هشت** کپیِ دست‌نویس بینِ JS و
    پایتون دارد و هیچ تستی دو طرف را گره نمی‌زند. این تست دستِ‌کم سمتِ سرور
    را به منبعِ واقعی گره می‌زند.
    """
    from app.keyboards import _WIDTH_CAP, _resolved_menu, _rows_from_widths

    body = await (await _get(seeded, "/api/console/keyboard?kind=video")).json()
    expected = _resolved_menu("video")
    assert [i["op"] for i in body["items"]] == [op for op, _k, _w in expected]
    assert body["rows"] == _rows_from_widths([w for _o, _k, w in expected])
    assert body["widthCap"] == _WIDTH_CAP


async def test_an_unknown_kind_falls_back_instead_of_500(seeded):
    body = await (await _get(seeded, "/api/console/keyboard?kind=nonsense")).json()
    assert body["kind"] == "video"


async def test_langs_reports_coverage_against_the_pack_keys(seeded):
    """پوشش روی **همان** `TEXT_KEYS`ی است که export می‌کند، نه یک شمارشِ دوم."""
    from app import langpack

    body = await (await _get(seeded, "/api/console/langs")).json()
    assert body["total"] == len(langpack.TEXT_KEYS)
    codes = {r["code"] for r in body["rows"]}
    assert {"fa", "en"} <= codes
    builtin = [r for r in body["rows"] if r["code"] == "fa"][0]
    assert builtin["builtin"] is True
    # زبانِ داخلی کاتالوگِ کد دارد، پس پوششش کامل است.
    assert builtin["keys"] == body["total"]


async def test_langs_counts_users_per_language(seeded):
    """fixture دو کاربر دارد: یکی fa و یکی en."""
    body = await (await _get(seeded, "/api/console/langs")).json()
    by = {r["code"]: r["users"] for r in body["rows"]}
    assert by["fa"] == 1
    assert by["en"] == 1


async def test_traffic_mirrors_the_stats_page(seeded):
    """همان اعدادِ `/stats`، بدونِ محاسبهٔ دوم."""
    body = await (await _get(seeded, "/api/console/traffic?range=7D")).json()
    assert body["files"] == 5
    assert body["dl_files"] == 4
    assert any(b["key"] == "soundcloud" for b in body["by_platform"])
    # `op_perf` از جدولِ `jobs` می‌آید و دانلودها را نمی‌بیند — پس با ۴ فایلِ
    # دانلودی، مجموعش همچنان از سمتِ آپلود می‌آید.
    #
    # و **جابِ در صف شمرده نمی‌شود**: `n` برابرِ `done + failed` است، پس از
    # سه جابِ کاشته‌شده فقط دو تای تمام‌شده این‌جا دیده می‌شوند. نسخهٔ اولِ
    # همین تست ۳ می‌خواست و افتاد — کد درست بود و انتظار غلط. کارت دربارهٔ
    # کارِ **انجام‌شده** است، و ریختنِ صف در آن نرخِ موفقیت را رقیق می‌کند.
    perf = {o["op"]: o["n"] for o in body["op_perf"]}
    assert sum(perf.values()) == 2, perf
    assert body["queued"] == 1
