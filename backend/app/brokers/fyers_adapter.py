"""
app/brokers/fyers_adapter.py — Fyers API v3 integration with dynamic token loading.
"""

import os
from datetime import datetime
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
        "5": "5",
        "15": "15",
        "30": "30",
        "60": "60",
    }

    SYMBOL_MAP = {
        "NIFTY": "NSE:NIFTY50-INDEX",
        "NIFTY50": "NSE:NIFTY50-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
        "NIFTYBANK": "NSE:NIFTYBANK-INDEX",
        "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    }

    def __init__(self, client_id: str | None = None, access_token: str | None = None):
        self.client_id = client_id or os.getenv("FYERS_CLIENT_ID", "937RN4D2JZ-100")
        
        # Check environment or .fyers_token file
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

        payload = {
            "symbol": fyers_sym,
            "resolution": fyers_res,
            "date_format": "1",
            "range_from": date_from,
            "range_to": date_to,
            "cont_flag": "1",
        }

        try:
            res = self.client.history(data=payload)
        except Exception as e:
            raise BrokerError(f"Network error during Fyers history fetch: {str(e)}") from e

        if not isinstance(res, dict) or res.get("s") != "ok":
            msg = res.get("message", "History fetch failed") if isinstance(res, dict) else str(res)
            raise BrokerError(f"Fyers history API error: {msg}", raw=res)

        candles = res.get("candles", [])
        if not candles:
            raise BrokerError(
                f"No candle data returned for {fyers_sym} ({date_from} to {date_to})",
                raw=res,
            )

        df = pd.DataFrame(candles, columns=["ts_raw", "o", "h", "l", "c", "v"])
        df["ts"] = pd.to_datetime(df["ts_raw"], unit="s", utc=True).dt.tz_convert(
            ZoneInfo("Asia/Kolkata")
        ).dt.tz_localize(None)

        df["o"] = df["o"].astype(float)
        df["h"] = df["h"].astype(float)
        df["l"] = df["l"].astype(float)
        df["c"] = df["c"].astype(float)
        df["v"] = df["v"].fillna(0.0).astype(float)

        return df[["ts", "o", "h", "l", "c", "v"]].sort_values("ts").reset_index(drop=True)

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
            "ts": datetime.now(),
            "ltp": float(v_data.get("lp", 0.0)),
            "o": float(v_data.get("open_price", cmd.get("o", 0.0))),
            "h": float(v_data.get("high_price", cmd.get("h", 0.0))),
            "l": float(v_data.get("low_price", cmd.get("l", 0.0))),
            "c": float(v_data.get("prev_close_price", cmd.get("c", 0.0))),
            "v": float(v_data.get("volume", 0.0)),
        }