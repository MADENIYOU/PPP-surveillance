#!/usr/bin/env python3
"""Worker de détection d'anomalies — Étape 3 du pipeline.

Référence : pipeline/PIPELINE_SPEC.md §4 + 02_ia/IQA_SPEC.md (seuils).

Pattern pull (boucle 60 secondes) — 3 niveaux de détection :

  Niveau 1 — Seuils fixes IQA (§4.1) :
    Évalué à chaque point calibré reçu via la boucle 60s.
    Seuils adaptés au contexte dakarois (IQA_SPEC.md §3) — "malsain" = warning,
    "dangereux" = danger.

  Niveau 2 — Isolation Forest (§4, Niveau 2) :
    Fenêtre glissante 2h, toutes les 60s. Si le modèle `.pkl` n'existe pas
    encore (entraîné en tâche #7), ce niveau est sauté silencieusement
    (logging INFO, pas d'exception).

  Niveau 3 — Règles structurelles (§4, Niveau 3) :
    Toutes les 5 min : capteur bloqué (std < 0.1 sur 30min),
    ratio implausible PM2.5 > PM10 × 1.5.

Les anomalies sont écrites dans PostgreSQL `anomaly_detections` ;
une alerte est générée dans `alerts` si la sévérité est suffisante
et qu'aucune alerte dupliquée n'a été émise dans les 30 dernières minutes (§4.2).
"""
from __future__ import annotations

import functools
import json
import os
import select
import signal
import structlog
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

from db.influxdb_client import get_influxdb_client, query_cleansed_window  # noqa: E402
from db.postgres_client import PostgresPool  # noqa: E402
from metrics import inc_counter, set_gauge  # noqa: E402

LOGGER = structlog.get_logger("anomaly_detector")

DETECTOR_INTERVAL_S = int(os.environ.get("ANOMALY_DETECTOR_INTERVAL", "60"))
STRUCTURAL_RULES_INTERVAL_S = 5 * 60

MODELS_DIR = PIPELINE_ROOT / "models"
IF_MODEL_PATH = MODELS_DIR / "anomaly_if.pkl"
IF_SCALER_PATH = MODELS_DIR / "anomaly_if_scaler.pkl"
IF_META_PATH = MODELS_DIR / "anomaly_if_meta.json"
IF_MODEL_ID = "isolation_forest_v1"

# Features attendues par l'Isolation Forest. DOIT correspondre exactement (ordre +
# nombre) à l'entraînement (training/train_anomaly.py:IF_FEATURES). Lue depuis les
# métadonnées du modèle pour rester synchronisée ; repli sur la liste de référence.
# Les champs absents du flux capteur (wind_speed, traffic_index) sont remplis à 0.0
# puis recentrés par le scaler.
IF_FEATURES_DEFAULT = ["pm25", "pm10", "co", "no2", "o3",
                       "temperature", "humidity", "pressure"]

# ─── Seuils IQA adaptés Dakar (IQA_SPEC.md §3) ───────────────────────────────
# Seuls "warning" (malsain pour sensibles) et "danger" (malsain+) sont déclenchés.
THRESHOLDS: dict[str, dict[str, float]] = {
    "pm25":  {"warning":  50.1, "danger": 100.1},
    "pm10":  {"warning": 155.0, "danger": 255.0},
    "co":    {"warning":   9.5, "danger":  12.5},
    "no2":   {"warning": 101.0, "danger": 361.0},
    "o3":    {"warning":  71.0, "danger":  86.0},
}

ALERT_COOLDOWN_MIN = 30  # §4.2 : pas de doublon dans les 30 min


# ============================================================================
# Persistance PostgreSQL
# ============================================================================
def insert_anomaly(pool: PostgresPool, sensor_serial: str, zone_id: str,
                   anomaly_type: str, pollutant: str, detected_value: float,
                   threshold: float, score: Optional[float], detected_at: datetime,
                   severity: str) -> Optional[int]:
    """INSERT dans `anomaly_detections`. Retourne l'ID inséré."""
    with pool.cursor() as cur:
        # Résolution sensor.id depuis serial_number
        cur.execute("SELECT id, zone_id FROM sensors WHERE serial_number = %s LIMIT 1", (sensor_serial,))
        row = cur.fetchone()
        sensor_int_id = int(row["id"]) if row else None
        zone_int_id = int(row["zone_id"]) if row else None

        if zone_int_id is None:
            with pool.cursor() as c2:
                c2.execute("SELECT id FROM zones WHERE path ~ %s ORDER BY niveau DESC LIMIT 1", (f"*.{zone_id}",))
                z = c2.fetchone()
                zone_int_id = int(z["id"]) if z else 1  # fallback zone_id=1

        cur.execute(
            """
            INSERT INTO anomaly_detections
              (sensor_id, zone_id, pollutant, detected_value, threshold,
               anomaly_score, detected_at, handled)
            VALUES (%s, %s, %s, %s, %s, %s, %s, false)
            RETURNING id
            """,
            (sensor_int_id, zone_int_id, pollutant, detected_value, threshold, score,
             detected_at),
        )
        result = cur.fetchone()
        return int(result["id"]) if result else None


