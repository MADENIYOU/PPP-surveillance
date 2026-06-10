#!/bin/sh
# ============================================================================
# Initialisation post-démarrage InfluxDB — Surveillance Pollution Dakar (DIC2)
#
# Le bucket "bucket_raw" et le token admin sont créés automatiquement par
# l'image officielle via DOCKER_INFLUXDB_INIT_* (voir docker-compose.infra.yml).
# Ce script complète le déploiement décrit dans 02_influxdb_config.flux (MODULE 6) :
#   1. Créer les buckets manquants (bucket_cleansed, bucket_downsampled)
#   2. Déployer les 4 tâches Flux planifiées
#   3. Créer les tokens scoped par composant (principe du moindre privilège)
#
# Idempotent : relancer ce script ne duplique ni les buckets ni les tâches
# (vérification d'existence avant création). Les tokens sont en revanche
# recréés à chaque exécution s'ils manquent (un seul token par description).
# ============================================================================
set -eu

: "${INFLUX_HOST:=http://influxdb:8086}"
: "${INFLUX_ORG:=dakar_pollution}"
: "${INFLUX_TOKEN:?INFLUX_TOKEN (admin) doit être défini}"

export INFLUX_HOST INFLUX_ORG INFLUX_TOKEN

echo "[influxdb-init] En attente de disponibilité de $INFLUX_HOST ..."
until influx ping --host "$INFLUX_HOST" >/dev/null 2>&1; do
  sleep 2
done
echo "[influxdb-init] InfluxDB disponible."

bucket_id() {
  influx bucket list --host "$INFLUX_HOST" --org "$INFLUX_ORG" --name "$1" --json 2>/dev/null \
    | grep -o '"id": *"[a-f0-9]*"' | head -n1 | cut -d'"' -f4
}

ensure_bucket() {
  name="$1"; retention="$2"; description="$3"
  if [ -z "$(bucket_id "$name")" ]; then
    echo "[influxdb-init] Création du bucket $name (rétention: $retention) ..."
    influx bucket create --host "$INFLUX_HOST" --org "$INFLUX_ORG" \
      --name "$name" --retention "$retention" --description "$description"
  else
    echo "[influxdb-init] Bucket $name déjà présent — ignoré."
  fi
}

# ── Étape 1 : buckets manquants (bucket_raw existe déjà via DOCKER_INFLUXDB_INIT_*) ──
ensure_bucket "bucket_cleansed"    "17520h" "Données calibrées RF+Kalman — source de vérité — rétention 2 ans"
ensure_bucket "bucket_downsampled" "0"      "Agrégats horaires/journaliers + IQA — rétention infinie"

RAW_ID=$(bucket_id "bucket_raw")
CLEANSED_ID=$(bucket_id "bucket_cleansed")
DOWN_ID=$(bucket_id "bucket_downsampled")
echo "[influxdb-init] IDs buckets — raw=$RAW_ID cleansed=$CLEANSED_ID downsampled=$DOWN_ID"

# ── Étape 2 : déploiement des 4 tâches Flux planifiées ───────────────────────
for task_def in \
  "downsample_hourly:/config/tasks/downsample_hourly.flux" \
  "downsample_daily:/config/tasks/downsample_daily.flux" \
  "compute_iqa_daily:/config/tasks/compute_iqa_daily.flux" \
  "monitor_sensor_freshness:/config/tasks/monitor_freshness.flux"
do
  task_name="${task_def%%:*}"
  task_file="${task_def#*:}"
  existing=$(influx task list --host "$INFLUX_HOST" --org "$INFLUX_ORG" --json 2>/dev/null \
    | grep -o "\"name\": *\"$task_name\"" || true)
  if [ -z "$existing" ]; then
    echo "[influxdb-init] Déploiement de la tâche $task_name ..."
    influx task create --host "$INFLUX_HOST" --org "$INFLUX_ORG" --file "$task_file"
  else
    echo "[influxdb-init] Tâche $task_name déjà déployée — ignorée."
  fi
done

# ── Étape 3 : tokens scoped par composant (moindre privilège) ────────────────
# influx auth create ne supporte pas la vérification d'existence par description ;
# on ne (re)crée que s'il n'existe aucun token portant cette description.
ensure_auth() {
  description="$1"; shift
  existing=$(influx auth list --host "$INFLUX_HOST" --org "$INFLUX_ORG" --json 2>/dev/null \
    | grep -o "\"description\": *\"$description\"" || true)
  if [ -z "$existing" ]; then
    echo "[influxdb-init] Création du token '$description' ..."
    influx auth create --host "$INFLUX_HOST" --org "$INFLUX_ORG" --description "$description" "$@" \
      | grep -i token | tee "/tokens/${description}.token.txt" >/dev/null
  else
    echo "[influxdb-init] Token '$description' déjà présent — ignoré."
  fi
}

ensure_auth "mqtt_subscriber_write"  --write-bucket "$RAW_ID"
ensure_auth "calibration_pipeline"   --read-bucket  "$RAW_ID"      --write-bucket "$CLEANSED_ID"
ensure_auth "anomaly_detector_read"  --read-bucket  "$CLEANSED_ID"
ensure_auth "feature_kriging_read"   --read-bucket  "$CLEANSED_ID"
ensure_auth "fastapi_readonly"       --read-bucket  "$CLEANSED_ID" --read-bucket "$DOWN_ID"
ensure_auth "flux_tasks_internal" \
  --read-bucket  "$RAW_ID" --read-bucket  "$CLEANSED_ID" --read-bucket  "$DOWN_ID" \
  --write-bucket "$CLEANSED_ID" --write-bucket "$DOWN_ID"

echo "[influxdb-init] Terminé. Tokens écrits dans /tokens/ (volume partagé — ne pas committer)."
