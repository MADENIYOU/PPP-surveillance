#!/usr/bin/env bash
# =============================================================================
# start.sh — UNE SEULE COMMANDE pour lancer toute la plateforme Dakar
#
#   ./start.sh
#
# Ce script fait TOUT dans l'ordre :
#   1. Vérifie Docker + .env
#   2. Démarre Postgres, InfluxDB, Mosquitto, Redis (attend "healthy")
#   3. Applique les migrations SQL (idempotent)
#   4. Build les images pipeline + backend + frontend
#   5. Entraîne les modèles de base si absents (RF + IF, ~2 min)
#   6. Démarre workers + flows + backend + frontend (permanent)
#
# Options :
#   --no-train      Saute l'entraînement (démarre en mode fallback)
#   --with-sim      Démarre aussi le simulateur de capteurs
#   --down          Arrête tout proprement
#   --restart       Redémarre uniquement le pipeline (sans rebuild)
#   --logs          Affiche les logs en direct
#   --status        Montre l'état des conteneurs
# =============================================================================
set -euo pipefail

COMPOSE_INFRA="docker compose -f docker-compose.infra.yml"
COMPOSE_PIPELINE="docker compose -f docker-compose.infra.yml -f docker-compose.pipeline.yml"
COMPOSE_APP="docker compose -f docker-compose.infra.yml -f docker-compose.app.yml"
COMPOSE_ALL="docker compose -f docker-compose.infra.yml -f docker-compose.pipeline.yml -f docker-compose.app.yml"
MODELS_DIR="./pipeline/models"
MIGRATION_FILE="./infra/postgres/init/02_missing_tables.sql"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[✓]${NC} $*"; }
step()    { echo -e "${CYAN}[→]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }
hr()      { echo -e "${CYAN}$(printf '─%.0s' {1..60})${NC}"; }

NO_TRAIN=0; WITH_SIM=0; ACTION="up"
for arg in "$@"; do
  case $arg in
    --no-train)  NO_TRAIN=1 ;;
    --with-sim)  WITH_SIM=1 ;;
    --down)      ACTION="down" ;;
    --restart)   ACTION="restart" ;;
    --logs)      ACTION="logs" ;;
    --status)    ACTION="status" ;;
    *) warn "Argument inconnu : $arg" ;;
  esac
done

# ── Commandes secondaires ─────────────────────────────────────────────────────
case $ACTION in
  down)
    step "Arrêt de tous les services…"
    $COMPOSE_ALL down
    info "Plateforme arrêtée."
    exit 0 ;;
  restart)
    step "Redémarrage du pipeline + app (sans rebuild)…"
    $COMPOSE_ALL restart pipeline-workers pipeline-flows backend frontend
    info "Pipeline + app redémarrés."
    exit 0 ;;
  logs)
    $COMPOSE_ALL logs -f --tail=150
    exit 0 ;;
  status)
    $COMPOSE_ALL ps
    exit 0 ;;
esac

# ─────────────────────────────────────────────────────────────────────────────
hr
echo -e "  ${GREEN}Plateforme Surveillance Pollution — Dakar${NC}"
echo -e "  Démarrage complet en une commande"
hr

# ── Prérequis ─────────────────────────────────────────────────────────────────
step "Vérification des prérequis…"
command -v docker >/dev/null 2>&1 || error "Docker non trouvé. Installer Docker Desktop."
docker info >/dev/null 2>&1       || error "Docker daemon non démarré. Lancer Docker Desktop."

if [ ! -f ".env" ]; then
  [ -f ".env.example" ] && { warn ".env absent — copie depuis .env.example (vérifier les mots de passe)"; cp .env.example .env; } \
    || error ".env absent."
fi
info "Prérequis OK"

# ── Étape 1 : Infra ───────────────────────────────────────────────────────────
step "Étape 1/6 — Démarrage infra (Postgres · InfluxDB · Mosquitto · Redis)…"

# Build l'image Postgres localement si absente (pas de registry)
if ! docker image inspect dakar-postgres-postgis-pgvector:16 >/dev/null 2>&1; then
  step "  Build image Postgres + PostGIS + pgvector…"
  $COMPOSE_INFRA build --quiet postgres 2>&1 | tail -3
  info "  Image dakar-postgres-postgis-pgvector prête"
else
  info "  Image Postgres déjà présente (skip build)"
fi

$COMPOSE_INFRA up -d

step "Attente healthchecks (max 2 min)…"
DEADLINE=$(( $(date +%s) + 120 ))
until docker inspect dakar-postgres  --format='{{.State.Health.Status}}' 2>/dev/null | grep -q healthy \
   && docker inspect dakar-influxdb  --format='{{.State.Health.Status}}' 2>/dev/null | grep -q healthy \
   && docker inspect dakar-mosquitto --format='{{.State.Health.Status}}' 2>/dev/null | grep -q healthy; do
  [ "$(date +%s)" -gt "$DEADLINE" ] && error "Timeout healthcheck — vérifier : ./start.sh --logs"
  sleep 4
done
info "Infra prête"

# ── Étape 2 : Migrations SQL ──────────────────────────────────────────────────
step "Étape 2/6 — Application des migrations SQL…"