def get_recent_alerts(pool: PostgresPool, zone_int_id: int, alert_type: str,
                      minutes: int = ALERT_COOLDOWN_MIN) -> bool:
    """Vérifie si une alerte du même type existe déjà pour cette zone (§4.2)."""
    with pool.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM alerts
            WHERE zone_id = %s AND type = %s
              AND created_at > now() - (%s * interval '1 minute')
            LIMIT 1
            """,
            (zone_int_id, alert_type, minutes),
        )
        return cur.fetchone() is not None


def insert_alert(pool: PostgresPool, anomaly_id: int, zone_int_id: int,
                 alert_type: str, pollutant: str, gravite: str, message: str) -> None:
    with pool.cursor() as cur:
        cur.execute(
            """
            INSERT INTO alerts (anomaly_id, zone_id, type, pollutant, gravite, message, canal_envoi)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (anomaly_id, zone_int_id, alert_type, pollutant, gravite, message,
             ["push", "dashboard"]),
        )


def _zone_int_id(pool: PostgresPool, zone_slug: str) -> int:
    with pool.cursor() as cur:
        cur.execute("SELECT id FROM zones WHERE path ~ %s ORDER BY niveau DESC LIMIT 1", (f"*.{zone_slug}",))
        row = cur.fetchone()
        return int(row["id"]) if row else 1


# ============================================================================
# Niveaux de détection
# ============================================================================
def score_to_severity(score: float) -> str:
    """score = valeur de decision_function (négative ⇒ anomalie). Plus c'est
    négatif, plus l'écart à la normale est marqué."""
    if score < -0.15:
        return "danger"
    return "warning"


@functools.lru_cache(maxsize=1)
def _if_features() -> tuple[str, ...]:
    """Liste ordonnée des features de l'IsolationForest, lue depuis les métadonnées
    du modèle (repli sur IF_FEATURES_DEFAULT). Mise en cache (le modèle ne change
    pas en cours d'exécution)."""
    try:
        meta = json.loads(IF_META_PATH.read_text())
        feats = meta.get("features")
        if feats:
            return tuple(feats)
    except Exception as exc:
        LOGGER.warning("if_meta_load_error error=%s — features par défaut", exc)
    return tuple(IF_FEATURES_DEFAULT)


def build_anomaly_features(df) -> "import numpy as np; np.ndarray":
    """Construit la matrice de features dans l'ordre EXACT attendu par le modèle.
    Les colonnes absentes du df (ex. wind_speed, traffic_index non émis par les
    capteurs) sont créées à 0.0 → le nombre de features correspond toujours au
    modèle, évitant le ValueError "X has N features, expecting M"."""
    import pandas as pd
    feats = list(_if_features())
    aligned = df.reindex(columns=feats).fillna(0.0)
    return aligned.values


def detect_level1_thresholds(sensor_id: str, zone_id: str, row) -> list[dict]:
    """Niveau 1 — seuils fixes par polluant (§4.1)."""
    findings = []
    for pollutant, levels in THRESHOLDS.items():
        val = row.get(pollutant)
        if val is None:
            continue
        val = float(val)
        for severity, threshold in [("danger", levels["danger"]), ("warning", levels["warning"])]:
            if val >= threshold:
                findings.append({
                    "type": "threshold_exceeded",
                    "severity": severity,
                    "pollutant": pollutant,
                    "detected_value": val,
                    "threshold": threshold,
                    "score": None,
                    "description": f"{pollutant.upper()} = {val:.1f} dépasse le seuil {severity} ({threshold})",
                })
                break  # Seule la sévérité la plus haute est rapportée
    return findings


