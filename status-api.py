#!/usr/bin/env python3
"""
status-api — read-only HTTP-tjeneste for status-DB.

Mountet DB: /data/status.db (fra host: ~/status-data/status.db)
Port:       8882 (lyttende på 0.0.0.0 inne i container)

Nginx proxyer /status-api/ → denne tjenesten. Frontend (status.html) henter JSON.

Endepunkter:
  GET  /health
  GET  /api/apps?tier=primary,secondary
  GET  /api/overview?tier=primary
  GET  /api/app/<slug>               — full "truth": app-rad, deploys, versjoner,
                                       concerns, plans, work_log, CF, Lighthouse, TLS
  GET  /api/series/<slug>/<metric>?days=30
        metrics: smoke, endpoint, health (legacy alias for smoke),
                 cloudflare, lighthouse, github, deploys, tls
  GET  /api/shadow-modes             — livssyklus-data for registrerte shadow-modes

Alle svar er JSON. CORS tillates (LAN-only via nginx).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = os.environ.get("STATUS_DB", "/data/status.db")
PORT = int(os.environ.get("STATUS_API_PORT", "8882"))
TRIAGE_LOG_DIR = os.environ.get("TRIAGE_LOG_DIR", "/triage-logs")


def rows_to_dicts(cursor) -> list[dict]:
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def open_ro() -> sqlite3.Connection:
    """Åpne DB for lesing.

    WAL-mode krever skrivetilgang for -wal/-shm — derfor mountes katalogen
    read-write. PRAGMA query_only = 1 sikrer at denne tjenesten aldri kan
    skrive til DB (INSERT/UPDATE/DELETE returnerer feil).
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = 1")
    return conn


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------
def q_apps(conn, tiers: list[str] | None) -> list[dict]:
    sql = "SELECT * FROM apps"
    params: list = []
    if tiers:
        placeholders = ",".join(["?"] * len(tiers))
        sql += f" WHERE tier IN ({placeholders})"
        params = tiers
    sql += (" ORDER BY CASE tier WHEN 'primary' THEN 1 WHEN 'secondary' THEN 2 "
            "WHEN 'lib' THEN 3 WHEN 'maintenance' THEN 4 "
            "WHEN 'unclassified' THEN 5 WHEN 'archived' THEN 6 END, slug")
    return rows_to_dicts(conn.execute(sql, params))


def q_overview(conn, tiers: list[str]) -> list[dict]:
    apps = q_apps(conn, tiers)
    out = []
    for a in apps:
        slug = a["slug"]
        latest_health = conn.execute(
            "SELECT status, response_ms, ts FROM health_checks WHERE app_slug = ? "
            "ORDER BY ts DESC LIMIT 1", (slug,)).fetchone()
        latest_deploy = conn.execute(
            "SELECT commit_sha, status, ts, slot FROM deploys WHERE app_slug = ? "
            "ORDER BY ts DESC LIMIT 1", (slug,)).fetchone()
        latest_gh = conn.execute(
            "SELECT open_prs, draft_prs, open_issues, dependabot_alerts, ci_status, "
            "last_commit_sha, last_commit_ts FROM github_snapshots "
            "WHERE app_slug = ? ORDER BY ts DESC LIMIT 1", (slug,)).fetchone()
        # Aggreger over alle tenants (hostnames) for siste tilgjengelige dato
        latest_cf = conn.execute(
            "SELECT date, SUM(requests) AS requests, SUM(unique_visitors) AS unique_visitors, "
            "CASE WHEN SUM(requests) > 0 "
            "     THEN ROUND(SUM(requests * cache_hit_pct / 100.0) * 100.0 / SUM(requests), 2) "
            "     ELSE NULL END AS cache_hit_pct, "
            "SUM(errors_4xx) AS errors_4xx, SUM(errors_5xx) AS errors_5xx, "
            "COUNT(DISTINCT hostname) AS tenant_count "
            "FROM cloudflare_daily WHERE app_slug = ? "
            "AND date = (SELECT MAX(date) FROM cloudflare_daily WHERE app_slug = ?) "
            "GROUP BY date", (slug, slug)).fetchone()
        latest_lh = conn.execute(
            "SELECT performance, accessibility, best_practices, seo, ts "
            "FROM lighthouse_scores WHERE app_slug = ? "
            "ORDER BY ts DESC LIMIT 1", (slug,)).fetchone()
        latest_tls = conn.execute(
            "SELECT domain, days_until_expiry, expires_at FROM tls_checks "
            "WHERE app_slug = ? ORDER BY ts DESC LIMIT 1", (slug,)).fetchone()
        latest_backup = conn.execute(
            "SELECT status, ts, detail FROM backups WHERE app_slug = ? "
            "ORDER BY ts DESC LIMIT 1", (slug,)).fetchone()

        concerns = rows_to_dicts(conn.execute(
            "SELECT severity, COUNT(*) AS n FROM concerns WHERE app_slug = ? "
            "AND status != 'resolved' GROUP BY severity", (slug,)))
        plans = rows_to_dicts(conn.execute(
            "SELECT status, COUNT(*) AS n FROM plans WHERE app_slug = ? "
            "AND status NOT IN ('done','cancelled') GROUP BY status", (slug,)))

        # Siste 24t helse-trend (opp/ned ratio) for sparkline
        health_24h = rows_to_dicts(conn.execute(
            "SELECT status, response_ms, ts FROM health_checks "
            "WHERE app_slug = ? AND ts > datetime('now','-1 day') "
            "ORDER BY ts", (slug,)))

        out.append({
            "slug": slug,
            "display_name": a["display_name"],
            "tier": a["tier"],
            "github_repo": a["github_repo"],
            "prod_url": a["prod_url"],
            "dev_url": a["dev_url"],
            "health": dict(latest_health) if latest_health else None,
            "health_24h": health_24h,
            "last_deploy": dict(latest_deploy) if latest_deploy else None,
            "github": dict(latest_gh) if latest_gh else None,
            "cloudflare": dict(latest_cf) if latest_cf else None,
            "lighthouse": dict(latest_lh) if latest_lh else None,
            "tls": dict(latest_tls) if latest_tls else None,
            "backup": dict(latest_backup) if latest_backup else None,
            "concerns": {r["severity"]: r["n"] for r in concerns},
            "plans": {r["status"]: r["n"] for r in plans},
        })
    return out


