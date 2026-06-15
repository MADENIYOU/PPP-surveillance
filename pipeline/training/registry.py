#!/usr/bin/env python3
"""Enregistrement des modèles entraînés dans la table PostgreSQL `models`.

Chaque script d'entraînement appelle register_model() après sauvegarde du .pkl/.pt,
pour que le registre (et la page Modèles du dashboard) reflète les modèles réels.
Tolérant : si la base est indisponible (entraînement hors conteneur), on logge et
on continue sans planter l'entraînement.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

LOGGER = logging.getLogger("training.registry")

# Types valides de l'enum SQL model_type
VALID_TYPES = {"LSTM", "GRU", "Prophet", "GCN", "RandomForest",
               "AutoEncoder", "IsolationForest", "GaussianProcess"}


def register_model(name: str, model_type: str, version: str = "1.0",
                   metrics: Optional[dict] = None, file_path: Optional[str] = None,
                   hyperparams: Optional[dict] = None,
                   training_start: Optional[datetime] = None,
                   training_end: Optional[datetime] = None,
                   activate: bool = True) -> None:
    if model_type not in VALID_TYPES:
        LOGGER.warning("register_model: type invalide %s — ignoré", model_type)
        return
    try:
        from db.postgres_client import PostgresPool
    except Exception as exc:  # module DB indisponible
        LOGGER.warning("register_model: DB indisponible (%s) — skip", exc)
        return

    te = training_end or datetime.now(timezone.utc)
    try:
        pool = PostgresPool()
        with pool.cursor() as cur:
            if activate:
                # Un seul modèle actif par type
                cur.execute("UPDATE models SET is_active = false WHERE type = %s", (model_type,))
            cur.execute("""
                INSERT INTO models (name, type, version, metrics, hyperparams, file_path,
                                    training_start, training_end, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name, version) DO UPDATE SET
                    type = EXCLUDED.type, metrics = EXCLUDED.metrics,
                    hyperparams = EXCLUDED.hyperparams, file_path = EXCLUDED.file_path,
                    training_end = EXCLUDED.training_end, is_active = EXCLUDED.is_active
            """, (name, model_type, version, json.dumps(metrics or {}),
                  json.dumps(hyperparams or {}), file_path, training_start, te, activate))
        pool.closeall()
        LOGGER.info("model_registered name=%s type=%s version=%s", name, model_type, version)
    except Exception as exc:
        LOGGER.warning("register_model failed name=%s error=%s", name, exc)
