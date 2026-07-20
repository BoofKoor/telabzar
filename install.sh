#!/usr/bin/env bash
# ── تل‌ابزار · نصب تعاملی (Milestone 1) ─────────────────────────
# مقادیر را موقع نصب می‌پرسد، .env می‌سازد، و استک را بالا می‌آورد.
# حالت‌ها: master (فعال)، node (در M5).
set -euo pipefail

BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; RESET=$'\e[0m'
say()  { printf "%s\n" "$*"; }
ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}!${RESET} %s\n" "$*"; }
die()  { printf "${RED}✗ %s${RESET}\n" "$*" >&2; exit 1; }

rand() { openssl rand -hex "${1:-24}" 2>/dev/null || head -c "${1:-24}" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

# مقدارِ یک کلید از .envِ موجود (برای حفظِ اسرار هنگامِ reconfigure)
env_get() { [[ -f .env ]] && sed -n "s/^$1=//p" .env | head -n1 || true; }

ask() { # ask <var> <prompt> [default]
  local __var=$1 __prompt=$2 __def=${3:-} __ans=""
  if [[ -n "$__def" ]]; then
    read -rp "$(printf "${BOLD}?${RESET} %s ${DIM}[%s]${RESET}: " "$__prompt" "$__def")" __ans || true
    __ans=${__ans:-$__def}
  else
    read -rp "$(printf "${BOLD}?${RESET} %s: " "$__prompt")" __ans || true
  fi
  printf -v "$__var" '%s' "$__ans"
}

read_pem() { # read_pem <outfile> <label>
  local out=$1 label=$2 line
  say ""
  say "${BOLD}${label}${RESET}"
  say "${DIM}کلِ متن (شاملِ خطوطِ BEGIN/END) را بچسبان، بعد در یک خطِ جدا فقط ${RESET}${BOLD}EOF${RESET}${DIM} بنویس و Enter بزن:${RESET}"
  : > "$out"; chmod 600 "$out"
  while IFS= read -r line; do
    [[ "$line" == "EOF" ]] && break
    printf '%s\n' "$line" >> "$out"
  done
  if ! grep -q "BEGIN" "$out"; then
    warn "به‌نظر PEM معتبری وارد نشد (خطِ BEGIN پیدا نشد)."
  fi
}

require_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker نصب نیست. اول Docker را نصب کن: https://docs.docker.com/engine/install/"
  if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose";
  elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose";
  else die "Docker Compose پیدا نشد."; fi
  ok "Docker و Compose آماده‌اند."
}

banner() {
  cat <<'EOF'

  ┌────────────────────────────────────────────┐
  │   تل‌ابزار — نصب تعاملی · Telabzar setup     │
  └────────────────────────────────────────────┘
EOF
}

