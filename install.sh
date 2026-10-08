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

# Bare host name from whatever was typed: lowercase, no scheme, no trailing slash or dot.
clean_domain() {
  local d
  d=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
  d=${d#http://}; d=${d#https://}; d=${d%/}; d=${d%.}
  printf '%s' "$d"
}

valid_domain() { # letters/digits/hyphens, at least two labels, alphabetic TLD
  [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$ ]] && (( ${#1} <= 253 ))
}

# Every pipeline below that may legitimately fail ends in `|| true`. Under
# `set -euo pipefail` a failing pipeline inside an assignment ends the whole
# script with no message — and "the domain does not resolve yet" is the common
# case here, not an edge case (getent exits 2).
public_ip() { # the same detection node/master-setup.sh uses
  local ip
  ip=$(curl -fsS4 --max-time 8 https://api.ipify.org 2>/dev/null || true)
  [[ -n "$ip" ]] || ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' || true)
  printf '%s' "$ip"
}

# Where the domain's records point, compared with this server. Only warns: DNS
# may still be propagating, and Caddy retries on its own once it points here.
# Sets DNS_STATE (ok | missing | elsewhere | unknown) for issue_panel_cert.
DNS_STATE=unknown
check_dns() { # check_dns <domain>
  local d=$1 me ips v6
  me=$(public_ip)
  ips=$(getent ahostsv4 "$d" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' || true)
  if [[ -z "$ips" ]]; then
    DNS_STATE=missing
    # No apostrophe inside ${...:-…}: bash then hunts for a closing quote and the
    # whole script stops parsing (measured — `bash -n` fails at a later `done`).
    warn "${d} does not resolve yet. Create an A record pointing to ${me:-the IP of this server}."
    say  "${DIM}The certificate is issued automatically as soon as it points here.${RESET}"
  elif [[ -z "$me" ]]; then
    DNS_STATE=unknown
    warn "${d} points to ${ips% }; the IP of this server could not be detected to compare."
  elif [[ " $ips" == *" $me "* ]]; then
    DNS_STATE=ok
    ok "${d} points to this server (${me})."
  else
    DNS_STATE=elsewhere
    warn "${d} points to ${ips% } but this server is ${me}."
    say  "${DIM}Fix the A record. On Cloudflare, set the record to \"DNS only\" (grey cloud): the automatic${RESET}"
    say  "${DIM}certificate needs the request to reach this server directly.${RESET}"
  fi
  # Let's Encrypt validates over IPv6 first when an AAAA record exists, so a stale
  # AAAA fails the certificate even with a perfect A record. (`ahostsv6` also lists
  # the A records as ::ffff:… — those are not AAAA records.)
  v6=$(getent ahostsv6 "$d" 2>/dev/null | awk '{print $1}' | grep -v '^::ffff:' | sort -u | tr '\n' ' ' || true)
  if [[ -n "$v6" ]]; then
    warn "${d} also has an IPv6 (AAAA) record: ${v6% }"
    say  "${DIM}Let's Encrypt tries IPv6 first: that address must reach this server too, or delete the AAAA record.${RESET}"
  fi
}

# Caddy needs ports 80 (certificate challenge, redirect) and 443. Another web
# server on either makes it crash-loop and the panel unreachable over HTTPS.
check_ports() {
  local p who busy=0
  command -v ss >/dev/null 2>&1 || return 0
  # A reconfigure: our own caddy already holds both ports. Asked of compose rather
  # than read from `ss -p`, which shows no process names unless run as root.
  [[ -n "$($COMPOSE ps -q caddy 2>/dev/null || true)" ]] && return 0
  for p in 80 443; do
    who=$(ss -Hltnp "sport = :$p" 2>/dev/null | grep -v docker-proxy || true)
    if [[ -n "$who" ]]; then
      warn "Port $p is already in use: $(printf '%s' "$who" | head -n1 | awk '{print $NF}')"
      busy=1
    fi
  done
  if (( busy )); then
    say "${DIM}Stop that service (e.g. systemctl disable --now nginx) — the automatic HTTPS needs 80 and 443.${RESET}"
    local GO
    ask GO "Continue anyway? (y/n)" "n"
    [[ "$GO" =~ ^[Yy]$ ]] || die "Cancelled. Free ports 80/443 and run the installer again."
  fi
}

# Get the panel certificate now, so the installer can say whether HTTPS works
# instead of leaving it to the first visit. One attempt only: Let's Encrypt
# allows 5 failed validations per name per hour, and a name that points
# elsewhere would only spend them.
issue_panel_cert() { # issue_panel_cert <domain>
  local d=$1 port i
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl is not installed; open https://${d} once to get the certificate."
    return 0
  fi
  if [[ "$DNS_STATE" == missing || "$DNS_STATE" == elsewhere ]]; then
    warn "Not requesting the certificate yet: ${d} does not point to this server."
    say  "${DIM}Once the A record is fixed, opening https://${d} gets it automatically.${RESET}"
    return 0
  fi
  port=$(env_get ADMIN_HTTPS_PORT); port=${port:-2083}
  # Caddy asks the panel (/tls/ask) before every certificate, so wait for it.
  say "Waiting for the admin panel to start…"
  for i in $(seq 1 30); do
    curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:${port}/healthz" 2>/dev/null && break
    sleep 3
  done
  say "Getting the HTTPS certificate for ${d} from Let's Encrypt…"
  # --resolve: talk to the local Caddy whatever this server's own DNS says;
  # Let's Encrypt still validates through the public A record.
  if curl -fsS -o /dev/null --max-time 150 --resolve "${d}:443:127.0.0.1" "https://${d}/healthz" 2>/dev/null; then
    ok "HTTPS works: https://${d} (the certificate renews automatically)."
  else
    warn "No certificate yet. Check that the A record points here and ports 80/443 are open;"
    say  "${DIM}details: telabzar logs caddy. It is retried automatically on the next visit to https://${d}.${RESET}"
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

  # ── Admin panel domain: HTTPS with an automatic certificate (Caddy + Let's Encrypt) ──
  say ""
  say "${BOLD}Admin panel domain${RESET} ${DIM}(recommended — HTTPS with a certificate that is issued and renewed automatically)${RESET}"
  say "${DIM}Create an A record for it pointing to this server first. On Cloudflare use \"DNS only\" (grey cloud).${RESET}"
  say "${DIM}Download/stream links get their own domain later, in the admin panel (Settings), also with an automatic certificate.${RESET}"
  local PANEL_DOMAIN="" ADMIN_BASE="" ADMIN_BIND="0.0.0.0" OLD_DOMAIN
  OLD_DOMAIN=$(env_get PANEL_DOMAIN)
  while true; do
    if [[ -n "$OLD_DOMAIN" ]]; then   # a reconfigure: Enter keeps the domain, so removing needs its own answer
      ask PANEL_DOMAIN "Panel domain (Enter keeps it, - removes it)" "$OLD_DOMAIN"
    else
      ask PANEL_DOMAIN "Panel domain (e.g. panel.example.com — press Enter to skip)"
    fi
    [[ "$PANEL_DOMAIN" == "-" ]] && PANEL_DOMAIN=""
    PANEL_DOMAIN=$(clean_domain "$PANEL_DOMAIN")
    [[ -z "$PANEL_DOMAIN" ]] && break
    valid_domain "$PANEL_DOMAIN" && break
    warn "\"${PANEL_DOMAIN}\" is not a valid domain name. Type just the name, e.g. panel.example.com."
  done
  if [[ -n "$PANEL_DOMAIN" ]]; then
    ADMIN_BASE="https://${PANEL_DOMAIN}"
    # The plain-HTTP port 2083 then stays on localhost: an SSH tunnel still reaches it,
    # the internet does not (login codes and session cookies never travel unencrypted).
    ADMIN_BIND="127.0.0.1"
    check_dns "$PANEL_DOMAIN"
    check_ports
    ok "Panel → ${ADMIN_BASE}"
  else
    warn "No domain: the panel is served on plain HTTP at port 2083 (http://<server-ip>:2083)."
    say  "${DIM}You can add a domain any time: telabzar reconfigure${RESET}"
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
# HTTPS: Caddy serves the panel on PANEL_DOMAIN and gets its certificate itself.
# The download/stream link domain is a panel setting (link_domain), not this file.
PANEL_DOMAIN=${PANEL_DOMAIN}
ADMIN_BASE=${ADMIN_BASE}
# Direct plain-HTTP ports (panel 2083, gateway 8443): 127.0.0.1 = this server only.
ADMIN_BIND=${ADMIN_BIND}
GATEWAY_BIND=127.0.0.1
EOF
  ok ".env written (secrets generated randomly)."

  say ""
  say "${BOLD}Summary:${RESET}"
  say "  • The bot connects to local-bot-api with ${BOLD}long-polling${RESET}."
  say "  • Services: caddy · local-bot-api · tg-janitor · postgres · redis · bot · worker · download-worker · clamav · gateway · admin · bgutil-pot-provider"
  if [[ -n "$PANEL_DOMAIN" ]]; then
    say "  • Admin panel on ${BOLD}${ADMIN_BASE}${RESET} (certificate: automatic, Let's Encrypt)."
  fi
  local CONFIRM
  ask CONFIRM "Start the install and bring the stack up? (y/n)" "y"
  [[ "$CONFIRM" =~ ^[Yy]$ ]] || { warn "Cancelled. .env was written; run 'telabzar up' later."; exit 0; }

  say ""
  say "Building and starting… (the first build takes several minutes)"
  $COMPOSE up -d --build

  install_cli
  [[ -n "$PANEL_DOMAIN" ]] && issue_panel_cert "$PANEL_DOMAIN"

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
  if [[ -n "$PANEL_DOMAIN" ]]; then
    say "${DIM}Admin panel:${RESET}  ${ADMIN_BASE}"
    say "${DIM}If it does not load, check the A record and 'telabzar logs caddy'; meanwhile an SSH tunnel${RESET}"
    say "${DIM}reaches the panel:  ssh -L 2083:127.0.0.1:2083 root@<server-ip>   then open http://localhost:2083${RESET}"
  else
    say "${DIM}Admin panel:${RESET}  http://<server-ip>:2083"
  fi
  say "${DIM}Download/stream links: admin panel → Settings → link domain (e.g. dl.example.com, its own A record).${RESET}"
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

# Tests source this file to call the functions above one by one; they set this
# variable so that sourcing defines everything without starting the installer.
[[ -n "${TELABZAR_INSTALL_LIB:-}" ]] || main "$@"
