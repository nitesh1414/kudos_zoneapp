# Adding a broker

No broker is chosen yet. When one is:

1. New file: `brokers/<name>_adapter.py`
2. Implement every method of `BrokerAdapter` (see `base.py`)
3. Read credentials from environment variables only — never hardcode,
   never put them in this repo, never put them in any Excel file
4. Register it in `main.py` where `CSVAdapter` is currently instantiated
5. Verify before trusting: pull a small (5-10 day) date range and manually
   compare 2-3 candles against a chart on the broker's own platform before
   wiring it into the EOD job

Full detail: DEVELOPER_BIBLE.md §5.
