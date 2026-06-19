"""Router /pipeline — statut et métriques du pipeline pour le dashboard centralisé.

SSE (Server-Sent Events) : GET /pipeline/stream pousse en continu les métriques,
statuts et alertes via un flux `text/event-stream`. Le client ouvre une seule
connexion HTTP persistante — pas de polling, latence < 1s.

Événements émis :
  event: metrics    — toutes les 5s   (compteurs ingestion/calibration/anomalies/...)
  event: status     — toutes les 10s  (workers, flows, infrastructure)
  event: alerts     — toutes les 10s  (dernières alertes actives)
  event: heartbeat  — toutes les 15s  (timestamp UTC, keep-alive)

Utilisation frontend :
  const es = new EventSource('/api/pipeline/stream');
  es.addEventListener('metrics', (e) => setMetrics(JSON.parse(e.data)));
  es.addEventListener('status',  (e) => setStatus(JSON.parse(e.data)));
  es.addEventListener('alerts',  (e) => setAlerts(JSON.parse(e.data)));
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.db import influxdb, postgres
from app.db.redis_client import client as redis_client
from app.security.rate_limit import limiter

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_s(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    return (_now() - dt).total_seconds()


def _check_influx() -> str:
    try:
        influxdb.client().ping()
        return "connected"
    except Exception:
        return "disconnected"


def _check_redis() -> str:
    try:
        r = redis_client()
        if r is None:
            return "disconnected"
        r.ping()
        return "connected"
    except Exception:
        return "disconnected"


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/status
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/status")
@limiter.limit("30/minute")
def pipeline_status(request: Request):
    workers: dict[str, dict[str, Any]] = {}
    flows: dict[str, dict[str, Any]] = {}
    infra: dict[str, dict[str, Any]] = {
        "postgres": {"status": "connected"},
        "influxdb": {"status": _check_influx()},
        "redis": {"status": _check_redis()},
        "mosquitto": {"status": "unknown", "messages_since_start": 0},
    }

    def _safe_query(table: str, query: str, params=None):
        """Exécute une requête, retourne None si la table n'existe pas."""
        try:
            with postgres.cursor() as cur:
                cur.execute(query, params or [])
                return cur.fetchone()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("pipeline_status: table '%s' inaccessible — %s", table, e)
            return None

    # ── Workers ───────────────────────────────────────────────────────────
    row = _safe_query("air_quality", """
        SELECT EXTRACT(EPOCH FROM now() - MIN(timestamp)) AS uptime_s,
               COUNT(*) AS messages_ingested,
               MAX(timestamp) AS last_message_at
        FROM air_quality
    """)
    if row:
        ingestion_uptime = float(row["uptime_s"] or 0)
        workers["ingestion"] = {
            "status": "running" if row["last_message_at"] and (_now() - row["last_message_at"]).total_seconds() < 300 else "idle",
            "uptime_s": round(ingestion_uptime, 0),
            "messages_ingested": row["messages_ingested"],
            "last_message_at": row["last_message_at"].isoformat() if row["last_message_at"] else None,
        }
    else:
        workers["ingestion"] = {"status": "unknown", "uptime_s": 0, "messages_ingested": 0, "last_message_at": None}

    row = _safe_query("calibration", """
        SELECT EXTRACT(EPOCH FROM now() - MIN(valid_from)) AS uptime_s,
               COUNT(*) AS messages_calibrated,
               MAX(created_at) AS last_calibration_at
        FROM calibration
    """)
    if row:
        workers["calibration"] = {
            "status": "running" if row["last_calibration_at"] and (_now() - row["last_calibration_at"]).total_seconds() < 3600 else "idle",
            "uptime_s": round(float(row["uptime_s"] or 0), 0),
            "messages_calibrated": row["messages_calibrated"],
            "last_calibration_at": row["last_calibration_at"].isoformat() if row["last_calibration_at"] else None,
        }
    else:
        workers["calibration"] = {"status": "unknown", "uptime_s": 0, "messages_calibrated": 0, "last_calibration_at": None}

    row = _safe_query("anomaly_detections", """
        SELECT EXTRACT(EPOCH FROM now() - MIN(detected_at)) AS uptime_s,
               COUNT(*) AS anomalies_detected,
               COUNT(*) FILTER (WHERE detected_at > now() - interval '1 hour') AS recent
        FROM anomaly_detections
    """)
    alerts_total = 0
    try:
        with postgres.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM alerts")
            alerts_total = cur.fetchone()["cnt"]
    except Exception:
        pass
    if row:
        workers["anomaly_detector"] = {
            "status": "running" if row["recent"] and row["recent"] > 0 else "idle",
            "uptime_s": round(float(row["uptime_s"] or 0), 0),
            "anomalies_detected": row["anomalies_detected"],
            "alerts_generated": alerts_total,
        }
    else:
        workers["anomaly_detector"] = {"status": "unknown", "uptime_s": 0, "anomalies_detected": 0, "alerts_generated": alerts_total}

    # ── Flows ──────────────────────────────────────────────────────────────
    FLOW_DEFAULTS: dict[str, dict[str, Any]] = {
        "feature_engineering": {"status": "idle", "last_run": None, "zones_processed": 0},
        "predictions": {"status": "idle", "last_run": None, "zones_with_predictions": 0},
        "kriging": {"status": "idle", "last_run": None},
        "nlp_pipeline": {"status": "idle", "last_run": None, "reports_processed": 0},
        "monitoring": {"status": "idle", "last_run": None, "metrics": {}},
        "retraining": {"status": "idle", "last_run": None, "models_updated": []},
    }

    row = _safe_query("feature_store", "SELECT MAX(created_at) AS last_run, COUNT(DISTINCT zone_id) AS zones_processed FROM feature_store")
    if row:
        flows["feature_engineering"] = {
            "status": "healthy" if row["last_run"] and (_now() - row["last_run"]).total_seconds() < 3600 else "stale",
            "last_run": row["last_run"].isoformat() if row["last_run"] else None,
            "zones_processed": row["zones_processed"],
        }

    row = _safe_query("predictions", "SELECT MAX(created_at) AS last_run, COUNT(DISTINCT zone_id) AS zones_with_predictions FROM predictions")
    if row:
        flows["predictions"] = {
            "status": "healthy" if row["last_run"] and (_now() - row["last_run"]).total_seconds() < 3600 else "stale",
            "last_run": row["last_run"].isoformat() if row["last_run"] else None,
            "zones_with_predictions": row["zones_with_predictions"],
        }

    row = _safe_query("kriging_grid", "SELECT MAX(computed_at) AS last_run FROM kriging_grid")
    if row:
        flows["kriging"] = {
            "status": "healthy" if row["last_run"] and (_now() - row["last_run"]).total_seconds() < 7200 else "stale",
            "last_run": row["last_run"].isoformat() if row["last_run"] else None,
        }

    row = _safe_query("report_embeddings", "SELECT MAX(created_at) AS last_run, COUNT(*) AS reports_processed FROM report_embeddings")
    if row:
        flows["nlp_pipeline"] = {
            "status": "healthy" if row["last_run"] and (_now() - row["last_run"]).total_seconds() < 7200 else "stale",
            "last_run": row["last_run"].isoformat() if row["last_run"] else None,
            "reports_processed": row["reports_processed"],
        }

    row = _safe_query("data_quality_metrics", "SELECT computed_at AS last_run, metrics FROM data_quality_metrics ORDER BY computed_at DESC LIMIT 1")
    if row:
        flows["monitoring"] = {
            "status": "healthy" if row["last_run"] and (_now() - row["last_run"]).total_seconds() < 3600 else "stale",
            "last_run": row["last_run"].isoformat() if row["last_run"] else None,
            "metrics": row["metrics"] if row["metrics"] else {},
        }

    row = _safe_query("models", """
        SELECT MAX(training_end) AS last_run,
               ARRAY_AGG(name ORDER BY training_end DESC) FILTER (WHERE training_end > now() - interval '24 hours') AS models_updated
        FROM models
    """)
    if row:
        flows["retraining"] = {
            "status": "healthy" if row["last_run"] and (_now() - row["last_run"]).total_seconds() < 86400 else "idle",
            "last_run": row["last_run"].isoformat() if row["last_run"] else None,
            "models_updated": list(row["models_updated"]) if row["models_updated"] else [],
        }

    for name, defaults in FLOW_DEFAULTS.items():
        flows.setdefault(name, defaults)

    # ── Infrastructure ─────────────────────────────────────────────────────
    try:
        infra["postgres"]["pool_size"] = postgres.pool_info().get("active_connections", 0)
    except Exception:
        infra["postgres"]["pool_size"] = 0

    try:
        with postgres.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM air_quality")
            mosquitto_count = cur.fetchone()["cnt"]
        infra["mosquitto"] = {
            "status": "connected" if mosquitto_count > 0 else "unknown",
            "messages_since_start": mosquitto_count,
        }
    except Exception:
        infra["mosquitto"] = {"status": "unknown", "messages_since_start": 0}

    return {
        "workers": workers,
        "flows": flows,
        "infrastructure": infra,
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/metrics
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/metrics")
@limiter.limit("30/minute")
def pipeline_metrics(request: Request):
    with postgres.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM air_quality")
        messages_ingested_total = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM calibration")
        messages_calibrated_total = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM anomaly_detections")
        anomalies_detected_total = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM alerts")
        alerts_generated_total = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM predictions")
        predictions_generated_total = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT COUNT(DISTINCT zone_id) AS zones_with,
                   (SELECT COUNT(*) FROM zones WHERE niveau = 3) AS total_zones
            FROM kriging_grid
        """)
        row = cur.fetchone()
        kriging_coverage_pct = round(row["zones_with"] * 100.0 / row["total_zones"], 1) if row["total_zones"] > 0 else 0.0

        cur.execute("""
            SELECT EXTRACT(EPOCH FROM now() - MAX(timestamp)) / 60 AS freshness_min
            FROM air_quality
        """)
        row = cur.fetchone()
        data_freshness_min = round(float(row["freshness_min"] or 0), 1)

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM feature_store
            WHERE timestamp >= CURRENT_DATE
        """)
        feature_store_rows_today = cur.fetchone()["cnt"]

    return {
        "messages_ingested_total": messages_ingested_total,
        "messages_calibrated_total": messages_calibrated_total,
        "anomalies_detected_total": anomalies_detected_total,
        "alerts_generated_total": alerts_generated_total,
        "predictions_generated_total": predictions_generated_total,
        "kriging_coverage_pct": kriging_coverage_pct,
        "data_freshness_min": data_freshness_min,
        "feature_store_rows_today": feature_store_rows_today,
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/models
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/models")
@limiter.limit("30/minute")
def pipeline_models(request: Request):
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT name, type, version, training_end, metrics, hyperparams, is_active
            FROM models
            ORDER BY training_end DESC NULLS LAST
            LIMIT 50
        """)
        rows = cur.fetchall()

    models_list = []
    for r in rows:
        model_entry: dict[str, Any] = {
            "name": r["name"],
            "type": str(r["type"]),
            "version": r["version"],
            "last_trained": r["training_end"].isoformat() if r["training_end"] else None,
            "status": "active" if r["is_active"] else "inactive",
        }
        metrics = r["metrics"] or {}
        if isinstance(metrics, dict):
            if "mae" in metrics:
                model_entry["mae"] = metrics["mae"]
            if "rmse" in metrics:
                model_entry["val_rmse"] = metrics["rmse"]
            if "r2" in metrics:
                model_entry["r2"] = metrics["r2"]
        hyperparams = r["hyperparams"] or {}
        if isinstance(hyperparams, dict) and "contamination" in hyperparams:
            model_entry["contamination"] = hyperparams["contamination"]
        models_list.append(model_entry)

    return {
        "models": models_list,
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/dataflow
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/dataflow")
@limiter.limit("30/minute")
def pipeline_dataflow(request: Request):
    with postgres.cursor() as cur:
        # per-minute ingestion rate over last 60 minutes
        cur.execute("""
            SELECT DATE_TRUNC('minute', timestamp) AS minute, COUNT(*) AS cnt
            FROM air_quality
            WHERE timestamp > now() - interval '60 minutes'
            GROUP BY minute
            ORDER BY minute
        """)
        ingestion_rate = [
            {"minute": r["minute"].isoformat(), "count": r["cnt"]}
            for r in cur.fetchall()
        ]

        # per-zone message counts
        cur.execute("""
            SELECT split_part(z.path::text, '.', -1) AS zone_slug, COUNT(*) AS cnt
            FROM air_quality aq
            JOIN zones z ON z.id = aq.zone_id
            GROUP BY z.path
            ORDER BY cnt DESC
        """)
        per_zone = [{"zone_id": r["zone_slug"], "count": r["cnt"]} for r in cur.fetchall()]

        # calibration success rate (r2_score > 0.5 = success)
        cur.execute("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE r2_score > 0.5) AS success,
                   COUNT(*) FILTER (WHERE r2_score <= 0.5) AS low_quality
            FROM calibration
        """)
        row = cur.fetchone()
        calib_total = row["total"]
        calib_success_rate = round(row["success"] * 100.0 / calib_total, 1) if calib_total > 0 else 0.0

        # anomaly distribution by pollutant and severity
        cur.execute("""
            SELECT ad.pollutant::text AS anomaly_type,
                   a.gravite::text AS severity,
                   COUNT(*) AS cnt
            FROM anomaly_detections ad
            LEFT JOIN alerts a ON a.anomaly_id = ad.id
            GROUP BY ad.pollutant, a.gravite
            ORDER BY cnt DESC
        """)
        anomaly_distribution = [
            {"type": r["anomaly_type"], "severity": r["severity"] or "unclassified", "count": r["cnt"]}
            for r in cur.fetchall()
        ]

    return {
        "ingestion_rate_per_minute": ingestion_rate,
        "per_zone_message_counts": per_zone,
        "calibration": {
            "total_coefficients": calib_total,
            "success_rate_pct": calib_success_rate,
        },
        "anomaly_distribution": anomaly_distribution,
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/worker/{name}
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/worker/{name}")
@limiter.limit("30/minute")
def pipeline_worker_detail(request: Request, name: str):
    valid = {"ingestion", "calibration", "anomaly_detector"}
    if name not in valid:
        from fastapi import HTTPException
        raise HTTPException(404, detail={"code": "INVALID_WORKER",
                                         "message": f"Worker inconnu: {name}. Choix: {sorted(valid)}"})

    result: dict[str, Any] = {"worker": name, "generated_at": _now().isoformat()}

    if name == "ingestion":
        with postgres.cursor() as cur:
            # messages per minute (last 60 min)
            cur.execute("""
                SELECT DATE_TRUNC('minute', timestamp) AS minute, COUNT(*) AS cnt
                FROM air_quality
                WHERE timestamp > now() - interval '60 minutes'
                GROUP BY minute ORDER BY minute
            """)
            result["messages_per_min"] = [
                {"minute": r["minute"].isoformat(), "count": r["cnt"]} for r in cur.fetchall()
            ]

            # dead letter queue — gaps in ingestion via data_quality_metrics
            cur.execute("""
                SELECT metrics->>'dead_letter_count' AS dlq_count
                FROM data_quality_metrics
                ORDER BY computed_at DESC LIMIT 1
            """)
            dlq_row = cur.fetchone()
            result["dead_letter_count"] = int(dlq_row["dlq_count"]) if dlq_row and dlq_row["dlq_count"] else 0

            cur.execute("""
                SELECT s.serial_number,
                       s.metadata->>'mqtt_reconnects' AS mqtt_reconnects,
                       s.status,
                       s.last_seen
                FROM sensors s
                ORDER BY (s.metadata->>'mqtt_reconnects')::int DESC NULLS LAST
                LIMIT 20
            """)
            result["mqtt_status"] = [
                {
                    "sensor_id": r["serial_number"],
                    "mqtt_reconnects": int(r["mqtt_reconnects"]) if r["mqtt_reconnects"] else 0,
                    "status": r["status"],
                    "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                }
                for r in cur.fetchall()
            ]
            result["total_mqtt_reconnects"] = sum(s["mqtt_reconnects"] for s in result["mqtt_status"])

            # stale data detection
            cur.execute("""
                SELECT COUNT(*) FILTER (WHERE metadata->>'stale' = 'true') AS stale_cnt,
                       COUNT(*) AS total
                FROM air_quality
                WHERE timestamp > now() - interval '24 hours'
            """)
            stale_row = cur.fetchone()
            total_msgs = stale_row["total"] or 1
            result["stale_pct"] = round((stale_row["stale_cnt"] or 0) * 100.0 / total_msgs, 1)

            # per-sensor message distribution
            cur.execute("""
                SELECT s.serial_number AS sensor_id,
                       split_part(z.path::text, '.', -1) AS zone_id,
                       COUNT(*) AS messages_received,
                       MAX(aq.timestamp) AS last_message,
                       AVG(EXTRACT(EPOCH FROM (aq.timestamp - aq.timestamp)) * 1000) AS avg_latency_ms
                FROM air_quality aq
                JOIN sensors s ON s.id = aq.sensor_id
                JOIN zones z ON z.id = aq.zone_id
                WHERE aq.timestamp > now() - interval '1 hour'
                GROUP BY s.serial_number, z.path
                ORDER BY messages_received DESC
                LIMIT 50
            """)
            result["per_sensor"] = [
                {
                    "sensor_id": r["sensor_id"],
                    "zone_id": r["zone_id"],
                    "messages_received": r["messages_received"],
                    "last_message": r["last_message"].isoformat() if r["last_message"] else None,
                }
                for r in cur.fetchall()
            ]

            # buffer utilization (recent rows in air_quality as proxy)
            cur.execute("SELECT COUNT(*) AS cnt FROM air_quality WHERE timestamp > now() - interval '5 minutes'")
            buf_row = cur.fetchone()
            result["buffer_utilization_pct"] = min(round((buf_row["cnt"] or 0) / 1000.0 * 100, 1), 100)

            # stale entries list (dead letter)
            cur.execute("""
                SELECT s.serial_number AS sensor_id, aq.timestamp,
                       aq.metadata->>'stale_reason' AS reason
                FROM air_quality aq
                JOIN sensors s ON s.id = aq.sensor_id
                WHERE aq.metadata->>'stale' = 'true'
                  AND aq.timestamp > now() - interval '1 hour'
                ORDER BY aq.timestamp DESC
                LIMIT 20
            """)
            result["dead_letter_entries"] = [
                {
                    "sensor_id": r["sensor_id"],
                    "timestamp": r["timestamp"].isoformat(),
                    "reason": r["reason"] or "unknown",
                }
                for r in cur.fetchall()
            ]

    elif name == "calibration":
        with postgres.cursor() as cur:
            # success rate
            cur.execute("""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE r2_score > 0.5) AS success
                FROM calibration
            """)
            cal_row = cur.fetchone()
            cal_total = cal_row["total"] or 1
            result["success_rate_pct"] = round((cal_row["success"] or 0) * 100.0 / cal_total, 1)

            # model info (latest RF model) — la calibration utilise RandomForest
            cur.execute("""
                SELECT name, version, training_end, metrics, hyperparams
                FROM models
                WHERE type = 'RandomForest'
                ORDER BY training_end DESC LIMIT 1
            """)
            model_row = cur.fetchone()
            if model_row:
                result["model_info"] = {
                    "name": model_row["name"],
                    "version": model_row["version"],
                    "last_trained": model_row["training_end"].isoformat() if model_row["training_end"] else None,
                    "features_used": list(model_row["hyperparams"].get("features", [])) if isinstance(model_row.get("hyperparams"), dict) else [],
                    "r2": (model_row["metrics"] or {}).get("r2"),
                    "rmse": (model_row["metrics"] or {}).get("rmse"),
                }

            # kalman filter effectiveness (from data_quality_metrics)
            cur.execute("""
                SELECT metrics->>'kalman_gain_avg' AS kg,
                       metrics->>'uncertainty_reduction_pct' AS ur
                FROM data_quality_metrics
                WHERE metrics ? 'kalman_gain_avg'
                ORDER BY computed_at DESC LIMIT 1
            """)
            kf_row = cur.fetchone()
            result["kalman_effectiveness"] = {
                "avg_kalman_gain": float(kf_row["kg"]) if kf_row and kf_row["kg"] else None,
                "uncertainty_reduction_pct": float(kf_row["ur"]) if kf_row and kf_row["ur"] else None,
            }

            # per-pollutant MAE
            cur.execute("""
                SELECT pollutant,
                       AVG(r2_score) AS avg_r2,
                       COUNT(*) AS calibrations
                FROM calibration
                GROUP BY pollutant
                ORDER BY calibrations DESC
            """)
            result["per_pollutant_mae"] = [
                {
                    "pollutant": r["pollutant"],
                    "avg_r2": round(float(r["avg_r2"]), 3),
                    "calibrations": r["calibrations"],
                }
                for r in cur.fetchall()
            ]

            # fallback count
            cur.execute("""
                SELECT COUNT(*) FILTER (WHERE r2_score < 0.3) AS fallbacks,
                       COUNT(*) AS total
                FROM calibration
            """)
            fb_row = cur.fetchone()
            result["fallback_count"] = fb_row["fallbacks"] or 0
            result["fallback_pct"] = round((fb_row["fallbacks"] or 0) * 100.0 / (fb_row["total"] or 1), 1)

            # active sensors being calibrated
            cur.execute("""
                SELECT s.serial_number AS sensor_id,
                       split_part(z.path::text, '.', -1) AS zone_id,
                       MAX(c.created_at) AS last_calibrated,
                       COUNT(*) AS calibrations_count
                FROM calibration c
                JOIN sensors s ON s.id = c.sensor_id
                JOIN zones z ON z.id = s.zone_id
                WHERE c.created_at > now() - interval '24 hours'
                GROUP BY s.serial_number, z.path
                ORDER BY last_calibrated DESC
                LIMIT 30
            """)
            result["active_sensors"] = [
                {
                    "sensor_id": r["sensor_id"],
                    "zone_id": r["zone_id"],
                    "last_calibrated": r["last_calibrated"].isoformat(),
                    "calibrations_count": r["calibrations_count"],
                }
                for r in cur.fetchall()
            ]

    elif name == "anomaly_detector":
        with postgres.cursor() as cur:
            # detection rate per hour
            cur.execute("""
                SELECT DATE_TRUNC('hour', detected_at) AS hour, COUNT(*) AS cnt
                FROM anomaly_detections
                WHERE detected_at > now() - interval '24 hours'
                GROUP BY hour ORDER BY hour
            """)
            result["detection_rate"] = [
                {"hour": r["hour"].isoformat(), "count": r["cnt"]}
                for r in cur.fetchall()
            ]

            # level distribution
            cur.execute("""
                SELECT COALESCE(a.gravite::text, 'unclassified') AS level, COUNT(*) AS cnt
                FROM anomaly_detections ad
                LEFT JOIN alerts a ON a.anomaly_id = ad.id
                WHERE ad.detected_at > now() - interval '24 hours'
                GROUP BY COALESCE(a.gravite::text, 'unclassified')
                ORDER BY cnt DESC
            """)
            result["level_distribution"] = [
                {"level": r["level"], "count": r["cnt"]}
                for r in cur.fetchall()
            ]

            # Isolation Forest model health
            cur.execute("""
                SELECT AVG(ad.anomaly_score) AS mean_score,
                       COUNT(*) FILTER (WHERE ad.anomaly_score > 0.5) * 1.0 / NULLIF(COUNT(*), 0) AS contamination_rate
                FROM anomaly_detections ad
                WHERE ad.detected_at > now() - interval '24 hours'
                  AND ad.anomaly_score IS NOT NULL
            """)
            if_row = cur.fetchone()
            result["model_health"] = {
                "mean_anomaly_score": round(float(if_row["mean_score"]), 4) if if_row and if_row["mean_score"] else None,
                "contamination_rate": round(float(if_row["contamination_rate"]), 4) if if_row and if_row["contamination_rate"] else None,
            }

            # LISTEN/NOTIFY status from pg_stat_activity
            try:
                cur.execute("""
                    SELECT COUNT(*) AS listeners
                    FROM pg_stat_activity
                    WHERE query LIKE '%LISTEN anomaly_channel%'
                       OR query LIKE '%LISTEN anomaly%'
                       OR state = 'idle' AND wait_event_type = 'Client'
                """)
                listen_row = cur.fetchone()
                result["listen_status"] = {
                    "active_listeners": listen_row["listeners"] if listen_row else 0,
                    "channel": "anomaly_channel",
                }
            except Exception:
                result["listen_status"] = {"active_listeners": 0, "channel": "anomaly_channel"}

            # per-zone anomaly heat map
            cur.execute("""
                SELECT split_part(z.path::text, '.', -1) AS zone_id,
                       COUNT(*) AS anomaly_count,
                       AVG(ad.anomaly_score) AS avg_score,
                       MAX(ad.anomaly_score) AS max_score
                FROM anomaly_detections ad
                JOIN zones z ON z.id = ad.zone_id
                WHERE ad.detected_at > now() - interval '24 hours'
                GROUP BY z.path
                ORDER BY anomaly_count DESC
                LIMIT 30
            """)
            result["per_zone_heatmap"] = [
                {
                    "zone_id": r["zone_id"],
                    "anomaly_count": r["anomaly_count"],
                    "avg_score": round(float(r["avg_score"]), 4) if r["avg_score"] else None,
                    "max_score": round(float(r["max_score"]), 4) if r["max_score"] else None,
                }
                for r in cur.fetchall()
            ]

            # recent structural rule violations
            cur.execute("""
                SELECT ad.id, ad.pollutant, ad.detected_value, ad.detected_at,
                       split_part(z.path::text, '.', -1) AS zone_id,
                       s.serial_number AS sensor_id,
                       a.gravite AS severity
                FROM anomaly_detections ad
                JOIN zones z ON z.id = ad.zone_id
                LEFT JOIN sensors s ON s.id = ad.sensor_id
                LEFT JOIN alerts a ON a.anomaly_id = ad.id
                WHERE ad.detected_at > now() - interval '24 hours'
                  AND (ad.detected_value = 0 OR ad.duration_minutes > 120)
                ORDER BY ad.detected_at DESC
                LIMIT 20
            """)
            result["structural_violations"] = [
                {
                    "id": r["id"],
                    "zone_id": r["zone_id"],
                    "pollutant": str(r["pollutant"]),
                    "detected_value": float(r["detected_value"]),
                    "detected_at": r["detected_at"].isoformat(),
                    "sensor_id": r["sensor_id"],
                    "severity": str(r["severity"]) if r["severity"] else "warning",
                    "type": "stuck_sensor" if float(r["detected_value"]) == 0 else "implausible_ratio",
                }
                for r in cur.fetchall()
            ]

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/flow/{name}
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/flow/{name}")
@limiter.limit("30/minute")
def pipeline_flow_detail(request: Request, name: str):
    valid = {"feature_engineering", "predictions", "kriging", "nlp_pipeline", "monitoring", "retraining"}
    if name not in valid:
        from fastapi import HTTPException
        raise HTTPException(404, detail={"code": "INVALID_FLOW",
                                         "message": f"Flow inconnu: {name}. Choix: {sorted(valid)}"})

    result: dict[str, Any] = {"flow": name, "generated_at": _now().isoformat()}

    if name == "feature_engineering":
        with postgres.cursor() as cur:
            cur.execute("SELECT MAX(created_at) AS last_run, COUNT(*) AS total_rows FROM feature_store")
            row = cur.fetchone()
            result["last_run"] = row["last_run"].isoformat() if row["last_run"] else None
            result["total_feature_rows"] = row["total_rows"] or 0

            # feature coverage (how many of 57 features have non-null values)
            cur.execute("""
                SELECT COUNT(DISTINCT zone_id) AS zones_with_features
                FROM feature_store
                WHERE timestamp > now() - interval '24 hours'
            """)
            cov_row = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS total_zones FROM zones WHERE niveau = 3")
            total_zones = cur.fetchone()["total_zones"] or 1
            result["feature_coverage_pct"] = round((cov_row["zones_with_features"] or 0) * 100.0 / total_zones, 1)

            # per-zone feature completeness
            cur.execute("""
                SELECT split_part(z.path::text, '.', -1) AS zone_id,
                       COUNT(*) AS feature_count,
                       COUNT(*) FILTER (WHERE fs.features IS NOT NULL) AS non_null_features
                FROM feature_store fs
                JOIN zones z ON z.id = fs.zone_id
                WHERE fs.timestamp > now() - interval '24 hours'
                GROUP BY z.path
                ORDER BY feature_count DESC
                LIMIT 30
            """)
            result["per_zone_completeness"] = [
                {
                    "zone_id": r["zone_id"],
                    "feature_count": r["feature_count"],
                    "non_null_features": r["non_null_features"],
                    "completeness_pct": round((r["non_null_features"] or 0) * 100.0 / max(r["feature_count"], 1), 1),
                }
                for r in cur.fetchall()
            ]

            # latest feature vector preview
            cur.execute("""
                SELECT split_part(z.path::text, '.', -1) AS zone_id,
                       fs.timestamp,
                       fs.features
                FROM feature_store fs
                JOIN zones z ON z.id = fs.zone_id
                ORDER BY fs.created_at DESC
                LIMIT 20
            """)
            result["latest_features"] = [
                {
                    "zone_id": r["zone_id"],
                    "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                    "features": r["features"] if r["features"] else {},
                }
                for r in cur.fetchall()
            ]

            # feature importance if available from models
            cur.execute("""
                SELECT metrics->>'feature_importance' AS fi
                FROM models
                WHERE name = 'feature_engineering'
                ORDER BY training_end DESC LIMIT 1
            """)
            fi_row = cur.fetchone()
            result["feature_importance"] = fi_row["fi"] if fi_row and fi_row["fi"] else None

    elif name == "predictions":
        with postgres.cursor() as cur:
            cur.execute("SELECT MAX(created_at) AS last_run, COUNT(*) AS total FROM predictions")
            row = cur.fetchone()
            result["last_run"] = row["last_run"].isoformat() if row["last_run"] else None
            result["total_predictions"] = row["total"] or 0

            # prediction accuracy RMSE per horizon
            # (air_quality table stores raw PG copy — absent when ingestion writes only to InfluxDB)
            cur.execute("""
                SELECT p.horizon_minutes AS horizon,
                       NULL::float AS rmse,
                       COUNT(*) AS predictions
                FROM predictions p
                WHERE p.created_at > now() - interval '7 days'
                GROUP BY p.horizon_minutes
                ORDER BY p.horizon_minutes
            """)
            result["horizon_metrics"] = [
                {
                    "horizon": r["horizon"],
                    "rmse": round(float(r["rmse"]), 3) if r["rmse"] else None,
                    "predictions": r["predictions"],
                }
                for r in cur.fetchall()
            ]

            # per-zone prediction summary
            cur.execute("""
                SELECT split_part(z.path::text, '.', -1) AS zone_id,
                       COUNT(*) AS prediction_count,
                       MAX(p.created_at) AS last_prediction,
                       AVG(p.predicted_value) AS avg_predicted
                FROM predictions p
                JOIN zones z ON z.id = p.zone_id
                WHERE p.created_at > now() - interval '24 hours'
                GROUP BY z.path
                ORDER BY prediction_count DESC
                LIMIT 30
            """)
            result["per_zone_summary"] = [
                {
                    "zone_id": r["zone_id"],
                    "prediction_count": r["prediction_count"],
                    "last_prediction": r["last_prediction"].isoformat() if r["last_prediction"] else None,
                    "avg_predicted": round(float(r["avg_predicted"]), 2) if r["avg_predicted"] else None,
                }
                for r in cur.fetchall()
            ]

            # model version in use
            cur.execute("""
                SELECT name, version, training_end, metrics
                FROM models
                WHERE type IN ('LSTM', 'GRU', 'Prophet', 'GCN') AND is_active = true
                ORDER BY training_end DESC LIMIT 1
            """)
            model_row = cur.fetchone()
            if model_row:
                result["active_model"] = {
                    "name": model_row["name"],
                    "version": model_row["version"],
                    "last_trained": model_row["training_end"].isoformat() if model_row["training_end"] else None,
                    "metrics": model_row["metrics"] if model_row["metrics"] else {},
                }

            # predicted vs actual — requires air_quality PG table (absent when ingestion
            # writes only to InfluxDB); return empty list to avoid 500
            result["predicted_vs_actual"] = []

    elif name == "kriging":
        with postgres.cursor() as cur:
            cur.execute("SELECT MAX(computed_at) AS last_run FROM kriging_grid")
            row = cur.fetchone()
            result["last_run"] = row["last_run"].isoformat() if row["last_run"] else None

            # coverage map
            cur.execute("""
                SELECT COUNT(DISTINCT zone_id) AS zones_with,
                       (SELECT COUNT(*) FROM zones WHERE niveau = 3) AS total_zones
                FROM kriging_grid
            """)
            cov_row = cur.fetchone()
            result["zones_with_kriging"] = cov_row["zones_with"] or 0
            result["total_zones"] = cov_row["total_zones"] or 0
            result["coverage_pct"] = round((cov_row["zones_with"] or 0) * 100.0 / (cov_row["total_zones"] or 1), 1)

            # grid resolution and total points
            cur.execute("SELECT COUNT(*) AS grid_points FROM kriging_grid")
            grid_row = cur.fetchone()
            result["total_grid_points"] = grid_row["grid_points"] or 0

            cur.execute("""
                SELECT MIN(ST_Y(point_geom)) AS lat_min, MAX(ST_Y(point_geom)) AS lat_max,
                       MIN(ST_X(point_geom)) AS lon_min, MAX(ST_X(point_geom)) AS lon_max
                FROM kriging_grid
            """)
            bbox = cur.fetchone()
            result["grid_bbox"] = {
                "lat": [bbox["lat_min"], bbox["lat_max"]],
                "lon": [bbox["lon_min"], bbox["lon_max"]],
            }

            # RMSE from data_quality_metrics or models
            cur.execute("""
                SELECT metrics->>'kriging_rmse_loo' AS rmse
                FROM data_quality_metrics
                WHERE metrics ? 'kriging_rmse_loo'
                ORDER BY computed_at DESC LIMIT 1
            """)
            rmse_row = cur.fetchone()
            result["rmse_loo"] = float(rmse_row["rmse"]) if rmse_row and rmse_row["rmse"] else None

            # per-zone interpolation quality
            cur.execute("""
                SELECT split_part(z.path::text, '.', -1) AS zone_id,
                       COUNT(*) AS grid_cells,
                       AVG(kg.pm25_estime) AS avg_value,
                       STDDEV(kg.pm25_estime) AS stddev_value
                FROM kriging_grid kg
                JOIN zones z ON z.id = kg.zone_id
                GROUP BY z.path
                ORDER BY grid_cells DESC
                LIMIT 30
            """)
            result["per_zone_quality"] = [
                {
                    "zone_id": r["zone_id"],
                    "grid_cells": r["grid_cells"],
                    "avg_value": round(float(r["avg_value"]), 2) if r["avg_value"] else None,
                    "stddev": round(float(r["stddev_value"]), 2) if r["stddev_value"] else None,
                }
                for r in cur.fetchall()
            ]

    elif name == "nlp_pipeline":
        with postgres.cursor() as cur:
            cur.execute("SELECT MAX(created_at) AS last_run, COUNT(*) AS total FROM report_embeddings")
            row = cur.fetchone()
            result["last_run"] = row["last_run"].isoformat() if row["last_run"] else None
            result["reports_processed"] = row["total"] or 0

            # entity extraction summary
            cur.execute("""
                SELECT e.entity_type, e.entity_value, COUNT(*) AS cnt
                FROM report_entities e
                WHERE e.created_at > now() - interval '7 days'
                GROUP BY e.entity_type, e.entity_value
                ORDER BY cnt DESC
                LIMIT 30
            """)
            result["top_entities"] = [
                {
                    "type": r["entity_type"] or "unknown",
                    "value": r["entity_value"],
                    "count": r["cnt"],
                }
                for r in cur.fetchall()
            ]

            # urgency classification distribution
            cur.execute("""
                SELECT COALESCE(r.metadata->>'urgency_level', 'non_classe') AS urgency,
                       COUNT(*) AS cnt
                FROM reports r
                WHERE r.created_at > now() - interval '7 days'
                GROUP BY r.metadata->>'urgency_level'
                ORDER BY cnt DESC
            """)
            result["urgency_distribution"] = [
                {"urgency": r["urgency"], "count": r["cnt"]}
                for r in cur.fetchall()
            ]

            # spatio-temporal correlation success rate
            cur.execute("""
                SELECT COUNT(*) AS total_reports,
                       COUNT(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM anomaly_labels al WHERE al.report_id = r.id
                       )) AS correlated
                FROM reports r
                WHERE r.created_at > now() - interval '7 days'
            """)
            corr_row = cur.fetchone()
            total_reports_val = corr_row["total_reports"] or 1
            result["correlation_success_rate_pct"] = round(
                (corr_row["correlated"] or 0) * 100.0 / total_reports_val, 1
            )

            # embedding quality metrics (dummy — real metric would come from embedding model)
            cur.execute("""
                SELECT COUNT(*) AS embedding_count
                FROM report_embeddings
                WHERE created_at > now() - interval '7 days'
            """)
            emb_row = cur.fetchone()
            result["embedding_metrics"] = {
                "total_embeddings": emb_row["embedding_count"] or 0,
            }

    elif name == "monitoring":
        with postgres.cursor() as cur:
            cur.execute("SELECT MAX(computed_at) AS last_run FROM data_quality_metrics")
            row = cur.fetchone()
            result["last_run"] = row["last_run"].isoformat() if row["last_run"] else None

            # Q1-Q6 metrics with historical trends
            cur.execute("""
                SELECT computed_at, metrics
                FROM data_quality_metrics
                ORDER BY computed_at DESC
                LIMIT 50
            """)
            metrics_rows = cur.fetchall()
            result["metrics_timeseries"] = [
                {
                    "computed_at": r["computed_at"].isoformat(),
                    "metrics": r["metrics"] if r["metrics"] else {},
                }
                for r in metrics_rows
            ]

            # pipeline latency p95
            cur.execute("""
                SELECT computed_at,
                       (metrics->>'p95_latency_ms')::float AS p95_latency
                FROM data_quality_metrics
                WHERE metrics ? 'p95_latency_ms'
                ORDER BY computed_at DESC
                LIMIT 20
            """)
            latency_rows = cur.fetchall()
            result["latency_p95"] = [
                {"computed_at": r["computed_at"].isoformat(), "p95_latency_ms": r["p95_latency"] or 0}
                for r in latency_rows
            ]

            # coverage metrics over time
            cur.execute("""
                SELECT computed_at,
                       (metrics->>'coverage_pct')::float AS coverage_pct
                FROM data_quality_metrics
                WHERE metrics ? 'coverage_pct'
                ORDER BY computed_at DESC
                LIMIT 20
            """)
            cov_rows = cur.fetchall()
            result["coverage_over_time"] = [
                {"computed_at": r["computed_at"].isoformat(), "coverage_pct": r["coverage_pct"] or 0}
                for r in cov_rows
            ]

    elif name == "retraining":
        with postgres.cursor() as cur:
            # model version history with performance comparison
            cur.execute("""
                SELECT name, type, version, training_end, metrics, is_active
                FROM models
                ORDER BY training_end DESC
                LIMIT 30
            """)
            result["model_versions"] = [
                {
                    "name": r["name"],
                    "type": str(r["type"]),
                    "version": r["version"],
                    "training_end": r["training_end"].isoformat() if r["training_end"] else None,
                    "metrics": r["metrics"] if r["metrics"] else {},
                    "is_active": r["is_active"],
                }
                for r in cur.fetchall()
            ]

            # last retraining details
            cur.execute("""
                SELECT name, type, version, training_end, metrics, hyperparams
                FROM models
                WHERE training_end IS NOT NULL
                ORDER BY training_end DESC
                LIMIT 5
            """)
            last_models = cur.fetchall()
            result["last_retraining"] = [
                {
                    "name": r["name"],
                    "type": str(r["type"]),
                    "version": r["version"],
                    "training_end": r["training_end"].isoformat() if r["training_end"] else None,
                    "mae": (r["metrics"] or {}).get("mae"),
                    "rmse": (r["metrics"] or {}).get("rmse"),
                    "r2": (r["metrics"] or {}).get("r2"),
                    "data_points": (r["hyperparams"] or {}).get("n_samples") if isinstance(r.get("hyperparams"), dict) else None,
                }
                for r in last_models
            ]

            # next scheduled retraining (default 24h cycle)
            cur.execute("SELECT MAX(training_end) AS latest FROM models")
            latest_row = cur.fetchone()
            if latest_row and latest_row["latest"]:
                from datetime import timedelta
                next_scheduled = latest_row["latest"] + timedelta(hours=24)
                result["next_retraining_at"] = next_scheduled.isoformat()
            else:
                result["next_retraining_at"] = None

            # archived versions list
            cur.execute("""
                SELECT name, type, version, training_end, metrics
                FROM models
                WHERE NOT is_active
                ORDER BY training_end DESC
                LIMIT 20
            """)
            result["archived_versions"] = [
                {
                    "name": r["name"],
                    "type": str(r["type"]),
                    "version": r["version"],
                    "training_end": r["training_end"].isoformat() if r["training_end"] else None,
                    "metrics": r["metrics"] if r["metrics"] else {},
                }
                for r in cur.fetchall()
            ]

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/recent-anomalies
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/recent-anomalies")
@limiter.limit("30/minute")
def pipeline_recent_anomalies(request: Request,
                              limit: int = 50,
                              zone_id: Optional[str] = None):
    clauses, params = [], []
    if zone_id:
        clauses.append("z.path ~ %s")
        params.append(f"*.{zone_id}")
    clauses.append("ad.detected_at > now() - interval '24 hours'")
    where = " AND ".join(clauses)

    with postgres.cursor() as cur:
        cur.execute(f"""
            SELECT ad.id, ad.pollutant, ad.detected_value, ad.threshold,
                   ad.anomaly_score, ad.detected_at, ad.duration_minutes,
                   split_part(z.path::text, '.', -1) AS zone_id,
                   s.serial_number AS sensor_id,
                   a.gravite AS severity,
                   a.type AS alert_type
            FROM anomaly_detections ad
            JOIN zones z ON z.id = ad.zone_id
            LEFT JOIN sensors s ON s.id = ad.sensor_id
            LEFT JOIN alerts a ON a.anomaly_id = ad.id
            WHERE {where}
            ORDER BY ad.detected_at DESC
            LIMIT %s
        """, params + [limit])
        rows = cur.fetchall()

    anomalies = [{
        "id": r["id"],
        "zone_id": r["zone_id"],
        "type": str(r["alert_type"]) if r["alert_type"] else "threshold_exceeded",
        "pollutant": str(r["pollutant"]),
        "severity": str(r["severity"]) if r["severity"] else "warning",
        "value": float(r["detected_value"]),
        "threshold": float(r["threshold"]),
        "anomaly_score": float(r["anomaly_score"]) if r["anomaly_score"] else None,
        "duration_minutes": r["duration_minutes"],
        "detected_at": r["detected_at"].isoformat(),
        "sensor_id": r["sensor_id"],
    } for r in rows]

    return {
        "anomalies": anomalies,
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Helper : fallback log synthesis when pipeline_events table is unavailable
# ═══════════════════════════════════════════════════════════════════════════════

def _synthesize_logs(service: Optional[str], level: Optional[str],
                     search: Optional[str], limit: int, offset: int) -> tuple[list[dict], int]:
    """Build event feed from operational tables when pipeline_events is absent."""
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT 'anomaly_detector' AS service, 'WARN' AS level,
                   format('Anomaly: %s = %s in zone %s', ad.pollutant::text,
                          ad.detected_value::text,
                          split_part(z.path::text, '.', -1)) AS message,
                   jsonb_build_object('anomaly_id', ad.id, 'anomaly_score',
                          ad.anomaly_score) AS metadata,
                   ad.detected_at AS created_at
            FROM anomaly_detections ad
            JOIN zones z ON z.id = ad.zone_id
            WHERE ad.detected_at > now() - interval '24 hours'
            UNION ALL
            SELECT 'alerts' AS service, 'INFO' AS level,
                   format('Alert: %s [%s] — %s', a.gravite::text, a.type::text, a.message) AS message,
                   jsonb_build_object('alert_id', a.id, 'zone_id',
                          split_part(z.path::text, '.', -1)) AS metadata,
                   a.created_at AS created_at
            FROM alerts a
            JOIN zones z ON z.id = a.zone_id
            WHERE a.created_at > now() - interval '24 hours'
            UNION ALL
            SELECT 'monitoring' AS service, 'INFO' AS level,
                   format('Quality check: %s', dqm.metrics::text) AS message,
                   dqm.metrics AS metadata,
                   dqm.computed_at AS created_at
            FROM data_quality_metrics dqm
            WHERE dqm.computed_at > now() - interval '24 hours'
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, [limit, offset])
        rows = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM (
                SELECT 1 FROM anomaly_detections WHERE detected_at > now() - interval '24 hours'
                UNION ALL
                SELECT 1 FROM alerts WHERE created_at > now() - interval '24 hours'
                UNION ALL
                SELECT 1 FROM data_quality_metrics WHERE computed_at > now() - interval '24 hours'
            ) _
        """)
        total = cur.fetchone()["cnt"]

    logs = [{
        "id": str(i + offset),
        "timestamp": r["created_at"].isoformat(),
        "service": str(r["service"]),
        "level": str(r["level"]),
        "message": str(r["message"]),
        "metadata": r["metadata"] if r["metadata"] else None,
    } for i, r in enumerate(rows)]
    return logs, total


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/logs
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/logs")
@limiter.limit("30/minute")
def pipeline_logs(request: Request,
                  service: Optional[str] = None,
                  level: Optional[str] = None,
                  search: Optional[str] = None,
                  limit: int = 200,
                  offset: int = 0):
    clauses: list[str] = []
    params: list[Any] = []

    if service:
        clauses.append("service = %s")
        params.append(service)
    if level:
        clauses.append("level = %s")
        params.append(level.upper())
    if search:
        clauses.append("message ILIKE %s")
        params.append(f"%{search}%")

    where = " AND ".join(clauses) if clauses else "TRUE"

    # Try pipeline_events table first, fall back to synthesized logs from
    # anomaly_detections + alerts + data_quality_metrics UNION ALL
    try:
        with postgres.cursor() as cur:
            cur.execute(f"""
                SELECT id, created_at, service, level, message, metadata
                FROM pipeline_events
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            rows = cur.fetchall()

            cur.execute(f"""
                SELECT COUNT(*) AS total FROM pipeline_events WHERE {where}
            """, params)
            total = cur.fetchone()["total"]

        logs = [{
            "id": str(r["id"]),
            "timestamp": r["created_at"].isoformat(),
            "service": str(r["service"]),
            "level": str(r["level"]),
            "message": str(r["message"]),
            "metadata": r["metadata"] if r["metadata"] else None,
        } for r in rows]
    except Exception:
        # Fallback: synthesize logs from operational tables
        logs, total = _synthesize_logs(service, level, search, limit, offset)

    return {
        "logs": logs,
        "meta": {
            "total": total,
            "offset": offset,
            "limit": limit,
            "generated_at": _now().isoformat(),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/calibration/history
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/calibration/history")
@limiter.limit("30/minute")
def calibration_history(request: Request,
                        sensor_id: Optional[str] = None,
                        zone_id: Optional[str] = None,
                        limit: int = 100):
    clauses: list[str] = []
    params: list[Any] = []

    if sensor_id:
        clauses.append("s.serial_number = %s")
        params.append(sensor_id)
    if zone_id:
        clauses.append("split_part(z.path::text, '.', -1) = %s")
        params.append(zone_id)

    where = " AND ".join(clauses) if clauses else "TRUE"

    with postgres.cursor() as cur:
        cur.execute(f"""
            SELECT c.id,
                   s.serial_number AS sensor_id,
                   split_part(z.path::text, '.', -1) AS zone_id,
                   c.valid_from AS calibrated_at,
                   c.coef_a, c.coef_b, c.pollutant,
                   c.r2_score
            FROM calibration c
            JOIN sensors s ON s.id = c.sensor_id
            JOIN zones z ON z.id = s.zone_id
            WHERE {where}
            ORDER BY c.valid_from DESC
            LIMIT %s
        """, params + [limit])
        rows = cur.fetchall()

        cur.execute(f"""
            SELECT COUNT(*) AS total FROM calibration c
            JOIN sensors s ON s.id = c.sensor_id
            JOIN zones z ON z.id = s.zone_id
            WHERE {where}
        """, params)
        total = cur.fetchone()["total"]

    records = [{
        "id": r["id"],
        "sensor_id": str(r["sensor_id"]),
        "zone_id": str(r["zone_id"]),
        "calibrated_at": r["calibrated_at"].isoformat() if hasattr(r["calibrated_at"], "isoformat") else str(r["calibrated_at"]),
        "old_coefficients": None,
        "new_coefficients": {"coef_a": float(r["coef_a"]), "coef_b": float(r["coef_b"])} if r["coef_a"] is not None else {},
        "pollutant": str(r["pollutant"]) if r["pollutant"] else None,
        "r2_score": float(r["r2_score"]) if r["r2_score"] else 0.0,
    } for r in rows]

    return {
        "records": records,
        "meta": {"total": total, "generated_at": _now().isoformat()},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/calibration/drift
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/calibration/drift")
@limiter.limit("30/minute")
def calibration_drift(request: Request, hours: int = 168):
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT s.serial_number AS sensor_id,
                   split_part(z.path::text, '.', -1) AS zone_id,
                   c.valid_from AS timestamp,
                   c.r2_score,
                   c.coef_a, c.coef_b
            FROM calibration c
            JOIN sensors s ON s.id = c.sensor_id
            JOIN zones z ON z.id = s.zone_id
            WHERE c.valid_from > now() - (%s || ' hours')::interval
            ORDER BY s.serial_number, c.valid_from
        """, [str(hours)])
        rows = cur.fetchall()

    drifts: list[dict[str, Any]] = []
    sensor_prev: dict[str, float] = {}
    for r in rows:
        coef_a = float(r["coef_a"]) if r["coef_a"] is not None else 0.0
        coef_b = float(r["coef_b"]) if r["coef_b"] is not None else 0.0
        mean_coeff = (coef_a + coef_b) / 2.0
        sid = str(r["sensor_id"])
        drift_pct = 0.0
        if sid in sensor_prev and sensor_prev[sid] != 0:
            drift_pct = abs(mean_coeff - sensor_prev[sid]) / abs(sensor_prev[sid]) * 100.0
        sensor_prev[sid] = mean_coeff
        drifts.append({
            "sensor_id": sid,
            "zone_id": str(r["zone_id"]),
            "timestamp": r["timestamp"].isoformat() if hasattr(r["timestamp"], "isoformat") else str(r["timestamp"]),
            "drift_pct": round(drift_pct, 3),
        })

    return {
        "drifts": drifts,
        "meta": {"generated_at": _now().isoformat()},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/anomalies/search
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/anomalies/search")
@limiter.limit("30/minute")
def pipeline_anomalies_search(request: Request,
                              zone_id: Optional[str] = Query(None),
                              severity: Optional[str] = Query(None, pattern="^(info|warning|danger|critical)$"),
                              type: Optional[str] = Query(None),
                              pollutant: Optional[str] = Query(None),
                              date_from: Optional[str] = Query(None),
                              date_to: Optional[str] = Query(None),
                              page: int = Query(1, ge=1),
                              page_size: int = Query(20, ge=1, le=100)):
    clauses: list[str] = []
    params: list[Any] = []

    if zone_id:
        clauses.append("split_part(z.path::text, '.', -1) = %s")
        params.append(zone_id)
    if severity:
        clauses.append("a.gravite = %s::alert_gravite")
        params.append(severity)
    if type:
        clauses.append("a.type = %s::alert_type")
        params.append(type)
    if pollutant:
        clauses.append("ad.pollutant = %s::pollutant_type")
        params.append(pollutant)
    if date_from:
        clauses.append("ad.detected_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        clauses.append("ad.detected_at <= %s::timestamptz")
        params.append(date_to)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    offset = (page - 1) * page_size

    with postgres.cursor() as cur:
        cur.execute(f"""
            SELECT ad.id, ad.pollutant, ad.detected_value, ad.threshold,
                   ad.anomaly_score, ad.detected_at, ad.duration_minutes,
                   ad.handled,
                   split_part(z.path::text, '.', -1) AS zone_id,
                   z.nom AS zone_name,
                   s.serial_number AS sensor_id,
                   a.gravite AS severity,
                   a.type AS alert_type,
                   a.message AS alert_message,
                   a.id AS alert_id
            FROM anomaly_detections ad
            JOIN zones z ON z.id = ad.zone_id
            LEFT JOIN sensors s ON s.id = ad.sensor_id
            LEFT JOIN alerts a ON a.anomaly_id = ad.id
            {where}
            ORDER BY ad.detected_at DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])
        rows = cur.fetchall()

        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM anomaly_detections ad
            JOIN zones z ON z.id = ad.zone_id
            LEFT JOIN alerts a ON a.anomaly_id = ad.id
            {where}
        """, params)
        total_count = cur.fetchone()["total"]

    results = [{
        "id": r["id"],
        "zone_id": r["zone_id"],
        "zone_name": r["zone_name"],
        "pollutant": str(r["pollutant"]),
        "detected_value": float(r["detected_value"]),
        "threshold": float(r["threshold"]),
        "anomaly_score": float(r["anomaly_score"]) if r["anomaly_score"] else None,
        "severity": str(r["severity"]) if r["severity"] else "warning",
        "type": str(r["alert_type"]) if r["alert_type"] else "threshold_exceeded",
        "duration_minutes": r["duration_minutes"],
        "detected_at": r["detected_at"].isoformat(),
        "sensor_id": r["sensor_id"],
        "handled": r["handled"],
        "alert_id": r["alert_id"],
        "alert_message": r["alert_message"],
    } for r in rows]

    return {
        "anomalies": results,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": max((total_count + page_size - 1) // page_size, 1),
        },
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/alerts
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/alerts")
@limiter.limit("30/minute")
def pipeline_alerts_list(request: Request,
                         zone_id: Optional[str] = Query(None),
                         gravite: Optional[str] = Query(None, pattern="^(info|warning|danger|critical)$"),
                         type: Optional[str] = Query(None),
                         active_only: bool = Query(False),
                         date_from: Optional[str] = Query(None),
                         date_to: Optional[str] = Query(None),
                         page: int = Query(1, ge=1),
                         page_size: int = Query(20, ge=1, le=100)):
    clauses: list[str] = []
    params: list[Any] = []

    if zone_id:
        clauses.append("split_part(z.path::text, '.', -1) = %s")
        params.append(zone_id)
    if gravite:
        clauses.append("a.gravite = %s::alert_gravite")
        params.append(gravite)
    if type:
        clauses.append("a.type = %s::alert_type")
        params.append(type)
    if active_only:
        clauses.append("a.statut_envoi IN ('pending', 'sent')")
        clauses.append("a.resolved_at IS NULL")
    if date_from:
        clauses.append("a.created_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        clauses.append("a.created_at <= %s::timestamptz")
        params.append(date_to)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    offset = (page - 1) * page_size

    with postgres.cursor() as cur:
        cur.execute(f"""
            SELECT a.id, a.type, a.gravite, a.pollutant, a.message,
                   a.canal_envoi, a.statut_envoi, a.sent_at, a.created_at,
                   a.resolved_at, a.acknowledged_at,
                   split_part(z.path::text, '.', -1) AS zone_id,
                   z.nom AS zone_name,
                   s.serial_number AS sensor_id,
                   ad.id AS anomaly_id,
                   ad.detected_value, ad.anomaly_score
            FROM alerts a
            JOIN zones z ON z.id = a.zone_id
            LEFT JOIN anomaly_detections ad ON ad.id = a.anomaly_id
            LEFT JOIN sensors s ON s.id = ad.sensor_id
            {where}
            ORDER BY a.created_at DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])
        rows = cur.fetchall()

        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM alerts a
            JOIN zones z ON z.id = a.zone_id
            LEFT JOIN anomaly_detections ad ON ad.id = a.anomaly_id
            {where}
        """, params)
        total_count = cur.fetchone()["total"]

    results = [{
        "id": r["id"],
        "zone_id": r["zone_id"],
        "zone_name": r["zone_name"],
        "type": str(r["type"]),
        "gravite": str(r["gravite"]),
        "pollutant": str(r["pollutant"]) if r["pollutant"] else None,
        "message": r["message"],
        "canal_envoi": r["canal_envoi"],
        "statut_envoi": r["statut_envoi"],
        "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
        "created_at": r["created_at"].isoformat(),
        "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None,
        "acknowledged_at": r["acknowledged_at"].isoformat() if r["acknowledged_at"] else None,
        "sensor_id": r["sensor_id"],
        "anomaly_id": r["anomaly_id"],
        "detected_value": float(r["detected_value"]) if r["detected_value"] else None,
        "anomaly_score": float(r["anomaly_score"]) if r["anomaly_score"] else None,
        "active": r["resolved_at"] is None and r["statut_envoi"] in ("pending", "sent"),
    } for r in rows]

    return {
        "alerts": results,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": max((total_count + page_size - 1) // page_size, 1),
        },
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# POST /pipeline/alerts/acknowledge-all
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/alerts/acknowledge-all")
@limiter.limit("30/minute")
def pipeline_alerts_acknowledge_all(request: Request,
                                    severity: Optional[str] = Body(None, embed=True)):
    clauses: list[str] = ["statut_envoi = 'pending'", "acknowledged_at IS NULL"]
    params: list[Any] = []

    if severity:
        clauses.append("gravite = %s::alert_gravite")
        params.append(severity)

    where = " AND ".join(clauses)

    with postgres.cursor() as cur:
        cur.execute(f"""
            UPDATE alerts
            SET statut_envoi = 'sent',
                acknowledged_at = now(),
                sent_at = COALESCE(sent_at, now())
            WHERE {where}
            RETURNING id
        """, params)
        updated = cur.fetchall()

    return {
        "acknowledged_count": len(updated),
        "message": f"{len(updated)} alert(s) acknowledged",
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# POST /pipeline/alerts/{alert_id}/acknowledge
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/alerts/{alert_id}/acknowledge")
@limiter.limit("30/minute")
def pipeline_alert_acknowledge(request: Request, alert_id: int,
                               notes: Optional[str] = Body(None, embed=True)):
    with postgres.cursor() as cur:
        cur.execute("""
            UPDATE alerts
            SET statut_envoi = 'sent',
                acknowledged_at = now(),
                sent_at = COALESCE(sent_at, now())
            WHERE id = %s
            RETURNING id, gravite, message, statut_envoi, acknowledged_at
        """, [alert_id])
        row = cur.fetchone()

    if not row:
        raise HTTPException(404, detail={"code": "ALERT_NOT_FOUND",
                                          "message": f"Alerte {alert_id} introuvable"})

    return {
        "alert": {
            "id": row["id"],
            "gravite": str(row["gravite"]),
            "message": row["message"],
            "statut_envoi": row["statut_envoi"],
            "acknowledged_at": row["acknowledged_at"].isoformat() if row["acknowledged_at"] else None,
        },
        "notes": notes,
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# POST /pipeline/alerts/{alert_id}/resolve
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/alerts/{alert_id}/resolve")
@limiter.limit("30/minute")
def pipeline_alert_resolve(request: Request, alert_id: int):
    with postgres.cursor() as cur:
        cur.execute("""
            UPDATE alerts
            SET resolved_at = now(),
                statut_envoi = CASE WHEN statut_envoi = 'pending' THEN 'cancelled'
                                    ELSE statut_envoi END
            WHERE id = %s
            RETURNING id, gravite, message, statut_envoi, resolved_at, anomaly_id
        """, [alert_id])
        row = cur.fetchone()

    if not row:
        raise HTTPException(404, detail={"code": "ALERT_NOT_FOUND",
                                          "message": f"Alerte {alert_id} introuvable"})

    # Also mark the linked anomaly as handled
    if row["anomaly_id"]:
        with postgres.cursor() as cur:
            cur.execute("UPDATE anomaly_detections SET handled = true WHERE id = %s",
                        [row["anomaly_id"]])

    return {
        "alert": {
            "id": row["id"],
            "gravite": str(row["gravite"]),
            "message": row["message"],
            "statut_envoi": row["statut_envoi"],
            "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
        },
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# POST /pipeline/alerts/{alert_id}/dismiss
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/alerts/{alert_id}/dismiss")
@limiter.limit("30/minute")
def pipeline_alert_dismiss(request: Request, alert_id: int):
    with postgres.cursor() as cur:
        cur.execute("""
            UPDATE alerts
            SET statut_envoi = 'cancelled'
            WHERE id = %s
            RETURNING id, gravite, message, statut_envoi
        """, [alert_id])
        row = cur.fetchone()

    if not row:
        raise HTTPException(404, detail={"code": "ALERT_NOT_FOUND",
                                          "message": f"Alerte {alert_id} introuvable"})

    return {
        "alert": {
            "id": row["id"],
            "gravite": str(row["gravite"]),
            "message": row["message"],
            "statut_envoi": row["statut_envoi"],
        },
        "generated_at": _now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /pipeline/model/{name}
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/model/{name}")
@limiter.limit("30/minute")
def pipeline_model_detail(request: Request, name: str):
    with postgres.cursor() as cur:
        # Fetch all versions of this model
        cur.execute("""
            SELECT name, type, version, description, hyperparams, metrics,
                   training_start, training_end, data_window_start, data_window_end,
                   file_path, is_active, created_at
            FROM models
            WHERE name = %s
            ORDER BY training_end DESC
        """, [name])
        rows = cur.fetchall()

    if not rows:
        raise HTTPException(404, detail={"code": "MODEL_NOT_FOUND",
                                          "message": f"Modèle '{name}' introuvable"})

    current = rows[0]
    result: dict[str, Any] = {
        "name": current["name"],
        "type": str(current["type"]),
        "current_version": current["version"],
        "is_active": current["is_active"],
        "description": current["description"],
        "created_at": current["created_at"].isoformat() if current["created_at"] else None,
        "training_metadata": {
            "training_start": current["training_start"].isoformat() if current["training_start"] else None,
            "training_end": current["training_end"].isoformat() if current["training_end"] else None,
            "data_window_start": current["data_window_start"].isoformat() if current["data_window_start"] else None,
            "data_window_end": current["data_window_end"].isoformat() if current["data_window_end"] else None,
        },
        "hyperparams": current["hyperparams"] if current["hyperparams"] else {},
        "performance": current["metrics"] if current["metrics"] else {},
        "file_path": current["file_path"],
        "version_history": [
            {
                "version": r["version"],
                "is_active": r["is_active"],
                "training_end": r["training_end"].isoformat() if r["training_end"] else None,
                "metrics": r["metrics"] if r["metrics"] else {},
            }
            for r in rows
        ],
        "generated_at": _now().isoformat(),
    }

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SSE STREAM — Server-Sent Events temps réel
# ═══════════════════════════════════════════════════════════════════════════════

def _serialize(obj: Any) -> str:
    def _default(o: Any) -> str:
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=_default, ensure_ascii=False)


def _sse_event(event: str, data: Any, event_id: Optional[str] = None) -> str:
    lines = [f"event: {event}"]
    if event_id:
        lines.append(f"id: {event_id}")
    for line in _serialize(data).split("\n"):
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _gather_metrics() -> dict:
    now = _now()
    with postgres.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM air_quality WHERE timestamp > now() - interval '24 hours'")
        row = cur.fetchone()
        ingested = int(list(row.values())[0]) if row else 0

        cur.execute("SELECT COUNT(*) FROM anomaly_detections WHERE detected_at > now() - interval '24 hours'")
        row = cur.fetchone()
        anomalies = int(list(row.values())[0]) if row else 0

        cur.execute("SELECT COUNT(*) FROM alerts WHERE created_at > now() - interval '24 hours'")
        row = cur.fetchone()
        alerts = int(list(row.values())[0]) if row else 0

        cur.execute("SELECT COUNT(*) FROM predictions WHERE target_timestamp > now() - interval '24 hours'")
        row = cur.fetchone()
        predictions = int(list(row.values())[0]) if row else 0

        cur.execute("SELECT COUNT(DISTINCT zone_id) FROM kriging_grid WHERE computed_at > now() - interval '6 hours'")
        row = cur.fetchone()
        kriging_zones = int(list(row.values())[0]) if row else 0
        cur.execute("SELECT COUNT(*) FROM zones WHERE niveau = 3")
        row = cur.fetchone()
        total_zones = int(list(row.values())[0]) if row else 1
        coverage = round(kriging_zones / total_zones * 100, 1)

        cur.execute("SELECT EXTRACT(EPOCH FROM now() - MAX(timestamp)) FROM air_quality")
        row = cur.fetchone()
        freshness_min = round(float(list(row.values())[0]) / 60, 1) if row and list(row.values())[0] else None

        cur.execute("SELECT COUNT(*) FROM feature_store WHERE timestamp > now() - interval '24 hours'")
        row = cur.fetchone()
        features_today = int(list(row.values())[0]) if row else 0

    return {
        "messages_ingested_total": ingested,
        "anomalies_detected_total": anomalies,
        "alerts_generated_total": alerts,
        "predictions_generated_total": predictions,
        "kriging_coverage_pct": coverage,
        "data_freshness_min": freshness_min,
        "feature_store_rows_today": features_today,
        "generated_at": now.isoformat(),
    }


def _gather_status() -> dict:
    now = _now()
    with postgres.cursor() as cur:
        cur.execute("SELECT MAX(timestamp) FROM air_quality WHERE timestamp > now() - interval '5 minutes'")
        row = cur.fetchone()
        ingestion_alive = row and list(row.values())[0] is not None

        cur.execute("SELECT MAX(timestamp) FROM air_quality")
        row = cur.fetchone()
        last_any = list(row.values())[0] if row else None

        cur.execute("SELECT COUNT(*) FROM air_quality")
        row = cur.fetchone()
        total_msgs = int(list(row.values())[0]) if row else 0

        cur.execute("SELECT COUNT(*) FROM anomaly_detections")
        row = cur.fetchone()
        total_anomalies = int(list(row.values())[0]) if row else 0

        cur.execute("SELECT COUNT(*) FROM alerts")
        row = cur.fetchone()
        total_alerts = int(list(row.values())[0]) if row else 0

        cur.execute("SELECT MAX(timestamp) FROM feature_store")
        row = cur.fetchone(); last_fe = list(row.values())[0] if row else None
        cur.execute("SELECT MAX(target_timestamp) FROM predictions")
        row = cur.fetchone(); last_pred = list(row.values())[0] if row else None
        cur.execute("SELECT MAX(computed_at) FROM kriging_grid")
        row = cur.fetchone(); last_krig = list(row.values())[0] if row else None
        cur.execute("SELECT MAX(created_at) FROM report_embeddings")
        row = cur.fetchone(); last_nlp = list(row.values())[0] if row else None
        cur.execute("SELECT MAX(created_at) FROM data_quality_metrics")
        row = cur.fetchone(); last_mon = list(row.values())[0] if row else None

    workers = {
        "ingestion": {"status": "running" if ingestion_alive else "stopped",
                       "messages_ingested": total_msgs,
                       "last_message_at": last_any.isoformat() if last_any else None},
        "calibration": {"status": "running" if total_msgs > 0 else "stopped",
                         "messages_calibrated": total_msgs},
        "anomaly_detector": {"status": "running" if total_anomalies > 0 else "stopped",
                              "anomalies_detected": total_anomalies,
                              "alerts_generated": total_alerts},
    }
    flows = {
        "feature_engineering": {"status": "healthy" if last_fe else "idle",
                                 "last_run": last_fe.isoformat() if last_fe else None},
        "predictions": {"status": "healthy" if last_pred else "idle",
                         "last_run": last_pred.isoformat() if last_pred else None},
        "kriging": {"status": "healthy" if last_krig else "idle",
                     "last_run": last_krig.isoformat() if last_krig else None},
        "nlp_pipeline": {"status": "healthy" if last_nlp else "idle",
                          "last_run": last_nlp.isoformat() if last_nlp else None},
        "monitoring": {"status": "healthy" if last_mon else "idle",
                        "last_run": last_mon.isoformat() if last_mon else None},
        "retraining": {"status": "idle", "last_run": None},
    }
    infra = {
        "postgres": {"status": "connected", "pool_size": getattr(postgres, "_pool", None) and 1 or 0},
        "influxdb": {"status": _check_influx()},
        "redis": {"status": _check_redis()},
        "mosquitto": {"status": "connected" if ingestion_alive else "unknown"},
    }
    return {"workers": workers, "flows": flows, "infrastructure": infra, "generated_at": now.isoformat()}


def _gather_alerts() -> list:
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT a.id, a.zone_id, a.type, a.gravite, a.message, a.created_at,
                   split_part(z.path::text, '.', -1) AS zone_slug
            FROM alerts a JOIN zones z ON z.id = a.zone_id
            WHERE a.statut_envoi IN ('pending', 'sent')
            ORDER BY a.created_at DESC LIMIT 5
        """)
        rows = cur.fetchall()
    return [{"id": r["id"], "zone_id": r["zone_slug"], "type": r["type"],
             "gravite": r["gravite"], "message": r["message"],
             "created_at": r["created_at"].isoformat() if r["created_at"] else None} for r in rows]


async def _sse_generator(request: Request):
    seq = 0
    try:
        while True:
            if await request.is_disconnected():
                break
            seq += 1
            if seq % 5 == 1:
                try:
                    yield _sse_event("metrics", _gather_metrics())
                except Exception:
                    yield _sse_event("error", {"type": "metrics", "message": "erreur d'agregation"})
            if seq % 10 == 1:
                try:
                    yield _sse_event("status", _gather_status())
                except Exception:
                    yield _sse_event("error", {"type": "status", "message": "erreur d'agregation"})
                try:
                    yield _sse_event("alerts", _gather_alerts())
                except Exception:
                    yield _sse_event("error", {"type": "alerts", "message": "erreur d'agregation"})
            yield _sse_event("heartbeat", {"time": _now().isoformat(), "seq": seq})
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass


@router.get("/stream")
async def pipeline_stream(request: Request):
    """Flux SSE temps reel — metrics (5s), status (10s), alerts (10s), heartbeat (1s)."""
    return StreamingResponse(
        _sse_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
