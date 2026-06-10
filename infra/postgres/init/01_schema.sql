-- ============================================================================
-- SCRIPT D'INITIALISATION POSTGRESQL
-- Projet : Surveillance Citoyenne de la Pollution à Dakar (DIC2)
-- Usage  : psql -U dakar_admin -d dakar_pollution -f 01_schema.sql
-- ============================================================================

-- ════════════════════════════════════════════════════════════════════════════
-- EXTENSIONS
-- ════════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;          -- pour recherche texte fuzzy

-- ════════════════════════════════════════════════════════════════════════════
-- TYPES ENUM
-- ════════════════════════════════════════════════════════════════════════════

DO $$ BEGIN
    CREATE TYPE sensor_status AS ENUM ('active', 'maintenance', 'inactive', 'decommissioned');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE pollutant_type AS ENUM ('pm25', 'pm10', 'pm1_0', 'co', 'co2', 'no2', 'o3', 'so2', 'voc');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE model_type AS ENUM ('LSTM', 'GRU', 'Prophet', 'GCN', 'RandomForest', 'AutoEncoder', 'IsolationForest', 'GaussianProcess');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE alert_gravite AS ENUM ('info', 'warning', 'danger', 'critical');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE alert_type AS ENUM ('prevision', 'anomaly', 'citizen_report', 'data_quality', 'system');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_action AS ENUM ('INSERT', 'UPDATE', 'DELETE', 'READ_REPORT', 'READ_HEALTH', 'LOGIN', 'LOGOUT', 'EXPORT');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_status AS ENUM ('success', 'denied', 'error', 'rate_limited');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ════════════════════════════════════════════════════════════════════════════
-- MODULE 1 : INFRASTRUCTURE SPATIALE
-- ════════════════════════════════════════════════════════════════════════════

-- 1. ZONES ---------------------------------------------------------------

CREATE TABLE zones (
    id              SERIAL PRIMARY KEY,
    nom             VARCHAR(128) NOT NULL,
    geom            GEOMETRY(Polygon, 4326) NOT NULL,
    path            LTREE NOT NULL,
    niveau          INT NOT NULL DEFAULT 0 CHECK (niveau BETWEEN 0 AND 3),
    population      INT CHECK (population >= 0),
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_zones_path UNIQUE (path),
    CONSTRAINT ck_zones_geom_srid CHECK (ST_SRID(geom) = 4326),
    CONSTRAINT ck_zones_geom_valid CHECK (ST_IsValid(geom))
);

CREATE INDEX idx_zones_path_gist ON zones USING GIST (path);
CREATE INDEX idx_zones_path_btree ON zones USING BTREE (path);
CREATE INDEX idx_zones_geom ON zones USING GIST (geom);
CREATE INDEX idx_zones_niveau ON zones (niveau);
CREATE INDEX idx_zones_nom ON zones USING GIST (nom gist_trgm_ops);

COMMENT ON TABLE zones IS 'Découpage géographique hiérarchique. path ltree ex: dakar.plateau.fann';
COMMENT ON COLUMN zones.niveau IS '0=Région, 1=Département, 2=Commune, 3=Quartier';

-- 2. REF_STATIONS --------------------------------------------------------

