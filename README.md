# Zone Levels

Next-session support/resistance zones for NSE indices, with historical base
rates. Single-user internal tool: FastAPI + DuckDB + one HTML page.

**Reference map, not a signal generator.** No orders, no advice.

---

## Quick start (local)

**Easiest:** put your bars CSV in this folder named `data.csv`, then

- Windows: double-click `start_local.bat`
- macOS / Linux: `bash start_local.sh`

It builds a venv, installs everything, loads the CSV, starts the server and
opens the dashboard. Local API key is `local-dev-key`.

**Manual:**

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export ZONEAPP_API_KEY=dev
export ZONEAPP_DB=./data/dev.duckdb

python ../scripts/seed.py /path/to/bars.csv     # load history
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000 — dashboard. API docs at `/docs`.

CSV needs columns `time, open, high, low, close` (volume optional). A
TradingView "Export chart data" file works as-is.

## Deploy to a VPS

```bash
git clone <repo> /opt/zoneapp
bash /opt/zoneapp/deploy/install.sh
certbot --nginx -d your.domain
sudo -u zoneapp /opt/zoneapp/venv/bin/python /opt/zoneapp/scripts/seed.py /path/to/bars.csv
```

Full detail in `DEVELOPER_GUIDE.md` §7.

## Daily use

1. Upload a CSV from the dashboard (or `POST /api/ingest/csv`) — no broker
   needed, works today
2. When a broker is chosen, add it under `backend/app/brokers/` (see
   `brokers/README.md`) and wire an equivalent ingest route
3. Zones for the next session appear on the dashboard and at
   `GET /api/levels/next`

## Layout

```
backend/app/zones.py       level maths + clustering   <- the critical file
backend/app/db.py          DuckDB schema and access
backend/app/brokers/       broker adapters (CSV works today, no broker chosen yet)
backend/app/service.py     EOD job + statistics
backend/app/main.py        FastAPI routes and auth
backend/app/templates/     the entire frontend, one file
scripts/seed.py            history import
deploy/                    systemd, nginx, cron, install.sh
DEVELOPER_GUIDE.md         architecture, constraints, roadmap
```

## Before changing anything numeric

Read `DEVELOPER_GUIDE.md` §9. Several design choices exist because the
alternative was measured and found wrong — in particular: base rates are not
probabilities, star rating predicts *reach* not *hold*, and changing zone
parameters invalidates historical comparisons.

## Status

- Level engine, storage, statistics, API, dashboard: working, verified
  against 541 sessions
- No broker chosen yet — see `backend/app/brokers/README.md` and
  `DEVELOPER_BIBLE.md` SS5 before adding one; verify any new adapter with a
  small date range before trusting it
- Tests: none yet. See `DEVELOPER_GUIDE.md` §10
