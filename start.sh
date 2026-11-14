#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PROJECT="${1:-.}"
PORT="${2:-7741}"

echo "Quick-TakeApart quick start"

command -v node >/dev/null || { echo "Node.js is required (pyright + web build)." >&2; exit 1; }
command -v python >/dev/null || command -v python3 >/dev/null || {
  echo "Python is required." >&2; exit 1;
}
PYTHON_BIN="$(command -v python || command -v python3)"

if [ ! -f node_modules/pyright/langserver.index.js ]; then
  echo "Installing indexer dependencies..."
  npm ci --omit=dev
fi

if ! "$PYTHON_BIN" -c "import anthropic" >/dev/null 2>&1; then
  echo "Installing Python dependencies..."
  "$PYTHON_BIN" -m pip install -r requirements.txt
fi

if [ ! -d web/node_modules ]; then
  echo "Installing frontend dependencies..."
  npm --prefix web ci
fi

echo "Building frontend..."
npm --prefix web run build

echo "Starting http://127.0.0.1:${PORT}/ for ${PROJECT}"
exec "$PYTHON_BIN" serve.py "$PROJECT" --host 127.0.0.1 --port "$PORT"
