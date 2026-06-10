#!/usr/bin/env python3
"""Télécharge et normalise les datasets publics pour l'entraînement.

Sources :
  1. OpenAQ v3 API — mesures PM2.5/PM10/NO2/O3/CO pour le Sénégal et
     les villes d'Afrique de l'Ouest proches (Dakar, Abidjan, Accra, Lagos).
     URL de base : https://api.openaq.org/v3  (pas d'auth pour ~1000 req/jour)

  2. UCI Air Quality Dataset (Italie, 2004-2005) — paires capteur/référence
     utiles pour apprendre le biais de calibration capteur électrochimique.
     URL : https://archive.ics.uci.edu/ml/machine-learning-databases/00360/AirQualityUCI.zip

  3. EPA AQS (États-Unis, EPA) — données PM2.5 horaires de grande qualité
     utilisées pour le pré-entraînement du LSTM (transfert de domaine).
     Format : CSV annuel pré-téléchargé via l'API AQS.

Sorties dans training/data/external/ :
  openaq_west_africa.csv    colonnes : timestamp, city, parameter, value, unit
  uci_calibration.csv       colonnes : timestamp, co_sensor, co_ref, no2_sensor, no2_ref, temperature, humidity
  merged_calibration.csv    fusion synthétique + UCI + OpenAQ
  merged_lstm.csv           fusion synthétique + OpenAQ pour LSTM

Usage :
  python download_datasets.py
  python download_datasets.py --no-openaq   # sauter OpenAQ (hors ligne)
  python download_datasets.py --days 180    # OpenAQ : 180 derniers jours
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("download_datasets")

DATA_DIR = Path(__file__).parent / "data"
EXT_DIR  = DATA_DIR / "external"

OPENAQ_BASE    = "https://api.openaq.org/v3"
UCI_ZIP_URL    = "https://archive.ics.uci.edu/ml/machine-learning-databases/00360/AirQualityUCI.zip"
OPENAQ_TIMEOUT = 20
MAX_RETRIES    = 3

WEST_AFRICA_COUNTRIES = ["SN", "CI", "GH", "NG", "ML", "MR"]   # codes ISO-2
PARAMETERS = ["pm25", "pm10", "no2", "o3", "co"]


# ============================================================================
# Helpers HTTP
# ============================================================================
def _get_json(url: str, params: dict | None = None, retry: int = 0) -> dict | None:
    try:
        r = requests.get(url, params=params, timeout=OPENAQ_TIMEOUT,
                         headers={"User-Agent": "dakar-pipeline/1.0"})
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        if retry < MAX_RETRIES:
            time.sleep(2 ** retry)
            return _get_json(url, params, retry + 1)
        LOGGER.warning("request_failed url=%s error=%s", url, exc)
        return None


def _get_bytes(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        return r.content
    except requests.RequestException as exc:
        LOGGER.warning("download_failed url=%s error=%s", url, exc)
        return None


# ============================================================================
# 1. OpenAQ v3
# ============================================================================
def _fetch_openaq_locations(country_iso2: str) -> list[dict]:
    data = _get_json(f"{OPENAQ_BASE}/locations",
                     {"country_id": country_iso2, "limit": 100})
    if not data:
        return []
    return data.get("results", [])


def _fetch_openaq_measurements(location_id: int, parameter: str,
                                date_from: str, date_to: str) -> list[dict]:
    """Lit toutes les pages (max 500 rés./page)."""
    records = []
    page = 1
    while True:
        data = _get_json(
            f"{OPENAQ_BASE}/measurements",
            {
                "locations_id": location_id,
                "parameter": parameter,
                "date_from": date_from,
                "date_to":   date_to,
                "limit": 500,
                "page":  page,
            },
        )
        if not data or not data.get("results"):
            break
        records.extend(data["results"])
        meta = data.get("meta", {})
        if len(records) >= meta.get("found", 0):
            break
        page += 1
        time.sleep(0.3)   # politesse API
    return records


def download_openaq(days: int) -> pd.DataFrame:
    LOGGER.info("OpenAQ — téléchargement (%d derniers jours, %d pays)…",
                days, len(WEST_AFRICA_COUNTRIES))
    now  = datetime.now(timezone.utc)
    d_to = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    d_fr = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = []
    for country in WEST_AFRICA_COUNTRIES:
        locations = _fetch_openaq_locations(country)
        LOGGER.info("  %s : %d stations trouvées", country, len(locations))
        for loc in locations[:15]:   # max 15 stations par pays
            loc_id   = loc.get("id")
            city     = loc.get("city") or loc.get("name", "unknown")
            lat      = loc.get("coordinates", {}).get("latitude")
            lon      = loc.get("coordinates", {}).get("longitude")
            for param in PARAMETERS:
                meas = _fetch_openaq_measurements(loc_id, param, d_fr, d_to)
                for m in meas:
                    rows.append({
                        "timestamp": m.get("date", {}).get("utc"),
                        "country":   country,
                        "city":      city,
                        "lat":       lat,
                        "lon":       lon,
                        "parameter": param,
                        "value":     m.get("value"),
                        "unit":      m.get("unit"),
                    })
            time.sleep(0.2)

    if not rows:
        LOGGER.warning("OpenAQ : aucune donnée récupérée")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.dropna(subset=["value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[df["value"] >= 0]
    LOGGER.info("  OpenAQ : %d mesures téléchargées", len(df))
    return df


def openaq_to_training(df: pd.DataFrame) -> pd.DataFrame:
    """Pivote OpenAQ (long) → format large (une ligne par horodatage × ville)."""
    if df.empty:
        return pd.DataFrame()
    pivot = (df.pivot_table(index=["timestamp", "city", "lat", "lon"],
                             columns="parameter", values="value", aggfunc="mean")
               .reset_index())
    pivot.columns.name = None
    # Uniformise les noms de colonnes
    rename = {"pm25": "pm25", "pm10": "pm10", "no2": "no2", "o3": "o3", "co": "co"}
    pivot = pivot.rename(columns=rename)
    return pivot


# ============================================================================
# 2. UCI Air Quality Dataset
# ============================================================================
def download_uci() -> pd.DataFrame:
    LOGGER.info("UCI Air Quality Dataset — téléchargement…")
    raw = _get_bytes(UCI_ZIP_URL)
    if not raw:
        return pd.DataFrame()

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".csv") or n.endswith(".xlsx"))
        with zf.open(name) as f:
            content = f.read().decode("latin-1")

    # UCI utilise ';' comme séparateur et ',' comme décimale (locale italienne)
    df = pd.read_csv(io.StringIO(content), sep=";", decimal=",", na_values=[-200])
    df = df.dropna(how="all", axis=1)   # supprime les colonnes vides en fin de fichier

    # Nommage attendu dans UCI : Date, Time, CO(GT), PT08.S1(CO), NO2(GT), PT08.S4(NO2), T, RH
    col_map = {
        "CO(GT)":       "co_ref",          # CO référence µg/m³ (converti en ppm : /1.1646)
        "PT08.S1(CO)":  "co_sensor",       # résistance capteur CO
        "NO2(GT)":      "no2_ref",         # NO2 référence µg/m³
        "PT08.S4(NO2)": "no2_sensor",
        "T":            "temperature",
        "RH":           "humidity",
    }
    df = df.rename(columns=col_map)
    available = [c for c in col_map.values() if c in df.columns]

    # Parse datetime
    if "Date" in df.columns and "Time" in df.columns:
        df["timestamp"] = pd.to_datetime(
            df["Date"].astype(str) + " " + df["Time"].astype(str),
            format="%d/%m/%Y %H.%M.%S", errors="coerce"
        )
    else:
        df["timestamp"] = pd.NaT

    df = df[["timestamp"] + available].dropna()

    # Conversion co_ref mg/m³ → ppm (densité CO à 20°C ≈ 1.1646 mg/L = 1164.6 µg/m³/ppm)
    if "co_ref" in df.columns:
        df["co_ref"] = df["co_ref"] / 1164.6

    LOGGER.info("  UCI : %d observations chargées", len(df))
    return df


# ============================================================================
# 3. Fusion avec données synthétiques existantes
# ============================================================================
def merge_calibration(uci: pd.DataFrame, openaq_wide: pd.DataFrame) -> pd.DataFrame:
    """Fusionne UCI + OpenAQ pour enrichir calibration.csv."""
    frames = []

    # UCI → paires (capteur, référence) pour CO
    if not uci.empty and "co_sensor" in uci.columns and "co_ref" in uci.columns:
        co_pairs = uci[["timestamp", "co_sensor", "co_ref",
                         "temperature", "humidity"]].copy()
        co_pairs["source"] = "uci"
        frames.append(co_pairs.rename(columns={"co_sensor": "pm25_raw",
                                                 "co_ref":    "pm25_true"}))

    # OpenAQ Dakar — utilise le biais inter-stations comme proxy de calibration
    if not openaq_wide.empty and "pm25" in openaq_wide.columns:
        dakar = openaq_wide[openaq_wide["city"].str.contains("Dakar", case=False, na=False)]
        if not dakar.empty:
            dakar_g = dakar.set_index("timestamp")["pm25"].resample("1h").mean()
            # Simule une paire capteur/référence avec bruit artificiel
            rng = np.random.default_rng(1234)
            pm_ref = dakar_g.values
            pm_raw = np.clip(pm_ref * rng.uniform(0.80, 1.20, len(pm_ref))
                             + rng.normal(0, 2, len(pm_ref)), 0, None)
            aq_pairs = pd.DataFrame({
                "timestamp": dakar_g.index,
                "pm25_raw":  pm_raw,
                "pm25_true": pm_ref,
                "temperature": np.nan,
                "humidity":    np.nan,
                "source": "openaq_dakar",
            })
            frames.append(aq_pairs.dropna(subset=["pm25_true"]))

    # Charge la base synthétique si elle existe
    synth_p = DATA_DIR / "calibration.csv"
    if synth_p.exists():
        synth = pd.read_csv(synth_p)
        synth["source"] = "synthetic"
        frames.append(synth)

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    merged["hour"] = pd.to_datetime(merged["timestamp"]).dt.hour.fillna(12)
    merged["pressure"] = merged.get("pressure", pd.Series(1013.0, index=merged.index))
    return merged[["timestamp", "pm25_raw", "pm25_true",
                    "temperature", "humidity", "pressure", "hour", "source"]].dropna(
        subset=["pm25_raw", "pm25_true"])


def merge_lstm(openaq_wide: pd.DataFrame) -> pd.DataFrame:
    """Enrichit lstm.csv avec données OpenAQ réelles."""
    synth_p = DATA_DIR / "lstm.csv"
    frames = []
    if synth_p.exists():
        frames.append(pd.read_csv(synth_p))

    if not openaq_wide.empty:
        # On conserve uniquement les colonnes compatibles avec les features LSTM
        keep = ["timestamp", "pm25", "pm10", "no2", "o3", "co"]
        aq = openaq_wide[[c for c in keep if c in openaq_wide.columns]].copy()
        aq = aq.rename(columns={"pm25": "pm25_true"})
        # Les features dérivées (lags, rolling…) seront recalculées au moment de l'entraînement
        frames.append(aq)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-openaq", action="store_true")
    parser.add_argument("--no-uci",    action="store_true")
    parser.add_argument("--days",      type=int, default=90)
    args = parser.parse_args()

    EXT_DIR.mkdir(parents=True, exist_ok=True)

    openaq_wide = pd.DataFrame()
    if not args.no_openaq:
        openaq_raw = download_openaq(args.days)
        if not openaq_raw.empty:
            openaq_raw.to_csv(EXT_DIR / "openaq_west_africa.csv", index=False)
            LOGGER.info("Sauvegardé : openaq_west_africa.csv")
            openaq_wide = openaq_to_training(openaq_raw)

    uci = pd.DataFrame()
    if not args.no_uci:
        uci = download_uci()
        if not uci.empty:
            uci.to_csv(EXT_DIR / "uci_calibration.csv", index=False)
            LOGGER.info("Sauvegardé : uci_calibration.csv")

    cal = merge_calibration(uci, openaq_wide)
    if not cal.empty:
        cal.to_csv(EXT_DIR / "merged_calibration.csv", index=False)
        LOGGER.info("merged_calibration.csv : %d lignes", len(cal))

    lstm_df = merge_lstm(openaq_wide)
    if not lstm_df.empty:
        lstm_df.to_csv(EXT_DIR / "merged_lstm.csv", index=False)
        LOGGER.info("merged_lstm.csv : %d lignes", len(lstm_df))

    LOGGER.info("Téléchargement terminé.")


if __name__ == "__main__":
    main()
