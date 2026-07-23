"""لایهٔ نودِ توزیع‌شده (master ↔ node) — سمتِ مستر.

یک **نود** = ماشینِ راه‌دور که با **WireGuard** به شبکهٔ خصوصیِ مستر وصل می‌شود و
یک ورکرِ ARQ در حالتِ **remote** (`is_local=False`: ورودی را از HTTPِ Bot API دانلود،
خروجی را multipart آپلود) اجرا می‌کند، و یک agentِ heartbeat وضعیتش را در Redis ثبت
می‌کند. ARQ همین حالا کارِ توزیعِ جاب را روی Redis انجام می‌دهد؛ نود فقط ورکری روی
همان Redis است — نه پروتکلِ جدید.

این ماژول (سمتِ مستر): نقش‌ها، توکنِ join (امضاشده + یک‌بارمصرف)، تخصیصِ IPِ WireGuard،
رجیستریِ زندهٔ نودها (Redis heartbeat)، و مدیریتِ peerهای WireGuard (فایلِ کانفیگ +
`wg syncconf`). منطقِ خالص (توکن/تخصیص/کانفیگ) تست‌پذیر است؛ اجرای واقعیِ `wg` روی
سرورِ مستر آزمایش می‌شود.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import subprocess
import time

from .config import settings

log = logging.getLogger("telabzar.nodes")

# نقش‌ها: هر نقش = کدام صف/ورکر/ایمیج را می‌گیرد.
ROLES: dict[str, dict] = {
    "download": {
        "label": "دانلود / IP-تمیز", "emoji": "⬇️",
        "queue": "arq:queue:dl", "worker": "app.worker.DownloadWorkerSettings",
        "image": "download-worker",
        "desc": "yt-dlp/gallery-dl/spotify روی IPِ تمیز (یوتیوب/اینستا).",
    },
    "processing": {  # فاز N2: opهای سنگینِ CPU (کاهش‌حجم/تبدیل/رونویسی/…) از راه دور
        "label": "پردازش / کاهش‌حجم", "emoji": "⚙️",
        "queue": "arq:queue:proc", "worker": "app.worker.ProcessingWorkerSettings",
        "image": "worker",
        "desc": "run_op سنگین (compress/convert/transcribe/bg/ویدیو) روی ماشینِ قوی‌تر.",
    },
    # آینده (N3):
    # "gateway":  {... سرویسِ gateway/استریم ...},
}

# opهای سنگینِ CPU که وقتی نودِ processing آنلاین است به آن سپرده می‌شوند. opهای سبک
# (rename/metadata/چرخش/…) و scan (که به سرویسِ ClamAVِ مستر وصل است) روی مستر می‌مانند.
OFFLOAD_OPS: frozenset[str] = frozenset({
    "compress", "convert", "transcribe", "bg_remove", "to_gif", "extract_audio",
    "watermark", "trim", "normalize", "speed", "video_concat", "screenshot",
    "thumb", "mute", "images_to_pdf", "to_pdf",
})

_NODE_PREFIX = "node:"          # کلیدِ heartbeat: node:{id} → JSON با TTL
_JOIN_PREFIX = "njoin:"         # توکنِ یک‌بارمصرف: njoin:{jti} → role (TTL)
_HEARTBEAT_TTL = 45             # ثانیه — نبودِ heartbeat بیش از این = آفلاین


def _secret() -> bytes:
    return (settings.node_secret or settings.bot_token or "telabzar").encode()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── توکنِ join (امضاشدهٔ HMAC + یک‌بارمصرف از طریقِ Redis) ────────
async def make_join_token(redis, role: str, ttl: int = 1800) -> str:
    """توکنِ نصب می‌سازد: payload امضاشده + jti که در Redis کوتاه‌عمر و یک‌بارمصرف است."""
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    jti = _b64e(os.urandom(9))
    payload = {"jti": jti, "role": role, "exp": int(time.time()) + ttl}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    try:
        await redis.set(_JOIN_PREFIX + jti, role, ex=ttl)
    except Exception as exc:  # noqa: BLE001
        log.warning("join token store failed: %s", exc)
    return f"{body}.{sig}"


def _parse_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    good = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, TypeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    if payload.get("role") not in ROLES:
        return None
    return payload


async def consume_join_token(redis, token: str) -> dict | None:
    """امضا/انقضا را چک و توکن را **یک‌بار** مصرف می‌کند (GETDEL). payload یا None."""
    payload = _parse_token(token)
    if payload is None:
        return None
    jti = payload["jti"]
    try:
        used = await redis.getdel(_JOIN_PREFIX + jti)
    except AttributeError:  # ردیس‌های قدیمی: get سپس delete
        used = await redis.get(_JOIN_PREFIX + jti)
        if used is not None:
            await redis.delete(_JOIN_PREFIX + jti)
    except Exception as exc:  # noqa: BLE001
        log.warning("join token consume failed: %s", exc)
        return None
    return payload if used else None


# ── تخصیصِ IPِ WireGuard ────────────────────────────────────────
def next_wg_ip(used: set[str]) -> str | None:
    """اولین IPِ آزادِ سابنتِ WG (به‌جز IPِ مستر). None اگر پر شد."""
    net = ipaddress.ip_network(settings.wg_subnet, strict=False)
    master = settings.wg_master_ip
    for host in net.hosts():
        ip = str(host)
        if ip != master and ip not in used:
            return ip
    return None


# ── رجیستریِ زنده (heartbeat در Redis) ──────────────────────────
async def write_heartbeat(redis, node_id: str, data: dict) -> None:
    try:
        await redis.set(_NODE_PREFIX + node_id, json.dumps(data), ex=_HEARTBEAT_TTL)
    except Exception as exc:  # noqa: BLE001
        log.debug("heartbeat write failed: %s", exc)


async def list_live(redis) -> dict[str, dict]:
    """node_id → آخرین heartbeat (فقط نودهای آنلاین؛ آفلاین‌ها TTL‌شان تمام شده)."""
    out: dict[str, dict] = {}
    try:
        keys = [k async for k in redis.scan_iter(match=_NODE_PREFIX + "*")]
        for k in keys:
            raw = await redis.get(k)
            if raw:
                nid = (k if isinstance(k, str) else k.decode()).split(":", 1)[1]
                try:
                    out[nid] = json.loads(raw)
                except (ValueError, TypeError):
                    pass
    except Exception as exc:  # noqa: BLE001
        log.debug("list_live failed: %s", exc)
    return out


async def role_online(redis, role: str) -> bool:
    """آیا حداقل یک نودِ این نقش الان heartbeat‌ِ زنده دارد؟ (مبنایِ مسیریابیِ enqueue)."""
    live = await list_live(redis)
    return any(v.get("role") == role for v in live.values())


# ── مدیریتِ peerهای WireGuard (فایلِ کانفیگ + syncconf) ──────────
def peer_block(pubkey: str, ip: str) -> str:
    """بلوکِ [Peer]‌ی wg-quick برای یک نود (کلیدِ عمومی + IPِ /32)."""
    return f"\n[Peer]\n# telabzar-node {ip}\nPublicKey = {pubkey}\nAllowedIPs = {ip}/32\n"


def _syncconf() -> None:
    """کانفیگِ فایل را بدونِ قطعِ تونل روی اینترفیس اعمال می‌کند (best-effort، سرورِ مستر)."""
    iface = settings.wg_interface
    try:
        stripped = subprocess.run(["wg-quick", "strip", iface], capture_output=True, check=True).stdout
        subprocess.run(["wg", "syncconf", iface, "/dev/stdin"], input=stripped, check=True)
    except Exception as exc:  # noqa: BLE001  — روی مستر با WG واقعی تست می‌شود
        log.warning("wg syncconf failed (%s): %s", iface, exc)


def add_peer(pubkey: str, ip: str) -> None:
    path = settings.wg_config_path
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(peer_block(pubkey, ip))
    except OSError as exc:
        log.warning("wg config append failed: %s", exc)
        return
    _syncconf()


def remove_peer(pubkey: str) -> None:
    """بلوکِ peer با این PublicKey را از فایل حذف و کانفیگ را دوباره اعمال می‌کند."""
    path = settings.wg_config_path
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return
    new = _strip_peer(text, pubkey)
    if new != text:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
        except OSError as exc:
            log.warning("wg config rewrite failed: %s", exc)
            return
        _syncconf()


def _strip_peer(text: str, pubkey: str) -> str:
    """بلوکِ [Peer]‌ای که PublicKey‌اش برابرِ pubkey است را حذف می‌کند (خالص/تست‌پذیر)."""
    blocks = text.split("[Peer]")
    kept = [blocks[0]]
    for b in blocks[1:]:
        if f"PublicKey = {pubkey}" in b or f"PublicKey={pubkey}" in b:
            continue
        kept.append(b)
    return "[Peer]".join(kept)


def node_config(role: str, node_ip: str) -> dict:
    """پاسخِ /node/join: کانفیگِ WG + URLهای داخلی + اطلاعاتِ نقش برای اسکریپتِ نود."""
    r = ROLES[role]
    return {
        "role": role,
        "wg": {
            "address": f"{node_ip}/32",
            "master_pubkey": settings.wg_master_pubkey,
            "endpoint": settings.wg_endpoint,
            "allowed_ips": settings.wg_subnet,
            "master_ip": settings.wg_master_ip,
        },
        "services": {  # نود اینها را روی WG می‌بیند (نه public)
            "redis_url": settings.node_redis_url,
            "postgres_dsn": settings.node_postgres_dsn,
            "api_base": settings.node_api_base,
            "pot_provider_url": settings.node_pot_provider_url,
            # نودِ ورکر خودش «ربات» است و برای Bot API به توکن نیاز دارد (کانالِ WG + توکنِ
            # یک‌بارمصرفِ join آن را می‌بندد). نودها admin-provisioned و مورداعتمادند.
            "bot_token": settings.bot_token,
        },
        "worker": {"queue": r["queue"], "settings": r["worker"], "image": r["image"]},
    }
