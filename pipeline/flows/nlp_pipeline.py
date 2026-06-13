#!/usr/bin/env python3
"""Flow Prefect — Pipeline NLP sur les signalements citoyens.

Référence : pipeline/PIPELINE_SPEC.md §8.

Déclencheur : sur événement (nouvel enregistrement dans `reports`) +
batch toutes les heures (traite tous les signalements `nlp_status='pending'`).

Étapes par signalement :
  1. Nettoyage du texte (normalisation, suppression bruit)
  2. NER avec spaCy `fr_core_news_md` (entités : LOC, ORG, MISC, polluants)
  3. Embedding vectoriel 300d (vecteur du document via spaCy)
  4. Matching spatio-temporel avec anomalies détectées (rayon 2km, fenêtre 2h)
  5. Classification urgence : mots-clés règles + NER → `low/medium/high`
  6. Alerte si urgence `high`

Si spaCy ou le modèle `fr_core_news_md` ne sont pas installés, le flow
log un avertissement et passe en mode dégradé (pas de NER, embedding None,
classification par règles simples uniquement).
"""
from __future__ import annotations

import os
import re
import structlog
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

try:
    from prefect import flow, task
    from prefect.logging import get_run_logger
    HAS_PREFECT = True
except ImportError:
    HAS_PREFECT = False
    def flow(*a, **kw):
        def _d(fn): return fn
        return _d
    def task(*a, **kw):
        def _d(fn): return fn
        return _d
    def get_run_logger():
        return structlog.get_logger("nlp_pipeline")

from circuit_breaker import nlp_breaker  # noqa: E402

from db.postgres_client import PostgresPool  # noqa: E402

LOGGER = structlog.get_logger("nlp_pipeline")

# Mots-clés d'urgence haute (contexte dakarois §8.1)
HIGH_URGENCY_KEYWORDS = [
    "incendie", "brûlage", "fumée noire", "dépotoir", "mbeubeuss",
    "hospitalisation", "difficulté à respirer", "intoxication", "évacuation",
    "danger immédiat", "urgence", "pompiers",
]
POLLUTANT_KEYWORDS = ["fumée", "odeur", "poussière", "gaz", "pollution", "pm", "particules"]


# ============================================================================
# Chargement spaCy (optionnel)
# ============================================================================
def _load_spacy():
    try:
        import spacy
        return spacy.load("fr_core_news_md")
    except Exception as exc:
        LOGGER.warning("spacy_load_failed error=%s — NER/embeddings désactivés", exc)
        return None


# ============================================================================
# Fonctions de traitement
# ============================================================================
def preprocess_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s\.,!?'àáâãäåèéêëìíîïòóôõöùúûüçñ]", "", text)
    return text


def extract_entities(doc) -> list[dict]:
    entities = []
    for ent in doc.ents:
        entities.append({
            "text": ent.text,
            "label": ent.label_,
            "start": ent.start_char,
            "end": ent.end_char,
        })
    # Détection simple de termes polluants non reconnus par NER
    for kw in POLLUTANT_KEYWORDS:
        if kw in doc.text.lower():
            entities.append({"text": kw, "label": "POLLUTANT", "start": -1, "end": -1})
    return entities


def classify_urgency(clean_text: str, entities: list[dict]) -> str:
    """Règles déterministes : haute urgence si mot-clé critique présent."""
    for kw in HIGH_URGENCY_KEYWORDS:
        if kw in clean_text:
            return "high"
    pollutant_entities = [e for e in entities if e["label"] == "POLLUTANT"]
    if len(pollutant_entities) >= 2:
        return "medium"
    if pollutant_entities:
        return "low"
    return "low"


def find_nearby_anomalies(pool: PostgresPool, lat: float, lon: float,
                           radius_km: float, time_window_hours: int, reported_at: datetime) -> list[dict]:
    with pool.cursor() as cur:
        cur.execute("""
            SELECT ad.id, ad.pollutant, ad.detected_value, ad.detected_at,
                   z.nom AS zone_nom
            FROM anomaly_detections ad
            JOIN zones z ON z.id = ad.zone_id
            WHERE ad.detected_at BETWEEN %s - (%s * interval '1 hour') AND %s + interval '30 minutes'
              AND ST_DWithin(
                  ST_GeomFromText('POINT(' || %s || ' ' || %s || ')', 4326)::geography,
                  ST_Centroid(z.geom)::geography,
                  %s * 1000
              )
            ORDER BY ad.detected_at DESC
            LIMIT 10
        """, (reported_at, time_window_hours, reported_at, lon, lat, radius_km))
        return list(cur.fetchall())


