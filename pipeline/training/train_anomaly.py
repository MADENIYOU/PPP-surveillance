#!/usr/bin/env python3
"""Entraîne le modèle de détection d'anomalies (Isolation Forest).

Entrée  : training/data/anomaly.csv (données normales uniquement)
Sortie  : ../models/anomaly_if.pkl

Usage :
  python train_anomaly.py
  python train_anomaly.py --contamination 0.05 --n-estimators 200
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

DATA_DIR   = Path(__file__).parent / "data"
MODELS_DIR = PIPELINE_ROOT / "models"

# Doit rester synchronisé avec workers/anomaly_detector.py (IF_FEATURES_DEFAULT).
# On se limite STRICTEMENT aux champs réellement émis par les capteurs et présents
# dans le flux cleansed (cf. db/influxdb_client.POLL_FIELDS). wind_speed et
# traffic_index étaient des features synthétiques absentes à l'inférence : remplies
# à 0.0, elles décalaient le scaling et faisaient flagger 100 % des observations.
IF_FEATURES = ["pm25", "pm10", "co", "no2", "o3",
               "temperature", "humidity", "pressure"]


def load_data() -> pd.DataFrame:
    p = DATA_DIR / "anomaly.csv"
    if not p.exists():
        print(f"[WARN] {p} absent — génération des données…")
        import subprocess
        subprocess.run([sys.executable,
                        str(Path(__file__).parent / "generate_synthetic_data.py")],
                       check=True)
    df = pd.read_csv(p)
    available = [c for c in IF_FEATURES if c in df.columns]
    return df[available].dropna()


def train(df: pd.DataFrame, contamination: float, n_estimators: int):
    scaler = StandardScaler()
    X = scaler.fit_transform(df.values)

    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X)

    # Qualité : le détecteur flagge decision_function < 0. Sur des données normales,
    # ce taux doit être proche de `contamination` (et non 100 %).
    decision = model.decision_function(X)
    pct_flagged = float(np.mean(decision < 0) * 100)
    mean_score  = float(decision.mean())

    return model, scaler, {"mean_score": mean_score, "pct_flagged_normal": pct_flagged}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contamination",  type=float, default=0.03)
    parser.add_argument("--n-estimators",   type=int,   default=150)
    args = parser.parse_args()

    print("=== Isolation Forest — détection d'anomalies ===")
    df = load_data()
    print(f"  {len(df)} observations normales chargées, {df.shape[1]} features")

    model, scaler, metrics = train(df, args.contamination, args.n_estimators)
    print(f"  Score moyen : {metrics['mean_score']:.3f}")
    print(f"  % données normales flagguées (<-0.3) : {metrics['pct_flagged_normal']:.1f}%")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    out_model  = MODELS_DIR / "anomaly_if.pkl"
    out_scaler = MODELS_DIR / "anomaly_if_scaler.pkl"
    out_meta   = MODELS_DIR / "anomaly_if_meta.json"
    joblib.dump(model,  out_model)
    joblib.dump(scaler, out_scaler)
    out_meta.write_text(json.dumps({**metrics, "features": IF_FEATURES}))
    print(f"  Sauvegardé : {out_model}")

    from training.registry import register_model
    register_model("anomaly_if", "IsolationForest", version="1.0",
                   metrics={**metrics, "features": IF_FEATURES}, file_path=str(out_model))


if __name__ == "__main__":
    main()
