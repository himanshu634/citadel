#!/usr/bin/env bash
# `make start`: one command from a fresh clone to the running app.
#
# 1. Checks everything first: tools and versions, .env, ports, disk. Every problem is listed at
#    once with its fix, and nothing is installed or started until all of them pass.
# 2. Installs and prepares quietly: Python and frontend packages, FalkorDB, the synthetic demo
#    company. Each step writes its output to data/logs/start/; a failed step shows a short reason
#    and the last lines of its log, never a wall of output.
# 3. Starts the API and the app in the background, waits until both answer, then prints the URLs.
#    Their logs go to data/logs/start/api.log and frontend.log. Ctrl+C stops both.
#
# Safe to run again: every step skips or repeats harmlessly (the ingest is incremental).
# Written for the bash 3.2 that macOS ships (no associative arrays, no `wait -n`).
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
API_PORT="${API_PORT:-8000}"
FE_PORT="${FE_PORT:-5173}"
LOG_DIR="data/logs/start"
WORK="$(mktemp -d)"
ERRORS="$WORK/errors"
WARNINGS="$WORK/warnings"
: >"$ERRORS"
: >"$WARNINGS"

if [ -t 1 ]; then
  BOLD=$'\033[1m' RED=$'\033[31m' GREEN=$'\033[32m' YELLOW=$'\033[33m' CYAN=$'\033[36m'
  DIM=$'\033[2m' RESET=$'\033[0m' CLEAR=$'\r\033[K'
else
  BOLD="" RED="" GREEN="" YELLOW="" CYAN="" DIM="" RESET="" CLEAR=$'\n'
fi

heading() { printf '\n%s%s%s\n' "$BOLD$CYAN" "$1" "$RESET"; }
# problem "what is wrong" "how to fix it": blocks the start.
problem() { printf '%s\n%s\n' "$1" "$2" >>"$ERRORS"; }
# notice "what to know" "what it affects": shown, but the start goes on.
notice() { printf '%s\n%s\n' "$1" "$2" >>"$WARNINGS"; }

# --- Reading settings ---------------------------------------------------------------------------

# The value of KEY in .env (last one wins), with quotes and a trailing " # comment" removed.
env_file_value() {
  [ -f .env ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" .env | tail -n 1 |
    sed -E -e 's/^[[:space:]]+//' -e 's/[[:space:]]+#.*$//' -e 's/[[:space:]]+$//' \
      -e 's/^"(.*)"$/\1/' -e "s/^'(.*)'$/\\1/"
}

# The value the app will use: an exported variable wins over .env (as in brain/config.py),
# then the default given as $2.
setting() {
  local key=$1 default=${2-} value
  if [ -n "${!key+set}" ]; then
    printf '%s' "${!key}"
    return
  fi
  value=$(env_file_value "$key")
  if [ -n "$value" ]; then printf '%s' "$value"; else printf '%s' "$default"; fi
}

is_port() { case $1 in '' | *[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }

# version_at_least "20.19.1" 20 19: true when the version is 20.19 or newer.
version_at_least() {
  local major minor
  major=$(printf '%s' "$1" | cut -d. -f1)
  minor=$(printf '%s' "$1" | cut -d. -f2)
  case "$major$minor" in '' | *[!0-9]*) return 1 ;; esac
  [ "$major" -gt "$2" ] || { [ "$major" -eq "$2" ] && [ "$minor" -ge "$3" ]; }
}

port_busy() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
  fi
}

# =================================================================================================
heading "Checking your setup (nothing is installed or started until every check passes)"

# --- Tools --------------------------------------------------------------------------------------
tool_hint() {
  case $1 in
    docker) echo "Install Docker Desktop: https://docs.docker.com/get-docker/" ;;
    uv) echo "Install uv: brew install uv  (or: curl -LsSf https://astral.sh/uv/install.sh | sh)" ;;
    node) echo "Install Node.js 22 LTS: brew install node@22  (or https://nodejs.org)" ;;
    pnpm) echo "Install pnpm: brew install pnpm  (or: corepack enable pnpm)" ;;
    *) echo "Install it: brew install $1  (or your system's package manager)" ;;
  esac
}

