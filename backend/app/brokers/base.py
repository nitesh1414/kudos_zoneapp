"""
base.py — the ONE interface every broker plugs into.

No broker SDK, no credentials, no network code lives in this file. This is
the contract. Concrete brokers go in brokers/<name>_adapter.py and import
their own SDK there, nowhere else in the app.

Nothing in zones.py, service.py, or main.py should import a broker SDK
directly. If you're about to do that outside brokers/, stop — see
DEVELOPER_BIBLE.md §5.3.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class AuthStatus:
    connected: bool
    message: str


class BrokerError(RuntimeError):
    """Always carries the raw provider response so failures are debuggable
    without guessing what the broker actually said."""

    def __init__(self, msg: str, raw=None):
        super().__init__(msg)
        self.raw = raw


class BrokerAdapter(ABC):
    """Every broker integration implements exactly this shape.

    Historical and live are kept separate on purpose — they serve
    different jobs at different frequencies (DEVELOPER_BIBLE.md §5.1).
    Zone computation only ever uses fetch_historical(); fetch_live_quote()
    is for a "current price" display only.
    """

    name: str

    @abstractmethod
    def auth_status(self) -> AuthStatus:
        """Cheap check: is the connection alive right now? Should be a
        lightweight profile/ping call, not a heavy data pull."""

    @abstractmethod
    def fetch_historical(self, symbol: str, resolution: str,
                          date_from: str, date_to: str) -> pd.DataFrame:
        """Returns a DataFrame with columns: ts, o, h, l, c, v (v optional,
        default 0.0). ts must be timezone-naive IST timestamps.

        Raise BrokerError on any failure — never return an empty or
        partial DataFrame silently. The caller needs to know a fetch
        failed, not infer it from missing rows later.
        """

    @abstractmethod
    def fetch_live_quote(self, symbol: str) -> dict:
        """Returns {ts, ltp, o, h, l, c, v}. Used only for a live-price
        badge on the dashboard — never for zone computation, which only
        ever reads completed sessions."""

    def fetch_holidays(self, year: int):
        """Optional. Trading holidays as [(date, label), …] straight from the
        provider. Raise NotImplementedError when the API has no such feed —
        the caller then falls back to the exchange list and, failing that, to
        inference from stored candles.
        """
        raise NotImplementedError(f"{self.name} does not publish a holiday calendar")

    def stream_live(self, symbol: str, on_tick):
        """Optional. Only implement if the broker supports websockets AND
        a live-updating dashboard feature is actually being built
        (DEVELOPER_BIBLE.md §8.3). Default: unsupported, caller should
        fall back to polling fetch_live_quote() on an interval.
        """
        raise NotImplementedError(f"{self.name} does not support streaming")
