"""فاز ۴ / موردِ ۱۵ — اتصال در پنل: رفت‌وبرگشت چیزی منجمد نکند.

منطقِ `review` در `tests/test_langpack_defaults.py` است؛ این‌جا ادعا دربارهٔ
**ردیف‌های واقعیِ** `text_overrides` بعد از POSTِ واقعیِ `/langs/import` است.
"""
from __future__ import annotations

import json

from app import langpack as L
from app import textstore
from app.i18n import DEFAULT, default_text


async def _export(panel, lang, source=DEFAULT, name="x"):
    r = await panel.client.get(
        f"/langs/export?lang={lang}&source={source}&name={name}", cookies=panel.cookies)
    assert r.status == 200
    return json.loads(await r.text())


async def _import(panel, pack, *, lang, **extra):
    data = {"lang": lang, "name": "x", "pack": json.dumps(pack, ensure_ascii=False), **extra}
    r = await panel.client.post("/langs/import", cookies=panel.cookies, data=data)
    await r.text()
    await textstore.load()
    return r


async def test_an_unchanged_round_trip_writes_no_rows(panel):
    """پیش از رفع: ۲۱۴ ردیف، هرکدام برابر با پیش‌فرض."""
    pack = await _export(panel, DEFAULT)
    await _import(panel, pack, lang=DEFAULT, confirm="yes")
    assert textstore.lang_texts(DEFAULT) == {}, \
        f"{len(textstore.lang_texts(DEFAULT))} ردیف پیش‌فرض را منجمد کرد"


async def test_setting_a_key_back_to_default_removes_its_override(panel):
    key = L.TEXT_KEYS[0]
    await textstore.set_text(DEFAULT, key, "OLD EDIT")
    pack = await _export(panel, DEFAULT)
    pack["texts"] = {key: default_text(DEFAULT, key)}
    await _import(panel, pack, lang=DEFAULT, confirm="yes")
    assert key not in textstore.lang_texts(DEFAULT), "override نباید با پیش‌فرض بازنویسی بماند"


async def test_a_real_edit_is_still_stored(panel):
    """کنترل."""
    key = L.TEXT_KEYS[0]
    pack = await _export(panel, DEFAULT)
    pack["texts"] = {key: "EDITED"}
    await _import(panel, pack, lang=DEFAULT, confirm="yes")
    assert textstore.lang_texts(DEFAULT) == {key: "EDITED"}
