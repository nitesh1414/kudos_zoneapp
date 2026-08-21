"""Trading-holiday calendar, sourced automatically rather than typed in.

Three sources are tried in order, so the calendar fills itself on any
installation:

1. **the broker** — an adapter may implement ``fetch_holidays(year)``;
2. **the exchange** — NSE publishes a public holiday master;
3. **the data itself** — a weekday inside the stored range with no candles for
   a liquid symbol was a holiday, which needs no network at all.

Dates an administrator entered by hand are never overwritten.
"""
from datetime import date, datetime, timedelta

import requests

NSE_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ZoneApp/3.0)",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


def _year(value=None):
    return int(value or date.today().year)


def broker_holidays(adapter, year=None):
    """Whatever the broker itself publishes, when the adapter supports it."""
    if adapter is None or not hasattr(adapter, "fetch_holidays"):
        return None
    try:
        rows = adapter.fetch_holidays(_year(year))
    except NotImplementedError:
        return None
    except Exception:
        return None
    return _clean(rows)


def exchange_holidays(year=None, timeout=20, get=None):
    """NSE's published trading-holiday list for the year."""
    try:
        response = (get or requests.get)(NSE_URL, headers=NSE_HEADERS, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None
    wanted = str(_year(year))
    rows = []
    for entries in (payload or {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            raw = str(entry.get("tradingDate") or entry.get("date") or "").strip()
            label = (entry.get("description") or "Market holiday").strip()
            parsed = _parse_date(raw)
            if parsed and str(parsed.year) == wanted:
                rows.append((parsed, label))
    return _clean(rows)


def inferred_holidays(store, symbol=None, year=None, min_symbols=1):
    """Weekdays inside the stored range that produced no candles at all.

    Works offline and is self-correcting: as soon as data exists for a day it
    stops being reported. Only the range actually covered by data is examined,
    so missing history is never mistaken for a holiday.
    """
    target = _year(year)
    params = [target]
    symbol_clause = ""
    if symbol:
        symbol_clause = "AND symbol = ?"
        params.append(symbol)
    frame = store.q(f"""SELECT min(d) AS first_day, max(d) AS last_day, count(DISTINCT d) AS days
        FROM intraday_bars WHERE extract(year from d) = ? {symbol_clause}""", params)
    if frame.empty or not frame.iloc[0]["first_day"] or int(frame.iloc[0]["days"] or 0) < 20:
        return []
    first_day, last_day = frame.iloc[0]["first_day"], frame.iloc[0]["last_day"]

    params = [first_day, last_day]
    if symbol:
        params.append(symbol)
    traded = store.q(f"""SELECT DISTINCT d FROM intraday_bars
        WHERE d BETWEEN ? AND ? {symbol_clause}""", params)
    have = set() if traded.empty else {row["d"] for row in traded.to_dict("records")}

    rows, cursor = [], first_day
    while cursor <= last_day:
        if cursor.weekday() < 5 and cursor not in have:
            rows.append((cursor, "No trading recorded"))
        cursor += timedelta(days=1)
    return _clean(rows)


def _parse_date(raw):
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _clean(rows):
    out = {}
    for value, label in rows or []:
        parsed = value if isinstance(value, date) else _parse_date(str(value))
        if parsed:
            out[parsed] = (label or "Market holiday").strip()[:120]
    return sorted(out.items())


def save(store, rows, source):
    """Store dates without touching anything an administrator typed in."""
    added = 0
    for holiday, label in rows:
        result = store.one("""INSERT INTO market_holidays(holiday_date,label,source)
            VALUES (?,?,?)
            ON CONFLICT(holiday_date) DO UPDATE SET label=excluded.label, source=excluded.source
                WHERE market_holidays.source <> 'manual'
            RETURNING holiday_date""", [holiday, label, source])
        added += 1 if result else 0
    return added


def sync(store, adapter=None, year=None, exchange_get=None):
    """Fill the calendar from the best source available."""
    target = _year(year)
    attempts = []

    rows = broker_holidays(adapter, target)
    if rows:
        return dict(ok=True, year=target, source="broker", found=len(rows),
                    saved=save(store, rows, "broker"), attempts=attempts)
    attempts.append("broker: not available")

    rows = exchange_holidays(target, get=exchange_get)
    if rows:
        return dict(ok=True, year=target, source="exchange", found=len(rows),
                    saved=save(store, rows, "exchange"), attempts=attempts)
    attempts.append("exchange: unreachable")

    rows = inferred_holidays(store, year=target)
    if rows:
        return dict(ok=True, year=target, source="inferred", found=len(rows),
                    saved=save(store, rows, "inferred"), attempts=attempts)
    attempts.append("inference: not enough stored candles")
    return dict(ok=False, year=target, source=None, found=0, saved=0, attempts=attempts,
                message="No holiday source is reachable yet. Add today's broker token, or enter "
                        "dates by hand — manual entries are never overwritten.")