install_master() {
  say ""
  say "${BOLD}پیکربندی سرور master${RESET}"
  say "${DIM}مقادیر تلگرام را از @BotFather و my.telegram.org بگیر.${RESET}"
  say ""

  ask BOT_TOKEN "توکن ربات (BotFather)"
  [[ "$BOT_TOKEN" == *:* ]] || die "فرمت توکن نامعتبر است."
  ask TG_API_ID "TG_API_ID (my.telegram.org)"
  [[ "$TG_API_ID" =~ ^[0-9]+$ ]] || die "TG_API_ID باید عدد باشد."
  ask TG_API_HASH "TG_API_HASH (my.telegram.org)"
  [[ -n "$TG_API_HASH" ]] || die "TG_API_HASH خالی است."
  ask ADMIN_IDS "شناسهٔ عددی ادمین‌ها (با کاما جدا کن)"
  ask DEFAULT_LANG "زبان پیش‌فرض (fa/en)" "fa"
  ask MAX_FILE_MB "سقف حجم هر فایل (مگابایت)" "2000"

  # ── دامنه و TLS برای لینکِ دانلود/استریم (اختیاری) ──
  say ""
  say "${BOLD}لینکِ دانلود/استریم${RESET} ${DIM}(اختیاری — برای دادنِ لینک به فایل‌ها)${RESET}"
  say "${DIM}دامنه پشتِ Cloudflare (پروکسی روشن) و یک Origin Certificate از پنلِ Cloudflare لازم است.${RESET}"
  ask DOMAIN "دامنه (مثلِ files.example.com — Enter برای رد شدن)" ""

  local PUBLIC_BASE="" TLS_CERT="" TLS_KEY="" GW_PORT="8080"
  if [[ -n "$DOMAIN" ]]; then
    say "${DIM}اگر ۴۴۳ سرور آزاد است بزن ۴۴۳؛ اگر اشغال است ۸۴۴۳ (کلودفلر هر دو را پروکسی می‌کند).${RESET}"
    ask GW_PORT "پورتِ HTTPS روی سرور" "8443"
    if [[ "$GW_PORT" == "443" ]]; then PUBLIC_BASE="https://${DOMAIN}"; else PUBLIC_BASE="https://${DOMAIN}:${GW_PORT}"; fi
    mkdir -p certs
    read_pem certs/cert.pem "۱) سرتیفیکیتِ Origin کلودفلر (Origin Certificate)"
    read_pem certs/key.pem  "۲) کلیدِ خصوصیِ Origin (Private Key)"
    TLS_CERT="/certs/cert.pem"; TLS_KEY="/certs/key.pem"
    ok "دامنه و سرتیفیکیت تنظیم شد → ${PUBLIC_BASE}"
  else
    warn "بدونِ دامنه؛ دکمهٔ «لینک» تا تنظیمِ دامنه (telabzar reconfigure) غیرفعال است."
  fi

  # اسرارِ ثابت را از .envِ موجود حفظ کن (رمزِ Postgres در ولومِ pg-data پخته
  # شده؛ بازتولیدِ آن هنگامِ reconfigure اتصالِ دیتابیس را می‌شکند).
  local PG_PASS WH_SECRET
  PG_PASS=$(env_get POSTGRES_PASSWORD); [[ -n "$PG_PASS" ]] || PG_PASS=$(rand 18)
  WH_SECRET=$(env_get WEBHOOK_SECRET); [[ -n "$WH_SECRET" ]] || WH_SECRET=$(rand 24)

  umask 077
  cat > .env <<EOF
# ساخته‌شده توسط install.sh — دستی ویرایش نکن (از: ./install.sh یا telabzar reconfigure)
BOT_TOKEN=${BOT_TOKEN}
TG_API_ID=${TG_API_ID}
TG_API_HASH=${TG_API_HASH}
ADMIN_IDS=${ADMIN_IDS}
DEFAULT_LANG=${DEFAULT_LANG}
MAX_FILE_MB=${MAX_FILE_MB}
WEBHOOK_SECRET=${WH_SECRET}
POSTGRES_USER=telabzar
POSTGRES_PASSWORD=${PG_PASS}
POSTGRES_DB=telabzar
DOMAIN=${DOMAIN}
PUBLIC_BASE=${PUBLIC_BASE}
GATEWAY_HTTPS_PORT=${GW_PORT}
TLS_CERT=${TLS_CERT}
TLS_KEY=${TLS_KEY}
EOF
  ok ".env ساخته شد (اسرار تصادفی تولید شدند)."

  say ""
  say "${BOLD}خلاصه:${RESET}"
  say "  • ربات با ${BOLD}long-polling${RESET} به local-bot-api وصل می‌شود."
  say "  • سرویس‌ها: local-bot-api · postgres · redis · bot · worker · clamav · gateway"
  if [[ -n "$DOMAIN" ]]; then
    say "  • لینک/استریم روی ${BOLD}${PUBLIC_BASE}${RESET} (پورتِ ${GW_PORT})."
  fi
  local CONFIRM
  ask CONFIRM "شروع نصب و بالا آوردن استک؟ (y/n)" "y"
  [[ "$CONFIRM" =~ ^[Yy]$ ]] || { warn "لغو شد. .env ساخته شد؛ بعداً 'telabzar up' را بزن."; exit 0; }

  say ""
  say "در حال build و اجرا…"
  $COMPOSE up -d --build

  install_cli
  say ""
  ok "بالا آمد. ربات هنگام استارت، وبهوک را خودش ثبت می‌کند."
  say "${DIM}وضعیت:${RESET}  telabzar status    ${DIM}|${RESET}   ${DIM}لاگ:${RESET}  telabzar logs"
  say "${DIM}حالا در تلگرام به ربات /start بده.${RESET}"
}

install_cli() {
  # نصب یک CLIِ کمکی سبک برای مدیریت روزمره
  local target="/usr/local/bin/telabzar" here; here=$(pwd)
  if [[ -w "$(dirname "$target")" ]] || sudo -n true 2>/dev/null; then
    local SUDO=""; [[ -w "$(dirname "$target")" ]] || SUDO="sudo"
    $SUDO tee "$target" >/dev/null <<EOF
#!/usr/bin/env bash
cd "$here" || exit 1
case "\${1:-}" in
  up)          ${COMPOSE} up -d --build ;;
  down)        ${COMPOSE} down ;;
  status|ps)   ${COMPOSE} ps ;;
  logs)        ${COMPOSE} logs --tail=200 \${2:-} ;;
  logf)        ${COMPOSE} logs -f --tail=100 \${2:-} ;;
  update)      git fetch origin main && git checkout -f -B main origin/main && ${COMPOSE} up -d --build ;;
  reconfigure) exec bash "$here/install.sh" ;;
  *) echo "استفاده: telabzar {up|down|status|logs|update|reconfigure}" ;;
esac
EOF
    $SUDO chmod +x "$target"
    ok "CLI نصب شد: ${BOLD}telabzar${RESET}"
  else
    warn "دسترسی نوشتن در /usr/local/bin نبود؛ CLI نصب نشد (اختیاری)."
  fi
}

install_node() {
  say ""
  warn "حالت node در Milestone 5 (لایهٔ توزیع‌شده) فعال می‌شود."
  say "${DIM}فعلاً فقط master را نصب کن؛ افزودن نود بعداً از پنل ادمین انجام می‌شود.${RESET}"
  exit 0
}

main() {
  banner
  require_docker
  say ""
  say "این سرور چیست؟"
  say "  ${BOLD}1${RESET}) master  ${DIM}(همه‌چیز رویش هست)${RESET}"
  say "  ${BOLD}2${RESET}) node    ${DIM}(کارگر — در M5)${RESET}"
  local MODE
  ask MODE "انتخاب" "1"
  case "$MODE" in
    1|master) install_master ;;
    2|node)   install_node ;;
    *) die "انتخاب نامعتبر." ;;
  esac
}

main "$@"
