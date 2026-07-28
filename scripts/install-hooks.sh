#!/usr/bin/env bash
# Point git at the repo's tracked hooks. Idempotent; safe to run repeatedly.
#
# Git deliberately never installs hooks from a clone (a hook is arbitrary code
# a clone shouldn't run unasked), so every developer runs this once —
# ./start.sh does it for you.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

current="$(git config --get core.hooksPath || true)"
if [ "$current" = ".githooks" ]; then
  echo "✓ hooks already enabled (core.hooksPath=.githooks)"
else
  git config core.hooksPath .githooks
  echo "✓ enabled repo hooks (core.hooksPath=.githooks)"
fi

chmod +x .githooks/* 2>/dev/null || true
echo "  pre-commit → scripts/scan_secrets.py (secret scan)"
