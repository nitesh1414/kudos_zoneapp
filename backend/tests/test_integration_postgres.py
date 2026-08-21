"""End-to-end test against a real PostgreSQL database.

DATABASE_URL comes from backend/.env (or the environment), exactly like the
application itself. For a disposable server:

    pip install pgserver
    python -c "import pgserver;print(pgserver.get_server('/tmp/pgdata').get_uri())"
    # put that URI in backend/.env, or export DATABASE_URL, then:
    python -m unittest discover -s backend/tests

The whole module is skipped when no database is configured, so the normal unit
suite still runs anywhere. A synthetic broker replaces the provider, so no
network access and no credentials are needed. Point it at a scratch database:
the suite truncates the tables it uses.
"""
import os
import unittest
from datetime import date, datetime, timedelta

import pandas as pd

import app  # loads backend/.env so the tests use the same configuration as the app

DSN = os.getenv("DATABASE_URL", "")

os.environ.setdefault("ZONEAPP_ADMIN_USERNAME", "admin")
os.environ.setdefault("ZONEAPP_ADMIN_PASSWORD", "integration-password")
os.environ.setdefault("ZONEAPP_API_KEY", "integration-job-key")
os.environ.setdefault("ZONEAPP_SECURE_COOKIES", "false")
os.environ.setdefault("ZONEAPP_SYMBOL", "NSE:NIFTY50-INDEX")

if DSN:
    from app.brokers.base import AuthStatus, BrokerAdapter, BrokerError
    from app.brokers.registry import BrokerType, register

    class MockBroker(BrokerAdapter):
        """Deterministic synthetic candles: 25 fifteen-minute bars per weekday."""

        name = "mock"
        calls = []

        def __init__(self, client_id=None, access_token=None, **_):
            self.client_id, self.access_token = client_id, access_token

        def auth_status(self):
            return AuthStatus(bool(self.access_token),
                              "Connected as Mock" if self.access_token else "Token Missing")

        def fetch_historical(self, symbol, resolution, date_from, date_to):
            if not self.access_token:
                raise BrokerError("Token Missing")
            MockBroker.calls.append((symbol, str(resolution), date_from, date_to))
            start = datetime.strptime(date_from, "%Y-%m-%d").date()
            end = datetime.strptime(date_to, "%Y-%m-%d").date()
            rows, day, seed = [], start, abs(hash(symbol)) % 500
            while day <= end:
                if day.weekday() < 5:
                    base = 20000 + seed + (day.toordinal() % 250) * 3
                    if str(resolution) == "D":
                        rows.append(dict(ts=pd.Timestamp(day) + pd.Timedelta(hours=9, minutes=15),
                                         o=base, h=base + 90, l=base - 70, c=base + 20, v=1000))
                    else:
                        for i in range(25):  # 09:15 → 15:15, enough for a complete session
                            drift = ((i * 7 + day.toordinal()) % 40) - 20
                            ts = pd.Timestamp(day) + pd.Timedelta(hours=9, minutes=15 + 15 * i)
                            rows.append(dict(ts=ts, o=base + drift, h=base + drift + 18,
                                             l=base + drift - 15, c=base + drift + 4, v=100))
                day += timedelta(days=1)
            if not rows:
                raise BrokerError(f"No candle data for {symbol}")
            return pd.DataFrame(rows)

        def fetch_live_quote(self, symbol):
            return {"ltp": 20000.0}

    register(BrokerType(key="mock", label="Mock provider", adapter=MockBroker,
                        fields=({"name": "client_id", "label": "Client ID", "secret": False},
                                {"name": "access_token", "label": "Access token", "secret": True,
                                 "required": False}),
                        token_ttl_hours=24, defaults={"client_id": "mock-client"}))


