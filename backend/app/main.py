"""ZoneApp multi-tenant FastAPI application."""
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ENV_FILE  # importing the package loads .env before anything reads it
from .auth import (COOKIE_NAME, create_session, decrypt_credentials, delete_session,
                   encrypt_credentials, hash_password, session_user, verify_password)
from .broker_store import BrokerUnavailable, load_adapter, symbols_for
from .brokers.base import BrokerError
from .brokers.registry import INDIA_CANDLE_RESOLUTIONS, broker_types, get_broker_type, make_broker
from .db import Store, records
from . import instruments as instrument_master
from . import market_calendar
from .jobs import run_market_close
from .seeding import DEFAULT_DAYS, date_window, recent_runs, seed_all, seed_broker
from . import symbols as watchlist
from .service import (ZoneParams, dashboard_payload, match_check, next_session_sheet, recent_sessions, run_eod, session_chart, session_recap, stats_days, stats_zones)

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


def bootstrap_watchlist():
    """First start: seed the alias table and track the standard indices, so the
    app has something to fetch as soon as a broker token exists. Everything is
    editable afterwards and read back from the database."""
    watchlist.seed_aliases(store)
    if not watchlist.tracked(store, active_only=False):
        for symbol, label in watchlist.DEFAULT_WATCHLIST:
            watchlist.add(store, symbol, label)
        print(f"[zoneapp] watchlist seeded with {len(watchlist.DEFAULT_WATCHLIST)} symbols")
    watchlist.ensure_a_default(store)   # also fixes databases upgraded from an older schema


def bootstrap_instruments():
    """The headline indices are always available; the full contract master is
    downloaded in the background so startup never waits on the network."""
    try:
        if not store.one("SELECT symbol FROM instruments LIMIT 1"):
            instrument_master.seed_indices(store)
        if instrument_master.is_stale(store):
            threading.Thread(target=_refresh_reference_data, name="reference-data", daemon=True).start()
    except Exception as exc:
        print(f"[zoneapp] instrument bootstrap skipped: {exc}")


def _refresh_reference_data():
    try:
        from .jobs import refresh_reference_data
        print("[zoneapp] refreshing instrument master and holiday calendar…")
        print(f"[zoneapp] reference data: {refresh_reference_data(store)}")
    except Exception as exc:                       # never take the app down for this
        print(f"[zoneapp] reference data refresh failed: {exc}")


@app.on_event("startup")
def startup():
    print(f"[zoneapp] configuration: {ENV_FILE or 'environment variables only'}")
    if not os.getenv("ZONEAPP_ENCRYPTION_KEY"):
        print("[zoneapp] ZONEAPP_ENCRYPTION_KEY is not set — broker credentials are "
              "encrypted with a key stored in the database. Set it in .env for production.")
    bootstrap_admin()
    bootstrap_watchlist()
    bootstrap_instruments()


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


def resolve_symbol(user=None, symbol: str | None = None):
    """Any signed-in account may look at any symbol the platform tracks; the
    picker in the header is the only thing that chooses one."""
    if symbol:
        return watchlist.normalize(symbol, store)
    return watchlist.default_symbol(store)


class LoginIn(BaseModel): username: str; password: str
class ClientIn(BaseModel):
    """Accounts are just logins: every client can view every tracked symbol,
    so there is no symbol or broker to assign."""
    username: str = Field(min_length=3,max_length=80)
    display_name: str = Field(min_length=1,max_length=120)
    password: str = Field(min_length=8,max_length=256)
class ClientPatch(BaseModel):
    display_name: str | None=None; password: str | None=None; active: bool | None=None
class BrokerIn(BaseModel):
    name: str = Field(min_length=1,max_length=120); broker_type: str
    credentials: dict; enabled: bool=True
    resolutions: list[str] = Field(default_factory=lambda: list(INDIA_CANDLE_RESOLUTIONS))
