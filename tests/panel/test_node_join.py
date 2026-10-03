"""رگرسیونِ پنلی: `/node/join` کلیدِ عمومیِ بدشکل را رد می‌کند.

مکملِ `tests/test_wg_pubkey.py` (که تابعِ خالص را می‌سنجد): این‌جا از هندلرِ
واقعیِ aiohttp عبور می‌کنیم تا ثابت شود سیمِ `node_join` هم کلیدِ تزریقی را
پیش از نشستن در جدولِ `Node` رد می‌کند — بدونِ ردیفِ Node، `render_peers` چیزی
برای نوشتن در `wg0.conf` ندارد.
"""
from __future__ import annotations

import base64
import os

import pytest
from sqlalchemy import func, select

from app import nodes
from app.models import Node


async def _mint(panel, role="download"):
    return await nodes.make_join_token(panel.redis, role)


async def _node_count(panel) -> int:
    async with panel.maker() as s:
        return (await s.execute(select(func.count()).select_from(Node))).scalar_one()


@pytest.mark.parametrize("pubkey", [
    "",
    "tooshort=",
    base64.b64encode(os.urandom(32)).decode() + "\n[Interface]\nPostUp = id",
    base64.b64encode(os.urandom(32)).decode()[:-1] + "\nAllowedIPs = 0.0.0.0/0",
])
async def test_join_rejects_bad_pubkey(panel, pubkey):
    token = await _mint(panel)
    resp = await panel.client.post("/node/join", json={"token": token, "pubkey": pubkey})
    assert resp.status == 400
    assert await _node_count(panel) == 0        # هیچ ردیفی ساخته نشد


async def test_join_accepts_a_real_key(panel):
    token = await _mint(panel)
    good = base64.b64encode(os.urandom(32)).decode()
    resp = await panel.client.post("/node/join", json={"token": token, "pubkey": good})
    assert resp.status == 200
    assert await _node_count(panel) == 1
