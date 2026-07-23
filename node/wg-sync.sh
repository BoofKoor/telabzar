#!/usr/bin/env bash
# همگام‌سازیِ اعلانیِ [Peer]های WireGuardِ مستر از رویِ جدولِ Node (منبعِ حقیقت).
# توسطِ تایمرِ systemd (telabzar-wg-sync) هر ~۳۰ث اجرا می‌شود؛ node/master-setup.sh نصبش می‌کند.
#
# wg0.conf = [Interface]ِ ثابت (wg0.interface) + [Peer]هایی که پنل از جدولِ Node می‌دهد،
# سپس `wg syncconf` (بدونِ قطعِ تونل). پس افزودن/حذفِ نود از پنل خودکار روی تونل اعمال و
# self-healing می‌شود (peerِ دستی‌حذف‌شده برمی‌گردد؛ نودِ حذف‌شده می‌رود).
set -euo pipefail

DIR="${TELABZAR_DIR:-/opt/telabzar}"
ENV_FILE="$DIR/.env"
WG_DIR="/etc/wireguard"
WG_IFACE="wg0"

[[ -f "$ENV_FILE" ]] || { echo "wg-sync: .env نیست ($ENV_FILE)"; exit 0; }
env_get(){ sed -n "s/^$1=//p" "$ENV_FILE" | head -n1; }

SECRET=$(env_get NODE_SECRET); [[ -n "$SECRET" ]] || SECRET=$(env_get BOT_TOKEN)
PORT=$(env_get ADMIN_HTTPS_PORT); PORT="${PORT:-2083}"
[[ -n "$SECRET" ]] || { echo "wg-sync: NODE_SECRET/BOT_TOKEN نیست"; exit 0; }

# پنل روی هاست منتشر شده (TLS یا http)؛ اول https با -k، بعد http
fetch(){ curl -fsS --max-time 8 "$1" 2>/dev/null; }
PEERS=$(fetch "https://127.0.0.1:${PORT}/node/peers?key=${SECRET}" ) \
  || PEERS=$(fetch "http://127.0.0.1:${PORT}/node/peers?key=${SECRET}") \
  || { echo "wg-sync: پنل در دسترس نیست (127.0.0.1:${PORT})"; exit 0; }

# پاسخِ نامعتبر (مثلِ 403 که با -f نمی‌آید، ولی محضِ احتیاط) → کاری نکن
case "$PEERS" in
  \#*) echo "wg-sync: پاسخِ نامعتبر از پنل"; exit 0 ;;
esac

[[ -f "$WG_DIR/${WG_IFACE}.interface" ]] || { echo "wg-sync: interfaceِ پایه نیست؛ master-setup را اجرا کن"; exit 0; }

TMP=$(mktemp)
cat "$WG_DIR/${WG_IFACE}.interface" > "$TMP"
printf '%s\n' "$PEERS" >> "$TMP"
install -m 600 "$TMP" "$WG_DIR/${WG_IFACE}.conf"
rm -f "$TMP"

# اعمالِ بدونِ قطعِ تونل
if command -v wg >/dev/null; then
  wg syncconf "$WG_IFACE" <(wg-quick strip "$WG_IFACE") 2>/dev/null \
    || echo "wg-sync: syncconf ناموفق (wg0 بالا است؟)"
fi