CREATE TABLE ref_stations (
    id              SERIAL PRIMARY KEY,
    nom             VARCHAR(128) NOT NULL,
    source          VARCHAR(64) NOT NULL,
    zone_id         INT REFERENCES zones(id) ON DELETE SET NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL,
    pollutants      TEXT[] NOT NULL DEFAULT '{}',
    resolution_min  INT DEFAULT 60 CHECK (resolution_min > 0),
    api_endpoint    VARCHAR(256),
    status          sensor_status DEFAULT 'active',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_ref_stations_zone ON ref_stations(zone_id);
CREATE INDEX idx_ref_stations_geom ON ref_stations USING GIST (geom);
CREATE INDEX idx_ref_stations_source ON ref_stations(source);

COMMENT ON TABLE ref_stations IS 'Stations professionnelles de référence (vérité terrain DEEC, CGQA, ASDAN)';
COMMENT ON COLUMN ref_stations.pollutants IS 'Array des polluants mesurés: {pm25, pm10, co, no2}';

-- 3. SENSORS --------------------------------------------------------------

CREATE TABLE sensors (
    id              SERIAL PRIMARY KEY,
    serial_number   VARCHAR(64) NOT NULL,
    type            VARCHAR(32) NOT NULL,
    zone_id         INT NOT NULL REFERENCES zones(id) ON DELETE RESTRICT,
    ref_station_id  INT REFERENCES ref_stations(id) ON DELETE SET NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL,
    status          sensor_status DEFAULT 'active',
    firmware_version VARCHAR(16),
    install_date    DATE,
    last_seen       TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_sensors_serial UNIQUE (serial_number),
    CONSTRAINT ck_sensors_geom_srid CHECK (ST_SRID(geom) = 4326)
);

CREATE INDEX idx_sensors_zone_id ON sensors(zone_id);
CREATE INDEX idx_sensors_geom ON sensors USING GIST (geom);
CREATE INDEX idx_sensors_type ON sensors(type);
CREATE INDEX idx_sensors_status ON sensors(status) WHERE status = 'active';
CREATE INDEX idx_sensors_last_seen ON sensors(last_seen);
CREATE INDEX idx_sensors_metadata ON sensors USING GIN (metadata);

COMMENT ON TABLE sensors IS 'Inventaire des noeuds IoT (capteurs physiques)';
COMMENT ON COLUMN sensors.serial_number IS 'Identifiant unique matériel (ex: ESP32_042)';
COMMENT ON COLUMN sensors.metadata IS 'Extensible: MAC, date_derniere_maintenance, notes';

-- ════════════════════════════════════════════════════════════════════════════
-- MODULE 2 : IA & MODELES
-- ════════════════════════════════════════════════════════════════════════════

-- 4. MODELS ----------------------------------------------------------------

CREATE TABLE models (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(64) NOT NULL,
    type            model_type NOT NULL,
    version         VARCHAR(16) NOT NULL,
    description     TEXT,
    hyperparams     JSONB,
    metrics         JSONB,
    training_start  TIMESTAMPTZ,
    training_end    TIMESTAMPTZ,
    data_window_start TIMESTAMPTZ,
    data_window_end   TIMESTAMPTZ,
    file_path       VARCHAR(256),
    is_active       BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_models_name_version UNIQUE (name, version)
);

CREATE INDEX idx_models_active ON models(type) WHERE is_active = true;
CREATE INDEX idx_models_name ON models(name);
CREATE INDEX idx_models_created ON models(created_at);

COMMENT ON TABLE models IS 'Registre des modèles IA versionnés';
COMMENT ON COLUMN models.hyperparams IS 'Ex: {"layers": 2, "units": 64, "lr": 0.001, "dropout": 0.2}';
COMMENT ON COLUMN models.metrics IS 'Ex: {"rmse": 4.2, "mae": 3.1, "r2": 0.87}';

-- 5. CALIBRATION ----------------------------------------------------------

CREATE TABLE calibration (
    id              SERIAL PRIMARY KEY,
    sensor_id       INT NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    ref_station_id  INT REFERENCES ref_stations(id) ON DELETE SET NULL,
    model_id        INT REFERENCES models(id) ON DELETE SET NULL,
    coef_a          DOUBLE PRECISION NOT NULL,
    coef_b          DOUBLE PRECISION NOT NULL,
    pollutant       pollutant_type NOT NULL,
    r2_score        DOUBLE PRECISION,
    valid_from      DATE NOT NULL,
    valid_until     DATE,
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT ck_calibration_dates CHECK (valid_until IS NULL OR valid_until > valid_from)
);

CREATE INDEX idx_calibration_sensor ON calibration(sensor_id, pollutant, valid_from DESC);
CREATE INDEX idx_calibration_active ON calibration(sensor_id, pollutant) WHERE valid_until IS NULL;

COMMENT ON TABLE calibration IS 'Coefficients de correction (Y = aX + b) versionnés par capteur';
COMMENT ON COLUMN calibration.valid_until IS 'NULL = toujours actif. Si renseigné, fin de validité';

-- 6. PREDICTIONS ----------------------------------------------------------

CREATE TABLE predictions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id            INT NOT NULL REFERENCES models(id) ON DELETE RESTRICT,
    zone_id             INT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    pollutant           pollutant_type NOT NULL,
    predicted_value     DOUBLE PRECISION NOT NULL,
    ci_lower            DOUBLE PRECISION,
    ci_upper            DOUBLE PRECISION,
    target_timestamp    TIMESTAMPTZ NOT NULL,
    horizon_minutes     INT NOT NULL CHECK (horizon_minutes > 0),
    created_at          TIMESTAMPTZ DEFAULT now(),
    actual_value        DOUBLE PRECISION,
    error               DOUBLE PRECISION GENERATED ALWAYS AS (
        CASE WHEN actual_value IS NOT NULL
             THEN predicted_value - actual_value
             ELSE NULL
        END
    ) STORED,
    abs_error           DOUBLE PRECISION GENERATED ALWAYS AS (
        CASE WHEN actual_value IS NOT NULL
             THEN ABS(predicted_value - actual_value)
             ELSE NULL
        END
    ) STORED,

    CONSTRAINT ck_predictions_ci CHECK (ci_lower IS NULL OR ci_upper IS NULL OR ci_lower <= ci_upper)
);

CREATE INDEX idx_predictions_zone_target ON predictions(zone_id, target_timestamp DESC);
CREATE INDEX idx_predictions_pollutant ON predictions(zone_id, pollutant, target_timestamp DESC);
CREATE INDEX idx_predictions_model ON predictions(model_id, target_timestamp DESC);
CREATE INDEX idx_predictions_backtest ON predictions(target_timestamp) WHERE actual_value IS NULL;
CREATE INDEX idx_predictions_zone_pollutant_ts ON predictions(zone_id, pollutant, target_timestamp DESC);

COMMENT ON TABLE predictions IS 'Sorties des modèles de prédiction (forecasting)';
COMMENT ON COLUMN predictions.actual_value IS 'Rempli a posteriori par le backtesting (Prefect flow)';

-- 7. ANOMALY_DETECTIONS ---------------------------------------------------

CREATE TABLE anomaly_detections (
    id              SERIAL PRIMARY KEY,
    sensor_id       INT REFERENCES sensors(id) ON DELETE SET NULL,
    zone_id         INT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    model_id        INT REFERENCES models(id) ON DELETE SET NULL,
    pollutant       pollutant_type NOT NULL,
    detected_value  DOUBLE PRECISION NOT NULL,
    threshold       DOUBLE PRECISION NOT NULL,
    anomaly_score   DOUBLE PRECISION,
    detected_at     TIMESTAMPTZ NOT NULL,
    duration_minutes INT,
    handled         BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT ck_anomaly_source CHECK (sensor_id IS NOT NULL OR zone_id IS NOT NULL)
);

