#!/usr/bin/env python3
"""Master script — entraîne tous les modèles dans l'ordre correct.

Ordre :
  1. Génération des données synthétiques
  2. Téléchargement datasets publics (OpenAQ + UCI) — optionnel
  3. Calibration RF        → models/calibration_rf_pm25.pkl
  4. Isolation Forest      → models/anomaly_if.pkl
  5. LSTM full + light     → models/lstm_*.pt + feature_scaler.pkl
  6. Prophet               → models/prophet_pm25.pkl

Usage :
  python train_all.py                    # tout entraîner (avec téléchargement)
  python train_all.py --no-download      # sauter le téléchargement
  python train_all.py --skip lstm        # sauter l'entraînement LSTM
  python train_all.py --skip prophet     # sauter Prophet (lourd)
  python train_all.py --epochs 10        # raccourcir pour test rapide
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

TRAINING_DIR = Path(__file__).parent


def run(script: str, extra_args: list[str]) -> bool:
    path = TRAINING_DIR / script
    cmd  = [sys.executable, str(path)] + extra_args
    print(f"\n{'='*60}")
    print(f"  {script}")
    print(f"{'='*60}")
    t0 = time.time()
    result = subprocess.run(cmd)
    elapsed = time.time() - t0
    ok = result.returncode == 0
    status = "OK" if ok else f"ECHEC (code {result.returncode})"
    print(f"  → {status} ({elapsed:.1f}s)")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip",        nargs="*", default=[],
                        choices=["data", "download", "calibration", "anomaly", "lstm", "prophet"],
                        help="Modules à sauter")
    parser.add_argument("--no-download", action="store_true",
                        help="Alias de --skip download")
    parser.add_argument("--days",        type=int,   default=60,  help="Jours de données synthétiques")
    parser.add_argument("--epochs",      type=int,   default=20,  help="Epochs LSTM")
    parser.add_argument("--batch-size",  type=int,   default=32)
    parser.add_argument("--skip-cv",     action="store_true",     help="Sauter la CV Prophet")
    args = parser.parse_args()

    skip = set(args.skip or [])
    if args.no_download:
        skip.add("download")
    results = {}

    # 1. Génération des données synthétiques
    if "data" not in skip:
        results["data"] = run("generate_synthetic_data.py", ["--days", str(args.days)])

    # 2. Téléchargement datasets publics (OpenAQ + UCI)
    if "download" not in skip:
        results["download"] = run("download_datasets.py", [])

    # 2. Calibration RF
    if "calibration" not in skip:
        results["calibration"] = run("train_calibration.py", [])

    # 3. Isolation Forest
    if "anomaly" not in skip:
        results["anomaly"] = run("train_anomaly.py", [])

    # 4. LSTM
    if "lstm" not in skip:
        results["lstm"] = run("train_lstm.py",
                              ["--epochs", str(args.epochs), "--batch-size", str(args.batch_size)])

    # 5. Prophet
    if "prophet" not in skip:
        extra = ["--skip-cv"] if args.skip_cv else []
        results["prophet"] = run("train_prophet.py", extra)

    print(f"\n{'='*60}")
    print("  RÉSUMÉ")
    print(f"{'='*60}")
    all_ok = True
    for name, ok in results.items():
        icon = "✓" if ok else "✗"
        print(f"  {icon} {name}")
        if not ok:
            all_ok = False
    print()

    if not all_ok:
        print("  Certains modèles n'ont pas pu être entraînés.")
        print("  Le pipeline fonctionnera en mode dégradé (fallbacks actifs).")
        sys.exit(1)
    else:
        print("  Tous les modèles sont entraînés — pipeline prêt.")


if __name__ == "__main__":
    main()
