"""نودِ لینک/استریم (فاز N3) — پروکسیِ معکوسِ عمومی به gatewayِ مستر.

نودِ gateway یک ماشینِ راه‌دور با **IPِ تمیز** است که `/dl/{token}` و `/s/{token}`
را روی اینترنتِ عمومی سرو می‌کند و هر درخواست را روی WireGuard به **gatewayِ خودِ
مستر** فوروارد می‌کند (استریم با حفظِ Range → seek/پخش کار می‌کند). توکن کاملاً روی
مستر resolve می‌شود؛ این نود به Postgres/Bot API نیاز ندارد — فقط دسترسیِ HTTP به
gatewayِ مستر روی WG (`NODE_GATEWAY_URL`). یعنی: بارِ TLS/DDoSِ عمومی و IPِ استریم از
روی مستر برداشته می‌شود.

اجرا (روی نود، توسطِ `node/install.sh`):  python -m app.gateway_node
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import ssl

import aiohttp
from aiohttp import web

from . import nodes
from .config import settings

log = logging.getLogger("telabzar.gateway_node")

# هدرهای پاسخ که از upstream به کلاینت کپی می‌شوند (allowlist — از کپیِ hop-by-hop و
# Content-Encoding پرهیز می‌کنیم تا فریمینگ/بدنه خراب نشود). Range/Content-Range حفظ می‌شوند.
_COPY_RESP = (
    "Content-Type", "Content-Length", "Content-Range", "Accept-Ranges",
    "Content-Disposition", "Cache-Control", "ETag", "Last-Modified", "Expires", "Vary",
    # هدرهای امنیتیِ گیت‌وی باید به کلاینت برسند، وگرنه نودِ استریم محتوای کاربر را
    # بدونِ nosniff/CSP سرو می‌کند و رفعِ گیت‌وی روی این مسیر بی‌اثر می‌شود.
    "X-Content-Type-Options", "Content-Security-Policy",
)
# token از مسیرِ گیت‌وی می‌آید (`secrets.token_urlsafe`): فقط این الفبا مجاز است،
# تا مقدارِ decode‌شده نتواند به upstream مسیر/کوئری تزریق کند.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# هدرهای درخواست که به upstream فوروارد می‌شوند (مهم‌ترینش Range برای seek).
_COPY_REQ = ("Range", "If-Range", "If-None-Match", "If-Modified-Since", "Accept-Encoding")
_CHUNK = 64 * 1024
# **سقفِ استخرِ اتصالِ upstream: هیچ.** پیش‌فرضِ aiohttp `limit=100` است و هر
# استریمِ زنده یک اتصال را تا **پایانِ استریم** نگه می‌دارد، پس صد و یکمین بیننده
# در صفِ استخر می‌ماند تا `connect=15` بگذرد و بعد 502 می‌گرفت — بی‌آنکه مستر
# اصلاً تحت فشار باشد. پروکسی نباید سقفی تنگ‌تر از سروری که جلویش نشسته بگذارد:
# تعدادِ اتصالِ upstream همیشه برابرِ تعدادِ درخواستِ زندهٔ همین سرور است.
_UPSTREAM_LIMIT = 0
# کلاینتی که این‌قدر ثانیه **هیچ** بایتی نخواند رها می‌شود. بدونِ این، یک کلاینتِ
# متوقف (یا مهاجمی که فقط سوکت باز می‌کند و نمی‌خواند) `resp.write` را برای
# همیشه معلق و اتصالِ upstream را برای همیشه اشغال نگه می‌داشت؛ `sock_read`
# فقط سمتِ upstream را می‌پاید، نه کلاینت را. پخش‌کنندهٔ ویدیو با بافرِ پر هم
# مکث می‌کند، پس عدد سخاوتمندانه است — دربارهٔ «مرده»، نه «کند».
_CLIENT_STALL = 120


async def _send(resp: web.StreamResponse, chunk: bytes) -> bool:
    """یک تکه به کلاینت؛ False یعنی کلاینت `_CLIENT_STALL` ثانیه نخواند."""
    try:
        await asyncio.wait_for(resp.write(chunk), _CLIENT_STALL)
        return True
    except asyncio.TimeoutError:
        return False


def _drop(request: web.Request) -> None:
    """`abort` نه `close`: `close` منتظرِ خالی‌شدنِ بافری می‌ماند که کلاینت هرگز نمی‌خواند."""
    tr = request.transport
    if tr is not None:
        tr.abort()


def _upstream() -> str:
    return (settings.node_gateway_url or "http://10.51.0.1:8080").rstrip("/")


async def _forward(request: web.Request, prefix: str) -> web.StreamResponse:
    """درخواست را به `{upstream}{prefix}{token}` فوروارد و پاسخ را استریم می‌کند."""
    token = request.match_info.get("token", "")
    if not _TOKEN_RE.match(token):
        raise web.HTTPNotFound()
    url = f"{_upstream()}{prefix}{token}"
    fwd = {h: request.headers[h] for h in _COPY_REQ if h in request.headers}
    client: aiohttp.ClientSession = request.app["client"]
    state = request.app["state"]
    state["inflight"] += 1
    try:
        async with client.request(request.method, url, headers=fwd,
                                  allow_redirects=False) as up:
            out = {h: up.headers[h] for h in _COPY_RESP if h in up.headers}
            resp = web.StreamResponse(status=up.status, headers=out)
            await resp.prepare(request)
            if request.method != "HEAD":
                async for chunk in up.content.iter_chunked(_CHUNK):
                    if not await _send(resp, chunk):
                        log.info("client stalled %ss on %s; dropping it", _CLIENT_STALL, token)
                        _drop(request)
                        return resp   # خروج از `async with` اتصالِ upstream را می‌بندد
            await resp.write_eof()
            return resp
    except web.HTTPException:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        log.warning("upstream fetch failed for %s: %s", token, exc)
        raise web.HTTPBadGateway(text="upstream unavailable")
    finally:
        state["inflight"] -= 1


async def _dl(request: web.Request) -> web.StreamResponse:
    return await _forward(request, "/dl/")


async def _stream(request: web.Request) -> web.StreamResponse:
    return await _forward(request, "/s/")


async def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _heartbeat(app: web.Application) -> None:
    """هر ~۲۰ ثانیه وضعیتِ نودِ gateway را در Redisِ مستر ثبت می‌کند (پنل آنلاین نشانش می‌دهد)."""
    try:
        from redis.asyncio import from_url
    except Exception as exc:  # noqa: BLE001
        log.warning("redis unavailable, heartbeat disabled: %s", exc)
        return
    r = from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    nid = settings.node_id or settings.node_role or "gateway"
    while True:
        await nodes.write_heartbeat(r, nid, {
            "name": settings.node_name or nid, "role": settings.node_role or "gateway",
            "ver": "1", "load": app["state"]["inflight"]})
        await asyncio.sleep(20)


async def _on_start(app: web.Application) -> None:
    timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_read=120)
    app["client"] = aiohttp.ClientSession(
        timeout=timeout,
        connector=aiohttp.TCPConnector(limit=_UPSTREAM_LIMIT, limit_per_host=0))
    app["state"] = {"inflight": 0}
    if settings.node_role:  # این پروسه یک نود است → heartbeat بزن
        app["hb"] = asyncio.create_task(_heartbeat(app))


async def _on_clean(app: web.Application) -> None:
    hb = app.get("hb")
    if hb is not None:
        hb.cancel()
    client = app.get("client")
    if client is not None:
        await client.close()


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_route("GET", "/health", _health)
    app.router.add_route("GET", "/dl/{token}", _dl)
    app.router.add_route("HEAD", "/dl/{token}", _dl)
    app.router.add_route("GET", "/s/{token}", _stream)
    app.router.add_route("HEAD", "/s/{token}", _stream)
    app.on_startup.append(_on_start)
    app.on_cleanup.append(_on_clean)
    return app


def _ssl_context() -> ssl.SSLContext | None:
    """TLSِ اختیاری روی خودِ نود (اگر cert/key موجود بود)؛ وگرنه HTTP پشتِ CF/پروکسی."""
    cert, key = settings.tls_cert, settings.tls_key
    if cert and key and os.path.exists(cert) and os.path.exists(key):
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(cert, key)
        return ctx
    return None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ctx = _ssl_context()
    log.info("Gateway-node on :%s → upstream %s (tls=%s, node=%s)",
             settings.gateway_port, _upstream(), bool(ctx), settings.node_role or "—")
    web.run_app(build_app(), host="0.0.0.0", port=settings.gateway_port,
                ssl_context=ctx, print=None)


if __name__ == "__main__":
    main()
