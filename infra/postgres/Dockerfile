# ============================================================================
# Image PostgreSQL 16 + PostGIS + pgvector — Surveillance Pollution Dakar (DIC2)
# Multi-arch (amd64 / arm64) — compatible Apple Silicon.
#
# Stratégie : partir de postgres:16-alpine (officiel multi-arch), ajouter
# PostGIS et pgvector via les paquets Alpine officiels (disponibles sur les
# deux architectures), puis copier les .so/.control dans le préfixe utilisé
# par l'image postgres:alpine (/usr/local/share/postgresql/).
# ============================================================================
FROM postgres:16-alpine

RUN set -eux; \
    apk add --no-cache \
        postgis \
        postgresql-pgvector; \
    cp /usr/share/postgresql16/extension/postgis*       /usr/local/share/postgresql/extension/; \
    cp /usr/share/postgresql16/extension/postgis_raster* /usr/local/share/postgresql/extension/ 2>/dev/null || true; \
    cp /usr/share/postgresql16/extension/postgis_topology* /usr/local/share/postgresql/extension/ 2>/dev/null || true; \
    cp /usr/share/postgresql16/extension/address_standardizer* /usr/local/share/postgresql/extension/ 2>/dev/null || true; \
    cp /usr/share/postgresql16/extension/vector*         /usr/local/share/postgresql/extension/; \
    cp /usr/lib/postgresql16/postgis*.so                 /usr/local/lib/postgresql/ 2>/dev/null || true; \
    cp /usr/lib/postgresql16/vector.so                   /usr/local/lib/postgresql/; \
    apk del postgis postgresql-pgvector
