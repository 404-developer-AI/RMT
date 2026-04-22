#!/usr/bin/env bash
# =============================================================================
# RMT — one-command update.
# Usage: sudo bash /opt/rmt/scripts/update.sh
# =============================================================================

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/rmt}"

BOLD=$(tput bold 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)
RED=$(tput setaf 1 2>/dev/null || true)
GREEN=$(tput setaf 2 2>/dev/null || true)
BLUE=$(tput setaf 4 2>/dev/null || true)

info()  { printf "%s==>%s %s\n" "${BLUE}${BOLD}" "${RESET}" "$*"; }
ok()    { printf "%sOK%s  %s\n" "${GREEN}${BOLD}" "${RESET}" "$*"; }
die()   { printf "%sERROR%s %s\n" "${RED}${BOLD}" "${RESET}" "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Must run as root (try: sudo bash $0)"
[ -d "$INSTALL_DIR/.git" ] || die "$INSTALL_DIR is not a RMT checkout — run install.sh first"
[ -f "$INSTALL_DIR/.env" ] || die "$INSTALL_DIR/.env missing — run install.sh first"

cd "$INSTALL_DIR"

# Refuse if there are local changes — we would overwrite them.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo
    git status --short
    echo
    die "$INSTALL_DIR has uncommitted local changes. Resolve them before updating."
fi

get_running_version() {
    docker compose exec -T backend python -c \
        'from app import __version__; print(__version__)' 2>/dev/null || echo "unknown"
}

previous_version=$(get_running_version)
info "Previous version: $previous_version"

info "Pulling latest from git"
git pull --ff-only

info "Rebuilding container images"
docker compose build

info "Running database migrations (alembic upgrade head)"
docker compose run --rm backend alembic upgrade head

info "Starting updated stack"
docker compose up -d

info "Waiting for backend to report healthy"
deadline=$(( $(date +%s) + 120 ))
while true; do
    if docker compose exec -T backend curl -fsS http://localhost:8000/api/healthz >/dev/null 2>&1; then
        break
    fi
    if [ "$(date +%s)" -gt "$deadline" ]; then
        die "Backend did not become healthy within 2 minutes — check 'docker compose logs backend'"
    fi
    sleep 3
done

new_version=$(get_running_version)
ok  "Updated successfully: ${previous_version} → ${new_version}"
echo
printf "View live logs with:   docker compose -f %s/docker-compose.yml logs -f\n" "$INSTALL_DIR"
