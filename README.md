# ZoneApp

A multi-client FastAPI application that ingests completed market candles and
builds next-session support/resistance reference zones with historical base
rates. It does **not** place orders or produce trading advice.

## What is in this repository

- `backend/app/zones.py` — deterministic pivot/CPR, clustering and outcome maths
- `backend/app/service.py` — EOD orchestration and historical statistics
- `backend/app/db.py` — PostgreSQL schema/access; enables a TimescaleDB
  hypertable when the extension is available
- `backend/app/brokers/` — provider-independent `BrokerAdapter`, registry, CSV
  adapter and Fyers implementation
- `backend/app/main.py` — authentication, admin/client APIs and single-page-app hosting
- `frontend/` — React + Vite interface (login screen, tabbed client dashboard,
  tabbed admin panel). `npm run build` compiles it into `backend/app/static/`,
  which FastAPI serves
- `backend/app/jobs.py` — idempotent trading-day market-close worker
- `deploy/` — systemd, nginx and 17:00 Asia/Kolkata cron examples

Raw intraday bars are the source of truth. Daily OHLC, zone sheets, outcomes
and base-rate tables are derived and can be rebuilt.

## Local start (Docker)

```bash
docker compose up --build
```

Open <http://localhost:8000>. There is no public landing page — the first
screen is always the login form, and everything else lives behind it as tabs.
The local compose credentials are:

- username: `admin`
- password: `local-admin-password`

Change every example secret before deployment. Docker Compose starts
TimescaleDB/PostgreSQL and the API. Docker is optional. For a non-Docker install, install PostgreSQL 16 (and the
TimescaleDB extension when available), create the database, copy
`backend/.env.example` to `backend/.env`, and set `DATABASE_URL` and the other
secrets. Then run:

```bash
bash start_local.sh --no-docker
# or manually:
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

The application reads `backend/.env` itself; it does not require Docker or
machine-level environment configuration.

## Frontend development

```bash
cd frontend
npm install
npm run dev        # Vite dev server on :5173, proxies /api to :8000
npm run dev:mock   # same UI against built-in demo data, no database needed
npm run build      # writes backend/app/static/ (committed, so plain uvicorn works)
```

Market data is ingested through broker connections and the market-close job;
there is no CSV upload in the interface.

## Administrator workflow

1. Sign in at `/login` and open **Broker connections**.
2. Add credentials for a registered provider and use **Test**.
3. Open **Client management**, create a login, select its broker, and assign a
   symbol in that provider's symbol format.
4. The client signs in through the same login page and lands on the same
   dashboard; the Administration tabs are only rendered for administrators.
   A client can only query their assigned symbol.

Client management supports create, edit (name, symbol, password reset, broker),
enable/disable and delete, in either a card or a table view.

The symbol picker searches Fyers' complete Indian symbol masters for NSE cash
and indices, NSE derivatives/currency, BSE cash/derivatives, and MCX
commodities. Exact provider symbols can also be entered, so the application is
not limited to the original NIFTY aliases. Connections can retain every Fyers
candle resolution (`1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 120, 180, 240, D`).
The historical backfill API chunks long date ranges according to provider
limits and stores each timeframe independently. Zone results deliberately use
completed 15-minute candles.

Broker credentials are Fernet-encrypted in PostgreSQL. Keep
`ZONEAPP_ENCRYPTION_KEY` stable and outside source control.

### Adding another broker provider

“Any broker” cannot safely mean that arbitrary APIs work without integration:
each provider has different authentication, symbols and candle payloads. The
application itself is generic. Implement `BrokerAdapter` in
`backend/app/brokers/<provider>_adapter.py`, then add one `BrokerType` entry to
`registry.py`, including the credential fields the admin UI should render.
No route, job or UI code needs to change. Fyers is the first registered
provider.

## Market-close job

`deploy/crontab.example` invokes one job at **17:00 Asia/Kolkata, Monday to
Friday**. The worker:

1. skips weekends and rows in `market_holidays`;
2. finds each distinct active broker/symbol assignment;
3. downloads the latest completed 15-minute candles;
4. upserts them into the TimescaleDB hypertable;
5. scores the completed session and writes the forward sheet;
6. exposes that sheet to assigned clients for the next session.

Runs are recorded in `job_runs` and are idempotent per date, broker and symbol.
The administrator can manually run or force the job from the UI. Add exchange
holidays to `market_holidays` as part of annual operations.

All trading decisions use `Asia/Kolkata` through Python `zoneinfo`, PostgreSQL
absolute timestamps, and `CRON_TZ=Asia/Kolkata`; they do not depend on the
server or machine timezone.

Fyers connections track their 24-hour token lifetime. Admin and assigned
client dashboards show missing, expiring (within three hours), and expired
notifications. Either the admin or assigned client can paste the daily token;
it is validated and immediately re-encrypted in PostgreSQL.

## Security notes

- Browser access uses HTTP-only, SameSite session cookies and role checks.
- `ZONEAPP_API_KEY` is only for the local cron endpoint.
- Use HTTPS and `ZONEAPP_SECURE_COOKIES=true` in production.
- Never commit `.env`, broker tokens, log files, screenshots, or database dumps.
