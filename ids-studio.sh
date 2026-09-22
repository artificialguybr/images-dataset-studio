#!/usr/bin/env bash
# Images Dataset Studio — single-command start (API + built frontend on :8766)
set -euo pipefail
cd "$(dirname "$0")"

# build the frontend once (skip when dist is current)
if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html 2>/dev/null)" ]; then
  (cd frontend && npm run build)
fi

exec uv run uvicorn backend.app.main:app --host 127.0.0.1 --port "${IDS_PORT:-8766}"
