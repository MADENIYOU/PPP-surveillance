#Requires -Version 5.1
<#
.SYNOPSIS
    Démarre la plateforme complète de surveillance pollution Dakar en une commande.

.DESCRIPTION
    Étapes :
      1. Vérifie Docker + .env
      2. Démarre Postgres · InfluxDB · Mosquitto (attend "healthy")
      3. Applique les migrations SQL (idempotent — CREATE TABLE IF NOT EXISTS)
      4. Build l'image pipeline
      5. Entraîne les modèles de base si absents (~2 min)
      6. Démarre workers + flows en permanence

.PARAMETER NoTrain
    Saute l'entraînement initial (démarre en mode fallback)

.PARAMETER WithSim
    Démarre aussi le simulateur de capteurs en tâche de fond

.PARAMETER Down
    Arrête tous les services proprement

.PARAMETER Restart
    Redémarre uniquement le pipeline (sans rebuild)

.PARAMETER Logs
    Affiche les logs en direct

.PARAMETER Status
    Montre l'état des conteneurs

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Down
    .\start.ps1 -NoTrain
    .\start.ps1 -Status
#>
[CmdletBinding(DefaultParameterSetName = "Up")]
param(
    [Parameter(ParameterSetName = "Up")]
    [switch]$NoTrain,

    [Parameter(ParameterSetName = "Up")]
    [switch]$WithSim,

    [Parameter(ParameterSetName = "Down")]
    [switch]$Down,

    [Parameter(ParameterSetName = "Restart")]
    [switch]$Restart,

    [Parameter(ParameterSetName = "Logs")]
    [switch]$Logs,

    [Parameter(ParameterSetName = "Status")]
    [switch]$Status
)

$ErrorActionPreference = "Stop"

# ── Couleurs ─────────────────────────────────────────────────────────────────
function Write-Step  { param($msg) Write-Host "[→] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[✓] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "[✗] $msg" -ForegroundColor Red; exit 1 }
function Write-Hr    { Write-Host ("─" * 60) -ForegroundColor Cyan }

$ComposeInfra    = "docker compose -f docker-compose.infra.yml"
$ComposeAll      = "docker compose -f docker-compose.infra.yml -f docker-compose.pipeline.yml"
$ModelsDir       = ".\pipeline\models"
$MigrationFile   = ".\infra\postgres\init\02_missing_tables.sql"

# ── Commandes secondaires ─────────────────────────────────────────────────────
if ($Down) {
    Write-Step "Arrêt de tous les services…"
    Invoke-Expression "$ComposeAll down"
    Write-Ok "Plateforme arrêtée."
    exit 0
}

if ($Restart) {
    Write-Step "Redémarrage du pipeline (sans rebuild)…"
    Invoke-Expression "$ComposeAll restart pipeline-workers pipeline-flows"
    Write-Ok "Pipeline redémarré."
    exit 0
}

if ($Logs) {
    Invoke-Expression "$ComposeAll logs -f --tail=150"
    exit 0
}

if ($Status) {
    Invoke-Expression "$ComposeAll ps"
    exit 0
}

# ── Démarrage complet ─────────────────────────────────────────────────────────
Write-Hr
Write-Host "  Plateforme Surveillance Pollution — Dakar" -ForegroundColor Green
Write-Host "  Démarrage complet en une commande"
Write-Hr

# ── Prérequis ─────────────────────────────────────────────────────────────────
Write-Step "Vérification des prérequis…"

try { $null = Get-Command docker -ErrorAction Stop }
catch { Write-Fail "Docker non trouvé. Installer Docker Desktop : https://docs.docker.com/desktop/windows/" }

try { docker info 2>&1 | Out-Null }
catch { Write-Fail "Docker daemon non démarré. Lancer Docker Desktop puis réessayer." }

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Warn ".env absent — copie depuis .env.example (vérifier les mots de passe !)"
        Copy-Item ".env.example" ".env"
    } else {
        Write-Fail ".env absent et pas de .env.example."
    }
}
Write-Ok "Prérequis OK"

# ── Étape 1 : Infra ───────────────────────────────────────────────────────────
Write-Step "Étape 1/5 — Démarrage infra (Postgres · InfluxDB · Mosquitto)…"
Invoke-Expression "$ComposeInfra up -d"

Write-Step "Attente healthchecks (max 2 min)…"
$deadline = (Get-Date).AddSeconds(120)
do {
    if ((Get-Date) -gt $deadline) {
        Write-Fail "Timeout healthcheck — vérifier : .\start.ps1 -Logs"
    }
    Start-Sleep -Seconds 4
    $pgHealth  = docker inspect dakar-postgres  --format='{{.State.Health.Status}}' 2>$null
    $influxH   = docker inspect dakar-influxdb  --format='{{.State.Health.Status}}' 2>$null
    $mqttH     = docker inspect dakar-mosquitto --format='{{.State.Health.Status}}' 2>$null
} until ($pgHealth -eq "healthy" -and $influxH -eq "healthy" -and $mqttH -eq "healthy")
Write-Ok "Infra prête"