# Vérifie si la migration 02 est déjà appliquée (table data_quality_metrics)
MIGRATION_NEEDED=$(docker exec dakar-postgres psql -U dakar_admin -d dakar_pollution -tAq \
  -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='data_quality_metrics';" 2>/dev/null || echo "0")

if [ "$MIGRATION_NEEDED" = "0" ]; then
  step "  Application de 02_missing_tables.sql…"
  docker exec -i dakar-postgres psql -U dakar_admin -d dakar_pollution \
    < "$MIGRATION_FILE"
  info "Migration 02 appliquée"
else
  info "Migrations déjà à jour"
fi

# ── Étape 3 : Build images ───────────────────────────────────────────
step "Étape 3/6 — Build images pipeline + simulateur + backend + frontend…"
$COMPOSE_PIPELINE build --quiet pipeline-workers simulator 2>&1 | tail -5
$COMPOSE_APP build --quiet 2>&1 | tail -5
info "Images prêtes (pipeline + simulateur + backend + frontend)"

# ── Étape 4 : Entraînement initial ────────────────────────────────────────────
if [ "$NO_TRAIN" = "0" ]; then
  ALL_OK=1
  for f in calibration_rf_pm25.pkl anomaly_if.pkl lstm_full.pt prophet_pm25.pkl; do
    [ -f "$MODELS_DIR/$f" ] || ALL_OK=0
  done

  # LSTM (torch) et Prophet ne s'entraînent que si leurs dépendances sont dans
  # l'image. Sinon on les saute automatiquement (image légère par défaut).
  SKIP_ARGS=""
  if ! $COMPOSE_PIPELINE run --rm pipeline-workers python -c "import torch" >/dev/null 2>&1; then
    SKIP_ARGS="$SKIP_ARGS lstm"
  fi
  if ! $COMPOSE_PIPELINE run --rm pipeline-workers python -c "import prophet" >/dev/null 2>&1; then
    SKIP_ARGS="$SKIP_ARGS prophet"
  fi

  if [ "$ALL_OK" = "1" ]; then
    info "Étape 4/6 — Modèles déjà présents — skip"
  else
    step "Étape 4/6 — Entraînement des modèles (~3-5 min)…"
    step "  RandomForest (calibration) · IsolationForest (anomalie)$([ -n "$SKIP_ARGS" ] && echo " (LSTM/Prophet sautés : deps absentes)" || echo " · LSTM · Prophet")"
    step "  Chaque modèle est enregistré dans la table 'models' (page Modèles du dashboard)"
    mkdir -p "$MODELS_DIR"
      $COMPOSE_PIPELINE run --rm \
      -v "$(pwd)/pipeline/models:/app/models" \
      pipeline-workers \
      python training/train_all.py \
        --no-download \
        ${SKIP_ARGS:+--skip$SKIP_ARGS} \
        --epochs 5
    info "Modèles entraînés et enregistrés"
  fi
else
  warn "Étape 4/6 — Entraînement skippé (--no-train) — pipeline en mode fallback"
fi

# ── Étapes 5 & 6 : Lancement de toute la stack ────────────────────────────────
# On utilise COMPOSE_ALL (infra + pipeline + app) en une seule commande pour que
# tous les services soient déclarés dans la même invocation → pas de warning
# "orphan containers" (qui survenait en lançant pipeline puis app séparément).
step "Étapes 5 & 6/6 — Démarrage pipeline (workers · flows · simulateur) + backend + frontend…"
$COMPOSE_ALL up -d

# Simulateur optionnel
if [ "$WITH_SIM" = "1" ]; then
  step "Démarrage du simulateur de capteurs…"
  (cd simulation && python data_generator.py \
     --sensor-ids ESP32-DK-MEDINA-001 ESP32-DK-PLATEAU-001 \
     &> /tmp/simulator.log &)
  info "Simulateur démarré (PID $! — logs : /tmp/simulator.log)"
fi

# ── Résumé ────────────────────────────────────────────────────────────────────
hr
echo ""
echo -e "  ${GREEN}Plateforme démarrée — tout tourne en permanence${NC}"
echo ""
$COMPOSE_ALL ps
echo ""
hr
echo ""
echo -e "  ${CYAN}Services actifs :${NC}"
echo "    dakar-mosquitto         — Broker MQTT           port 1883"
echo "    dakar-postgres          — PostgreSQL+PostGIS     port 5432"
echo "    dakar-influxdb          — InfluxDB               port 8086  (UI: http://localhost:8086)"
echo "    dakar-redis             — Cache                  port 6379"
  echo "    dakar-pipeline-workers  — Ingestion · Calibration · Anomaly (supervisord)"
  echo "    dakar-pipeline-flows    — Features · Prédictions · Kriging · NLP · Monitoring · Retraining"
  echo "    dakar-backend           — API FastAPI             port 8000  (Swagger: http://localhost:8000/docs)"
  echo "    dakar-frontend          — Dashboard React         port 3000  (http://localhost:3000)"
  echo "    pipeline-metrics        — Métriques + dashboard   port 9090  (http://localhost:9090)"
echo ""
echo -e "  ${CYAN}Commandes utiles :${NC}"
echo "    ./start.sh --logs       Logs en direct"
echo "    ./start.sh --status     État des conteneurs"
echo "    ./start.sh --down       Arrêt propre"
echo "    ./start.sh --restart    Redémarre le pipeline sans rebuild"
echo "    ./start.sh --with-sim   Relancer avec le simulateur de capteurs"
echo ""
hr
