"""Administrator-managed watchlist of symbols the platform tracks.

Every symbol here is fetched and run through the zone engine, whether or not a
client is assigned to it. Client accounts still point at one symbol each; the
union of both lists is what the seeder and the market-close job work on.
"""
import json
import os

# Convenience aliases so an administrator can type "NIFTY" instead of the
# provider's exact contract name.
ALIASES = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "NIFTY50": "NSE:NIFTY50-INDEX",
    "NIFTY 50": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "NIFTYBANK": "NSE:NIFTYBANK-INDEX",
    "BANK NIFTY": "NSE:NIFTYBANK-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
}

DEFAULT_RESOLUTIONS = ("15", "D")  # 15 drives the zone engine, D is for context


def normalize(symbol: str) -> str:
    """Uppercase, trim and expand known aliases. Unknown symbols pass through
    unchanged so any provider symbol keeps working."""
    clean = " ".join(str(symbol or "").strip().upper().split())
    if not clean:
        raise ValueError("Symbol must not be empty")
    return ALIASES.get(clean, clean)


def default_symbol() -> str:
    return normalize(os.getenv("ZONEAPP_SYMBOL", "NSE:NIFTY50-INDEX"))


def tracked(store, active_only: bool = True):
    """Watchlist rows with the data volume already stored for each symbol."""
    rows = store.q(f"""SELECT t.symbol, t.label, t.resolutions, t.broker_id, t.active, t.created_at,
               b.name AS broker_name,
               (SELECT count(*) FROM intraday_bars i WHERE i.symbol = t.symbol) AS bars,
               (SELECT count(DISTINCT o.target_date) FROM zone_outcomes o WHERE o.symbol = t.symbol) AS sessions,
               (SELECT max(d) FROM intraday_bars i WHERE i.symbol = t.symbol) AS last_bar_date,
               (SELECT count(*) FROM users u WHERE u.symbol = t.symbol AND u.role = 'client') AS clients
        FROM tracked_symbols t LEFT JOIN broker_connections b ON b.id = t.broker_id
        {'WHERE t.active = true' if active_only else ''}
        ORDER BY t.symbol""")
    from .db import records
    return records(rows)


def add(store, symbol: str, label: str = "", resolutions=None, broker_id=None):
    clean = normalize(symbol)
    selected = [str(r) for r in (resolutions or DEFAULT_RESOLUTIONS)]
    if "15" not in selected:
        selected.append("15")
    store.exec("""INSERT INTO tracked_symbols(symbol,label,resolutions,broker_id,active)
        VALUES (?,?,?::jsonb,?,true)
        ON CONFLICT(symbol) DO UPDATE SET label=excluded.label, resolutions=excluded.resolutions,
            broker_id=excluded.broker_id, active=true""",
        [clean, label.strip(), json.dumps(selected), broker_id])
    return clean


def update(store, symbol: str, label=None, resolutions=None, broker_id=None,
           active=None, broker_set=False):
    clean = normalize(symbol)
    sets, values = [], []
    if label is not None:
        sets.append("label=?"); values.append(label.strip())
    if resolutions is not None:
        selected = [str(r) for r in resolutions]
        if "15" not in selected:
            selected.append("15")
        sets.append("resolutions=?::jsonb"); values.append(json.dumps(selected))
    if broker_set:
        sets.append("broker_id=?"); values.append(broker_id)
    if active is not None:
        sets.append("active=?"); values.append(active)
    if sets:
        store.exec(f"UPDATE tracked_symbols SET {','.join(sets)} WHERE symbol=?", values + [clean])
    return clean


def remove(store, symbol: str, purge_data: bool = False):
    clean = normalize(symbol)
    store.exec("DELETE FROM tracked_symbols WHERE symbol=?", [clean])
    if purge_data:
        for table in ("intraday_bars", "zone_sheets", "zone_outcomes"):
            store.exec(f"DELETE FROM {table} WHERE symbol=?", [clean])
    return clean


def all_symbols(store):
    """Every symbol the platform must keep up to date: the watchlist plus any
    symbol a client account is pointed at."""
    rows = store.q("""SELECT symbol FROM tracked_symbols WHERE active = true
                      UNION
                      SELECT symbol FROM users WHERE role = 'client' AND active = true
                      ORDER BY symbol""")
    found = [] if rows.empty else [r["symbol"] for r in rows.to_dict("records")]
    return found or [default_symbol()]
