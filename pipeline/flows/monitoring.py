#!/usr/bin/env python3
"""Flow Prefect — Monitoring qualité pipeline (métriques Q1-Q6).

Référence : pipeline/PIPELINE_SPEC.md §9.

Planification : toutes les heures.
Calcule les 6 métriques documentées (§9.1) et les écrit dans
`data_quality_metrics` (PostgreSQL). Génère une alerte système si un
seuil de dégradation est dépassé.

Q1 : Couverture données        (points reçus / points attendus)
Q2 : Taux calibration           (points cleansed / points raw)
Q3 : RMSE prédictions t+1h     (sur les 24 dernières heures)
Q4 : RMSE prédictions t+24h    (sur les 24 dernières heures)
Q5 : Taux fausses alertes      (alertes résolues comme FP / total alertes)
Q6 : Latence pipeline p95      (timestamp capteur → point InfluxDB, ms)

Seuils d'alerte :
  Q1 < 0.80  → "data_coverage_low"
  Q2 < 0.90  → "calibration_rate_low"
  Q3 > 15.0  → "prediction_rmse_high_1h"
  Q4 > 25.0  → "prediction_rmse_high_24h"
  Q5 > 0.30  → "false_alarm_rate_high"
"""
from __future__ import annotations

import math
import os
import structlog
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

try:
    from prefect import flow, task
    from prefect.logging import get_run_logger
    HAS_PREFECT = True
except ImportError:
    HAS_PREFECT = False
    def flow(*a, **kw):
        def _d(fn): return fn
        return _d
    def task(*a, **kw):
        def _d(fn): return fn
        return _d
    def get_run_logger():
        return structlog.get_logger("monitoring")

from db.influxdb_client import (  # noqa: E402
    INFLUX_ORG, INFLUX_BUCKET_RAW, INFLUX_BUCKET_CLEANSED,
    get_influxdb_client,
)
from db.postgres_client import PostgresPool  # noqa: E402

LOGGER = structlog.get_logger("monitoring")

# Capteurs attendus par cycle et par période (doit correspondre à la flotte réelle)
EXPECTED_SENSORS = int(os.environ.get("EXPECTED_SENSORS", "10"))
EXPECTED_CYCLE_INTERVAL_S = 30  # §8.1 cycle capteur
EXPECTED_POINTS_PER_HOUR = (3600 // EXPECTED_CYCLE_INTERVAL_S) * EXPECTED_SENSORS

ALERT_THRESHOLDS = {
    "Q1_coverage":               ("min", 0.80, "data_coverage_low"),
    "Q2_calibration_rate":       ("min", 0.90, "calibration_rate_low"),
    "Q3_rmse_1h":                ("max", 15.0, "prediction_rmse_high_1h"),
    "Q4_rmse_24h":               ("max", 25.0, "prediction_rmse_high_24h"),
    "Q5_false_alarm_rate":       ("max", 0.30, "false_alarm_rate_high"),
}


# ============================================================================
# Helpers InfluxDB (comptage de points)
# ============================================================================
def _count_influx_points(client, bucket: str, measurement: str, hours: int = 1) -> int:
    flux = f"""
from(bucket: "{bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> filter(fn: (r) => r._field == "pm25")
  |> count()
"""
    try:
        total = 0
        tables = client.query_api().query(flux, org=INFLUX_ORG)
        for table in tables:
            for rec in table.records:
                v = rec.get_value()
                if v is not None:
                    total += int(v)
        return total
    except Exception:
        return 0


def _compute_p95_latency(client, bucket: str, hours: int = 1) -> Optional[float]:
    """P95 de la latence capteur→InfluxDB en ms, via le champ `seq` qui porte
    le timestamp encodé de façon indirecte — ici on utilise l'écart entre
    l'horodatage InfluxDB (`_time`) et `now()` au moment de la requête comme
    proxy de latence bout-en-bout (§9.1 Q6)."""
    flux = f"""
import "experimental"
from(bucket: "{bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "air_quality_raw")
  |> filter(fn: (r) => r._field == "seq")
  |> map(fn: (r) => ({{
       r with latency_ms: float(v: uint(v: experimental.subDuration(d: duration(v: uint(v: r._time)), from: r._time))) / 1000000.0
  }}))
  |> keep(columns: ["latency_ms"])
  |> quantile(q: 0.95)
"""
    # Simplification : requête directe Flux de quantile complexe ; fallback None si non implémenté
    try:
        tables = get_influxdb_client().query_api().query(flux, org=INFLUX_ORG)
        for table in tables:
            for rec in table.records:
                v = rec.get_value()
                if v is not None:
                    return float(v)
    except Exception:
        pass
    return None


# ============================================================================
# Métriques PostgreSQL (Q3-Q5)
# ============================================================================
def fill_actual_values(pool: PostgresPool) -> None:
    """Joint les prédictions avec les mesures réelles pour calculer le RMSE (§9.1 Q3-Q4)."""
    with pool.cursor() as cur:
        cur.execute("""
            UPDATE predictions p
            SET actual_value = (
                SELECT fs.features->>'pm25_lag_1h'
                FROM feature_store fs
                WHERE fs.zone_id = p.zone_id
                  AND fs.timestamp >= p.target_timestamp - interval '30 minutes'
                  AND fs.timestamp <= p.target_timestamp + interval '30 minutes'
                ORDER BY ABS(EXTRACT(EPOCH FROM (fs.timestamp - p.target_timestamp)))
                LIMIT 1
            )
            WHERE p.actual_value IS NULL
              AND p.target_timestamp <= now() - interval '1 hour'
        """)


def compute_rmse(pool: PostgresPool, horizon_minutes: int, last_hours: int = 24) -> Optional[float]:
    with pool.cursor() as cur:
        cur.execute("""
            SELECT SQRT(AVG(abs_error * abs_error)) AS rmse
            FROM predictions
            WHERE horizon_minutes = %s
              AND actual_value IS NOT NULL
              AND created_at > now() - (%s * interval '1 hour')
        """, (horizon_minutes, last_hours))
        row = cur.fetchone()
        if row and row.get("rmse") is not None:
            return float(row["rmse"])
        return None


def compute_false_alarm_rate(pool: PostgresPool, last_hours: int = 24) -> float:
    with pool.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE statut_envoi = 'cancelled') AS resolved_false,
                   COUNT(*) AS total
            FROM alerts
            WHERE created_at > now() - (%s * interval '1 hour')
        """, (last_hours,))
        row = cur.fetchone()
        if row and row.get("total") and row["total"] > 0:
            return float(row["resolved_false"]) / float(row["total"])
        return 0.0


def write_quality_metrics(pool: PostgresPool, metrics: dict, ts: datetime) -> None:
    import json
    with pool.cursor() as cur:
        cur.execute("""
            INSERT INTO data_quality_metrics (computed_at, metrics)
            VALUES (%s, %s::jsonb)
        """, (ts, json.dumps({k: v for k, v in metrics.items() if v is not None}, ensure_ascii=False)))


def check_and_alert(pool: PostgresPool, metrics: dict) -> list[str]:
    alerts_fired = []
    for metric_key, (direction, threshold, alert_type) in ALERT_THRESHOLDS.items():
        val = metrics.get(metric_key)
        if val is None:
            continue
        breach = (val < threshold) if direction == "min" else (val > threshold)
        if breach:
            # Anti-spam : une seule alerte système par type par heure
            with pool.cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM alerts WHERE type = 'system'
                      AND message LIKE %s
                      AND created_at > now() - interval '1 hour'
                    LIMIT 1
                """, (f"%{alert_type}%",))
                if cur.fetchone():
                    continue
                cur.execute("""
                    INSERT INTO alerts (zone_id, type, gravite, message, canal_envoi)
                    SELECT id, 'system', 'warning', %s, '{dashboard}'
                    FROM zones WHERE niveau = 0 LIMIT 1
                """, (f"Pipeline quality alert: {alert_type} = {val:.3f} (seuil {threshold})",))
            alerts_fired.append(alert_type)
            LOGGER.warning("quality_alert type=%s value=%.3f threshold=%.3f", alert_type, val, threshold)
    return alerts_fired


