"""PostgreSQL/TimescaleDB persistence for ZoneApp.

PostgreSQL stores users, broker connections and computed results.  When the
TimescaleDB extension is installed, ``intraday_bars`` is converted to a
hypertable. The application remains usable on plain PostgreSQL as well.
"""
import json
import math
import os
import re
from contextlib import contextmanager

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from .auth import new_encryption_key, use_key_provider

def records(df):
    """DataFrame → JSON-safe list of dicts.

    pandas turns SQL NULLs in mixed columns into NaN/NaT, which are not valid
    JSON and made FastAPI return 500s (for example a client with no broker
    assigned). Every API response built from a DataFrame goes through here.
    """
    if df is None or len(df) == 0:
        return []
    return [
        {k: (None if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
             or v is pd.NaT else v)
         for k, v in row.items()}
        for row in df.astype(object).where(pd.notnull(df), None).to_dict("records")
    ]


SCHEMA = """
CREATE TABLE IF NOT EXISTS intraday_bars (
    symbol TEXT NOT NULL, resolution TEXT NOT NULL DEFAULT '15',
    ts TIMESTAMP NOT NULL, d DATE NOT NULL,
    o DOUBLE PRECISION, h DOUBLE PRECISION, l DOUBLE PRECISION,
    c DOUBLE PRECISION, v DOUBLE PRECISION, source TEXT,
    PRIMARY KEY (symbol, resolution, ts)
);
CREATE TABLE IF NOT EXISTS zone_sheets (
    symbol TEXT NOT NULL, basis_date DATE NOT NULL, target_date DATE,
    label TEXT NOT NULL, lo DOUBLE PRECISION, hi DOUBLE PRECISION,
    key_px DOUBLE PRECISION, key_name TEXT, stars INTEGER,
    weight DOUBLE PRECISION, members TEXT, day_type TEXT,
    cpr_pct DOUBLE PRECISION, range_pct DOUBLE PRECISION, params_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (symbol,basis_date,label)
);
CREATE TABLE IF NOT EXISTS zone_outcomes (
    symbol TEXT NOT NULL, target_date DATE NOT NULL, label TEXT NOT NULL,
    stars INTEGER, key_px DOUBLE PRECISION, key_name TEXT,
    lo DOUBLE PRECISION, hi DOUBLE PRECISION, touched BOOLEAN,
    bounced BOOLEAN, broke BOOLEAN, held BOOLEAN, opened_inside BOOLEAN,
    day_type TEXT, gap_pct DOUBLE PRECISION, open_pos TEXT,
    PRIMARY KEY (symbol,target_date,label)
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v JSONB);
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','client')),
    symbol TEXT NOT NULL DEFAULT 'NSE:NIFTY50-INDEX',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS broker_connections (
    id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, broker_type TEXT NOT NULL,
    credentials JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolutions JSONB NOT NULL DEFAULT '["15","D"]'::jsonb,
    token_updated_at TIMESTAMPTZ, token_expires_at TIMESTAMPTZ,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS client_brokers (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    broker_id BIGINT REFERENCES broker_connections(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS tracked_symbols (
    symbol TEXT PRIMARY KEY, label TEXT NOT NULL DEFAULT '',
    resolutions JSONB NOT NULL DEFAULT '["15","D"]'::jsonb,
    broker_id BIGINT REFERENCES broker_connections(id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS symbol_aliases (
    alias TEXT PRIMARY KEY, symbol TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS market_holidays (
    holiday_date DATE PRIMARY KEY, label TEXT NOT NULL DEFAULT 'Market holiday',
    source TEXT NOT NULL DEFAULT 'manual', exchange TEXT NOT NULL DEFAULT 'NSE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS instruments (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    exchange TEXT, segment TEXT, source TEXT,
    instrument_type TEXT,                 -- INDEX / EQ / FUT / CE / PE
    underlying TEXT,                      -- short name, e.g. NIFTY
    expiry_date DATE, strike DOUBLE PRECISION, option_type TEXT,
    lot_size INTEGER, tick_size DOUBLE PRECISION,
    isin TEXT, fytoken TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_instruments_underlying ON instruments(underlying, expiry_date);
CREATE INDEX IF NOT EXISTS idx_instruments_type ON instruments(instrument_type);
CREATE INDEX IF NOT EXISTS idx_instruments_expiry ON instruments(expiry_date);
CREATE INDEX IF NOT EXISTS idx_instruments_name ON instruments(lower(name));
CREATE TABLE IF NOT EXISTS job_runs (
    id BIGSERIAL PRIMARY KEY, job_date DATE NOT NULL, broker_id BIGINT,
    symbol TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'market-close',
    status TEXT NOT NULL, detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
    UNIQUE(job_date,broker_id,symbol,kind)
);
CREATE INDEX IF NOT EXISTS idx_bars_symbol_date ON intraday_bars(symbol,d);
CREATE INDEX IF NOT EXISTS idx_outcomes_symbol_date ON zone_outcomes(symbol,target_date);
"""

