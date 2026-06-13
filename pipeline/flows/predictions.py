#!/usr/bin/env python3
"""Flow Prefect — Prédictions PM2.5 (LSTM + Prophet + fallback seuils).

Référence : pipeline/PIPELINE_SPEC.md §6 + 02_ia/COLD_START_STRATEGY.md.

Planification : toutes les 30 minutes via Prefect deployment.
Horizons de prédiction : t+1h (60 min), t+6h (360 min), t+24h (1440 min).

Stratégie de fallback (Cold Start §6.2) selon la quantité de données disponibles :
  - < 1 jour de feature_store : prédiction par seuils IQA fixes
  - < 7 jours : Prophet (trend + saisonnalité)
  - < 30 jours : LSTM léger (si disponible)
  - ≥ 30 jours : LSTM full (si disponible)

Si les modèles .pt / .pkl n'existent pas encore (tâche #7), le flow
descend automatiquement d'un niveau de fallback, avec log INFO (pas d'exception).
"""
from __future__ import annotations

import json
import os
import structlog
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

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
        return structlog.get_logger("predictions")


from db.postgres_client import PostgresPool  # noqa: E402
# Import explicite requis pour que torch.load (pickle) retrouve les classes au chargement
try:
    from models_def import LSTMPollution, LSTMLightPollution  # noqa: F401
except ImportError:
    pass

LOGGER = structlog.get_logger("predictions")

MODELS_DIR = PIPELINE_ROOT / "models"
LSTM_FULL_PATH  = MODELS_DIR / "lstm_full.pt"
LSTM_LIGHT_PATH = MODELS_DIR / "lstm_light.pt"
SCALER_PATH     = MODELS_DIR / "feature_scaler.pkl"
PROPHET_MODEL_PATH = MODELS_DIR / "prophet_pm25.pkl"
FEATURE_COLS_PATH  = MODELS_DIR / "feature_cols.json"

HORIZONS = {"h1": 60, "h6": 360, "h24": 1440}  # horizon → minutes
IQA_WARNING_PM25 = 50.1    # µg/m³ — seuil "malsain pour sensibles" (IQA_SPEC §3.1)
IQA_DANGER_PM25  = 100.1


# ============================================================================
# Lecture feature_store
# ============================================================================
def _read_feature_store(pool: PostgresPool, zone_int_id: int,
                         n_steps: int = 288) -> Optional["pd.DataFrame"]:
    """Lit jusqu'à `n_steps` lignes de feature_store, triées par timestamp asc."""
    import pandas as pd
    with pool.cursor() as cur:
        cur.execute("""
            SELECT timestamp, features AS feature_vector
            FROM feature_store
            WHERE zone_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """, (zone_int_id, n_steps))
        rows = cur.fetchall()
    if not rows:
        return None
    records = []
    for row in reversed(rows):  # oldest first
        fv = row["feature_vector"] if isinstance(row["feature_vector"], dict) else json.loads(row["feature_vector"])
        fv["_timestamp"] = row["timestamp"]
        records.append(fv)
    return pd.DataFrame(records)


def _n_days_available(df) -> float:
    if df is None or len(df) == 0:
        return 0.0
    return len(df) / (288.0)  # 288 steps/jour à résolution 5min


# ============================================================================
# Stratégies de prédiction
# ============================================================================
# prédictions représentées comme de simples dicts (pas de dataclass)


def _threshold_prediction(zone_int_id: int, model_int_id: int) -> dict:
    """Fallback de dernier recours : seuil IQA Dakar moyen (§6.2)."""
    return {
        "zone_int_id": zone_int_id, "model_int_id": model_int_id,
        "h1": 30.0, "h6": 30.0, "h24": 30.0,
        "ci_lower_h1": 10.0, "ci_upper_h1": 80.0,
        "model_used": "threshold_fallback",
    }


def _prophet_prediction(pool: PostgresPool, zone_int_id: int, model_int_id: int) -> dict:
    if not PROPHET_MODEL_PATH.exists():
        return _threshold_prediction(zone_int_id, model_int_id)
    try:
        import joblib, pandas as pd
        m = joblib.load(PROPHET_MODEL_PATH)
        future = m.make_future_dataframe(periods=24, freq="H")
        forecast = m.predict(future)
        h1  = float(forecast.iloc[-23]["yhat"])
        h6  = float(forecast.iloc[-18]["yhat"])
        h24 = float(forecast.iloc[-1]["yhat"])
        return {
            "zone_int_id": zone_int_id, "model_int_id": model_int_id,
            "h1": max(0, h1), "h6": max(0, h6), "h24": max(0, h24),
            "ci_lower_h1": max(0, float(forecast.iloc[-23]["yhat_lower"])),
            "ci_upper_h1": float(forecast.iloc[-23]["yhat_upper"]),
            "model_used": "prophet",
        }
    except Exception as exc:
        LOGGER.warning("prophet_prediction_failed zone=%d error=%s", zone_int_id, exc)
        return _threshold_prediction(zone_int_id, model_int_id)


