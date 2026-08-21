"""Historical seeding that runs right after a broker token is saved.

The administrator adds a token, dependent services immediately have data:
candles are pulled for every symbol that depends on the connection and the
zone/base-rate tables are rebuilt. Progress is recorded in ``job_runs`` with
kind='seed' so the UI can show what happened.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .broker_store import BrokerUnavailable, load_adapter, symbols_for
from .service import ZoneParams, run_eod

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_DAYS = 180
SEED_RESOLUTIONS = ("15", "D")  # 15 is the zone engine's canonical timeframe


def _record(store, day, broker_id, symbol, status, detail):
    store.exec("""INSERT INTO job_runs(job_date,broker_id,symbol,kind,status,detail,finished_at)
        VALUES (?,?,?,'seed',?,?::jsonb, CASE WHEN ?='running' THEN NULL ELSE now() END)
        ON CONFLICT(job_date,broker_id,symbol,kind) DO UPDATE SET status=excluded.status,
            detail=excluded.detail, started_at=CASE WHEN excluded.status='running' THEN now()
            ELSE job_runs.started_at END, finished_at=excluded.finished_at""",
        [day, broker_id, symbol, status, json.dumps(detail), status])


def seed_symbol(store, broker_id: int, symbol: str, days: int = DEFAULT_DAYS,
                params: ZoneParams | None = None, resolutions=SEED_RESOLUTIONS):
    """Pull `days` of candles for one symbol and rebuild every derived table."""
    day = datetime.now(IST).date()
    _record(store, day, broker_id, symbol, "running", {"days": days})
    try:
        row, adapter = load_adapter(store, broker_id=broker_id)
        date_from = (day - timedelta(days=days)).isoformat()
        resolutions = [str(r) for r in (resolutions or SEED_RESOLUTIONS)]
        if "15" not in resolutions:
            resolutions.append("15")  # the zone engine's canonical timeframe
        ingested, warnings = {}, {}
        for resolution in resolutions:
            try:
                bars = adapter.fetch_historical(symbol, str(resolution), date_from, day.isoformat())
                ingested[str(resolution)] = store.upsert_bars(bars, symbol, row["broker_type"], str(resolution))
            except Exception as exc:  # one timeframe failing must not lose the others
                warnings[str(resolution)] = str(exc)
        if "15" not in ingested:
            raise RuntimeError(f"15-minute candles could not be fetched: {warnings.get('15', 'unknown error')}")
        result = run_eod(store, symbol, params or ZoneParams(), rebuild_all=True)
        detail = {"bars_ingested": sum(ingested.values()), "by_resolution": ingested,
                  "timeframe_warnings": warnings, "days": days, **result}
        _record(store, day, broker_id, symbol, "success" if result.get("ok") else "failed", detail)
        return detail
    except (BrokerUnavailable, Exception) as exc:
        detail = {"error": str(exc), "days": days}
        _record(store, day, broker_id, symbol, "failed", detail)
        return detail


def seed_broker(store, broker_id: int, days: int = DEFAULT_DAYS,
                params: ZoneParams | None = None, symbols=None):
    """Seed every symbol that depends on this broker connection."""
    targets = symbols or symbols_for(store, broker_id)
    return {"broker_id": broker_id, "days": days, "symbols": len(targets),
            "runs": [{"symbol": s, **seed_symbol(store, broker_id, s, days, params)} for s in targets]}


def seed_all(store, days: int = DEFAULT_DAYS, params: ZoneParams | None = None):
    """Seed every symbol the platform tracks, each through its own broker."""
    from .jobs import targets as pairs  # local import keeps the module graph flat
    rows = pairs(store)
    return {"days": days, "symbols": len(rows),
            "runs": [{"symbol": r["symbol"], "broker_id": r["broker_id"],
                      **seed_symbol(store, r["broker_id"], r["symbol"], days, params,
                                    r.get("resolutions") or SEED_RESOLUTIONS)}
                     for r in rows]}


def recent_runs(store, limit: int = 20):
    rows = store.q("""SELECT j.id, j.job_date, j.broker_id, b.name broker_name, j.symbol, j.kind,
               j.status, j.detail, j.started_at, j.finished_at
        FROM job_runs j LEFT JOIN broker_connections b ON b.id = j.broker_id
        ORDER BY j.started_at DESC LIMIT ?""", [limit])
    return [] if rows.empty else rows.to_dict("records")
