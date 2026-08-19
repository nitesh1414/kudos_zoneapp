"""
app/brokers/fyers_adapter.py — Fyers API v3 integration with dynamic token loading.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
from fyers_apiv3 import fyersModel

from .base import AuthStatus, BrokerAdapter, BrokerError


class FyersAdapter(BrokerAdapter):
    name = "fyers"

    RESOLUTION_MAP = {
        "D": "D",
        "1D": "D",
        "day": "D",
        "1": "1",
        "2": "2",
        "3": "3",
        "5": "5",
        "10": "10",
        "15": "15",
        "20": "20",
        "30": "30",
        "45": "45",
        "60": "60",
        "120": "120",
        "180": "180",
        "240": "240",
    }

    SYMBOL_MAP = {
        "NIFTY": "NSE:NIFTY50-INDEX",
        "NIFTY50": "NSE:NIFTY50-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
        "NIFTYBANK": "NSE:NIFTYBANK-INDEX",
        "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    }

    def __init__(self, client_id: str | None = None, access_token: str | None = None, **_):
        self.client_id = client_id or os.getenv("FYERS_CLIENT_ID")

        # Environment/file loading remains for backwards compatibility. Admin-
        # managed connections pass both values explicitly through the registry.
        token = access_token or os.getenv("FYERS_ACCESS_TOKEN")
        if not token:
            token_file = Path(__file__).resolve().parent.parent.parent / ".fyers_token"
            if token_file.exists():
                token = token_file.read_text().strip()

        self.access_token = token

        if not self.access_token:
            # We allow initialization so auth_status() can report token missing cleanly
            self.client = None
        else:
            self.client = fyersModel.FyersModel(
                client_id=self.client_id,
                token=self.access_token,
                is_async=False,
                log_path="",
            )

    def _normalize_symbol(self, symbol: str) -> str:
        clean = symbol.upper().strip()
        return self.SYMBOL_MAP.get(clean, clean)

    def auth_status(self) -> AuthStatus:
        if not self.access_token or not self.client:
            return AuthStatus(
                connected=False,
                message="Token Missing: Update FYERS_ACCESS_TOKEN via /api/broker/token",
            )
        try:
            res = self.client.get_profile()
            if isinstance(res, dict) and res.get("s") == "ok":
                name = res.get("data", {}).get("name", "Connected")
                return AuthStatus(connected=True, message=f"Connected as {name}")
            
            err_msg = res.get("message", "Token expired or invalid") if isinstance(res, dict) else str(res)
            return AuthStatus(connected=False, message=f"Token Expired/Invalid: {err_msg}")
        except Exception as e:
            return AuthStatus(connected=False, message=f"Auth Error: {str(e)}")

    def fetch_historical(
        self, symbol: str, resolution: str, date_from: str, date_to: str
    ) -> pd.DataFrame:
        if not self.client:
            raise BrokerError("Cannot fetch historical data: FYERS_ACCESS_TOKEN is missing or expired.")

        fyers_sym = self._normalize_symbol(symbol)
        fyers_res = self.RESOLUTION_MAP.get(str(resolution), str(resolution))

        start = datetime.strptime(date_from, "%Y-%m-%d").date()
        end = datetime.strptime(date_to, "%Y-%m-%d").date()
        if end < start:
            raise BrokerError("date_to must not be before date_from")

        # Fyers limits a request window. Chunking here means every caller can
        # request the full available date range without knowing provider limits.
        window_days = 366 if fyers_res == "D" else 100
        candles, cursor = [], start
        last_response = None
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=window_days - 1))
            payload = {
                "symbol": fyers_sym, "resolution": fyers_res, "date_format": "1",
                "range_from": cursor.isoformat(), "range_to": chunk_end.isoformat(),
                "cont_flag": "1",
            }
            try:
                res = self.client.history(data=payload)
            except Exception as e:
                raise BrokerError(f"Network error during Fyers history fetch: {str(e)}") from e
            last_response = res
            if isinstance(res, dict) and res.get("s") == "ok":
                candles.extend(res.get("candles", []))
            else:
                msg = res.get("message", "History fetch failed") if isinstance(res, dict) else str(res)
                # Empty historical windows are valid (before listing, holiday-only
                # range). Authentication/rate-limit errors are not silently ignored.
                if "no data" not in msg.lower() and "no_data" not in str(res).lower():
                    raise BrokerError(f"Fyers history API error: {msg}", raw=res)
            cursor = chunk_end + timedelta(days=1)

        if not candles:
            raise BrokerError(f"No candle data returned for {fyers_sym} ({date_from} to {date_to})", raw=last_response)

        df = pd.DataFrame(candles, columns=["ts_raw", "o", "h", "l", "c", "v"])
        df["ts"] = pd.to_datetime(df["ts_raw"], unit="s", utc=True).dt.tz_convert(
            ZoneInfo("Asia/Kolkata")
        ).dt.tz_localize(None)

        df["o"] = df["o"].astype(float)
        df["h"] = df["h"].astype(float)
        df["l"] = df["l"].astype(float)
        df["c"] = df["c"].astype(float)
        df["v"] = df["v"].fillna(0.0).astype(float)

        return df[["ts", "o", "h", "l", "c", "v"]].drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)

    def fetch_live_quote(self, symbol: str) -> dict:
        if not self.client:
            raise BrokerError("Cannot fetch live quote: FYERS_ACCESS_TOKEN is missing or expired.")

        fyers_sym = self._normalize_symbol(symbol)
        try:
            res = self.client.quotes(data={"symbols": fyers_sym})
        except Exception as e:
            raise BrokerError(f"Network error during quote fetch: {str(e)}") from e

        if not isinstance(res, dict) or res.get("s") != "ok":
            msg = res.get("message", "Quote fetch failed") if isinstance(res, dict) else str(res)
            raise BrokerError(f"Fyers quote API error for {fyers_sym}: {msg}", raw=res)

        quote_data = res.get("d", [])
        if not quote_data:
            raise BrokerError(f"Empty quote data returned for {fyers_sym}", raw=res)

        v_data = quote_data[0].get("v", {})
        cmd = v_data.get("cmd", {})

        return {
            "ts": datetime.now(ZoneInfo("Asia/Kolkata")),
            "ltp": float(v_data.get("lp", 0.0)),
            "o": float(v_data.get("open_price", cmd.get("o", 0.0))),
            "h": float(v_data.get("high_price", cmd.get("h", 0.0))),
            "l": float(v_data.get("low_price", cmd.get("l", 0.0))),
            "c": float(v_data.get("prev_close_price", cmd.get("c", 0.0))),
            "v": float(v_data.get("volume", 0.0)),
        }