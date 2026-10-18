#!/usr/bin/env bash
# One command from a fresh clone to the running app: `make start`.
#
# Checks the tools, creates .env, installs the Python and frontend packages, starts FalkorDB,
# builds the synthetic demo company (no keys needed) and then runs the API + frontend.
# Safe to run again: every step skips or repeats harmlessly (the ingest is incremental).
# Ports: FALKORDB_PORT / FALKORDB_BROWSER_PORT come from .env; API_PORT and FE_PORT from make.
set -euo pipefail

cd "$(dirname "$0")/.."
API_PORT="${API_PORT:-8000}"
FE_PORT="${FE_PORT:-5173}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
die() { printf '\n\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }

step "Checking the tools"
missing=()
for tool in docker uv node pnpm; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if ((${#missing[@]})); then
  die "missing: ${missing[*]}. Install them first (macOS: brew install uv node pnpm, plus Docker Desktop). See DEVELOPMENT.md."
fi
docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop (or the Docker daemon) and run make start again."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is missing (the 'docker compose' command)."
echo "docker, uv, node, pnpm: ok"

step "Creating .env"
if [[ -f .env ]]; then
  echo ".env already exists: kept as is"
else
  cp .env.example .env
  echo "Created .env from .env.example. Add ANTHROPIC_API_KEY to it to ask questions."
fi

step "Installing Python packages (uv sync)"
uv sync

step "Installing frontend packages (pnpm install)"
pnpm --dir apps/frontend install --frozen-lockfile

step "Starting FalkorDB"
if ! docker compose up -d --wait; then
  die "FalkorDB did not start. If port 6379 or 3000 is taken (another FalkorDB or Redis), set FALKORDB_PORT / FALKORDB_BROWSER_PORT in .env and run make start again."
fi

step "Building the synthetic demo company (brain_synthetic)"
uv run brain schema synthetic >/dev/null
uv run brain ingest synthetic

if ! grep -qE '^ANTHROPIC_API_KEY=.+' .env && [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  printf '\n\033[1;33mnote:\033[0m ANTHROPIC_API_KEY is empty: the app runs, but Ask and the Keeper'"'"'s agent jobs need it (.env).\n'
fi

for port in "$API_PORT" "$FE_PORT"; do
  if lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    die "port $port is already in use (an earlier make dev?). Stop it, or pick other ports: make start API_PORT=8010 FE_PORT=5180"
  fi
done

step "Starting the app: http://localhost:${FE_PORT} (API on http://127.0.0.1:${API_PORT}); Ctrl+C stops it"
exec make dev API_PORT="$API_PORT" FE_PORT="$FE_PORT"
