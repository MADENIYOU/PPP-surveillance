#!/usr/bin/env python3
"""Entraîne le modèle de calibration PM2.5 (Random Forest).

Entrée  : training/data/calibration.csv (généré par generate_synthetic_data.py)
          OU feature_store PostgreSQL si --source db
Sortie  : ../models/calibration_rf_pm25.pkl

Usage :
  python train_calibration.py                    # source=csv par défaut
  python train_calibration.py --source db        # lit depuis PostgreSQL
  python train_calibration.py --n-estimators 200
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

DATA_DIR   = Path(__file__).parent / "data"
MODELS_DIR = PIPELINE_ROOT / "models"
FEATURES   = ["pm25_raw", "temperature", "humidity", "pressure", "hour"]
TARGET     = "pm25_true"


def load_csv() -> pd.DataFrame:
    p = DATA_DIR / "calibration.csv"
    if not p.exists():
        print(f"[WARN] {p} absent — lancement de generate_synthetic_data.py…")
        import subprocess
        subprocess.run([sys.executable,
                        str(Path(__file__).parent / "generate_synthetic_data.py")],
                       check=True)
    return pd.read_csv(p)


def load_db() -> pd.DataFrame:
    from db.postgres_client import PostgresPool
    from db.influxdb_client import get_influxdb_client, INFLUX_BUCKET_RAW, INFLUX_ORG
    pool   = PostgresPool()
    influx = get_influxdb_client()
    flux = f"""
from(bucket: "{INFLUX_BUCKET_RAW}")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "air_quality_raw")
  |> filter(fn: (r) => r._field == "pm25" or r._field == "temperature" or r._field == "humidity")
  |> pivot(rowKey:["_time","sensor_id"], columnKey:["_field"], valueColumn:"_value")
"""
    try:
        df = influx.query_api().query_data_frame(flux, org=INFLUX_ORG)
        if df.empty:
            raise ValueError("InfluxDB vide — utiliser --source csv")
        df = df.rename(columns={"pm25": "pm25_raw", "_time": "timestamp"})
        df["pm25_true"] = df["pm25_raw"] * 0.85 - 1.2   # approximation initiale
        df["pressure"]  = 1013.0
        df["hour"]      = pd.to_datetime(df["timestamp"]).dt.hour
        return df[FEATURES + [TARGET]].dropna()
    except Exception as exc:
        print(f"[WARN] DB load failed ({exc}) — fallback CSV")
        return load_csv()


def train(df: pd.DataFrame, n_estimators: int, max_depth: int) -> tuple:
    df = df[FEATURES + [TARGET]].dropna()
    X, y = df[FEATURES].values, df[TARGET].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.15, random_state=42)

    model = RandomForestRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        min_samples_leaf=5,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    metrics = {
        "mae":  float(mean_absolute_error(y_test, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_test, y_pred))),
        "r2":   float(r2_score(y_test, y_pred)),
    }
    return model, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source",        choices=["csv", "db"], default="csv")
    parser.add_argument("--n-estimators",  type=int, default=150)
    parser.add_argument("--max-depth",     type=int, default=12)
    args = parser.parse_args()

    print("=== Calibration RF — PM2.5 ===")
    df = load_db() if args.source == "db" else load_csv()
    print(f"  {len(df)} échantillons chargés")

    model, metrics = train(df, args.n_estimators, args.max_depth)
    print(f"  MAE={metrics['mae']:.2f}  RMSE={metrics['rmse']:.2f}  R²={metrics['r2']:.3f}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    out_model = MODELS_DIR / "calibration_rf_pm25.pkl"
    out_meta  = MODELS_DIR / "calibration_rf_pm25_meta.json"
    joblib.dump(model, out_model)
    out_meta.write_text(json.dumps({**metrics, "features": FEATURES, "target": TARGET}))
    print(f"  Sauvegardé : {out_model}")

    from training.registry import register_model
    register_model("calibration_rf_pm25", "RandomForest", version="1.0",
                   metrics=metrics, file_path=str(out_model))


if __name__ == "__main__":
    main()