# ── Étape 2 : Migrations SQL ──────────────────────────────────────────────────
Write-Step "Étape 2/5 — Application des migrations SQL…"

$migrationCheck = docker exec dakar-postgres psql -U dakar_admin -d dakar_pollution -tAq `
    -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='data_quality_metrics';" 2>$null

if ($migrationCheck -eq "0" -or [string]::IsNullOrWhiteSpace($migrationCheck)) {
    Write-Step "  Application de 02_missing_tables.sql…"
    Get-Content $MigrationFile | docker exec -i dakar-postgres psql -U dakar_admin -d dakar_pollution
    Write-Ok "Migration 02 appliquée"
} else {
    Write-Ok "Migrations déjà à jour"
}

# ── Étape 3 : Build image pipeline ───────────────────────────────────────────
Write-Step "Étape 3/5 — Build image pipeline…"
Invoke-Expression "$ComposeAll build --quiet pipeline-workers"
Write-Ok "Image dakar-pipeline prête"

# ── Étape 4 : Entraînement initial ────────────────────────────────────────────
if (-not $NoTrain) {
    $rfOk = Test-Path "$ModelsDir\calibration_rf_pm25.pkl"
    $ifOk = Test-Path "$ModelsDir\anomaly_if.pkl"

    if ($rfOk -and $ifOk) {
        Write-Ok "Étape 4/5 — Modèles déjà présents (skip)"
    } else {
        Write-Step "Étape 4/5 — Entraînement initial des modèles (~2 min)…"
        Write-Step "  (RF calibration + Isolation Forest sur données synthétiques)"
        Write-Step "  (LSTM et Prophet entraînés automatiquement après accumulation de données réelles)"

        if (-not (Test-Path $ModelsDir)) {
            New-Item -ItemType Directory -Path $ModelsDir -Force | Out-Null
        }

        $absModels = (Resolve-Path $ModelsDir).Path
        $trainCmd = "$ComposeAll run --rm " +
                    "-v `"$($absModels):/app/models`" " +
                    "pipeline-workers " +
                    "python training/train_all.py --no-download --skip prophet lstm --epochs 5"
        Invoke-Expression $trainCmd
        Write-Ok "Modèles de base entraînés"
    }
} else {
    Write-Warn "Étape 4/5 — Entraînement skippé (-NoTrain) — pipeline en mode fallback"
}

# ── Étape 5 : Pipeline permanent ─────────────────────────────────────────────
Write-Step "Étape 5/5 — Démarrage du pipeline (permanent)…"
Invoke-Expression "$ComposeAll up -d"

if ($WithSim) {
    Write-Step "Démarrage du simulateur de capteurs…"
    $simLog = "$env:TEMP\dakar-simulator.log"
    Start-Process -FilePath "python" `
        -ArgumentList "data_generator.py --sensor-ids ESP32-DK-MEDINA-001 ESP32-DK-PLATEAU-001" `
        -WorkingDirectory (Resolve-Path ".\simulation").Path `
        -RedirectStandardOutput $simLog `
        -WindowStyle Hidden
    Write-Ok "Simulateur démarré (logs : $simLog)"
}

# ── Résumé ────────────────────────────────────────────────────────────────────
Write-Hr
Write-Host ""
Write-Host "  Plateforme démarrée — tout tourne en permanence" -ForegroundColor Green
Write-Host ""
Invoke-Expression "$ComposeAll ps"
Write-Host ""
Write-Hr
Write-Host ""
Write-Host "  Services actifs :" -ForegroundColor Cyan
Write-Host "    dakar-mosquitto         — Broker MQTT           port 1883"
Write-Host "    dakar-postgres          — PostgreSQL+PostGIS     port 5432"
Write-Host "    dakar-influxdb          — InfluxDB               port 8086  (UI: http://localhost:8086)"
Write-Host "    dakar-pipeline-workers  — Ingestion · Calibration · Anomaly (supervisord)"
Write-Host "    dakar-pipeline-flows    — Features · Prédictions · Kriging · NLP · Monitoring · Retraining"
Write-Host ""
Write-Host "  Commandes utiles :" -ForegroundColor Cyan
Write-Host "    .\start.ps1 -Logs       Logs en direct"
Write-Host "    .\start.ps1 -Status     État des conteneurs"
Write-Host "    .\start.ps1 -Down       Arrêt propre"
Write-Host "    .\start.ps1 -Restart    Redémarre le pipeline sans rebuild"
Write-Host "    .\start.ps1 -WithSim    Relancer avec le simulateur de capteurs"
Write-Host ""
Write-Hr
