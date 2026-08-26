# ZoneApp

A multi-client FastAPI application that ingests completed market candles and
builds next-session support/resistance reference zones with historical base
rates. It does **not** place orders or produce trading advice.

## What is in this repository

- `backend/app/zones.py` — deterministic pivot/CPR, clustering and outcome maths
- `backend/app/service.py` — EOD orchestration, completed-session awareness,
  the session-chart payload and historical statistics
- `backend/app/db.py` — PostgreSQL schema/access; enables a TimescaleDB
  hypertable when the extension is available
- `backend/app/brokers/` — provider-independent `BrokerAdapter`, registry, CSV
  adapter and Fyers implementation
- `backend/app/main.py` — authentication, admin/client APIs and single-page-app hosting
- `frontend/` — React + Vite interface (login screen, tabbed client dashboard,
  tabbed admin panel). `npm run build` compiles it into `backend/app/static/`,
  which FastAPI serves
- `docs/METHODOLOGY.md` — the strategy document: every metric, its formula and
  the basis it is measured on. Served to the admin **Strategy & definitions**
  tab by `GET /api/methodology`, so the tab and the file cannot drift
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

### Session chart

The client **Overview** tab includes a TradingView-style intraday session chart
(`frontend/src/components/SessionChart.jsx`) fed by `GET /api/chart/session`.
It draws recent 15-minute candles plus the actionable zone levels so a client
can read the last result and the next possible session in one view without a
live data stream.

- **Session completeness is market-aware.** A stored day is only treated as a
  completed session after the 16:00 IST close. If today's market is still
  running, the chart uses the last completed session for the result and shows
  today's levels as the next possible session — it does not jump ahead to
  tomorrow.
- **Quick filters** (Latest / Today / Next / Prev) mirror TradingView-style
  session switching. A custom `from`/`to` date filter is also available.
- **Multi-session candle window.** The default view shows the last few sessions
  together (for example yesterday and today) rather than a single day, so the
  price action context is visible.
- **Slim level lines instead of boxes.** Each zone is drawn as one thin line at
  its key price. The actionable next-session lines are dashed violet and
  labelled on the price axis; completed results appear as compact chips under
  the chart (HELD / TOUCHED / BROKE / NOT REACHED).
- **Data is fetched on demand.** Opening the page or pressing the chart's
  **Refresh** button calls the API again for the selected symbol and window;
  there is no background live stream.

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
string, an auth code, or the whole redirect URL — whatever the provider showed
you. Fyers issues both the auth code and the access token as long JWTs, so the
payload is inspected before the provider is called: an auth code is exchanged
automatically, and a token for a different app id or from a previous day is
rejected with that exact reason instead of the generic
`Could not authenticate the user`.

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

The catalogue lives in PostgreSQL — `tracked_symbols` and `symbol_aliases` —
and `GET /api/symbols/catalog` serves it to the interface, so a symbol added in
the admin panel appears in every picker, job and API without a code change.

- A new installation starts tracking `NSE:NIFTY50-INDEX`, `NSE:NIFTYBANK-INDEX`
  and `NSE:MIDCPNIFTY-INDEX`, and seeds the alias table; both are editable
  afterwards and are only used on an empty database.
- Aliases are rows, not constants: `NIFTY` → `NSE:NIFTY50-INDEX` ships as seed
  data and administrators add their own under **Symbol shortcuts**. Anything
  unknown is passed to the provider unchanged, so `NSE:RELIANCE-EQ` or
  `MCX:CRUDEOILM25SEPFUT` work immediately.
- One symbol is flagged as the landing symbol (`is_default`); that is what a
  visitor sees before choosing anything, and deleting it promotes another.
- A symbol with no candles yet answers every endpoint with an empty result
  instead of failing, so adding one never breaks a screen.
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

Saving a token only saves the token. History is fetched when you ask for it —
optionally right there in the token dialog (default: don't fetch anything), or
any time from the **Data seeding** tab. Progress is visible under **Broker
connections → Data sync activity**.

Seeding the same period twice, or a period that overlaps one already stored, is
safe: candles are upserted on `(symbol, resolution, timestamp)`, so a re-run
repairs gaps instead of duplicating rows. Two seeds for the same symbol never
run at once either — the second caller's window is merged into the run that
owns the slot (an atomic claim on `job_runs`, so it holds across processes),
and any dates it still needs are fetched as a follow-up when that run
finishes.

### Adding another broker provider

“Any broker” cannot safely mean that arbitrary APIs work without integration:
each provider has different authentication, symbols and candle payloads. The
application itself is generic. Implement `BrokerAdapter` in
`backend/app/brokers/<provider>_adapter.py`, then add one `BrokerType` entry to
`registry.py`, including the credential fields the admin UI should render.
No route, job or UI code needs to change. Fyers is the first registered
provider.

## Strategy documentation

`docs/METHODOLOGY.md` explains, in the order the engine computes them: the
basis session (high/low/close/range), the central pivot range and its
NARROW/NORMAL/WIDE classification, the 21 weighted level families and round
numbers, how levels cluster into a zone (`lo…hi`, `Level`, `Built from`), the
star rating, the next-session zone map (R1…R4 / AT / S1…S4), the per-zone
outcome flags (touched, bounced, broke, held), the session measurements (gap %,
gap fill, trend day, open position) and every base-rate table — by strength, by
side, by CPR day type, by opening position, the gap-fill curve, the CPR
day-type matrix, the daily-OHLC cross-check and weekday behaviour — plus the
tunable parameters and how to read the numbers honestly.

Administrators read the same file inside the app under **Strategy &
definitions**, alongside the parameter values in force on that installation.

## Instrument master and the trading calendar

Two reference datasets are kept in PostgreSQL and refreshed in the background —
by the market-close job, on startup when they are stale, or on demand.

**`instruments`** holds every contract the provider publishes: cash, indices,
futures and options with `lot_size`, `tick_size`, `expiry_date`, `strike`,
`option_type`, `underlying` and `isin`. The **Instruments** tab searches it and
answers the questions that need it — every expiry for NIFTY, the lot size of
each, the full option chain for one expiry — without touching the provider.

- `GET /api/instruments?q=&type=&underlying=&expiry=` — search contracts
- `GET /api/instruments/underlyings` — everything with a derivatives chain,
  with its lot size and next expiry
- `GET /api/instruments/expiries?underlying=NIFTY` — expiries with contract
  counts and lot size
- `GET /api/instruments/{symbol}/contract` — one contract in full
- `POST /api/admin/instruments/refresh` — re-download the masters

A segment that fails to download never loses the others, and a completely
failed run keeps the record of the last good one.

**Trading holidays** are no longer typed in. `POST /api/admin/holidays/sync`
(also run by the daily job) tries three sources in order: the broker adapter's
`fetch_holidays(year)` when the provider publishes one, then the exchange's
public holiday master, then inference from the candles already stored — a
weekday inside the covered range with no candles was a holiday. Each row
records where it came from, and dates entered by hand are never overwritten.

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

Because the job runs after close, the **session chart and dashboard panels**
always treat the last stored day as completed only once 16:00 IST has passed.
Until then the UI keeps today's incomplete candles out of the "last completed
session" calculation, so clients see the last complete result and today's
levels as the next possible session.

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
