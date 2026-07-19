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
  ask DOMAIN "دامنه برای لینک/استریم (اختیاری — Enter برای رد شدن)" ""

  local PG_PASS WH_SECRET
  PG_PASS=$(rand 18)
  WH_SECRET=$(rand 24)

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
EOF
  ok ".env ساخته شد (اسرار تصادفی تولید شدند)."

  say ""
  say "${BOLD}خلاصه:${RESET}"
  say "  • ربات با ${BOLD}وبهوکِ داخلی${RESET} بالا می‌آید (از طریق local-bot-api)."
  say "  • سرویس‌ها: local-bot-api · postgres · redis · bot"
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
  update)      git pull --ff-only && ${COMPOSE} up -d --build ;;
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
