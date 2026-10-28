#!/usr/bin/env bash
# One-command local install (FR-SETUP-09, ADR-0071): writes .env with fresh secrets, starts the stack on
# 127.0.0.1 and waits until it is healthy. Then open the printed address to create the first accounts.
#
#   bash install.sh                                   from a clone of the repository
#   REPO_URL=<git url> bash install.sh                clones first (INSTALL_DIR, default ./intake)
#
# Optional environment: WEB_PORT (8080), APP_PORT (8001), MEETING_GATEWAY_PORT (8002), COMPOSE_PROJECT_NAME.
# Secrets are written to .env only and never printed.
set -euo pipefail

say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker is not installed. Install Docker Desktop or Docker Engine first."
docker compose version >/dev/null 2>&1 || die "'docker compose' is not available. Install the Docker Compose plugin."
docker info >/dev/null 2>&1 || die "the Docker daemon is not running. Start Docker and run this again."

here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
if [ -f "$here/docker-compose.yml" ] && [ -f "$here/.env.example" ]; then
  cd "$here"
elif [ -n "${REPO_URL:-}" ]; then
  command -v git >/dev/null 2>&1 || die "git is required to clone ${REPO_URL}."
  target="${INSTALL_DIR:-intake}"
  [ -e "$target" ] && die "$target already exists. Remove it or set INSTALL_DIR."
  git clone --depth 1 "$REPO_URL" "$target"
  cd "$target"
else
  die "run this from the repository folder, or set REPO_URL to clone it."
fi

[ -e .env ] && die ".env already exists, so this looks like an installed copy. Delete .env only if you want a new install (it holds your secrets; back it up first)."

secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex "$1"; else od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'; fi
}

# Replace KEY=... in .env, or append it when the file has no such line. Values go through the environment so
# characters such as & or / are never interpreted.
set_env() {
  KEY="$1" VAL="$2" awk '
    BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VAL"]; done = 0 }
    index($0, k "=") == 1 { print k "=" v; done = 1; next }
    { print }
    END { if (!done) print k "=" v }
  ' .env >.env.tmp && mv .env.tmp .env
}

umask 077
cp .env.example .env

web_port="${WEB_PORT:-8080}"
app_port="${APP_PORT:-8001}"
pg="$(secret 24)"
redis="$(secret 24)"

set_env SECRET_KEY "$(secret 32)"
set_env POSTGRES_PASSWORD "$pg"
set_env REDIS_PASSWORD "$redis"
set_env DATABASE_URL "postgresql+psycopg://intake:${pg}@postgres:5432/intake"
set_env REDIS_URL "redis://:${redis}@redis:6379/0"
set_env CELERY_BROKER_URL "redis://:${redis}@redis:6379/1"
set_env SEAWEEDFS_S3_ACCESS_KEY "intake$(secret 8)"
set_env SEAWEEDFS_S3_SECRET_KEY "$(secret 24)"
set_env BACKUP_PASSPHRASE "$(secret 16)"
set_env CTO_INITIAL_PASSWORD "$(secret 16)"
set_env PROJECT_OWNER_INITIAL_PASSWORD ""
set_env FIRST_RUN_WIZARD true
set_env WEB_BIND_ADDRESS 127.0.0.1
set_env APP_BIND_ADDRESS 127.0.0.1
set_env WEB_PORT "$web_port"
set_env APP_PORT "$app_port"
set_env APP_PUBLIC_URL "http://127.0.0.1:${web_port}"
[ -n "${COMPOSE_PROJECT_NAME:-}" ] && set_env COMPOSE_PROJECT_NAME "$COMPOSE_PROJECT_NAME"
[ -n "${MEETING_GATEWAY_PORT:-}" ] && set_env MEETING_GATEWAY_PORT "$MEETING_GATEWAY_PORT"
chmod 600 .env
say "Wrote .env with new secrets (not shown)."

say "Building and starting the stack. The first run takes a few minutes."
docker compose up -d --build

say "Waiting for the app to be ready..."
ready=0
for _ in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:${web_port}/api/v1/health/ready" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[ "$ready" -eq 1 ] || die "the app did not become ready in 4 minutes. Check: docker compose ps  and  docker compose logs api"
curl -fsS "http://127.0.0.1:${web_port}/web-health" >/dev/null 2>&1 || die "the web container is not answering. Check: docker compose logs web"

say ""
say "Intake is running. Open this address in your browser and create the first accounts:"
say ""
say "    http://127.0.0.1:${web_port}/"
say ""
say "Before you continue:"
say "  - Back up the .env file in this folder somewhere safe. Changing or losing SECRET_KEY makes saved AI keys unreadable."
say "  - Until you create the accounts, the first visitor becomes the CTO. This install only listens on 127.0.0.1;"
say "    do not expose the port to a network before you have finished the setup page."
say "  - You will need an API key for an OpenAI-compatible AI provider on the setup page."
