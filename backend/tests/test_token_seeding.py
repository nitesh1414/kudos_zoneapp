"""Saving a broker token must make every dependent service usable at once.

These tests use an in-memory store double, so they run without PostgreSQL:
they prove that credentials saved by an administrator are what the resolver,
the seeder and the market-close job all read.
"""
import json
import os
import unittest

import pandas as pd

os.environ.setdefault("ZONEAPP_API_KEY", "unit-test-key")
os.environ.setdefault("ZONEAPP_ADMIN_PASSWORD", "unit-test-password")

from app import broker_store, seeding
from app.auth import decrypt_credentials, encrypt_credentials
from app.brokers.base import AuthStatus, BrokerAdapter
from app.brokers.registry import BrokerType, register


class FakeBroker(BrokerAdapter):
    name = "fake"

    def __init__(self, client_id=None, access_token=None, **_):
        self.client_id, self.access_token = client_id, access_token

    def auth_status(self):
        return AuthStatus(bool(self.access_token), "connected" if self.access_token else "Token Missing")

    def fetch_historical(self, symbol, resolution, date_from, date_to):
        index = pd.date_range("2026-08-20 09:15", periods=4, freq="15min")
        return pd.DataFrame({"ts": index, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1.0})

    def fetch_live_quote(self, symbol):
        return {}


register(BrokerType(key="fake", label="Fake", adapter=FakeBroker,
                    fields=({"name": "client_id", "label": "Client", "secret": False},),
                    token_ttl_hours=24))


class FakeStore:
    """Only the handful of calls the resolver/seeder make."""

    def __init__(self, access_token=""):
        self.connection_row = {
            "id": 1, "name": "Main", "broker_type": "fake",
            "credentials": encrypt_credentials({"client_id": "cid", "access_token": access_token}),
            "resolutions": ["15", "D"], "enabled": True,
            "token_updated_at": None, "token_expires_at": None,
        }
        self.bars, self.job_runs = [], []

    def one(self, sql, params=None):
        return dict(self.connection_row) if "broker_connections" in sql else None

    def q(self, sql, params=None):
        if "u.symbol" in sql:
            return pd.DataFrame([{"symbol": "NSE:NIFTY50-INDEX"}])
        return pd.DataFrame()

    def exec(self, sql, params=None):
        if "job_runs" in sql:
            self.job_runs.append(params)
        elif "UPDATE broker_connections SET credentials" in sql:
            self.connection_row["credentials"] = json.loads(params[0])
            self.connection_row["token_updated_at"] = params[1]
            self.connection_row["token_expires_at"] = params[2]

    def upsert_bars(self, df, symbol, source, resolution="15"):
        self.bars.append((symbol, resolution, len(df)))
        return len(df)

    def kv_get(self, key, default=None):
        return default


class ResolverTests(unittest.TestCase):
    def test_stored_token_is_used(self):
        store = FakeStore(access_token="stored-token")
        row, adapter = broker_store.load_adapter(store, broker_id=1)
        self.assertEqual("Main", row["name"])
        self.assertEqual("stored-token", adapter.access_token)
        self.assertTrue(adapter.auth_status().connected)

    def test_missing_token_reports_where_to_add_it(self):
        store = FakeStore(access_token="")
        os.environ.pop("FYERS_ACCESS_TOKEN", None)
        with self.assertRaises(broker_store.BrokerUnavailable) as ctx:
            broker_store.load_adapter(store, broker_id=1)
        self.assertIn("Daily token", str(ctx.exception))

    def test_environment_token_is_only_a_fallback(self):
        store = FakeStore(access_token="")
        os.environ["FYERS_ACCESS_TOKEN"] = "env-token"
        try:
            _, adapter = broker_store.load_adapter(store, broker_id=1)
            self.assertEqual("env-token", adapter.access_token)
        finally:
            os.environ.pop("FYERS_ACCESS_TOKEN", None)


class SeedingTests(unittest.TestCase):
    def setUp(self):
        self._run_eod = seeding.run_eod
        seeding.run_eod = lambda store, symbol, params, rebuild_all=False: {
            "ok": True, "sheets_written": 3, "sessions_scored": 3}

    def tearDown(self):
        seeding.run_eod = self._run_eod

    def test_seed_ingests_and_rebuilds(self):
        store = FakeStore(access_token="stored-token")
        result = seeding.seed_broker(store, 1, days=30)
        run = result["runs"][0]
        self.assertEqual("NSE:NIFTY50-INDEX", run["symbol"])
        self.assertEqual(8, run["bars_ingested"])  # 4 bars x 2 resolutions
        self.assertEqual(3, run["sessions_scored"])
        self.assertEqual({"15", "D"}, set(run["by_resolution"]))
        self.assertTrue(any("running" in (p or []) for p in store.job_runs))

    def test_seed_without_token_fails_loudly(self):
        store = FakeStore(access_token="")
        os.environ.pop("FYERS_ACCESS_TOKEN", None)
        run = seeding.seed_broker(store, 1, days=30)["runs"][0]
        self.assertIn("access token", run["error"])
        self.assertNotIn("bars_ingested", run)


