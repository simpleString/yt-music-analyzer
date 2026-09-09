#!/usr/bin/env bash
# Prod: serves the built frontend (frontend/dist) and the API from one port.
# Requires the one-time setup: ./setup.sh
set -euo pipefail

API_HOST=127.0.0.1
API_PORT=8000

cd backend

# essentia-tensorflow may be shadowed by the plain wheel on a fresh venv
uv run --no-sync python tools/ensure_essentia.py || exit 1

# frontend missing? build it on the spot when possible
if [ ! -f ../frontend/dist/index.html ]; then
  echo "start.sh: frontend/dist is missing"
  if command -v node >/dev/null 2>&1; then
    echo "start.sh: building frontend..."
    (cd ../frontend && npm ci && npm run build)
  else
    echo "start.sh: run ./setup.sh first (installs Node.js and builds the frontend)" >&2
    exit 1
  fi
fi

exec uv run uvicorn app.main:app --host "$API_HOST" --port "$API_PORT"
