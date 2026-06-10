#!/usr/bin/env python3
"""Génère les jeux de données synthétiques d'entraînement.

Produit 4 fichiers CSV dans training/data/ :
  calibration.csv — paires (raw, true) PM2.5 avec covariables
  anomaly.csv     — observations "normales" multipolluants
  lstm.csv        — série temporelle 5-min avec 57 features + cibles
  prophet.csv     — série horaire PM2.5 (colonnes ds, y)

Usage : python generate_synthetic_data.py [--days 60] [--seed 42]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).parent / "data"


def _hour_series(timestamps: pd.DatetimeIndex) -> np.ndarray:
    return timestamps.hour + timestamps.minute / 60.0


def generate_base_series(n_days: int = 60, freq_min: int = 5, seed: int = 42) -> pd.DataFrame:
    """Série temporelle de base : pollutants + météo à `freq_min` min de résolution."""
    rng = np.random.default_rng(seed)
    n = n_days * 24 * 60 // freq_min
    ts = pd.date_range("2024-01-01", periods=n, freq=f"{freq_min}min", tz="UTC")
    hour = _hour_series(ts)

    # ── PM2.5 ──────────────────────────────────────────────────────────────────
    diurnal_pm25 = (
        12 * np.sin(2 * np.pi * (hour - 4) / 24)
        + 8  * np.sin(4 * np.pi * (hour - 7) / 24)   # double pic matin/soir
    )
    weekly = 6.0 * (ts.dayofweek < 5).astype(float)   # semaine vs weekend
    # Harmattan : pic autour du 15 janvier (jour 15 de l'année)
    doy = ts.dayofyear.to_numpy()
    harmattan = 18 * np.exp(-((doy - 15) ** 2) / (2 * 25 ** 2))
    pm25_true = np.clip(35 + diurnal_pm25 + weekly + harmattan
                        + rng.normal(0, 3, n), 2.0, 280.0)

    # ── PM10 (≈ 1.6 × PM2.5 + bruit) ──────────────────────────────────────────
    pm10 = np.clip(pm25_true * 1.6 + rng.normal(0, 5, n), 5.0, 450.0)

    # ── CO (corrélé trafic) ────────────────────────────────────────────────────
    traffic = np.clip(0.3 + 0.5 * np.maximum(0,
        np.sin(2 * np.pi * (hour - 8) / 3) * (hour > 6) * (hour < 11)
        + np.sin(2 * np.pi * (hour - 17) / 3) * (hour > 15) * (hour < 21)
    ), 0, 1)
    co = np.clip(0.3 + 0.6 * traffic + rng.normal(0, 0.05, n), 0.05, 5.0)

    # ── NO2 ────────────────────────────────────────────────────────────────────
    no2 = np.clip(20 + 40 * traffic + rng.normal(0, 5, n), 2.0, 200.0)

    # ── O3 (anti-corrélé NO2, pic après-midi) ─────────────────────────────────
    o3_diurnal = 30 * np.maximum(0, np.sin(2 * np.pi * (hour - 6) / 24))
    o3 = np.clip(40 + o3_diurnal - 0.3 * no2 + rng.normal(0, 4, n), 5.0, 120.0)

    # ── Météo ──────────────────────────────────────────────────────────────────
    temperature = np.clip(28 + 6 * np.sin(2 * np.pi * (hour - 6) / 24)
                          + rng.normal(0, 1.5, n), 18.0, 45.0)
    humidity    = np.clip(68 - 20 * np.sin(2 * np.pi * (hour - 14) / 24)
                          + rng.normal(0, 5, n), 20.0, 98.0)
    pressure    = np.clip(1013 + rng.normal(0, 2, n), 1000.0, 1030.0)
    wind_speed  = np.clip(rng.exponential(3, n), 0, 25.0)

    return pd.DataFrame({
        "timestamp":    ts,
        "pm25_true":    pm25_true,
        "pm10":         pm10,
        "co":           co,
        "no2":          no2,
        "o3":           o3,
        "temperature":  temperature,
        "humidity":     humidity,
        "pressure":     pressure,
        "wind_speed":   wind_speed,
        "traffic_index": traffic,
    })


def make_calibration_csv(df: pd.DataFrame, seed: int, out_dir: Path) -> Path:
    """Génère des paires (pm25_raw, pm25_true) avec biais capteur aléatoire."""
    rng = np.random.default_rng(seed + 1)
    n = len(df)
    # Biais capteur : chaque capteur a un facteur et un offset propres
    n_sensors = 20
    factors  = rng.uniform(0.80, 1.20, n_sensors)
    offsets  = rng.uniform(-4.0, 4.0,  n_sensors)
    sensor_id = rng.integers(0, n_sensors, n)

    pm25_raw = np.clip(
        df["pm25_true"].values * factors[sensor_id]
        + offsets[sensor_id]
        + rng.normal(0, 1.5, n),
        0.0, 300.0,
    )
    out = df[["timestamp", "temperature", "humidity", "pressure"]].copy()
    out["pm25_raw"]  = pm25_raw
    out["pm25_true"] = df["pm25_true"].values
    out["hour"]      = out["timestamp"].dt.hour
    p = out_dir / "calibration.csv"
    out.to_csv(p, index=False)
    print(f"  calibration.csv  {len(out):>7} lignes → {p}")
    return p


def make_anomaly_csv(df: pd.DataFrame, seed: int, out_dir: Path) -> Path:
    """Observations normales multipolluants pour Isolation Forest."""
    out = df[["pm25_true", "pm10", "co", "no2", "o3",
              "temperature", "humidity", "pressure",
              "wind_speed", "traffic_index"]].copy()
    out.columns = ["pm25", "pm10", "co", "no2", "o3",
                   "temperature", "humidity", "pressure",
                   "wind_speed", "traffic_index"]
    p = out_dir / "anomaly.csv"
    out.to_csv(p, index=False)
    print(f"  anomaly.csv      {len(out):>7} lignes → {p}")
    return p


def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule les features LSTM (sous-ensemble des 57 F01-F57) depuis la série brute."""
    feat = pd.DataFrame(index=df.index)
    ts = df["timestamp"]
    hour = ts.dt.hour + ts.dt.minute / 60.0
    doy  = ts.dt.dayofyear
    dow  = ts.dt.dayofweek

    pm = df["pm25_true"]

    # Lags PM2.5 (F01-F12) — pas de 5 min, nommés en "unités de lag"
    for k in [1, 2, 3, 6, 12, 24, 36, 48, 72, 96, 144, 288]:
        feat[f"pm25_lag_{k}"] = pm.shift(k)

    # Rolling stats PM2.5 (F13-F24)
    feat["pm25_rolling_mean_1h"]  = pm.rolling(12).mean()
    feat["pm25_rolling_std_1h"]   = pm.rolling(12).std()
    feat["pm25_rolling_mean_3h"]  = pm.rolling(36).mean()
    feat["pm25_rolling_std_3h"]   = pm.rolling(36).std()
    feat["pm25_rolling_mean_6h"]  = pm.rolling(72).mean()
    feat["pm25_rolling_mean_12h"] = pm.rolling(144).mean()
    feat["pm25_rolling_mean_24h"] = pm.rolling(288).mean()
    feat["pm25_rolling_min_3h"]   = pm.rolling(36).min()
    feat["pm25_rolling_max_3h"]   = pm.rolling(36).max()
    feat["pm25_rolling_min_24h"]  = pm.rolling(288).min()
    feat["pm25_rolling_max_24h"]  = pm.rolling(288).max()
    feat["pm25_rolling_median_3h"] = pm.rolling(36).median()

    # Dérivées (F25-F28)
    feat["pm25_diff_1"]  = pm.diff(1)
    feat["pm25_diff_3"]  = pm.diff(3)
    feat["pm25_diff_12"] = pm.diff(12)
    feat["pm25_diff_24"] = pm.diff(24)

    # Variables cycliques (F29-F36)
    feat["hour_sin"]         = np.sin(2 * np.pi * hour / 24)
    feat["hour_cos"]         = np.cos(2 * np.pi * hour / 24)
    feat["day_of_week_sin"]  = np.sin(2 * np.pi * dow / 7)
    feat["day_of_week_cos"]  = np.cos(2 * np.pi * dow / 7)
    feat["day_of_year_sin"]  = np.sin(2 * np.pi * doy / 365)
    feat["day_of_year_cos"]  = np.cos(2 * np.pi * doy / 365)
    feat["week_of_year_sin"] = np.sin(2 * np.pi * ts.dt.isocalendar().week.astype(float) / 52)
    feat["week_of_year_cos"] = np.cos(2 * np.pi * ts.dt.isocalendar().week.astype(float) / 52)

    # Météo (F37-F44)
    feat["temperature"] = df["temperature"]
    feat["humidity"]    = df["humidity"]
    feat["pressure"]    = df["pressure"]
    feat["wind_speed"]  = df["wind_speed"]
    feat["temp_rolling_mean_3h"] = df["temperature"].rolling(36).mean()
    feat["humidity_rolling_mean_3h"] = df["humidity"].rolling(36).mean()
    feat["wind_rolling_mean_3h"] = df["wind_speed"].rolling(36).mean()
    feat["temp_x_humidity"] = df["temperature"] * df["humidity"] / 100

    # Trafic (F45-F47)
    feat["traffic_index"] = df["traffic_index"]
    feat["traffic_rolling_mean_1h"] = df["traffic_index"].rolling(12).mean()
    feat["traffic_rolling_mean_3h"] = df["traffic_index"].rolling(36).mean()

    # Autres polluants (F48-F57)
    for pol in ["pm10", "co", "no2", "o3"]:
        feat[f"{pol}_lag_1"] = df[pol].shift(1)
    feat["pm25_pm10_ratio"]  = pm / df["pm10"].replace(0, np.nan)
    feat["no2_o3_ratio"]     = df["no2"] / df["o3"].replace(0, np.nan)
    feat["pm25_co_ratio"]    = pm / df["co"].replace(0, np.nan)
    feat["pm25_no2_product"] = pm * df["no2"]
    feat["pm25_spatial_lag"] = pm.shift(6)   # proxy upwind (simplifié)
    feat["zone_elevation"]   = 12.0          # constante (Médina ≈ 12m)

    return feat


