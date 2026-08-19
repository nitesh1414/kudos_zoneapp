"""
db.py - DuckDB storage.

DuckDB is a single file on disk. No server, no daemon, nothing to babysit
on the VPS. Back it up by copying the file.

TABLES
  intraday_bars   raw OHLC bars, one row per bar        (source of truth)
  daily           derived daily OHLC                    (view over bars)
  zone_sheets     computed zones, one row per zone      (basis -> target date)
  zone_outcomes   what each zone did on its target date
  kv              small key/value store (broker tokens, settings)

Everything downstream (stats, base rates, the dashboard) is derived from
these. Delete zone_sheets/zone_outcomes and rebuild any time - the bars are
the only thing you cannot regenerate.
"""
import os
import json
import threading
from datetime import date
from typing import Optional

import duckdb

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS intraday_bars (
    symbol   VARCHAR NOT NULL,
    ts       TIMESTAMP NOT NULL,
    d        DATE NOT NULL,
    o DOUBLE, h DOUBLE, l DOUBLE, c DOUBLE, v DOUBLE,
    source   VARCHAR,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS zone_sheets (
    symbol      VARCHAR NOT NULL,
    basis_date  DATE NOT NULL,
    target_date DATE,
    label       VARCHAR NOT NULL,
    lo DOUBLE, hi DOUBLE, key_px DOUBLE,
    key_name    VARCHAR,
    stars       INTEGER,
    weight      DOUBLE,
    members     VARCHAR,
    day_type    VARCHAR,
    cpr_pct     DOUBLE,
    range_pct   DOUBLE,
    params_hash VARCHAR,
    created_at  TIMESTAMP DEFAULT now(),
    PRIMARY KEY (symbol, basis_date, label)
);

CREATE TABLE IF NOT EXISTS zone_outcomes (
    symbol       VARCHAR NOT NULL,
    target_date  DATE NOT NULL,
    label        VARCHAR NOT NULL,
    stars        INTEGER,
    key_px       DOUBLE,
    key_name     VARCHAR,
    lo DOUBLE, hi DOUBLE,
    touched BOOLEAN, bounced BOOLEAN, broke BOOLEAN, held BOOLEAN,
    opened_inside BOOLEAN,
    day_type     VARCHAR,
    gap_pct      DOUBLE,
    open_pos     VARCHAR,
    PRIMARY KEY (symbol, target_date, label)
);

CREATE TABLE IF NOT EXISTS kv (
    k VARCHAR PRIMARY KEY,
    v VARCHAR
);
"""

DAILY_SQL = """
SELECT symbol, d,
       first(o ORDER BY ts) AS o,
       max(h) AS h, min(l) AS l,
       last(c ORDER BY ts) AS c,
       sum(v) AS v,
       count(*) AS n_bars
FROM intraday_bars
GROUP BY symbol, d
"""


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        self.path = path
        self._con = duckdb.connect(path)
        self._con.execute(SCHEMA)

    # ---------- low level ----------
    def q(self, sql, params=None):
        with _LOCK:
            return self._con.execute(sql, params or []).fetchdf()

    def exec(self, sql, params=None):
        with _LOCK:
            self._con.execute(sql, params or [])

    # ---------- kv ----------
    def kv_get(self, key, default=None):
        df = self.q("SELECT v FROM kv WHERE k = ?", [key])
        if df.empty:
            return default
        try:
            return json.loads(df.v.iloc[0])
        except Exception:
            return df.v.iloc[0]

    def kv_set(self, key, value):
        self.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", [key, json.dumps(value)])

    # ---------- bars ----------
    def upsert_bars(self, df, symbol: str, source: str):
        """df needs columns ts, o, h, l, c and optionally v."""
        if df is None or df.empty:
            return 0
        d = df.copy()
        if 'v' not in d.columns:
            d['v'] = 0.0
        d['symbol'] = symbol
        d['source'] = source
        d['d'] = d['ts'].dt.date
        d = d[['symbol', 'ts', 'd', 'o', 'h', 'l', 'c', 'v', 'source']]
        with _LOCK:
            self._con.register('incoming', d)
            self._con.execute("""
    DELETE FROM intraday_bars
    WHERE EXISTS (
        SELECT 1 
        FROM incoming 
        WHERE incoming.symbol = intraday_bars.symbol 
          AND incoming.ts = intraday_bars.ts
    )
""")
            self._con.execute("INSERT INTO intraday_bars SELECT * FROM incoming")
            self._con.unregister('incoming')
        return len(d)

    def daily(self, symbol: str, min_bars: int = 20):
        return self.q(f"""
            SELECT * FROM ({DAILY_SQL}) t
            WHERE symbol = ? AND n_bars >= ?
            ORDER BY d
        """, [symbol, min_bars])

    def last_complete_day(self, symbol: str, min_bars: int = 20):
        df = self.daily(symbol, min_bars)
        return None if df.empty else df.iloc[-1]

    def bars_for_day(self, symbol: str, d):
        return self.q("""
            SELECT ts, o, h, l, c FROM intraday_bars
            WHERE symbol = ? AND d = ? ORDER BY ts
        """, [symbol, d])

    # ---------- zone sheets ----------
    def save_sheet(self, symbol, sheet, target_date, params_hash):
        rows = []
        zones = list(sheet.resistances) + list(sheet.supports)
        if sheet.at_zone:
            zones.append(sheet.at_zone)
        for z in zones:
            rows.append((symbol, sheet.basis_date, target_date, z.label, z.lo, z.hi,
                         z.key, z.key_name, z.stars, z.weight, z.members,
                         sheet.day_type, sheet.cpr_pct, sheet.range_pct, params_hash))
        with _LOCK:
            self._con.execute(
                "DELETE FROM zone_sheets WHERE symbol = ? AND basis_date = ?",
                [symbol, sheet.basis_date])
            self._con.executemany("""
                INSERT INTO zone_sheets
                (symbol, basis_date, target_date, label, lo, hi, key_px, key_name,
                 stars, weight, members, day_type, cpr_pct, range_pct, params_hash)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows)
        return len(rows)

    def get_sheet(self, symbol, basis_date):
        return self.q("""
            SELECT * FROM zone_sheets
            WHERE symbol = ? AND basis_date = ?
            ORDER BY key_px DESC
        """, [symbol, basis_date])

    # ---------- outcomes ----------
    def save_outcomes(self, symbol, target_date, recs, day_type, gap_pct, open_pos):
        rows = [(symbol, target_date, r['label'], r['stars'], r['key'], r['key_name'],
                 r['lo'], r['hi'], r['touched'], r['bounced'], r['broke'], r['held'],
                 r['opened_inside'], day_type, gap_pct, open_pos) for r in recs]
        with _LOCK:
            self._con.execute(
                "DELETE FROM zone_outcomes WHERE symbol = ? AND target_date = ?",
                [symbol, target_date])
            self._con.executemany("""
                INSERT INTO zone_outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows)
        return len(rows)

    def counts(self, symbol: str):
        d = self.q("""
            SELECT
              (SELECT count(*) FROM intraday_bars WHERE symbol = ?)   AS bars,
              (SELECT count(DISTINCT target_date) FROM zone_outcomes WHERE symbol = ?) AS sessions,
              (SELECT count(*) FROM zone_outcomes WHERE symbol = ?)   AS zone_obs
        """, [symbol, symbol, symbol])
        return d.iloc[0].to_dict()
