#!/usr/bin/env bash
# =============================================================================
# RMT — Registrar Migration Tool
# One-command installer for a fresh Ubuntu VPS.
#
# Usage:   sudo bash install.sh
#    or:   curl -fsSL <url>/scripts/install.sh | sudo bash
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
INSTALL_DIR="${INSTALL_DIR:-/opt/rmt}"
REPO_URL="${REPO_URL:-https://github.com/404-developer-AI/RMT.git}"
REPORT_PATH="/root/rmt-install-report-$(date +%Y%m%d-%H%M%S).txt"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
BOLD=$(tput bold 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)
RED=$(tput setaf 1 2>/dev/null || true)
GREEN=$(tput setaf 2 2>/dev/null || true)
YELLOW=$(tput setaf 3 2>/dev/null || true)
BLUE=$(tput setaf 4 2>/dev/null || true)

info()  { printf "%s==>%s %s\n" "${BLUE}${BOLD}" "${RESET}" "$*"; }
ok()    { printf "%sOK%s  %s\n" "${GREEN}${BOLD}" "${RESET}" "$*"; }
warn()  { printf "%sWARNING%s %s\n" "${YELLOW}${BOLD}" "${RESET}" "$*" >&2; }
die()   { printf "%sERROR%s %s\n" "${RED}${BOLD}" "${RESET}" "$*" >&2; exit 1; }

# All prompts read from /dev/tty so the script also works via `curl | bash`.

ask() {
    # ask "prompt" "default"  →  prints the entered value (or default) to stdout
    local prompt="$1" default="${2:-}" reply
    if [ -n "$default" ]; then
        read -r -p "$prompt [$default]: " reply </dev/tty
    else
        read -r -p "$prompt: " reply </dev/tty
    fi
    printf "%s" "${reply:-$default}"
}

ask_yes_no() {
    # ask_yes_no "prompt" "default (y|n)"  →  returns 0 for yes, 1 for no
    local prompt="$1" default="${2:-n}" reply
    local hint="y/N"; [ "$default" = "y" ] && hint="Y/n"
    read -r -p "$prompt [$hint]: " reply </dev/tty
    reply="${reply:-$default}"
    case "$reply" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

ask_password() {
    # ask_password "prompt"  →  prints entered password; confirms by re-asking
    local prompt="$1" p1 p2
    while :; do
        read -r -s -p "$prompt: " p1 </dev/tty; echo >&2
        [ "${#p1}" -ge 12 ] || { warn "Password must be at least 12 characters."; continue; }
        read -r -s -p "Confirm: " p2 </dev/tty; echo >&2
        [ "$p1" = "$p2" ] || { warn "Passwords did not match, try again."; continue; }
        printf "%s" "$p1"; return 0
    done
}

gen_password() {
    # `head -c 32` closes the pipe once it has 32 bytes, which makes `tr` die
    # with SIGPIPE (exit 141). Under `set -o pipefail` that would abort the
    # whole installer silently, so swallow the pipeline's non-zero status —
    # stdout has already been written by the time `head` exits.
    LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 || true
}

# -----------------------------------------------------------------------------
# Preflight
# -----------------------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || die "Must run as root (try: sudo bash $0)"

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [ "${ID:-}" != "ubuntu" ]; then
        warn "This installer was tested on Ubuntu; detected '${ID:-unknown}'."
        ask_yes_no "Proceed anyway?" "n" || die "Aborted by user"
    fi
else
    warn "/etc/os-release not readable — cannot verify distribution."
fi

if [ -f "$INSTALL_DIR/.env" ]; then
    die "$INSTALL_DIR/.env already exists. Run '$INSTALL_DIR/scripts/update.sh' to update, or remove the directory to reinstall from scratch."
fi

info "Installing prerequisites (curl, git, dnsutils, ca-certificates)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl git dnsutils ca-certificates gnupg lsb-release

# -----------------------------------------------------------------------------
# Prompts
# -----------------------------------------------------------------------------
echo
echo "${BOLD}RMT — Registrar Migration Tool installer${RESET}"
echo "-----------------------------------------"
echo

FQDN=$(ask "Fully-qualified domain name (e.g. rmt.example.com)")
[ -n "$FQDN" ] || die "FQDN cannot be empty"

SSL_ENABLED="false"
LETSENCRYPT_EMAIL=""
if ask_yes_no "Enable HTTPS via Let's Encrypt?" "y"; then
    SSL_ENABLED="true"
    LETSENCRYPT_EMAIL=$(ask "Email for Let's Encrypt (expiry warnings)")
    [ -n "$LETSENCRYPT_EMAIL" ] || die "An email is required for Let's Encrypt"
fi

POSTGRES_USER=$(ask "PostgreSQL username" "rmt")
POSTGRES_DB=$(ask "PostgreSQL database name" "rmt")

if ask_yes_no "Auto-generate a random PostgreSQL password?" "y"; then
    POSTGRES_PASSWORD=$(gen_password)
    PG_PW_MODE="auto-generated"
else
    POSTGRES_PASSWORD=$(ask_password "Enter password for PostgreSQL user '$POSTGRES_USER'")
    PG_PW_MODE="user-provided"
fi

APP_SECRET=$(gen_password)

# -----------------------------------------------------------------------------
# DNS sanity check (soft)
# -----------------------------------------------------------------------------
info "Checking DNS for $FQDN"
resolved_ip=$(dig +short "$FQDN" A | tail -n1 || true)
public_ip=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}' || true)
if [ -n "$resolved_ip" ] && [ -n "$public_ip" ] && [ "$resolved_ip" != "$public_ip" ]; then
    warn "$FQDN resolves to $resolved_ip but this host's public IP is $public_ip."
    warn "If SSL is enabled and DNS does not match, Let's Encrypt will fail."
    ask_yes_no "Continue anyway?" "n" || die "Aborted by user"