def _lstm_prediction(pool: PostgresPool, zone_int_id: int, model_int_id: int,
                      df, model_path: Path, model_tag: str) -> dict:
    if not model_path.exists() or not SCALER_PATH.exists():
        return _prophet_prediction(pool, zone_int_id, model_int_id)
    try:
        import torch, joblib, numpy as np
        from models_def import safe_load_model
        n_feat = len(df.columns) if df is not None else 57
        model = safe_load_model(model_path, model_tag, n_features=n_feat)
        if model is None:
            return _prophet_prediction(pool, zone_int_id, model_int_id)
        model.eval()
        scaler = joblib.load(SCALER_PATH)
        cols_path = FEATURE_COLS_PATH
        feat_cols = json.loads(cols_path.read_text()) if cols_path.exists() else list(df.columns)
        feat_cols = [c for c in feat_cols if c in df.columns]
        X = df[feat_cols].fillna(0.0).values
        X = scaler.transform(X)
        X_t = torch.FloatTensor(X).unsqueeze(0)

        with torch.no_grad():
            out = model(X_t)
        preds = out if isinstance(out, (tuple, list)) else (out,)
        h1 = float(preds[0].squeeze())

        # Monte Carlo Dropout (50 passes §6.1)
        model.train()
        mc = [float(model(X_t)[0].squeeze()) for _ in range(50)]
        import numpy as np
        mean_h1 = float(np.mean(mc))
        std_h1  = float(np.std(mc))

        h6  = float(preds[1].squeeze()) if len(preds) > 1 else mean_h1
        h24 = float(preds[2].squeeze()) if len(preds) > 2 else mean_h1

        return {
            "zone_int_id": zone_int_id, "model_int_id": model_int_id,
            "h1": max(0, mean_h1), "h6": max(0, h6), "h24": max(0, h24),
            "ci_lower_h1": max(0, mean_h1 - 1.96 * std_h1),
            "ci_upper_h1": mean_h1 + 1.96 * std_h1,
            "model_used": model_tag,
        }
    except Exception as exc:
        LOGGER.warning("lstm_prediction_failed zone=%d model=%s error=%s", zone_int_id, model_tag, exc)
        return _prophet_prediction(pool, zone_int_id, model_int_id)


# ============================================================================
# Persistence
# ============================================================================
_MODEL_TYPE_MAP = {
    "lstm_full":         "LSTM",
    "lstm_light":        "LSTM",
    "prophet":           "Prophet",
    "threshold_fallback":"RandomForest",  # valeur enum la plus proche pour un fallback règle
    "linear_fallback":   "RandomForest",
}

def _get_or_create_model_id(pool: PostgresPool, model_name: str) -> int:
    model_type = _MODEL_TYPE_MAP.get(model_name, "LSTM")
    with pool.cursor() as cur:
        cur.execute("SELECT id FROM models WHERE name = %s AND is_active = true LIMIT 1", (model_name,))
        row = cur.fetchone()
        if row:
            return int(row["id"])
        cur.execute("""
            INSERT INTO models (name, type, version, is_active)
            VALUES (%s, %s::model_type, '0.0', true)
            ON CONFLICT (name, version) DO UPDATE SET is_active = true
            RETURNING id
        """, (model_name, model_type))
        result = cur.fetchone()
        return int(result["id"]) if result else 1


