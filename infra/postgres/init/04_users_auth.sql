-- ============================================================================
-- MIGRATION 04 — Comptes utilisateurs API (backend FastAPI, API_SPEC.md §2)
-- Projet : Surveillance Citoyenne de la Pollution à Dakar (DIC2)
--
-- La table `citizens` (01_schema.sql) est volontairement anonyme (pseudonyme,
-- email_hash) — les identifiants de connexion vivent ici, séparés des données
-- métier. users.citizen_id relie un compte à son profil citoyen.
-- ============================================================================

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('citizen', 'researcher', 'admin');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(254) NOT NULL,
    password_hash   VARCHAR(128) NOT NULL,      -- bcrypt
    role            user_role NOT NULL DEFAULT 'citizen',
    zone_id         INT REFERENCES zones(id) ON DELETE SET NULL,
    citizen_id      INT REFERENCES citizens(id) ON DELETE SET NULL,
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_login      TIMESTAMPTZ,

    CONSTRAINT uq_users_email UNIQUE (email)
);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

COMMENT ON TABLE users IS 'Comptes API (auth JWT) — séparés du profil citoyen anonymisé';

GRANT SELECT, INSERT, UPDATE, DELETE ON users TO app_user;

-- Comptes de démonstration : créés au démarrage du backend FastAPI si
-- BACKEND_SEED_DEMO_USERS=true (hash bcrypt calculé à l'exécution — jamais de
-- hash en dur dans un script versionné). Voir backend/app/db/seed.py.

DO $$ BEGIN
    RAISE NOTICE 'Migration 04 appliquée : table users.';
END $$;
