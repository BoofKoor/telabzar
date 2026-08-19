"""`/nodes` — **کلِ** فهرستِ نودها می‌توانست ناپدید شود و سوییت سبز بماند.

اندازه‌گیری روی `f00d37e`: سه نگهبانِ محتوا داشت و هر سه دربارهٔ جریانِ
**افزودن** بودند (توکنِ یک‌بارمصرف، نقشِ نامعتبر) — نه دربارهٔ اینکه صفحه نودهای
موجود را نشان بدهد. سابوتاژِ `{% for n in nodes %}` → `{% for n in [] %}` هیچ
تستی را نینداخت.

`nodes_page` تنها جایی است که ادمین می‌بیند یک نود آنلاین است یا نه؛ و §۷ ثبت
کرده که «نودِ آفلاین» و «نودِ زنده ولی گیرکرده» از بیرون یکی به‌نظر می‌رسند —
پس ردیفی که بی‌صدا نرندر شود مستقیماً روی تشخیص اثر می‌گذارد.
"""
from __future__ import annotations

from pagefacts import shows
from test_panel_css_classes import _fetch


async def test_a_registered_node_is_listed_with_its_identifying_facts(seeded):
    """نام، IPِ WireGuard و نقش — هر سه، چون هرکدام به‌تنهایی مبهم است."""
    from app import nodes as node_mod

    html = await _fetch(seeded, "/nodes")
    role = node_mod.ROLES["download"]
    shows(html, "edge", "10.51.0.2", "download", role["label"])


async def test_the_header_counts_the_nodes(seeded):
    """شمارِ کل و شمارِ آنلاین — دو عددِ متفاوت که نباید یکی شوند."""
    shows(await _fetch(seeded, "/nodes"), "1 نود", "0 آنلاین")


async def test_a_node_with_no_heartbeat_is_shown_as_offline(seeded):
    """نودِ کاشته‌شده heartbeat ندارد، پس باید «آفلاین» بگوید.

    اگر این برچسب بیفتد، ادمین یک نودِ مرده را زنده می‌بیند — بدترین حالت،
    چون تصمیمِ «چرا کار نمی‌کند» را از همان اول غلط می‌کند.
    """
    shows(await _fetch(seeded, "/nodes"), "آفلاین")


async def test_an_empty_registry_says_so(panel):
    """کنترلِ معکوس: بدونِ نود، صفحه باید توضیح بدهد نه اینکه خالی بماند."""
    shows(await _fetch(panel, "/nodes"), "هنوز نودی وصل نشده")
