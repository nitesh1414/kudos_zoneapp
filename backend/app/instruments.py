"""Instrument master: every tradable contract, kept in the database.

The provider publishes one CSV per segment listing each contract with its lot
size, tick size, expiry, strike and option type. Those files are downloaded in
the background and upserted into ``instruments``, so the application can answer
"what are NIFTY's expiries and lot sizes?" from PostgreSQL instead of hitting
the provider on every keystroke.
"""
import csv
import io
from datetime import datetime, timezone

import requests

from .db import records

SOURCES = {
    "NSE cash & indices": "https://public.fyers.in/sym_details/NSE_CM.csv",
    "NSE futures & options": "https://public.fyers.in/sym_details/NSE_FO.csv",
    "NSE currency": "https://public.fyers.in/sym_details/NSE_CD.csv",
    "BSE cash & indices": "https://public.fyers.in/sym_details/BSE_CM.csv",
    "BSE futures & options": "https://public.fyers.in/sym_details/BSE_FO.csv",
    "MCX commodities": "https://public.fyers.in/sym_details/MCX_COM.csv",
}

SYNC_KEY = "instruments_sync"
STALE_HOURS = 20  # masters change daily (new strikes, rolled expiries)

# Seeded when the table is empty so the pickers work before the first download.
MAJOR_INDICES = [
    ("NIFTY 50", "NSE:NIFTY50-INDEX", "NIFTY"),
    ("NIFTY BANK", "NSE:NIFTYBANK-INDEX", "BANKNIFTY"),
    ("NIFTY MIDCAP SELECT", "NSE:MIDCPNIFTY-INDEX", "MIDCPNIFTY"),
    ("NIFTY FINANCIAL SERVICES", "NSE:FINNIFTY-INDEX", "FINNIFTY"),
    ("NIFTY NEXT 50", "NSE:NIFTYNXT50-INDEX", "NIFTYNXT50"),
    ("NIFTY 100", "NSE:NIFTY100-INDEX", "NIFTY100"),
    ("NIFTY 500", "NSE:NIFTY500-INDEX", "NIFTY500"),
    ("NIFTY IT", "NSE:NIFTYIT-INDEX", "NIFTYIT"),
    ("NIFTY AUTO", "NSE:NIFTYAUTO-INDEX", "NIFTYAUTO"),
    ("NIFTY PHARMA", "NSE:NIFTYPHARMA-INDEX", "NIFTYPHARMA"),
    ("SENSEX", "BSE:SENSEX-INDEX", "SENSEX"),
    ("BANKEX", "BSE:BANKEX-INDEX", "BANKEX"),
]

# Column layout of the provider's header-less masters.
COL = dict(fytoken=0, name=1, exch_type=2, lot_size=3, tick_size=4, isin=5,
           expiry=8, symbol=9, exchange=10, segment=11, underlying=13,
           strike=15, option_type=16)


def _num(value, cast=float, default=None):
    try:
        text = str(value).strip()
        return cast(float(text)) if text not in ("", "-", "0.0000000000") or cast is float else default
    except (TypeError, ValueError):
        return default


def _expiry(value):
    """Masters carry the expiry as a unix timestamp; blank for cash."""
    try:
        stamp = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).date()


