"""‏`/api/console` باید دادهٔ **واقعی** بدهد، و نبودِ داده را نام ببرد.

**چرا این تست‌ها روی HTTPِ واقعی‌اند نه روی صداکردنِ تابع:** ادعای اصلیِ این
اندپوینت دربارهٔ **اتصال** است — گیتِ نشست، کدِ وضعیت، و اینکه عددها از همان
`_stats`/`_health`ی می‌آیند که صفحاتِ Jinja می‌خوانند. صداکردنِ مستقیمِ
`console_api` تابعِ کمکی را می‌سنجد و اتصال را نه؛ همان شکافی که §۶ برای
`test_probe_cookie_blame` ثبت کرده.

**و ادعای «واقعی» فقط وقتی معنا دارد که فیکسچر داده داشته باشد.** روی DBِ
خالی هر عددی صفر است و «صفر» با «از فیکسچرِ نمایشی نیامده» تفکیک‌ناپذیر
می‌شود — یعنی تستِ توخالی. پس همه‌جا `seeded` استفاده می‌شود و عددها با
ردیف‌های **کاشته‌شده** مقایسه می‌شوند.
"""
from __future__ import annotations

import json


async def _get(panel, path: str, *, auth: bool = True):
    ck = {panel.aw._COOKIE: panel.aw._make_session(panel.admin_id)} if auth else {}
    return await panel.client.get(path, cookies=ck)


async def test_an_unauthenticated_call_gets_401_json_not_a_redirect(panel):
    """ریدایرکت به `/login` بدنهٔ HTML با ۲۰۰ می‌دهد و `JSON.parse` را با
    پیامی می‌شکند که هیچ ربطی به «نشستت تمام شده» ندارد."""
    r = await _get(panel, "/api/console", auth=False)
    assert r.status == 401
    assert (await r.json())["error"] == "unauthorized"


async def test_the_payload_is_json(seeded):
    r = await _get(seeded, "/api/console")
    assert r.status == 200
    assert r.content_type == "application/json"


async def test_the_file_count_is_the_seeded_one(seeded):
    """کنترلِ ضدِتوخالی برای کلِ فایل: پنج فایل کاشته شده (۴ لینک + ۱ آپلود)."""
    body = await (await _get(seeded, "/api/console")).json()
    assert body["kpis"]["files"]["value"] == 5
    assert "4 via link" in body["kpis"]["files"]["foot"]


async def test_the_platform_row_carries_the_raw_key_not_only_the_persian_label(seeded):
    """کنسول LTR و مونو است: رنگِ پلتفرم روی نامِ **انگلیسی** کلید می‌خورد و
    برچسبِ فارسی باید از `<Fa>` رد شود. اگر فقط برچسب برسد، کلاینت مجبور است
    برچسب‌زدایی کند — همان دو کپیِ دست‌نویس که واگرا می‌شود."""
    body = await (await _get(seeded, "/api/console")).json()
    plats = {p["key"]: p for p in body["platforms"]}
    assert "soundcloud" in plats, body["platforms"]
    assert plats["soundcloud"]["n"] == 4
    # برچسب هست، ولی جایگزینِ کلید نشده.
    assert plats["soundcloud"]["label"]


async def test_the_queue_depths_come_from_the_real_arq_keys(seeded):
    """عمقِ صف باید همان `zcard`ی باشد که `_health` می‌خواند، نه عددِ حلقه.

    ادعا روی **تفاضل** است نه مقدارِ مطلق، و این عمدی است: fixture خودش
    صف‌ها را پر می‌کارد، پس یک عددِ هاردکد هم به دادهٔ fixture گره می‌خورد و
    هم با تغییرش بی‌صدا بی‌معنا می‌شود. تفاضل مستقل از پایه است و دقیقاً همان
    چیزی را می‌گوید که مهم است: عدد از این کلید می‌آید.
    """
    before = (await (await _get(seeded, "/api/console")).json())["queues"]
    await seeded.redis.zadd("arq:queue", {"probe-a": 1, "probe-b": 2})
    await seeded.redis.zadd("arq:queue:proc", {"probe-c": 1})
    await seeded.redis.zadd("arq:queue:dl:master", {"probe-d": 1})
    after = (await (await _get(seeded, "/api/console")).json())["queues"]
    assert after["main"] - before["main"] == 2
    assert after["proc"] - before["proc"] == 1
    # صفِ دانلود = صفِ نود + صفِ مسترِ fallback، پس یک عضو در مستر یعنی +۱.
    assert after["dl"] - before["dl"] == 1


async def test_every_seeded_cookie_account_appears_with_a_flag(seeded):
    """هفت وضعیت کاشته شده؛ هیچ‌کدام نباید بی‌پرچم برسد."""
    body = await (await _get(seeded, "/api/console")).json()
    assert len(body["cookies"]) == 7, body["cookies"]
    assert all(c["flag"].startswith("[") for c in body["cookies"])
    # پرچمِ ناشناس («[ ?? ]») یعنی نگاشت از وضعیتِ واقعی عقب افتاده.
    assert not [c for c in body["cookies"] if c["flag"] == "[ ?? ]"], body["cookies"]


async def test_a_node_with_no_heartbeat_is_reported_down(seeded):
    """نودِ کاشته‌شده heartbeat ندارد، پس باید `DOWN` باشد — نه اینکه چون
    ردیفِ DB دارد «بالا» فرض شود."""
    body = await (await _get(seeded, "/api/console")).json()
    assert [n["name"] for n in body["nodes"]] == ["edge"]
    assert body["nodes"][0]["up"] is False
    assert body["nodes"][0]["flag"] == "[DOWN]"


