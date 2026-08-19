"""
main.py - FastAPI application with Fyers Token Management & Notifications.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .brokers.base import BrokerError
from .brokers.csv_adapter import CSVAdapter
from .brokers.fyers_adapter import FyersAdapter
from .brokers.generate_token import exchange_code_for_token, get_login_url
from .db import Store
from .service import (
    ZoneParams,
    next_session_sheet,
    recent_sessions,
    run_eod,
    stats_days,
    stats_zones,
)

# ------------------------------ Config & Safety ------------------------------
DB_PATH = os.environ.get("ZONEAPP_DB", "./data/zoneapp.duckdb")
API_KEY = os.environ.get("ZONEAPP_API_KEY", "1380916c63c88e4305b7fb5009964a156b342c394edfbccf03")
SYMBOL = os.environ.get("ZONEAPP_SYMBOL", "NSE:NIFTY50-INDEX")
UPLOAD_DIR = os.environ.get("ZONEAPP_UPLOADS", "./data/uploads")

if not API_KEY:
    raise RuntimeError(
        "ZONEAPP_API_KEY is not set. Refusing to start - write endpoints "
        "would be unauthenticated."
    )

os.makedirs(UPLOAD_DIR, exist_ok=True)
store = Store(DB_PATH)

app = FastAPI(
    title="Zone Levels API",
    version="1.0.0",
    description="Next-session support/resistance zones with historical base rates.",
)


def require_key(x_api_key: Optional[str]):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def get_broker_adapter() -> FyersAdapter:
    return FyersAdapter()


def current_params() -> ZoneParams:
    saved = store.kv_get("zone_params")
    return ZoneParams(**saved) if saved else ZoneParams()


class ParamsIn(BaseModel):
    cluster_tol: float = 25.0
    zone_half_w: float = 15.0
    round_step: float = 100.0
    zones_per_side: int = 4
    break_pts: float = 15.0
    bounce_pts: float = 45.0


class TokenIn(BaseModel):
    access_token: str


class AuthCodeIn(BaseModel):
    auth_code_or_url: str


# ------------------------------ BROKER TOKEN & STATUS ------------------------------
@app.get("/api/broker/status")
def broker_status():
    """Returns real-time connection and token status with notifications."""
    adapter = get_broker_adapter()
    status = adapter.auth_status()
    return {
        "broker": "fyers",
        "connected": status.connected,
        "status_message": status.message,
        "action_required": not status.connected,
        "notification": "Token is active and ready." if status.connected else "ACTION REQUIRED: Broker token is missing or expired. Update token to enable live data and automated historical ingestion.",
    }


@app.get("/api/broker/login-url")
def broker_login_url():
    """Returns the Fyers login URL for manual token renewal."""
    return {"login_url": get_login_url()}


@app.post("/api/broker/token")
def set_broker_token(body: TokenIn, x_api_key: Optional[str] = Header(None)):
    """Directly sets and persists the access token."""
    require_key(x_api_key)
    token = body.access_token.strip()
    if not token:
        raise HTTPException(400, "access_token cannot be empty")

    token_file = Path(__file__).resolve().parent.parent / ".fyers_token"
    token_file.write_text(token)
    os.environ["FYERS_ACCESS_TOKEN"] = token

    # Verify new token
    status = get_broker_adapter().auth_status()
    return {
        "ok": True,
        "saved": True,
        "connected": status.connected,
        "message": status.message,
    }


@app.post("/api/broker/exchange-code")
def exchange_code(body: AuthCodeIn, x_api_key: Optional[str] = Header(None)):
    """Exchanges an auth_code or redirect URL for an access token."""
    require_key(x_api_key)
    try:
        token = exchange_code_for_token(body.auth_code_or_url)
        status = get_broker_adapter().auth_status()
        return {
            "ok": True,
            "connected": status.connected,
            "message": status.message,
        }
    except Exception as e:
        raise HTTPException(400, f"Code exchange failed: {str(e)}")


# ------------------------------ READ ENDPOINTS ------------------------------
@app.get("/api/health")
def health():
    c = store.counts(SYMBOL)
    adapter = get_broker_adapter()
    status = adapter.auth_status()

    return {
        "ok": True,
        "symbol": SYMBOL,
        "db": DB_PATH,
        "bars": int(c["bars"]),
        "sessions": int(c["sessions"]),
        "zone_observations": int(c["zone_obs"]),
        "broker": {
            "name": "fyers",
            "connected": status.connected,
            "message": status.message,
        },
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/quote/live")
def live_quote():
    adapter = get_broker_adapter()
    try:
        return adapter.fetch_live_quote(SYMBOL)
    except BrokerError as e:
        raise HTTPException(502, f"Failed to fetch live quote: {str(e)}")


@app.get("/api/levels/next")
def levels_next():
    sheet = next_session_sheet(store, SYMBOL, current_params())
    if sheet is None:
        raise HTTPException(404, "No complete session in the database yet")
    d = sheet.dict()
    d["disclaimer"] = (
        "Reference map computed from the last completed session. "
        "Not a trade signal and not a forecast."
    )
    return d


@app.get("/api/levels/{basis_date}")
def levels_for(basis_date: str):
    df = store.get_sheet(SYMBOL, basis_date)
    if df.empty:
        raise HTTPException(404, f"No stored sheet for basis {basis_date}")
    return df.to_dict("records")


@app.get("/api/stats/zones")
def api_stats_zones():
    return stats_zones(store, SYMBOL)


@app.get("/api/stats/days")
def api_stats_days():
    return stats_days(store, SYMBOL)


@app.get("/api/sessions")
def api_sessions(limit: int = Query(20, ge=1, le=200)):
    return recent_sessions(store, SYMBOL, limit)


@app.get("/api/params")
def api_params():
    return current_params().__dict__


# ------------------------------ WRITE ENDPOINTS ------------------------------
@app.post("/api/params")
def set_params(body: ParamsIn, x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    store.kv_set("zone_params", body.dict())
    return {
        "ok": True,
        "params": body.dict(),
        "note": (
            "Historical rows were computed with the previous parameters. "
            "Run /api/jobs/eod with rebuild_all=true so the whole history is consistent."
        ),
    }


@app.post("/api/ingest/broker")
def ingest_broker(
    days: int = Query(10, ge=1, le=365),
    resolution: str = Query("15", description="Candle timeframe: 15, D, etc."),
    x_api_key: Optional[str] = Header(None),
):
    require_key(x_api_key)
    adapter = get_broker_adapter()

    today = datetime.now().date()
    start_date = (today - timedelta(days=days)).isoformat()
    end_date = today.isoformat()

    try:
        df = adapter.fetch_historical(SYMBOL, resolution, start_date, end_date)
    except BrokerError as e:
        raise HTTPException(400, f"Broker fetch error: {str(e)}")

    n = store.upsert_bars(df, SYMBOL, "fyers")
    result = run_eod(store, SYMBOL, current_params(), rebuild_all=False)
    return {"ok": True, "bars_ingested": n, **result}


@app.post("/api/ingest/csv")
async def ingest_csv(
    file: UploadFile = File(...), x_api_key: Optional[str] = Header(None)
):
    require_key(x_api_key)
    path = os.path.join(UPLOAD_DIR, file.filename)
    with open(path, "wb") as f:
        f.write(await file.read())
    try:
        df = CSVAdapter(path).fetch_historical(SYMBOL, "15", "1900-01-01", "2100-01-01")
    except BrokerError as e:
        raise HTTPException(400, str(e))

    n = store.upsert_bars(df, SYMBOL, "csv")
    result = run_eod(store, SYMBOL, current_params(), rebuild_all=True)
    return {"ok": True, "bars_ingested": n, **result}


@app.post("/api/jobs/eod")
def job_eod(rebuild_all: bool = False, x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    return run_eod(store, SYMBOL, current_params(), rebuild_all=rebuild_all)


# ------------------------------ DASHBOARD ------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "templates", "index.html")) as f:
        return f.read()