# ============================================================================
# Flow principal
# ============================================================================
@flow(name="pipeline_monitoring", retries=1, retry_delay_seconds=300)
def run_monitoring():
    log = get_run_logger() if HAS_PREFECT else LOGGER
    pool = PostgresPool()
    influx = get_influxdb_client()
    ts = datetime.now(timezone.utc)
    metrics: dict = {}

    # Q1 — Couverture données
    received = _count_influx_points(influx, INFLUX_BUCKET_RAW, "air_quality_raw", hours=1)
    metrics["Q1_coverage"] = round(received / max(EXPECTED_POINTS_PER_HOUR, 1), 3)
    log.info("Q1_coverage received=%d expected=%d ratio=%.3f", received, EXPECTED_POINTS_PER_HOUR, metrics["Q1_coverage"])

    # Q2 — Taux de calibration
    cleansed = _count_influx_points(influx, INFLUX_BUCKET_CLEANSED, "air_quality_cleansed", hours=1)
    metrics["Q2_calibration_rate"] = round(cleansed / max(received, 1), 3)
    log.info("Q2_calibration_rate cleansed=%d raw=%d ratio=%.3f", cleansed, received, metrics["Q2_calibration_rate"])

    # Q3-Q4 — RMSE prédictions
    fill_actual_values(pool)
    metrics["Q3_rmse_1h"]  = compute_rmse(pool, horizon_minutes=60)
    metrics["Q4_rmse_24h"] = compute_rmse(pool, horizon_minutes=1440)
    log.info("Q3_rmse_1h=%s Q4_rmse_24h=%s", metrics["Q3_rmse_1h"], metrics["Q4_rmse_24h"])

    # Q5 — Taux de fausses alertes
    metrics["Q5_false_alarm_rate"] = round(compute_false_alarm_rate(pool), 3)
    log.info("Q5_false_alarm_rate=%.3f", metrics["Q5_false_alarm_rate"])

    # Q6 — Latence p95 (proxy simplifié)
    metrics["Q6_pipeline_latency_p95_ms"] = _compute_p95_latency(influx, INFLUX_BUCKET_RAW)
    log.info("Q6_latency_p95_ms=%s", metrics["Q6_pipeline_latency_p95_ms"])

    write_quality_metrics(pool, metrics, ts)
    alerts_fired = check_and_alert(pool, metrics)

    log.info("monitoring_cycle_complete ts=%s alerts=%s", _iso(ts), alerts_fired)
    return {**metrics, "alerts_fired": alerts_fired, "computed_at": _iso(ts)}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    result = run_monitoring()
    print("monitoring result:", result)