def q_app_truth(conn, slug: str) -> dict | None:
    app = conn.execute("SELECT * FROM apps WHERE slug = ?", (slug,)).fetchone()
    if not app:
        return None

    latest_versions = rows_to_dicts(conn.execute(
        "SELECT package, version, ts FROM versions v WHERE app_slug = ? "
        "AND ts = (SELECT MAX(ts) FROM versions WHERE app_slug = v.app_slug "
        "AND package = v.package) ORDER BY package", (slug,)))

    return {
        "app": dict(app),
        "latest_deploys": rows_to_dicts(conn.execute(
            "SELECT * FROM deploys WHERE app_slug = ? ORDER BY ts DESC LIMIT 20",
            (slug,))),
        "health_24h": rows_to_dicts(conn.execute(
            "SELECT status, response_ms, http_status, ts FROM health_checks "
            "WHERE app_slug = ? AND ts > datetime('now','-1 day') ORDER BY ts",
            (slug,))),
        "github_latest": rows_to_dicts(conn.execute(
            "SELECT * FROM github_snapshots WHERE app_slug = ? ORDER BY ts DESC LIMIT 1",
            (slug,)))[:1],
        "versions": latest_versions,
        "concerns_open": rows_to_dicts(conn.execute(
            "SELECT * FROM concerns WHERE app_slug = ? AND status != 'resolved' "
            "ORDER BY CASE severity WHEN 'crit' THEN 1 WHEN 'high' THEN 2 "
            "WHEN 'med' THEN 3 WHEN 'low' THEN 4 ELSE 5 END, created_at DESC",
            (slug,))),
        "plans_active": rows_to_dicts(conn.execute(
            "SELECT * FROM plans WHERE app_slug = ? AND status NOT IN ('done','cancelled') "
            "ORDER BY priority, created_at DESC", (slug,))),
        "recent_work": rows_to_dicts(conn.execute(
            "SELECT * FROM work_log WHERE app_slug = ? ORDER BY ts DESC LIMIT 50",
            (slug,))),
        # cloudflare_30d: aggregert per dato (for tidsserie-graf)
        "cloudflare_30d": rows_to_dicts(conn.execute(
            "SELECT date, SUM(requests) AS requests, SUM(unique_visitors) AS unique_visitors, "
            "CASE WHEN SUM(requests) > 0 "
            "     THEN ROUND(SUM(requests * cache_hit_pct / 100.0) * 100.0 / SUM(requests), 2) "
            "     ELSE NULL END AS cache_hit_pct, "
            "SUM(errors_4xx) AS errors_4xx, SUM(errors_5xx) AS errors_5xx "
            "FROM cloudflare_daily WHERE app_slug = ? AND date > date('now','-30 day') "
            "GROUP BY date ORDER BY date", (slug,))),
        # cloudflare_tenants_latest: én rad per hostname, nyeste dato
        "cloudflare_tenants_latest": rows_to_dicts(conn.execute(
            "SELECT * FROM cloudflare_daily cd WHERE app_slug = ? "
            "AND date = (SELECT MAX(date) FROM cloudflare_daily WHERE app_slug = cd.app_slug) "
            "ORDER BY requests DESC", (slug,))),
        "lighthouse_history": rows_to_dicts(conn.execute(
            "SELECT * FROM lighthouse_scores WHERE app_slug = ? "
            "ORDER BY ts DESC LIMIT 50", (slug,))),
        "tls_latest": rows_to_dicts(conn.execute(
            "SELECT * FROM tls_checks WHERE app_slug = ? ORDER BY ts DESC LIMIT 1",
            (slug,)))[:1],
        "backups_30d": rows_to_dicts(conn.execute(
            "SELECT * FROM backups WHERE app_slug = ? "
            "AND ts > datetime('now','-30 day') ORDER BY ts DESC", (slug,))),
    }