class BrokerTokenIn(BaseModel):
    access_token: str = ""      # the token itself…
    auth_code: str = ""         # …or the auth code / redirect URL to exchange
    # Saving a token just saves the token. History is fetched only when asked
    # for, here or from the Data seeding tab.
    seed: bool = False
    seed_days: int = Field(default=DEFAULT_DAYS, ge=1, le=3650)
class SeedIn(BaseModel):
    days: int = Field(default=DEFAULT_DAYS, ge=5, le=3650)
    symbols: list[str] | None = None
class SeedRangeIn(BaseModel):
    """Either a trailing day count or an explicit date range."""
    symbols: list[str] | None = None          # None = every tracked symbol
    days: int | None = Field(default=None, ge=1, le=7300)
    date_from: str | None = None
    date_to: str | None = None
    resolutions: list[str] | None = None
class SymbolIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=80)
    label: str = ""
    resolutions: list[str] | None = None
    broker_id: int | None = None
    seed: bool = True
    seed_days: int = Field(default=DEFAULT_DAYS, ge=5, le=3650)
class SymbolPatch(BaseModel):
    label: str | None = None
    resolutions: list[str] | None = None
    broker_id: int | None = None
    active: bool | None = None
    is_default: bool | None = None
class AliasIn(BaseModel):
    alias: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=1, max_length=80)
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
    return records(store.q("""SELECT u.id,u.username,u.display_name,u.symbol,u.active,u.created_at,
      cb.broker_id,b.name broker_name FROM users u LEFT JOIN client_brokers cb ON cb.user_id=u.id
      LEFT JOIN broker_connections b ON b.id=cb.broker_id WHERE u.role='client' ORDER BY u.created_at DESC"""))
@app.post("/api/admin/clients")
def add_client(body:ClientIn,_=Depends(admin_user)):
    try:
        with store.connection() as con:
            user=con.execute("INSERT INTO users(username,display_name,password_hash,role) VALUES (%s,%s,%s,'client') RETURNING id",
                             [body.username.strip().lower(),body.display_name.strip(),hash_password(body.password)]).fetchone()
        return {"ok":True,"id":user["id"]}
    except Exception as exc:
        if "unique" in str(exc).lower(): raise HTTPException(409,"Username already exists")
        raise
@app.patch("/api/admin/clients/{user_id}")
def update_client(user_id:int,body:ClientPatch,_=Depends(admin_user)):
    updates=[]; values=[]
    for col,val in (("display_name",body.display_name),("active",body.active)):
        if val is not None: updates.append(f"{col}=?"); values.append(val)
    if body.password is not None: updates.append("password_hash=?"); values.append(hash_password(body.password))
    if updates: store.exec(f"UPDATE users SET {','.join(updates)} WHERE id=? AND role='client'",values+[user_id])
    return {"ok":True}

@app.delete("/api/admin/clients/{user_id}")
def delete_client(user_id:int,_=Depends(admin_user)):
    """Remove a client login. Sessions and the broker assignment cascade."""
    row=store.one("SELECT id FROM users WHERE id=? AND role='client'",[user_id])
    if not row: raise HTTPException(404,"Client not found")
    store.exec("DELETE FROM users WHERE id=? AND role='client'",[user_id])
    return {"ok":True}

# ------------------------------ SYMBOL WATCHLIST ------------------------------
@app.get("/api/symbols")
def list_symbols(user=Depends(current_user)):
    """Symbols the platform tracks, straight from the database."""
    return watchlist.tracked(store, active_only=user["role"] != "admin")

@app.get("/api/symbols/catalog")
def symbol_catalog(_=Depends(current_user)):
    """Everything the UI needs to build symbol and timeframe pickers: the
    watchlist, the aliases, the supported resolutions and the landing symbol.
    Adding a symbol in the admin panel changes this for every screen."""
    return watchlist.catalog(store, INDIA_CANDLE_RESOLUTIONS)

