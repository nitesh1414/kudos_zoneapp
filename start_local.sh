#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" != "--no-docker" ] && command -v docker >/dev/null; then
  echo "Starting ZoneApp and TimescaleDB with Docker..."
  exec docker compose up --build
fi

if [ ! -f backend/.env ] && [ -z "${DATABASE_URL:-}" ]; then
  echo "Non-Docker mode needs PostgreSQL/TimescaleDB."
  echo "Copy backend/.env.example to backend/.env and set DATABASE_URL and secrets."
  exit 1
fi
# Build the React interface when it is missing and Node is available.
if [ ! -f backend/app/static/index.html ]; then
  if command -v npm >/dev/null; then
    echo "Building the React frontend..."
    (cd frontend && npm install --no-audit --no-fund && npm run build)
  else
    echo "Warning: backend/app/static/index.html is missing and npm was not found."
    echo "Install Node.js 20+, then run: cd frontend && npm install && npm run build"
  fi
fi

PY=$(command -v python3 || command -v python)
[ -d .venv ] || "$PY" -m venv .venv
. .venv/bin/activate
pip install -q -r backend/requirements.txt
exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
