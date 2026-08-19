"""
seed.py - load a CSV of intraday bars into the database and build history.

    python scripts/seed.py path/to/bars.csv

Run this once so the app starts with real base rates instead of an empty
sample. Safe to re-run; bars are upserted on (symbol, timestamp).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))
os.environ.setdefault('ZONEAPP_API_KEY', 'seed-only')

from app.db import Store
from app.brokers.csv_adapter import CSVAdapter
from app.service import run_eod, ZoneParams

def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: python scripts/seed.py <csv-path> [symbol]')
    csv = sys.argv[1]
    symbol = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('ZONEAPP_SYMBOL', 'NSE:NIFTY50-INDEX')
    db = os.environ.get('ZONEAPP_DB', './data/local.duckdb')

    store = Store(db)
    df = CSVAdapter(csv).fetch_historical(symbol, '15', '1900-01-01', '2100-01-01')
    n = store.upsert_bars(df, symbol, 'csv-seed')
    print(f'ingested {n:,} bars for {symbol}')

    res = run_eod(store, symbol, ZoneParams(), rebuild_all=True)
    print(res)
    c = store.counts(symbol)
    print(f"bars={int(c['bars']):,}  sessions={int(c['sessions']):,}  zone_obs={int(c['zone_obs']):,}")

if __name__ == '__main__':
    main()
