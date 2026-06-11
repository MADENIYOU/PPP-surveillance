"""Architecture PyTorch des modèles de prédiction — partagée entre training et inférence.

torch.load(weights_only=True) est privilégié (sécurité, pas d'exécution de pickle).
Le helper safe_load_model() gère les deux formats :
  - Format récent : state_dict sauvegardé avec torch.save(model.state_dict(), path)
  - Format legacy : modèle complet pickle (nécessite weights_only=False)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn

LOGGER = logging.getLogger("models_def")

# 20 features utilisées par LSTM-light — sous-ensemble de F01-F57
LSTM_LIGHT_FEATURES = [
    "pm25_lag_1", "pm25_lag_2", "pm25_lag_3", "pm25_lag_6", "pm25_lag_12",
    "pm25_rolling_mean_1h", "pm25_rolling_std_1h", "pm25_rolling_mean_3h",
    "pm10_lag_1", "co_lag_1", "no2_lag_1", "o3_lag_1",
    "temperature", "humidity", "wind_speed",
    "traffic_index",
    "hour_sin", "hour_cos", "day_of_week_sin", "day_of_week_cos",
]


class LSTMPollution(nn.Module):
    """LSTM full — 57 features × 288 timesteps (24h à 5 min), 2 couches LSTM."""

    N_FEATURES = 57
    SEQ_LEN    = 288   # 24h × 12 pas/h

    def __init__(self, n_features: int = 57, hidden_size: int = 128,
                 n_layers: int = 2, dropout: float = 0.3):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=n_layers,
            dropout=dropout,
            batch_first=True,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, 3)   # sorties : [h1, h6, h24]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.fc(self.dropout(out[:, -1, :]))


class LSTMLightPollution(nn.Module):
    """LSTM léger — 20 features × 48 timesteps (4h à 5 min), 1 couche LSTM."""

    N_FEATURES = 20
    SEQ_LEN    = 48    # 4h × 12 pas/h

    def __init__(self, n_features: int = 20, hidden_size: int = 64,
                 dropout: float = 0.3):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, 3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.fc(self.dropout(out[:, -1, :]))


def safe_load_model(
    model_path: str | Path,
    model_tag: str,
    n_features: int = 57,
    device: str = "cpu",
) -> Optional[nn.Module]:
    """Charge un modèle LSTM de manière sécurisée.

    Essaie d'abord de charger en format state_dict (weights_only=True),
    puis retombe sur le format legacy pickle complet si nécessaire.
    Le model_tag détermine la classe : "lstm_full" → LSTMPollution, "lstm_light" → LSTMLightPollution.
    """
    model_path = Path(model_path)
    if not model_path.exists():
        return None

    MODEL_CLASSES = {
        "lstm_full": LSTMPollution,
        "lstm_light": LSTMLightPollution,
    }
    model_cls = MODEL_CLASSES.get(model_tag, LSTMPollution)
    model = model_cls(n_features=n_features)

    try:
        # Essai 1 : state_dict (format recommandé, weights_only=True)
        state_dict = torch.load(model_path, weights_only=True, map_location=device)
        model.load_state_dict(state_dict)
        LOGGER.debug("model_loaded_state_dict model=%s features=%d", model_tag, n_features)
        return model
    except Exception as exc1:
        LOGGER.debug("state_dict_load_failed model=%s error=%s — trying pickle format", model_tag, exc1)
        try:
            # Essai 2 : format legacy pickle complet
            model = torch.load(model_path, weights_only=False, map_location=device)
            LOGGER.debug("model_loaded_pickle model=%s", model_tag)
            return model
        except Exception as exc2:
            LOGGER.warning("model_load_failed model=%s error=%s", model_tag, exc2)
            return None


def save_model_state(model: nn.Module, model_path: str | Path, model_tag: str, n_features: int) -> None:
    """Sauvegarde le modèle au format state_dict + métadonnées JSON."""
    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)

    # Sauvegarde state_dict (compatible weights_only=True)
    torch.save(model.state_dict(), model_path)

    # Métadonnées pour le rechargement
    meta_path = model_path.with_suffix(".meta.json")
    meta = {"model_tag": model_tag, "n_features": n_features, "format": "state_dict"}
    meta_path.write_text(json.dumps(meta))

    LOGGER.info("model_saved model=%s features=%d path=%s", model_tag, n_features, model_path)