@app.post("/api/admin/symbols")
def add_symbol(body:SymbolIn,background:BackgroundTasks,_=Depends(admin_user)):
    try: symbol=watchlist.add(store,body.symbol,body.label,body.resolutions,body.broker_id)
    except ValueError as exc: raise HTTPException(400,str(exc))
    seeded=False
    if body.seed:
        try:
            row,_adapter=load_adapter(store,broker_id=body.broker_id)
            background.add_task(seed_broker,store,row["id"],body.seed_days,params(),[symbol])
            seeded=True
        except BrokerUnavailable:
            seeded=False  # symbol is tracked; it will fill in once a token exists
    return {"ok":True,"symbol":symbol,"seeding":seeded,
            "seed_message":(f"Backfilling {body.seed_days} days for {symbol} in the background."
                            if seeded else "Symbol added. Add a broker token to fetch its data.")}

@app.patch("/api/admin/symbols/{symbol:path}")
def update_symbol(symbol:str,body:SymbolPatch,_=Depends(admin_user)):
    watchlist.update(store,symbol,label=body.label,resolutions=body.resolutions,
                     broker_id=body.broker_id,active=body.active,is_default=body.is_default,
                     broker_set="broker_id" in body.model_fields_set)
    return {"ok":True}

@app.post("/api/admin/symbol-aliases")
def add_symbol_alias(body:AliasIn,_=Depends(admin_user)):
    """Teach the platform a shorthand, e.g. NIFTY -> NSE:NIFTY50-INDEX."""
    try: watchlist.add_alias(store,body.alias,body.symbol)
    except ValueError as exc: raise HTTPException(400,str(exc))
    return {"ok":True,"aliases":watchlist.aliases(store)}

@app.delete("/api/admin/symbol-aliases/{alias:path}")
def delete_symbol_alias(alias:str,_=Depends(admin_user)):
    watchlist.remove_alias(store,alias); return {"ok":True}

@app.delete("/api/admin/symbols/{symbol:path}")
def delete_symbol(symbol:str,purge:bool=False,_=Depends(admin_user)):
    """Stop tracking a symbol. `purge=true` also deletes its stored candles,
    zone sheets and outcomes."""
    return {"ok":True,"symbol":watchlist.remove(store,symbol,purge_data=purge)}

@app.post("/api/admin/symbols/{symbol:path}/seed")
def seed_symbol_now(symbol:str,body:SeedRangeIn,background:BackgroundTasks,_=Depends(admin_user)):
    clean=watchlist.normalize(symbol,store)
    try: row,_adapter=load_adapter(store,symbol=clean)
    except BrokerUnavailable as exc: raise HTTPException(400,str(exc))
    try: date_from,date_to=date_window(body.days,body.date_from,body.date_to)
    except ValueError as exc: raise HTTPException(400,str(exc))
    background.add_task(seed_broker,store,row["id"],None,params(),[clean],date_from,date_to,body.resolutions)
    return {"ok":True,"seeding":True,"seed_symbols":[clean],"date_from":date_from,"date_to":date_to,
            "seed_message":f"Fetching {date_from} to {date_to} for {clean} in the background."}

@app.post("/api/admin/seed-all")
def seed_everything(body:SeedIn,background:BackgroundTasks,_=Depends(admin_user)):
    """Fetch data and rebuild zones for every tracked symbol."""
    return run_seed(SeedRangeIn(symbols=body.symbols,days=body.days),background)


@app.post("/api/admin/seed")
def run_seed(body:SeedRangeIn,background:BackgroundTasks,_=Depends(admin_user)):
    """Seed on demand for a chosen period: a trailing day count (past day,
    past week, past month...) or an explicit from/to date range."""
    try: load_adapter(store)
    except BrokerUnavailable as exc: raise HTTPException(400,str(exc))
    try: date_from,date_to=date_window(body.days,body.date_from,body.date_to)
    except ValueError as exc: raise HTTPException(400,str(exc))
    chosen=[watchlist.normalize(s,store) for s in body.symbols] if body.symbols else watchlist.all_symbols(store)
    if not chosen: raise HTTPException(400,"No symbols are being tracked yet")
    resolutions=[r for r in (body.resolutions or []) if r in INDIA_CANDLE_RESOLUTIONS] or None
    background.add_task(seed_all,store,None,params(),chosen,date_from,date_to,resolutions)
    return {"ok":True,"seeding":True,"seed_symbols":chosen,"date_from":date_from,"date_to":date_to,
            "seed_message":f"Fetching {date_from} to {date_to} for {len(chosen)} symbol(s) in the background."}


