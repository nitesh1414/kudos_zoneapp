"""
app/brokers/verify_fyers.py — Pre-flight sanity check for Fyers API integration (DEVELOPER_BIBLE.md §5.2).
"""

# Importing the app package loads .env from backend/.env (or the repo root).
import app  # noqa: F401


from app.broker_store import BrokerUnavailable, load_adapter
from app.brokers.fyers_adapter import FyersAdapter
from app.db import Store

# Stored, administrator-managed credentials are the source of truth. The
# environment is only used when the database has no connection with a token.
try:
    _row, adapter = load_adapter(Store())
    print(f"Using stored broker connection '{_row['name']}' (id {_row['id']}).")
except Exception as exc:
    print(f"Stored connection unavailable ({exc}); using environment credentials.")
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