FALKORDB_HOST=$(setting FALKORDB_HOST localhost)
case $FALKORDB_HOST in localhost | 127.0.0.1 | ::1 | "") LOCAL_DB=1 ;; *) LOCAL_DB=0 ;; esac

for tool in git curl uv node pnpm; do
  command -v "$tool" >/dev/null 2>&1 || problem "$tool is not installed." "$(tool_hint "$tool")"
done
if [ "$LOCAL_DB" = 1 ]; then
  if ! command -v docker >/dev/null 2>&1; then
    problem "docker is not installed (it runs FalkorDB)." "$(tool_hint docker)"
  elif ! docker info >/dev/null 2>&1; then
    problem "Docker is installed but not running." "Start Docker Desktop (or the Docker daemon), wait until it says it is running, then run make start again."
  elif ! docker compose version >/dev/null 2>&1; then
    problem "Docker Compose v2 (the 'docker compose' command) is missing." "Update Docker Desktop, or install the compose plugin: https://docs.docker.com/compose/install/"
  fi
fi
if command -v node >/dev/null 2>&1; then
  NODE_VERSION=$(node -p 'process.versions.node' 2>/dev/null)
  version_at_least "$NODE_VERSION" 20 19 ||
    problem "Node.js $NODE_VERSION is too old: the frontend needs 20.19 or newer." "$(tool_hint node)"
fi
if command -v pnpm >/dev/null 2>&1; then
  PNPM_VERSION=$(pnpm --version 2>/dev/null)
  version_at_least "$PNPM_VERSION" 9 0 ||
    problem "pnpm $PNPM_VERSION is too old: version 9 or newer is needed." "Update it: brew upgrade pnpm  (or: corepack enable pnpm)"
fi

# --- .env ---------------------------------------------------------------------------------------
if [ ! -f .env ]; then
  if cp .env.example .env 2>/dev/null; then
    notice "Created .env from .env.example." "Edit it to add keys (ANTHROPIC_API_KEY for Ask); the defaults run the demo."
  else
    problem "There is no .env and .env.example could not be copied." "Run this from the repo folder, or copy .env.example to .env yourself."
  fi
fi