@app.get("/api/admin/broker-types")
def types(_=Depends(admin_user)): return broker_types()
@app.get("/api/admin/brokers")
def brokers(_=Depends(admin_user)):
    return records(store.q("""SELECT id,name,broker_type,resolutions,enabled,created_at,updated_at,
        token_updated_at,token_expires_at,
        CASE WHEN token_expires_at IS NULL THEN 'unknown' WHEN token_expires_at<=now() THEN 'expired'
             WHEN token_expires_at<=now()+interval '3 hours' THEN 'expiring' ELSE 'valid' END token_status
        FROM broker_connections ORDER BY id"""))
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
    return {"ok":True,"id":row["id"],"seeding":False,"seed_symbols":[]}
@app.get("/api/admin/brokers/{broker_id}/login-url")
def broker_login_url(broker_id:int,_=Depends(admin_user)):
    """Provider sign-in URL built from THIS connection's credentials, so the
    token that comes back belongs to the same app id."""
    row=store.one("SELECT * FROM broker_connections WHERE id=?",[broker_id])
    if not row: raise HTTPException(404,"Broker not found")
    if row["broker_type"]!="fyers": raise HTTPException(400,"This provider has no browser sign-in flow")
    from .brokers.generate_token import get_login_url
    try: return {"ok":True,"url":get_login_url(decrypt_credentials(row["credentials"]))}
    except Exception as exc: raise HTTPException(400,str(exc))


def _save_token(row,credentials,token:str,broker_id:int):
    """Verify a token with the provider and store it encrypted."""
    from .brokers.generate_token import describe_token
    credentials=dict(credentials); credentials["access_token"]=token
    status=make_broker(row["broker_type"],credentials).auth_status()
    if not status.connected:
        info=describe_token(token,credentials.get("client_id")) if row["broker_type"]=="fyers" else {}
        detail=f"Token was not saved: {status.message}."
        if info.get("problem"):
            detail+=" "+info["problem"]
        elif info.get("readable"):
            who=f"user '{info['user']}'" if info.get("user") else "an unnamed user"
            detail+=(f" The token parses correctly ({info['kind']} for {who}), so the provider refused it for "
                     f"another reason: a newer token may have been generated for app id "
                     f"'{credentials.get('client_id')}' since, or the app may be inactive. "
                     f"Press Generate token on this connection to create a fresh one.")
        else:
            detail+=(" The value could not be read as a Fyers token. Press Generate token on this connection, or "
                     "paste the access token or the full redirect URL exactly as the provider shows it.")
        raise HTTPException(400,detail)
    kind=get_broker_type(row["broker_type"]); now=datetime.now(timezone.utc)
    expires=now+timedelta(hours=kind.token_ttl_hours) if kind.token_ttl_hours else None
    store.exec("UPDATE broker_connections SET credentials=?::jsonb,token_updated_at=?,token_expires_at=?,updated_at=now() WHERE id=?",
               [json.dumps(encrypt_credentials(credentials)),now,expires,broker_id])
    return status,expires


