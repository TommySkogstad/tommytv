#!/usr/bin/env python3
"""Enhetstester for status-api.py — fokus paa job-metrics-endepunktet (issue #20)."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_status_api(db_path: str):
    """Last status-api.py som modul med STATUS_DB satt til en midlertidig DB."""
    os.environ["STATUS_DB"] = db_path
    spec = importlib.util.spec_from_file_location("status_api", HERE / "status-api.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["status_api"] = mod
    spec.loader.exec_module(mod)
    return mod


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
            self._insert(wconn, "issue-triage", "2026-05-20", runs=5, fails=1)
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
        with sqlite3.connect(self.db_path) as wconn:
            self._create_table(wconn)
            self._insert(wconn, "issue-triage", "2026-05-20")
            self._insert(wconn, "issue-triage", "2026-05-18")
            self._insert(wconn, "issue-triage", "2026-05-19")
            wconn.commit()

        conn = self.api.open_ro()
        try:
            result = self.api.q_job_metrics(conn, job="issue-triage", days=365)
        finally:
            conn.close()

        days = [p["day"] for p in result["points"]]
        self.assertEqual(days, ["2026-05-18", "2026-05-19", "2026-05-20"])

    def test_q_job_metrics_list_returnerer_distinkte_jobnavn(self) -> None:
        with sqlite3.connect(self.db_path) as wconn:
            self._create_table(wconn)
            self._insert(wconn, "issue-triage", "2026-05-20")
            self._insert(wconn, "guardian", "2026-05-20")
            self._insert(wconn, "issue-triage", "2026-05-19")
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


if __name__ == "__main__":
    unittest.main()