def parse_row(record, segment, source_name):
    """One CSV line → an instrument dict, or None when it is not a contract."""
    if len(record) <= COL["underlying"]:
        return None
    symbol = (record[COL["symbol"]] or "").strip()
    if not symbol or ":" not in symbol:
        return None
    option_type = (record[COL["option_type"]] or "").strip().upper() if len(record) > COL["option_type"] else ""
    if option_type in ("XX", "-"):
        option_type = ""
    expiry = _expiry(record[COL["expiry"]]) if len(record) > COL["expiry"] else None
    strike = _num(record[COL["strike"]]) if len(record) > COL["strike"] else None
    if strike is not None and strike <= 0:
        strike = None

    if option_type in ("CE", "PE"):
        kind = option_type
    elif expiry:
        kind = "FUT"
    elif symbol.endswith("-INDEX"):
        kind = "INDEX"
    else:
        kind = "EQ"

    return dict(
        symbol=symbol,
        name=(record[COL["name"]] or record[COL["underlying"]] or symbol).strip(),
        exchange=(record[COL["exchange"]] or symbol.split(":")[0]).strip(),
        segment=segment, source=source_name, instrument_type=kind,
        underlying=(record[COL["underlying"]] or "").strip().upper() or None,
        expiry_date=expiry, strike=strike, option_type=option_type or None,
        lot_size=_num(record[COL["lot_size"]], int, None),
        tick_size=_num(record[COL["tick_size"]]),
        isin=(record[COL["isin"]] or "").strip() or None,
        fytoken=(record[COL["fytoken"]] or "").strip() or None,
    )


UPSERT = """INSERT INTO instruments(symbol,name,exchange,segment,source,instrument_type,underlying,
        expiry_date,strike,option_type,lot_size,tick_size,isin,fytoken,updated_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
    ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, exchange=excluded.exchange,
        segment=excluded.segment, source=excluded.source, instrument_type=excluded.instrument_type,
        underlying=excluded.underlying, expiry_date=excluded.expiry_date, strike=excluded.strike,
        option_type=excluded.option_type, lot_size=excluded.lot_size, tick_size=excluded.tick_size,
        isin=excluded.isin, fytoken=excluded.fytoken, updated_at=now()"""


def save(store, rows):
    if not rows:
        return 0
    values = [(r["symbol"], r["name"], r["exchange"], r["segment"], r["source"], r["instrument_type"],
               r["underlying"], r["expiry_date"], r["strike"], r["option_type"], r["lot_size"],
               r["tick_size"], r["isin"], r["fytoken"]) for r in rows]
    with store.connection() as con:
        with con.cursor() as cur:
            for start in range(0, len(values), 5000):     # keep statements bounded
                cur.executemany(UPSERT, values[start:start + 5000])
    return len(values)


def seed_indices(store):
    """Enough to work offline: the headline indices are always present."""
    rows = [dict(symbol=symbol, name=name, exchange=symbol.split(":")[0], segment="Major indices",
                 source="builtin", instrument_type="INDEX", underlying=under, expiry_date=None,
                 strike=None, option_type=None, lot_size=None, tick_size=None, isin=None, fytoken=None)
            for name, symbol, under in MAJOR_INDICES]
    return save(store, rows)


def fetch_master(url, timeout=45):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def refresh(store, fetch=fetch_master, sources=None):
    """Download every master and upsert it. Safe to re-run: rows are upserted
    on the symbol, so contracts keep their identity and expired ones simply
    stop being refreshed."""
    started = datetime.now(timezone.utc)
    by_segment, errors, total = {}, {}, 0
    for segment, url in (sources or SOURCES).items():
        try:
            text = fetch(url)
        except Exception as exc:                       # one segment must not stop the rest
            errors[segment] = str(exc)[:200]
            continue
        rows = []
        for record in csv.reader(io.StringIO(text)):
            parsed = parse_row(record, segment, url)
            if parsed:
                rows.append(parsed)
        by_segment[segment] = save(store, rows)
        total += by_segment[segment]
    summary = dict(at=started.isoformat(), finished_at=datetime.now(timezone.utc).isoformat(),
                   total=total, by_segment=by_segment, errors=errors)
    if total:
        store.kv_set(SYNC_KEY, summary)
    else:
        # Everything failed (offline, provider down): keep the last good sync on
        # record and just note the failure, so the UI still shows real numbers.
        previous = last_sync(store) or {}
        store.kv_set(SYNC_KEY, {**previous, "last_error_at": summary["finished_at"], "errors": errors})
    return summary


def last_sync(store):
    return store.kv_get(SYNC_KEY, default=None)