def q_shadow_modes(conn) -> list[dict]:
    """Hent alle registrerte shadow-modes med livssyklus-data.

    Returnerer tom liste hvis tabellen ikke finnes enda (shadow_modes legges til
    av schema-migrasjon 003, se misc-scripts #115/#118).
    """
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_modes'"
    ).fetchone()
    if not exists:
        return []
    rows = rows_to_dicts(conn.execute(
        "SELECT name, description, owner, status, started_at, "
        "promotion_criteria_json, max_lifetime_days, "
        "promoted_at, promoted_by, "
        "last_evaluated_at, last_match_rate, last_sample_count "
        "FROM shadow_modes ORDER BY started_at DESC"))
    for r in rows:
        raw = r.pop("promotion_criteria_json", None)
        try:
            r["promotion_criteria"] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            r["promotion_criteria"] = None
    return rows


def q_series(conn, slug: str, metric: str, days: int) -> dict:
    """Tidsserier for grafer. Returnerer {points: [...], metric, slug}."""
    days = max(1, min(days, 365))
    # NB: "health" (misc-scripts#159) var historisk navn paa frontend-render-
    # maalingen (Playwright smoke-test, ~1,5 s). Vi eksponerer den som "smoke"
    # fra 2026-04-21 og holder "health" som bakoverkompatibel alias. Nytt navn
    # "endpoint" (misc-scripts#160) er reservert for backend-curl-timing.
    metric_map = {
        "smoke": (
            "SELECT ts, response_ms AS value, status AS tag FROM health_checks "
            "WHERE app_slug = ? AND ts > datetime('now', ?) "
            "AND (check_kind = 'smoke' OR check_kind IS NULL) ORDER BY ts"
        ),
        "endpoint": (
            "SELECT ts, response_ms AS value, status AS tag FROM health_checks "
            "WHERE app_slug = ? AND ts > datetime('now', ?) "
            "AND check_kind = 'endpoint' ORDER BY ts"
        ),
        "health": (
            "SELECT ts, response_ms AS value, status AS tag FROM health_checks "
            "WHERE app_slug = ? AND ts > datetime('now', ?) "
            "AND (check_kind = 'smoke' OR check_kind IS NULL) ORDER BY ts"
        ),
        "cloudflare": (
            "SELECT date AS ts, SUM(requests) AS value, SUM(errors_5xx) AS errors, "
            "CASE WHEN SUM(requests) > 0 "
            "     THEN ROUND(SUM(requests * cache_hit_pct/100.0) * 100.0 / SUM(requests), 2) "
            "     ELSE NULL END AS cache_hit, "
            "SUM(unique_visitors) AS visitors "
            "FROM cloudflare_daily WHERE app_slug = ? AND date > date('now', ?) "
            "GROUP BY date ORDER BY date"
        ),
        "lighthouse": (
            "SELECT ts, performance AS value, accessibility, best_practices, seo, url "
            "FROM lighthouse_scores WHERE app_slug = ? AND ts > datetime('now', ?) "
            "ORDER BY ts"
        ),
        "github": (
            "SELECT ts, open_prs, open_issues, dependabot_alerts, ci_status "
            "FROM github_snapshots WHERE app_slug = ? AND ts > datetime('now', ?) "
            "ORDER BY ts"
        ),
        "deploys": (
            "SELECT ts, status AS tag, duration_s AS value, commit_sha, slot "
            "FROM deploys WHERE app_slug = ? AND ts > datetime('now', ?) "
            "ORDER BY ts"
        ),
        "tls": (
            "SELECT ts, days_until_expiry AS value, domain AS tag "
            "FROM tls_checks WHERE app_slug = ? AND ts > datetime('now', ?) "
            "ORDER BY ts"
        ),
    }
    sql = metric_map.get(metric)
    if not sql:
        raise ValueError(f"ukjent metric: {metric}")
    offset = f"-{days} day"
    return {
        "slug": slug,
        "metric": metric,
        "days": days,
        "points": rows_to_dicts(conn.execute(sql, (slug, offset))),
    }