elif [ -z "$resolved_ip" ]; then
    warn "Could not resolve $FQDN via DNS."
    ask_yes_no "Continue anyway?" "n" || die "Aborted by user"
else
    ok "DNS for $FQDN resolves to $resolved_ip (matches this host)"
fi

# -----------------------------------------------------------------------------
# Summary / confirmation
# -----------------------------------------------------------------------------
echo
echo "${BOLD}About to install with:${RESET}"
printf "  %-22s %s\n" "FQDN:" "$FQDN"
printf "  %-22s %s\n" "HTTPS:" "$SSL_ENABLED"
[ "$SSL_ENABLED" = "true" ] && printf "  %-22s %s\n" "Let's Encrypt email:" "$LETSENCRYPT_EMAIL"
printf "  %-22s %s\n" "PostgreSQL user:" "$POSTGRES_USER"
printf "  %-22s %s\n" "PostgreSQL db:" "$POSTGRES_DB"
printf "  %-22s %s\n" "PostgreSQL password:" "$PG_PW_MODE (not shown)"
printf "  %-22s %s\n" "Install directory:" "$INSTALL_DIR"
echo
ask_yes_no "Proceed with install?" "y" || die "Aborted by user"

# -----------------------------------------------------------------------------
# Install Docker (if missing)
# -----------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    info "Installing Docker Engine + Compose plugin"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
    arch="$(dpkg --print-architecture)"
    echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ok "Docker installed"
else
    ok "Docker already installed: $(docker --version)"
fi

if ! docker compose version >/dev/null 2>&1; then
    die "'docker compose' plugin not available after install — aborting."
fi

# -----------------------------------------------------------------------------
# Clone repository
# -----------------------------------------------------------------------------
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Repository already present at $INSTALL_DIR — pulling latest"
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning $REPO_URL to $INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# -----------------------------------------------------------------------------
# Write .env
# -----------------------------------------------------------------------------
info "Writing $INSTALL_DIR/.env (chmod 600, root-owned)"
DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
CORS_ORIGINS="http://${FQDN}"
[ "$SSL_ENABLED" = "true" ] && CORS_ORIGINS="https://${FQDN}"

umask 077
cat > "$INSTALL_DIR/.env" <<EOF
# Generated by install.sh on $(date -Iseconds).
# DO NOT COMMIT THIS FILE. It is gitignored.

APP_ENV=production
LOG_LEVEL=INFO

PUBLIC_FQDN=${FQDN}
SSL_ENABLED=${SSL_ENABLED}
LETSENCRYPT_EMAIL=${LETSENCRYPT_EMAIL}

POSTGRES_DB=${POSTGRES_DB}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

DATABASE_URL=${DATABASE_URL}

APP_SECRET=${APP_SECRET}

