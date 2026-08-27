# ZoneApp — Repository Overview & Work Log

> **Read this first.** One page to get oriented before starting any new work.
> It summarises what the repo is, how to run/test it, what has been built so far,
> and **which commit/PR did which piece of work**.

---

## How to maintain this document (read, then follow)

This file is the shared memory between the user and the agent across sessions.
After **every** work session, the agent must:

1. Add one row to the **Work log** table (commit hash + PR + one-line summary).
2. Update **Current state & open items** (what is merged, what is open, what is next).
3. If a new module/dir/concept was introduced, add it to **Repository map**.

Keep entries short and factual (hash, PR number, what changed). Do not delete old
rows — the log is append-only history.

---

## What this app is (one paragraph)

ZoneApp ingests completed intraday candles (15-minute + daily) for tracked symbols
and, from each completed session's High/Low/Close, derives a set of pivot/CPR-based
support/resistance **zones** for the *next* session, each with a historical base-rate.
It logs what each zone actually did (touched / bounced / broke / held) to build those
base rates. It is a **reference-map generator, not a signal generator** — it never
places orders and never gives buy/sell advice (see `DEVELOPER_BIBLE.md` §0/§8).

---

## Repository map

| Path | Purpose |
|---|---|
| `backend/app/zones.py` | Deterministic zone/level maths + outcome evaluation (single source of truth). |
| `backend/app/service.py` | EOD orchestration, completed-session awareness, `session_chart()` payload, stats. |
| `backend/app/db.py` | PostgreSQL schema/access; TimescaleDB hypertable when available. |
| `backend/app/main.py` | FastAPI app: auth, admin/client APIs, SPA hosting from `app/static`. |
| `backend/app/brokers/` | Provider-agnostic `BrokerAdapter`, registry, CSV + Fyers adapters. |
| `backend/app/{seeding,jobs,market_calendar,instruments,symbols,broker_store,auth}.py` | backfill, market-close worker, calendar, instrument master, watchlist, broker resolver, auth. |
| `frontend/src/pages/` | React tabs: `Overview`, `Zones`, `BaseRates`, `GapCpr`, `Sessions`(admin), `Login`, `admin/*`. |
| `frontend/src/components/SessionChart.jsx` | Overview TradingView-style chart card (quick views + date range + chips). |
| `frontend/src/components/chartLevels.js` | Canvas renderers that draw each session's zones only across its own candles (PR #7). |
| `frontend/src/lib/` | `api.js`, `auth.jsx`, `hooks.js` (fetch + formatters), `symbol.jsx`. |
| `frontend/mock/` | Dev-only mock API (`npm run dev:mock`) so the UI previews without Postgres. |
| `backend/tests/` | Unit + integration tests (`test_session_chart.py` runs without a DB). |
| `docs/METHODOLOGY.md` | Strategy/formula doc, served to the admin "Strategy & definitions" tab. |
| `docs/DEPLOYMENT_VPS.md` | VPS deployment guide. |
| `DEVELOPER_BIBLE.md` | Locked formulas, architecture rules, security rules, roadmap. |
| `deploy/` | systemd / nginx / cron examples. |

### Key concepts
- **Session** = one trading day. A session is *complete* once the market close has passed.
- **Basis** = the previous completed session's H/L/C; it fixes the zones for the next session.
- **Zone** = merged cluster of candidate levels; each has a `key` price, `label` (R1..R4/S1..S4/AT), a side, and a star rating (admin-only).
- **Outcome** = what a zone did that session: `HELD` / `TOUCHED` / `BROKE` / `NOT REACHED`.

---

## Run / build / test

```bash
# Full stack (Docker + TimescaleDB); creds admin / local-admin-password
./start_local.sh            # or: docker compose up --build   → http://localhost:8000

# Backend only (needs PostgreSQL; set backend/.env or DATABASE_URL)
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000

# Frontend dev against a running backend
cd frontend && npm run dev                 # http://localhost:5173 (proxies /api → :8000)

# Frontend dev with a mock backend (no Postgres needed)
cd frontend && npm run dev:mock            # ZONEAPP_MOCK=1

# Build the SPA into backend/app/static (this output IS committed)
cd frontend && npm run build

# Backend tests (DB tests self-skip when DATABASE_URL is unset)
cd backend && python -m unittest discover -s tests
```

Gotchas:
- `backend/app/static/` is committed build output — rebuild & commit it whenever the
  frontend changes (FastAPI serves it in production).
- The local git clone may be **shallow** (only the last couple of commits). The
  authoritative work timeline is the GitHub PR list, mirrored below.
- Tests that need PostgreSQL skip automatically; everything else runs anywhere.

---

## Work log (append-only; newest last)

Local git is shallow, so merge commits for PRs 1–5 are not present locally; the PR
number/title is the durable record.

| PR | Local commit | Summary |
|---|---|---|
| #1 | — (shallow) | Build the multi-client, broker-agnostic ZoneApp platform. |
| #2 | — (shallow) | Fyers as default broker, token-generation flow, last-3-month seeder, multi-panel NIFTY 50 dashboard, public landing page. |
| #3 | — (shallow) | Login-first React dashboard, multi-symbol tracking, on-demand seeding, fixes for four production bugs. |
| #4 | — (shallow) | Hide Sessions tab from clients (admin-only) + VPS deployment guide. |
| #5 | — (shallow) | Session chart on Overview; fix Sessions tab landing on Overview. |
| #6 | `a49b96f` | Improve session chart: TradingView-style candles, slim levels, correct next-session logic. |
| #7 | `0f9f288` (merged `2ab8dd5`) | Scope each session's zone levels to its own candles on the Overview chart. |

### Detail for the most recent work
- **PR #6 (`a49b96f`)** — rebuilt the Overview chart as a lightweight-charts
  candlestick view with quick views (latest/today/next/prev), a date-range picker,
  volume, an OHLCV legend, and forward next-session levels.
- **PR #7 (`0f9f288`)** — fixed the readability problem where every zone was a
  full-width line across all days. Now `session_chart()` returns `day_levels[]`
  (one scored sheet per session) and `chartLevels.js` draws each level only across
  its own session's candles, with per-day date stamps, day separators/tinting, the
  next-session sheet in the right-hand empty space, and per-day chips below.

---

## Current state & open items

- **Merged:** PRs #1–#7 (latest merge `2ab8dd5`). **Open:** none.
- Chart now renders per-session level segments; verified in-browser for a 3-session
  default view and an 8-session custom range.
- Possible next steps (from prior sessions, not yet started): directional session
  bias display (blocked on SEBI RA registration per DEVELOPER_BIBLE §8 — do not build
  until its conditions are met), and promoting gap-retest Variant B research.