# --------------------------------------------------------------------------
# Issue-triage classifier-evaluation (rullerende 24t)
# --------------------------------------------------------------------------
def q_triage_classifier_window(hours: int = 24) -> dict:
    """Les ~/log/issue-triage/classifier-eval.jsonl, filter siste `hours` og
    aggreger: total, outcome-fordeling, klasse-fordeling, modell-fordeling,
    eskaleringer (retries>0), suksessrate per klasse.

    Returnerer et tomt skjelett hvis loggen mangler — frontend viser "ingen data".
    """
    log_path = os.path.join(TRIAGE_LOG_DIR, "classifier-eval.jsonl")
    empty = {
        "window_hours": hours, "total": 0,
        "outcomes": {}, "by_class": {}, "by_model": {},
        "escalations": 0, "success_rate_by_class": {},
        "dynamic_active": None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not os.path.exists(log_path):
        return empty

    cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
    records: list[dict] = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = r.get("ts", "")
                try:
                    # ts er ISO-8601 med tz — fromisoformat handterer offset
                    rec_ts = datetime.fromisoformat(ts).timestamp()
                except (ValueError, TypeError):
                    continue
                if rec_ts >= cutoff:
                    records.append(r)
    except OSError:
        return empty

    if not records:
        return empty

    outcomes: dict[str, int] = {}
    by_class: dict[str, int] = {}
    by_model: dict[str, int] = {}
    class_success: dict[str, list[int]] = {}  # class -> [success, total]
    escalations = 0
    dynamic_count = 0

    for r in records:
        o = r.get("outcome", "unknown")
        c = r.get("class", "unknown")
        m = r.get("model", "unknown")
        e = r.get("effort", "unknown")
        retries = int(r.get("retries", 0) or 0)
        dynamic = bool(r.get("dynamic_active", False))

        outcomes[o] = outcomes.get(o, 0) + 1
        by_class[c] = by_class.get(c, 0) + 1
        model_key = f"{m}/{e}"
        by_model[model_key] = by_model.get(model_key, 0) + 1

        stats = class_success.setdefault(c, [0, 0])
        stats[1] += 1
        if o == "success":
            stats[0] += 1
        if retries > 0:
            escalations += 1
        if dynamic:
            dynamic_count += 1

    success_rate = {
        c: round(stats[0] / stats[1], 3) if stats[1] else 0.0
        for c, stats in class_success.items()
    }

    return {
        "window_hours": hours,
        "total": len(records),
        "outcomes": outcomes,
        "by_class": by_class,
        "by_model": by_model,
        "escalations": escalations,
        "success_rate_by_class": success_rate,
        "dynamic_active": dynamic_count == len(records) if records else None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# --------------------------------------------------------------------------
# HTTP-handler
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # stille

    def _json(self, code: int, payload: object) -> None:
        body = json.dumps(payload, default=str, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: int, msg: str) -> None:
        self._json(code, {"error": msg})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path == "/health":
            self._json(200, {"status": "ok", "db": DB_PATH,
                             "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
            return

        try:
            conn = open_ro()
        except FileNotFoundError:
            self._error(503, f"DB mangler: {DB_PATH}")
            return
        except sqlite3.OperationalError as e:
            self._error(503, f"DB-feil: {e}")
            return

        try:
            if path == "/api/apps":
                tiers = (query.get("tier", ["primary,secondary,lib,maintenance"])[0]).split(",")
                self._json(200, {"apps": q_apps(conn, tiers)})
                return

            if path == "/api/overview":
                tiers = (query.get("tier", ["primary"])[0]).split(",")
                self._json(200, {"apps": q_overview(conn, tiers),
                                 "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
                return

            if path.startswith("/api/app/"):
                slug = path[len("/api/app/"):]
                data = q_app_truth(conn, slug)
                if data is None:
                    self._error(404, f"ukjent app: {slug}")
                    return
                self._json(200, data)
                return

            if path == "/api/shadow-modes":
                self._json(200, {
                    "shadow_modes": q_shadow_modes(conn),
                    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })
                return

            if path == "/api/triage-24h":
                hours = int(query.get("hours", ["24"])[0])
                self._json(200, q_triage_classifier_window(hours))
                return

            if path.startswith("/api/series/"):
                parts = path[len("/api/series/"):].split("/")
                if len(parts) != 2:
                    self._error(400, "forventet /api/series/<slug>/<metric>")
                    return
                slug, metric = parts
                days = int(query.get("days", ["30"])[0])
                try:
                    self._json(200, q_series(conn, slug, metric, days))
                except ValueError as e:
                    self._error(400, str(e))
                return

            self._error(404, f"ukjent sti: {path}")
        finally:
            conn.close()


def main() -> None:
    if not os.path.exists(DB_PATH):
        print(f"ADVARSEL: DB finnes ikke enda ({DB_PATH}) — API vil returnere 503",
              file=sys.stderr)
    print(f"status-api lytter på :{PORT} (DB: {DB_PATH})", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
