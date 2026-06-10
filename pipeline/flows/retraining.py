#!/usr/bin/env python3
"""Flow Prefect — Réentraînement automatique des modèles sur données accumulées.

Stratégies par modèle :
  • Calibration RF    : réentraînement complet toutes les 24h si ≥ MIN_NEW_POINTS
                        nouvelles mesures depuis le dernier cycle.
                        (RandomForest n'a pas de partial_fit)

  • Isolation Forest  : même stratégie que RF (pas de partial_fit sklearn).
                        Fenêtre glissante 30 derniers jours.

  • LSTM full/light   : fine-tuning à chaud (warm restart) toutes les 24h.
                        Charge le modèle existant, 5 epochs supplémentaires sur
                        les 7 derniers jours de feature_store.
                        Sauvegardé uniquement si val_RMSE s'améliore ≥ 0.5%.

  • Prophet           : réentraînement complet hebdomadaire sur tout l'historique
                        feature_store (Prophet est conçu pour ça).

État persistent : models/retrain_state.json
  Enregistre la date et le nb de points du dernier réentraînement de chaque modèle.

Archivage : models/archive/  — garde les 3 dernières versions de chaque modèle.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
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
        return logging.getLogger("retraining")

from db.influxdb_client import get_influxdb_client, INFLUX_BUCKET_CLEANSED, INFLUX_ORG
from db.postgres_client import PostgresPool

LOGGER = logging.getLogger("retraining")
MODELS_DIR    = PIPELINE_ROOT / "models"
ARCHIVE_DIR   = MODELS_DIR / "archive"
STATE_FILE    = MODELS_DIR / "retrain_state.json"

# Nb minimum de nouveaux points cleansed avant réentraînement
MIN_NEW_POINTS = {
    "calibration":  2_000,
    "anomaly":      5_000,
    "lstm":         2_016,   # ~7 jours × 288 points/jour
    "prophet":        168,   # ~7 jours × 24h
}
RETRAIN_INTERVAL_H = {
    "calibration": 24,
    "anomaly":     48,
    "lstm":        24,
    "prophet":    168,   # hebdo
}
ARCHIVE_KEEP = 3


# ============================================================================
# État persistant
# ============================================================================
def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _should_retrain(state: dict, model: str, current_points: int) -> tuple[bool, str]:
    s = state.get(model, {})
    last_ts   = s.get("last_retrain_utc")
    last_pts  = s.get("n_points_at_last_retrain", 0)
    new_points = current_points - last_pts
    interval_h = RETRAIN_INTERVAL_H[model]

    if last_ts:
        elapsed_h = (datetime.now(timezone.utc) -
                     datetime.fromisoformat(last_ts)).total_seconds() / 3600
        if elapsed_h < interval_h:
            return False, f"dernier cycle il y a {elapsed_h:.1f}h < {interval_h}h"

    if new_points < MIN_NEW_POINTS[model]:
        return False, f"seulement {new_points} nouveaux points (min {MIN_NEW_POINTS[model]})"

    return True, f"{new_points} nouveaux points depuis {last_ts or 'jamais'}"


# ============================================================================
# Archivage
# ============================================================================
def _archive(src: Path) -> None:
    if not src.exists():
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst = ARCHIVE_DIR / f"{src.stem}_{ts}{src.suffix}"
    shutil.copy2(src, dst)
    # Nettoyage : garde seulement ARCHIVE_KEEP versions
    past = sorted(ARCHIVE_DIR.glob(f"{src.stem}_*{src.suffix}"), key=lambda p: p.name)
    for old in past[:-ARCHIVE_KEEP]:
        old.unlink(missing_ok=True)


# ============================================================================
# Lecture des données depuis InfluxDB + feature_store
# ============================================================================
def _count_cleansed_points(influx) -> int:
    flux = f"""
from(bucket: "{INFLUX_BUCKET_CLEANSED}")
  |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
  |> filter(fn: (r) => r._field == "pm25")
  |> count()
