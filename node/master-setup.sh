#!/usr/bin/env bash
# آماده‌سازیِ خودکارِ زیرساختِ مستر برای نودهای توزیع‌شده (فاز N5).
# روی سرورِ مستر با root اجرا شود:  sudo bash node/master-setup.sh   (یا: telabzar nodes-enable)
#
# این اسکریپت (idempotent):
#  1) WireGuard نصب می‌کند، کلیدِ مستر می‌سازد، wg0 را با [Interface] بالا می‌آورد،
#     IP forwarding و UDP 51820 را باز می‌کند، و روی بوت enable می‌کند.
#  2) IPِ عمومی را تشخیص می‌دهد و WG_*/NODE_* را در .env می‌نویسد (بدونِ ویرایشِ دستی).
#  3) یک تایمرِ systemd (telabzar-wg-sync) نصب می‌کند که [Peer]ها را از جدولِ Node
#     همگام می‌کند (افزودن/حذفِ نود از پنل خودکار روی تونل اعمال می‌شود، self-healing).
#  4) overlayِ docker-compose.nodes.yml را اعمال می‌کند تا redis/postgres/bot-api/pot/
#     gateway روی IPِ WG منتشر شوند (نودها روی تونل می‌رسند؛ IPِ عمومی دست‌نخورده).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$HERE/.env"
WG_IFACE="wg0"
WG_MASTER_IP="10.51.0.1"
WG_SUBNET="10.51.0.0/24"
WG_PORT="51820"
WG_DIR="/etc/wireguard"

say(){ printf '\033[1;36m==> %s\033[0m\n' "$*"; }
ok(){ printf '\033[1;32m✓\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31mخطا: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "با root اجرا کن (sudo)."
[[ -f "$ENV_FILE" ]] || die ".env پیدا نشد ($ENV_FILE). اول install.sh را اجرا کن."

env_get(){ sed -n "s/^$1=//p" "$ENV_FILE" | head -n1; }
set_env(){ # set_env KEY VALUE  (جایگزین یا افزودن)
  local k="$1" v="$2"
  if grep -q "^${k}=" "$ENV_FILE"; then sed -i "s|^${k}=.*|${k}=${v}|" "$ENV_FILE"
  else echo "${k}=${v}" >> "$ENV_FILE"; fi
}

say "نصبِ پیش‌نیازها (wireguard, curl)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq wireguard-tools curl iproute2 >/dev/null

say "ساختِ کلیدِ WireGuardِ مستر…"
mkdir -p "$WG_DIR"; umask 077
[[ -f "$WG_DIR/master_priv" ]] || wg genkey > "$WG_DIR/master_priv"
MPRIV=$(cat "$WG_DIR/master_priv")
MPUB=$(printf '%s' "$MPRIV" | wg pubkey)

# IPِ عمومی برای WG_ENDPOINT (آرگومان > تشخیصِ خودکار)
PUBIP="${1:-}"
[[ -n "$PUBIP" ]] || PUBIP=$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)
[[ -n "$PUBIP" ]] || PUBIP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
[[ -n "$PUBIP" ]] || die "IPِ عمومی تشخیص داده نشد؛ به‌صورتِ آرگومان بده: master-setup.sh <PUBLIC_IP>"

say "نوشتنِ [Interface]ِ ثابت + wg0.conf…"
# [Interface] ثابت در فایلِ جدا نگه‌داری می‌شود؛ wg-sync هربار = interface + peers(from DB)
cat > "$WG_DIR/${WG_IFACE}.interface" <<EOF
[Interface]
Address = ${WG_MASTER_IP}/24
ListenPort = ${WG_PORT}
PrivateKey = ${MPRIV}
EOF
# اگر wg0.conf نبود، از روی interface بساز (peerها را wg-sync اضافه می‌کند)
[[ -f "$WG_DIR/${WG_IFACE}.conf" ]] || cp "$WG_DIR/${WG_IFACE}.interface" "$WG_DIR/${WG_IFACE}.conf"

