#!/usr/bin/env bash
# ── Telabzar · interactive installer ───────────────────────────────────────
# Asks for the settings, writes .env, and brings the stack up.
# Modes: master (this script). Nodes are added later from the admin panel.
#
# Everything this script prints is English on purpose: Persian text does not
# render readably in most server terminals (no RTL shaping, broken joining).
set -euo pipefail

BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; RESET=$'\e[0m'
say()  { printf "%s\n" "$*"; }
ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}!${RESET} %s\n" "$*"; }
die()  { printf "${RED}✗ %s${RESET}\n" "$*" >&2; exit 1; }

rand() { openssl rand -hex "${1:-24}" 2>/dev/null || head -c "${1:-24}" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

# Value of a key from an existing .env (keeps secrets stable on reconfigure)
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
  say "${DIM}Paste the whole text (including the BEGIN/END lines), then type ${RESET}${BOLD}EOF${RESET}${DIM} on a line of its own and press Enter:${RESET}"
  : > "$out"; chmod 600 "$out"
  while IFS= read -r line; do
    [[ "$line" == "EOF" ]] && break
    printf '%s\n' "$line" >> "$out"
  done
  if ! grep -q "BEGIN" "$out"; then
    warn "That does not look like a valid PEM (no BEGIN line found)."
  fi
}

require_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed. Install it first: https://docs.docker.com/engine/install/"
  if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose";
  elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose";
  else die "Docker Compose not found."; fi
  ok "Docker and Compose are ready."
}

banner() {
  cat <<'EOF'

  ┌────────────────────────────────────────────┐
  │        Telabzar — interactive setup        │
  └────────────────────────────────────────────┘
EOF
}

