"""Idempotent post-market ingestion and zone calculation job."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .auth import decrypt_credentials
from .brokers.registry import make_broker
from .service import ZoneParams, run_eod

IST = ZoneInfo("Asia/Kolkata")


def is_market_day(store, day):
    if day.weekday() >= 5:
        return False, "Weekend"
    holiday = store.one("SELECT label FROM market_holidays WHERE holiday_date=?", [day])
    return (False, holiday["label"]) if holiday else (True, "Trading weekday")


def run_market_close(store, params: ZoneParams | None = None, now=None, force=False):
    now = now or datetime.now(IST)
    now = now.replace(tzinfo=IST) if now.tzinfo is None else now.astimezone(IST)
    day = now.date()
    working, reason = is_market_day(store, day)
    if not working and not force:
        return {"ok": True, "skipped": True, "reason": reason, "date": str(day), "runs": []}
    if now.hour < 16 and not force:
        return {"ok": True, "skipped": True, "reason": "Market has not closed", "date": str(day), "runs": []}

    assignments = store.q("""SELECT DISTINCT b.id broker_id,b.broker_type,b.credentials,b.resolutions,b.token_expires_at,u.symbol
        FROM broker_connections b JOIN client_brokers cb ON cb.broker_id=b.id
        JOIN users u ON u.id=cb.user_id
        WHERE b.enabled=true AND u.active=true""")
    runs = []
    for row in assignments.to_dict("records"):
        existing = store.one("SELECT status FROM job_runs WHERE job_date=? AND broker_id=? AND symbol=?", [day,row["broker_id"],row["symbol"]])
        if existing and existing["status"] == "success" and not force:
            runs.append({"broker_id": row["broker_id"], "symbol": row["symbol"], "status": "already-complete"})
            continue
        store.exec("""INSERT INTO job_runs(job_date,broker_id,symbol,status) VALUES (?,?,?,'running')
            ON CONFLICT(job_date,broker_id,symbol) DO UPDATE SET status='running',started_at=now(),finished_at=NULL""", [day,row["broker_id"],row["symbol"]])
        try:
            expiry=row.get("token_expires_at")
            if expiry and expiry <= now.astimezone(expiry.tzinfo):
                raise RuntimeError("Broker access token has expired; add today's token")
            adapter = make_broker(row["broker_type"], decrypt_credentials(row["credentials"]))
            start = (day - timedelta(days=10)).isoformat()
            resolutions=row.get("resolutions") or ["15","D"]
            ingested, warnings={}, {}
            for resolution in resolutions:
                try:
                    bars = adapter.fetch_historical(row["symbol"], resolution, start, day.isoformat())
                    ingested[str(resolution)] = store.upsert_bars(bars, row["symbol"], row["broker_type"], str(resolution))
                except Exception as exc:
                    warnings[str(resolution)] = str(exc)
            if "15" not in ingested:
                raise RuntimeError(f"Required 15-minute candle sync failed: {warnings.get('15','not configured')}")
            result = run_eod(store, row["symbol"], params or ZoneParams(), rebuild_all=False)
            detail = {"bars_ingested": sum(ingested.values()), "by_resolution": ingested, "timeframe_warnings": warnings, **result}
            status = "success" if result.get("ok") else "failed"
        except Exception as exc:
            status, detail = "failed", {"error": str(exc)}
        store.exec("UPDATE job_runs SET status=?,detail=?::jsonb,finished_at=now() WHERE job_date=? AND broker_id=? AND symbol=?", [status,json.dumps(detail),day,row["broker_id"],row["symbol"]])
        runs.append({"broker_id": row["broker_id"], "symbol": row["symbol"], "status": status, **detail})
    return {"ok": all(r["status"] in ("success","already-complete") for r in runs), "date": str(day), "runs": runs}
