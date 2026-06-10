#!/usr/bin/env python3
"""Worker de calibration RF + Kalman — Étape 2 du pipeline.

Référence : pipeline/PIPELINE_SPEC.md §3.

Pattern pull (boucle 30 secondes) : lit les nouveaux points bruts de
`bucket_raw` (measurement `air_quality_raw`), applique :
  1. Calibration par Random Forest si le modèle `.pkl` existe, sinon fallback
     linéaire (slope=0.85, intercept=-1.2 — valeurs doc §3.1) ;
  2. Filtre de Kalman scalaire 1D par capteur pour lisser et quantifier
     l'incertitude ;
  3. Écriture batch dans `bucket_cleansed` (measurement `air_quality_cleansed`).

L'état Kalman (x, P, Q, R) est persisté entre les redémarrages dans
`models/kalman_states.json` pour éviter la re-initialisation à froid.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

from db.influxdb_client import (  # noqa: E402
    InfluxBatchWriter,
    build_cleansed_point,
    get_influxdb_client,
    query_raw_recent,
)
from db.postgres_client import PostgresPool  # noqa: E402

LOGGER = logging.getLogger("calibration")

CALIBRATION_INTERVAL_S = int(os.environ.get("CALIBRATION_INTERVAL", "30"))
LOOKBACK_S = int(os.environ.get("CALIBRATION_LOOKBACK_S", "60"))

MODELS_DIR = PIPELINE_ROOT / "models"
RF_MODEL_PATH = MODELS_DIR / "calibration_rf_pm25.pkl"
KALMAN_PARAMS_PATH = MODELS_DIR / "kalman_params.json"
KALMAN_STATES_PATH = MODELS_DIR / "kalman_states.json"

FALLBACK_SLOPE = 0.85
FALLBACK_INTERCEPT = -1.2

# ─── Paramètres Kalman par défaut ─────────────────────────────────────────────
DEFAULT_Q = 0.5    # Bruit processus : pollution varie de ~0.5 µg/m³/cycle
DEFAULT_R = 4.0    # Bruit mesure : incertitude PMS5003 ≈ ±2 µg/m³ (variance=4)


# ============================================================================
# État Kalman scalaire 1D (§3.2)
# ============================================================================
@dataclass
class KalmanState:
    x: float       # Estimation courante (µg/m³)
    P: float       # Covariance d'erreur
    Q: float = DEFAULT_Q
    R: float = DEFAULT_R
    last_update: str = ""  # ISO timestamp


def kalman_update(state: KalmanState, measurement: float) -> tuple[float, float]:
    """Un pas du filtre de Kalman scalaire.

    Retourne `(x_updated, std_updated)` — l'estimation lissée et son
    écart-type (√P_updated, utile comme indicateur de confiance §3.4)."""
    x_pred = state.x
    P_pred = state.P + state.Q

    K = P_pred / (P_pred + state.R)
    state.x = x_pred + K * (measurement - x_pred)
    state.P = (1 - K) * P_pred
    state.last_update = _iso(datetime.now(timezone.utc))

    return state.x, K, (state.P ** 0.5)


def init_kalman_state(initial_value: float) -> KalmanState:
    """Initialise un état Kalman à partir d'une première mesure brute."""
    return KalmanState(x=initial_value, P=DEFAULT_R)


def load_kalman_states(path: Path) -> dict[str, KalmanState]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {sid: KalmanState(**v) for sid, v in raw.items()}
    except Exception:
        LOGGER.warning("kalman_states_load_failed path=%s — reset des états", path)
        return {}