"""
    try:
        total = 0
        for tbl in influx.query_api().query(flux, org=INFLUX_ORG):
            for rec in tbl.records:
                v = rec.get_value()
                if v:
                    total += int(v)
        return total
    except Exception:
        return 0


def _load_feature_store(pool: PostgresPool, days: int = 30) -> "pd.DataFrame | None":
    import pandas as pd
    with pool.cursor() as cur:
        cur.execute("""
            SELECT timestamp, features AS feature_vector
            FROM feature_store
            WHERE timestamp > now() - (%s * interval '1 day')
            ORDER BY timestamp ASC
        """, (days,))
        rows = cur.fetchall()
    if not rows:
        return None
    records = []
    for row in rows:
        fv = row["feature_vector"] if isinstance(row["feature_vector"], dict) \
             else json.loads(row["feature_vector"])
        fv["_timestamp"] = row["timestamp"]
        records.append(fv)
    return pd.DataFrame(records)


def _load_cleansed_series(influx, days: int = 30) -> "pd.DataFrame | None":
    flux = f"""
from(bucket: "{INFLUX_BUCKET_CLEANSED}")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
  |> filter(fn: (r) => r._field == "pm25" or r._field == "pm10" or
            r._field == "co" or r._field == "no2" or r._field == "o3" or
            r._field == "temperature" or r._field == "humidity")
  |> pivot(rowKey:["_time","zone_id"], columnKey:["_field"], valueColumn:"_value")
"""
    try:
        import pandas as pd
        df = influx.query_api().query_data_frame(flux, org=INFLUX_ORG)
        if hasattr(df, "empty") and df.empty:
            return None
        return df
    except Exception as exc:
        LOGGER.warning("cleansed_series_load_failed error=%s", exc)
        return None


# ============================================================================
# Réentraînement Calibration RF
# ============================================================================
def retrain_calibration(pool: PostgresPool, influx) -> Optional[dict]:
    log = get_run_logger() if HAS_PREFECT else LOGGER
    try:
        import joblib
        import numpy as np
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_absolute_error
    except ImportError as exc:
        log.warning("calibration_retrain_skipped missing_deps=%s", exc)
        return None

    # Charge paires (raw, cleansed) depuis les deux buckets InfluxDB
    flux_pairs = f"""
import "join"
raw = from(bucket: "bucket_raw")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "air_quality_raw" and r._field == "pm25")
  |> aggregateWindow(every: 5m, fn: mean)
  |> rename(columns: {{_value: "pm25_raw"}})

cleansed = from(bucket: "{INFLUX_BUCKET_CLEANSED}")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "air_quality_cleansed" and r._field == "pm25")
  |> aggregateWindow(every: 5m, fn: mean)
  |> rename(columns: {{_value: "pm25_cleansed"}})

