"""Idempotent post-market ingestion and zone calculation job.

It runs for **every** symbol on the administrator watchlist. Each (connection,
symbol) pair is recorded separately in ``job_runs`` so one failing symbol never
hides another.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .broker_store import load_adapter
from .service import ZoneParams, run_eod

IST = ZoneInfo("Asia/Kolkata")


def is_market_day(store, day):
    if day.weekday() >= 5:
        return False, "Weekend"
    holiday = store.one("SELECT label FROM market_holidays WHERE holiday_date=?", [day])
    return (False, holiday["label"]) if holiday else (True, "Trading weekday")


def targets(store):
    """Every (broker, symbol) pair that must be refreshed today."""
    brokers = store.q("""SELECT id, broker_type, resolutions, token_expires_at
        FROM broker_connections WHERE enabled = true
        ORDER BY token_expires_at DESC NULLS LAST, id""")
    if brokers.empty:
        return []
    brokers = brokers.to_dict("records")
    by_id = {b["id"]: b for b in brokers}
    fallback = brokers[0]

    pairs = {}
    watchlist = store.q("SELECT symbol, resolutions, broker_id FROM tracked_symbols WHERE active = true")
    for row in ([] if watchlist.empty else watchlist.to_dict("records")):
        broker = by_id.get(row["broker_id"]) or fallback
        pairs.setdefault((broker["id"], row["symbol"]), dict(
            broker_id=broker["id"], broker_type=broker["broker_type"],
            symbol=row["symbol"], resolutions=row["resolutions"] or broker["resolutions"] or ["15", "D"]))
    return list(pairs.values())


def run_market_close(store, params: ZoneParams | None = None, now=None, force=False):
    now = now or datetime.now(IST)
    now = now.replace(tzinfo=IST) if now.tzinfo is None else now.astimezone(IST)
    day = now.date()
    working, reason = is_market_day(store, day)
    if not working and not force:
        return {"ok": True, "skipped": True, "reason": reason, "date": str(day), "runs": []}
    if now.hour < 16 and not force:
        return {"ok": True, "skipped": True, "reason": "Market has not closed", "date": str(day), "runs": []}

    runs = []
    for row in targets(store):
        existing = store.one("SELECT status FROM job_runs WHERE job_date=? AND broker_id=? AND symbol=? AND kind='market-close'",
                             [day, row["broker_id"], row["symbol"]])
        if existing and existing["status"] == "success" and not force:
            runs.append({"broker_id": row["broker_id"], "symbol": row["symbol"], "status": "already-complete"})
            continue
        store.exec("""INSERT INTO job_runs(job_date,broker_id,symbol,kind,status) VALUES (?,?,?,'market-close','running')
            ON CONFLICT(job_date,broker_id,symbol,kind) DO UPDATE SET status='running',started_at=now(),finished_at=NULL""",
            [day, row["broker_id"], row["symbol"]])
        try:
            # Stored credentials are the single source of truth for every service.
            _, adapter = load_adapter(store, broker_id=row["broker_id"])
            start = (day - timedelta(days=10)).isoformat()
            ingested, warnings = {}, {}
            for resolution in (row["resolutions"] or ["15", "D"]):
                try:
                    bars = adapter.fetch_historical(row["symbol"], str(resolution), start, day.isoformat())
                    ingested[str(resolution)] = store.upsert_bars(bars, row["symbol"], row["broker_type"], str(resolution))
                except Exception as exc:
                    warnings[str(resolution)] = str(exc)
            if "15" not in ingested:
                raise RuntimeError(f"Required 15-minute candle sync failed: {warnings.get('15','not configured')}")
            result = run_eod(store, row["symbol"], params or ZoneParams(), rebuild_all=False)
            detail = {"bars_ingested": sum(ingested.values()), "by_resolution": ingested,
                      "timeframe_warnings": warnings, **result}
            status = "success" if result.get("ok") else "failed"
        except Exception as exc:
            status, detail = "failed", {"error": str(exc)}
        store.exec("UPDATE job_runs SET status=?,detail=?::jsonb,finished_at=now() WHERE job_date=? AND broker_id=? AND symbol=? AND kind='market-close'",
                   [status, json.dumps(detail), day, row["broker_id"], row["symbol"]])
        runs.append({"broker_id": row["broker_id"], "symbol": row["symbol"], "status": status, **detail})
    return {"ok": all(r["status"] in ("success", "already-complete") for r in runs),
            "date": str(day), "symbols": len(runs), "runs": runs}