if [ -f .env ]; then
  missing_keys=""
  for key in $(sed -n 's/^\([A-Z][A-Z0-9_]*\)=.*/\1/p' .env.example); do
    grep -q "^[[:space:]]*$key[[:space:]]*=" .env || missing_keys="$missing_keys $key"
  done
  [ -n "$missing_keys" ] &&
    notice "Not in your .env:$missing_keys." "Their defaults apply. Copy the lines from .env.example to change them."

  for key in FALKORDB_PORT FALKORDB_BROWSER_PORT; do
    value=$(setting "$key" "$([ $key = FALKORDB_PORT ] && echo 6379 || echo 3000)")
    is_port "$value" || problem "$key=$value in .env is not a port number." "Set it to a number from 1 to 65535."
  done

  tls=$(setting FALKORDB_TLS false)
  case $tls in true | false | True | False | 1 | 0 | "") ;; *)
    problem "FALKORDB_TLS=$tls in .env must be true or false." "Use false for the local Docker FalkorDB, true for FalkorDB Cloud with TLS." ;;
  esac

  provider=$(setting EMBEDDING_PROVIDER fastembed)
  model=$(setting EMBEDDING_MODEL "")
  dim=$(setting EMBEDDING_DIM 768)
  case $provider in
    fastembed | none) ;;
    gemini)
      [ -n "$(setting GEMINI_API_KEY "")" ] ||
        problem "EMBEDDING_PROVIDER=gemini needs GEMINI_API_KEY in .env." "Add a key from aistudio.google.com, or set EMBEDDING_PROVIDER=fastembed (local, no key)."
      ;;
    *) problem "EMBEDDING_PROVIDER=$provider in .env is not known." "Use fastembed (local model, no key), gemini (needs GEMINI_API_KEY) or none (semantic search off)." ;;
  esac
  case $dim in
    '' | *[!0-9]*) problem "EMBEDDING_DIM=$dim in .env is not a number." "Set it to 768 (the default model's size)." ;;
    *)
      if [ "$provider" = fastembed ] && [ -z "$model" ] && [ "$dim" != 768 ]; then
        problem "EMBEDDING_DIM=$dim does not match the default local model, which makes 768 values." "Set EMBEDDING_DIM=768, or set EMBEDDING_MODEL to a model of that size."
      fi
      ;;
  esac

  effort=$(setting ANTHROPIC_EFFORT medium)
  case $effort in low | medium | high | xhigh | max) ;; *)
    problem "ANTHROPIC_EFFORT=$effort in .env is not known." "Use one of: low, medium, high, xhigh, max." ;;
  esac
  anthropic_model=$(setting ANTHROPIC_MODEL claude-sonnet-5-5)
  case $anthropic_model in claude-*) ;; *)
    problem "ANTHROPIC_MODEL=$anthropic_model in .env is not a Claude model id." "Use claude-sonnet-5-5 (default), claude-haiku-5-5 or claude-opus-5-5." ;;
  esac

  anthropic_key=$(setting ANTHROPIC_API_KEY "")
  if [ -z "$anthropic_key" ]; then
    notice "ANTHROPIC_API_KEY is empty." "The app, the graph and the demo company work; asking questions and the Keeper's agent jobs need the key (console.anthropic.com)."
  else
    case $anthropic_key in sk-ant-*) ;; *)
      notice "ANTHROPIC_API_KEY does not start with sk-ant-." "Check that it is an Anthropic API key; questions fail with a wrong one." ;;
    esac
  fi
  if [ -z "$(setting GITHUB_TOKEN "")" ] && ! gh auth token >/dev/null 2>&1; then
    notice "No GitHub token (GITHUB_TOKEN is empty and gh is not signed in)." "The demo company needs none; building a brain from a GitHub repo does."
  fi
fi

# --- Ports --------------------------------------------------------------------------------------
for pair in "API_PORT:$API_PORT" "FE_PORT:$FE_PORT"; do
  name=${pair%%:*} port=${pair#*:}
  if ! is_port "$port"; then
    problem "$name=$port is not a port number." "Use a number from 1 to 65535: make start $name=8010"
  elif port_busy "$port"; then
    problem "Port $port ($name, the $([ $name = API_PORT ] && echo API || echo app)) is already in use, maybe by an earlier make dev or make start." "Stop that program, or use another port: make start $name=$([ $name = API_PORT ] && echo 8010 || echo 5180)"
  fi
done

if [ "$LOCAL_DB" = 1 ] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ours=$(docker compose ps --status running --services 2>/dev/null | grep -x falkordb)
  if [ -z "$ours" ]; then
    for key in FALKORDB_PORT FALKORDB_BROWSER_PORT; do
      port=$(setting "$key" "$([ $key = FALKORDB_PORT ] && echo 6379 || echo 3000)")
      if is_port "$port" && port_busy "$port"; then
        problem "Port $port ($key) is already in use by another program (another FalkorDB or Redis?)." "Stop it, or set $key to a free port in .env (for example $((port + 1)))."
      fi
    done
  fi
fi

# --- Disk ---------------------------------------------------------------------------------------
free_kb=$(df -Pk . 2>/dev/null | awk 'NR==2 {print $4}')
case $free_kb in '' | *[!0-9]*) ;; *)
  if [ "$free_kb" -lt 1048576 ]; then
    problem "Only $((free_kb / 1024)) MB of disk space is free." "Free at least 2 GB: the packages, the embedding model and FalkorDB need it."
  elif [ "$free_kb" -lt 2097152 ]; then
    notice "Only $((free_kb / 1024)) MB of disk space is free." "The first run needs about 1.5 GB (packages, embedding model, FalkorDB)."
  fi
  ;;
