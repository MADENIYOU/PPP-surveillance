-- ============================================================================
-- SEED 03 — Zones de Dakar + 10 capteurs simulés
-- Projet : Surveillance Citoyenne de la Pollution à Dakar (DIC2)
--
-- Source : implementation/simulation/config/sensors.yaml + zones.yaml.
-- Enregistre les capteurs simulés dans `sensors` afin que ZoneResolver
-- (pipeline/db/postgres_client.py) résolve les zones depuis la base au lieu
-- du fallback dérivé du serial_number (tâche #8 du backlog pipeline).
--
-- Idempotent : ON CONFLICT DO NOTHING / DO UPDATE partout.
-- Les polygones de zone sont des carrés ~2 km centrés sur le capteur — une
-- approximation suffisante pour resolve_zone_id() et le kriging en Phase 3/4
-- (les vrais contours administratifs seront importés en Phase 5).
-- ============================================================================

-- ── Zone racine (région Dakar, niveau 0) ─────────────────────────────────────
INSERT INTO zones (nom, geom, path, niveau, population)
VALUES (
    'Dakar',
    ST_GeomFromText('POLYGON((-17.65 14.50, -17.10 14.50, -17.10 14.95, -17.65 14.95, -17.65 14.50))', 4326),
    'dakar', 0, 3900000
)
ON CONFLICT (path) DO NOTHING;

-- ── Quartiers (niveau 3) — carré de ±0.01° (~1.1 km) autour du capteur ───────
INSERT INTO zones (nom, geom, path, niveau, population)
VALUES
    ('Médina',               ST_MakeEnvelope(-17.4620, 14.6967, -17.4420, 14.7167, 4326), 'dakar.medina',               3, 120000),
    ('Plateau',              ST_MakeEnvelope(-17.4541, 14.6837, -17.4341, 14.7037, 4326), 'dakar.plateau',              3,  37000),
    ('Pikine',               ST_MakeEnvelope(-17.4043, 14.7356, -17.3843, 14.7556, 4326), 'dakar.pikine',               3, 350000),
    ('Almadies',             ST_MakeEnvelope(-17.5223, 14.7356, -17.5023, 14.7556, 4326), 'dakar.almadies',             3,  55000),
    ('Rufisque',             ST_MakeEnvelope(-17.2841, 14.7052, -17.2641, 14.7252, 4326), 'dakar.rufisque',             3, 230000),
    ('Port',                 ST_MakeEnvelope(-17.4335, 14.6689, -17.4135, 14.6889, 4326), 'dakar.port',                 3,  15000),
    ('Parcelles Assainies',  ST_MakeEnvelope(-17.4334, 14.7578, -17.4134, 14.7778, 4326), 'dakar.parcelles_assainies',  3, 380000),
    ('Guédiawaye',           ST_MakeEnvelope(-17.4023, 14.7689, -17.3823, 14.7889, 4326), 'dakar.guediawaye',           3, 330000),
    ('Fann-Point E',         ST_MakeEnvelope(-17.4778, 14.6834, -17.4578, 14.7034, 4326), 'dakar.fann_pe',              3,  25000),
    ('Grand-Dakar',          ST_MakeEnvelope(-17.4667, 14.7023, -17.4467, 14.7223, 4326), 'dakar.grand_dakar',          3, 100000)
ON CONFLICT (path) DO NOTHING;

-- ── Capteurs simulés (sensors.yaml §6.1) ─────────────────────────────────────
INSERT INTO sensors (serial_number, type, zone_id, geom, status, firmware_version, install_date, metadata)
SELECT
    v.serial_number,
    'ESP32',
    z.id,
    ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326),
    'active',
    'sim-v1.2.0',
    DATE '2026-06-01',
    jsonb_build_object(
        'sim', true,
        'pollution_profile', v.profile,
        'altitude_m', v.altitude_m,
        'solar_panel', v.solar,
        'network_type', v.network,
        'calibration_date', '2026-06-01'
    )
FROM (VALUES
    ('ESP32-DK-MEDINA-001',     'medina',              14.7067, -17.4520, 12, 'urban_medium',    true,  'mqtt'),
    ('ESP32-DK-PLATEAU-001',    'plateau',             14.6937, -17.4441, 15, 'urban_high',      false, 'mqtt'),
    ('ESP32-DK-PIKINE-001',     'pikine',              14.7456, -17.3943,  8, 'periurban_high',  true,  'mqtt'),
    ('ESP32-DK-ALMADIES-001',   'almadies',            14.7456, -17.5123, 20, 'coastal_low',     true,  'mqtt'),
    ('ESP32-DK-RUFISQUE-001',   'rufisque',            14.7152, -17.2741, 10, 'industrial_high', true,  'mqtt'),
    ('ESP32-DK-PORT-001',       'port',                14.6789, -17.4235,  6, 'port_high',       false, 'mqtt'),
    ('ESP32-DK-PARCELLES-001',  'parcelles_assainies', 14.7678, -17.4234, 14, 'urban_medium',    true,  'mqtt'),
    ('ESP32-DK-GUEDIAWAYE-001', 'guediawaye',          14.7789, -17.3923,  9, 'periurban_medium',true,  'mqtt'),
    ('ESP32-DK-FANN-001',       'fann_pe',             14.6934, -17.4678, 18, 'residential_low', true,  'mqtt'),
    ('ESP32-DK-LORA-001',       'grand_dakar',         14.7123, -17.4567, 16, 'urban_medium',    true,  'lora')
) AS v(serial_number, zone_slug, lat, lon, altitude_m, profile, solar, network)
JOIN zones z ON z.path = ('dakar.' || v.zone_slug)::ltree
ON CONFLICT (serial_number) DO UPDATE
SET zone_id  = EXCLUDED.zone_id,
    geom     = EXCLUDED.geom,
    metadata = sensors.metadata || EXCLUDED.metadata;

DO $$
DECLARE
    n_zones INT; n_sensors INT;
BEGIN
    SELECT count(*) INTO n_zones FROM zones;
    SELECT count(*) INTO n_sensors FROM sensors;
    RAISE NOTICE 'Seed 03 appliqué : % zones, % capteurs.', n_zones, n_sensors;
END $$;
