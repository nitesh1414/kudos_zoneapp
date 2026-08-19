"""
csv_adapter.py — offline reference implementation. No network, no secrets.

This is what lets the rest of the app be built and tested before a broker
is chosen (DEVELOPER_BIBLE.md §5). Historical only; live quote raises,
since a CSV has no concept of "now".
"""
import os

import pandas as pd

from .base import BrokerAdapter, AuthStatus, BrokerError


class CSVAdapter(BrokerAdapter):
    name = "csv"

    def __init__(self, path: str):
        self.path = path

    def auth_status(self) -> AuthStatus:
        ok = os.path.exists(self.path)
        return AuthStatus(connected=ok,
                          message="File found" if ok else f"Not found: {self.path}")

    def fetch_historical(self, symbol: str, resolution: str,
                          date_from: str, date_to: str) -> pd.DataFrame:
        df = pd.read_csv(self.path)
        cols = {c.lower().strip(): c for c in df.columns}

        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            raise BrokerError(f"CSV missing a column for {names[0]}",
                              raw=list(df.columns))

        out = pd.DataFrame({
            'ts': pd.to_datetime(df[pick('time', 'timestamp', 'datetime', 'date')]),
            'o': df[pick('open', 'o')].astype(float),
            'h': df[pick('high', 'h')].astype(float),
            'l': df[pick('low', 'l')].astype(float),
            'c': df[pick('close', 'c')].astype(float),
        })
        vc = cols.get('volume') or cols.get('v')
        out['v'] = df[vc].astype(float) if vc else 0.0
        if out.ts.dt.tz is not None:
            out['ts'] = out.ts.dt.tz_localize(None)
        mask = (out.ts >= date_from) & (out.ts <= date_to)
        return out[mask].sort_values('ts').reset_index(drop=True)

    def fetch_live_quote(self, symbol: str) -> dict:
        raise BrokerError("CSVAdapter has no live data — this is historical-only")
