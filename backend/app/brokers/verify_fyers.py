"""
app/brokers/verify_fyers.py — Pre-flight sanity check for Fyers API integration (DEVELOPER_BIBLE.md §5.2).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Load .env
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# 2. Correct package import
from app.brokers.fyers_adapter import FyersAdapter

adapter = FyersAdapter()

print("=" * 60)
print("1. TESTING AUTHENTICATION / PING")
print("=" * 60)
status = adapter.auth_status()
print(f"Connected : {status.connected}")
print(f"Message   : {status.message}")

if not status.connected:
    print("\n[STOP] Authentication failed. Check your token.")
    exit(1)

print("\n" + "=" * 60)
print("2. TESTING HISTORICAL DAILY CANDLES (NSE:NIFTY50-INDEX)")
print("=" * 60)
try:
    df = adapter.fetch_historical(
        symbol="NSE:NIFTY50-INDEX",
        resolution="D",
        date_from="2026-08-01",
        date_to="2026-08-14"
    )
    print("Latest 3 daily candles (verify OHLC against Fyers terminal):")
    print(df.tail(3))
except Exception as e:
    print(f"Historical fetch error: {e}")

print("\n" + "=" * 60)
print("3. TESTING LIVE QUOTE / LTP")
print("=" * 60)
try:
    quote = adapter.fetch_live_quote("NSE:NIFTY50-INDEX")
    print("Live Quote Data:")
    for k, v in quote.items():
        print(f"  {k:5s} : {v}")
except Exception as e:
    print(f"Live quote fetch error: {e}")