CREATE INDEX idx_anomaly_zone_ts ON anomaly_detections(zone_id, detected_at DESC);
CREATE INDEX idx_anomaly_sensor_ts ON anomaly_detections(sensor_id, detected_at DESC);
CREATE INDEX idx_anomaly_unhandled ON anomaly_detections(handled, detected_at) WHERE handled = false;

COMMENT ON TABLE anomaly_detections IS 'Anomalies détectées par AutoEncoder / Isolation Forest';
COMMENT ON COLUMN anomaly_detections.anomaly_score IS 'Score brut du modèle. > seuil = anomalie';

-- 8. ALERTS ---------------------------------------------------------------

CREATE TABLE alerts (
    id              SERIAL PRIMARY KEY,
    prediction_id   UUID REFERENCES predictions(id) ON DELETE SET NULL,
    anomaly_id      INT REFERENCES anomaly_detections(id) ON DELETE SET NULL,
    zone_id         INT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    type            alert_type NOT NULL,
    pollutant       pollutant_type,
    gravite         alert_gravite NOT NULL,
    message         TEXT NOT NULL,
    canal_envoi     TEXT[] NOT NULL DEFAULT '{push}',
    statut_envoi    VARCHAR(16) DEFAULT 'pending',
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT ck_alerts_source CHECK (
        (type = 'prevision' AND prediction_id IS NOT NULL) OR
        (type = 'anomaly' AND anomaly_id IS NOT NULL) OR
        (type IN ('citizen_report', 'data_quality', 'system'))
    ),
    CONSTRAINT ck_alerts_statut CHECK (statut_envoi IN ('pending', 'sent', 'failed', 'cancelled'))
);

CREATE INDEX idx_alerts_zone_ts ON alerts(zone_id, created_at DESC);
CREATE INDEX idx_alerts_statut ON alerts(statut_envoi, created_at);
CREATE INDEX idx_alerts_gravite ON alerts(gravite, created_at DESC);
CREATE INDEX idx_alerts_type ON alerts(type, created_at DESC);

COMMENT ON TABLE alerts IS 'Journal des alertes générées et leur statut d''envoi';
COMMENT ON COLUMN alerts.canal_envoi IS 'Array: {push, sms, email}';

-- ════════════════════════════════════════════════════════════════════════════
-- MODULE 3 : CITOYEN & NLP
-- ════════════════════════════════════════════════════════════════════════════

-- 9. CITIZENS -------------------------------------------------------------

CREATE TABLE citizens (
    id              SERIAL PRIMARY KEY,
    pseudonyme      VARCHAR(64) NOT NULL,
    email_hash      VARCHAR(64),
    score_confiance DOUBLE PRECISION DEFAULT 1.0 CHECK (score_confiance BETWEEN 0 AND 1),
    nb_reports      INT DEFAULT 0,
    nb_validated    INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_active     TIMESTAMPTZ,

    CONSTRAINT uq_citizens_pseudonyme UNIQUE (pseudonyme)
);

COMMENT ON TABLE citizens IS 'Utilisateurs anonymisés — identifiants JWT stockés côté auth, pas ici';
COMMENT ON COLUMN citizens.score_confiance IS 'Qualité métier: signalements vérifiés / total';
COMMENT ON COLUMN citizens.email_hash IS 'SHA256 de l''email pour notification push/email (optionnel)';

-- 10. REPORTS --------------------------------------------------------------

CREATE TABLE reports (
    id              SERIAL PRIMARY KEY,
    citizen_id      INT NOT NULL REFERENCES citizens(id) ON DELETE CASCADE,
    texte           TEXT NOT NULL,
    geom            GEOMETRY(Point, 4326),
    source_app      VARCHAR(32) DEFAULT 'mobile',
    langue          VARCHAR(8) DEFAULT 'fr',
    nlp_status      VARCHAR(16) DEFAULT 'pending' CHECK (nlp_status IN ('pending', 'processing', 'processed', 'error')),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT ck_reports_texte_len CHECK (char_length(texte) BETWEEN 10 AND 1000),
    CONSTRAINT ck_reports_geom_srid CHECK (geom IS NULL OR ST_SRID(geom) = 4326)
);

CREATE INDEX idx_reports_citizen ON reports(citizen_id, created_at DESC);
CREATE INDEX idx_reports_geom ON reports USING GIST (geom);
CREATE INDEX idx_reports_created ON reports(created_at DESC);
CREATE INDEX idx_reports_nlp_status ON reports(nlp_status, created_at) WHERE nlp_status = 'pending';
CREATE INDEX idx_reports_texte ON reports USING GIST (texte gist_trgm_ops);

COMMENT ON TABLE reports IS 'Signalements citoyens bruts. geom est déjà anonymisé (SnapToGrid + jitter)';
COMMENT ON COLUMN reports.nlp_status IS 'pending → processing (batch pick) → processed → error';

-- 11. REPORT_ENTITIES ------------------------------------------------------