esac

# --- Report -------------------------------------------------------------------------------------
print_list() { # file colour mark
  while IFS= read -r what && IFS= read -r fix; do
    printf '  %s%s%s %s\n      %s%s%s\n' "$2" "$3" "$RESET" "$what" "$DIM" "$fix" "$RESET"
  done <"$1"
}
error_count=$(($(wc -l <"$ERRORS") / 2))
if [ -s "$WARNINGS" ]; then print_list "$WARNINGS" "$YELLOW" "!"; fi
if [ "$error_count" -gt 0 ]; then
  print_list "$ERRORS" "$RED" "✗"
  printf '\n%s%s problem(s) to fix first.%s Nothing was installed or started. Fix them and run make start again.\n' \
    "$BOLD$RED" "$error_count" "$RESET"
  rm -rf "$WORK"
  exit 1
fi
printf '  %s✓%s Tools, .env, ports and disk are ready.\n' "$GREEN" "$RESET"

# The one line of a log that says why it failed: the last line that mentions an error, else the
# last non-empty line (for Python, the exception line comes last).
reason_of() {
  local line
  line=$(tail -n 30 "$1" 2>/dev/null | grep -iE 'error|exception|failed|refused|denied|not found|no such' | tail -n 1)
  [ -n "$line" ] || line=$(grep -v '^[[:space:]]*$' "$1" 2>/dev/null | tail -n 1)
  printf '%s' "$line" | sed -E 's/^[[:space:]]+//' | cut -c 1-220
}

# =================================================================================================
heading "Preparing (output goes to $LOG_DIR/)"
mkdir -p "$LOG_DIR"

# step <log name> <label> <what to do when it fails> <command...>
step() {
  local name=$1 label=$2 hint=$3 log="$LOG_DIR/$1.log" started=$SECONDS
  shift 3
  printf '  %s…%s %s' "$DIM" "$RESET" "$label"
  if "$@" >"$log" 2>&1; then
    printf '%s  %s✓%s %s %s(%ss)%s\n' "$CLEAR" "$GREEN" "$RESET" "$label" "$DIM" "$((SECONDS - started))" "$RESET"
    return 0
  fi
  printf '%s  %s✗%s %s\n\n  %s\n' "$CLEAR" "$RED" "$RESET" "$label" "$hint"
  printf '  Reason:   %s\n  Full log: %s\n' "$(reason_of "$log")" "$log"
  printf '\n%sStopped before starting the app.%s Fix the cause and run make start again.\n' "$BOLD$RED" "$RESET"
  rm -rf "$WORK"
  exit 1
}

step python "Python packages (uv sync)" \
  "uv could not install the Python packages. Check your internet connection; the log says which package failed." \
  uv sync
step frontend "Frontend packages (pnpm install)" \
  "pnpm could not install the frontend packages. Check your internet connection; the log says which package failed." \
  pnpm --dir apps/frontend install --frozen-lockfile
if [ "$LOCAL_DB" = 1 ]; then
  step falkordb "FalkorDB (Docker)" \
    "The FalkorDB container did not become healthy. Check that Docker has enough memory, and that the ports in .env are free." \
    docker compose up -d --wait
fi
step connect "Connecting to FalkorDB at $FALKORDB_HOST:$(setting FALKORDB_PORT 6379)" \
  "FalkorDB does not answer. Check FALKORDB_HOST, FALKORDB_PORT, FALKORDB_PASSWORD and FALKORDB_TLS in .env. A password added after the container was first started needs make down, then make start." \
  uv run python -c "
