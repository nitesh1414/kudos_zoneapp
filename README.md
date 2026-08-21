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
- `backend/app/symbols.py` — administrator watchlist of tracked symbols
- `backend/app/broker_store.py` — the single resolver that turns a stored,
  encrypted broker connection into a ready adapter for every dependent service
- `backend/app/seeding.py` — historical backfill that runs automatically after
  a token is saved
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

Compose reads the repository-root `.env` (copy `.env.example` to `.env`), so no
credentials live in `docker-compose.yml`. Change every example secret before
deployment.

## Configuration (.env)

PostgreSQL is the only supported database and its URL lives in `.env`:

```bash
cp .env.example backend/.env      # docker compose: cp .env.example .env
```

```ini
DATABASE_URL=postgresql://zoneapp:your-password@127.0.0.1:5432/zoneapp
ZONEAPP_ADMIN_USERNAME=admin
ZONEAPP_ADMIN_PASSWORD=a-strong-password
ZONEAPP_API_KEY=a-long-random-value          # market-close cron only
ZONEAPP_ENCRYPTION_KEY=a-fernet-key          # encrypts stored broker credentials
ZONEAPP_SECURE_COOKIES=true                  # false only on plain HTTP
```

`backend/app/__init__.py` loads this file, so the API, the market-close worker,
the seeder, `scripts/seed.py`, `scripts/health_check.py` and the backfill CLI
all read the same settings from any working directory. Real environment
variables still override the file, which is what `deploy/zoneapp.service` and
the cron entries rely on. Generate the encryption key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Leaving `ZONEAPP_ENCRYPTION_KEY` unset is supported — a key is generated and
stored in the database — but set it explicitly in production and never change
it on a live installation, or saved broker credentials must be entered again.

For a non-Docker install, install PostgreSQL 16 (and the TimescaleDB extension
when available), create the database and role, fill in `backend/.env`, then
run:

```bash
bash start_local.sh --no-docker
# or manually:
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

The application reads `backend/.env` itself; it does not require Docker or
machine-level environment configuration. Schema creation and forward
migrations run automatically on startup, on plain PostgreSQL as well as
TimescaleDB.

## Tests

```bash
# unit tests — no services required
python -m unittest discover -s backend/tests

# full end-to-end suite against a throwaway PostgreSQL
pip install pgserver
python -c "import pgserver;print(pgserver.get_server('/tmp/pgdata').get_uri())"
DATABASE_URL=<printed uri> python -m unittest discover -s backend/tests
```

The end-to-end module (`backend/tests/test_integration_postgres.py`) swaps in a
synthetic broker, so it needs no credentials or network. It covers login and
role separation, broker creation, token save → automatic seeding, seeding by
day count and by date range, the symbol watchlist, client CRUD, the
market-close job (including weekend/holiday skips, idempotency and the cron API
key), JSON-safety of nullable columns, and forward migration from an older
database.

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
2. Add a connection: for Fyers that is the **App / Client ID**, **Secret key**
   and **Redirect URI** (`FYERS_CLIENT_ID`, `FYERS_SECRET_KEY`,
   `FYERS_REDIRECT_URI`); the daily access token is added next.
3. Press **Generate token** on that connection: it opens the provider sign-in
   built from the connection's own credentials, then you paste back the
   redirect URL (or just the auth code) and it is exchanged and stored.
4. Nothing else needs assigning. Accounts are plain logins — clients see the
   same watchlist and pick any symbol from the header dropdown; only the
   Administration tabs are hidden from them.

Client management supports create, edit (name, password reset), enable/disable
and delete, in either a card or a table view.

The token field also accepts a pasted access token, an `APPID-100:token`
string, or the whole redirect URL — whatever the provider showed you.

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

### Tracking many symbols

**Market symbols** in the administrator panel is the watchlist. Every active
entry is fetched and run through the zone engine on its own, whether or not a
client is assigned to it, and each symbol keeps its own candles, zone sheets,
outcomes and base rates.

- A new installation starts tracking `NSE:NIFTY50-INDEX`, `NSE:NIFTYBANK-INDEX`
  and `NSE:MIDCPNIFTY-INDEX` automatically, so the first broker token is enough
  to start collecting data.
- Aliases are expanded on entry (`NIFTY` → `NSE:NIFTY50-INDEX`, `BANKNIFTY`,
  `FINNIFTY`, `MIDCPNIFTY`, `SENSEX`); anything else is passed to the provider
  unchanged, so `NSE:RELIANCE-EQ` or `MCX:CRUDEOIL25AUGFUT` work too.
- Per symbol you can choose timeframes (15-minute is always included) and pin a
  specific broker connection, or leave it on any enabled connection.
- `POST /api/admin/symbols` adds and immediately backfills one symbol,
  `POST /api/admin/symbols/{symbol}/seed` refetches it, and
  `POST /api/admin/seed` runs an on-demand fetch for a chosen period.
- The market-close job iterates the same list, recording one `job_runs` row per
  (connection, symbol) so a single bad symbol cannot hide the others.
- Every signed-in account chooses which symbol the market tabs show, from the
  header dropdown. Symbols and brokers are platform-wide, not per account.

### Data seeding on demand

**Data seeding** in the administrator panel fetches any period into the
database and rebuilds every derived table from it:

- period presets — today, past week, past month, 3/6 months, 1/2/5 years — or a
  custom `from`/`to` date range;
- all tracked symbols or a hand-picked subset;
- optional timeframe override (15-minute is always included).

It posts to `POST /api/admin/seed` with either `days` or `date_from`/`date_to`,
runs in the background and reports each symbol in the activity table. Seeding
is idempotent: candles are upserted, so re-running a period repairs gaps rather
than duplicating rows.

### Tokens and the automatic seeder

A token saved in the UI is stored on the broker connection and is the single
source of truth. `backend/app/broker_store.py` resolves it for every dependent
service — the market-close job, the seeder, `scripts/seed.py`,
`backend/scripts/backfill_data.py` and `verify_fyers.py` — so none of them fall
back to "token not found" after an administrator adds one. Environment
variables (`FYERS_ACCESS_TOKEN`) are only used when no stored connection has a
token, which keeps standalone CLI runs working.

Saving a token immediately starts a background seed: candles are fetched for
every symbol that depends on the connection and zones plus base rates are
rebuilt. Progress is visible under **Broker connections → Data sync activity**
and can be re-triggered from the same page (`POST /api/admin/brokers/{id}/seed`,
default 180 days).

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