join.time(left: raw, right: cleansed, as: (l, r) => ({{l with pm25_cleansed: r.pm25_cleansed}}))
"""
    try:
        import pandas as pd
        df = influx.query_api().query_data_frame(flux_pairs, org=INFLUX_ORG)
    except Exception:
        df = pd.DataFrame()

    # Fallback : merged_calibration.csv (synthétique + externe)
    if df is None or (hasattr(df, "empty") and df.empty):
        ext_p = PIPELINE_ROOT / "training" / "data" / "external" / "merged_calibration.csv"
        base_p = PIPELINE_ROOT / "training" / "data" / "calibration.csv"
        frames = []
        for p in [ext_p, base_p]:
            if p.exists():
                frames.append(pd.read_csv(p))
        if not frames:
            log.warning("calibration_no_training_data")
            return None
        df = pd.concat(frames, ignore_index=True)
        df = df.rename(columns={"pm25_true": "pm25_cleansed"})

    features_needed = ["pm25_raw", "temperature", "humidity", "pressure"]
    targets = "pm25_cleansed"
    available = [c for c in features_needed if c in df.columns]
    if "hour" not in df.columns:
        df["hour"] = pd.to_datetime(df.get("timestamp", df.get("_time", pd.NaT)),
                                     errors="coerce").dt.hour.fillna(12)
    available.append("hour")
    df = df[available + [targets]].dropna()
    if len(df) < 100:
        log.warning("calibration_insufficient_data n=%d", len(df))
        return None

    X, y = df[available].values, df[targets].values
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.15, random_state=42)
    model = RandomForestRegressor(n_estimators=150, max_depth=12, n_jobs=-1, random_state=42)
    model.fit(X_tr, y_tr)
    mae = float(mean_absolute_error(y_te, model.predict(X_te)))

    _archive(MODELS_DIR / "calibration_rf_pm25.pkl")
    joblib.dump(model, MODELS_DIR / "calibration_rf_pm25.pkl")
    log.info("calibration_retrained mae=%.3f n_samples=%d", mae, len(df))
    return {"mae": mae, "n_samples": len(df)}


# ============================================================================
# Réentraînement Isolation Forest
# ============================================================================
def retrain_anomaly(influx) -> Optional[dict]:
    log = get_run_logger() if HAS_PREFECT else LOGGER
    try:
        import joblib
        import numpy as np
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        log.warning("anomaly_retrain_skipped missing_deps=%s", exc)
        return None

    IF_FEATURES = ["pm25", "pm10", "co", "no2", "o3",
                   "temperature", "humidity", "pressure"]

    df = _load_cleansed_series(influx, days=30)
    if df is None or (hasattr(df, "empty") and df.empty):
        ext_p = PIPELINE_ROOT / "training" / "data" / "anomaly.csv"
        if not ext_p.exists():
            log.warning("anomaly_no_training_data")
            return None
        import pandas as pd
        df = pd.read_csv(ext_p)

    available = [c for c in IF_FEATURES if c in df.columns]
    df = df[available].dropna()
    if len(df) < 500:
        log.warning("anomaly_insufficient_data n=%d", len(df))
        return None

    scaler = StandardScaler()
    X = scaler.fit_transform(df.values)
    model = IsolationForest(n_estimators=150, contamination=0.03,
                            random_state=42, n_jobs=-1)
    model.fit(X)
    import numpy as np
    mean_score = float(model.score_samples(X).mean())

    _archive(MODELS_DIR / "anomaly_if.pkl")
    joblib.dump(model,  MODELS_DIR / "anomaly_if.pkl")
    joblib.dump(scaler, MODELS_DIR / "anomaly_if_scaler.pkl")
    log.info("anomaly_retrained mean_score=%.3f n_samples=%d", mean_score, len(df))
    return {"mean_score": mean_score, "n_samples": len(df)}


# ============================================================================
# Fine-tuning LSTM (warm restart)
# ============================================================================
def finetune_lstm(pool: PostgresPool) -> Optional[dict]:
    log = get_run_logger() if HAS_PREFECT else LOGGER
    results = {}
    try:
        import torch
        import torch.nn as nn
        import joblib
        import numpy as np
        from torch.utils.data import DataLoader, TensorDataset
        from models_def import LSTMPollution, LSTMLightPollution, LSTM_LIGHT_FEATURES
    except ImportError as exc:
        log.warning("lstm_finetune_skipped missing_deps=%s", exc)
        return None

    df = _load_feature_store(pool, days=7)
    if df is None or len(df) < 100:
        log.warning("lstm_finetune_insufficient_data")
        return None

    TARGETS = ["target_h1", "target_h6", "target_h24"]
    exc_cols = {"_timestamp"} | set(TARGETS)

    for model_name, ModelClass, cols_file, scaler_file in [
        ("lstm_full",  LSTMPollution,      "feature_cols.json",       "feature_scaler.pkl"),
        ("lstm_light", LSTMLightPollution, "feature_cols_light.json", "feature_scaler_light.pkl"),
    ]:
        model_path  = MODELS_DIR / f"{model_name}.pt"
        scaler_path = MODELS_DIR / scaler_file
        cols_path   = MODELS_DIR / cols_file
        if not model_path.exists() or not scaler_path.exists():
            log.info("lstm_finetune_skipped model=%s (fichier absent)", model_name)
            continue

        feat_cols = json.loads(cols_path.read_text()) if cols_path.exists() else \
                    [c for c in df.columns if c not in exc_cols]
        feat_cols  = [c for c in feat_cols if c in df.columns]

        # Prépare cibles (décalées)
        pm25 = df.get("pm25_lag_1", df.get("pm25_true", None))
        if pm25 is None:
            continue
        # Génère des pseudo-cibles depuis les lags disponibles (approximation)
        targets_df = df[["target_h1", "target_h6", "target_h24"]].copy() \
            if all(c in df.columns for c in TARGETS) \
            else None
        if targets_df is None:
            continue

        scaler = joblib.load(scaler_path)
        X = scaler.transform(df[feat_cols].fillna(0).values).astype(np.float32)
        y = targets_df.values.astype(np.float32)

        seq_len = ModelClass.SEQ_LEN
        seqs_x, seqs_y = [], []
        for i in range(seq_len, len(X)):
            seqs_x.append(X[i - seq_len: i])
            seqs_y.append(y[i])
        if len(seqs_x) < 10:
            continue

        Xt = torch.FloatTensor(np.array(seqs_x))
        yt = torch.FloatTensor(np.array(seqs_y))
        split = int(len(Xt) * 0.85)

        dl_tr = DataLoader(TensorDataset(Xt[:split], yt[:split]), batch_size=16, shuffle=True)
        dl_va = DataLoader(TensorDataset(Xt[split:], yt[split:]), batch_size=16)

        model = torch.load(model_path, weights_only=False)
        model.train()
        opt  = torch.optim.Adam(model.parameters(), lr=1e-4)
        loss_fn = nn.MSELoss()

        # Mémorise la val_loss AVANT fine-tuning pour savoir s'il améliore
        model.eval()
        with torch.no_grad():
            prev_val = np.sqrt(np.mean([
                loss_fn(model(xb), yb).item() for xb, yb in dl_va
            ]))

        # 5 epochs de fine-tuning
        for _ in range(5):
            model.train()
            for xb, yb in dl_tr:
                opt.zero_grad()
                loss_fn(model(xb), yb).backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()

        model.eval()
        with torch.no_grad():
            new_val = np.sqrt(np.mean([
                loss_fn(model(xb), yb).item() for xb, yb in dl_va
            ]))

        improvement = (prev_val - new_val) / max(prev_val, 1e-6)
        if improvement >= 0.005:   # amélioration ≥ 0.5%
            model.to("cpu")
            _archive(model_path)
            torch.save(model, model_path)
            log.info("lstm_finetuned model=%s prev_rmse=%.4f new_rmse=%.4f imp=%.1f%%",
                     model_name, prev_val, new_val, improvement * 100)
            results[model_name] = {"prev_rmse": float(prev_val),
                                    "new_rmse": float(new_val),
                                    "improved": True}
        else:
            log.info("lstm_finetune_no_improvement model=%s prev=%.4f new=%.4f",
                     model_name, prev_val, new_val)
            results[model_name] = {"improved": False}

    return results if results else None


# ============================================================================
# Réentraînement Prophet
# ============================================================================
def retrain_prophet(pool: PostgresPool) -> Optional[dict]:
    log = get_run_logger() if HAS_PREFECT else LOGGER
    try:
        from prophet import Prophet
        import joblib
    except ImportError as exc:
        log.warning("prophet_retrain_skipped missing_deps=%s", exc)
        return None

    with pool.cursor() as cur:
        cur.execute("""
            SELECT date_trunc('hour', timestamp) AS ds,
                   AVG((features->>'pm25_lag_1')::float) AS y
            FROM feature_store
            WHERE timestamp > now() - interval '90 days'
              AND features ? 'pm25_lag_1'
            GROUP BY 1 ORDER BY 1
        """)
        rows = cur.fetchall()

    if len(rows) < 168:
        log.warning("prophet_insufficient_data n=%d", len(rows))
        return None

    import pandas as pd
    df = pd.DataFrame(rows)
    df["ds"] = pd.to_datetime(df["ds"]).dt.tz_localize(None)
    df["y"]  = pd.to_numeric(df["y"], errors="coerce").clip(lower=0)
    df = df.dropna()

    model = Prophet(changepoint_prior_scale=0.05, daily_seasonality=True,
                    weekly_seasonality=True, yearly_seasonality=True)
    model.fit(df)

    _archive(MODELS_DIR / "prophet_pm25.pkl")
    joblib.dump(model, MODELS_DIR / "prophet_pm25.pkl")
    log.info("prophet_retrained n_hours=%d", len(df))
    return {"n_hours": len(df)}


# ============================================================================
# Flow principal
# ============================================================================
@flow(name="model_retraining", retries=1, retry_delay_seconds=600)
def run_retraining():
    log = get_run_logger() if HAS_PREFECT else LOGGER
    pool   = PostgresPool()
    influx = get_influxdb_client()
    state  = _load_state()
    ts     = datetime.now(timezone.utc)

    total_points = _count_cleansed_points(influx)
    log.info("retraining_check total_cleansed_points=%d", total_points)

    results = {}
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Calibration RF ────────────────────────────────────────────────────────
    ok, reason = _should_retrain(state, "calibration", total_points)
    if ok:
        log.info("calibration_retrain_start reason=%s", reason)
        res = retrain_calibration(pool, influx)
        if res:
            state.setdefault("calibration", {}).update({
                "last_retrain_utc": ts.isoformat(),
                "n_points_at_last_retrain": total_points,
            })
            results["calibration"] = res
    else:
        log.info("calibration_retrain_skipped reason=%s", reason)

    # ── Isolation Forest ──────────────────────────────────────────────────────
    ok, reason = _should_retrain(state, "anomaly", total_points)
    if ok:
        log.info("anomaly_retrain_start reason=%s", reason)
        res = retrain_anomaly(influx)
        if res:
            state.setdefault("anomaly", {}).update({
                "last_retrain_utc": ts.isoformat(),
                "n_points_at_last_retrain": total_points,
            })
            results["anomaly"] = res
    else:
        log.info("anomaly_retrain_skipped reason=%s", reason)

    # ── LSTM fine-tuning ──────────────────────────────────────────────────────
    ok, reason = _should_retrain(state, "lstm", total_points)
    if ok:
        log.info("lstm_finetune_start reason=%s", reason)
        res = finetune_lstm(pool)
        if res:
            state.setdefault("lstm", {}).update({
                "last_retrain_utc": ts.isoformat(),
                "n_points_at_last_retrain": total_points,
            })
            results["lstm"] = res
    else:
        log.info("lstm_finetune_skipped reason=%s", reason)

    # ── Prophet ───────────────────────────────────────────────────────────────
    ok, reason = _should_retrain(state, "prophet", total_points)
    if ok:
        log.info("prophet_retrain_start reason=%s", reason)
        res = retrain_prophet(pool)
        if res:
            state.setdefault("prophet", {}).update({
                "last_retrain_utc": ts.isoformat(),
                "n_points_at_last_retrain": total_points,
            })
            results["prophet"] = res
    else:
        log.info("prophet_retrain_skipped reason=%s", reason)

    _save_state(state)
    log.info("retraining_cycle_complete models_updated=%s", list(results.keys()))
    return {"updated": list(results.keys()), "details": results}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    result = run_retraining()
    print("retraining result:", result)
