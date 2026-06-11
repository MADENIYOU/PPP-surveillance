# Plateforme Surveillance Pollution — Dakar

Projet PPP DIC2 · Sémestre 2

## Démarrage en une commande

### Linux / macOS / WSL

```bash
cd implementation
chmod +x start.sh
./start.sh
```

### Windows (PowerShell)

```powershell
cd implementation
.\start.ps1
```

> **Prérequis :** Docker Desktop en cours d'exécution. C'est tout.

Le script fait tout automatiquement :
1. Démarre Postgres, InfluxDB, Mosquitto
2. Applique les migrations SQL
3. Build l'image du pipeline
4. Entraîne les modèles de base (RF + Isolation Forest, ~2 min)
5. Lance workers + flows en permanence

---

## Commandes utiles

| Objectif | Linux/macOS | Windows |
|---|---|---|
| Logs en direct | `./start.sh --logs` | `.\start.ps1 -Logs` |
| État des conteneurs | `./start.sh --status` | `.\start.ps1 -Status` |
| Arrêt propre | `./start.sh --down` | `.\start.ps1 -Down` |
| Redémarrage pipeline | `./start.sh --restart` | `.\start.ps1 -Restart` |
| Avec simulateur capteurs | `./start.sh --with-sim` | `.\start.ps1 -WithSim` |
| Sans entraînement | `./start.sh --no-train` | `.\start.ps1 -NoTrain` |
| Backup modèles | `./backup_models.sh save` | — |
| Restaurer modèles | `./backup_models.sh restore` | — |

---

## Couche applicative (API + Dashboard)

```bash
# Backend FastAPI (port 8000, Swagger sur /docs) + Frontend React (port 3000)
docker compose -f docker-compose.infra.yml -f docker-compose.app.yml up -d --build
```

- **API** : `http://localhost:8000` — 28 endpoints REST + SSE stream.
  Swagger : `/docs`, Redoc : `/redoc`.
- **Dashboard** : `http://localhost:3000` — carte Leaflet + heatmap kriging,
  jauges IQA par zone, historique/prédictions, formulaire de signalement.
- **Pipeline Control Center** : `http://localhost:3000/pipeline` —
  dashboard temps réel SSE (métriques, workers, flows, modèles, anomalies, alertes).
- **Comptes démo** (si `BACKEND_SEED_DEMO_USERS=true`) :
  `citizen@demo.dakar-pollution.sn` / `citizen-demo-2026` (idem researcher/admin).
- **Dev frontend** : `cd frontend && npm install && npm run dev` (proxy /api → :8000).
- **Dev backend** : `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`.

### Authentification & Sécurité

