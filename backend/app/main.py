"""ZoneApp multi-tenant FastAPI application."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .auth import (COOKIE_NAME, create_session, decrypt_credentials, delete_session,
                   encrypt_credentials, hash_password, session_user, verify_password)
from .brokers.base import BrokerError
from .brokers.csv_adapter import CSVAdapter
from .brokers.registry import broker_types, make_broker
from .db import Store
from .jobs import run_market_close
from .service import ZoneParams, next_session_sheet, recent_sessions, run_eod, stats_days, stats_zones

API_KEY = os.getenv("ZONEAPP_API_KEY", "")
UPLOAD_DIR = os.getenv("ZONEAPP_UPLOADS", "./data/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
store = Store()

app = FastAPI(title="ZoneApp", version="2.0.0", description="Multi-client next-session market zones")
TEMPLATES = Path(__file__).parent / "templates"


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
class HolidayIn(BaseModel):
    holiday_date: str
    label: str = "Market holiday"
class ParamsIn(BaseModel):
    cluster_tol: float=25; zone_half_w: float=15; round_step: float=100
    zones_per_side: int=4; break_pts: float=15; bounce_pts: float=45


@app.get("/")
def root(token: str|None=Cookie(None,alias=COOKIE_NAME)):
    user=session_user(store,token)
    return RedirectResponse("/admin" if user and user["role"]=="admin" else ("/app" if user else "/login"))
@app.get("/login")
def login_page(): return FileResponse(TEMPLATES/"login.html")
@app.get("/admin")
def admin_page(token: str|None=Cookie(None,alias=COOKIE_NAME)):
    user=session_user(store,token)
    return FileResponse(TEMPLATES/"admin.html") if user and user["role"]=="admin" else RedirectResponse("/login")
@app.get("/app")
def client_page(token: str|None=Cookie(None,alias=COOKIE_NAME)):
    return FileResponse(TEMPLATES/"client.html") if session_user(store,token) else RedirectResponse("/login")


@app.post("/api/auth/login")
def login(body: LoginIn):
    user=store.one("SELECT * FROM users WHERE lower(username)=lower(?) AND active=true",[body.username.strip()])
    if not user or not verify_password(body.password,user["password_hash"]):
        raise HTTPException(401,"Invalid username or password")
    token,expires=create_session(store,user["id"])
    response=JSONResponse({"ok":True,"role":user["role"],"redirect":"/admin" if user["role"]=="admin" else "/app"})
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

@app.get("/api/admin/broker-types")
def types(_=Depends(admin_user)): return broker_types()
@app.get("/api/admin/brokers")
def brokers(_=Depends(admin_user)):
    return store.q("SELECT id,name,broker_type,enabled,created_at,updated_at FROM broker_connections ORDER BY id").to_dict("records")
@app.post("/api/admin/brokers")
def add_broker(body:BrokerIn,_=Depends(admin_user)):
    spec=next((x for x in broker_types() if x["key"]==body.broker_type),None)
    if not spec: raise HTTPException(400,"Unsupported broker type")
    required={f["name"] for f in spec["fields"]}
    if not required.issubset(body.credentials): raise HTTPException(400,f"Missing credentials: {', '.join(sorted(required-set(body.credentials)))}")
    row=store.one("INSERT INTO broker_connections(name,broker_type,credentials,enabled) VALUES (?,?,?::jsonb,?) RETURNING id",[body.name,body.broker_type,json.dumps(encrypt_credentials(body.credentials)),body.enabled])
    return {"ok":True,"id":row["id"]}
@app.delete("/api/admin/brokers/{broker_id}")
def delete_broker(broker_id:int,_=Depends(admin_user)):
    store.exec("DELETE FROM broker_connections WHERE id=?",[broker_id]); return {"ok":True}
@app.post("/api/admin/brokers/{broker_id}/test")
def test_broker(broker_id:int,_=Depends(admin_user)):
    row=store.one("SELECT * FROM broker_connections WHERE id=?",[broker_id])
    if not row: raise HTTPException(404,"Broker not found")
    try:
        status=make_broker(row["broker_type"],decrypt_credentials(row["credentials"])).auth_status()
        return {"connected":status.connected,"message":status.message}
    except Exception as exc: return {"connected":False,"message":str(exc)}


# Client result APIs; symbol always comes from the authenticated account.
@app.get("/api/health")
def health(user=Depends(current_user)):
    symbol=user["symbol"]; c=store.counts(symbol)
    return {"ok":True,"symbol":symbol,**c,"server_time":datetime.now().isoformat(timespec="seconds")}
@app.get("/api/levels/next")
def levels_next(user=Depends(current_user)):
    sheet=next_session_sheet(store,user["symbol"],params())
    if sheet is None: raise HTTPException(404,"No complete session available")
    result=sheet.dict(); result["disclaimer"]="Reference map from the last completed session; not a trade signal or forecast."; return result
@app.get("/api/stats/zones")
def zone_stats(user=Depends(current_user)): return stats_zones(store,user["symbol"])
@app.get("/api/stats/days")
def day_stats(user=Depends(current_user)): return stats_days(store,user["symbol"])
@app.get("/api/sessions")
def sessions(limit:int=20,user=Depends(current_user)): return recent_sessions(store,user["symbol"],min(max(limit,1),200))

@app.post("/api/admin/ingest/csv")
async def ingest_csv(symbol:str,file:UploadFile=File(...),_=Depends(admin_user)):
    safe=Path(file.filename or "upload.csv").name; path=Path(UPLOAD_DIR)/safe; path.write_bytes(await file.read())
    try: df=CSVAdapter(str(path)).fetch_historical(symbol,"15","1900-01-01","2100-01-01")
    except BrokerError as exc: raise HTTPException(400,str(exc))
    n=store.upsert_bars(df,symbol,"csv"); return {"bars_ingested":n,**run_eod(store,symbol,params(),True)}
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
