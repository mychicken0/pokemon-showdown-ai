#!/usr/bin/env bash
# Setup script for development environment.
# Creates the showdown_ai.pth file in the venv site-packages directory
# so subprocess invocations can find production modules.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_SITE_PACKAGES="$PROJECT_ROOT/venv/lib/python3.12/site-packages"
PTH_FILE="$VENV_SITE_PACKAGES/showdown_ai.pth"

if [ ! -d "$VENV_SITE_PACKAGES" ]; then
    echo "venv not found at $VENV_SITE_PACKAGES"
    echo "Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

cat > "$PTH_FILE" <<PTH_EOF
import sys, os; _root = '$PROJECT_ROOT'; sys.path[:0] = [_root + '/showdown_ai', _root + '/scripts/analyze', _root + '/scripts/inspect']
PTH_EOF

echo "Created $PTH_FILE"
echo "Subprocess invocations like 'python -c \"import ability_rules\"' will now work."