say "فعال‌کردنِ IP forwarding + بازکردنِ UDP ${WG_PORT}…"
sysctl -qw net.ipv4.ip_forward=1 || true
grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf 2>/dev/null || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
command -v ufw >/dev/null && ufw allow "${WG_PORT}/udp" >/dev/null 2>&1 || true

say "بالا آوردنِ تونلِ wg0 + enable روی بوت…"
systemctl enable "wg-quick@${WG_IFACE}" >/dev/null 2>&1 || true
wg-quick down "$WG_IFACE" 2>/dev/null || true
wg-quick up "$WG_IFACE" || die "wg-quick up ناموفق (کانفیگِ $WG_DIR/${WG_IFACE}.conf را ببین)."

say "به‌روزرسانیِ .env با آدرس‌های WG…"
PG_USER=$(env_get POSTGRES_USER); PG_PASS=$(env_get POSTGRES_PASSWORD); PG_DB=$(env_get POSTGRES_DB)
NSECRET=$(env_get NODE_SECRET); [[ -n "$NSECRET" ]] || NSECRET=$(env_get BOT_TOKEN)
set_env WG_INTERFACE     "$WG_IFACE"
set_env WG_SUBNET        "$WG_SUBNET"
set_env WG_MASTER_IP     "$WG_MASTER_IP"
set_env WG_MASTER_PUBKEY "$MPUB"
set_env WG_ENDPOINT      "${PUBIP}:${WG_PORT}"
set_env WG_CONFIG_PATH   "$WG_DIR/${WG_IFACE}.conf"
set_env NODE_SECRET      "$NSECRET"
set_env NODE_REDIS_URL        "redis://${WG_MASTER_IP}:6379/0"
set_env NODE_POSTGRES_DSN     "postgresql+asyncpg://${PG_USER}:${PG_PASS}@${WG_MASTER_IP}:5432/${PG_DB}"
set_env NODE_API_BASE         "http://${WG_MASTER_IP}:8081"
set_env NODE_POT_PROVIDER_URL "http://${WG_MASTER_IP}:4416"
set_env NODE_GATEWAY_URL      "http://${WG_MASTER_IP}:8080"

say "نصبِ تایمرِ همگام‌سازیِ peerها (telabzar-wg-sync)…"
install -m 700 "$HERE/node/wg-sync.sh" /usr/local/sbin/telabzar-wg-sync
cat > /etc/systemd/system/telabzar-wg-sync.service <<EOF
[Unit]
Description=Telabzar WireGuard peer sync (from Node table)
After=wg-quick@${WG_IFACE}.service
[Service]
Type=oneshot
Environment=TELABZAR_DIR=${HERE}
ExecStart=/usr/local/sbin/telabzar-wg-sync
EOF
cat > /etc/systemd/system/telabzar-wg-sync.timer <<EOF
[Unit]
Description=Run Telabzar WG peer sync every 30s
[Timer]
OnBootSec=30
OnUnitActiveSec=30
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now telabzar-wg-sync.timer >/dev/null 2>&1 || true

# docker بعد از wg0 بالا بیاید تا bind روی IPِ WG موفق شود
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/telabzar-wg.conf <<EOF
[Unit]
After=wg-quick@${WG_IFACE}.service
Wants=wg-quick@${WG_IFACE}.service
EOF
systemctl daemon-reload || true

say "اعمالِ overlayِ نودها روی استک (انتشارِ سرویس‌ها روی IPِ WG)…"
COMPOSE="docker compose"; docker compose version >/dev/null 2>&1 || COMPOSE="docker-compose"
touch "$HERE/.nodes-enabled"   # نشانه برای CLI تا از overlay استفاده کند
(cd "$HERE" && WG_MASTER_IP="$WG_MASTER_IP" $COMPOSE -f docker-compose.yml -f docker-compose.nodes.yml up -d)

# اولین همگام‌سازیِ peer را همین حالا بزن
/usr/local/sbin/telabzar-wg-sync || true

ok "زیرساختِ مستر آماده شد."
say "  • WG_ENDPOINT = ${PUBIP}:${WG_PORT}  ·  WG_MASTER_IP = ${WG_MASTER_IP}"
say "  • حالا از پنل → نودها یک نود اضافه کن؛ چند ثانیه بعد آنلاین می‌شود."