async def test_the_seeded_job_error_reaches_the_console(seeded):
    """یک جابِ شکست‌خورده با متنِ مشخص کاشته شده."""
    body = await (await _get(seeded, "/api/console")).json()
    assert any("ffmpeg exploded" in e["msg"] for e in body["errors"]), body["errors"]


async def test_the_gaps_are_named_in_the_payload_not_left_to_the_client(seeded):
    """پنلی که منبع ندارد باید **علتش** را از سرور بگیرد.

    این ادعای کلیدیِ کلِ اتصال است: بدونِ آن، کلاینت یا عددِ ساختگی نشان
    می‌دهد (§۷: «fallbackی که بی‌صدا تنزل کند از خطا بدتر است») یا علت را
    دستی می‌نویسد و کپیِ دومی می‌سازد که با سرور واگرا می‌شود.
    """
    body = await (await _get(seeded, "/api/console")).json()
    assert "audit" in body["gaps"]
    assert "job_progress" in body["gaps"]
    assert "host_cpu" in body["gaps"]
    assert all(v.strip() for v in body["gaps"].values())


async def test_cpu_and_memory_are_not_reported_as_resources(seeded):
    """کنترلِ معکوس: تنها منبعِ واقعیِ منابع، دیسک است.

    `psutil` در هیچ فایلِ requirements نیست، پس هر عددِ cpu/mem/net ساختگی
    است — و سه نوارِ ساختگی کنارِ یک نوارِ واقعی از بیرون تفکیک‌ناپذیرند.
    """
    body = await (await _get(seeded, "/api/console")).json()
    labels = {r["label"] for r in body["resources"]}
    assert not (labels & {"cpu", "mem", "net eth0"}), labels


async def test_the_range_reaches_the_stats_layer(seeded):
    """سه دکمهٔ کنسول به چهار کلیدِ `_stats` نگاشت می‌شوند، پس «TODAY» باید
    واقعاً `24h` بشود نه اینکه بی‌صدا به پیش‌فرض بیفتد."""
    for rng in ("TODAY", "7D", "30D"):
        body = await (await _get(seeded, f"/api/console?range={rng}")).json()
        assert body["range"] == rng
    # بازهٔ نامعتبر باید امن بیفتد، نه ۵۰۰ بدهد.
    r = await _get(seeded, "/api/console?range=NONSENSE")
    assert r.status == 200


async def test_the_trend_has_one_row_per_day_of_the_range(seeded):
    body = await (await _get(seeded, "/api/console?range=7D")).json()
    assert len(body["trend"]) == 7
    assert all({"day", "f", "o", "u"} <= set(r) for r in body["trend"])


async def test_the_recent_jobs_are_the_seeded_ones(seeded):
    """جریانِ جاب باید از جدولِ `jobs` بیاید — سه جابِ کاشته‌شده."""
    body = await (await _get(seeded, "/api/console")).json()
    ops = {j["op"] for j in body["jobs"]}
    assert {"compress", "convert", "trim"} <= ops, body["jobs"]
    statuses = {j["op"]: j["status"] for j in body["jobs"]}
    assert statuses["convert"] == "failed"
    assert statuses["trim"] == "queued"


async def test_an_empty_system_reports_zero_not_a_placeholder(panel):
    """کنترلِ معکوس، و **باگی که با رندر پیدا شد نه با خواندن**.

    روی سیستمِ خالی باید عددها صفر باشند. نسخهٔ اولِ لایهٔ کلاینت شرطش را
    روی *طولِ* آرایه گذاشته بود، پس آرایهٔ خالی «داده نداریم» خوانده نمی‌شد
    بلکه به دادهٔ نمایشی سقوط می‌کرد — و کنارِ «۰ فایل» یک رادارِ پر با
    «YOUTUBE ۱۸٬۴۲۰» می‌نشست. سمتِ سرور همان تفکیک باید صریح بماند: خالی
    یعنی خالی، نه غایب.
    """
    body = await (await _get(panel, "/api/console")).json()
    assert body["kpis"]["files"]["value"] == 0
    assert body["kpis"]["users"]["value"] == 0
    # «نمی‌دانیم» با «صفر درصد» یکی نیست: بدونِ هیچ جابی نرخ باید `null` باشد.
    assert body["kpis"]["success"]["value"] is None
    assert body["platforms"] == []
    assert body["jobs"] == []
    assert body["cookies"] == []
    assert body["nodes"] == []


async def test_the_activity_map_is_seven_by_twenty_four_and_counts_real_files(seeded):
    """نقشهٔ فعالیت شمارشِ **واقعیِ** فایل است، نه یک الگوی مصنوعی.

    پنج فایلِ امروزی کاشته شده، پس مجموعِ کلِ ماتریس باید دقیقاً پنج باشد —
    که هم شکل را می‌سنجد هم اینکه چیزی از قلم نیفتاده.
    """
    body = await (await _get(seeded, "/api/console")).json()
    heat = body["heat"]
    assert len(heat) == 7
    assert all(len(row) == 24 for row in heat)
    assert sum(sum(row) for row in heat) == 5, heat
    # آخرین ردیف امروز است؛ همهٔ فایل‌های fixture مالِ امروزند.
    assert sum(heat[-1]) == 5


async def test_the_payload_is_serialisable_as_written(seeded):
    """گاردِ ارزان در برابرِ نشتِ یک شیء غیرِJSON (مثلِ `datetime`) از لایه‌های
    زیرین: پاسخ باید بدونِ کدِ سفارشی دوباره پارس شود."""
    raw = await (await _get(seeded, "/api/console")).text()
    json.loads(raw)