def _write_prediction(pool: PostgresPool, pred: dict, ts: datetime, horizon_key: str,
                       zone_int_id: int, model_int_id: int) -> None:
    horizon_min = HORIZONS[horizon_key]
    target_ts = ts + timedelta(minutes=horizon_min)
    val = pred[horizon_key]
    ci_l = pred.get("ci_lower_h1") if horizon_key == "h1" else None
    ci_u = pred.get("ci_upper_h1") if horizon_key == "h1" else None
    with pool.cursor() as cur:
        cur.execute("""
            INSERT INTO predictions
              (model_id, zone_id, pollutant, predicted_value, ci_lower, ci_upper,
               target_timestamp, horizon_minutes)
            VALUES (%s, %s, 'pm25', %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (model_int_id, zone_int_id, val, ci_l, ci_u, target_ts, horizon_min))


def _maybe_forecast_alert(pool: PostgresPool, pred: dict, zone_int_id: int, ts: datetime) -> None:
    if pred["h1"] > IQA_DANGER_PM25:
        gravite, msg = "danger", f"PM2.5 prédit à {pred['h1']:.0f} µg/m³ dans 1h"
    elif pred["h1"] > IQA_WARNING_PM25:
        gravite, msg = "warning", f"PM2.5 prédit à {pred['h1']:.0f} µg/m³ dans 1h"
    else:
        return
    with pool.cursor() as cur:
        cur.execute("""
            SELECT 1 FROM alerts WHERE zone_id = %s AND type = 'prevision'
              AND created_at > now() - interval '30 minutes' LIMIT 1
        """, (zone_int_id,))
        if cur.fetchone():
            return
        cur.execute("""
            INSERT INTO alerts (zone_id, type, pollutant, gravite, message, canal_envoi)
            VALUES (%s, 'prevision', 'pm25', %s, %s, '{push,dashboard}')
        """, (zone_int_id, gravite, msg))
    LOGGER.info("forecast_alert gravite=%s zone=%d h1=%.1f", gravite, zone_int_id, pred["h1"])


# ============================================================================
# Tasks et Flow principal
# ============================================================================
@task(name="predict-zone", retries=1)
def predict_zone(zone_slug: str, pool: PostgresPool) -> Optional[dict]:
    log = get_run_logger() if HAS_PREFECT else LOGGER
    zone_int_id = _zone_int(pool, zone_slug)
    if zone_int_id is None:
        log.warning("zone_not_found slug=%s", zone_slug)
        return None

    df = _read_feature_store(pool, zone_int_id, n_steps=288)
    n_days = _n_days_available(df)
    model_int_id = _get_or_create_model_id(pool, "threshold_fallback")

    if n_days < 1:
        pred = _threshold_prediction(zone_int_id, model_int_id)
    elif n_days < 7:
        pred = _prophet_prediction(pool, zone_int_id, model_int_id)
    elif n_days < 30:
        pred = _lstm_prediction(pool, zone_int_id, model_int_id, df, LSTM_LIGHT_PATH, "lstm_light")
    else:
        pred = _lstm_prediction(pool, zone_int_id, model_int_id, df, LSTM_FULL_PATH, "lstm_full")
        model_int_id = _get_or_create_model_id(pool, pred["model_used"])

    log.info("prediction zone=%s n_days=%.1f h1=%.1f h6=%.1f h24=%.1f model=%s",
             zone_slug, n_days, pred["h1"], pred["h6"], pred["h24"], pred["model_used"])
    return {"zone_slug": zone_slug, "zone_int_id": zone_int_id,
            "model_int_id": model_int_id, **pred}


@flow(name="predictions", retries=1, retry_delay_seconds=120)
def run_predictions(zone_id: Optional[str] = None):
    pool = PostgresPool()
    ts = datetime.now(timezone.utc)
    zones = _active_zones(pool) if zone_id is None else [zone_id]

    for zone_slug in zones:
        pred = predict_zone(zone_slug, pool)
        if pred is None:
            continue
        zone_int_id = pred["zone_int_id"]
        model_int_id = pred["model_int_id"]
        for hk in ["h1", "h6", "h24"]:
            _write_prediction(pool, pred, ts, hk, zone_int_id, model_int_id)
        _maybe_forecast_alert(pool, pred, zone_int_id, ts)

    return {"zones": len(zones), "ts": _iso(ts)}


def _active_zones(pool: PostgresPool) -> list[str]:
    with pool.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT split_part(z.path::text, '.', -1) AS slug
            FROM sensors s JOIN zones z ON z.id = s.zone_id WHERE s.status = 'active'
        """)
        return [r["slug"] for r in cur.fetchall()]


def _zone_int(pool: PostgresPool, zone_slug: str) -> Optional[int]:
    with pool.cursor() as cur:
        cur.execute("SELECT id FROM zones WHERE path ~ %s ORDER BY niveau DESC LIMIT 1", (f"*.{zone_slug}",))
        row = cur.fetchone()
        return int(row["id"]) if row else None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    structlog.configure(
        processors=[
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    result = run_predictions()
    print("predictions result:", result)