@unittest.skipUnless(DSN, "DATABASE_URL is not set")
class EndToEndTests(unittest.TestCase):
    """One ordered scenario: broker → token → seed → symbols → clients → job."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import app.main as main

        cls.main = main
        cls.store = main.store
        for table in ("job_runs", "zone_outcomes", "zone_sheets", "intraday_bars",
                      "tracked_symbols", "client_brokers", "sessions", "market_holidays",
                      "broker_connections"):
            cls.store.exec(f"DELETE FROM {table}")
        cls.store.exec("DELETE FROM users WHERE role='client'")
        cls.admin = TestClient(main.app)
        cls.admin.__enter__()  # triggers startup / bootstrap_admin

    @classmethod
    def tearDownClass(cls):
        cls.admin.__exit__(None, None, None)

    # ------------------------------------------------------------------ auth
    def test_01_login_is_required_and_enforced(self):
        anon = self.__class__.admin.__class__(self.main.app)
        self.assertEqual(401, anon.get("/api/me").status_code)
        self.assertEqual(401, anon.get("/api/dashboard").status_code)
        self.assertEqual(307, anon.get("/", follow_redirects=False).status_code)
        self.assertEqual("/login", anon.get("/", follow_redirects=False).headers["location"])

        bad = anon.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        self.assertEqual(401, bad.status_code)

        good = self.admin.post("/api/auth/login",
                               json={"username": "admin", "password": os.environ["ZONEAPP_ADMIN_PASSWORD"]})
        self.assertEqual(200, good.status_code)
        self.assertEqual("admin", good.json()["role"])
        me = self.admin.get("/api/me").json()
        self.assertEqual("admin", me["role"])

    # --------------------------------------------------------------- brokers
    def test_02_broker_without_token_is_saved_but_reports_missing(self):
        created = self.admin.post("/api/admin/brokers", json={
            "name": "Mock desk", "broker_type": "mock",
            "credentials": {"client_id": "mock-client"}, "enabled": True,
            "resolutions": ["15", "D"]})
        self.assertEqual(200, created.status_code, created.text)
        type(self).broker_id = created.json()["id"]
        self.assertFalse(created.json()["seeding"])

        listed = self.admin.get("/api/admin/brokers").json()
        self.assertEqual(1, len(listed))
        self.assertEqual("unknown", listed[0]["token_status"])

        tested = self.admin.post(f"/api/admin/brokers/{self.broker_id}/test").json()
        self.assertFalse(tested["connected"])
        self.assertIn("token", tested["message"].lower())

    def test_03_dependent_services_report_a_missing_token_clearly(self):
        from app.broker_store import BrokerUnavailable, load_adapter

        with self.assertRaises(BrokerUnavailable) as ctx:
            load_adapter(self.store, broker_id=self.broker_id)
        self.assertIn("Daily token", str(ctx.exception))

    def test_04_saving_a_token_syncs_everywhere_and_seeds(self):
        from app.broker_store import load_adapter

        saved = self.admin.post(f"/api/brokers/{self.broker_id}/token",
                                json={"access_token": "mock-token-1234567890", "seed_days": 120})
        self.assertEqual(200, saved.status_code, saved.text)
        body = saved.json()
        self.assertTrue(body["connected"])
        self.assertTrue(body["seeding"])

        # the resolver (used by the job, the CLI scripts and the seeder) sees it
        _, adapter = load_adapter(self.store, broker_id=self.broker_id)
        self.assertEqual("mock-token-1234567890", adapter.access_token)
        self.assertTrue(adapter.auth_status().connected)
        self.assertEqual("valid", self.admin.get("/api/admin/brokers").json()[0]["token_status"])
        self.assertTrue(self.admin.post(f"/api/admin/brokers/{self.broker_id}/test").json()["connected"])

        # the background seed already ran and produced real derived data
        health = self.admin.get("/api/health").json()
        self.assertGreater(health["bars"], 1000)
        self.assertGreater(health["sessions"], 10)
        self.assertGreater(health["zone_observations"], 10)
        self.assertEqual("Mock desk", health["broker"])

    def test_05_zone_engine_output_is_available(self):
        levels = self.admin.get("/api/levels/next")
        self.assertEqual(200, levels.status_code, levels.text)
        sheet = levels.json()
        self.assertTrue(sheet["resistances"] or sheet["supports"])
        self.assertIn("disclaimer", sheet)

        payload = self.admin.get("/api/dashboard").json()
        self.assertTrue(payload["zones"]["rows"])
        self.assertIsNotNone(payload["zones"]["basis"]["cpr_pct"])
        self.assertTrue(all("stars" in row for row in payload["zones"]["rows"]))
        row = payload["zones"]["rows"][0]
        self.assertIn("touch_pct", row)
        self.assertTrue(self.admin.get("/api/stats/zones").json()["by_stars"])
        self.assertTrue(self.admin.get("/api/stats/days").json()["gap_fill"])
        self.assertTrue(self.admin.get("/api/sessions?limit=5").json())

    # --------------------------------------------------------------- symbols
    def test_06_admin_can_add_symbols_and_aliases_expand(self):
        added = self.admin.post("/api/admin/symbols",
                                json={"symbol": "banknifty", "label": "Nifty Bank", "seed": False})
        self.assertEqual(200, added.status_code, added.text)
        self.assertEqual("NSE:NIFTYBANK-INDEX", added.json()["symbol"])

        self.admin.post("/api/admin/symbols", json={"symbol": "NSE:NIFTY50-INDEX", "seed": False})
        symbols = {s["symbol"] for s in self.admin.get("/api/symbols").json()}
        self.assertIn("NSE:NIFTYBANK-INDEX", symbols)
        self.assertIn("NSE:NIFTY50-INDEX", symbols)

    def test_07_seeding_a_date_range_fetches_only_that_window(self):
        MockBroker.calls.clear()
        response = self.admin.post("/api/admin/seed", json={
            "symbols": ["NSE:NIFTYBANK-INDEX"], "date_from": "2026-05-01", "date_to": "2026-06-30"})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(("2026-05-01", "2026-06-30"),
                         (response.json()["date_from"], response.json()["date_to"]))
        self.assertTrue(MockBroker.calls, "the broker was never called")
        for symbol, _res, start, end in MockBroker.calls:
            self.assertEqual("NSE:NIFTYBANK-INDEX", symbol)
            self.assertEqual(("2026-05-01", "2026-06-30"), (start, end))

        counts = self.store.counts("NSE:NIFTYBANK-INDEX")
        self.assertGreater(counts["bars"], 500)
        self.assertGreater(counts["sessions"], 5)

    def test_08_invalid_ranges_are_rejected(self):
        bad = self.admin.post("/api/admin/seed", json={"date_from": "2026-06-30", "date_to": "2026-05-01"})
        self.assertEqual(400, bad.status_code)
        self.assertIn("end date", bad.json()["detail"])

    def test_09_seed_all_covers_every_tracked_symbol(self):
        MockBroker.calls.clear()
        response = self.admin.post("/api/admin/seed", json={"days": 30})
        self.assertEqual(200, response.status_code, response.text)
        touched = {c[0] for c in MockBroker.calls}
        self.assertIn("NSE:NIFTY50-INDEX", touched)
        self.assertIn("NSE:NIFTYBANK-INDEX", touched)

    def test_10_admin_can_view_any_symbol_client_cannot(self):
        payload = self.admin.get("/api/dashboard?symbol=NSE:NIFTYBANK-INDEX").json()
        self.assertEqual("NSE:NIFTYBANK-INDEX", payload["symbol"])
        health = self.admin.get("/api/health?symbol=NSE:NIFTYBANK-INDEX").json()
        self.assertEqual("NSE:NIFTYBANK-INDEX", health["symbol"])

    # --------------------------------------------------------------- clients
    def test_11_client_lifecycle_and_permissions(self):
        from fastapi.testclient import TestClient

        created = self.admin.post("/api/admin/clients", json={
            "username": "asha", "display_name": "Asha Rao", "password": "client-password",
            "symbol": "banknifty", "broker_id": self.broker_id})
        self.assertEqual(200, created.status_code, created.text)
        client_id = created.json()["id"]

        duplicate = self.admin.post("/api/admin/clients", json={
            "username": "asha", "display_name": "Dup", "password": "client-password"})
        self.assertEqual(409, duplicate.status_code)

        row = next(c for c in self.admin.get("/api/admin/clients").json() if c["id"] == client_id)
        self.assertEqual("NSE:NIFTYBANK-INDEX", row["symbol"])  # alias expanded on create
        self.assertEqual("Mock desk", row["broker_name"])

        client = TestClient(self.main.app)
        self.assertEqual(200, client.post("/api/auth/login",
                                          json={"username": "asha", "password": "client-password"}).status_code)

        # scoped to their own symbol even when asking for another one
        self.assertEqual("NSE:NIFTYBANK-INDEX", client.get("/api/dashboard?symbol=NSE:NIFTY50-INDEX").json()["symbol"])
        # star ratings are stripped for clients
        payload = client.get("/api/dashboard").json()
        self.assertTrue(payload["zones"]["rows"])
        self.assertFalse(any("stars" in row for row in payload["zones"]["rows"]))
        self.assertNotIn("by_stars", client.get("/api/stats/zones").json())
        # but the base rates they need are still there
        self.assertIn("touch_pct", payload["zones"]["rows"][0])
        # admin-only endpoints are refused
        self.assertEqual(403, client.get("/api/admin/clients").status_code)
        self.assertEqual(403, client.post("/api/admin/seed", json={"days": 5}).status_code)
        # their broker panel reports the shared connection
        self.assertTrue(client.get("/api/my/broker").json()["assigned"])

        # edit, disable, re-enable, delete
        self.assertEqual(200, self.admin.patch(f"/api/admin/clients/{client_id}",
                                               json={"display_name": "Asha R", "password": "new-password-1"}).status_code)
        self.admin.patch(f"/api/admin/clients/{client_id}", json={"active": False})
        disabled = TestClient(self.main.app)
        self.assertEqual(401, disabled.post("/api/auth/login",
                                            json={"username": "asha", "password": "new-password-1"}).status_code)
        self.admin.patch(f"/api/admin/clients/{client_id}", json={"active": True})
        self.assertEqual(200, disabled.post("/api/auth/login",
                                            json={"username": "asha", "password": "new-password-1"}).status_code)
        self.assertEqual(200, self.admin.delete(f"/api/admin/clients/{client_id}").status_code)
        self.assertEqual(404, self.admin.delete(f"/api/admin/clients/{client_id}").status_code)
        self.assertNotIn("asha", [c["username"] for c in self.admin.get("/api/admin/clients").json()])

    # ------------------------------------------------------------------ jobs
    def test_12_market_close_job_runs_for_every_symbol(self):
        result = self.admin.post("/api/admin/jobs/market-close?force=true")
        self.assertEqual(200, result.status_code, result.text)
        body = result.json()
        self.assertTrue(body["ok"], body)
        symbols = {run["symbol"] for run in body["runs"]}
        self.assertIn("NSE:NIFTY50-INDEX", symbols)
        self.assertIn("NSE:NIFTYBANK-INDEX", symbols)
        self.assertTrue(all(run["status"] == "success" for run in body["runs"]), body["runs"])

    def test_13_job_is_idempotent_and_skips_non_trading_days(self):
        from app.jobs import is_market_day, run_market_close

        repeat = self.admin.post("/api/admin/jobs/market-close").json()
        statuses = {run["status"] for run in repeat["runs"]}
        self.assertTrue(statuses <= {"already-complete", "success"}, statuses)

        saturday = datetime(2026, 8, 22, 17, 30)
        skipped = run_market_close(self.store, now=saturday)
        self.assertTrue(skipped["skipped"])
        self.assertEqual("Weekend", skipped["reason"])

        self.admin.post("/api/admin/holidays", json={"holiday_date": "2026-08-24", "label": "Test holiday"})
        self.assertEqual((False, "Test holiday"), is_market_day(self.store, date(2026, 8, 24)))
        holiday_run = run_market_close(self.store, now=datetime(2026, 8, 24, 17, 30))
        self.assertTrue(holiday_run["skipped"])

        early = run_market_close(self.store, now=datetime(2026, 8, 25, 10, 0))
        self.assertEqual("Market has not closed", early["reason"])

    def test_14_cron_endpoint_requires_the_job_api_key(self):
        self.assertEqual(401, self.admin.post("/api/jobs/market-close").status_code)
        self.assertEqual(401, self.admin.post("/api/jobs/market-close",
                                              headers={"X-API-Key": "nope"}).status_code)
        ok = self.admin.post("/api/jobs/market-close?force=true",
                             headers={"X-API-Key": os.environ["ZONEAPP_API_KEY"]})
        self.assertEqual(200, ok.status_code)
        self.assertIn("runs", ok.json())

    def test_15_activity_feed_records_both_kinds(self):
        runs = self.admin.get("/api/admin/job-runs?limit=50").json()
        self.assertTrue(runs)
        kinds = {r["kind"] for r in runs}
        self.assertIn("seed", kinds)
        self.assertIn("market-close", kinds)
        self.assertTrue(all(r["status"] in ("success", "failed", "running") for r in runs))

    # -------------------------------------------------------------- holidays
    def test_16_holiday_crud(self):
        self.admin.post("/api/admin/holidays", json={"holiday_date": "2026-12-25", "label": "Christmas"})
        dates = [str(h["holiday_date"]) for h in self.admin.get("/api/admin/holidays").json()]
        self.assertIn("2026-12-25", dates)
        self.assertEqual(400, self.admin.post("/api/admin/holidays",
                                              json={"holiday_date": "25-12-2026"}).status_code)
        self.assertEqual(200, self.admin.delete("/api/admin/holidays/2026-12-25").status_code)
        dates = [str(h["holiday_date"]) for h in self.admin.get("/api/admin/holidays").json()]
        self.assertNotIn("2026-12-25", dates)

    # ------------------------------------------------------- symbol teardown
    def test_17_symbol_can_be_paused_and_removed_with_its_data(self):
        self.admin.patch("/api/admin/symbols/NSE:NIFTYBANK-INDEX", json={"active": False})
        row = next(s for s in self.admin.get("/api/symbols").json() if s["symbol"] == "NSE:NIFTYBANK-INDEX")
        self.assertFalse(row["active"])
        self.assertGreater(row["bars"], 0)

        self.assertEqual(200, self.admin.delete("/api/admin/symbols/NSE:NIFTYBANK-INDEX?purge=true").status_code)
        self.assertNotIn("NSE:NIFTYBANK-INDEX", {s["symbol"] for s in self.admin.get("/api/symbols").json()})
        self.assertEqual(0, int(self.store.counts("NSE:NIFTYBANK-INDEX")["bars"]))

    # -------------------------------------------------------------- frontend
    def test_18_single_page_app_is_served(self):
        login_page = self.admin.get("/login")
        self.assertEqual(200, login_page.status_code)
        self.assertIn("<div id=\"root\">", login_page.text)
        self.assertEqual(200, self.admin.get("/dashboard/overview").status_code)
        self.assertEqual(200, self.admin.get("/admin/seeding").status_code)
        self.assertEqual(404, self.admin.get("/api/does-not-exist").status_code)

    def test_19_logout_ends_the_session(self):
        from fastapi.testclient import TestClient

        client = TestClient(self.main.app)
        client.post("/api/auth/login", json={"username": "admin",
                                             "password": os.environ["ZONEAPP_ADMIN_PASSWORD"]})
        self.assertEqual(200, client.get("/api/me").status_code)
        self.assertEqual(200, client.post("/api/auth/logout").status_code)
        self.assertEqual(401, client.get("/api/me").status_code)





@unittest.skipUnless(DSN, "DATABASE_URL is not set")
class JsonSafetyTests(unittest.TestCase):
    """SQL NULLs must never reach the JSON encoder as NaN."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import app.main as main

        cls.main = main
        cls.client = TestClient(main.app)
        cls.client.__enter__()
        cls.client.post("/api/auth/login", json={"username": "admin",
                                                 "password": os.environ["ZONEAPP_ADMIN_PASSWORD"]})

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_client_without_a_broker_serialises(self):
        created = self.client.post("/api/admin/clients", json={
            "username": "nobroker", "display_name": "No Broker", "password": "client-password",
            "symbol": "NSE:NIFTY50-INDEX"})
        self.assertEqual(200, created.status_code, created.text)
        try:
            listed = self.client.get("/api/admin/clients")
            self.assertEqual(200, listed.status_code, listed.text[:200])
            row = next(c for c in listed.json() if c["username"] == "nobroker")
            self.assertIsNone(row["broker_id"])
            self.assertIsNone(row["broker_name"])
        finally:
            self.client.delete(f"/api/admin/clients/{created.json()['id']}")

    def test_records_helper_nulls_out_nan(self):
        import pandas as pd
        from app.db import records

        frame = pd.DataFrame([{"a": 1, "b": None}, {"a": None, "b": "x"}])
        self.assertEqual([{"a": 1, "b": None}, {"a": None, "b": "x"}], records(frame))
        self.assertEqual([], records(pd.DataFrame()))