def detect_level2_isolation_forest(sensor_id: str, df) -> list[dict]:
    """Niveau 2 — Isolation Forest sur fenêtre 2h (§4, Niveau 2)."""
    if not IF_MODEL_PATH.exists():
        return []
    import numpy as np
    try:
        import joblib
        iso_forest = joblib.load(IF_MODEL_PATH)
        # Scaler appliqué à l'entraînement (StandardScaler) : indispensable pour
        # que les scores correspondent. Optionnel si le fichier est absent.
        scaler = joblib.load(IF_SCALER_PATH) if IF_SCALER_PATH.exists() else None
    except Exception as exc:
        LOGGER.warning("if_model_load_error sensor=%s error=%s", sensor_id, exc)
        return []

    if len(df) < 10:
        return []

    # On utilise la fenêtre 2h comme contexte mais on n'évalue QUE la dernière
    # observation (comme le niveau 1) : re-scorer tout l'historique à chaque cycle
    # de 60s ré-insérait les mêmes points en boucle (faux positifs massifs).
    X = build_anomaly_features(df)
    if scaler is not None:
        X = scaler.transform(X)
    # decision_function : négatif ⇒ anomalie. Frontière calibrée par `contamination`
    # à l'entraînement (≈3 %), au lieu d'un seuil arbitraire sur score_samples qui
    # flaggait 100 % des observations normales.
    score = float(iso_forest.decision_function(X[-1:])[0])
    if score >= 0:
        return []
    last_row = df.iloc[-1]
    return [{
        "type": "pollution_anomaly",
        "severity": score_to_severity(score),
        "pollutant": "pm25",
        "detected_value": float(last_row.get("pm25", 0.0)),
        "threshold": 0.0,
        "score": score,
        "description": f"Isolation Forest decision_function={score:.3f} (<0 ⇒ anomalie)",
    }]


def detect_level3_structural(sensor_id: str, df) -> list[dict]:
    """Niveau 3 — règles structurelles (§4, Niveau 3) : capteur bloqué + ratio implausible."""
    if len(df) < 10:
        return []
    findings = []

    # Capteur bloqué : std très faible sur la fenêtre disponible (§4, `detect_stuck_sensor`)
    if "pm25" in df.columns and df["pm25"].std() < 0.1:
        findings.append({
            "type": "stuck_sensor",
            "severity": "warning",
            "pollutant": "pm25",
            "detected_value": float(df["pm25"].mean()),
            "threshold": 0.1,
            "score": None,
            "description": f"Capteur bloqué : std(pm25) = {df['pm25'].std():.4f} < 0.1",
        })

    # Ratio implausible : PM2.5 > PM10 × 1.5 (§4, `detect_implausible_ratio`)
    if "pm25" in df.columns and "pm10" in df.columns:
        last = df.iloc[-1]
        pm25, pm10 = float(last.get("pm25", 0.0)), float(last.get("pm10", 0.0))
        if pm10 > 0 and pm25 > pm10 * 1.5:
            findings.append({
                "type": "implausible_ratio",
                "severity": "warning",
                "pollutant": "pm25",
                "detected_value": pm25,
                "threshold": pm10 * 1.5,
                "score": None,
                "description": f"PM2.5 ({pm25:.1f}) > PM10 ({pm10:.1f}) × 1.5",
            })

    return findings


