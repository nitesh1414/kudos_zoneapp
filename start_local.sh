#!/usr/bin/env bash
# ============================================================
#  Zone Levels - local start (macOS / Linux)
#
#  1. Put your bars CSV in this folder and name it  data.csv
#  2. Run:  bash start_local.sh
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "==== Zone Levels - local ===="
echo

PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  echo "Python not found. Install Python 3.10 or newer."
  exit 1
fi

if [ ! -d venv ]; then
  echo "Creating virtual environment..."
  "$PY" -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate
echo "Installing dependencies..."
pip install --upgrade pip --quiet
pip install -r backend/requirements.txt --quiet

export ZONEAPP_API_KEY=local-dev-key
export ZONEAPP_DB="$PWD/data/local.duckdb"
export ZONEAPP_UPLOADS="$PWD/data/uploads"
export ZONEAPP_SYMBOL=${ZONEAPP_SYMBOL:-NSE:NIFTY50-INDEX}
mkdir -p data/uploads

if [ -f data.csv ] && [ ! -f "$ZONEAPP_DB" ]; then
  echo
  echo "Loading history from data.csv ..."
  python scripts/seed.py data.csv
elif [ ! -f data.csv ]; then
  echo
  echo "NOTE: no data.csv in this folder. The app will start empty."
  echo "Put your CSV here as data.csv and restart, or upload from the dashboard."
fi

echo
echo "============================================================"
echo "  Dashboard : http://127.0.0.1:8000"
echo "  API docs  : http://127.0.0.1:8000/docs"
echo "  API key   : local-dev-key"
echo
echo "  Press Ctrl+C to stop."
echo "============================================================"
echo

( sleep 2; (command -v open >/dev/null && open http://127.0.0.1:8000) || \
           (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8000) || true ) &

cd backend
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