def save_kalman_states(states: dict[str, KalmanState], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {sid: asdict(s) for sid, s in states.items()}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================================
# Calibration RF (avec fallback linéaire — §3.3)
# ============================================================================
def load_calibration_model():
    """Charge le modèle RF et la liste de features depuis le disque.

    Retourne `(model, feature_list)` ou `(None, [])` si le fichier n'existe
    pas encore (le modèle est entraîné en tâche #7 — en attendant le fallback
    linéaire est utilisé, ce qui est le comportement documenté en §3.3)."""
    if not RF_MODEL_PATH.exists():
        LOGGER.info("rf_model_not_found path=%s — fallback linéaire activé", RF_MODEL_PATH)
        return None, []
    try:
        import joblib
        model = joblib.load(RF_MODEL_PATH)
        feature_list_path = MODELS_DIR / "calibration_features.json"
        features = json.loads(feature_list_path.read_text(encoding="utf-8")) if feature_list_path.exists() else []
        LOGGER.info("rf_model_loaded path=%s n_features=%d", RF_MODEL_PATH, len(features))
        return model, features
    except Exception as exc:
        LOGGER.warning("rf_model_load_error error=%s — fallback linéaire", exc)
        return None, []


def build_rf_feature_vector(row, sensor_id: str, feature_list: list) -> Optional[list]:
    """Construit le vecteur de features pour le modèle RF.

    Retourne None si des features sont manquantes (déclenchera le fallback
    linéaire plutôt que de propager une erreur)."""
    vec = []
    for fname in feature_list:
        v = row.get(fname)
        if v is None:
            return None
        vec.append(float(v))
    return vec if vec else None


# ============================================================================
# Worker principal
# ============================================================================
class CalibrationWorker:
    """Boucle de calibration (§3.3 `calibration_loop`).

    `pg_pool` : utilisé pour loger les résumés de cycle (futur : mise à jour
    `calibration` table). Passé None si PostgreSQL n'est pas requis pour
    une démo minimaliste."""

    def __init__(self, pg_pool: Optional[PostgresPool] = None,
                 clock_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleep_fn: Callable[[float], None] = time.sleep):
        self._pg_pool = pg_pool
        self._clock_fn = clock_fn
        self._sleep_fn = sleep_fn
        self._influx = get_influxdb_client()
        self._writer = InfluxBatchWriter(self._influx, bucket=os.environ.get("INFLUXDB_BUCKET_CLEANSED", "bucket_cleansed"))
        self._kalman: dict[str, KalmanState] = load_kalman_states(KALMAN_STATES_PATH)
        self._model, self._features = load_calibration_model()
        self._model_mtime: float = RF_MODEL_PATH.stat().st_mtime if RF_MODEL_PATH.exists() else 0.0
        self._stop = False
        self._cycles_done = 0
        self._points_calibrated = 0

    def _maybe_reload_model(self) -> None:
        """Recharge le modèle RF si le fichier a changé sur disque (hot-reload)."""
        if not RF_MODEL_PATH.exists():
            return
        mtime = RF_MODEL_PATH.stat().st_mtime
        if mtime != self._model_mtime:
            self._model, self._features = load_calibration_model()
            self._model_mtime = mtime
            LOGGER.info("rf_model_hot_reloaded mtime=%.0f", mtime)

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown())
        signal.signal(signal.SIGINT, lambda *_: self._shutdown())
        LOGGER.info("calibration_worker_started interval_s=%d", CALIBRATION_INTERVAL_S)
        while not self._stop:
            t_start = time.perf_counter()
            self._cycle()
            self._cycles_done += 1
            elapsed = time.perf_counter() - t_start
            self._sleep_fn(max(0, CALIBRATION_INTERVAL_S - elapsed))
        LOGGER.info("calibration_worker_stopped cycles=%d points=%d", self._cycles_done, self._points_calibrated)

    def _cycle(self) -> None:
        self._maybe_reload_model()
        df = query_raw_recent(self._influx, lookback_s=LOOKBACK_S)
        if df is None or df.empty:
            LOGGER.debug("calibration_cycle no_new_points")
            return

        n_calibrated = 0
        for sensor_id, group in df.groupby("sensor_id"):
            zone_id = group["zone_id"].iloc[0] if "zone_id" in group.columns else "unknown"
            for _, row in group.iterrows():
                pm25_raw = float(row.get("pm25", 0.0))
                ts = row.get("_time") or row.get("_timestamp")
                if ts is None:
                    continue
                if hasattr(ts, "to_pydatetime"):
                    ts = ts.to_pydatetime()

                # Calibration RF ou fallback linéaire
                try:
                    feat_vec = build_rf_feature_vector(row, sensor_id, self._features)
                    if self._model is not None and feat_vec is not None:
                        pm25_rf = float(self._model.predict([feat_vec])[0])
                        cal_method = "random_forest"
                    else:
                        raise ValueError("model_or_features_unavailable")
                except Exception:
                    pm25_rf = pm25_raw * FALLBACK_SLOPE + FALLBACK_INTERCEPT
                    cal_method = "linear_fallback"

                pm25_rf = max(0.0, pm25_rf)

                # Filtre de Kalman (§3.2)
                state = self._kalman.get(sensor_id, init_kalman_state(pm25_rf))
                pm25_kalman, kalman_gain, pm25_std = kalman_update(state, pm25_rf)
                self._kalman[sensor_id] = state

                point = build_cleansed_point(
                    sensor_id=sensor_id, zone_id=zone_id, timestamp=ts,
                    pm25_kalman=max(0.0, pm25_kalman), pm25_std=pm25_std,
                    calibration_method=cal_method, kalman_gain=kalman_gain, row=row,
                )
                self._writer.add(point)
                n_calibrated += 1

        if n_calibrated:
            n_flushed = self._writer.flush()
            self._points_calibrated += n_calibrated
            save_kalman_states(self._kalman, KALMAN_STATES_PATH)
            LOGGER.info("calibration_cycle n_calibrated=%d n_flushed=%d method=%s",
                        n_calibrated, n_flushed, cal_method if n_calibrated else "—")

    def _shutdown(self) -> None:
        LOGGER.info("calibration_worker_stopping")
        self._stop = True
        self._writer.flush()
        save_kalman_states(self._kalman, KALMAN_STATES_PATH)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    CalibrationWorker().run()