| Fonctionnalité | Détail |
|---|---|
| JWT | RS256 (prod) / HS256 (dev), access + refresh tokens |
| RBAC | 6 rôles hiérarchiques : citizen < researcher < analyst < operator < admin < super_admin |
| Rate limiting | slowapi, limites configurées par endpoint (5/min login → 100/min public) |
| MFA (opt-in) | TOTP via pyotp — `POST /auth/mfa/enable`, `/verify`, `/disable`, `/status` |
| Chiffrement au repos | Fernet AES-256, opt-in via `ENCRYPTION_KEY` — chiffrement déterministe pour email |
| RGPD | `DELETE /auth/me` (droit à l'effacement), `POST /admin/gdpr/erase`, consentement |
| Audit logging | Table `audit_logs` partitionnée, toutes les opérations sensibles tracées |
| PKI mTLS | 3 niveaux : Root CA → Intermediate CA → Server + 9 clients |

---

## Pipeline Control Center (SSE temps réel)

```
http://localhost:3000/pipeline
```

| Page | Route | Contenu |
|---|---|---|
| **Pipeline** | `/pipeline` | Dashboard SSE : 6 métriques, statuts workers/flows, alertes push, modèles, infra |
| **Worker** | `/pipeline/worker/:name` | Détail ingestion/calibration/anomaly : throughput, dead letter, Kalman, LISTEN |
| **Flow** | `/pipeline/flow/:name` | Détail flows : coverage, RMSE horizons, radar chart, per-zone quality |
| **Anomalies** | `/pipeline/anomalies` | Explorer : filtres, pie chart, timeline, heatmap, pagination |
| **Alertes** | `/pipeline/alerts` | Manager : acquitter/résoudre/rejeter, bulk actions, trend chart |
| **Modèle** | `/pipeline/model/:name` | Détail modèle : historique RMSE, versions, hyperparamètres, comparaison |
| **DataFlow** | `/pipeline/dataflow` | Diagramme flux SVG interactif, throughput, latence, backpressure |
| **Capteurs** | `/pipeline/sensors` | Grille capteurs : sparklines PM2.5, batterie, RSSI, filtres, modal |
| **Logs** | `/pipeline/logs` | Stream logs : filtres service/niveau, pie/bar charts, export JSON/CSV |
| **Calibration** | `/pipeline/calibration` | Dérive calibration : line chart par capteur, histogram drift, R² comparison |

Le dashboard utilise **Server-Sent Events** (SSE) — une seule connexion TCP persistante,
latence < 1s, pas de polling. Événements push : `metrics` (5s), `status` (10s),
`alerts` (10s), `heartbeat` (1s).

---

## Pipeline — Workers & Flows

### Workers permanents (supervisord)

| Worker | Rôle | Technologies |
|---|---|---|
| **Ingestion** | MQTT → InfluxDB `air_quality_raw` | paho-mqtt, Pydantic, batch write, dead letter queue, circuit breaker |
| **Calibration** | Raw → Cleansed (RF + Kalman) | RandomForest, Kalman 1D, hot-reload modèle, fallback linéaire |
| **Anomaly Detector** | 3 niveaux de détection | Seuils fixes (N1), Isolation Forest (N2), règles structurelles (N3), PG NOTIFY temps réel |

### Flows planifiés (APScheduler)

| Flow | Fréquence | Description |
|---|---|---|
| **Feature Engineering** | 15 min | 73 features (F01-F73) → `feature_store` |
| **Predictions** | 30 min | LSTM + Prophet + fallback seuils, Monte Carlo Dropout CI |
| **Kriging** | 1h | GPR Matérn 3/2, grille 200×200, GeoJSON |
| **NLP** | 1h | spaCy NER, embeddings pgvector, corrélation spatio-temporelle |
| **Monitoring** | 1h | Q1-Q6 métriques (couverture, calibration rate, RMSE, FPR, latence p95) |
| **Retraining** | 24h-168h | Fine-tuning LSTM, réentraînement RF/IF/Prophet, archivage 3 versions |

### Modèles ML

| Modèle | Type | Fichier |
|---|---|---|
| Calibration RF | RandomForest (n=150, depth=12) | `calibration_rf_pm25.pkl` |
| Isolation Forest | IsolationForest (n=150, cont=0.03) | `anomaly_if.pkl` + scaler |
| LSTM Full | 2 couches LSTM, 128 hidden, 57→20→3 | `lstm_full.pt` + `feature_scaler.pkl` |
| LSTM Light | 1 couche LSTM, 64 hidden, 20→3 | `lstm_light.pt` + `feature_scaler_light.pkl` |
| Prophet | Prophet (changepoint=0.05) | `prophet_pm25.pkl` |

### Monitoring & Observabilité

| Composant | Port | Description |
|---|---|---|
| Prometheus `/metrics` | 9090 | Gauges/counters : ingestion, calibration, anomalies, alerts |
| structlog | — | Logging JSON structuré sur tous les workers/flows |
| Circuit breaker | — | `mqtt_breaker`, `nlp_breaker`, `weather_breaker` (failure_threshold=5) |
| Health checks | — | Tous les conteneurs Docker avec healthcheck intégré |

---

## Simulation IoT

```bash
cd simulation
python data_generator.py --sensor-ids ESP32-DK-MEDINA-001 ESP32-DK-PLATEAU-001 --duration 3600
```

| Module | Description |
|---|---|
| `data_generator.py` | Publie 5 topics MQTT : data, status, alert, gateway heartbeat, broadcast |
| `sensor_models.py` | PMS5003 (particules), BME280 (T/H/P), MICS-6814 (CO/NO₂/NH₃), O₃ virtuel |
| `atmospheric_models.py` | Cycles bimodaux PM2.5, Harmattan, saison des pluies, 10 zones Dakar |
| `anomaly_injector.py` | 8 types d'anomalies : SPIKE, STUCK, DROPOUT, DRIFT, OUTLIER, HARMATTAN… |
| `firmware_v*_sim.py` | V0 (simple, 30s), V1 (SPIFFS buffer, OTA, batterie solaire) |
| `lora_*_sim.py` | Okumura-Hata 868 MHz, AES-128-CTR, couverture SF7-SF12 |

---

## Base de données

### PostgreSQL — 26 tables

| Module | Tables |
|---|---|
| Spatial | `zones`, `ref_stations`, `sensors`, `air_quality` |
| IA & Modèles | `models`, `calibration`, `predictions`, `anomaly_detections`, `alerts` |
| Citoyen & NLP | `citizens`, `reports`, `report_entities`, `report_embeddings`, `anomaly_labels` |
| Santé | `participants`, `health_logs`, `mitigations` |
| Externes | `traffic_observations`, `external_weather` |
| Features & Kriging | `feature_store`, `kriging_grid`, `kriging_results`, `data_gaps` |
| Sécurité | `audit_logs` (partitionné), `users`, `pipeline_events`, `data_quality_metrics` |

Extensions : PostGIS, pgvector, ltree, pgcrypto, uuid-ossp, pg_trgm.

### InfluxDB — 3 buckets + 4 tâches

| Bucket | Rétention | Mesures |
|---|---|---|
| `bucket_raw` | 7 jours | `air_quality_raw` (pm25, pm10, co, no2, o3, T, H, P, batterie, RSSI) |
| `bucket_cleansed` | 2 ans | `air_quality_cleansed` (RF+Kalman), `sensor_health` |
| `bucket_downsampled` | ∞ | `air_quality_hourly`, `air_quality_daily`, `iqa_daily` |

---

## TLS MQTT (mTLS, S3.3)

```bash
# Génère la PKI 3 niveaux (Root CA → Intermediate CA → Server + 9 clients)
sh infra/mosquitto/certs/generate_certs.sh
docker compose -f docker-compose.infra.yml restart mosquitto
```

---

## Architecture

```
implementation/
├── docker-compose.infra.yml        # Postgres · InfluxDB · Mosquitto · Redis
├── docker-compose.pipeline.yml     # Workers (supervisord) + Flows (APScheduler)
├── docker-compose.app.yml          # Backend FastAPI + Frontend React/Nginx
├── start.sh                        # ← point d'entrée Linux/macOS/WSL
├── start.ps1                       # ← point d'entrée Windows PowerShell
├── backup_models.sh                # Sauvegarde/restauration des modèles ML
│
├── infra/
│   ├── postgres/init/              # 4 scripts SQL idempotents (01→04)
│   ├── influxdb/                   # Config Flux + setup script + 4 tâches
│   └── mosquitto/                  # Config MQTT + PKI 3 niveaux mTLS
│
├── pipeline/
│   ├── workers/                    # Ingestion MQTT · Calibration RF · Anomaly IF
│   ├── flows/                      # Features · Prédictions · Kriging · NLP · Monitoring · Retraining
│   ├── training/                   # Génération données · Téléchargement datasets · Entraînement
│   ├── models/                     # Modèles sérialisés (.pkl, .pt) — bind mount hôte
│   ├── models/archive/             # 3 dernières versions archivées par modèle
│   ├── models_def/                 # Architectures PyTorch + safe_load_model()
│   ├── db/                         # Clients Postgres + InfluxDB
│   ├── circuit_breaker.py          # Circuit breaker (MQTT, NLP, Weather)
│   ├── metrics.py                  # Prometheus /metrics endpoint (port 9090)
│   └── run_flows.py                # Scheduler APScheduler (démarre tous les flows)
│
├── backend/
│   ├── app/
│   │   ├── routers/               # 10 routeurs (auth, aqi, sensors, reports, predictions,
│   │   │                           #   map, alerts, export, admin, pipeline)
│   │   ├── models/                 # Pydantic (aqi, auth, predictions, reports, sensors)
│   │   ├── security/               # JWT, RBAC 6 rôles, rate limiting
│   │   ├── middleware/             # CORS, Security Headers, Request ID, Audit Logging
│   │   ├── db/                     # Postgres pool, Redis, InfluxDB clients, seed
│   │   └── utils/                  # IQA calculator, audit logger, encryption
│   └── tests/                      # test_auth_jwt.py, test_iqa.py
│
├── frontend/
│   └── src/
│       ├── pages/                  # 14 pages (Dashboard, Zone, Report, About + 10 pipeline)
│       ├── components/             # map/, charts/, ui/
│       ├── hooks/                  # useApi.ts (React Query) + usePipelineStream.ts (SSE)
│       ├── lib/                    # apiClient, iqaUtils, dateUtils, leafletFix
│       ├── store/                  # Zustand (selectedZone, historyPeriod)
│       └── types/                  # 40+ interfaces TypeScript
│
└── simulation/                     # Simulateur IoT complet (capteurs, atmosphère, LoRa)
```

---

## Services et ports

| Service | Port | UI / Accès |
|---|---|---|
| **Dashboard React** | 3000 | http://localhost:3000 |
| **Pipeline Control Center** | 3000 | http://localhost:3000/pipeline |
| **API FastAPI** | 8000 | http://localhost:8000/docs (Swagger) |
| PostgreSQL + PostGIS + pgvector | 5432 | psql -U dakar_admin -d dakar_pollution |
| InfluxDB | 8086 | http://localhost:8086 |
| Mosquitto MQTT | 1883 / 8883 (TLS) | mqtt://localhost:1883 |
| Redis | 6379 | redis-cli |
| **Prometheus metrics** | 9090 | http://localhost:9090/metrics |