DAILY_SQL = """
SELECT symbol, resolution, d,
 (array_agg(o ORDER BY ts))[1] AS o, max(h) AS h, min(l) AS l,
 (array_agg(c ORDER BY ts DESC))[1] AS c, sum(v) AS v, count(*) AS n_bars
FROM intraday_bars GROUP BY symbol,resolution,d
"""


class Store:
    def __init__(self, dsn: str | None = None):
        self._enc_key = None
        self.dsn = dsn or os.getenv("DATABASE_URL")
        if not self.dsn:
            raise RuntimeError(
                "DATABASE_URL is not set. Copy backend/.env.example to backend/.env and set "
                "DATABASE_URL=postgresql://user:password@host:5432/zoneapp")
        if not self.dsn.startswith(("postgresql://", "postgres://")):
            raise RuntimeError(
                f"DATABASE_URL must be a PostgreSQL URL (postgresql://...), got: {self.dsn.split(':')[0]}://…")
        self._init_schema()
        # Share one encryption key across the API, the worker and the CLI
        # scripts so credentials saved in one are readable in the others.
        use_key_provider(self._encryption_key)

    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn, row_factory=dict_row) as con:
            yield con

    def _init_schema(self):
        with self.connection() as con:
            con.execute(SCHEMA)
            # Forward migrations for installations created before multi-timeframe
            # storage and daily broker-token reminders were introduced.
            con.execute("ALTER TABLE intraday_bars ADD COLUMN IF NOT EXISTS resolution TEXT NOT NULL DEFAULT '15'")
            con.execute("ALTER TABLE broker_connections ADD COLUMN IF NOT EXISTS resolutions JSONB NOT NULL DEFAULT '[\"15\",\"D\"]'::jsonb")
            con.execute("ALTER TABLE broker_connections ADD COLUMN IF NOT EXISTS token_updated_at TIMESTAMPTZ")
            con.execute("ALTER TABLE broker_connections ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ")
            con.execute("CREATE INDEX IF NOT EXISTS idx_bars_symbol_resolution_date ON intraday_bars(symbol,resolution,d)")
            # job_runs gained a 'kind' so seeding and the market-close job can
            # both record a run for the same broker/symbol on the same day.
            con.execute("ALTER TABLE job_runs ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'market-close'")
            con.execute("ALTER TABLE tracked_symbols ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE")
            con.execute("ALTER TABLE market_holidays ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual'")
            con.execute("ALTER TABLE market_holidays ADD COLUMN IF NOT EXISTS exchange TEXT NOT NULL DEFAULT 'NSE'")
            con.execute("ALTER TABLE market_holidays ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()")
            job_key = con.execute("""SELECT conname, pg_get_constraintdef(oid) definition FROM pg_constraint
                WHERE conrelid='job_runs'::regclass AND contype='u'""").fetchone()
            if job_key and "kind" not in job_key["definition"]:
                con.execute(f'ALTER TABLE job_runs DROP CONSTRAINT "{job_key["conname"]}"')
                con.execute("ALTER TABLE job_runs ADD CONSTRAINT job_runs_run_key UNIQUE(job_date,broker_id,symbol,kind)")
            pkey = con.execute("SELECT pg_get_constraintdef(oid) definition FROM pg_constraint WHERE conrelid='intraday_bars'::regclass AND contype='p'").fetchone()
            if pkey and "resolution" not in pkey["definition"]:
                con.execute("ALTER TABLE intraday_bars DROP CONSTRAINT intraday_bars_pkey")
                con.execute("ALTER TABLE intraday_bars ADD PRIMARY KEY(symbol,resolution,ts)")
        # TimescaleDB is optional and may be restricted on managed PostgreSQL.
        # It runs in its own transaction: a failure here used to roll back the
        # migrations above, leaving plain-PostgreSQL installations un-migrated.
        try:
            with self.connection() as con:
                con.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
                con.execute("SELECT create_hypertable('intraday_bars','ts',if_not_exists => TRUE, migrate_data => TRUE)")
        except Exception:
            pass

    def _encryption_key(self) -> str:
        """Installation key, created once and kept in the kv table. Only used
        when ZONEAPP_ENCRYPTION_KEY is not configured."""
        if self._enc_key is None:
            row = self.one("SELECT v FROM kv WHERE k='encryption_key'")
            if row and row["v"]:
                self._enc_key = row["v"]
            else:
                self._enc_key = new_encryption_key()
                self.kv_set("encryption_key", self._enc_key)
        return self._enc_key

    @staticmethod
    def _sql(sql):
        # Existing service queries use DB-API qmark placeholders.
        return re.sub(r"\?", "%s", sql)

    def q(self, sql, params=None):
        with self.connection() as con:
            cur = con.execute(self._sql(sql), params or [])
            rows = cur.fetchall()
            return pd.DataFrame(rows, columns=[d.name for d in cur.description])

    def exec(self, sql, params=None):
        with self.connection() as con:
            con.execute(self._sql(sql), params or [])

    def one(self, sql, params=None):
        with self.connection() as con:
            return con.execute(self._sql(sql), params or []).fetchone()

    def kv_get(self, key, default=None):
        row = self.one("SELECT v FROM kv WHERE k=?", [key])
        return default if not row else row["v"]

    def kv_set(self, key, value):
        with self.connection() as con:
            con.execute("INSERT INTO kv(k,v) VALUES (%s,%s::jsonb) ON CONFLICT(k) DO UPDATE SET v=excluded.v", [key, json.dumps(value)])

    def upsert_bars(self, df, symbol: str, source: str, resolution: str = "15"):
        if df is None or df.empty:
            return 0
        d = df.copy()
        if "v" not in d: d["v"] = 0.0
        rows = [(symbol, str(resolution), r.ts.to_pydatetime(), r.ts.date(), float(r.o), float(r.h),
                 float(r.l), float(r.c), float(r.v or 0), source) for r in d.itertuples()]
        sql = """INSERT INTO intraday_bars(symbol,resolution,ts,d,o,h,l,c,v,source)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                 ON CONFLICT(symbol,resolution,ts) DO UPDATE SET d=excluded.d,o=excluded.o,h=excluded.h,
                 l=excluded.l,c=excluded.c,v=excluded.v,source=excluded.source"""
        with self.connection() as con:
            with con.cursor() as cur: cur.executemany(sql, rows)
        return len(rows)

    def daily(self, symbol, min_bars=20, resolution="15"):
        return self.q(f"SELECT * FROM ({DAILY_SQL}) t WHERE symbol=? AND resolution=? AND n_bars>=? ORDER BY d", [symbol,resolution,min_bars])

    def last_complete_day(self, symbol, min_bars=20):
        df=self.daily(symbol,min_bars); return None if df.empty else df.iloc[-1]

    def bars_for_day(self, symbol, d, resolution="15"):
        return self.q("SELECT ts,o,h,l,c FROM intraday_bars WHERE symbol=? AND resolution=? AND d=? ORDER BY ts", [symbol,resolution,d])

    def bars_range(self, symbol, date_from, date_to, resolution="15", limit=5000):
        """Candles for a date window (inclusive), oldest first, for charting."""
        return self.q("SELECT ts,o,h,l,c,v FROM intraday_bars WHERE symbol=? AND resolution=? AND d BETWEEN ? AND ? ORDER BY ts LIMIT ?",
                      [symbol,resolution,date_from,date_to,limit])

    def recent_bars(self, symbol, resolution="15", limit=500):
        return self.q("SELECT ts,o,h,l,c,v FROM intraday_bars WHERE symbol=? AND resolution=? ORDER BY ts DESC LIMIT ?", [symbol,resolution,limit]).sort_values("ts")

    def save_sheet(self, symbol, sheet, target_date, params_hash):
        zones=list(sheet.resistances)+list(sheet.supports)+([sheet.at_zone] if sheet.at_zone else [])
        rows=[(symbol,sheet.basis_date,target_date,z.label,z.lo,z.hi,z.key,z.key_name,z.stars,z.weight,z.members,sheet.day_type,sheet.cpr_pct,sheet.range_pct,params_hash) for z in zones]
        with self.connection() as con:
            con.execute("DELETE FROM zone_sheets WHERE symbol=%s AND basis_date=%s",[symbol,sheet.basis_date])
            with con.cursor() as cur: cur.executemany("""INSERT INTO zone_sheets(symbol,basis_date,target_date,label,lo,hi,key_px,key_name,stars,weight,members,day_type,cpr_pct,range_pct,params_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",rows)
        return len(rows)

    def get_sheet(self,symbol,basis_date):
        return self.q("SELECT * FROM zone_sheets WHERE symbol=? AND basis_date=? ORDER BY key_px DESC",[symbol,basis_date])

    def save_outcomes(self,symbol,target_date,recs,day_type,gap_pct,open_pos):
        rows=[(symbol,target_date,r['label'],r['stars'],r['key'],r['key_name'],r['lo'],r['hi'],r['touched'],r['bounced'],r['broke'],r['held'],r['opened_inside'],day_type,gap_pct,open_pos) for r in recs]
        with self.connection() as con:
            con.execute("DELETE FROM zone_outcomes WHERE symbol=%s AND target_date=%s",[symbol,target_date])
            with con.cursor() as cur: cur.executemany("INSERT INTO zone_outcomes(symbol,target_date,label,stars,key_px,key_name,lo,hi,touched,bounced,broke,held,opened_inside,day_type,gap_pct,open_pos) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",rows)
        return len(rows)

    def counts(self,symbol):
        row=self.one("""SELECT (SELECT count(*) FROM intraday_bars WHERE symbol=?) bars,
        (SELECT count(DISTINCT target_date) FROM zone_outcomes WHERE symbol=?) sessions,
        (SELECT count(*) FROM zone_outcomes WHERE symbol=?) zone_obs""",[symbol,symbol,symbol])
        # zone_observations is the name the API and UI use.
        return {**row, "zone_observations": row["zone_obs"]}
