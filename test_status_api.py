#!/usr/bin/env python3
"""Enhetstester for status-api.py."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent


def load_status_api(db_path: str):
    """Last status-api.py som modul med STATUS_DB satt til en midlertidig DB."""
    os.environ["STATUS_DB"] = db_path
    spec = importlib.util.spec_from_file_location("status_api", HERE / "status-api.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["status_api"] = mod
    spec.loader.exec_module(mod)
    return mod


def _create_full_schema(conn) -> None:
    """Opprett alle tabeller brukt av q_app_truth, q_overview, q_series og q_apps."""
    for ddl in [
        """CREATE TABLE IF NOT EXISTS apps (
            slug TEXT PRIMARY KEY, display_name TEXT, tier TEXT,
            github_repo TEXT, prod_url TEXT, dev_url TEXT)""",
        """CREATE TABLE IF NOT EXISTS versions (
            app_slug TEXT, package TEXT, version TEXT, ts TEXT)""",
        """CREATE TABLE IF NOT EXISTS deploys (
            app_slug TEXT, ts TEXT, commit_sha TEXT, status TEXT,
            duration_s INT, slot TEXT)""",
        """CREATE TABLE IF NOT EXISTS health_checks (
            app_slug TEXT, status TEXT, response_ms INT,
            http_status INT, check_kind TEXT, ts TEXT)""",
        """CREATE TABLE IF NOT EXISTS github_snapshots (
            app_slug TEXT, ts TEXT, open_prs INT, draft_prs INT,
            open_issues INT, dependabot_alerts INT, ci_status TEXT,
            last_commit_sha TEXT, last_commit_ts TEXT)""",
        """CREATE TABLE IF NOT EXISTS concerns (
            app_slug TEXT, status TEXT, severity TEXT, created_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS plans (
            app_slug TEXT, status TEXT, priority INT, created_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS work_log (app_slug TEXT, ts TEXT)""",
        """CREATE TABLE IF NOT EXISTS cloudflare_daily (
            app_slug TEXT, date TEXT, requests INT, unique_visitors INT,
            cache_hit_pct REAL, errors_4xx INT, errors_5xx INT, hostname TEXT)""",
        """CREATE TABLE IF NOT EXISTS lighthouse_scores (
            app_slug TEXT, ts TEXT, performance INT, accessibility INT,
            best_practices INT, seo INT, url TEXT)""",
        """CREATE TABLE IF NOT EXISTS tls_checks (
            app_slug TEXT, ts TEXT, domain TEXT, days_until_expiry INT, expires_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS backups (
            app_slug TEXT, ts TEXT, status TEXT, detail TEXT)""",
    ]:
        conn.execute(ddl)


def _start_status_server(db_path: str):
    """Start status-api på tilfeldig port. Returnerer (server, port)."""
    api = load_status_api(db_path)
    server = HTTPServer(("127.0.0.1", 0), api.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def _http_get(port: int, path: str) -> tuple:
    try:
        with urlopen(f"http://127.0.0.1:{port}{path}") as r:
            return r.status, json.loads(r.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())


class JobMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        # Lag en tom DB (uten job_metrics-tabell) — fallback-scenario.
        sqlite3.connect(self.db_path).close()
        self.api = load_status_api(self.db_path)

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    # ------------------------------------------------------------------
    # Graceful fallback naar tabellen mangler
    # ------------------------------------------------------------------
    def test_q_job_metrics_returnerer_tom_liste_naar_tabell_mangler(self) -> None:
        conn = self.api.open_ro()
        try:
            result = self.api.q_job_metrics(conn, job="issue-triage", days=7)
        finally:
            conn.close()
        self.assertEqual(result, {"job": "issue-triage", "days": 7, "points": []})

    def test_q_job_metrics_list_returnerer_tom_liste_naar_tabell_mangler(self) -> None:
        conn = self.api.open_ro()
        try:
            result = self.api.q_job_metrics_list(conn, days=7)
        finally:
            conn.close()
        self.assertEqual(result, {"days": 7, "jobs": []})

    # ------------------------------------------------------------------
    # Med skjema og data
    # ------------------------------------------------------------------
    def _create_table(self, conn) -> None:
        conn.execute(
            """
            CREATE TABLE job_metrics (
              job TEXT,
              day DATE,
              runs INT,
              fails INT,
              p50_dur_s INT,
              p95_dur_s INT,
              escalations_used INT,
              recoveries_triggered INT,
              recoveries_succeeded INT,
              tokens_in_total BIGINT,
              tokens_out_total BIGINT,
              cache_hits BIGINT,
              PRIMARY KEY (job, day)
            )
            """
        )

    def _insert(self, conn, job: str, day: str, **kw) -> None:
        defaults = dict(
            runs=1, fails=0, p50_dur_s=10, p95_dur_s=20,
            escalations_used=0, recoveries_triggered=0, recoveries_succeeded=0,
            tokens_in_total=100, tokens_out_total=50, cache_hits=10,
        )
        defaults.update(kw)
        conn.execute(
            "INSERT INTO job_metrics (job, day, runs, fails, p50_dur_s, p95_dur_s, "
            "escalations_used, recoveries_triggered, recoveries_succeeded, "
            "tokens_in_total, tokens_out_total, cache_hits) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job, day, defaults["runs"], defaults["fails"],
             defaults["p50_dur_s"], defaults["p95_dur_s"],
             defaults["escalations_used"], defaults["recoveries_triggered"],
             defaults["recoveries_succeeded"], defaults["tokens_in_total"],
             defaults["tokens_out_total"], defaults["cache_hits"]),
        )

    def test_q_job_metrics_returnerer_riktig_skjema(self) -> None:
        # Skriv via egen tilkobling (open_ro er read-only).
        with sqlite3.connect(self.db_path) as wconn:
            self._create_table(wconn)
            day = (date.today() - timedelta(days=1)).isoformat()
            self._insert(wconn, "issue-triage", day, runs=5, fails=1)
            wconn.commit()

        conn = self.api.open_ro()
        try:
            result = self.api.q_job_metrics(conn, job="issue-triage", days=30)
        finally:
            conn.close()

        self.assertEqual(result["job"], "issue-triage")
        self.assertEqual(result["days"], 30)
        self.assertEqual(len(result["points"]), 1)
        point = result["points"][0]
        forventede_felt = {
            "day", "runs", "fails", "p50_dur_s", "p95_dur_s",
            "escalations_used", "recoveries_triggered", "recoveries_succeeded",
            "tokens_in_total", "tokens_out_total", "cache_hits",
        }
        self.assertEqual(set(point.keys()), forventede_felt)
        self.assertEqual(point["runs"], 5)
        self.assertEqual(point["fails"], 1)

    def test_q_job_metrics_sorterer_eldst_forst(self) -> None:
        day_new = (date.today() - timedelta(days=1)).isoformat()
        day_mid = (date.today() - timedelta(days=2)).isoformat()
        day_old = (date.today() - timedelta(days=3)).isoformat()
        with sqlite3.connect(self.db_path) as wconn:
            self._create_table(wconn)
            self._insert(wconn, "issue-triage", day_new)
            self._insert(wconn, "issue-triage", day_old)
            self._insert(wconn, "issue-triage", day_mid)
            wconn.commit()

        conn = self.api.open_ro()
        try:
            result = self.api.q_job_metrics(conn, job="issue-triage", days=7)
        finally:
            conn.close()

        days = [p["day"] for p in result["points"]]
        self.assertEqual(days, [day_old, day_mid, day_new])

    def test_q_job_metrics_list_returnerer_distinkte_jobnavn(self) -> None:
        day0 = (date.today() - timedelta(days=1)).isoformat()
        day1 = (date.today() - timedelta(days=2)).isoformat()
        with sqlite3.connect(self.db_path) as wconn:
            self._create_table(wconn)
            self._insert(wconn, "issue-triage", day0)
            self._insert(wconn, "guardian", day0)
            self._insert(wconn, "issue-triage", day1)
            wconn.commit()

        conn = self.api.open_ro()
        try:
            result = self.api.q_job_metrics_list(conn, days=7)
        finally:
            conn.close()

        self.assertEqual(sorted(result["jobs"]), ["guardian", "issue-triage"])
        self.assertEqual(result["days"], 7)

    # ------------------------------------------------------------------
    # Days-clamping
    # ------------------------------------------------------------------
    def test_q_job_metrics_clamper_days_til_minst_1(self) -> None:
        conn = self.api.open_ro()
        try:
            result = self.api.q_job_metrics(conn, job="x", days=0)
        finally:
            conn.close()
        self.assertEqual(result["days"], 1)

    def test_q_job_metrics_clamper_days_til_hoyst_365(self) -> None:
        conn = self.api.open_ro()
        try:
            result = self.api.q_job_metrics(conn, job="x", days=9999)
        finally:
            conn.close()
        self.assertEqual(result["days"], 365)


class AppsQueryTests(unittest.TestCase):
    """Tests for q_apps() — med og uten tier-filter."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        with sqlite3.connect(self.db_path) as conn:
            _create_full_schema(conn)
            conn.executemany(
                "INSERT INTO apps (slug, display_name, tier) VALUES (?,?,?)",
                [("bio", "Biologportal", "primary"),
                 ("6810", "6810", "secondary"),
                 ("safekeeper", "Safekeeper", "lib")],
            )
            conn.commit()
        self.api = load_status_api(self.db_path)

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def _q(self, tiers):
        conn = self.api.open_ro()
        try:
            return self.api.q_apps(conn, tiers)
        finally:
            conn.close()

    def test_ingen_filter_returnerer_alle(self) -> None:
        slugs = {a["slug"] for a in self._q(None)}
        self.assertEqual(slugs, {"bio", "6810", "safekeeper"})

    def test_filtrerer_paa_en_tier(self) -> None:
        result = self._q(["primary"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["slug"], "bio")

    def test_filtrerer_paa_flere_tiers(self) -> None:
        slugs = {a["slug"] for a in self._q(["primary", "secondary"])}
        self.assertEqual(slugs, {"bio", "6810"})
        self.assertNotIn("safekeeper", slugs)

    def test_ukjent_tier_gir_tom_liste(self) -> None:
        self.assertEqual(self._q(["finnes-ikke"]), [])


class SeriesQueryTests(unittest.TestCase):
    """Tests for q_series() — gyldige og ugyldige metric-navn."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE health_checks (
                    app_slug TEXT, status TEXT, response_ms INT,
                    http_status INT, check_kind TEXT, ts TEXT)
            """)
            conn.execute(
                "INSERT INTO health_checks VALUES "
                "('bio','ok',120,200,'smoke',datetime('now','-1 hour'))"
            )
            conn.commit()
        self.api = load_status_api(self.db_path)

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def _q(self, slug, metric, days=30):
        conn = self.api.open_ro()
        try:
            return self.api.q_series(conn, slug, metric, days)
        finally:
            conn.close()

    def test_smoke_returnerer_punkter(self) -> None:
        result = self._q("bio", "smoke")
        self.assertEqual(result["metric"], "smoke")
        self.assertEqual(len(result["points"]), 1)
        self.assertEqual(result["points"][0]["tag"], "ok")

    def test_health_er_alias_for_smoke(self) -> None:
        self.assertEqual(len(self._q("bio", "health")["points"]), 1)

    def test_ugyldig_metric_gir_valueerror(self) -> None:
        conn = self.api.open_ro()
        try:
            with self.assertRaises(ValueError):
                self.api.q_series(conn, "bio", "ukjent-metric", 30)
        finally:
            conn.close()

    def test_clamper_days_til_hoyst_365(self) -> None:
        self.assertEqual(self._q("bio", "smoke", days=9999)["days"], 365)

    def test_clamper_days_til_minst_1(self) -> None:
        self.assertEqual(self._q("bio", "smoke", days=0)["days"], 1)

    def test_ukjent_slug_returnerer_ingen_punkter(self) -> None:
        self.assertEqual(self._q("finnes-ikke", "smoke")["points"], [])


class ShadowModesQueryTests(unittest.TestCase):
    """Tests for q_shadow_modes() — graceful fallback og filtrering."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        sqlite3.connect(self.db_path).close()
        self.api = load_status_api(self.db_path)

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_returnerer_tom_liste_naar_tabell_mangler(self) -> None:
        conn = self.api.open_ro()
        try:
            self.assertEqual(self.api.q_shadow_modes(conn), [])
        finally:
            conn.close()

    def test_ekskluderer_abandoned_status(self) -> None:
        with sqlite3.connect(self.db_path) as wconn:
            wconn.execute("""
                CREATE TABLE shadow_modes (
                    name TEXT PRIMARY KEY, description TEXT, owner TEXT,
                    status TEXT, started_at TEXT, promotion_criteria_json TEXT,
                    max_lifetime_days INT, promoted_at TEXT, promoted_by TEXT,
                    last_evaluated_at TEXT, last_match_rate REAL, last_sample_count INT)
            """)
            wconn.executemany(
                "INSERT INTO shadow_modes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    ("active", "Aktiv", "sys", "active", "2026-01-01",
                     None, 30, None, None, None, None, None),
                    ("aban", "Avviklet", "sys", "abandoned", "2026-01-01",
                     None, 30, None, None, None, None, None),
                ],
            )
            wconn.commit()
        self.api = load_status_api(self.db_path)
        conn = self.api.open_ro()
        try:
            result = self.api.q_shadow_modes(conn)
        finally:
            conn.close()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "active")


class AppTruthQueryTests(unittest.TestCase):
    """Tests for q_app_truth() — ikke-funnet (None) og funnet med tomme tabeller."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        with sqlite3.connect(self.db_path) as conn:
            _create_full_schema(conn)
            conn.execute(
                "INSERT INTO apps (slug, display_name, tier) VALUES "
                "('bio','Biologportal','primary')"
            )
            conn.commit()
        self.api = load_status_api(self.db_path)

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_returnerer_none_for_ukjent_slug(self) -> None:
        conn = self.api.open_ro()
        try:
            self.assertIsNone(self.api.q_app_truth(conn, "finnes-ikke"))
        finally:
            conn.close()

    def test_returnerer_dict_med_forventede_nokler_for_kjent_slug(self) -> None:
        conn = self.api.open_ro()
        try:
            result = self.api.q_app_truth(conn, "bio")
        finally:
            conn.close()
        self.assertIsNotNone(result)
        self.assertEqual(result["app"]["slug"], "bio")
        for key in ("latest_deploys", "health_24h", "versions",
                    "concerns_open", "plans_active", "recent_work"):
            self.assertIn(key, result)
            self.assertIsInstance(result[key], list)


class TriageClassifierTests(unittest.TestCase):
    """Tests for q_triage_classifier_window() — fallback og JSONL-parsing."""

    def setUp(self) -> None:
        self.tmpdb = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmpdb.close()
        self.tmplogdir = tempfile.mkdtemp()
        os.environ["TRIAGE_LOG_DIR"] = self.tmplogdir
        self.api = load_status_api(self.tmpdb.name)

    def tearDown(self) -> None:
        import shutil
        os.unlink(self.tmpdb.name)
        shutil.rmtree(self.tmplogdir)
        os.environ.pop("TRIAGE_LOG_DIR", None)

    def test_returnerer_tomt_skjelett_naar_logg_mangler(self) -> None:
        result = self.api.q_triage_classifier_window(24)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["outcomes"], {})
        self.assertEqual(result["window_hours"], 24)

    def test_parser_jsonl_og_aggregerer_outcomes(self) -> None:
        ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        log_path = os.path.join(self.tmplogdir, "classifier-eval.jsonl")
        with open(log_path, "w") as f:
            f.write(json.dumps({
                "ts": ts, "repo": "biologportal", "issue": 1,
                "outcome": "success", "class": "bug",
                "model": "sonnet", "effort": "medium",
                "retries": 0, "model_escalated": False, "dynamic_active": False,
            }) + "\n")
        self.api = load_status_api(self.tmpdb.name)
        result = self.api.q_triage_classifier_window(24)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["outcomes"].get("success"), 1)
        self.assertEqual(result["by_class"].get("bug"), 1)


class HttpEndpointTests(unittest.TestCase):
    """HTTP-nivå tester: /health, 404-routing, ugyldig series-metric."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        with sqlite3.connect(self.db_path) as conn:
            _create_full_schema(conn)
            conn.commit()
        self.server, self.port = _start_status_server(self.db_path)

    def tearDown(self) -> None:
        self.server.shutdown()
        os.unlink(self.db_path)

    def test_health_returnerer_200_med_status_ok(self) -> None:
        code, data = _http_get(self.port, "/health")
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "ok")

    def test_ukjent_sti_returnerer_404(self) -> None:
        code, _ = _http_get(self.port, "/api/finnes-ikke")
        self.assertEqual(code, 404)

    def test_ukjent_app_slug_returnerer_404(self) -> None:
        code, data = _http_get(self.port, "/api/app/finnes-ikke")
        self.assertEqual(code, 404)
        self.assertIn("ukjent app", data.get("error", ""))

    def test_ugyldig_series_metric_returnerer_400(self) -> None:
        code, _ = _http_get(self.port, "/api/series/bio/ugyldig-metric")
        self.assertEqual(code, 400)


class OverviewQueryTests(unittest.TestCase):
    """Verifiserer at q_overview bruker bulk-fetching (ikke N+1 per app).

    Uten fix: 1 (q_apps) + N×10 = 51 kall for N=5 apper.
    Med fix:  1 (q_apps) + 10 bulk-queries = ~11 kall uansett N.
    """

    class _CountingConn:
        """Proxy-wrapper som teller conn.execute()-kall."""
        def __init__(self, real: sqlite3.Connection):
            self._real = real
            self.call_count = 0

        def execute(self, sql, params=()):
            self.call_count += 1
            return self._real.execute(sql, params)

        def close(self):
            self._real.close()

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        with sqlite3.connect(self.db_path) as conn:
            _create_full_schema(conn)
            for i in range(5):
                conn.execute(
                    "INSERT INTO apps (slug, display_name, tier) VALUES (?,?,?)",
                    (f"app{i}", f"App {i}", "primary"),
                )
            conn.commit()
        self.api = load_status_api(self.db_path)

    def tearDown(self) -> None:
        os.unlink(self.db_path)

    def test_q_overview_bruker_bulk_fetch_ikke_n_pluss_1(self) -> None:
        """Med N=5 apper skal q_overview gjøre ≤15 DB-kall, ikke N×10=50+1."""
        real_conn = self.api.open_ro()
        counting = self._CountingConn(real_conn)
        try:
            result = self.api.q_overview(counting, ["primary"])
        finally:
            counting.close()

        self.assertEqual(len(result), 5, "Skal returnere alle 5 apper")
        MAX_QUERIES = 15
        self.assertLessEqual(
            counting.call_count, MAX_QUERIES,
            f"Forventet ≤{MAX_QUERIES} DB-kall (bulk-fetching), "
            f"fikk {counting.call_count}. N+1-mønster ikke eliminert."
        )

    def test_q_overview_returnerer_korrekte_felt_for_app_med_data(self) -> None:
        """Bulk-refaktorering skal returnere identisk struktur som originalkode."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO health_checks (app_slug, status, response_ms, ts) "
                "VALUES ('app0','ok',42,'2026-06-18T10:00:00')"
            )
            conn.execute(
                "INSERT INTO deploys (app_slug, commit_sha, status, ts, slot) "
                "VALUES ('app0','abc123','success','2026-06-18T09:00:00','blue')"
            )
            conn.execute(
                "INSERT INTO concerns (app_slug, status, severity, created_at) "
                "VALUES ('app0','open','high','2026-06-18T08:00:00')"
            )
            conn.commit()
        self.api = load_status_api(self.db_path)

        conn = self.api.open_ro()
        try:
            result = self.api.q_overview(conn, ["primary"])
        finally:
            conn.close()

        app0 = next(r for r in result if r["slug"] == "app0")
        self.assertEqual(app0["health"]["status"], "ok")
        self.assertEqual(app0["health"]["response_ms"], 42)
        self.assertEqual(app0["last_deploy"]["commit_sha"], "abc123")
        self.assertEqual(app0["last_deploy"]["status"], "success")
        self.assertEqual(app0["concerns"], {"high": 1})
        self.assertIsNone(app0["github"])
        self.assertIsNone(app0["cloudflare"])
        self.assertEqual(app0["plans"], {})

    def test_q_overview_tom_liste_uten_apper(self) -> None:
        conn = self.api.open_ro()
        try:
            result = self.api.q_overview(conn, ["finnes-ikke"])
        finally:
            conn.close()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
