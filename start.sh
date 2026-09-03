#!/usr/bin/env bash
# Prod: только backend, раздаёт собранный frontend/dist. Node не нужен.
set -euo pipefail

API_HOST=127.0.0.1
API_PORT=8000

cd backend
exec uv run uvicorn app.main:app --host "$API_HOST" --port "$API_PORT"
