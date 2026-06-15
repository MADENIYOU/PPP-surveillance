#!/usr/bin/env python3
"""Entraîne le modèle Prophet pour les prédictions PM2.5 (cold start < 7 jours).

Entrée  : training/data/prophet.csv
Sortie  : ../models/prophet_pm25.pkl

Pré-requis : pip install prophet  (cf. requirements_training.txt)
Usage :
  python train_prophet.py
  python train_prophet.py --changepoint-prior 0.1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

DATA_DIR   = Path(__file__).parent / "data"
MODELS_DIR = PIPELINE_ROOT / "models"


def load_data() -> pd.DataFrame:
    p = DATA_DIR / "prophet.csv"
    if not p.exists():
        print(f"[WARN] {p} absent — génération…")
        import subprocess
        subprocess.run([sys.executable,
                        str(Path(__file__).parent / "generate_synthetic_data.py")],
                       check=True)
    df = pd.read_csv(p, parse_dates=["ds"])
    df["y"] = df["y"].clip(lower=0.0)
    return df


def evaluate_cv(model, horizon: str = "7 days", period: str = "14 days") -> dict:
    """Cross-validation Prophet sur les 60 derniers jours."""
    try:
        from prophet.diagnostics import cross_validation, performance_metrics
        df_cv = cross_validation(model, horizon=horizon, period=period, parallel=None)
        pm = performance_metrics(df_cv, rolling_window=1)
        return {
            "rmse": float(pm["rmse"].mean()),
            "mae":  float(pm["mae"].mean()),
        }
    except Exception as exc:
        print(f"  [WARN] CV échoué : {exc}")
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--changepoint-prior",  type=float, default=0.05)
    parser.add_argument("--seasonality-prior",  type=float, default=10.0)
    parser.add_argument("--skip-cv",            action="store_true")
    args = parser.parse_args()

    print("=== Entraînement Prophet — PM2.5 ===")

    try:
        from prophet import Prophet
    except ImportError:
        print("[ERREUR] Prophet non installé. Lancez : pip install prophet")
        sys.exit(1)

    df = load_data()
    print(f"  {len(df)} heures de données chargées")

    split = int(len(df) * 0.85)
    df_train, df_test = df.iloc[:split], df.iloc[split:]

    model = Prophet(
        changepoint_prior_scale=args.changepoint_prior,
        seasonality_prior_scale=args.seasonality_prior,
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=True,
    )
    # Saisonnalité harmattan (novembre–février)
    model.add_seasonality(name="harmattan", period=365.25, fourier_order=5)
    model.fit(df_train)

    # Évaluation sur le jeu de test
    future = model.make_future_dataframe(periods=len(df_test), freq="h")
    forecast = model.predict(future)
    y_pred = forecast.iloc[-len(df_test):]["yhat"].values
    y_true = df_test["y"].values
    rmse = float(np.sqrt(np.mean((y_pred - y_true) ** 2)))
    mae  = float(np.mean(np.abs(y_pred - y_true)))
    print(f"  Test RMSE={rmse:.2f}  MAE={mae:.2f}")

    metrics = {"rmse": rmse, "mae": mae}
    if not args.skip_cv:
        print("  Cross-validation…")
        cv_metrics = evaluate_cv(model)
        metrics.update({f"cv_{k}": v for k, v in cv_metrics.items()})
        if cv_metrics:
            print(f"  CV RMSE={cv_metrics.get('rmse', '?'):.2f}  MAE={cv_metrics.get('mae', '?'):.2f}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    out_model = MODELS_DIR / "prophet_pm25.pkl"
    out_meta  = MODELS_DIR / "prophet_pm25_meta.json"
    joblib.dump(model, out_model)
    out_meta.write_text(json.dumps(metrics))
    print(f"  Sauvegardé : {out_model}")

    from training.registry import register_model
    register_model("prophet_pm25", "Prophet", version="1.0",
                   metrics=metrics, file_path=str(out_model))


if __name__ == "__main__":
    main()
