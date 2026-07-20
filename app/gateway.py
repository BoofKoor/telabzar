"""سرویسِ HTTP برای لینکِ دانلود/استریم.

چون از Local Bot API Server استفاده می‌کنیم، فایل‌ها روی دیسک هستند؛ پس
به‌جای MTProto، همان فایلِ لوکال را با پشتیبانیِ Range (برای seek/استریم)
سرو می‌کنیم. اجرا:  python -m app.gateway
"""
from __future__ import annotations

import logging
import os
import ssl
from urllib.parse import quote

from aiohttp import web
from sqlalchemy import select

from .bot import create_bot
from .config import settings
from .db import Sessionmaker
from .models import File

log = logging.getLogger("telabzar.gateway")


async def _lookup(token: str) -> File | None:
    async with Sessionmaker() as session:
        result = await session.execute(select(File).where(File.dl_token == token))
        return result.scalar_one_or_none()


async def _serve(request: web.Request, *, inline: bool) -> web.StreamResponse:
    token = request.match_info.get("token", "")
    if not token or len(token) > 64:
        raise web.HTTPNotFound()
    file = await _lookup(token)
    if file is None:
        raise web.HTTPNotFound()
    try:
        tg_file = await request.app["bot"].get_file(file.file_id)
    except Exception as exc:  # noqa: BLE001  — فایل روی سرور نیست/خطای API
        log.warning("gateway get_file failed for %s: %s", token, exc)
        raise web.HTTPNotFound()
    path = tg_file.file_path
    if not path or not os.path.exists(path):
        raise web.HTTPNotFound()

    name = file.name or "file"
    disp = "inline" if inline else "attachment"
    # RFC 5987 برای نام‌های غیر-ASCII (فارسی)
    headers = {"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(name)}"}
    resp = web.FileResponse(path, headers=headers)  # FileResponse خودش Range را می‌فهمد
    if file.mime:
        resp.content_type = file.mime
    return resp


async def _dl(request: web.Request) -> web.StreamResponse:
    return await _serve(request, inline=False)


async def _stream(request: web.Request) -> web.StreamResponse:
    return await _serve(request, inline=True)


async def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _close_bot(app: web.Application) -> None:
    await app["bot"].session.close()


def build_app() -> web.Application:
    app = web.Application()
    app["bot"] = create_bot(request_timeout=600.0)
    app.router.add_get("/health", _health)
    app.router.add_get("/dl/{token}", _dl)
    app.router.add_get("/s/{token}", _stream)
    app.on_cleanup.append(_close_bot)
    return app


def _ssl_context() -> ssl.SSLContext | None:
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
    log.info("Gateway on :%s  (tls=%s, base=%s)",
             settings.gateway_port, bool(ctx), settings.public_base or "—")
    web.run_app(build_app(), host="0.0.0.0", port=settings.gateway_port,
                ssl_context=ctx, print=None)


if __name__ == "__main__":
    main()
