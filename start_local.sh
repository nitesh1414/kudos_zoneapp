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
PY=$(command -v python3 || command -v python)
[ -d .venv ] || "$PY" -m venv .venv
. .venv/bin/activate
pip install -q -r backend/requirements.txt
exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
