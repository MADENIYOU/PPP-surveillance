"""Architecture PyTorch des modèles de prédiction — partagée entre training et inférence.

torch.load(weights_only=False) utilise pickle et doit retrouver cette classe à l'import.
PYTHONPATH doit inclure le répertoire parent de models_def/ (= pipeline/).
"""
from __future__ import annotations

import torch
import torch.nn as nn

# 20 features utilisées par LSTM-light — sous-ensemble de F01-F57
# Doit rester synchronisé avec train_lstm.py et flows/predictions.py
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
            dropout=dropout,      # appliqué entre couches (n_layers > 1)
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
