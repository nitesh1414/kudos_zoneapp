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
- `backend/app/main.py` — authentication plus admin/client APIs
- `backend/app/templates/` — separate login, admin and client interfaces
- `backend/app/jobs.py` — idempotent trading-day market-close worker
- `deploy/` — systemd, nginx and 17:00 Asia/Kolkata cron examples

Raw intraday bars are the source of truth. Daily OHLC, zone sheets, outcomes
and base-rate tables are derived and can be rebuilt.

## Local start (Docker)

```bash
docker compose up --build
```

Open <http://localhost:8000>. The local compose credentials are:

- username: `admin`
- password: `local-admin-password`

Change every example secret before deployment. Docker Compose starts
TimescaleDB/PostgreSQL and the API. For a non-Docker install, copy
`backend/.env.example`, export its values, install
`backend/requirements.txt`, and run:

```bash
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

## Administrator workflow

1. Sign in at `/login` and open **Broker connections**.
2. Add credentials for a registered provider and use **Test**.
3. Open **Client management**, create a login, select its broker, and assign a
   symbol in that provider's symbol format.
4. The client signs in through the same login page and is redirected to the
   separate `/app` result view. A client can only query their assigned symbol.

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

## Security notes

- Browser access uses HTTP-only, SameSite session cookies and role checks.
- `ZONEAPP_API_KEY` is only for the local cron endpoint.
- Use HTTPS and `ZONEAPP_SECURE_COOKIES=true` in production.
- Never commit `.env`, broker tokens, log files, screenshots, or database dumps.
