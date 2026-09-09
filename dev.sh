#!/usr/bin/env bash
# Dev: backend (uvicorn --reload) + frontend (vite dev server) together.
# Ctrl+C stops both. Requires the one-time setup: ./setup.sh
set -euo pipefail

API_HOST=127.0.0.1
API_PORT=8000
WAIT_SECONDS=30

wait_for_port() {
  local host=$1 port=$2 deadline=$(( SECONDS + WAIT_SECONDS ))
  until (exec 3<>"/dev/tcp/${host}/${port}") 2>/dev/null; do
    if (( SECONDS >= deadline )); then
      echo "dev.sh: backend did not come up on ${host}:${port} within ${WAIT_SECONDS}s" >&2
      return 1
    fi
    sleep 0.5
  done
}

cleanup() {
  kill "${API_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT

# essentia-tensorflow may be shadowed by the plain wheel on a fresh venv
(cd backend && uv run --no-sync python tools/ensure_essentia.py) || exit 1

(cd backend && uv run uvicorn app.main:app --reload --host "$API_HOST" --port "$API_PORT") &
API_PID=$!

wait_for_port "$API_HOST" "$API_PORT"

(cd frontend && npm run dev)
