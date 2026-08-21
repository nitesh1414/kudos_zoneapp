"""Stored broker credentials → a ready-to-use adapter.

Every dependent service (EOD job, seeding, CLI scripts) must resolve its
broker through this module. Before it existed each caller built the adapter
its own way, so a token added by an administrator lived only in the database
while `FyersAdapter()` looked for an environment variable or a token file and
reported "Token Missing".
"""
import os

from .auth import decrypt_credentials
from .brokers.registry import make_broker

SELECT = """SELECT id, name, broker_type, credentials, resolutions, enabled,
                   token_updated_at, token_expires_at
            FROM broker_connections"""


class BrokerUnavailable(RuntimeError):
    """No usable broker connection could be resolved."""


def connection(store, broker_id: int | None = None, symbol: str | None = None):
    """The connection to use: explicit id, else the one serving `symbol`,
    else the first enabled connection that has a token."""
    if broker_id is not None:
        row = store.one(f"{SELECT} WHERE id=?", [broker_id])
        if not row:
            raise BrokerUnavailable(f"Broker connection {broker_id} does not exist")
        return row
    if symbol:
        row = store.one(f"""SELECT b.id, b.name, b.broker_type, b.credentials, b.resolutions,
                b.enabled, b.token_updated_at, b.token_expires_at
            FROM broker_connections b
            JOIN client_brokers cb ON cb.broker_id = b.id
            JOIN users u ON u.id = cb.user_id
            WHERE b.enabled = true AND u.active = true AND u.symbol = ?
            ORDER BY b.token_expires_at DESC NULLS LAST LIMIT 1""", [symbol])
        if row:
            return row
    row = store.one(f"{SELECT} WHERE enabled=true ORDER BY token_expires_at DESC NULLS LAST, id LIMIT 1")
    if not row:
        raise BrokerUnavailable(
            "No broker connection is configured. Add one in the administrator panel.")
    return row


def credentials_for(store, broker_id: int | None = None, symbol: str | None = None):
    """Decrypted credentials for a stored connection, with the environment
    used only as a fallback for fields the connection does not carry."""
    row = connection(store, broker_id, symbol)
    creds = dict(decrypt_credentials(row["credentials"]) or {})
    creds.setdefault("client_id", os.getenv("FYERS_CLIENT_ID", ""))
    if not creds.get("access_token"):
        env_token = os.getenv("FYERS_ACCESS_TOKEN")
        if env_token:
            creds["access_token"] = env_token
    return row, creds


def load_adapter(store, broker_id: int | None = None, symbol: str | None = None,
                 require_token: bool = True):
    """Return ``(connection_row, adapter)`` built from stored credentials."""
    row, creds = credentials_for(store, broker_id, symbol)
    if require_token and not creds.get("access_token"):
        raise BrokerUnavailable(
            f"'{row['name']}' has no access token yet. Add today's token in the "
            f"administrator panel (Broker connections → Daily token).")
    return row, make_broker(row["broker_type"], creds)


def symbols_for(store, broker_id: int):
    """Watchlist entries this connection is responsible for: the ones pinned to
    it plus the ones that are not pinned to any connection."""
    rows = store.q("""SELECT symbol FROM tracked_symbols
                      WHERE active = true AND (broker_id IS NULL OR broker_id = ?)
                      ORDER BY symbol""", [broker_id])
    symbols = [] if rows.empty else [r["symbol"] for r in rows.to_dict("records")]
    if symbols:
        return symbols
    from .symbols import default_symbol
    return [default_symbol(store)]