# ============================================================================
# Boucle principale
# ============================================================================
class AnomalyDetectorWorker:

    def __init__(self, pg_pool: PostgresPool):
        self._pool = pg_pool
        self._influx = get_influxdb_client()
        self._stop = False
        self._last_structural_check: dict[str, datetime] = {}
        self._anomaly_count = 0
        self._alert_count = 0

    def _listen_thread(self) -> None:
        """Listen for PostgreSQL NOTIFY on air_quality_insert channel for real-time Level 1."""
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=os.environ.get("POSTGRES_HOST", "localhost"),
                port=int(os.environ.get("POSTGRES_PORT", "5432")),
                dbname=os.environ.get("POSTGRES_DB", "dakar_pollution"),
                user=os.environ.get("POSTGRES_USER", "dakar_admin"),
                password=os.environ.get("POSTGRES_PASSWORD", ""),
            )
            conn.set_isolation_level(0)
            cursor = conn.cursor()
            cursor.execute("LISTEN air_quality_insert;")
            LOGGER.info("anomaly_detector listening on air_quality_insert")

            while not self._stop:
                if select.select([conn], [], [], 5) == ([], [], []):
                    continue
                conn.poll()
                while conn.notifies:
                    notify = conn.notifies.pop(0)
                    try:
                        data = json.loads(notify.payload)
                        findings = detect_level1_thresholds(
                            str(data.get("sensor_id", "")),
                            "unknown",
                            data
                        )
                        sensor_id = str(data.get("sensor_id", ""))
                        zone_int_id = int(data.get("zone_id", 1))
                        ts_str = str(data.get("timestamp", ""))
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.now(timezone.utc)
                        for f in findings:
                            self._persist(f, sensor_id, "unknown", zone_int_id, ts)
                    except Exception:
                        LOGGER.exception("notify_handler_error")
        except Exception:
            LOGGER.exception("listen_thread_error")

    def run(self) -> None:
        try:
            signal.signal(signal.SIGTERM, lambda *_: self._shutdown())
            signal.signal(signal.SIGINT, lambda *_: self._shutdown())
        except ValueError:
            pass
        self._listen_t = threading.Thread(target=self._listen_thread, daemon=True)
        self._listen_t.start()
        LOGGER.info("anomaly_detector_started interval_s=%d", DETECTOR_INTERVAL_S)
        while not self._stop:
            t_start = time.perf_counter()
            self._cycle()
            elapsed = time.perf_counter() - t_start
            time.sleep(max(0, DETECTOR_INTERVAL_S - elapsed))
        LOGGER.info("anomaly_detector_stopped anomalies=%d alerts=%d", self._anomaly_count, self._alert_count)

    def _cycle(self) -> None:
        active_sensors = self._get_active_sensors()
        if not active_sensors:
            return

        for sensor in active_sensors:
            sensor_id = sensor["serial_number"]
            zone_slug = sensor.get("zone_slug", "unknown")
            zone_int_id = sensor.get("zone_int_id", 1)

            df = query_cleansed_window(self._influx, sensor_id, hours=2)
            if df.empty:
                continue

            last_row = df.iloc[-1]
            ts = last_row.get("_time") or datetime.now(timezone.utc)
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()

            # Niveau 1 — seuils fixes (toutes les 60s, sur le dernier point)
            findings = detect_level1_thresholds(sensor_id, zone_slug, last_row)

            # Niveau 2 — Isolation Forest (toutes les 60s, fenêtre 2h)
            findings += detect_level2_isolation_forest(sensor_id, df)

            # Niveau 3 — règles structurelles (toutes les 5 min)
            now = datetime.now(timezone.utc)
            last_struct = self._last_structural_check.get(sensor_id, datetime.min.replace(tzinfo=timezone.utc))
            if (now - last_struct).total_seconds() >= STRUCTURAL_RULES_INTERVAL_S:
                findings += detect_level3_structural(sensor_id, df)
                self._last_structural_check[sensor_id] = now

            for finding in findings:
                self._persist(finding, sensor_id, zone_slug, zone_int_id, ts)

    def _persist(self, finding: dict, sensor_id: str, zone_slug: str, zone_int_id: int, ts: datetime) -> None:
        try:
            anomaly_id = insert_anomaly(
                self._pool, sensor_id, zone_slug,
                finding["type"], finding["pollutant"],
                finding["detected_value"], finding["threshold"],
                finding.get("score"), ts, finding["severity"],
            )
            self._anomaly_count += 1
            inc_counter("dakar_anomalies_detected_total", 1, {"type": finding["type"]})
            LOGGER.info("anomaly_detected sensor=%s type=%s severity=%s pollutant=%s val=%.1f",
                        sensor_id, finding["type"], finding["severity"], finding["pollutant"], finding["detected_value"])

            if anomaly_id and finding["severity"] in ("warning", "danger"):
                if not get_recent_alerts(self._pool, zone_int_id, "anomaly"):
                    insert_alert(
                        self._pool, anomaly_id, zone_int_id,
                        alert_type="anomaly",
                        pollutant=finding["pollutant"],
                        gravite=finding["severity"],
                        message=finding["description"],
                    )
                    self._alert_count += 1
                    inc_counter("dakar_alerts_generated_total", 1, {"severity": finding["severity"]})
                    LOGGER.info("alert_generated zone=%s type=anomaly gravite=%s", zone_slug, finding["severity"])
        except Exception:
            LOGGER.exception("anomaly_persist_failed sensor=%s finding=%s", sensor_id, finding.get("type"))

    def _get_active_sensors(self) -> list[dict]:
        """Retourne la liste des capteurs actifs avec leur zone_id slug + int."""
        try:
            with self._pool.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.serial_number,
                           split_part(z.path::text, '.', -1) AS zone_slug,
                           s.zone_id AS zone_int_id
                    FROM sensors s
                    JOIN zones z ON z.id = s.zone_id
                    WHERE s.status = 'active'
                    """,
                )
                return list(cur.fetchall())
        except Exception:
            LOGGER.exception("get_active_sensors_failed")
            return []

    def _shutdown(self) -> None:
        LOGGER.info("anomaly_detector_stopping")
        self._stop = True


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

    from db.postgres_client import PostgresPool
    pool = PostgresPool()
    from metrics import start_metrics_server
    metrics_server = start_metrics_server()
    AnomalyDetectorWorker(pool).run()
