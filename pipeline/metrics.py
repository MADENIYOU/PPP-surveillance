#!/usr/bin/env python3
"""Serveur de métriques + centre de supervision du pipeline Dakar (port 9090).

Trois surfaces :
  - GET /metrics      → format Prometheus (gauges calculées depuis Postgres/Influx)
  - GET /api/overview → JSON riche (workers, flows, événements, AQI zones, débit…)
  - GET /            → dashboard HTML temps réel (consomme /api/overview)

Le worker `metrics` (supervisord) exécute run_collector() : il sert le HTTP et
rafraîchit en boucle. Étant dans le conteneur pipeline-workers, il voit
supervisorctl (état réel des workers) + PostgreSQL + InfluxDB.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

LOGGER = logging.getLogger(__name__)

# ─── État partagé (gauges Prometheus + dernier overview) ─────────────────────
_metrics: dict = {}
_overview: dict = {"generated_at": None}
_lock = threading.Lock()


def set_gauge(name: str, value: float, labels: dict = None):
    with _lock:
        key = name if not labels else f"{name}{json.dumps(labels, sort_keys=True)}"
        _metrics[key] = (name, float(value), labels or {})


def inc_counter(name: str, amount: float = 1, labels: dict = None):
    with _lock:
        key = name if not labels else f"{name}{json.dumps(labels, sort_keys=True)}"
        if key in _metrics:
            _, old_val, old_labels = _metrics[key]
            _metrics[key] = (name, old_val + amount, old_labels)
        else:
            _metrics[key] = (name, float(amount), labels or {})


# ─── Helpers de calcul AQI (bandes PM2.5 — IQA_SPEC §3, simplifié) ───────────
_AQI_BANDS = [
    (12.0, "Bon", "#22c55e"),
    (35.4, "Modéré", "#eab308"),
    (55.4, "Mauvais (sensibles)", "#f97316"),
    (150.4, "Mauvais", "#ef4444"),
    (250.4, "Très mauvais", "#a21caf"),
    (10_000, "Dangereux", "#7f1d1d"),
]


def pm25_band(pm25):
    if pm25 is None:
        return {"label": "—", "color": "#475569"}
    for thr, label, color in _AQI_BANDS:
        if pm25 <= thr:
            return {"label": label, "color": color}
    return {"label": "Dangereux", "color": "#7f1d1d"}


def _health(age_min, warn=10, crit=30):
    """Statut de fraîcheur depuis un âge en minutes."""
    if age_min is None:
        return "unknown"
    if age_min <= warn:
        return "ok"
    if age_min <= crit:
        return "warn"
    return "stale"


# ─── Collecte ────────────────────────────────────────────────────────────────
def _worker_states() -> list[dict]:
    """État réel des workers via supervisorctl."""
    try:
        out = subprocess.run(["supervisorctl", "status"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception as exc:
        LOGGER.warning("supervisorctl_failed error=%s", exc)
        return []
    workers = []
    for line in out.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0].split(":")[-1]
            state = parts[1]
            uptime = " ".join(parts[3:]) if "RUNNING" in state and len(parts) > 3 else ""
            workers.append({"name": name, "state": state, "uptime": uptime,
                            "ok": state == "RUNNING"})
    return workers


def _minutes_since(ts) -> float | None:
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None
    return round((datetime.now(timezone.utc) - ts).total_seconds() / 60, 1)


def build_overview() -> dict:
    """Assemble la vue riche servie au dashboard. Robuste : chaque section isolée."""
    ov: dict = {"generated_at": datetime.now(timezone.utc).isoformat()}

    ov["workers"] = _worker_states()

    # ── PostgreSQL : flows, stats, événements ────────────────────────────────
    try:
        from db.postgres_client import PostgresPool
        pool = PostgresPool()
        with pool.cursor() as cur:
            cur.execute("""
                SELECT (SELECT max(created_at)  FROM feature_store)       AS feat,
                       (SELECT max(created_at)  FROM predictions)         AS pred,
                       (SELECT max(computed_at) FROM kriging_results)     AS krig,
                       (SELECT max(detected_at) FROM anomaly_detections)  AS anom,
                       (SELECT max(training_end) FROM models)             AS train
            """)
            r = cur.fetchone()
            flows = [
                ("feature_engineering", r["feat"], 10, 30),
                ("predictions", r["pred"], 45, 90),
                ("kriging", r["krig"], 90, 180),
                ("anomaly_detector", r["anom"], 5, 15),
                ("retraining", r["train"], 24 * 60, 48 * 60),
            ]
            ov["flows"] = [
                {"name": n, "last_run": ts.isoformat() if ts else None,
                 "age_min": _minutes_since(ts), "health": _health(_minutes_since(ts), w, c)}
                for n, ts, w, c in flows
            ]

            cur.execute("""
                SELECT (SELECT count(*) FROM sensors WHERE status='active') AS sensors_active,
                       (SELECT count(*) FROM sensors)                       AS sensors_total,
                       (SELECT count(*) FROM feature_store)                 AS features,
                       (SELECT count(*) FROM predictions)                   AS predictions,
                       (SELECT count(*) FROM kriging_results)               AS kriging,
                       (SELECT count(*) FROM anomaly_detections)            AS anomalies,
                       (SELECT count(*) FROM alerts)                        AS alerts
            """)
            ov["db_stats"] = dict(cur.fetchone())

            cur.execute("""
                SELECT ad.detected_at, COALESCE(s.serial_number, '?') AS sensor,
                       COALESCE(split_part(z.path::text, '.', -1), '?') AS zone,
                       ad.pollutant::text AS pollutant, ad.detected_value, ad.anomaly_score
                FROM anomaly_detections ad
                LEFT JOIN sensors s ON s.id = ad.sensor_id
                LEFT JOIN zones z   ON z.id = ad.zone_id
                ORDER BY ad.detected_at DESC LIMIT 12
            """)
            ov["recent_anomalies"] = [{
                "time": x["detected_at"].isoformat() if x["detected_at"] else None,
                "sensor": x["sensor"], "zone": x["zone"], "pollutant": x["pollutant"],
                "value": round(x["detected_value"], 1) if x["detected_value"] is not None else None,
                "score": round(x["anomaly_score"], 3) if x["anomaly_score"] is not None else None,
            } for x in cur.fetchall()]

            cur.execute("""
                SELECT a.created_at, a.gravite::text AS gravite, a.type::text AS type,
                       a.pollutant::text AS pollutant, a.message, a.statut_envoi,
                       COALESCE(split_part(z.path::text, '.', -1), '?') AS zone
                FROM alerts a LEFT JOIN zones z ON z.id = a.zone_id
                ORDER BY a.created_at DESC LIMIT 12
            """)
            ov["recent_alerts"] = [{
                "time": x["created_at"].isoformat() if x["created_at"] else None,
                "gravite": x["gravite"], "type": x["type"], "pollutant": x["pollutant"],
                "zone": x["zone"], "message": x["message"], "statut": x["statut_envoi"],
            } for x in cur.fetchall()]

            cur.execute("""
                SELECT name, type::text AS type, version, is_active,
                       training_end, metrics
                FROM models ORDER BY training_end DESC NULLS LAST LIMIT 8
            """)
            ov["models"] = [{
                "name": x["name"], "type": x["type"], "version": x["version"],
                "active": x["is_active"],
                "trained": x["training_end"].isoformat() if x["training_end"] else None,
                "metrics": x["metrics"] or {},
            } for x in cur.fetchall()]

            # Monitoring qualité (Q1-Q6) + historique pour tendance
            cur.execute("SELECT computed_at, metrics FROM data_quality_metrics ORDER BY computed_at DESC LIMIT 48")
            mrows = cur.fetchall()
            ov["monitoring"] = {
                "latest": (mrows[0]["metrics"] if mrows else {}) or {},
                "history": [{"t": r["computed_at"].isoformat(), **((r["metrics"] or {}))}
                            for r in reversed(mrows)],
            }

            # Calibration récente
            cur.execute("""
                SELECT c.created_at, COALESCE(s.serial_number,'?') AS sensor,
                       c.pollutant::text AS pollutant, c.coef_a, c.coef_b, c.r2_score
                FROM calibration c LEFT JOIN sensors s ON s.id = c.sensor_id
                ORDER BY c.created_at DESC LIMIT 15
            """)
            crows = cur.fetchall()
            r2s = [x["r2_score"] for x in crows if x["r2_score"] is not None]
            ov["calibration"] = {
                "recent": [{
                    "time": x["created_at"].isoformat() if x["created_at"] else None,
                    "sensor": x["sensor"], "pollutant": x["pollutant"],
                    "coef_a": round(x["coef_a"], 4) if x["coef_a"] is not None else None,
                    "coef_b": round(x["coef_b"], 4) if x["coef_b"] is not None else None,
                    "r2": round(x["r2_score"], 3) if x["r2_score"] is not None else None,
                } for x in crows],
                "avg_r2": round(sum(r2s) / len(r2s), 3) if r2s else None,
                "count": len(crows),
            }

            # Capteurs (statut + dernière émission) pour la page Données
            cur.execute("""
                SELECT s.serial_number, s.status, s.last_seen,
                       split_part(z.path::text, '.', -1) AS zone
                FROM sensors s JOIN zones z ON z.id = s.zone_id
                ORDER BY s.serial_number
            """)
            sensor_rows = cur.fetchall()

            cur.execute("""
                SELECT split_part(z.path::text, '.', -1) AS zone, z.nom AS name
                FROM zones z WHERE z.niveau = 3 ORDER BY z.nom
            """)
            zone_rows = cur.fetchall()
        pool.closeall()
    except Exception as exc:
        LOGGER.warning("overview_pg_failed error=%s", exc)
        zone_rows = []
        sensor_rows = []

    # ── InfluxDB : débit d'ingestion + AQI par zone ──────────────────────────
    try:
        from db.influxdb_client import (get_influxdb_client, INFLUX_ORG,
                                         INFLUX_BUCKET_RAW, INFLUX_BUCKET_CLEANSED,
                                         RAW_MEASUREMENT, CLEANSED_MEASUREMENT)
        client = get_influxdb_client()
        qapi = client.query_api()

        flux_rate = (f'from(bucket: "{INFLUX_BUCKET_RAW}") |> range(start: -60m) '
                     f'|> filter(fn: (r) => r._measurement == "{RAW_MEASUREMENT}") '
                     f'|> filter(fn: (r) => r._field == "pm25") '
                     f'|> aggregateWindow(every: 1m, fn: count, createEmpty: true) '
                     f'|> group()')
        series = []
        for tbl in qapi.query(flux_rate, org=INFLUX_ORG):
            for rec in tbl.records:
                series.append(int(rec.get_value() or 0))
        ov["ingestion_rate"] = series[-60:]

        flux_zone = (f'from(bucket: "{INFLUX_BUCKET_CLEANSED}") |> range(start: -1h) '
                     f'|> filter(fn: (r) => r._measurement == "{CLEANSED_MEASUREMENT}") '
                     f'|> filter(fn: (r) => r._field == "pm25") '
                     f'|> group(columns: ["zone_id"]) |> mean()')
        zmeans = {}
        for tbl in qapi.query(flux_zone, org=INFLUX_ORG):
            for rec in tbl.records:
                zmeans[rec.values.get("zone_id")] = rec.get_value()
        client.close()

        zones = []
        for zr in zone_rows:
            pm = zmeans.get(zr["zone"])
            band = pm25_band(pm)
            zones.append({"zone": zr["zone"], "name": zr["name"],
                          "pm25": round(pm, 1) if pm is not None else None,
                          "band": band["label"], "color": band["color"]})
        zones.sort(key=lambda z: (z["pm25"] is None, -(z["pm25"] or 0)))
        ov["zones"] = zones

        # Messages du jour par capteur (raw) → page Données / Ingestion
        flux_sensor = (f'from(bucket: "{INFLUX_BUCKET_RAW}") |> range(start: today()) '
                       f'|> filter(fn: (r) => r._measurement == "{RAW_MEASUREMENT}") '
                       f'|> filter(fn: (r) => r._field == "pm25") '
                       f'|> group(columns: ["sensor_id"]) |> count()')
        per_sensor_cnt = {}
        for tbl in qapi.query(flux_sensor, org=INFLUX_ORG):
            for rec in tbl.records:
                per_sensor_cnt[rec.values.get("sensor_id")] = int(rec.get_value() or 0)
        ov["sensors"] = [{
            "id": s["serial_number"], "zone": s["zone"], "status": s["status"],
            "last_seen": s["last_seen"].isoformat() if s["last_seen"] else None,
            "age_min": _minutes_since(s["last_seen"]),
            "messages_today": per_sensor_cnt.get(s["serial_number"], 0),
        } for s in sensor_rows]
    except Exception as exc:
        LOGGER.warning("overview_influx_failed error=%s", exc)
        ov.setdefault("sensors", [{
            "id": s["serial_number"], "zone": s["zone"], "status": s["status"],
            "last_seen": s["last_seen"].isoformat() if s["last_seen"] else None,
            "age_min": _minutes_since(s["last_seen"]), "messages_today": 0,
        } for s in sensor_rows])

    return ov


def collect_pipeline_metrics() -> None:
    """Met à jour les gauges Prometheus + le cache overview."""
    ov = build_overview()
    with _lock:
        _overview.clear()
        _overview.update(ov)

    stats = ov.get("db_stats", {})
    set_gauge("predictions_generated_total", stats.get("predictions", 0))
    set_gauge("feature_store_rows_today", stats.get("features", 0))
    set_gauge("anomalies_detected_total", stats.get("anomalies", 0))
    set_gauge("alerts_generated_total", stats.get("alerts", 0))
    set_gauge("sensors_active", stats.get("sensors_active", 0))
    krig = next((f for f in ov.get("flows", []) if f["name"] == "kriging"), None)
    set_gauge("kriging_coverage_pct", 100 if krig and krig["health"] == "ok" else 0)
    feat = next((f for f in ov.get("flows", []) if f["name"] == "feature_engineering"), None)
    set_gauge("data_freshness_min", feat["age_min"] if feat and feat["age_min"] is not None else 0)
    rate = ov.get("ingestion_rate", [])
    set_gauge("messages_ingested_total", sum(rate))
    set_gauge("workers_running", sum(1 for w in ov.get("workers", []) if w["ok"]))


# ─── HTTP ────────────────────────────────────────────────────────────────────
class MetricsHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence access logs
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/metrics":
            with _lock:
                lines = []
                for name, value, labels in _metrics.values():
                    lbl = ("{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}") if labels else ""
                    lines.append(f"{name}{lbl} {value}")
            self._send(200, "text/plain; charset=utf-8", ("\n".join(lines) + "\n").encode())
        elif self.path == "/api/overview":
            with _lock:
                body = json.dumps(_overview).encode()
            self._send(200, "application/json; charset=utf-8", body)
        elif self.path == "/health":
            self._send(200, "text/plain", b"OK")
        elif self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _DASHBOARD_HTML.encode("utf-8"))
        else:
            self._send(404, "text/plain", b"Not Found")


from dashboard_html import DASHBOARD_HTML as _DASHBOARD_HTML


def start_metrics_server(port: int = 9090):
    try:
        server = HTTPServer(("0.0.0.0", port), MetricsHandler)
    except OSError:
        LOGGER.warning("Metrics server port %d already in use — skipping (another worker handles it)", port)
        return None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_collector(port: int = 9090, interval_s: int = 5) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    start_metrics_server(port)
    LOGGER.info("metrics_collector_started port=%d interval=%ds", port, interval_s)
    while True:
        try:
            collect_pipeline_metrics()
        except Exception as exc:
            LOGGER.warning("collect_failed error=%s", exc)
        time.sleep(interval_s)


if __name__ == "__main__":
    run_collector()