install_master() {
  say ""
  say "${BOLD}Master server configuration${RESET}"
  say "${DIM}Get the Telegram values from @BotFather and my.telegram.org.${RESET}"
  say ""

  ask BOT_TOKEN "Bot token (from @BotFather)"
  [[ "$BOT_TOKEN" == *:* ]] || die "Invalid token format."
  ask TG_API_ID "TG_API_ID (from my.telegram.org)"
  [[ "$TG_API_ID" =~ ^[0-9]+$ ]] || die "TG_API_ID must be a number."
  ask TG_API_HASH "TG_API_HASH (from my.telegram.org)"
  [[ -n "$TG_API_HASH" ]] || die "TG_API_HASH is empty."
  ask ADMIN_IDS "Numeric Telegram ID(s) of the admins (comma-separated)"
  ask DEFAULT_LANG "Default language (fa/en)" "fa"
  ask MAX_FILE_MB "Max size per file (MB)" "2000"

  # ── Domain and TLS for download/stream links (optional) ──
  say ""
  say "${BOLD}Download / stream links${RESET} ${DIM}(optional — lets the bot hand out links to files)${RESET}"
  say "${DIM}Needs a domain behind Cloudflare (proxy on) and an Origin Certificate from the Cloudflare dashboard.${RESET}"
  ask DOMAIN "Domain (e.g. files.example.com — press Enter to skip)" ""

  local PUBLIC_BASE="" TLS_CERT="" TLS_KEY="" GW_PORT="8080"
  if [[ -n "$DOMAIN" ]]; then
    say "${DIM}Use 443 if it is free on this server; otherwise 8443 (Cloudflare proxies both).${RESET}"
    ask GW_PORT "HTTPS port on this server" "8443"
    if [[ "$GW_PORT" == "443" ]]; then PUBLIC_BASE="https://${DOMAIN}"; else PUBLIC_BASE="https://${DOMAIN}:${GW_PORT}"; fi
    mkdir -p certs
    read_pem certs/cert.pem "1) Cloudflare Origin Certificate"
    read_pem certs/key.pem  "2) Origin Private Key"
    TLS_CERT="/certs/cert.pem"; TLS_KEY="/certs/key.pem"
    ok "Domain and certificate configured → ${PUBLIC_BASE}"
  else
    warn "No domain; the \"Link\" button stays disabled until you set one (telabzar reconfigure)."
  fi

  # Keep fixed secrets from an existing .env (the Postgres password is baked
  # into the pg-data volume; regenerating it on reconfigure breaks the DB link).
  local PG_PASS
  PG_PASS=$(env_get POSTGRES_PASSWORD); [[ -n "$PG_PASS" ]] || PG_PASS=$(rand 18)
  # ADMIN_SECRET/NODE_SECRET behave the same: kept if present, generated
  # otherwise. They used to not be written at all and the code silently fell
  # back to BOT_TOKEN — so anyone holding the bot token (every node included)
  # could forge an admin session. Changing ADMIN_SECRET invalidates open
  # sessions and changing NODE_SECRET invalidates issued join tokens; both are
  # short-lived.
  local ADMIN_SECRET NODE_SECRET
  ADMIN_SECRET=$(env_get ADMIN_SECRET); [[ -n "$ADMIN_SECRET" ]] || ADMIN_SECRET=$(rand 32)
  NODE_SECRET=$(env_get NODE_SECRET);   [[ -n "$NODE_SECRET" ]]  || NODE_SECRET=$(rand 32)

  umask 077
  cat > .env <<EOF
# Generated by install.sh — do not edit by hand (re-run: ./install.sh or telabzar reconfigure)
BOT_TOKEN=${BOT_TOKEN}
TG_API_ID=${TG_API_ID}
TG_API_HASH=${TG_API_HASH}
ADMIN_IDS=${ADMIN_IDS}
DEFAULT_LANG=${DEFAULT_LANG}
MAX_FILE_MB=${MAX_FILE_MB}
POSTGRES_USER=telabzar
POSTGRES_PASSWORD=${PG_PASS}
POSTGRES_DB=telabzar
# Generated secrets. Leaving them empty makes the code fall back to BOT_TOKEN,
# and the admin panel deliberately refuses to start with an empty ADMIN_SECRET.
ADMIN_SECRET=${ADMIN_SECRET}
NODE_SECRET=${NODE_SECRET}
# Note: DOMAIN is deliberately not written — it is only an input to this
# script, used to build PUBLIC_BASE and the certificate paths; no code reads it.
PUBLIC_BASE=${PUBLIC_BASE}
GATEWAY_HTTPS_PORT=${GW_PORT}
TLS_CERT=${TLS_CERT}
TLS_KEY=${TLS_KEY}
EOF
  ok ".env written (secrets generated randomly)."

  say ""
  say "${BOLD}Summary:${RESET}"
  say "  • The bot connects to local-bot-api with ${BOLD}long-polling${RESET}."
  say "  • Services: local-bot-api · postgres · redis · bot · worker · download-worker · clamav · gateway · admin · bgutil-pot-provider"
  if [[ -n "$DOMAIN" ]]; then
    say "  • Links/streams on ${BOLD}${PUBLIC_BASE}${RESET} (port ${GW_PORT})."
  fi
  local CONFIRM
  ask CONFIRM "Start the install and bring the stack up? (y/n)" "y"
  [[ "$CONFIRM" =~ ^[Yy]$ ]] || { warn "Cancelled. .env was written; run 'telabzar up' later."; exit 0; }

  say ""
  say "Building and starting… (the first build takes several minutes)"
  $COMPOSE up -d --build

  install_cli

  # ── Distributed nodes (optional) — automatic WireGuard / master infra setup ──
  say ""
  say "${BOLD}Distributed nodes${RESET} ${DIM}(optional — extra download/processing/stream servers)${RESET}"
  say "${DIM}If you answer yes, WireGuard and the required infrastructure are set up on this master automatically;${RESET}"
  say "${DIM}you then add nodes from the admin panel → Nodes. Without nodes everything runs on the master.${RESET}"
  local WANT_NODES
  ask WANT_NODES "Set up node infrastructure now? (y/n)" "n"
  if [[ "$WANT_NODES" =~ ^[Yy]$ ]]; then
    if [[ $EUID -eq 0 ]] || sudo -n true 2>/dev/null; then
      local SUDO=""; [[ $EUID -eq 0 ]] || SUDO="sudo"
      $SUDO bash "$(pwd)/node/master-setup.sh" || warn "Node setup failed; run 'telabzar nodes-enable' later."
    else
      warn "Node setup needs root; run 'sudo telabzar nodes-enable' later."
    fi
  fi

  say ""
  ok "Stack is up. The bot connects with long-polling (no webhook needed)."
  say "${DIM}Status:${RESET}  telabzar status    ${DIM}|${RESET}   ${DIM}Logs:${RESET}  telabzar logs <service>"
  say "${DIM}ClamAV downloads its signature database on first start; it is ready after a few minutes.${RESET}"
  if [[ -n "$DOMAIN" ]]; then
    say "${DIM}Admin panel:${RESET}  https://${DOMAIN}:2083"
  else
    say "${DIM}Admin panel:${RESET}  http://<server-ip>:2083"
  fi
  say "${DIM}Now send /start to the bot in Telegram (do this before logging into the panel —${RESET}"
  say "${DIM}the panel's login code is sent to you by the bot).${RESET}"
}

