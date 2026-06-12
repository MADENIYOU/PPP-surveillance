# ============================================================================
# Image PostgreSQL 16 + PostGIS + pgvector — Surveillance Pollution Dakar (DIC2)
# Multi-arch (amd64 / arm64) — compatible Apple Silicon.
#
# Base : pgvector/pgvector:pg16 (officiel multi-arch, pgvector déjà inclus).
# On ajoute PostGIS par-dessus via les paquets Debian (l'image est basée sur
# debian:bookworm-slim, pas Alpine).
# ============================================================================
FROM pgvector/pgvector:pg16

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        postgresql-16-postgis-3 \
        postgresql-16-postgis-3-scripts; \
    rm -rf /var/lib/apt/lists/*