def is_stale(store, hours=STALE_HOURS):
    sync = last_sync(store)
    if not sync or not sync.get("total"):
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(sync["finished_at"])
    except (KeyError, ValueError):
        return True
    return age.total_seconds() > hours * 3600


# ------------------------------------------------------------------ queries
def search(store, query="", segment=None, instrument_type=None, underlying=None,
           expiry=None, limit=100):
    where, args = ["TRUE"], []
    for term in str(query or "").upper().split():
        where.append("(upper(symbol) LIKE ? OR upper(name) LIKE ?)")
        args += [f"%{term}%", f"%{term}%"]
    if segment:
        where.append("segment = ?"); args.append(segment)
    if instrument_type:
        where.append("instrument_type = ?"); args.append(instrument_type.upper())
    if underlying:
        where.append("underlying = ?"); args.append(underlying.upper())
    if expiry:
        where.append("expiry_date = ?"); args.append(expiry)
    args.append(min(max(int(limit), 1), 500))
    return records(store.q(f"""SELECT symbol,name,exchange,segment,instrument_type,underlying,expiry_date,
               strike,option_type,lot_size,tick_size,isin
        FROM instruments WHERE {' AND '.join(where)}
        ORDER BY (instrument_type='INDEX') DESC, expiry_date NULLS FIRST, strike NULLS FIRST, symbol
        LIMIT ?""", args))


def underlyings(store, query="", limit=200):
    args = []
    filter_sql = ""
    if query:
        filter_sql = "AND upper(underlying) LIKE ?"
        args.append(f"%{query.upper()}%")
    args.append(min(max(int(limit), 1), 500))
    return records(store.q(f"""SELECT underlying,
               count(*) FILTER (WHERE instrument_type='FUT') AS futures,
               count(*) FILTER (WHERE instrument_type IN ('CE','PE')) AS options,
               count(DISTINCT expiry_date) FILTER (WHERE expiry_date IS NOT NULL) AS expiries,
               max(lot_size) AS lot_size,
               min(expiry_date) FILTER (WHERE expiry_date >= current_date) AS next_expiry
        FROM instruments WHERE underlying IS NOT NULL {filter_sql}
        GROUP BY underlying HAVING count(*) FILTER (WHERE expiry_date IS NOT NULL) > 0
        ORDER BY options DESC, underlying LIMIT ?""", args))


def expiries(store, underlying, include_past=False):
    clause = "" if include_past else "AND expiry_date >= current_date"
    return records(store.q(f"""SELECT expiry_date, count(*) AS contracts,
               count(*) FILTER (WHERE instrument_type='FUT') AS futures,
               count(*) FILTER (WHERE option_type='CE') AS calls,
               count(*) FILTER (WHERE option_type='PE') AS puts,
               max(lot_size) AS lot_size, min(strike) AS min_strike, max(strike) AS max_strike
        FROM instruments WHERE underlying = ? AND expiry_date IS NOT NULL {clause}
        GROUP BY expiry_date ORDER BY expiry_date""", [str(underlying).upper()]))


def contract(store, symbol):
    row = store.one("""SELECT symbol,name,exchange,segment,instrument_type,underlying,expiry_date,
               strike,option_type,lot_size,tick_size,isin,updated_at
        FROM instruments WHERE symbol = ?""", [symbol])
    return dict(row) if row else None


def stats(store):
    rows = records(store.q("""SELECT instrument_type, count(*) AS n FROM instruments
                              GROUP BY instrument_type ORDER BY n DESC"""))
    segments = records(store.q("""SELECT segment, count(*) AS n, max(updated_at) AS updated_at
                                  FROM instruments GROUP BY segment ORDER BY n DESC"""))
    total = store.one("SELECT count(*) AS n FROM instruments")
    return dict(total=int((total or {}).get("n") or 0), by_type=rows, by_segment=segments,
                last_sync=last_sync(store), stale=is_stale(store))