@app.post("/api/brokers/{broker_id}/token")
def update_broker_token(broker_id:int,body:BrokerTokenIn,background:BackgroundTasks,_=Depends(admin_user)):
    """Save today's access token. Accepts the token itself, or the auth code /
    redirect URL from the provider sign-in, which is exchanged here."""
    from .brokers.generate_token import (clean_access_token, describe_token, exchange_code_for_token,
                                         looks_like_auth_code, read_auth_code)
    row=store.one("SELECT * FROM broker_connections WHERE id=?",[broker_id])
    if not row: raise HTTPException(404,"Broker not found")
    credentials=decrypt_credentials(row["credentials"])
    raw=(body.access_token or body.auth_code or "").strip()
    if not raw: raise HTTPException(400,"Provide an access token or an auth code")
    oauth=row["broker_type"]=="fyers"   # only Fyers has a browser sign-in flow
    exchanged=False
    if oauth:
        candidate=clean_access_token(raw,credentials.get("client_id"))
        # An auth code, a redirect URL, or something too short to be a JWT all
        # have to be exchanged first. Auth codes are long JWTs too, so the
        # payload is what tells them apart — not the length.
        if body.auth_code or read_auth_code(raw)!=raw or len(candidate)<60 or looks_like_auth_code(candidate):
            try:
                raw=exchange_code_for_token(raw,credentials); exchanged=True
            except Exception as exc:
                if body.auth_code or looks_like_auth_code(candidate):
                    reason=str(exc)
                    if "Max retries" in reason or "Connection" in reason:
                        reason="the provider could not be reached from this server"
                    raise HTTPException(400,f"Could not exchange the auth code: {reason}")
    token=clean_access_token(raw,credentials.get("client_id")) if oauth else raw
    if oauth:
        if len(token)<20:
            raise HTTPException(400,"That does not look like a Fyers access token. Paste the access token, "
                                    "the auth code, or the full redirect URL.")
        info=describe_token(token,credentials.get("client_id"))
        if info["problem"]: raise HTTPException(400,info["problem"])
    status,expires=_save_token(row,credentials,token,broker_id)
    seeded=[]
    if body.seed:
        seeded=symbols_for(store,broker_id)
        background.add_task(seed_broker,store,broker_id,body.seed_days,params(),seeded)
    return {"ok":True,"connected":True,"message":status.message,"expires_at":expires,"exchanged":exchanged,
            "seeding":bool(seeded),"seed_symbols":seeded,
            "seed_message":(f"Fetching the last {body.seed_days} days for {len(seeded)} symbol(s) in the background."
                            if seeded else "Token saved. Use Data seeding when you want to fetch history.")}


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


@app.get("/api/methodology")
def methodology(_=Depends(current_user)):
    """The strategy document (docs/METHODOLOGY.md) plus the live parameters, so
    the Methodology tab and the repository can never drift apart."""
    doc = Path(__file__).resolve().parent.parent.parent / "docs" / "METHODOLOGY.md"
    if not doc.is_file():
        raise HTTPException(404, "docs/METHODOLOGY.md is missing from this installation")
    active = params()
    return {"markdown": doc.read_text(encoding="utf-8"),
            "updated_at": datetime.fromtimestamp(doc.stat().st_mtime, timezone.utc).isoformat(),
            "params": active.__dict__,
            "day_types": {"NARROW": "CPR % < 0.08", "NORMAL": "0.08 – 0.26", "WIDE": "> 0.26"}}


@app.get("/api/admin/job-runs")
def job_runs(limit:int=20,_=Depends(admin_user)):
    return recent_runs(store,min(max(limit,1),100))

@app.post("/api/admin/brokers/{broker_id}/exchange-token")
def broker_exchange_token(broker_id:int,body:TokenExchangeIn,_=Depends(admin_user)):
    """Swap an auth code (or the full redirect URL) for an access token without
    saving it, so the administrator can review it first."""
    row=store.one("SELECT * FROM broker_connections WHERE id=?",[broker_id])
    if not row: raise HTTPException(404,"Broker not found")
    from .brokers.generate_token import exchange_code_for_token
    try: return {"ok":True,"access_token":exchange_code_for_token(body.auth_code,decrypt_credentials(row["credentials"]))}
    except Exception as exc: raise HTTPException(400,f"Token exchange failed: {exc}")


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
def dashboard(date:str|None=None,symbol:str|None=None,user=Depends(current_user)):
    """Single round-trip payload for the client dashboard UI."""
    active = resolve_symbol(user, symbol)
    payload = dashboard_payload(store, active, params())
    payload["authenticated"] = True
    payload["role"] = user["role"]
    payload["username"] = user["username"]
    payload["can_edit"] = (user["role"] == "admin")
    if date:
        r = session_recap(store, active, date, params())
        m = match_check(store, active, date, params())
        if r: payload["session_recap"] = r
        if m: payload["match_check"] = m
    return payload if user["role"] == "admin" else _strip_stars(payload)

