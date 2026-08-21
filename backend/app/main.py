"""ZoneApp multi-tenant FastAPI application."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .auth import (COOKIE_NAME, create_session, decrypt_credentials, delete_session,
                   encrypt_credentials, hash_password, session_user, verify_password)
from .broker_store import BrokerUnavailable, load_adapter, symbols_for
from .brokers.base import BrokerError
from .brokers.registry import INDIA_CANDLE_RESOLUTIONS, broker_types, get_broker_type, make_broker
from .db import Store
from .instruments import SOURCES, search_instruments
from .jobs import run_market_close
from .seeding import DEFAULT_DAYS, recent_runs, seed_broker
from .service import (ZoneParams, dashboard_payload, match_check, next_session_sheet, recent_sessions, run_eod, session_recap, stats_days, stats_zones)

API_KEY = os.getenv("ZONEAPP_API_KEY", "")
store = Store()

app = FastAPI(title="ZoneApp", version="3.0.0", description="Multi-client next-session market zones")
# Compiled React single-page app (frontend/ -> npm run build).
STATIC = Path(__file__).parent / "static"
SPA_INDEX = STATIC / "index.html"


def bootstrap_admin():
    username = os.getenv("ZONEAPP_ADMIN_USERNAME", "admin").strip().lower()
    password = os.getenv("ZONEAPP_ADMIN_PASSWORD")
    if not store.one("SELECT id FROM users WHERE role='admin' LIMIT 1"):
        if not password:
            raise RuntimeError("Set ZONEAPP_ADMIN_PASSWORD to create the first administrator")
        store.exec("INSERT INTO users(username,display_name,password_hash,role) VALUES (?,?,?,'admin')",
                   [username,"Administrator",hash_password(password)])


@app.on_event("startup")
def startup():
    bootstrap_admin()


def current_user(token=Cookie(None, alias=COOKIE_NAME)):
    user = session_user(store, token)
    if not user: raise HTTPException(401,"Please log in")
    return user


def admin_user(token=Cookie(None, alias=COOKIE_NAME)):
    user = current_user(token)
    if user["role"] != "admin": raise HTTPException(403,"Administrator access required")
    return user


def require_job_key(key):
    if not API_KEY or not key or not __import__("hmac").compare_digest(key, API_KEY):
        raise HTTPException(401,"Invalid job API key")


def params():
    saved=store.kv_get("zone_params"); return ZoneParams(**saved) if saved else ZoneParams()


class LoginIn(BaseModel): username: str; password: str
class ClientIn(BaseModel):
    username: str = Field(min_length=3,max_length=80)
    display_name: str = Field(min_length=1,max_length=120)
    password: str = Field(min_length=8,max_length=256)
    symbol: str = "NSE:NIFTY50-INDEX"
    broker_id: int | None = None
class ClientPatch(BaseModel):
    display_name: str | None=None; password: str | None=None; symbol: str | None=None
    broker_id: int | None=None; active: bool | None=None
class BrokerIn(BaseModel):
    name: str = Field(min_length=1,max_length=120); broker_type: str
    credentials: dict; enabled: bool=True
    resolutions: list[str] = Field(default_factory=lambda: list(INDIA_CANDLE_RESOLUTIONS))
class BrokerTokenIn(BaseModel):
    access_token: str = Field(min_length=10)
    # Saving a token immediately backfills history for the symbols that
    # depend on this connection, so other services never see empty tables.
    seed: bool = True
    seed_days: int = Field(default=DEFAULT_DAYS, ge=5, le=3650)
class SeedIn(BaseModel):
    days: int = Field(default=DEFAULT_DAYS, ge=5, le=3650)
    symbols: list[str] | None = None
class TokenExchangeIn(BaseModel):
    auth_code: str = Field(min_length=1)
class BackfillIn(BaseModel):
    symbol: str
    date_from: str = "2010-01-01"
    date_to: str | None = None
    resolutions: list[str] | None = None
class HolidayIn(BaseModel):
    holiday_date: str
    label: str = "Market holiday"
class ParamsIn(BaseModel):
    cluster_tol: float=25; zone_half_w: float=15; round_step: float=100
    zones_per_side: int=4; break_pts: float=15; bounce_pts: float=45
class GiftNiftyIn(BaseModel):
    ltp: float = Field(gt=0)
    pdc: float = Field(gt=0)
    captured_at: str | None = None
class DashboardQuery(BaseModel):
    date: str | None = None


# ------------------------------ ENTRY POINT ------------------------------
@app.get("/")
def root(token: str|None=Cookie(None,alias=COOKIE_NAME)):
    """There is no public landing page: visitors always start at the login
    screen and land on the dashboard once a session exists."""
    return RedirectResponse("/dashboard/overview" if session_user(store,token) else "/login")


@app.post("/api/auth/login")
def login(body: LoginIn):
    user=store.one("SELECT * FROM users WHERE lower(username)=lower(?) AND active=true",[body.username.strip()])
    if not user or not verify_password(body.password,user["password_hash"]):
        raise HTTPException(401,"Invalid username or password")
    token,expires=create_session(store,user["id"])
    response=JSONResponse({"ok":True,"role":user["role"],"redirect":"/"})
    response.set_cookie(COOKIE_NAME,token,httponly=True,samesite="lax",secure=os.getenv("ZONEAPP_SECURE_COOKIES","true").lower()=="true",expires=expires)
    return response
@app.post("/api/auth/logout")
def logout(token: str|None=Cookie(None,alias=COOKIE_NAME)):
    delete_session(store,token); response=JSONResponse({"ok":True}); response.delete_cookie(COOKIE_NAME); return response
@app.get("/api/me")
def me(user=Depends(current_user)): return dict(user)


# Admin: clients and broker connections
@app.get("/api/admin/clients")
def clients(_=Depends(admin_user)):
    return store.q("""SELECT u.id,u.username,u.display_name,u.symbol,u.active,u.created_at,
      cb.broker_id,b.name broker_name FROM users u LEFT JOIN client_brokers cb ON cb.user_id=u.id
      LEFT JOIN broker_connections b ON b.id=cb.broker_id WHERE u.role='client' ORDER BY u.created_at DESC""").to_dict("records")
@app.post("/api/admin/clients")
def add_client(body:ClientIn,_=Depends(admin_user)):
    try:
        with store.connection() as con:
            user=con.execute("INSERT INTO users(username,display_name,password_hash,role,symbol) VALUES (%s,%s,%s,'client',%s) RETURNING id",[body.username.strip().lower(),body.display_name.strip(),hash_password(body.password),body.symbol.strip()]).fetchone()
            if body.broker_id: con.execute("INSERT INTO client_brokers(user_id,broker_id) VALUES (%s,%s)",[user["id"],body.broker_id])
        return {"ok":True,"id":user["id"]}
    except Exception as exc:
        if "unique" in str(exc).lower(): raise HTTPException(409,"Username already exists")
        raise
@app.patch("/api/admin/clients/{user_id}")
def update_client(user_id:int,body:ClientPatch,_=Depends(admin_user)):
    updates=[]; values=[]
    for col,val in (("display_name",body.display_name),("symbol",body.symbol),("active",body.active)):
        if val is not None: updates.append(f"{col}=?"); values.append(val)
    if body.password is not None: updates.append("password_hash=?"); values.append(hash_password(body.password))
    if updates: store.exec(f"UPDATE users SET {','.join(updates)} WHERE id=? AND role='client'",values+[user_id])
    if "broker_id" in body.model_fields_set:
        if body.broker_id: store.exec("INSERT INTO client_brokers(user_id,broker_id) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET broker_id=excluded.broker_id",[user_id,body.broker_id])
        else: store.exec("DELETE FROM client_brokers WHERE user_id=?",[user_id])
    return {"ok":True}

@app.delete("/api/admin/clients/{user_id}")
def delete_client(user_id:int,_=Depends(admin_user)):
    """Remove a client login. Sessions and the broker assignment cascade."""
    row=store.one("SELECT id FROM users WHERE id=? AND role='client'",[user_id])
    if not row: raise HTTPException(404,"Client not found")
    store.exec("DELETE FROM users WHERE id=? AND role='client'",[user_id])
    return {"ok":True}

@app.get("/api/admin/broker-types")
def types(_=Depends(admin_user)): return broker_types()
@app.get("/api/admin/brokers")
def brokers(_=Depends(admin_user)):
    return store.q("""SELECT id,name,broker_type,resolutions,enabled,created_at,updated_at,
        token_updated_at,token_expires_at,
        CASE WHEN token_expires_at IS NULL THEN 'unknown' WHEN token_expires_at<=now() THEN 'expired'
             WHEN token_expires_at<=now()+interval '3 hours' THEN 'expiring' ELSE 'valid' END token_status
        FROM broker_connections ORDER BY id""").to_dict("records")
@app.post("/api/admin/brokers")
def add_broker(body:BrokerIn,background:BackgroundTasks,_=Depends(admin_user)):
    spec=next((x for x in broker_types() if x["key"]==body.broker_type),None)
    if not spec: raise HTTPException(400,"Unsupported broker type")
    # Only fields marked as required (default True) are mandatory
    required={f["name"] for f in spec["fields"] if f.get("required", True)}
    if not required.issubset(body.credentials): raise HTTPException(400,f"Missing required fields: {', '.join(sorted(required-set(body.credentials)))}")
    selected=[r for r in dict.fromkeys(body.resolutions) if r in INDIA_CANDLE_RESOLUTIONS]
    if "15" not in selected: selected.append("15")  # zone engine's canonical timeframe
    broker_type=get_broker_type(body.broker_type)
    # Only verify auth if an access_token was provided
    if body.credentials.get("access_token"):
        auth=make_broker(body.broker_type,body.credentials).auth_status()
        if not auth.connected: raise HTTPException(400,f"Broker was not saved: {auth.message}")
    now=datetime.now(timezone.utc)
    expiry=now+timedelta(hours=broker_type.token_ttl_hours) if broker_type.token_ttl_hours and body.credentials.get("access_token") else None
    row=store.one("""INSERT INTO broker_connections(name,broker_type,credentials,resolutions,token_updated_at,token_expires_at,enabled)
        VALUES (?,?,?::jsonb,?::jsonb,?,?,?) RETURNING id""",
        [body.name,body.broker_type,json.dumps(encrypt_credentials(body.credentials)),json.dumps(selected),now if expiry else None,expiry,body.enabled])
    seeded=[]
    if body.credentials.get("access_token"):
        seeded=symbols_for(store,row["id"])
        background.add_task(seed_broker,store,row["id"],DEFAULT_DAYS,params(),seeded)
    return {"ok":True,"id":row["id"],"seeding":bool(seeded),"seed_symbols":seeded}
@app.post("/api/brokers/{broker_id}/token")
def update_broker_token(broker_id:int,body:BrokerTokenIn,background:BackgroundTasks,user=Depends(current_user)):
    row=store.one("SELECT * FROM broker_connections WHERE id=?",[broker_id])
    if not row: raise HTTPException(404,"Broker not found")
    if user["role"] != "admin" and not store.one("SELECT 1 ok FROM client_brokers WHERE user_id=? AND broker_id=?",[user["id"],broker_id]):
        raise HTTPException(403,"This broker is not assigned to your account")
    credentials=decrypt_credentials(row["credentials"])
    credentials["access_token"]=body.access_token.strip()
    status=make_broker(row["broker_type"],credentials).auth_status()
    if not status.connected: raise HTTPException(400,f"Token was not saved: {status.message}")
    kind=get_broker_type(row["broker_type"]); now=datetime.now(timezone.utc)
    expires=now+timedelta(hours=kind.token_ttl_hours) if kind.token_ttl_hours else None
    store.exec("UPDATE broker_connections SET credentials=?::jsonb,token_updated_at=?,token_expires_at=?,updated_at=now() WHERE id=?",
               [json.dumps(encrypt_credentials(credentials)),now,expires,broker_id])
    seeded=[]
    if body.seed:
        seeded=symbols_for(store,broker_id) if user["role"]=="admin" else [user["symbol"]]
        background.add_task(seed_broker,store,broker_id,body.seed_days,params(),seeded)
    return {"ok":True,"connected":True,"message":status.message,"expires_at":expires,
            "seeding":bool(seeded),"seed_symbols":seeded,
            "seed_message":(f"Backfilling {body.seed_days} days for {', '.join(seeded)} in the background."
                            if seeded else "Token saved.")}


@app.post("/api/admin/brokers/{broker_id}/seed")
def seed_now(broker_id:int,body:SeedIn,background:BackgroundTasks,_=Depends(admin_user)):
    """Run the seeder for this connection (also runs automatically after a
    token is saved)."""
    try: load_adapter(store,broker_id=broker_id)
    except BrokerUnavailable as exc: raise HTTPException(400,str(exc))
    targets=body.symbols or symbols_for(store,broker_id)
    background.add_task(seed_broker,store,broker_id,body.days,params(),targets)
    return {"ok":True,"seeding":True,"seed_symbols":targets,
            "seed_message":f"Backfilling {body.days} days for {', '.join(targets)} in the background."}


@app.get("/api/admin/job-runs")
def job_runs(limit:int=20,_=Depends(admin_user)):
    return recent_runs(store,min(max(limit,1),100))

@app.get("/api/brokers/fyers/generate-url")
def fyers_generate_url(_=Depends(admin_user)):
    """Returns the Fyers OAuth authorization URL for the admin to visit."""
    try:
        from .brokers.generate_token import get_login_url
        url = get_login_url()
        return {"ok": True, "url": url}
    except Exception as e:
        raise HTTPException(400, f"Failed to generate login URL: {str(e)}")

@app.post("/api/brokers/fyers/exchange-token")
def fyers_exchange_token(body: TokenExchangeIn, _=Depends(admin_user)):
    """Exchange a Fyers auth_code for an access_token. Returns the token to be saved."""
    try:
        from .brokers.generate_token import exchange_code_for_token
        token = exchange_code_for_token(body.auth_code)
        return {"ok": True, "access_token": token}
    except Exception as e:
        raise HTTPException(400, f"Token exchange failed: {str(e)}")

@app.delete("/api/admin/brokers/{broker_id}")
def delete_broker(broker_id:int,_=Depends(admin_user)):
    store.exec("DELETE FROM broker_connections WHERE id=?",[broker_id]); return {"ok":True}
@app.post("/api/admin/brokers/{broker_id}/test")
def test_broker(broker_id:int,_=Depends(admin_user)):
    try:
        _,adapter=load_adapter(store,broker_id=broker_id)
        status=adapter.auth_status()
        return {"connected":status.connected,"message":status.message}
    except Exception as exc: return {"connected":False,"message":str(exc)}

@app.post("/api/admin/brokers/{broker_id}/backfill")
def backfill_broker(broker_id:int,body:BackfillIn,_=Depends(admin_user)):
    row=store.one("SELECT * FROM broker_connections WHERE id=?",[broker_id])
    if not row: raise HTTPException(404,"Broker not found")
    try:
        datetime.strptime(body.date_from,"%Y-%m-%d")
        date_to=body.date_to or datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        datetime.strptime(date_to,"%Y-%m-%d")
    except ValueError: raise HTTPException(400,"Dates must be YYYY-MM-DD")
    resolutions=body.resolutions or row["resolutions"]
    if any(r not in INDIA_CANDLE_RESOLUTIONS for r in resolutions): raise HTTPException(400,"Unsupported resolution")
    try: _,adapter=load_adapter(store,broker_id=broker_id)
    except BrokerUnavailable as exc: raise HTTPException(400,str(exc))
    counts={}
    try:
        for resolution in resolutions:
            frame=adapter.fetch_historical(body.symbol,resolution,body.date_from,date_to)
            counts[resolution]=store.upsert_bars(frame,body.symbol,row["broker_type"],resolution)
    except BrokerError as exc: raise HTTPException(400,str(exc))
    result=run_eod(store,body.symbol,params(),rebuild_all=True) if "15" in resolutions else {"ok":True,"message":"Candles stored; 15-minute data is required for zone results"}
    return {"ok":True,"symbol":body.symbol,"by_resolution":counts,**result}


def _strip_stars(payload: dict):
    """Star ratings are an administrator-only detail; clients see the base
    rates (touch/hold) instead, which is what the numbers actually mean."""
    for row in payload.get("zones", {}).get("rows", []) or []:
        row.pop("stars", None); row.pop("weight", None)
    for row in (payload.get("session_recap") or {}).get("zones", []) or []:
        row.pop("stars", None); row.pop("weight", None)
    return payload


@app.get("/api/dashboard")
def dashboard(date:str|None=None,user=Depends(current_user)):
    """Single round-trip payload for the client dashboard UI."""
    payload = dashboard_payload(store, user["symbol"], params())
    payload["authenticated"] = True
    payload["role"] = user["role"]
    payload["username"] = user["username"]
    payload["can_edit"] = (user["role"] == "admin")
    if date:
        r = session_recap(store, user["symbol"], date, params())
        m = match_check(store, user["symbol"], date, params())
        if r: payload["session_recap"] = r
        if m: payload["match_check"] = m
    return payload if user["role"] == "admin" else _strip_stars(payload)

# Client result APIs; symbol always comes from the authenticated account.
@app.get("/api/my/broker")
def my_broker(user=Depends(current_user)):
    row=store.one("""SELECT b.id,b.name,b.broker_type,b.enabled,b.token_updated_at,b.token_expires_at
        FROM client_brokers cb JOIN broker_connections b ON b.id=cb.broker_id WHERE cb.user_id=?""",[user["id"]])
    if not row: return {"assigned":False,"token_status":"missing","notification":"No broker is assigned. Contact your administrator."}
    now=datetime.now(timezone.utc); expiry=row["token_expires_at"]
    if not expiry: status,message="missing","Add today's broker access token before market data can be updated."
    elif expiry<=now: status,message="expired","Broker token has expired. Add a new token now to keep market data running."
    elif expiry<=now+timedelta(hours=3): status,message="expiring","Broker token expires soon. Add the next token to avoid interruption."
    else: status,message="valid",f"Broker token is active until {expiry.astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b, %I:%M %p IST')}."
    return {"assigned":True,**dict(row),"token_status":status,"notification":message}

@app.get("/api/instruments")
def instruments(q:str="",segment:str|None=None,limit:int=100,_=Depends(current_user)):
    return {"items":search_instruments(q,segment,min(max(limit,1),200)),"segments":list(SOURCES)}

@app.get("/api/candles")
def candles(resolution:str="15",limit:int=500,user=Depends(current_user)):
    if resolution not in INDIA_CANDLE_RESOLUTIONS: raise HTTPException(400,"Unsupported resolution")
    return store.recent_bars(user["symbol"],resolution,min(max(limit,1),5000)).to_dict("records")

@app.get("/api/health")
def health(user=Depends(current_user)):
    symbol=user["symbol"]; c=store.counts(symbol)
    broker=store.one("""SELECT b.name FROM client_brokers cb JOIN broker_connections b ON b.id=cb.broker_id
        WHERE cb.user_id=?""",[user["id"]]) if user["role"]!="admin" else store.one(
        "SELECT name FROM broker_connections WHERE enabled=true ORDER BY id LIMIT 1")
    return {"ok":True,"symbol":symbol,**c,"broker":(broker or {}).get("name") or "Not connected",
            "server_time":datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")}
@app.get("/api/levels/next")
def levels_next(user=Depends(current_user)):
    sheet=next_session_sheet(store,user["symbol"],params())
    if sheet is None: raise HTTPException(404,"No complete session available")
    result=sheet.dict()
    for zone in result["resistances"]+result["supports"]+([result["at_zone"]] if result.get("at_zone") else []):
        zone.pop("stars",None)
    result["disclaimer"]="Reference map from the last completed session; not a trade signal or forecast."
    return result
@app.get("/api/stats/zones")
def zone_stats(user=Depends(current_user)):
    stats=stats_zones(store,user["symbol"])
    if user["role"]!="admin": stats.pop("by_stars",None)  # star rating is admin-only
    return stats
@app.get("/api/stats/days")
def day_stats(user=Depends(current_user)): return stats_days(store,user["symbol"])
@app.get("/api/sessions")
def sessions(limit:int=20,user=Depends(current_user)): return recent_sessions(store,user["symbol"],min(max(limit,1),200))

@app.get("/api/admin/gift-nifty")
def get_gift_nifty(_=Depends(admin_user)):
    return store.kv_get("dashboard_gift_nifty")

@app.put("/api/admin/gift-nifty")
def put_gift_nifty(body: GiftNiftyIn, _=Depends(admin_user)):
    payload = dict(
        ltp=body.ltp, pdc=body.pdc,
        captured_at=body.captured_at or datetime.now(timezone.utc).isoformat(),
        symbol=os.getenv("ZONEAPP_SYMBOL", "NSE:NIFTY50-INDEX"),
    )
    payload["gap_pts"] = round(body.ltp - body.pdc, 2)
    payload["gap_pct"] = round(100 * (body.ltp - body.pdc) / body.pdc, 2)
    store.kv_set("dashboard_gift_nifty", payload)
    return {"ok": True, "payload": payload}

@app.get("/api/admin/holidays")
def holidays(_=Depends(admin_user)):
    return store.q("SELECT holiday_date,label FROM market_holidays ORDER BY holiday_date DESC").to_dict("records")
@app.post("/api/admin/holidays")
def add_holiday(body:HolidayIn,_=Depends(admin_user)):
    try: datetime.strptime(body.holiday_date,"%Y-%m-%d")
    except ValueError: raise HTTPException(400,"holiday_date must be YYYY-MM-DD")
    store.exec("INSERT INTO market_holidays(holiday_date,label) VALUES (?,?) ON CONFLICT(holiday_date) DO UPDATE SET label=excluded.label",[body.holiday_date,body.label])
    return {"ok":True}
@app.delete("/api/admin/holidays/{holiday_date}")
def delete_holiday(holiday_date:str,_=Depends(admin_user)):
    store.exec("DELETE FROM market_holidays WHERE holiday_date=?",[holiday_date]); return {"ok":True}
@app.post("/api/admin/jobs/market-close")
def market_job(force:bool=False,_=Depends(admin_user)): return run_market_close(store,params(),force=force)
@app.post("/api/jobs/market-close")
def cron_market_job(force:bool=False,x_api_key:Optional[str]=Header(None)):
    require_job_key(x_api_key); return run_market_close(store,params(),force=force)


# ------------------------------ SINGLE-PAGE APP ------------------------------
# Everything that is not an /api route is handed to the React build, which
# renders the login screen first and the tabbed dashboard once signed in.
if (STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    asset = (STATIC / full_path)
    if full_path and asset.is_file():
        return FileResponse(asset)
    if not SPA_INDEX.is_file():
        raise HTTPException(503, "Frontend build is missing. Run: cd frontend && npm install && npm run build")
    return FileResponse(SPA_INDEX)
