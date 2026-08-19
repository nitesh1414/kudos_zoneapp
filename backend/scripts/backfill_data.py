"""
scripts/backfill_data.py — Standalone CLI backfill tool.

Fetches historical candles from Fyers for a specific date range,
stores them into DuckDB, and recalculates the EOD zone levels.

Usage:
    python -m scripts.backfill_data --days 120
    python -m scripts.backfill_data --start 2026-04-01 --end 2026-08-14 --resolution 15
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# 1. Setup paths and load environment variables
backend_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=backend_root / ".env")

from app.brokers.fyers_adapter import FyersAdapter
from app.db import Store
from app.service import ZoneParams, run_eod

DB_PATH = os.getenv("ZONEAPP_DB", str(backend_root / "data" / "zoneapp.duckdb"))
SYMBOL = os.getenv("ZONEAPP_SYMBOL", "NSE:NIFTY50-INDEX")


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill historical candle data into Zone App.")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Number of trailing days from today to fetch (e.g. 120 for 4 months).",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format (e.g. 2026-04-01).",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD format (e.g. 2026-08-14). Defaults to today.",
    )
    parser.add_argument(
        "--resolution",
        type=str,
        default="15",
        help="Candle resolution: '15' for 15-min bars, 'D' for daily bars. Default: 15.",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=SYMBOL,
        help=f"Symbol to fetch. Default: {SYMBOL}.",
    )
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Skip automatic recalculation of zone statistics after ingestion.",
    )
    return parser.parse_args()


def run_backfill():
    args = parse_args()

    # Determine date range
    today = datetime.now().date()
    if args.days:
        end_date = (today if not args.end else datetime.strptime(args.end, "%Y-%m-%d").date()).isoformat()
        start_date = (datetime.strptime(end_date, "%Y-%m-%d").date() - timedelta(days=args.days)).isoformat()
    elif args.start:
        start_date = args.start
        end_date = args.end if args.end else today.isoformat()
    else:
        # Default to 4 months (120 days)
        start_date = (today - timedelta(days=120)).isoformat()
        end_date = today.isoformat()

    print("=" * 65)
    print("BACKFILL JOB CONFIGURATION")
    print("=" * 65)
    print(f"Symbol     : {args.symbol}")
    print(f"Resolution : {args.resolution} min")
    print(f"Date Range : {start_date} -> {end_date}")
    print(f"Database   : {DB_PATH}")
    print("=" * 65)

    # 1. Initialize Adapter and Store
    adapter = FyersAdapter()
    auth = adapter.auth_status()
    if not auth.connected:
        print(f"[ERROR] Broker not connected: {auth.message}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Broker Status: {auth.message}")
    print("[1/3] Fetching historical data from Fyers...")

    try:
        df = adapter.fetch_historical(
            symbol=args.symbol,
            resolution=args.resolution,
            date_from=start_date,
            date_to=end_date,
        )
    except Exception as e:
        print(f"[ERROR] Data fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Fetched {len(df):,} candles.")
    print(f"     Earliest : {df['ts'].min()}")
    print(f"     Latest   : {df['ts'].max()}")

    # 2. Ingest into DuckDB
    print("\n[2/3] Writing to DuckDB...")
    store = Store(DB_PATH)
    n_upserted = store.upsert_bars(df, args.symbol, "fyers")
    print(f"[OK] Upserted {n_upserted:,} bars into database.")

    # 3. Recalculate EOD Zone Statistics
    if not args.skip_rebuild:
        print("\n[3/3] Recalculating EOD zones and base rates (rebuild_all=True)...")
        saved_params = store.kv_get("zone_params")
        params = ZoneParams(**saved_params) if saved_params else ZoneParams()
        
        result = run_eod(store, args.symbol, params, rebuild_all=True)
        print(f"[OK] EOD calculation complete:")
        for k, v in result.items():
            print(f"     - {k}: {v}")
    else:
        print("\n[3/3] Skipped EOD rebuild (--skip-rebuild set).")

    print("\n" + "=" * 65)
    print("BACKFILL COMPLETED SUCCESSFULLY")
    print("=" * 65)


if __name__ == "__main__":
    run_backfill()