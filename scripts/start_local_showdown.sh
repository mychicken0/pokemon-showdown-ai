#!/usr/bin/env bash
set -euo pipefail

SHOWDOWN_DIR="${SHOWDOWN_DIR:-/home/phurin/Program/Showdown_AI/pokemon-showdown}"

cd "$SHOWDOWN_DIR"

if [[ ! -x ./pokemon-showdown ]]; then
  echo "ERROR: ./pokemon-showdown executable not found in $SHOWDOWN_DIR" >&2
  exit 1
fi

echo "Starting local Pokemon Showdown server on http://localhost:8000"
echo "Keep this terminal/session open. Stop with Ctrl-C."
echo

exec ./pokemon-showdown start --no-security