@unittest.skipUnless(DSN, "DATABASE_URL is not set")
class LegacyMigrationTests(unittest.TestCase):
    """An installation created before multi-timeframe storage, job kinds and
    the symbol watchlist must migrate forward without losing data — including
    on plain PostgreSQL where the TimescaleDB extension is unavailable."""

    LEGACY_SCHEMA = """
    CREATE TABLE intraday_bars (
        symbol TEXT NOT NULL, ts TIMESTAMP NOT NULL, d DATE NOT NULL,
        o DOUBLE PRECISION, h DOUBLE PRECISION, l DOUBLE PRECISION,
        c DOUBLE PRECISION, v DOUBLE PRECISION, source TEXT,
        PRIMARY KEY (symbol, ts));
    CREATE TABLE kv (k TEXT PRIMARY KEY, v JSONB);
    CREATE TABLE users (
        id BIGSERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','client')),
        symbol TEXT NOT NULL DEFAULT 'NSE:NIFTY50-INDEX', active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE broker_connections (
        id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, broker_type TEXT NOT NULL,
        credentials JSONB NOT NULL DEFAULT '{}'::jsonb, enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE client_brokers (user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        broker_id BIGINT REFERENCES broker_connections(id) ON DELETE SET NULL);
    CREATE TABLE market_holidays (holiday_date DATE PRIMARY KEY, label TEXT NOT NULL DEFAULT 'Market holiday');
    CREATE TABLE job_runs (id BIGSERIAL PRIMARY KEY, job_date DATE NOT NULL, broker_id BIGINT,
        symbol TEXT NOT NULL, status TEXT NOT NULL, detail JSONB NOT NULL DEFAULT '{}'::jsonb,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
        UNIQUE(job_date,broker_id,symbol));
    CREATE TABLE zone_sheets (symbol TEXT NOT NULL, basis_date DATE NOT NULL, target_date DATE,
        label TEXT NOT NULL, lo DOUBLE PRECISION, hi DOUBLE PRECISION, key_px DOUBLE PRECISION,
        key_name TEXT, stars INTEGER, weight DOUBLE PRECISION, members TEXT, day_type TEXT,
        cpr_pct DOUBLE PRECISION, range_pct DOUBLE PRECISION, params_hash TEXT,
        created_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (symbol,basis_date,label));
    CREATE TABLE zone_outcomes (symbol TEXT NOT NULL, target_date DATE NOT NULL, label TEXT NOT NULL,
        stars INTEGER, key_px DOUBLE PRECISION, key_name TEXT, lo DOUBLE PRECISION, hi DOUBLE PRECISION,
        touched BOOLEAN, bounced BOOLEAN, broke BOOLEAN, held BOOLEAN, opened_inside BOOLEAN,
        day_type TEXT, gap_pct DOUBLE PRECISION, open_pos TEXT, PRIMARY KEY (symbol,target_date,label));
    """

    def test_forward_migration_from_a_v2_database(self):
        import psycopg
        from urllib.parse import urlsplit, urlunsplit
        from app.db import Store

        name = "zoneapp_migration_test"
        admin = psycopg.connect(DSN, autocommit=True)
        admin.execute(f"DROP DATABASE IF EXISTS {name}")
        admin.execute(f"CREATE DATABASE {name}")
        admin.close()
        parts = urlsplit(DSN)  # keep host/socket and options, swap the database name
        legacy_dsn = urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))

        con = psycopg.connect(legacy_dsn, autocommit=True)
        con.execute(self.LEGACY_SCHEMA)
        con.execute("INSERT INTO broker_connections(name,broker_type) VALUES ('Old desk','fyers')")
        con.execute("INSERT INTO job_runs(job_date,broker_id,symbol,status) VALUES (current_date,1,'NSE:NIFTY50-INDEX','success')")
        con.execute("INSERT INTO intraday_bars(symbol,ts,d,o,h,l,c,v,source) "
                    "VALUES ('NSE:NIFTY50-INDEX',now(),current_date,1,2,0.5,1.5,10,'old')")
        con.close()

        store = Store(legacy_dsn)
        columns = set(store.q("SELECT column_name FROM information_schema.columns "
                              "WHERE table_name='job_runs'").column_name)
        self.assertIn("kind", columns)
        self.assertIn("kind", store.one("SELECT pg_get_constraintdef(oid) d FROM pg_constraint "
                                        "WHERE conrelid='job_runs'::regclass AND contype='u'")["d"])
        self.assertIn("resolution", store.one("SELECT pg_get_constraintdef(oid) d FROM pg_constraint "
                                              "WHERE conrelid='intraday_bars'::regclass AND contype='p'")["d"])
        self.assertTrue(store.one("SELECT to_regclass('public.tracked_symbols') t")["t"])
        self.assertEqual(1, store.one("SELECT count(*) n FROM job_runs")["n"])
        self.assertEqual(1, store.one("SELECT count(*) n FROM intraday_bars")["n"])
        self.assertEqual("15", store.one("SELECT resolution FROM intraday_bars LIMIT 1")["resolution"])

        Store(legacy_dsn)  # idempotent


if __name__ == "__main__":
    unittest.main()
