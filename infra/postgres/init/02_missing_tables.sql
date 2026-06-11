-- ============================================================================
-- MIGRATION 02 — Tables manquantes détectées lors de l'intégration pipeline
-- Projet : Surveillance Citoyenne de la Pollution à Dakar (DIC2)
-- ============================================================================

-- ── data_quality_metrics ─────────────────────────────────────────────────────
-- Stocke les métriques Q1-Q6 calculées toutes les heures par flows/monitoring.py
-- Le schéma initial (01_schema.sql) ne la contenait pas.

CREATE TABLE IF NOT EXISTS data_quality_metrics (
    id          BIGSERIAL PRIMARY KEY,
    computed_at TIMESTAMPTZ NOT NULL,
    metrics     JSONB NOT NULL,       -- {Q1_coverage, Q2_calibration_rate, …}
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dqm_computed_at ON data_quality_metrics(computed_at DESC);

COMMENT ON TABLE data_quality_metrics IS
    'Métriques horaires de qualité du pipeline (Q1 couverture … Q6 latence p95)';
COMMENT ON COLUMN data_quality_metrics.metrics IS
    'JSONB : {Q1_coverage, Q2_calibration_rate, Q3_rmse_1h, Q4_rmse_24h, Q5_false_alarm_rate, Q6_pipeline_latency_p95_ms}';


-- ── kriging_results ───────────────────────────────────────────────────────────
-- Le flux kriging génère une grille GeoJSON complète (200×200) + méta.
-- La table kriging_grid du schéma initial stocke des points individuels
-- (conçue pour le kriging vectoriel fin) ; kriging_results stocke la grille
-- agrégée utilisée par le frontend et l'API REST.

CREATE TABLE IF NOT EXISTS kriging_results (
    id               BIGSERIAL PRIMARY KEY,
    computed_at      TIMESTAMPTZ NOT NULL,
    geojson          JSONB NOT NULL,       -- FeatureCollection + grille raster
    rmse_loo         DOUBLE PRECISION,     -- Leave-One-Out RMSE (qualité kriging)
    grid_resolution  INT DEFAULT 200,      -- nb de cellules par côté (200×200)
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kriging_results_ts ON kriging_results(computed_at DESC);

COMMENT ON TABLE kriging_results IS
    'Grille de kriging GPR 200×200 sur Dakar — résultat du flow flows/kriging.py';
COMMENT ON COLUMN kriging_results.geojson IS
    'GeoJSON FeatureCollection : points de mesure + métadonnées grille';
COMMENT ON COLUMN kriging_results.rmse_loo IS
    'RMSE leave-one-out — mesure la qualité de l''interpolation spatiale';


-- ── Droits sur les nouvelles tables ──────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON data_quality_metrics TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON kriging_results       TO app_user;
GRANT SELECT ON data_quality_metrics TO readonly_user;
GRANT SELECT ON kriging_results       TO readonly_user;
GRANT USAGE, SELECT ON SEQUENCE data_quality_metrics_id_seq TO app_user;
GRANT USAGE, SELECT ON SEQUENCE kriging_results_id_seq       TO app_user;

-- ── pipeline_events ──────────────────────────────────────────────────────────
-- Journal d'événements du pipeline pour le dashboard /pipeline/logs.
-- Alimenté par les workers (INSERT) et triggers (NOTIFY → worker logging).

CREATE TABLE IF NOT EXISTS pipeline_events (
    id          BIGSERIAL PRIMARY KEY,
    service     VARCHAR(32) NOT NULL,
    level       VARCHAR(8) NOT NULL DEFAULT 'INFO',
    message     TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_events_service ON pipeline_events(service, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_level ON pipeline_events(level, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_created ON pipeline_events(created_at DESC);

COMMENT ON TABLE pipeline_events IS
    'Journal unifié des événements pipeline (ingestion, calibration, anomaly_detector, flows...)';
COMMENT ON COLUMN pipeline_events.service IS
    'Nom du worker/flow : ingestion, calibration, anomaly_detector, feature_engineering, etc.';

-- ── Colonne resolved_at sur alerts ───────────────────────────────────────────
-- Ajoutée pour supporter les endpoints /pipeline/alerts/{id}/resolve

DO $$ BEGIN
    ALTER TABLE alerts ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE alerts ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- ── Droits sur les nouveaux objets ───────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON pipeline_events TO app_user;
GRANT SELECT ON pipeline_events TO readonly_user;
GRANT USAGE, SELECT ON SEQUENCE pipeline_events_id_seq TO app_user;
GRANT UPDATE (resolved_at, acknowledged_at) ON alerts TO app_user;

DO $$
BEGIN
    RAISE NOTICE 'Migration 02 appliquée : tables data_quality_metrics, kriging_results, pipeline_events créées.';
END $$;