# Client result APIs; symbol always comes from the authenticated account.
@app.get("/api/data-status")
def data_status(_=Depends(current_user)):
    """Read-only freshness banner for every account: is the platform's market
    data source connected and up to date?"""
    row=store.one("""SELECT name,token_expires_at FROM broker_connections WHERE enabled=true
                     ORDER BY token_expires_at DESC NULLS LAST LIMIT 1""")
    if not row: return {"connected":False,"status":"missing","message":"No broker connection is configured yet."}
    now=datetime.now(timezone.utc); expiry=row["token_expires_at"]
    if not expiry: status,message="missing","Market data is paused until an administrator adds today's broker token."
    elif expiry<=now: status,message="expired","The broker token has expired; an administrator needs to add a new one."
    elif expiry<=now+timedelta(hours=3): status,message="expiring","The broker token expires soon."
    else: status,message="valid",f"Market data is live until {expiry.astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b, %I:%M %p IST')}."
    return {"connected":status=="valid","status":status,"message":message,"broker":row["name"]}

# ------------------------------ INSTRUMENT MASTER ------------------------------
@app.get("/api/instruments")
def instruments(q:str="",segment:str|None=None,type:str|None=None,underlying:str|None=None,
                expiry:str|None=None,limit:int=100,_=Depends(current_user)):
    """Search every contract stored in the database: cash, futures and options
    with their lot size, tick size, expiry and strike."""
    return {"items":instrument_master.search(store,q,segment,type,underlying,expiry,limit),
            "segments":list(instrument_master.SOURCES),
            "types":["INDEX","EQ","FUT","CE","PE"]}

@app.get("/api/instruments/status")
def instrument_status(_=Depends(current_user)):
    return instrument_master.stats(store)

@app.get("/api/instruments/underlyings")
def instrument_underlyings(q:str="",limit:int=200,_=Depends(current_user)):
    return instrument_master.underlyings(store,q,limit)

@app.get("/api/instruments/expiries")
def instrument_expiries(underlying:str,include_past:bool=False,_=Depends(current_user)):
    """Expiry dates for an underlying with contract counts and the lot size."""
    return instrument_master.expiries(store,underlying,include_past)

@app.get("/api/instruments/{symbol:path}/contract")
def instrument_contract(symbol:str,_=Depends(current_user)):
    row=instrument_master.contract(store,symbol)
    if not row: raise HTTPException(404,"Unknown instrument")
    return row

@app.post("/api/admin/instruments/refresh")
def refresh_instruments(background:BackgroundTasks,_=Depends(admin_user)):
    """Re-download the provider's symbol masters in the background."""
    background.add_task(instrument_master.refresh,store)
    return {"ok":True,"refreshing":True,
            "message":"Downloading the instrument masters; lot sizes and expiries update in place."}

@app.get("/api/candles")
def candles(resolution:str="15",limit:int=500,symbol:str|None=None,user=Depends(current_user)):
    if resolution not in INDIA_CANDLE_RESOLUTIONS: raise HTTPException(400,"Unsupported resolution")
    return records(store.recent_bars(resolve_symbol(user,symbol),resolution,min(max(limit,1),5000)))

