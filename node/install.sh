#!/usr/bin/env bash
# نصبِ نودِ Telabzar (master/node روی WireGuard).
# استفاده:  curl -fsSL https://<panel>/node/install.sh | sudo bash -s -- <JOIN_TOKEN>
#
# این اسکریپت: WireGuard + Docker نصب می‌کند، با توکنِ یک‌بارمصرف به مستر join می‌شود
# (کلیدِ WG می‌سازد و کانفیگ + آدرس‌های داخلی را می‌گیرد)، تونل را بالا می‌آورد، و
# ورکرِ نقش را در حالتِ remote اجرا می‌کند. idempotent است؛ با root اجرا شود.
set -euo pipefail

MASTER="__MASTER_BASE__"                 # هنگامِ سرو شدن توسطِ پنل جایگزین می‌شود
TOKEN="${1:-}"
WORKDIR="/opt/telabzar-node"
WG_IFACE="wg0"
REPO="https://github.com/BoofKoor/telabzar.git"

say(){ printf '\033[1;36m==> %s\033[0m\n' "$*"; }
die(){ printf '\033[1;31mخطا: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "با root اجرا کن (sudo)."
[[ -n "$TOKEN" ]] || die "توکنِ join لازم است. از پنل → نودها → «افزودنِ نود» بگیر."
[[ "$MASTER" == http* ]] || die "آدرسِ مستر تنظیم نشده (ADMIN_BASE روی مستر خالی است)."

say "نصبِ پیش‌نیازها (wireguard, docker, jq)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq wireguard-tools jq curl git ca-certificates >/dev/null
command -v docker >/dev/null || sh -c "$(curl -fsSL https://get.docker.com)"

say "ساختِ کلیدِ WireGuard…"
mkdir -p "$WORKDIR" /etc/wireguard
umask 077
[[ -f "$WORKDIR/wg_priv" ]] || wg genkey > "$WORKDIR/wg_priv"
PRIV=$(cat "$WORKDIR/wg_priv")
PUB=$(printf '%s' "$PRIV" | wg pubkey)
HOSTNAME_SHORT=$(hostname -s 2>/dev/null || echo node)

say "join به مستر…"
RESP=$(curl -fsS -X POST "$MASTER/node/join" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg t "$TOKEN" --arg p "$PUB" --arg n "$HOSTNAME_SHORT" \
        '{token:$t, pubkey:$p, name:$n}')") || die "join ناموفق (توکن منقضی/مصرف‌شده؟)."
echo "$RESP" | jq -e '.node_id' >/dev/null 2>&1 || die "پاسخِ join نامعتبر: $RESP"

NODE_ID=$(echo "$RESP" | jq -r '.node_id')
WG_ADDR=$(echo "$RESP" | jq -r '.wg.address')
WG_MPUB=$(echo "$RESP" | jq -r '.wg.master_pubkey')
WG_ENDP=$(echo "$RESP" | jq -r '.wg.endpoint')
WG_ALLOW=$(echo "$RESP" | jq -r '.wg.allowed_ips')
ROLE=$(echo "$RESP"    | jq -r '.role')
QUEUE=$(echo "$RESP"   | jq -r '.worker.settings')
REDIS_URL=$(echo "$RESP" | jq -r '.services.redis_url')
PG_DSN=$(echo "$RESP"    | jq -r '.services.postgres_dsn')
API_BASE=$(echo "$RESP"  | jq -r '.services.api_base')
POT_URL=$(echo "$RESP"   | jq -r '.services.pot_provider_url')
BOT_TOKEN=$(echo "$RESP" | jq -r '.services.bot_token')

say "برپاییِ تونلِ WireGuard ($WG_ADDR)…"
cat > "/etc/wireguard/${WG_IFACE}.conf" <<EOF
[Interface]
PrivateKey = ${PRIV}
Address = ${WG_ADDR}

[Peer]
PublicKey = ${WG_MPUB}
Endpoint = ${WG_ENDP}
AllowedIPs = ${WG_ALLOW}
PersistentKeepalive = 25
EOF
systemctl enable --now "wg-quick@${WG_IFACE}" 2>/dev/null || wg-quick up "$WG_IFACE" || true
wg-quick down "$WG_IFACE" 2>/dev/null || true; wg-quick up "$WG_IFACE"

say "دریافتِ کد و ساختِ ایمیجِ نقش ($ROLE)…"
[[ -d "$WORKDIR/repo/.git" ]] && (cd "$WORKDIR/repo" && git pull -q) \
  || git clone --depth 1 "$REPO" "$WORKDIR/repo"
cd "$WORKDIR/repo"
docker build -q -f docker/download-worker.Dockerfile -t telabzar-node:$ROLE . >/dev/null

say "اجرای ورکرِ نود…"
docker rm -f telabzar-node 2>/dev/null || true
docker run -d --name telabzar-node --restart unless-stopped --network host \
  -e BOT_TOKEN="$BOT_TOKEN" \
  -e REDIS_URL="$REDIS_URL" \
  -e POSTGRES_DSN="$PG_DSN" \
  -e LOCAL_API_BASE="$API_BASE" \
  -e POT_PROVIDER_URL="$POT_URL" \
  -e NODE_ROLE="$ROLE" -e NODE_ID="$NODE_ID" -e NODE_NAME="$HOSTNAME_SHORT" \
  telabzar-node:$ROLE arq "$QUEUE"

say "تمام شد ✅  نودِ «$ROLE» ($NODE_ID) وصل شد. در پنل → نودها آنلاین می‌شود."
