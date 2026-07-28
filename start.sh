#!/usr/bin/env bash
# Start the full local stack: OrbStack/Dify, FastAPI backend, Vite frontend.
#
# Usage:
#   ./start.sh              # start everything (auth enforced, needs Firebase login)
#   ./start.sh --no-auth    # start backend with AUTH_DISABLED=1 for offline dev
#
# Logs stream to ./logs/*.log. Run ./stop.sh to tear everything down.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

ROOT="$(pwd)"
LOG_DIR="$ROOT/logs"
PID_DIR="$ROOT/.pids"
DIFY_DIR="$ROOT/infra/dify/docker"
mkdir -p "$LOG_DIR" "$PID_DIR"

NO_AUTH=0
[[ "${1:-}" == "--no-auth" ]] && NO_AUTH=1

# ---------------------------------------------------------------------------
c_cyan=$'\033[0;36m'; c_green=$'\033[0;32m'; c_yellow=$'\033[0;33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
say() { echo "${c_cyan}▸${c_off} $1"; }
ok()  { echo "${c_green}✓${c_off} $1"; }
warn(){ echo "${c_yellow}!${c_off} $1"; }

# ---------------------------------------------------------------------------
# 0. Git hooks (secret scan on commit)
# ---------------------------------------------------------------------------
# Git never installs hooks from a clone, so wire them up here — silently when
# they're already set, so this costs nothing on every later run.
if [ "$(git config --get core.hooksPath || true)" != ".githooks" ]; then
  ./scripts/install-hooks.sh >/dev/null 2>&1 && ok "Enabled git hooks (secret scan on commit)"
fi

# ---------------------------------------------------------------------------
# 1. Docker (OrbStack) + Dify stack
# ---------------------------------------------------------------------------
say "Checking Docker (OrbStack)…"
export PATH="$HOME/.orbstack/bin:$PATH"

if ! docker info >/dev/null 2>&1; then
  say "Starting OrbStack…"
  open -a OrbStack --background
  for i in $(seq 1 30); do
    docker info >/dev/null 2>&1 && break
    sleep 2
  done
fi
docker info >/dev/null 2>&1 && ok "Docker is up" || { echo "Docker did not start — open OrbStack manually."; exit 1; }

say "Starting Dify (docker compose)…"
( cd "$DIFY_DIR" && docker compose up -d ) > "$LOG_DIR/dify.log" 2>&1
ok "Dify containers requested (see logs/dify.log)"

say "Waiting for Dify API (localhost:8090)…"
for i in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://localhost:8090/console/api/setup || true)
  [[ "$code" == "200" ]] && break
  sleep 3
done
if [[ "$code" == "200" ]]; then
  ok "Dify is responding"
else
  warn "Dify not responding yet — it may still be warming up; check logs/dify.log"
fi

# ---------------------------------------------------------------------------
# 2. Backend (FastAPI)
# ---------------------------------------------------------------------------
say "Starting backend (uvicorn :8080)…"
cd "$ROOT/backend"
set -a; source .env; set +a
if [[ $NO_AUTH -eq 1 ]]; then
  export AUTH_DISABLED=1
  warn "AUTH_DISABLED=1 — every request runs as the admin identity, no Firebase login needed"
else
  unset AUTH_DISABLED || true
fi

nohup .venv/bin/uvicorn app:app --port 8080 > "$LOG_DIR/backend.log" 2>&1 &
echo $! > "$PID_DIR/backend.pid"
cd "$ROOT"

for i in $(seq 1 20); do
  curl -s -o /dev/null --max-time 2 http://localhost:8080/api/healthz && break
  sleep 2
done
curl -s --max-time 3 http://localhost:8080/api/healthz >/dev/null 2>&1 \
  && ok "Backend is up (pid $(cat "$PID_DIR/backend.pid"))" \
  || warn "Backend not responding yet — check logs/backend.log"

# ---------------------------------------------------------------------------
# 3. Frontend (Vite)
# ---------------------------------------------------------------------------
say "Starting frontend (vite :5173)…"
cd "$ROOT/frontend"
nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
echo $! > "$PID_DIR/frontend.pid"
cd "$ROOT"
sleep 2
ok "Frontend starting (pid $(cat "$PID_DIR/frontend.pid"))"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
DIFY_EMAIL=$(grep '^DIFY_ADMIN_EMAIL=' backend/.env | cut -d= -f2-)
DIFY_PASS=$(grep '^DIFY_ADMIN_PASSWORD=' backend/.env | cut -d= -f2-)

echo
echo "════════════════════════════════════════════════════════════"
echo "  ${c_green}NEXUS platform is up${c_off}"
echo "════════════════════════════════════════════════════════════"
echo "  NEXUS UI        ${c_cyan}http://localhost:5173${c_off}"
echo "  Backend API     ${c_cyan}http://localhost:8080${c_off}  (docs: /docs)"
echo "  Dify console    ${c_cyan}http://localhost:8090${c_off}"
echo "                  ${c_dim}login: $DIFY_EMAIL / $DIFY_PASS${c_off}"
echo "                  ${c_dim}(direct Dify UI — build/debug workflows here;${c_off}"
echo "                  ${c_dim} NEXUS's own AGENT FORGE is the normal path)${c_off}"
echo "────────────────────────────────────────────────────────────"
echo "  Logs:   tail -f logs/backend.log logs/frontend.log logs/dify.log"
echo "  Stop:   ./stop.sh"
echo "════════════════════════════════════════════════════════════"
