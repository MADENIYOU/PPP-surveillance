#!/usr/bin/env python3
"""Entraîne les modèles LSTM (full 57 features + light 20 features).

Entrée  : training/data/lstm.csv
Sorties : ../models/lstm_full.pt
          ../models/lstm_light.pt
          ../models/feature_scaler.pkl
          ../models/feature_cols.json

Pré-requis : pip install torch  (cf. requirements_training.txt)
Usage :
  python train_lstm.py
  python train_lstm.py --epochs 30 --batch-size 64
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

from models_def import LSTMPollution, LSTMLightPollution, LSTM_LIGHT_FEATURES  # noqa: E402

TARGETS = ["target_h1", "target_h6", "target_h24"]


# ─── Chargement des données ────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    p = DATA_DIR / "lstm.csv"
    if not p.exists():
        print(f"[WARN] {p} absent — génération…")
        import subprocess
        subprocess.run([sys.executable,
                        str(Path(__file__).parent / "generate_synthetic_data.py")],
                       check=True)
    return pd.read_csv(p, parse_dates=["timestamp"])


def split_features(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    exclude = {"timestamp"} | set(TARGETS)
    all_feat = [c for c in df.columns if c not in exclude]
    light_feat = [c for c in LSTM_LIGHT_FEATURES if c in all_feat]
    return all_feat, light_feat


# ─── Construction des séquences ───────────────────────────────────────────────

def make_sequences(X: np.ndarray, y: np.ndarray,
                   seq_len: int, step: int = 6) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = [], []
    for i in range(seq_len, len(X) - 1, step):
        xs.append(X[i - seq_len: i])
        ys.append(y[i])
    return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32)


# ─── Boucle d'entraînement ────────────────────────────────────────────────────

def train_model(model, X_train: np.ndarray, y_train: np.ndarray,
                X_val: np.ndarray, y_val: np.ndarray,
                epochs: int, batch_size: int, lr: float, tag: str) -> dict:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  {tag} — device={device}  params={sum(p.numel() for p in model.parameters()):,}")
    model.to(device)

    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=3, factor=0.5, verbose=False)

    ds_train = TensorDataset(torch.FloatTensor(X_train), torch.FloatTensor(y_train))
    ds_val   = TensorDataset(torch.FloatTensor(X_val),   torch.FloatTensor(y_val))
    dl_train = DataLoader(ds_train, batch_size=batch_size, shuffle=True, drop_last=True)
    dl_val   = DataLoader(ds_val,   batch_size=batch_size)

    best_val_loss = float("inf")
    best_state    = None
    patience_cnt  = 0
    history: list[dict] = []

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        for xb, yb in dl_train:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * len(xb)
        train_loss /= len(ds_train)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in dl_val:
                xb, yb = xb.to(device), yb.to(device)
                val_loss += criterion(model(xb), yb).item() * len(xb)
        val_loss /= max(len(ds_val), 1)

        scheduler.step(val_loss)
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state    = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_cnt  = 0
        else:
            patience_cnt += 1

        if epoch % 5 == 0 or epoch == epochs:
            rmse = np.sqrt(val_loss)
            print(f"  epoch {epoch:3d}/{epochs}  train_loss={train_loss:.4f}  val_RMSE={rmse:.4f}")
        history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss})

        if patience_cnt >= 8:
            print(f"  Early stop à epoch {epoch}")
            break

    if best_state:
        model.load_state_dict(best_state)
    model.to("cpu")
    return {"best_val_rmse": float(np.sqrt(best_val_loss)), "history": history}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import torch
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs",     type=int,   default=20)
    parser.add_argument("--batch-size", type=int,   default=32)
    parser.add_argument("--lr",         type=float, default=1e-3)
    args = parser.parse_args()

    print("=== Entraînement LSTM (full + light) ===")
    df = load_data()
    print(f"  {len(df)} pas de temps chargés")

    all_feat, light_feat = split_features(df)
    y = df[TARGETS].values

    # Scaler sur toutes les features (utilisé par LSTM full)
    scaler = StandardScaler()
    X_all   = scaler.fit_transform(df[all_feat].fillna(0).values).astype(np.float32)

    scaler_light = StandardScaler()
    X_light = scaler_light.fit_transform(df[light_feat].fillna(0).values).astype(np.float32)

    # Séquences
    seq_full  = LSTMPollution.SEQ_LEN
    seq_light = LSTMLightPollution.SEQ_LEN
    Xs_full,  ys_full  = make_sequences(X_all,   y, seq_full)
    Xs_light, ys_light = make_sequences(X_light, y, seq_light)

    print(f"  LSTM-full  : {Xs_full.shape}  — {len(all_feat)} features")
    print(f"  LSTM-light : {Xs_light.shape} — {len(light_feat)} features")

    split = int(len(Xs_full) * 0.85)
    Xf_tr, Xf_va = Xs_full[:split],  Xs_full[split:]
    Xl_tr, Xl_va = Xs_light[:split], Xs_light[split:]
    yf_tr, yf_va = ys_full[:split],  ys_full[split:]

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # ── LSTM full ──────────────────────────────────────────────────────────────
    model_full = LSTMPollution(n_features=len(all_feat))
    metrics_full = train_model(model_full, Xf_tr, yf_tr, Xf_va, yf_va,
                                args.epochs, args.batch_size, args.lr, "LSTM-full")
    torch.save(model_full, MODELS_DIR / "lstm_full.pt")
    joblib.dump(scaler, MODELS_DIR / "feature_scaler.pkl")
    (MODELS_DIR / "feature_cols.json").write_text(json.dumps(all_feat))
    print(f"  LSTM-full   sauvegardé — val_RMSE={metrics_full['best_val_rmse']:.3f}")

    # ── LSTM light ─────────────────────────────────────────────────────────────
    model_light = LSTMLightPollution(n_features=len(light_feat))
    yl_tr, yl_va = ys_light[:split], ys_light[split:]
    metrics_light = train_model(model_light, Xl_tr, yl_tr, Xl_va, yl_va,
                                 args.epochs, args.batch_size, args.lr, "LSTM-light")
    torch.save(model_light, MODELS_DIR / "lstm_light.pt")
    joblib.dump(scaler_light, MODELS_DIR / "feature_scaler_light.pkl")
    (MODELS_DIR / "feature_cols_light.json").write_text(json.dumps(light_feat))
    print(f"  LSTM-light  sauvegardé — val_RMSE={metrics_light['best_val_rmse']:.3f}")

    # Résumé métriques
    summary = {
        "lstm_full":  metrics_full,
        "lstm_light": metrics_light,
        "n_features_full":  len(all_feat),
        "n_features_light": len(light_feat),
    }
    (MODELS_DIR / "lstm_training_summary.json").write_text(json.dumps(summary, indent=2))
    print("Terminé.")


if __name__ == "__main__":
    main()