@app.get("/api/chart/session")
def chart_session(date:str|None=None,date_from:str|None=None,date_to:str|None=None,
                  resolution:str="15",symbol:str|None=None,user=Depends(current_user)):
    """Candles plus the zone levels (and their results) for one session or a
    date range, for the TradingView-style chart on the Overview tab. Default
    is the last completed session with the next session's levels on top."""
    if resolution not in INDIA_CANDLE_RESOLUTIONS: raise HTTPException(400,"Unsupported resolution")
    try:
        return session_chart(store,resolve_symbol(user,symbol),params(),date,date_from,date_to,resolution)
    except ValueError as exc: raise HTTPException(400,str(exc))
    except LookupError as exc: raise HTTPException(404,str(exc))

@app.get("/api/health")
def health(symbol:str|None=None,user=Depends(current_user)):
    symbol=resolve_symbol(user,symbol); c=store.counts(symbol)
    broker=store.one("""SELECT b.name FROM client_brokers cb JOIN broker_connections b ON b.id=cb.broker_id
        WHERE cb.user_id=?""",[user["id"]]) if user["role"]!="admin" else store.one(
        "SELECT name FROM broker_connections WHERE enabled=true ORDER BY id LIMIT 1")
    return {"ok":True,"symbol":symbol,**c,"broker":(broker or {}).get("name") or "Not connected",
            "server_time":datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")}
@app.get("/api/levels/next")
def levels_next(symbol:str|None=None,user=Depends(current_user)):
    sheet=next_session_sheet(store,resolve_symbol(user,symbol),params())
    if sheet is None: raise HTTPException(404,"No complete session available")
    result=sheet.dict()
    for zone in result["resistances"]+result["supports"]+([result["at_zone"]] if result.get("at_zone") else []):
        zone.pop("stars",None)
    result["disclaimer"]="Reference map from the last completed session; not a trade signal or forecast."
    return result
@app.get("/api/stats/zones")
def zone_stats(symbol:str|None=None,user=Depends(current_user)):
    stats=stats_zones(store,resolve_symbol(user,symbol))
    if user["role"]!="admin": stats.pop("by_stars",None)  # star rating is admin-only
    return stats
@app.get("/api/stats/days")
def day_stats(symbol:str|None=None,user=Depends(current_user)): return stats_days(store,resolve_symbol(user,symbol))
@app.get("/api/sessions")
def sessions(limit:int=20,symbol:str|None=None,user=Depends(current_user)): return recent_sessions(store,resolve_symbol(user,symbol),min(max(limit,1),200))

@app.get("/api/admin/gift-nifty")
def get_gift_nifty(_=Depends(admin_user)):
    return store.kv_get("dashboard_gift_nifty")

@app.put("/api/admin/gift-nifty")
def put_gift_nifty(body: GiftNiftyIn, _=Depends(admin_user)):
    payload = dict(
        ltp=body.ltp, pdc=body.pdc,
        captured_at=body.captured_at or datetime.now(timezone.utc).isoformat(),
        symbol=watchlist.default_symbol(store),
    )
    payload["gap_pts"] = round(body.ltp - body.pdc, 2)
    payload["gap_pct"] = round(100 * (body.ltp - body.pdc) / body.pdc, 2)
    store.kv_set("dashboard_gift_nifty", payload)
    return {"ok": True, "payload": payload}

@app.get("/api/admin/holidays")
def holidays(_=Depends(admin_user)):
    return records(store.q("""SELECT holiday_date,label,source,exchange FROM market_holidays
                              ORDER BY holiday_date DESC"""))

@app.post("/api/admin/holidays/sync")
def sync_holidays(year:int|None=None,_=Depends(admin_user)):
    """Pull the calendar from the broker, else the exchange, else infer it from
    the candles already stored. Manual entries are left alone."""
    adapter=None
    try: _row,adapter=load_adapter(store)
    except BrokerUnavailable: pass
    return market_calendar.sync(store,adapter,year)
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
    # The hashed JS/CSS bundles are safe to cache forever, but the un-hashed
    # index must always be fresh: a stale page keeps running an older app
    # whose routes may not exist any more (the Sessions tab then fell back to
    # the Overview tab after an upgrade).
    return FileResponse(SPA_INDEX, headers={"Cache-Control": "no-cache, must-revalidate"})