CORS_ALLOWED_ORIGINS=${CORS_ORIGINS}

# Registrar API credentials (GoDaddy, Combell, …) are stored encrypted in
# PostgreSQL and managed via the settings page in the UI — not in this file.
EOF
chown root:root "$INSTALL_DIR/.env"
chmod 600 "$INSTALL_DIR/.env"
umask 022

# -----------------------------------------------------------------------------
# Obtain Let's Encrypt cert (if SSL enabled)
# -----------------------------------------------------------------------------
if [ "$SSL_ENABLED" = "true" ]; then
    info "Obtaining Let's Encrypt certificate for $FQDN"
    apt-get install -y -qq certbot

    # Ensure port 80 is free for the standalone HTTP-01 challenge.
    systemctl stop nginx 2>/dev/null || true
    (cd "$INSTALL_DIR" && docker compose stop web 2>/dev/null || true)

    if ! certbot certificates 2>/dev/null | grep -q "Domains: $FQDN"; then
        certbot certonly --standalone --non-interactive --agree-tos \
            --email "$LETSENCRYPT_EMAIL" \
            -d "$FQDN"
    else
        ok "Certificate for $FQDN already present — skipping issuance"
    fi

    # Install a deploy-hook so a successful renewal restarts the web container.
    mkdir -p /etc/letsencrypt/renewal-hooks/deploy
    cat > /etc/letsencrypt/renewal-hooks/deploy/rmt-restart-web.sh <<EOF
#!/bin/bash
# Restart the RMT web container after a successful Let's Encrypt renewal.
docker compose -f ${INSTALL_DIR}/docker-compose.yml restart web
EOF
    chmod +x /etc/letsencrypt/renewal-hooks/deploy/rmt-restart-web.sh
    ok "Let's Encrypt certificate installed; auto-renewal configured via certbot.timer"
fi

# -----------------------------------------------------------------------------
# Build and start the stack
# -----------------------------------------------------------------------------
info "Building container images (first build takes a few minutes)"
cd "$INSTALL_DIR"
docker compose build

# Bootstrap the database schema before the backend starts accepting
# requests. Without this, a fresh install hits ProgrammingError on the
# first API call because no tables exist yet. The ``run --rm`` form
# brings up the postgres dependency, applies migrations in a throwaway
# container, and exits — same pattern update.sh uses for upgrades.
info "Applying database migrations (alembic upgrade head)"
docker compose run --rm backend alembic upgrade head

info "Starting the stack"
docker compose up -d

# -----------------------------------------------------------------------------
# Wait for backend health
# -----------------------------------------------------------------------------
info "Waiting for backend to become healthy"
deadline=$(( $(date +%s) + 180 ))
while true; do
    if docker compose exec -T backend curl -fsS http://localhost:8000/api/healthz >/dev/null 2>&1; then
        ok "Backend is healthy"
        break
    fi
    if [ "$(date +%s)" -gt "$deadline" ]; then
        warn "Backend did not become healthy within 3 minutes."
        warn "Check logs with: docker compose -f $INSTALL_DIR/docker-compose.yml logs backend"
        break
    fi
    sleep 3
done

SCHEME="http"
[ "$SSL_ENABLED" = "true" ] && SCHEME="https"

# -----------------------------------------------------------------------------
# Determine public egress IP for the Combell whitelist instruction
# -----------------------------------------------------------------------------
# Combell denies every API request from a non-whitelisted source IP, so the
# operator MUST register this host's egress IP in the Combell control panel
# before the adapter can reach the API. We try two independent echo services
# so a single outage does not block the install.
EGRESS_IP=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null \
           || curl -fsS --max-time 5 https://ifconfig.co 2>/dev/null \
           || true)
EGRESS_IP="${EGRESS_IP:-unknown — run \`curl https://api.ipify.org\` from this host}"