class TokenEndpointTests(unittest.TestCase):
    """Saving a token through the API must kick off the seeder immediately."""

    def setUp(self):
        import app.db as db
        db.Store.__init__ = lambda self, dsn=None: None
        db.Store.one = lambda self, *a, **k: None
        import app.main as main
        self.main = main
        self.store = FakeStore(access_token="")
        main.store = self.store
        self._run_eod = seeding.run_eod
        seeding.run_eod = lambda store, symbol, params, rebuild_all=False: {
            "ok": True, "sheets_written": 3, "sessions_scored": 3}
        admin = {"id": 1, "username": "a", "display_name": "A", "role": "admin",
                 "symbol": "NSE:NIFTY50-INDEX", "active": True}
        main.app.dependency_overrides[main.current_user] = lambda: admin
        main.app.dependency_overrides[main.admin_user] = lambda: admin

    def tearDown(self):
        seeding.run_eod = self._run_eod
        self.main.app.dependency_overrides.clear()

    def test_saving_a_token_seeds_dependent_symbols(self):
        from fastapi.testclient import TestClient

        with TestClient(self.main.app) as client:
            response = client.post("/api/brokers/1/token",
                                   json={"access_token": "fresh-token-123", "seed_days": 30})
        body = response.json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(body["seeding"])
        self.assertEqual(["NSE:NIFTY50-INDEX"], body["seed_symbols"])
        # the saved token is what the resolver hands to dependent services
        self.assertEqual("fresh-token-123",
                         decrypt_credentials(self.store.connection_row["credentials"])["access_token"])
        # and the background seeder actually ingested candles with it
        self.assertEqual([("NSE:NIFTY50-INDEX", "15", 4), ("NSE:NIFTY50-INDEX", "D", 4)], self.store.bars)
        self.assertIn("success", [p[3] for p in self.store.job_runs])





class WatchlistTests(unittest.TestCase):
    """The platform tracks many symbols, not just the ones clients use."""

    def test_aliases_are_expanded(self):
        from app import symbols as watchlist

        self.assertEqual("NSE:NIFTY50-INDEX", watchlist.normalize(" nifty "))
        self.assertEqual("NSE:NIFTYBANK-INDEX", watchlist.normalize("BankNifty"))
        # unknown symbols pass through untouched, only cleaned up
        self.assertEqual("MCX:CRUDEOIL25AUGFUT", watchlist.normalize("mcx:crudeoil25augfut"))
        with self.assertRaises(ValueError):
            watchlist.normalize("  ")

    def test_job_targets_cover_watchlist_and_clients(self):
        from app import jobs

        class Store:
            def q(self, sql, params=None):
                if "broker_connections WHERE enabled" in sql:
                    return pd.DataFrame([{"id": 1, "broker_type": "fake", "resolutions": ["15", "D"],
                                          "token_expires_at": None}])
                if "client_brokers" in sql:
                    return pd.DataFrame([{"broker_id": 1, "symbol": "NSE:NIFTY50-INDEX"}])
                if "tracked_symbols" in sql:
                    return pd.DataFrame([
                        {"symbol": "NSE:NIFTYBANK-INDEX", "resolutions": ["15"], "broker_id": None},
                        {"symbol": "NSE:NIFTY50-INDEX", "resolutions": ["15", "D"], "broker_id": None},
                    ])
                return pd.DataFrame()

        rows = jobs.targets(Store())
        self.assertEqual({"NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"}, {r["symbol"] for r in rows})
        self.assertTrue(all(r["broker_id"] == 1 for r in rows))





class SeedWindowTests(unittest.TestCase):
    """The admin seeding tab sends either a day count or explicit dates."""

    def test_trailing_day_count(self):
        from datetime import date, timedelta

        start, end = seeding.date_window(days=30)
        self.assertEqual(date.today().isoformat(), end)
        self.assertEqual((date.today() - timedelta(days=30)).isoformat(), start)

    def test_explicit_range_is_preserved(self):
        start, end = seeding.date_window(None, "2026-01-01", "2026-03-31")
        self.assertEqual(("2026-01-01", "2026-03-31"), (start, end))

    def test_end_before_start_is_rejected(self):
        with self.assertRaises(ValueError):
            seeding.date_window(None, "2026-03-31", "2026-01-01")

    def test_future_end_is_clamped_to_today(self):
        from datetime import date

        _, end = seeding.date_window(None, "2026-01-01", "2999-01-01")
        self.assertEqual(date.today().isoformat(), end)

    def test_seed_all_can_target_a_subset(self):
        calls = []
        original = seeding.seed_symbol
        seeding.seed_symbol = lambda store, broker_id, symbol, *a, **k: calls.append(symbol) or {"ok": True}
        try:
            class Store:
                def q(self, sql, params=None):
                    if "broker_connections WHERE enabled" in sql:
                        return pd.DataFrame([{"id": 1, "broker_type": "fake", "resolutions": ["15"],
                                              "token_expires_at": None}])
                    if "tracked_symbols" in sql:
                        return pd.DataFrame([{"symbol": "A", "resolutions": ["15"], "broker_id": None},
                                             {"symbol": "B", "resolutions": ["15"], "broker_id": None}])
                    return pd.DataFrame()

            result = seeding.seed_all(Store(), symbols=["b"], date_from="2026-01-01", date_to="2026-02-01")
            self.assertEqual(["B"], calls)
            self.assertEqual(1, result["symbols"])
        finally:
            seeding.seed_symbol = original


if __name__ == "__main__":
    unittest.main()