install_cli() {
  # Install a small helper CLI for day-to-day management
  local target="/usr/local/bin/telabzar" here; here=$(pwd)
  local COMPOSE="${COMPOSE:-docker compose}"   # when called headless and not set
  if [[ -w "$(dirname "$target")" ]] || sudo -n true 2>/dev/null; then
    local SUDO=""; [[ -w "$(dirname "$target")" ]] || SUDO="sudo"
    # Atomic write (temp, then mv) so that even if `telabzar update` rewrites
    # this file while running, the running process (old inode) does not break.
    $SUDO tee "$target.tmp" >/dev/null <<EOF
#!/usr/bin/env bash
cd "$here" || exit 1
# If nodes are enabled, pass the WG overlay to compose too (publish services on the WG IP)
FILES="-f docker-compose.yml"
[ -f "$here/.nodes-enabled" ] && FILES="\$FILES -f docker-compose.nodes.yml"
case "\${1:-}" in
  up)          ${COMPOSE} \$FILES up -d --build ;;
  down)        ${COMPOSE} \$FILES down ;;
  status|ps)   ${COMPOSE} \$FILES ps ;;
  logs)        ${COMPOSE} \$FILES logs --tail=200 \${2:-} ;;
  logf)        ${COMPOSE} \$FILES logs -f --tail=100 \${2:-} ;;
  # Update: pull the code, bring the stack up, then rewrite this CLI so new
  # subcommands (and the overlay logic) land on disk — otherwise it goes stale.
  update)      git fetch origin main && git checkout -f -B main origin/main \\
                 && ${COMPOSE} \$FILES up -d --build \\
                 && bash "$here/install.sh" refresh-cli ;;
  nodes-enable) sudo bash "$here/node/master-setup.sh" \${2:-} ;;   # automatic WG/infra setup
  wg-sync)     sudo /usr/local/sbin/telabzar-wg-sync ;;             # manual peer sync
  reconfigure) exec bash "$here/install.sh" ;;
  *) echo "Usage: telabzar {up|down|status|logs|logf|update|nodes-enable|wg-sync|reconfigure}" ;;
esac
EOF
    $SUDO chmod +x "$target.tmp"
    $SUDO mv -f "$target.tmp" "$target"
    ok "CLI installed: ${BOLD}telabzar${RESET}"
  else
    warn "No write access to /usr/local/bin; the CLI was not installed (optional)."
  fi
}

install_node() {
  say ""
  warn "Nodes are not installed from this script."
  say "${DIM}Install the master first, then add nodes from the admin panel → Nodes;${RESET}"
  say "${DIM}it gives you a one-line install command to run on the node server.${RESET}"
  exit 0
}

main() {
  # Headless mode: only rewrite the CLI (no prompts). `telabzar update` calls
  # this so new subcommands (nodes-enable/wg-sync/overlay) land on disk after
  # every update.
  case "${1:-}" in
    refresh-cli|cli) require_docker >/dev/null 2>&1 || true; install_cli; exit 0 ;;
  esac
  banner
  require_docker
  say ""
  say "What is this server?"
  say "  ${BOLD}1${RESET}) master  ${DIM}(runs everything)${RESET}"
  say "  ${BOLD}2${RESET}) node    ${DIM}(worker — added from the admin panel)${RESET}"
  local MODE
  ask MODE "Choice" "1"
  case "$MODE" in
    1|master) install_master ;;
    2|node)   install_node ;;
    *) die "Invalid choice." ;;
  esac
}

main "$@"
