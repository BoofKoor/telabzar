"""فاز ۲ / موردِ ۹ — پینِ خروجی روی **مستر** هم باید اعمال شود.

`cookies.pick` اکانتِ پین‌شده به خروجیِ دیگر را با شرطِ
`pinned and node_id and pinned != node_id` کنار می‌گذاشت. خروجیِ مستر
`settings.node_id == ""` است، پس نیمهٔ وسط روی مستر همیشه غلط بود و اکانتی که
به نودِ X پین شده **بی‌صدا از IPِ مستر** استفاده می‌شد — دقیقاً همان جابه‌جاییِ
IPِ یک سشن که پین برای جلوگیری از آن ساخته شده (§۷: «سشن یک هویت است»).
"""
from __future__ import annotations

import tempfile

import fakeredis.aioredis as fr
import pytest
import pytest_asyncio

from app import cookies as ck

NETSCAPE = ("# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\tvalue\n")


@pytest_asyncio.fixture
async def r(monkeypatch):
    redis = fr.FakeRedis(decode_responses=True)
    monkeypatch.setattr(ck.settings, "cookies_dir", tempfile.mkdtemp())
    return redis


async def _account(r, name: str, pin: str) -> str:
    assert await ck._save_cookie(r, name, NETSCAPE) == ""
    meta = await ck.get_meta(r, name)
    meta["node_id"] = pin
    await ck.set_meta(r, name, meta)
    return name


async def _seen(r, **kw) -> set:
    return {await ck.pick(r, "instagram", **kw) for _ in range(12)}


async def test_the_master_never_uses_an_account_pinned_to_a_node(r, monkeypatch):
    monkeypatch.setattr(ck.settings, "node_id", "")           # همین پروسه = مستر
    await _account(r, "instagram-node.txt", "nodeA")
    free = await _account(r, "instagram-free.txt", "")
    assert await _seen(r, node_id="") == {free}


async def test_a_master_with_only_node_pinned_accounts_gets_none(r, monkeypatch):
    """اکانتِ پین‌شده جای دیگر «نبودنِ اکانت» است، نه «استفاده از IPِ اشتباه»."""
    monkeypatch.setattr(ck.settings, "node_id", "")
    await _account(r, "instagram-node.txt", "nodeA")
    assert await ck.pick(r, "instagram", node_id="") is None


async def test_an_omitted_exit_means_this_process_not_any(r, monkeypatch):
    """`node_id=None` (نگاهِ پیشاپیشِ «اکانتِ دیگری هست؟») باید با انتخابِ واقعی
    یکی باشد — روی **نود**، اکانتِ پین‌شده به همان نود دیده شود."""
    monkeypatch.setattr(ck.settings, "node_id", "nodeA")
    mine = await _account(r, "instagram-mine.txt", "nodeA")
    await _account(r, "instagram-other.txt", "nodeB")
    assert await _seen(r) == {mine}


async def test_the_omitted_exit_on_the_master_is_the_master(r, monkeypatch):
    monkeypatch.setattr(ck.settings, "node_id", "")
    await _account(r, "instagram-node.txt", "nodeA")
    assert await ck.pick(r, "instagram") is None


async def test_a_node_still_prefers_its_own_and_accepts_unpinned(r, monkeypatch):
    """کنترل: روی نود، اکانتِ همان نود مقدم است و اکانتِ بی‌پین هم مجاز."""
    monkeypatch.setattr(ck.settings, "node_id", "nodeA")
    mine = await _account(r, "instagram-mine.txt", "nodeA")
    free = await _account(r, "instagram-free.txt", "")
    assert await ck.pick(r, "instagram", node_id="nodeA") == mine
    assert await _seen(r, node_id="nodeA", exclude={mine}) == {free}


async def test_unpinned_accounts_still_rotate_on_the_master(r, monkeypatch):
    """کنترل: بدونِ هیچ پینی رفتارِ مستر همان قبلی است."""
    monkeypatch.setattr(ck.settings, "node_id", "")
    a = await _account(r, "instagram-a.txt", "")
    b = await _account(r, "instagram-b.txt", "")
    assert await _seen(r, node_id="") == {a, b}