CREATE TABLE report_entities (
    id              SERIAL PRIMARY KEY,
    report_id       INT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    entity_type     VARCHAR(32) NOT NULL,
    entity_value    VARCHAR(128) NOT NULL,
    start_pos       INT CHECK (start_pos >= 0),
    end_pos         INT CHECK (end_pos >= start_pos),
    confidence      DOUBLE PRECISION DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_report_entities_report ON report_entities(report_id);
CREATE INDEX idx_report_entities_type ON report_entities(entity_type, entity_value);
CREATE INDEX idx_report_entities_value ON report_entities USING GIN (to_tsvector('french', entity_value));

COMMENT ON TABLE report_entities IS 'Entités extraites par NER spaCy (fr_core_news_md)';
COMMENT ON COLUMN report_entities.entity_type IS 'polluant, symptome, lieu, odeur, source, date';

-- 12. REPORT_EMBEDDINGS ----------------------------------------------------

CREATE TABLE report_embeddings (
    id              SERIAL PRIMARY KEY,
    report_id       INT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    model_name      VARCHAR(64) NOT NULL DEFAULT 'spacy_fr_core_news_md',
    embedding       VECTOR(300) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_report_embeddings UNIQUE (report_id, model_name)
);

CREATE INDEX idx_report_embeddings_vector ON report_embeddings
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

COMMENT ON TABLE report_embeddings IS 'Vecteurs sémantiques pré-calculés (spaCy 300d → pgvector)';

-- 13. ANOMALY_LABELS -------------------------------------------------------

CREATE TABLE anomaly_labels (
    id              SERIAL PRIMARY KEY,
    report_id       INT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    anomaly_id      INT NOT NULL REFERENCES anomaly_detections(id) ON DELETE CASCADE,
    label           VARCHAR(64) NOT NULL,
    confidence      DOUBLE PRECISION DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    validated       BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_anomaly_labels UNIQUE (report_id, anomaly_id)
);

CREATE INDEX idx_anomaly_labels_label ON anomaly_labels(label);
CREATE INDEX idx_anomaly_labels_validated ON anomaly_labels(validated) WHERE validated = false;

COMMENT ON TABLE anomaly_labels IS 'Liaison signalement citoyen ↔ anomalie détectée (Human-in-the-loop)';
COMMENT ON COLUMN anomaly_labels.label IS 'feu_poubelle, incendie, embouteillage, poussieres, etc.';

-- ════════════════════════════════════════════════════════════════════════════
-- MODULE 4 : SANTE & IMPACT
-- ════════════════════════════════════════════════════════════════════════════

-- 14. PARTICIPANTS ---------------------------------------------------------

CREATE TABLE participants (
    id              SERIAL PRIMARY KEY,
    pseudonyme      VARCHAR(64) NOT NULL,
    classe_age      VARCHAR(16) NOT NULL CHECK (classe_age IN ('0-14', '15-29', '30-44', '45-59', '60+')),
    zone_id         INT REFERENCES zones(id) ON DELETE SET NULL,
    pathologies     TEXT[] NOT NULL DEFAULT '{}',
    date_entree     DATE NOT NULL,
    date_sortie     DATE,
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_participants_pseudonyme UNIQUE (pseudonyme),
    CONSTRAINT ck_participants_dates CHECK (date_sortie IS NULL OR date_sortie > date_entree)
);

CREATE INDEX idx_participants_zone ON participants(zone_id);
CREATE INDEX idx_participants_active ON participants(zone_id) WHERE date_sortie IS NULL;

COMMENT ON TABLE participants IS 'Cohorte de suivi sanitaire anonymisée';
COMMENT ON COLUMN participants.pathologies IS 'Array: {asthme, bpco, allergies, cardio}';

-- 15. HEALTH_LOGS ----------------------------------------------------------

CREATE TABLE health_logs (
    id              SERIAL PRIMARY KEY,
    participant_id  INT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    date_heure      TIMESTAMPTZ NOT NULL,
    symptome        VARCHAR(64) NOT NULL,
    valeur_vEMS     DOUBLE PRECISION CHECK (valeur_vEMS >= 0),
    medicament_pris BOOLEAN DEFAULT false,
    commentaire     TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_health_logs_participant ON health_logs(participant_id, date_heure DESC);
CREATE INDEX idx_health_logs_date ON health_logs(date_heure DESC);
CREATE INDEX idx_health_logs_symptome ON health_logs(symptome, date_heure DESC);

COMMENT ON TABLE health_logs IS 'Journaux de symptômes déclarés';
COMMENT ON COLUMN health_logs.valeur_vEMS IS 'Score de sévérité (0-100, optionnel)';

-- 16. MITIGATIONS ----------------------------------------------------------

CREATE TABLE mitigations (
    id              SERIAL PRIMARY KEY,
    zone_id         INT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    type            VARCHAR(64) NOT NULL,
    description     TEXT,
    geom            GEOMETRY(Polygon, 4326),
    date_debut      DATE NOT NULL,
    date_fin        DATE,
    budget_fcfa     BIGINT CHECK (budget_fcfa >= 0),
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT ck_mitigations_dates CHECK (date_fin IS NULL OR date_fin > date_debut)
);

CREATE INDEX idx_mitigations_zone ON mitigations(zone_id);
CREATE INDEX idx_mitigations_active ON mitigations(zone_id) WHERE date_fin IS NULL;

COMMENT ON TABLE mitigations IS 'Actions correctives (politiques publiques)';
COMMENT ON COLUMN mitigations.type IS 'interdiction_circulation, fermeture_usine, plantation, etc.';
COMMENT ON COLUMN mitigations.budget_fcfa IS 'Budget alloué en FCFA';

-- ════════════════════════════════════════════════════════════════════════════
-- MODULE 5 : DONNEES EXTERNES
-- ════════════════════════════════════════════════════════════════════════════

-- 17. TRAFFIC_OBSERVATIONS -------------------------------------------------

CREATE TABLE traffic_observations (
    id                SERIAL PRIMARY KEY,
    zone_id           INT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    timestamp         TIMESTAMPTZ NOT NULL,
    congestion_level  INT CHECK (congestion_level BETWEEN 0 AND 100),
    avg_speed_kmh     DOUBLE PRECISION CHECK (avg_speed_kmh >= 0),
    free_flow_speed   DOUBLE PRECISION CHECK (free_flow_speed >= 0),
    source            VARCHAR(32) DEFAULT 'google_maps',
    raw_response      JSONB,
    created_at        TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_traffic_obs UNIQUE (zone_id, timestamp, source)
);

CREATE INDEX idx_traffic_zone_ts ON traffic_observations(zone_id, timestamp DESC);

COMMENT ON TABLE traffic_observations IS 'Données de trafic routier (Google Maps API)';

-- 18. EXTERNAL_WEATHER -----------------------------------------------------

CREATE TABLE external_weather (
    id              SERIAL PRIMARY KEY,
    zone_id         INT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    timestamp       TIMESTAMPTZ NOT NULL,
    temperature     DOUBLE PRECISION,
    feels_like      DOUBLE PRECISION,
    humidity        DOUBLE PRECISION CHECK (humidity >= 0),
    pressure        DOUBLE PRECISION,
    wind_speed      DOUBLE PRECISION CHECK (wind_speed >= 0),
    wind_direction  DOUBLE PRECISION CHECK (wind_direction BETWEEN 0 AND 360),
    wind_gust       DOUBLE PRECISION CHECK (wind_gust >= 0),
    precipitation   DOUBLE PRECISION CHECK (precipitation >= 0),
    cloud_cover     DOUBLE PRECISION CHECK (cloud_cover BETWEEN 0 AND 100),
    visibility      DOUBLE PRECISION CHECK (visibility >= 0),
    weather_main    VARCHAR(32),
    source          VARCHAR(32) DEFAULT 'openweathermap',
    raw_response    JSONB,
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_ext_weather UNIQUE (zone_id, timestamp, source)
);

CREATE INDEX idx_weather_zone_ts ON external_weather(zone_id, timestamp DESC);
CREATE INDEX idx_weather_wind ON external_weather(zone_id, wind_speed, wind_direction);

COMMENT ON TABLE external_weather IS 'Données météorologiques (OpenWeatherMap / Météo Sénégal)';
COMMENT ON COLUMN external_weather.wind_direction IS 'Degrés 0-360 (0=Nord, 90=Est, 180=Sud, 270=Ouest)';

-- ════════════════════════════════════════════════════════════════════════════
-- MODULE 6 : FEATURE STORE & KRIGING
-- ════════════════════════════════════════════════════════════════════════════

-- FEATURE_STORE -----------------------------------------------------------

CREATE TABLE feature_store (
    id              BIGSERIAL PRIMARY KEY,
    zone_id         INT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    timestamp       TIMESTAMPTZ NOT NULL,
    features        JSONB NOT NULL,
    feature_names   TEXT[] NOT NULL,
    feature_count   INT GENERATED ALWAYS AS (array_length(feature_names, 1)) STORED,
    missing_count   INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_feature_store UNIQUE (zone_id, timestamp)
);

CREATE INDEX idx_feature_store_zone_ts ON feature_store(zone_id, timestamp DESC);
CREATE INDEX idx_feature_store_ts ON feature_store(timestamp DESC);

COMMENT ON TABLE feature_store IS 'Features horaires pour l''entraînement et l''inférence IA';
COMMENT ON COLUMN feature_store.features IS 'JSONB contenant les paires nom_feature: valeur';
COMMENT ON COLUMN feature_store.feature_names IS 'Liste ordonnée des noms de features (introspection)';
COMMENT ON COLUMN feature_store.missing_count IS 'Nombre de features manquantes pour ce point';

-- KRIGING_GRID ------------------------------------------------------------

CREATE TABLE kriging_grid (
    id              BIGSERIAL PRIMARY KEY,
    zone_id         INT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    point_geom      GEOMETRY(Point, 4326) NOT NULL,
    pm25_estime     DOUBLE PRECISION,
    pm10_estime     DOUBLE PRECISION,
    pm25_variance   DOUBLE PRECISION,
    pm10_variance   DOUBLE PRECISION,
    computed_at     TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT uq_kriging_point UNIQUE (zone_id, point_geom),
    CONSTRAINT ck_kriging_geom_srid CHECK (ST_SRID(point_geom) = 4326)
);

CREATE INDEX idx_kriging_zone ON kriging_grid(zone_id, computed_at DESC);
CREATE INDEX idx_kriging_geom ON kriging_grid USING GIST (point_geom);

COMMENT ON TABLE kriging_grid IS 'Résultat du Kriging : grille 500m × 500m';
COMMENT ON COLUMN kriging_grid.pm25_variance IS 'Variance du krigeage (incertitude de l''interpolation)';

-- DATA_GAPS ---------------------------------------------------------------

CREATE TABLE data_gaps (
    id              SERIAL PRIMARY KEY,
    sensor_id       INT REFERENCES sensors(id) ON DELETE CASCADE,
    seq_start       INT NOT NULL CHECK (seq_start >= 0 AND seq_start <= 65535),
    seq_end         INT NOT NULL CHECK (seq_end >= 0 AND seq_end <= 65535),
    gap_size        INT NOT NULL CHECK (gap_size > 0),
    detected_at     TIMESTAMPTZ DEFAULT now(),
    imputed         BOOLEAN DEFAULT false
);

CREATE INDEX idx_data_gaps_sensor ON data_gaps(sensor_id, detected_at DESC);
CREATE INDEX idx_data_gaps_unimputed ON data_gaps(sensor_id) WHERE imputed = false;

COMMENT ON TABLE data_gaps IS 'Gaps détectés dans les séquences MQTT (pertes de messages)';

-- ════════════════════════════════════════════════════════════════════════════
-- MODULE 7 : SECURITE & CONFORMITE
-- ════════════════════════════════════════════════════════════════════════════

-- AUDIT_LOGS (partitionné) ------------------------------------------------

CREATE TABLE audit_logs (
    id          BIGSERIAL,
    timestamp   TIMESTAMPTZ DEFAULT now() NOT NULL,
    user_id     INT,
    action      audit_action NOT NULL,
    resource    VARCHAR(64) NOT NULL,
    resource_id INT,
    details     JSONB,
    ip_address  INET,
    user_agent  VARCHAR(256),
    status      audit_status DEFAULT 'success'
) PARTITION BY RANGE (timestamp);

-- Partitions initiales (3 mois glissants)
-- En production, utiliser pg_partman pour la création automatique
CREATE TABLE audit_logs_2026_05 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE audit_logs_2026_06 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE audit_logs_2026_07 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');

CREATE INDEX idx_audit_ts ON audit_logs(timestamp DESC);
CREATE INDEX idx_audit_resource ON audit_logs(resource, timestamp DESC);
CREATE INDEX idx_audit_user ON audit_logs(user_id, timestamp DESC);
CREATE INDEX idx_audit_action_status ON audit_logs(action, status);
CREATE INDEX idx_audit_status ON audit_logs(status, timestamp DESC) WHERE status != 'success';

COMMENT ON TABLE audit_logs IS 'Journal d''audit partitionné mensuellement';
COMMENT ON COLUMN audit_logs.action IS 'INSERT, UPDATE, DELETE, READ_REPORT, READ_HEALTH, LOGIN, LOGOUT, EXPORT';
COMMENT ON COLUMN audit_logs.resource IS 'sensors, reports, predictions, calibration, participants, health_logs, etc.';
COMMENT ON COLUMN audit_logs.details IS 'JSONB: avant/après, delta, raison, metadata';

-- ════════════════════════════════════════════════════════════════════════════
-- FONCTIONS UTILITAIRES
-- ════════════════════════════════════════════════════════════════════════════

-- Fonction d'anonymisation spatiale ---------------------------------------

CREATE OR REPLACE FUNCTION anonymize_geom(
    input_geom GEOMETRY(Point, 4326),
    p_zone_id INT
) RETURNS GEOMETRY(Point, 4326) AS $$
DECLARE
    snapped     GEOMETRY(Point, 4326);
    jittered    GEOMETRY(Point, 4326);
    zone_geom   GEOMETRY;
    max_attempts INT := 20;
    attempt     INT := 0;
BEGIN
    -- Étape 1 : SnapToGrid(0.001°) → ~111m → efface l'adresse exacte
    snapped := ST_SnapToGrid(input_geom, 0.001);

    -- Récupérer la géométrie de la zone pour validation
    SELECT geom INTO zone_geom FROM zones WHERE id = p_zone_id;

    -- Étape 2 : Jitter borné ±55m dans la cellule
    LOOP
        jittered := ST_Translate(
            snapped,
            (random() - 0.5) * 0.001,
            (random() - 0.5) * 0.001
        );

        -- Étape 3 : Validation → le point doit rester dans la même zone
        EXIT WHEN zone_geom IS NULL OR ST_Contains(zone_geom, jittered);
        attempt := attempt + 1;
        EXIT WHEN attempt >= max_attempts;
    END LOOP;

    -- Fallback : retourner le snapped sans jitter si 20 tentatives échouées
    RETURN COALESCE(jittered, snapped);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION anonymize_geom IS 'Anonymise un point: SnapToGrid(0.001°) + jitter ±55m borné par la zone';

-- Fonction de mise à jour automatique de updated_at -----------------------

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Fonction de résolution zone_id depuis un point géographique --------------

CREATE OR REPLACE FUNCTION resolve_zone_id(point_geom GEOMETRY(Point, 4326))
RETURNS INT AS $$
DECLARE
    found_zone_id INT;
BEGIN
    SELECT z.id INTO found_zone_id
    FROM zones z
    WHERE ST_Contains(z.geom, point_geom)
      AND z.niveau = 3      -- zone la plus fine (quartier)
    ORDER BY ST_Area(z.geom) ASC  -- la plus petite zone contenante
    LIMIT 1;

    RETURN found_zone_id;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION resolve_zone_id IS 'Trouve le quartier (niveau 3) contenant un point géographique';

-- Fonction de conversion IQA (EPA standard simplifié) ----------------------

CREATE OR REPLACE FUNCTION compute_iqa(
    pollutant pollutant_type,
    concentration DOUBLE PRECISION
) RETURNS INT AS $$
DECLARE
    iqa INT;
BEGIN
    -- Grille EPA simplifiée (breakpoints PM2.5, PM10, CO, NO2, O3)
    CASE pollutant
        WHEN 'pm25' THEN
            iqa := CASE
                WHEN concentration <= 12.0  THEN ROUND(concentration / 12.0 * 50)
                WHEN concentration <= 35.4  THEN ROUND(50 + (concentration - 12.0) / (35.4 - 12.0) * 50)
                WHEN concentration <= 55.4  THEN ROUND(100 + (concentration - 35.4) / (55.4 - 35.4) * 50)
                WHEN concentration <= 150.4 THEN ROUND(150 + (concentration - 55.4) / (150.4 - 55.4) * 50)
                WHEN concentration <= 250.4 THEN ROUND(200 + (concentration - 150.4) / (250.4 - 150.4) * 100)
                ELSE ROUND(300 + (concentration - 250.4) / (500.4 - 250.4) * 200)
            END;
        WHEN 'pm10' THEN
            iqa := CASE
                WHEN concentration <= 54   THEN ROUND(concentration / 54 * 50)
                WHEN concentration <= 154  THEN ROUND(50 + (concentration - 54) / (154 - 54) * 50)
                WHEN concentration <= 254  THEN ROUND(100 + (concentration - 154) / (254 - 154) * 50)
                WHEN concentration <= 354  THEN ROUND(150 + (concentration - 254) / (354 - 254) * 50)
                WHEN concentration <= 424  THEN ROUND(200 + (concentration - 354) / (424 - 354) * 100)
                ELSE ROUND(300 + (concentration - 424) / (604 - 424) * 200)
            END;
        WHEN 'co' THEN
            iqa := CASE
                WHEN concentration <= 4.4   THEN ROUND(concentration / 4.4 * 50)
                WHEN concentration <= 9.4   THEN ROUND(50 + (concentration - 4.4) / (9.4 - 4.4) * 50)
                WHEN concentration <= 12.4  THEN ROUND(100 + (concentration - 9.4) / (12.4 - 9.4) * 50)
                WHEN concentration <= 15.4  THEN ROUND(150 + (concentration - 12.4) / (15.4 - 12.4) * 50)
                WHEN concentration <= 30.4  THEN ROUND(200 + (concentration - 15.4) / (30.4 - 15.4) * 100)
                ELSE ROUND(300 + (concentration - 30.4) / (50.4 - 30.4) * 200)
            END;
        WHEN 'no2' THEN
            iqa := CASE
                WHEN concentration <= 53   THEN ROUND(concentration / 53 * 50)
                WHEN concentration <= 100  THEN ROUND(50 + (concentration - 53) / (100 - 53) * 50)
                WHEN concentration <= 360  THEN ROUND(100 + (concentration - 100) / (360 - 100) * 50)
                WHEN concentration <= 649  THEN ROUND(150 + (concentration - 360) / (649 - 360) * 50)
                WHEN concentration <= 1249 THEN ROUND(200 + (concentration - 649) / (1249 - 649) * 100)
                ELSE ROUND(300 + (concentration - 1249) / (2049 - 1249) * 200)
            END;
        WHEN 'o3' THEN
            iqa := CASE
                WHEN concentration <= 54   THEN ROUND(concentration / 54 * 50)
                WHEN concentration <= 70   THEN ROUND(50 + (concentration - 54) / (70 - 54) * 50)
                WHEN concentration <= 85   THEN ROUND(100 + (concentration - 70) / (85 - 70) * 50)
                WHEN concentration <= 105  THEN ROUND(150 + (concentration - 85) / (105 - 85) * 50)
                WHEN concentration <= 200  THEN ROUND(200 + (concentration - 105) / (200 - 105) * 100)
                ELSE ROUND(300 + (concentration - 200) / (400 - 200) * 200)
            END;
        ELSE
            iqa := NULL;
    END CASE;

    RETURN LEAST(GREATEST(iqa, 0), 500);  -- borné [0, 500]
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION compute_iqa IS 'Calcule l''IQA selon la grille EPA (US) par polluant. Retourne 0-500';

-- Fonction de catégorie IQA -----------------------------------------------

CREATE OR REPLACE FUNCTION iqa_category(iqa_value INT)
RETURNS VARCHAR(32) AS $$
BEGIN
    RETURN CASE
        WHEN iqa_value <= 50   THEN 'good'
        WHEN iqa_value <= 100  THEN 'moderate'
        WHEN iqa_value <= 150  THEN 'unhealthy_sensitive'
        WHEN iqa_value <= 200  THEN 'unhealthy'
        WHEN iqa_value <= 300  THEN 'very_unhealthy'
        ELSE 'hazardous'
    END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ════════════════════════════════════════════════════════════════════════════
-- TRIGGERS
-- ════════════════════════════════════════════════════════════════════════════

-- Trigger updated_at pour les tables qui l'ont -----------------------------

CREATE TRIGGER trg_zones_updated_at
    BEFORE UPDATE ON zones
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_sensors_updated_at
    BEFORE UPDATE ON sensors
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ════════════════════════════════════════════════════════════════════════════
-- TRIGGERS D'AUDIT
-- ════════════════════════════════════════════════════════════════════════════

-- Fonction générique d'audit -----------------------------------------------

CREATE OR REPLACE FUNCTION audit_trigger_function()
RETURNS TRIGGER AS $$
DECLARE
    audit_user_id INT;
    audit_details JSONB;
BEGIN
    -- Récupérer l'ID utilisateur depuis la variable de session (si définie)
    audit_user_id := NULLIF(current_setting('app.current_user_id', true), '')::INT;

    -- Construire les détails
    CASE TG_OP
        WHEN 'INSERT' THEN
            audit_details := jsonb_build_object('new', row_to_json(NEW));
        WHEN 'UPDATE' THEN
            audit_details := jsonb_build_object(
                'old', row_to_json(OLD),
                'new', row_to_json(NEW),
                'changed', (
                    SELECT jsonb_object_agg(key, jsonb_build_object('old', old_val, 'new', new_val))
                    FROM jsonb_each(row_to_json(NEW)::jsonb) AS n(key, new_val)
                    JOIN jsonb_each(row_to_json(OLD)::jsonb) AS o(key, old_val) USING (key)
                    WHERE n.new_val IS DISTINCT FROM o.old_val
                      AND key NOT IN ('created_at', 'updated_at', 'last_seen', 'last_active')
                )
            );
        WHEN 'DELETE' THEN
            audit_details := jsonb_build_object('old', row_to_json(OLD));
        ELSE
            audit_details := '{}'::jsonb;
    END CASE;

    INSERT INTO audit_logs (
        timestamp, user_id, action, resource,
        resource_id, details, ip_address, status
    ) VALUES (
        now(),
        audit_user_id,
        TG_OP::audit_action,
        TG_TABLE_NAME,
        CASE TG_OP
            WHEN 'DELETE' THEN OLD.id
            ELSE NEW.id
        END,
        audit_details,
        inet_client_addr(),
        'success'
    );

    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Application des triggers d'audit -----------------------------------------
-- Tables à auditer : écritures + données personnelles
-- PAS les lectures de carte publique (trop volumineux)

CREATE TRIGGER trg_audit_sensors
    AFTER INSERT OR UPDATE OR DELETE ON sensors
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER trg_audit_calibration
    AFTER INSERT OR UPDATE OR DELETE ON calibration
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER trg_audit_alerts
    AFTER INSERT OR UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER trg_audit_citizens
    AFTER INSERT OR UPDATE OR DELETE ON citizens
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER trg_audit_reports
    AFTER INSERT OR UPDATE OR DELETE ON reports
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER trg_audit_participants
    AFTER INSERT OR UPDATE OR DELETE ON participants
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER trg_audit_health_logs
    AFTER INSERT OR UPDATE OR DELETE ON health_logs
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

-- Tables sans audit (volume) : predictions, anomaly_detections, feature_store,
--   kriging_grid, traffic_observations, external_weather
--   → logs applicatifs suffisants (Prefect logging)

-- ════════════════════════════════════════════════════════════════════════════
-- VUES UTILITAIRES
-- ════════════════════════════════════════════════════════════════════════════

-- Vue : capteurs actifs avec leur zone full path ---------------------------

CREATE OR REPLACE VIEW v_active_sensors AS
SELECT
    s.id,
    s.serial_number,
    s.type,
    s.zone_id,
    z.nom AS zone_nom,
    z.path AS zone_path,
    s.geom,
    s.status,
    s.firmware_version,
    s.last_seen
    -- Note : pas de colonne "battery_level" sur cette table — la télémétrie
    -- (batterie, uptime, RSSI...) est une série temporelle stockée dans InfluxDB
    -- (mesure "sensor_health" / champs de "air_quality_raw"), pas une métadonnée.
FROM sensors s
JOIN zones z ON s.zone_id = z.id
WHERE s.status = 'active';

-- Vue : alertes actives avec contexte --------------------------------------

CREATE OR REPLACE VIEW v_active_alerts AS
SELECT
    a.id,
    a.type,
    a.gravite,
    a.message,
    a.zone_id,
    z.nom AS zone_nom,
    z.path AS zone_path,
    a.pollutant,
    a.canal_envoi,
    a.statut_envoi,
    a.created_at
FROM alerts a
JOIN zones z ON a.zone_id = z.id
WHERE a.statut_envoi IN ('pending', 'sent')
  AND a.created_at > now() - INTERVAL '24 hours';

-- Vue : synthèse de calibration par capteur ---------------------------------

CREATE OR REPLACE VIEW v_calibration_status AS
SELECT
    s.id AS sensor_id,
    s.serial_number,
    s.type,
    c.pollutant,
    c.coef_a,
    c.coef_b,
    c.r2_score,
    c.valid_from,
    c.valid_until,
    c.valid_until IS NULL AS is_active,
    c.valid_from + INTERVAL '90 days' > now() AS is_recent
FROM sensors s
LEFT JOIN calibration c ON s.id = c.sensor_id
    AND c.valid_until IS NULL;

-- ════════════════════════════════════════════════════════════════════════════
-- DROITS & ROLES
-- ════════════════════════════════════════════════════════════════════════════

-- Application des principes de moindre privilège

DO $$ BEGIN
    -- Rôle applicatif (FastAPI, pipeline workers)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user LOGIN PASSWORD 'CHANGE_ME_IN_VAULT';
    END IF;

    -- Rôle lecture seule (BI, dashboards publics)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'readonly_user') THEN
        CREATE ROLE readonly_user LOGIN PASSWORD 'CHANGE_ME_IN_VAULT';
    END IF;

    -- Rôle admin (maintenance, migrations)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dakar_admin') THEN
        CREATE ROLE dakar_admin LOGIN PASSWORD 'CHANGE_ME_IN_VAULT' SUPERUSER;
    END IF;
END $$;

-- app_user : CRUD complet sur toutes les tables (sauf audit)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- readonly_user : SELECT uniquement
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;
-- Interdire SELECT sur audit_logs et participants (données sensibles)
REVOKE SELECT ON audit_logs, participants, health_logs FROM readonly_user;

-- ════════════════════════════════════════════════════════════════════════════
-- COMMENTAIRES FINAUX
-- ════════════════════════════════════════════════════════════════════════════

COMMENT ON SCHEMA public IS 'Schéma principal — Surveillance Citoyenne Pollution Dakar (DIC2)';

-- Résumé des tables créées
DO $$
DECLARE
    table_count INT;
BEGIN
    SELECT count(*) INTO table_count FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
    RAISE NOTICE 'Initialisation terminée : % tables créées.', table_count;
END $$;