import sys
from brain import db
try:
    db.ping()
except Exception as e:
    sys.exit(f'error: {type(e).__name__}: {e}')
"
step demo "Demo company (brain_synthetic; the first run downloads a 0.2 GB embedding model)" \
  "The demo company could not be built. The log has the reason." \
  sh -c "uv run brain schema synthetic && uv run brain ingest synthetic"
if grep -q "^skipped" "$LOG_DIR/demo.log"; then
  printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$(grep '^skipped' "$LOG_DIR/demo.log" | head -n 1)"
fi

# =================================================================================================
heading "Starting the app"

API_PID="" FE_PID=""
kill_tree() { # a process and everything it started (make -> uv -> uvicorn ...)
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$child"; done
  kill "$1" 2>/dev/null
}
stop_servers() {
  [ -n "$API_PID" ] && kill_tree "$API_PID"
  [ -n "$FE_PID" ] && kill_tree "$FE_PID"
  API_PID="" FE_PID=""
  rm -rf "$WORK"
}
on_interrupt() {
  stop_servers
  printf '\n%sStopped the API and the app.%s FalkorDB keeps running (make down stops it).\n' "$BOLD" "$RESET"
  exit 0
}
trap on_interrupt INT TERM
trap stop_servers EXIT

# server_failed <name> <log> <reason>
server_failed() {
  printf '%s  %s✗%s %s\n\n  Reason:   %s\n  Full log: %s\n' "$CLEAR" "$RED" "$RESET" "$3" "$(reason_of "$2")" "$2"
  printf '\n%sThe %s stopped.%s Fix the cause and run make start again.\n' "$BOLD$RED" "$1" "$RESET"
  exit 1
}
# wait_ready <name> <pid> <url> <log> <seconds>
wait_ready() {
  local started=$SECONDS
  printf '  %s…%s %s' "$DIM" "$RESET" "$1"
  until curl -fsS -o /dev/null "$3" 2>/dev/null; do
    kill -0 "$2" 2>/dev/null || server_failed "$1" "$4" "The $1 exited while starting."
    [ $((SECONDS - started)) -lt "$5" ] || server_failed "$1" "$4" "The $1 did not answer within $5 s."
    sleep 1
  done
  printf '%s  %s✓%s %s %s(%ss)%s\n' "$CLEAR" "$GREEN" "$RESET" "$1" "$DIM" "$((SECONDS - started))" "$RESET"
}

make --no-print-directory api API_PORT="$API_PORT" >"$LOG_DIR/api.log" 2>&1 &
API_PID=$!
make --no-print-directory fe-dev FE_PORT="$FE_PORT" API_PORT="$API_PORT" >"$LOG_DIR/frontend.log" 2>&1 &
FE_PID=$!
wait_ready "API" "$API_PID" "http://127.0.0.1:$API_PORT/api/companies" "$LOG_DIR/api.log" 90
wait_ready "app" "$FE_PID" "http://localhost:$FE_PORT/" "$LOG_DIR/frontend.log" 90

printf '\n  %sCitadel is running.%s\n\n' "$BOLD$GREEN" "$RESET"
printf '    App   %shttp://localhost:%s%s   (open this)\n' "$BOLD" "$FE_PORT" "$RESET"
printf '    API   http://127.0.0.1:%s\n' "$API_PORT"
printf '    Logs  %s/api.log, %s/frontend.log\n\n' "$LOG_DIR" "$LOG_DIR"
printf '  Pick "Synthetic Co" on the left. Press Ctrl+C to stop.\n'

while sleep 2; do
  kill -0 "$API_PID" 2>/dev/null || server_failed "API" "$LOG_DIR/api.log" "The API exited."
  kill -0 "$FE_PID" 2>/dev/null || server_failed "app" "$LOG_DIR/frontend.log" "The app's dev server exited."
done
