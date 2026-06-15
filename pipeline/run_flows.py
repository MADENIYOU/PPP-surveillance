#!/usr/bin/env python3
"""Ordonnanceur APScheduler pour les flows Prefect (sans serveur Prefect dédié).

Planification :
  - feature_engineering  : toutes les 5 minutes
  - predictions          : toutes les 30 minutes
  - kriging              : toutes les heures
  - nlp_pipeline         : toutes les heures (batch signalements en attente)
  - monitoring           : toutes les heures
  - retraining           : toutes les 6 heures (RF/IF/LSTM/Prophet si seuils dépassés)

Lancement : python run_flows.py  (démarré par docker-compose service pipeline-flows)

Les flows s'exécutent dans des threads séparés (non-blocking). Si un flow plante,
APScheduler log l'exception et planifie la prochaine exécution normalement.
"""
from __future__ import annotations

import logging
import os
import sys
import signal
import threading
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
LOGGER = logging.getLogger("run_flows")

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.executors.pool import ThreadPoolExecutor


def _run_feature_engineering():
    from flows.feature_engineering import run_feature_engineering
    try:
        run_feature_engineering()
    except Exception as exc:
        LOGGER.error("feature_engineering_failed error=%s", exc, exc_info=True)


def _run_predictions():
    from flows.predictions import run_predictions
    try:
        run_predictions()
    except Exception as exc:
        LOGGER.error("predictions_failed error=%s", exc, exc_info=True)


def _run_kriging():
    from flows.kriging import run_kriging
    try:
        run_kriging()
    except Exception as exc:
        LOGGER.error("kriging_failed error=%s", exc, exc_info=True)


def _run_nlp_pipeline():
    from flows.nlp_pipeline import process_citizen_reports
    try:
        process_citizen_reports()
    except Exception as exc:
        LOGGER.error("nlp_pipeline_failed error=%s", exc, exc_info=True)


def _run_monitoring():
    from flows.monitoring import run_monitoring
    try:
        run_monitoring()
    except Exception as exc:
        LOGGER.error("monitoring_failed error=%s", exc, exc_info=True)


def _run_retraining():
    from flows.retraining import run_retraining
    try:
        run_retraining()
    except Exception as exc:
        LOGGER.error("retraining_failed error=%s", exc, exc_info=True)


# Flows producteurs de données, dans l'ordre de dépendance (amont → aval).
# retraining est volontairement exclu : lourd, cadence 6h, pas requis pour peupler
# le dashboard au premier démarrage.
_BOOTSTRAP_SEQUENCE = [
    ("feature_engineering", _run_feature_engineering),
    ("predictions", _run_predictions),
    ("kriging", _run_kriging),
    ("nlp_pipeline", _run_nlp_pipeline),
    ("monitoring", _run_monitoring),
]


def _database_is_empty() -> bool:
    """True si les tables clés sont vides → premier démarrage à amorcer.

    Tolérant aux erreurs : en cas de souci de connexion, on retourne True pour
    laisser le bootstrap tenter sa chance (les flows gèrent eux-mêmes l'absence
    de données amont sans planter)."""
    try:
        from db.postgres_client import PostgresPool
        pool = PostgresPool()
        with pool.cursor() as cur:
            cur.execute(
                "SELECT (SELECT count(*) FROM kriging_results) AS kriging,"
                "       (SELECT count(*) FROM predictions) AS preds,"
                "       (SELECT count(*) FROM feature_store) AS feats"
            )
            row = cur.fetchone()
        pool.closeall()
        return not (row["kriging"] or row["preds"] or row["feats"])
    except Exception as exc:
        LOGGER.warning("bootstrap_check_failed error=%s — bootstrap forcé", exc)
        return True


def _bootstrap_first_run():
    """Au premier démarrage (tables vides), exécute une fois les flows producteurs
    de données dans l'ordre de dépendance, pour que le dashboard ne reste pas vide
    pendant l'intervalle de planification (jusqu'à 1h pour le kriging)."""
    if not _database_is_empty():
        LOGGER.info("bootstrap ignoré — des données existent déjà")
        return
    LOGGER.info("bootstrap démarré — tables vides, exécution initiale des flows")
    for name, fn in _BOOTSTRAP_SEQUENCE:
        LOGGER.info("bootstrap → %s", name)
        fn()  # chaque _run_* capture déjà ses propres exceptions
    LOGGER.info("bootstrap terminé")


def main():
    LOGGER.info("Démarrage de l'ordonnanceur de flows — pipeline Dakar")

    executors = {
        "default": ThreadPoolExecutor(max_workers=5),
    }
    job_defaults = {
        "coalesce": True,       # si un job est en retard, ne l'exécute qu'une fois
        "max_instances": 1,     # pas de chevauchement pour le même flow
        "misfire_grace_time": 120,
    }

    scheduler = BlockingScheduler(executors=executors, job_defaults=job_defaults)

    # Feature engineering — toutes les 5 minutes
    scheduler.add_job(
        _run_feature_engineering,
        trigger="interval", minutes=5,
        id="feature_engineering",
        name="Feature Engineering (57 features → feature_store)",
    )

    # Prédictions PM2.5 — toutes les 30 minutes
    scheduler.add_job(
        _run_predictions,
        trigger="interval", minutes=30,
        id="predictions",
        name="Prédictions LSTM/Prophet (h1/h6/h24)",
    )

    # Kriging spatial — toutes les heures
    scheduler.add_job(
        _run_kriging,
        trigger="interval", hours=1,
        id="kriging",
        name="Kriging GPR 200×200 (Dakar)",
    )

    # NLP signalements citoyens — toutes les heures
    scheduler.add_job(
        _run_nlp_pipeline,
        trigger="interval", hours=1,
        id="nlp_pipeline",
        name="NLP Pipeline (signalements en attente)",
    )

    # Monitoring qualité pipeline — toutes les heures
    scheduler.add_job(
        _run_monitoring,
        trigger="interval", hours=1,
        id="monitoring",
        name="Monitoring qualité pipeline (Q1-Q6)",
    )

    # Réentraînement automatique des modèles — toutes les 6 heures
    # (le flow lui-même vérifie les seuils et saute les modèles non prêts)
    scheduler.add_job(
        _run_retraining,
        trigger="interval", hours=6,
        id="retraining",
        name="Réentraînement RF/IF/LSTM/Prophet sur données accumulées",
    )

    def _graceful_stop(signum, frame):
        LOGGER.info("Signal %s reçu — arrêt de l'ordonnanceur", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _graceful_stop)
    signal.signal(signal.SIGINT,  _graceful_stop)

    LOGGER.info("Ordonnanceur démarré — %d flows planifiés", len(scheduler.get_jobs()))
    for job in scheduler.get_jobs():
        LOGGER.info("  job id=%-25s name=%s", job.id, job.name)

    # Amorçage au premier démarrage dans un thread daemon : ne bloque pas le
    # scheduler ni l'arrêt gracieux (SIGTERM).
    threading.Thread(target=_bootstrap_first_run, name="bootstrap",
                     daemon=True).start()

    scheduler.start()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