# -----------------------------------------------------------------------------
# Install report
# -----------------------------------------------------------------------------
info "Writing install report to $REPORT_PATH"
umask 077
{
    echo "================================================================="
    echo "  RMT — Registrar Migration Tool — install report"
    echo "  Generated: $(date -Iseconds)"
    echo "  Host:      $(hostname -f 2>/dev/null || hostname)"
    echo "================================================================="
    echo
    echo "Access"
    echo "  URL:                 ${SCHEME}://${FQDN}"
    echo "  FQDN:                ${FQDN}"
    echo "  HTTPS:               ${SSL_ENABLED}"
    [ "$SSL_ENABLED" = "true" ] && echo "  Let's Encrypt email: ${LETSENCRYPT_EMAIL}"
    echo
    echo "PostgreSQL (inside Docker network)"
    echo "  host:                postgres"
    echo "  port:                5432"
    echo "  database:            ${POSTGRES_DB}"
    echo "  username:            ${POSTGRES_USER}"
    echo "  password:            ${POSTGRES_PASSWORD}     [${PG_PW_MODE}]"
    echo
    echo "Application"
    echo "  app secret:          ${APP_SECRET}     [auto-generated]"
    echo
    echo "Paths"
    echo "  install directory:   ${INSTALL_DIR}"
    echo "  environment file:    ${INSTALL_DIR}/.env          (chmod 600)"
    echo "  compose file:        ${INSTALL_DIR}/docker-compose.yml"
    [ "$SSL_ENABLED" = "true" ] && echo "  TLS certificate:     /etc/letsencrypt/live/${FQDN}/"
    echo "  this report:         ${REPORT_PATH}"
    echo
    echo "Common commands"
    echo "  update:              sudo bash ${INSTALL_DIR}/scripts/update.sh"
    echo "  logs (all):          docker compose -f ${INSTALL_DIR}/docker-compose.yml logs -f"
    echo "  logs (backend):      docker compose -f ${INSTALL_DIR}/docker-compose.yml logs -f backend"
    echo "  restart:             docker compose -f ${INSTALL_DIR}/docker-compose.yml restart"
    echo "  stop:                docker compose -f ${INSTALL_DIR}/docker-compose.yml down"
    echo
    echo "================================================================="
    echo "  REQUIRED MANUAL STEP — Combell IP whitelist"
    echo "================================================================="
    echo
    echo "  This VPS's public egress IP is:"
    echo
    echo "      ${EGRESS_IP}"
    echo
    echo "  Combell DENIES every API request from a non-whitelisted source"
    echo "  IP. Before RMT can talk to Combell you MUST:"
    echo
    echo "    1. Sign in at https://my.combell.com"
    echo "    2. Go to: Account → API configuration → IP whitelist"
    echo "    3. Add the IP above and save."
    echo
    echo "  Without this step, every Combell 'Test connection' and every"
    echo "  migration submission will fail with HTTP 401/403."
    echo
    echo "================================================================="
    echo "  SECURITY WARNING"
    echo "================================================================="
    echo
    echo "  This report contains PLAINTEXT SECRETS (PostgreSQL password and"
    echo "  application secret). After you have stored them in a password"
    echo "  manager, securely delete this report with:"
    echo
    echo "      shred -u ${REPORT_PATH}"
    echo
    echo "  (shred overwrites the file before unlinking so the plaintext"
    echo "   cannot be recovered from the disk.)"
    echo
} > "$REPORT_PATH"
chown root:root "$REPORT_PATH"
chmod 600 "$REPORT_PATH"
umask 022

# -----------------------------------------------------------------------------
# Final output
# -----------------------------------------------------------------------------
echo
echo "${GREEN}${BOLD}============================================================${RESET}"
ok "RMT is installed and reachable at ${SCHEME}://${FQDN}"
echo "${GREEN}${BOLD}============================================================${RESET}"
echo
printf "Install report: %s\n" "$REPORT_PATH"
echo
printf "%s${BOLD}⚠ REQUIRED: Combell IP whitelist${RESET}\n" "$YELLOW"
printf "           This VPS's public egress IP is: ${BOLD}%s${RESET}\n" "$EGRESS_IP"
printf "           Add it at Combell → Account → API configuration → IP whitelist\n"
printf "           before any migration will succeed.\n"
echo
printf "%s${BOLD}⚠ WARNING${RESET} — the install report contains %sPLAINTEXT SECRETS%s\n" "$YELLOW" "$BOLD" "$RESET"
printf "           (PostgreSQL password + application secret).\n"
echo
printf "           Store them in a password manager, then delete the report:\n"
echo
printf "               ${BOLD}shred -u %s${RESET}\n" "$REPORT_PATH"
echo
printf "To update RMT later, run:  ${BOLD}sudo bash %s/scripts/update.sh${RESET}\n" "$INSTALL_DIR"
echo
