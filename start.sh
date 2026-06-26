#!/usr/bin/env bash
#
# One-step launcher for the Anki Deck Workbench.
#
# You never have to touch a virtualenv. The first run creates a hidden one
# (.venv) and installs dependencies into it; every run after that just uses it.
# There is nothing to "activate".
#
#   ./start.sh         start it (or double-click "Anki Workbench.command")
#   Ctrl+C             stop it
#
set -euo pipefail
cd "$(dirname "$0")"

URL="http://127.0.0.1:5151"
VENV=".venv"
PYBIN="$VENV/bin/python"

# Already running? Just open the tab and stop.
if curl -fsS -m1 "$URL/api/status" >/dev/null 2>&1; then
  echo "Already running — opening $URL"
  open "$URL" 2>/dev/null || true
  exit 0
fi

# First run (or .venv was deleted): build the hidden venv + install deps once.
if [ ! -x "$PYBIN" ]; then
  echo "First run: setting up (one time)…"
  "${PYTHON:-python3}" -m venv "$VENV"
  "$PYBIN" -m pip install -q --upgrade pip
  "$PYBIN" -m pip install -q -r requirements.txt
fi

# Open the browser as soon as the server answers.
( for _ in $(seq 1 60); do
    curl -fsS -m1 "$URL/api/status" >/dev/null 2>&1 && { open "$URL" 2>/dev/null || true; break; }
    sleep 0.25
  done ) &

echo "Starting Anki Deck Workbench at $URL  (Ctrl+C to stop)"
exec "$PYBIN" run.py "$@"
