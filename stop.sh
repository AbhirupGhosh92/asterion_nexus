#!/usr/bin/env bash
# Stop the local stack started by ./start.sh.
#
# Usage:
#   ./stop.sh            # stop backend + frontend, leave Dify running
#   ./stop.sh --all       # also stop the Dify docker compose stack

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PID_DIR=".pids"

stop_pid() {
  local name="$1" file="$PID_DIR/$1.pid"
  if [[ -f "$file" ]]; then
    local pid; pid=$(cat "$file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      echo "✓ stopped $name (pid $pid)"
    else
      echo "· $name not running"
    fi
    rm -f "$file"
  else
    echo "· no pid file for $name"
  fi
}

stop_pid backend
stop_pid frontend

if [[ "${1:-}" == "--all" ]]; then
  export PATH="$HOME/.orbstack/bin:$PATH"
  echo "▸ stopping Dify containers…"
  ( cd infra/dify/docker && docker compose down ) && echo "✓ Dify stopped"
else
  echo "· Dify left running (use --all to stop it too)"
fi