def make_lstm_csv(df: pd.DataFrame, out_dir: Path) -> Path:
    """Série 5-min avec 57 features + cibles (pm25 à +1h, +6h, +24h)."""
    feat = _compute_features(df)
    feat["target_h1"]  = df["pm25_true"].shift(-12)   # +1h  = 12 pas
    feat["target_h6"]  = df["pm25_true"].shift(-72)   # +6h  = 72 pas
    feat["target_h24"] = df["pm25_true"].shift(-288)  # +24h = 288 pas
    feat.insert(0, "timestamp", df["timestamp"])
    feat = feat.dropna()
    p = out_dir / "lstm.csv"
    feat.to_csv(p, index=False)
    print(f"  lstm.csv         {len(feat):>7} lignes, {feat.shape[1]} colonnes → {p}")
    return p


def make_prophet_csv(df: pd.DataFrame, out_dir: Path) -> Path:
    """Série horaire PM2.5 au format Prophet (ds, y)."""
    hourly = (df.set_index("timestamp")["pm25_true"]
               .resample("1h").mean()
               .reset_index()
               .rename(columns={"timestamp": "ds", "pm25_true": "y"}))
    hourly["ds"] = hourly["ds"].dt.tz_localize(None)   # Prophet n'accepte pas TZ
    p = out_dir / "prophet.csv"
    hourly.to_csv(p, index=False)
    print(f"  prophet.csv      {len(hourly):>7} lignes → {p}")
    return p


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Génération de {args.days} jours de données synthétiques (seed={args.seed})…")

    df = generate_base_series(args.days, seed=args.seed)
    make_calibration_csv(df, args.seed, OUTPUT_DIR)
    make_anomaly_csv(df, args.seed, OUTPUT_DIR)
    make_lstm_csv(df, OUTPUT_DIR)
    make_prophet_csv(df, OUTPUT_DIR)
    print("Terminé.")


if __name__ == "__main__":
    main()
