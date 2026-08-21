"""The symbol catalogue: what the platform tracks, stored in the database.

Nothing about symbols is hard-coded at runtime. The watchlist, the aliases an
administrator can type instead of a provider contract name, and which symbol a
new visitor lands on all live in PostgreSQL, so adding a symbol in the UI is
enough for the whole application — backend jobs and frontend pickers alike — to
pick it up.

The constants below are only *seed data*, inserted once on an empty database.
"""
import json
import os

# Seeded into symbol_aliases on first start; editable afterwards in the UI.
SEED_ALIASES = {
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

# Tracked automatically on an empty database, so a new installation has
# something to fetch as soon as a broker token exists.
DEFAULT_WATCHLIST = (
    ("NSE:NIFTY50-INDEX", "Nifty 50"),
    ("NSE:NIFTYBANK-INDEX", "Nifty Bank"),
    ("NSE:MIDCPNIFTY-INDEX", "Nifty Midcap Select"),
)


def _clean(symbol: str) -> str:
    clean = " ".join(str(symbol or "").strip().upper().split())
    if not clean:
        raise ValueError("Symbol must not be empty")
    return clean


def aliases(store=None) -> dict:
    """Alias → symbol. From the database when one is available."""
    if store is None:
        return dict(SEED_ALIASES)
    rows = store.q("SELECT alias, symbol FROM symbol_aliases ORDER BY alias")
    found = {} if rows.empty else {r["alias"]: r["symbol"] for r in rows.to_dict("records")}
    return found or dict(SEED_ALIASES)


def normalize(symbol: str, store=None) -> str:
    """Trim, upper-case and expand a stored alias. Unknown symbols pass through
    unchanged, so any provider contract name keeps working."""
    clean = _clean(symbol)
    return aliases(store).get(clean, clean)


def add_alias(store, alias: str, symbol: str):
    store.exec("""INSERT INTO symbol_aliases(alias,symbol) VALUES (?,?)
                  ON CONFLICT(alias) DO UPDATE SET symbol=excluded.symbol""",
               [_clean(alias), _clean(symbol)])


def remove_alias(store, alias: str):
    store.exec("DELETE FROM symbol_aliases WHERE alias=?", [_clean(alias)])


def seed_aliases(store):
    if not store.one("SELECT alias FROM symbol_aliases LIMIT 1"):
        for alias, symbol in SEED_ALIASES.items():
            add_alias(store, alias, symbol)


def tracked(store, active_only: bool = True):
    """Watchlist rows with the data volume already stored for each symbol."""
    rows = store.q(f"""SELECT t.symbol, t.label, t.resolutions, t.broker_id, t.active, t.is_default,
               t.created_at, b.name AS broker_name,
               (SELECT count(*) FROM intraday_bars i WHERE i.symbol = t.symbol) AS bars,
               (SELECT count(DISTINCT o.target_date) FROM zone_outcomes o WHERE o.symbol = t.symbol) AS sessions,
               (SELECT max(d) FROM intraday_bars i WHERE i.symbol = t.symbol) AS last_bar_date,
               (SELECT count(*) FROM users u WHERE u.symbol = t.symbol AND u.role = 'client') AS clients
        FROM tracked_symbols t LEFT JOIN broker_connections b ON b.id = t.broker_id
        {'WHERE t.active = true' if active_only else ''}
        ORDER BY t.is_default DESC, t.symbol""")
    from .db import records
    return records(rows)


def add(store, symbol: str, label: str = "", resolutions=None, broker_id=None):
    clean = normalize(symbol, store)
    selected = [str(r) for r in (resolutions or DEFAULT_RESOLUTIONS)]
    if "15" not in selected:
        selected.append("15")
    first = not store.one("SELECT symbol FROM tracked_symbols LIMIT 1")
    store.exec("""INSERT INTO tracked_symbols(symbol,label,resolutions,broker_id,active,is_default)
        VALUES (?,?,?::jsonb,?,true,?)
        ON CONFLICT(symbol) DO UPDATE SET label=excluded.label, resolutions=excluded.resolutions,
            broker_id=excluded.broker_id, active=true""",
        [clean, label.strip(), json.dumps(selected), broker_id, first])
    return clean


def update(store, symbol: str, label=None, resolutions=None, broker_id=None,
           active=None, is_default=None, broker_set=False):
    clean = normalize(symbol, store)
    if is_default:
        store.exec("UPDATE tracked_symbols SET is_default = (symbol = ?)", [clean])
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
    _ensure_a_default(store)
    return clean


def remove(store, symbol: str, purge_data: bool = False):
    clean = normalize(symbol, store)
    store.exec("DELETE FROM tracked_symbols WHERE symbol=?", [clean])
    if purge_data:
        for table in ("intraday_bars", "zone_sheets", "zone_outcomes"):
            store.exec(f"DELETE FROM {table} WHERE symbol=?", [clean])
    _ensure_a_default(store)
    return clean


def ensure_a_default(store):
    """Exactly one active symbol is the landing symbol. Prefers ZONEAPP_SYMBOL
    when it is tracked, so upgrades keep the symbol operators expect."""
    if store.one("SELECT symbol FROM tracked_symbols WHERE is_default = true AND active = true"):
        return
    preferred = _clean(os.getenv("ZONEAPP_SYMBOL", "NSE:NIFTY50-INDEX"))
    row = (store.one("SELECT symbol FROM tracked_symbols WHERE active = true AND symbol = ?", [preferred])
           or store.one("SELECT symbol FROM tracked_symbols WHERE active = true ORDER BY symbol LIMIT 1"))
    if row:
        store.exec("UPDATE tracked_symbols SET is_default = (symbol = ?)", [row["symbol"]])


_ensure_a_default = ensure_a_default  # internal alias


def all_symbols(store):
    """Every symbol the platform tracks, the default one first. Accounts are
    not tied to a symbol — this list is the single source of truth."""
    rows = store.q("SELECT symbol FROM tracked_symbols WHERE active = true ORDER BY is_default DESC, symbol")
    found = [] if rows.empty else [r["symbol"] for r in rows.to_dict("records")]
    return found or [normalize(os.getenv("ZONEAPP_SYMBOL", "NSE:NIFTY50-INDEX"))]


def default_symbol(store=None) -> str:
    """Which symbol a fresh visitor lands on."""
    if store is None:
        return normalize(os.getenv("ZONEAPP_SYMBOL", "NSE:NIFTY50-INDEX"))
    return all_symbols(store)[0]


def catalog(store, resolutions=()):
    """Everything the UI needs to render symbol pickers, from the database."""
    rows = tracked(store, active_only=False)
    return dict(
        symbols=[r for r in rows if r["active"]],
        inactive=[r for r in rows if not r["active"]],
        aliases=aliases(store),
        resolutions=list(resolutions),
        default=default_symbol(store),
    )
