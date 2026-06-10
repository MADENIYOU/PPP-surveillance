# ============================================================================
# Image PostgreSQL 16 + PostGIS + pgvector — Surveillance Pollution Dakar (DIC2)
# Référence : 00_fondations/CHOIX_TECHNIQUES.md (§2.3) + 01_schema.sql (extension "vector")
#
# Aucune image officielle ne fournit PostGIS et pgvector ensemble : on part de
# l'image PostGIS (postgis/postgis:16-3.4-alpine) et on y ajoute pgvector en
# copiant les fichiers du paquet Alpine "postgresql-pgvector" (ABI PG16 identique)
# depuis le préfixe /usr (paquet officiel) vers le préfixe /usr/local (image PostGIS).
# ============================================================================
FROM postgis/postgis:16-3.4-alpine

RUN set -eux; \
    apk add --no-cache postgresql-pgvector; \
    cp /usr/share/postgresql16/extension/vector* /usr/local/share/postgresql/extension/; \
    cp /usr/lib/postgresql16/vector.so /usr/local/lib/postgresql/; \
    apk del postgresql-pgvector