# ============================================================================
# Persistence
# ============================================================================
def get_unprocessed_reports(pool: PostgresPool,
                              report_ids: Optional[list[int]] = None) -> list[dict]:
    with pool.cursor() as cur:
        if report_ids:
            cur.execute("""
                SELECT r.id, r.texte, r.created_at, r.langue,
                       ST_Y(r.geom) AS lat, ST_X(r.geom) AS lon
                FROM reports r
                WHERE r.id = ANY(%s) AND r.nlp_status = 'pending'
            """, (report_ids,))
        else:
            cur.execute("""
                SELECT r.id, r.texte, r.created_at, r.langue,
                       ST_Y(r.geom) AS lat, ST_X(r.geom) AS lon
                FROM reports r
                WHERE r.nlp_status = 'pending'
                ORDER BY r.created_at ASC
                LIMIT 100
            """)
        return list(cur.fetchall())


def insert_report_entities(pool: PostgresPool, report_id: int, entities: list[dict]) -> None:
    with pool.cursor() as cur:
        for ent in entities:
            cur.execute("""
                INSERT INTO report_entities (report_id, entity_type, entity_value)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (report_id, ent["label"], ent["text"]))


def insert_report_embedding(pool: PostgresPool, report_id: int, embedding: list[float]) -> None:
    # Le schéma utilise pgvector VECTOR(300) — format wire : '[x1,x2,…]'::vector
    vec_str = "[" + ",".join(f"{v:.6f}" for v in embedding[:300]) + "]"
    with pool.cursor() as cur:
        cur.execute("""
            INSERT INTO report_embeddings (report_id, embedding)
            VALUES (%s, %s::vector)
            ON CONFLICT (report_id, model_name) DO UPDATE SET embedding = EXCLUDED.embedding
        """, (report_id, vec_str))


def mark_report_processed(pool: PostgresPool, report_id: int) -> None:
    with pool.cursor() as cur:
        cur.execute("""
            UPDATE reports SET nlp_status = 'processed' WHERE id = %s
        """, (report_id,))


def create_correlation(pool: PostgresPool, report_id: int, anomalies: list[dict]) -> None:
    with pool.cursor() as cur:
        for anom in anomalies:
            cur.execute("""
                UPDATE anomaly_detections SET handled = true WHERE id = %s
            """, (anom["id"],))


def create_citizen_alert(pool: PostgresPool, report: dict, urgency: str) -> None:
    if not report.get("lon") or not report.get("lat"):
        return
    with pool.cursor() as cur:
        cur.execute("""
            SELECT z.id FROM zones z
            WHERE ST_Contains(z.geom, ST_GeomFromText('POINT(' || %s || ' ' || %s || ')', 4326))
            ORDER BY niveau DESC LIMIT 1
        """, (report["lon"], report["lat"]))
        zone_row = cur.fetchone()
        zone_int = int(zone_row["id"]) if zone_row else 1
        cur.execute("""
            INSERT INTO alerts (zone_id, type, gravite, message, canal_envoi)
            VALUES (%s, 'citizen_report', %s, %s, '{push,dashboard}')
        """, (zone_int, "warning" if urgency == "high" else "low",
              f"Signalement citoyen urgent : {report['texte'][:100]}"))


# ============================================================================
# Task + Flow principal
# ============================================================================
@task(name="process-report", retries=1)
def process_report(report: dict, pool: PostgresPool, nlp) -> dict:
    log = get_run_logger() if HAS_PREFECT else LOGGER
    report_id = report["id"]

    clean_text = preprocess_text(report["texte"])

    if nlp is not None:
        with nlp_breaker:
            doc = nlp(clean_text)
        entities = extract_entities(doc)
        embedding = doc.vector.tolist()
    else:
        entities = []
        embedding = None

    urgency = classify_urgency(clean_text, entities)

    insert_report_entities(pool, report_id, entities)
    if embedding is not None:
        insert_report_embedding(pool, report_id, embedding)

    # Matching spatio-temporel (§8.1 point 4)
    lat, lon = report.get("lat"), report.get("lon")
    nearby = []
    if lat is not None and lon is not None:
        nearby = find_nearby_anomalies(pool, lat, lon, radius_km=2,
                                        time_window_hours=2, reported_at=report["created_at"])
        if nearby:
            create_correlation(pool, report_id, nearby)

    if urgency == "high":
        create_citizen_alert(pool, report, urgency)

    mark_report_processed(pool, report_id)

    log.info("report_processed id=%d urgency=%s entities=%d nearby_anomalies=%d",
             report_id, urgency, len(entities), len(nearby))
    return {"id": report_id, "urgency": urgency, "entities": len(entities), "nearby": len(nearby)}


@flow(name="nlp_pipeline", retries=1, retry_delay_seconds=60)
def process_citizen_reports(report_ids: Optional[list[int]] = None):
    pool = PostgresPool()
    nlp = _load_spacy()

    reports = get_unprocessed_reports(pool, report_ids)
    if not reports:
        (get_run_logger() if HAS_PREFECT else LOGGER).info("nlp_no_reports_pending")
        return {"processed": 0}

    results = [process_report(r, pool, nlp) for r in reports]
    return {
        "processed": len(results),
        "high_urgency": sum(1 for r in results if r.get("urgency") == "high"),
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    result = process_citizen_reports()
    print("nlp_pipeline result:", result)
