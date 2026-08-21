"""
seed.py - Seed the database with last 3 months of market data from Fyers.

This uses the Fyers API to fetch the last 3 months of historical data for
the configured symbol, stores it in the database, and calculates zone levels.

Usage:
    python scripts/seed.py                  # Fetches last 3 months from Fyers
    python scripts/seed.py path/to/bars.csv # Loads from CSV file (legacy mode)

Environment variables (via .env or shell):
    FYERS_CLIENT_ID, FYERS_SECRET_KEY, FYERS_REDIRECT_URI
    FYERS_ACCESS_TOKEN or run generate_token.py first
    DATABASE_URL (defaults to .env value)
    ZONEAPP_SYMBOL (defaults to NSE:NIFTY50-INDEX)
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))
os.environ.setdefault('ZONEAPP_API_KEY', 'seed-only')

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

from app.db import Store
from app.broker_store import BrokerUnavailable, load_adapter
from app.brokers.csv_adapter import CSVAdapter
from app.brokers.fyers_adapter import FyersAdapter
from app.service import run_eod, ZoneParams


def resolve_adapter(store, symbol: str):
    """Prefer the token an administrator saved in the application; fall back to
    environment variables only when no stored connection has one."""
    try:
        row, adapter = load_adapter(store, symbol=symbol)
        print(f"[OK] Using stored broker connection '{row['name']}' (id {row['id']}).")
        return adapter
    except BrokerUnavailable as exc:
        print(f"[..] {exc}")
        print("[..] Falling back to FYERS_ACCESS_TOKEN from the environment.")
        return FyersAdapter()


def seed_from_fyers(store, symbol: str, days_back: int = 90):
    """Fetch last `days_back` days of data from Fyers and seed the database."""
    # Determine date range
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    date_from = (today - timedelta(days=days_back)).isoformat()
    date_to = today.isoformat()

    print(f"Fetching {symbol} data from {date_from} to {date_to} via Fyers API...")

    adapter = resolve_adapter(store, symbol)
    status = adapter.auth_status()

    if not status.connected:
        print(f"[ERROR] Fyers not connected: {status.message}")
        print("\nAdd today's token in the administrator panel")
        print("(Broker connections -> Daily token); seeding then starts on its own.")
        print("Alternatively run: cd backend && python -m app.brokers.generate_token\n")
        sys.exit(1)

    print(f"[OK] Fyers connected: {status.message}")

    # Fetch resolutions - always get 15-minute (needed for zones) and daily
    resolutions = ["15", "D"]
    total_bars = 0

    for resolution in resolutions:
        print(f"  Fetching {resolution} candles...", end=" ", flush=True)
        try:
            df = adapter.fetch_historical(
                symbol=symbol,
                resolution=resolution,
                date_from=date_from,
                date_to=date_to,
            )
            n = store.upsert_bars(df, symbol, "fyers-seed", resolution)
            total_bars += n
            print(f"{n:,} bars stored")
        except Exception as e:
            print(f"FAILED: {e}")

    print(f"\nTotal bars ingested: {total_bars:,}")

    # Recalculate EOD zones
    print("Recalculating zone levels...", end=" ", flush=True)
    saved_params = store.kv_get("zone_params")
    params = ZoneParams(**saved_params) if saved_params else ZoneParams()
    result = run_eod(store, symbol, params, rebuild_all=True)
    print("Done.")

    # Summary
    c = store.counts(symbol)
    print(f"\nSeed complete:")
    print(f"  Bars:     {int(c['bars']):,}")
    print(f"  Sessions: {int(c['sessions']):,}")
    print(f"  Zones:    {int(c['zone_observations']):,}")

    return result


def seed_from_csv(store, csv_path: str, symbol: str):
    """Legacy CSV-based seeding."""
    print(f"Loading CSV: {csv_path}")
    df = CSVAdapter(csv_path).fetch_historical(symbol, '15', '1900-01-01', '2100-01-01')
    n = store.upsert_bars(df, symbol, 'csv-seed')
    print(f'Ingested {n:,} bars for {symbol}')

    print("Recalculating zone levels...")
    res = run_eod(store, symbol, ZoneParams(), rebuild_all=True)
    print(res)
    c = store.counts(symbol)
    print(f"Bars={int(c['bars']):,}  Sessions={int(c['sessions']):,}  Zone Obs={int(c['zone_obs']):,}")
    return res


def main():
    store = Store()

    # If a CSV path is given, use legacy mode
    if len(sys.argv) >= 2 and not sys.argv[1].startswith('--'):
        seed_from_csv(store, sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.environ.get('ZONEAPP_SYMBOL', 'NSE:NIFTY50-INDEX'))
        return

    # Otherwise seed using Fyers API (last 3 months by default)
    symbol = os.environ.get('ZONEAPP_SYMBOL', 'NSE:NIFTY50-INDEX')
    days_back = 90

    # Parse optional arguments
    for arg in sys.argv[1:]:
        if arg.startswith('--days='):
            days_back = int(arg.split('=', 1)[1])
        elif arg.startswith('--symbol='):
            symbol = arg.split('=', 1)[1]
        elif arg == '--help' or arg == '-h':
            print(__doc__)
            sys.exit(0)

    seed_from_fyers(store, symbol, days_back)


if __name__ == '__main__':
    main()