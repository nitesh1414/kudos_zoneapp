"""
health_check.py - the guard-row pattern from the old Excel workbook,
run as code instead of spreadsheet formulas. See DEVELOPER_BIBLE.md SS10.3.

Run this daily, right after the EOD job (same cron entry). Exits non-zero
if any issue is found, so it plugs into any alerting that watches exit
codes or cron's own failure-email behaviour.

USAGE
    python scripts/health_check.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))

from app.db import Store


def health_check(store: Store, symbol: str) -> list:
    issues = []
    daily = store.daily(symbol)
    if len(daily) < 2:
        return issues
    last, prev = daily.iloc[-1], daily.iloc[-2]

    if last.h < last.l:
        issues.append(f"{last.d}: high < low, impossible session")
    if last.n_bars < 20:
        issues.append(f"{last.d}: only {last.n_bars} bars, session may be incomplete")

    sheet = store.get_sheet(symbol, str(prev.d))
    if sheet.empty:
        issues.append(f"no zone sheet stored for basis {prev.d}")
    else:
        # the exact check that would have caught all three basis
        # self-reference incidents documented in DEVELOPER_BIBLE.md SS2.4.1
        row0 = sheet.iloc[0]
        if 'lo' in sheet.columns and 'hi' in sheet.columns:
            at_row = sheet[sheet.label == 'AT']
            if not at_row.empty:
                key = float(at_row.iloc[0].key_px)
                if abs(key - float(prev.c)) > 0.5:
                    issues.append(
                        f"AT zone key ({key}) does not match basis close "
                        f"({prev.c}) for {prev.d} - possible basis self-reference")

    return issues


if __name__ == '__main__':
    db = os.environ.get('ZONEAPP_DB', './data/zoneapp.duckdb')
    symbol = os.environ.get('ZONEAPP_SYMBOL', 'NSE:NIFTY50-INDEX')
    store = Store(db)
    issues = health_check(store, symbol)
    if issues:
        print(f"HEALTH CHECK: {len(issues)} issue(s) found")
        for i in issues:
            print(f"  - {i}")
        sys.exit(1)
    print("HEALTH CHECK: all clear")
    sys.exit(0)
