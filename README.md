# Plateforme Surveillance Citoyenne de la Pollution — Dakar

Projet PPP DIC2 · ESP Dakar (IABD — IA & Big Data)

Plateforme bout-en-bout de surveillance de la qualité de l'air : ingestion IoT (MQTT),
calibration, détection d'anomalies, prévisions ML, interpolation spatiale (kriging),
NLP des signalements citoyens, API REST et **deux interfaces** — un dashboard citoyen
(port 3000) et un centre de supervision data-warehouse du pipeline (port 9090).

---

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
1. Démarre Postgres · InfluxDB · Mosquitto · Redis (attend `healthy`)
2. Applique les migrations SQL (idempotent)
3. Build les images pipeline + **simulateur** + backend + frontend (multi-stage, légères)
4. Entraîne **et enregistre** les modèles s'ils sont absents : RandomForest, IsolationForest,
   LSTM, Prophet (LSTM/Prophet sautés automatiquement si `torch`/`prophet` ne sont pas dans l'image)
5. Démarre toute la stack : workers · flows · **simulateur** · backend · frontend (permanent)

Le **simulateur de capteurs démarre automatiquement** (service `dakar-simulator`) et publie
en continu sur MQTT — le dashboard n'est jamais vide.

---

## Commandes utiles

| Objectif | Linux/macOS | Windows |
|---|---|---|
| Logs en direct | `./start.sh --logs` | `.\start.ps1 -Logs` |
| État des conteneurs | `./start.sh --status` | `.\start.ps1 -Status` |
| Arrêt propre | `./start.sh --down` | `.\start.ps1 -Down` |
| Redémarrage pipeline | `./start.sh --restart` | `.\start.ps1 -Restart` |
| Sans entraînement | `./start.sh --no-train` | `.\start.ps1 -NoTrain` |
| Backup modèles | `./backup_models.sh save` | — |
| Restaurer modèles | `./backup_models.sh restore` | — |

> Le simulateur est désormais un service Docker permanent : l'option `--with-sim`
> (lancement hôte) reste disponible mais n'est plus nécessaire.

---

## Les deux interfaces

### 1. Dashboard citoyen — `http://localhost:3000`

Application React/Vite (recharts + Leaflet + Tailwind), data-viz riche :

| Page | Route | Contenu |
|---|---|---|
| **Dashboard** | `/` | KPIs réseau, jauge IQA, aire multi-polluants 24h, classement zones, radar polluants, carte kriging, **prévision PM2.5 avec bande de confiance**, conseil santé |
| **Carte** | `/map` | Carte Leaflet + heatmap kriging interpolée, marqueurs capteurs colorés |
| **Prédictions** | `/predictions` | Trajectoire prévue (IC 95 %), cartes par horizon, RMSE par horizon |
| **Comparer** | `/compare` | Classement PM2.5, barres groupées PM2.5/PM10, cartes zones |
| **Capteurs** | `/sensors` | KPIs réseau, donut disponibilité, barres batterie, sparklines PM2.5 par capteur |
| **Alertes** | `/alerts` | KPIs gravité, donut répartition, liste détaillée |
| **Signalements** | `/reports` | Formulaire citoyen + histogramme par jour + analyse NLP |
| **Zone** | `/zone/:id` | Détail d'une zone (historique multi-période, capteurs, signalements) |

### 2. Centre de supervision pipeline (data-warehouse) — `http://localhost:9090`

Interface multi-pages autonome (sidebar de navigation, graphes SVG maison, auto-refresh 5 s) :

| Page | Contenu |
|---|---|
| 🛰️ **Vue d'ensemble** | KPIs globaux, aire du débit d'ingestion, santé des flows, top zones |
| 📥 **Ingestion & Workers** | Débit MQTT, état réel des workers (supervisord), messages/capteur |
| 🗄️ **Données & Capteurs** | Volumétrie des tables, table capteurs (statut/âge/messages) |
| ✅ **Qualité pipeline** | 6 jauges **Q1–Q6** + évolution couverture/calibration |
| 🧠 **Modèles & ML** | Modèles enregistrés, métriques, calibration, R² |
| 🌫️ **Qualité de l'air** | Classement PM2.5, donut des niveaux, cartes zones |
| 🚨 **Événements** | Anomalies & alertes récentes, donut gravité |

Endpoints du serveur 9090 : `/` (dashboard), `/api/overview` (JSON riche), `/metrics`
(format Prometheus), `/health`.

### 3. API FastAPI — `http://localhost:8000`

REST + SSE. Swagger : `/docs`, Redoc : `/redoc`. Le frontend passe par le proxy nginx `/api`.

**Pipeline Control Center** (sous `/pipeline` dans le dashboard) : pages temps réel SSE
(workers, flows, anomalies, alertes, modèles, dataflow, logs, calibration) alimentées par
les routes `/pipeline/*` du backend.

---

## Authentification & Sécurité

| Fonctionnalité | Détail |
|---|---|
| JWT | RS256 (prod) / HS256 (dev), access + refresh tokens |
| RBAC | 6 rôles : citizen < researcher < analyst < operator < admin < super_admin |
| Rate limiting | slowapi, limites par endpoint (5/min login → 100/min public) |
| MFA (opt-in) | TOTP via pyotp — `/auth/mfa/enable|verify|disable|status` |
| Chiffrement au repos | Fernet AES-256 (opt-in `ENCRYPTION_KEY`), déterministe pour l'email |
| RGPD | `DELETE /auth/me`, `POST /admin/gdpr/erase`, consentement |
| Audit logging | Table `audit_logs` partitionnée |
| PKI mTLS | Root CA → Intermediate CA → Server + 9 clients |

Comptes démo (si `BACKEND_SEED_DEMO_USERS=true`) :
`citizen@demo.dakar-pollution.sn` / `citizen-demo-2026` (idem researcher/admin).

---

## Pipeline — Workers & Flows

### Workers permanents (supervisord)

| Worker | Rôle | Technologies |
|---|---|---|
| **Ingestion** | MQTT → InfluxDB `air_quality_raw` | paho-mqtt, Pydantic, batch write, dead letter, circuit breaker |
| **Calibration** | Raw → Cleansed | RandomForest + Kalman 1D, hot-reload, fallback linéaire |
| **Anomaly Detector** | 3 niveaux | Seuils fixes (N1), Isolation Forest + scaler (N2), règles structurelles (N3), PG NOTIFY |
| **Metrics** | Centre de supervision 9090 | Collecte Postgres+InfluxDB, sert `/`, `/api/overview`, `/metrics` |

### Flows planifiés (APScheduler)

| Flow | Fréquence | Description |
|---|---|---|
| **Feature Engineering** | 5 min | Features → `feature_store` |
| **Predictions** | 30 min | LSTM + Prophet + fallback seuils (cold-start), IC 95 % |
| **Kriging** | 1h | GPR, grille 200×200, GeoJSON → `kriging_results` |
| **NLP** | 1h | spaCy NER, embeddings pgvector |
| **Monitoring** | 1h | Métriques Q1–Q6 → `data_quality_metrics` |
| **Retraining** | 6h | Réentraînement RF/IF/LSTM/Prophet sur données accumulées |

Un **bootstrap** exécute une fois les flows producteurs au premier démarrage (tables vides)
pour peupler immédiatement le dashboard sans attendre le premier cycle.

### Indicateurs qualité Q1–Q6 (monitoring)

| Code | Indicateur | Seuil d'alerte |
|---|---|---|
| Q1 | Couverture données (reçu/attendu) | < 0.80 |
| Q2 | Taux de calibration (cleansed/raw) | < 0.90 |
| Q3 | RMSE prédictions +1h | > 15 |
| Q4 | RMSE prédictions +24h | > 25 |
| Q5 | Taux de fausses alertes | > 0.30 |
| Q6 | Latence pipeline p95 (ms) | — |

> Q3/Q4/Q6 restent vides tant que les données ne sont pas matures (prédictions arrivées
> à échéance, latence mesurable) — comportement normal de cold-start.

---

## Modèles ML & registre

Chaque script d'entraînement **enregistre automatiquement** son modèle dans la table
PostgreSQL `models` (via `training/registry.py`) — la page Modèles (3000 et 9090) reflète
les modèles réellement entraînés et actifs.

| Modèle | Type | Fichier | Rôle |
|---|---|---|---|
| `calibration_rf_pm25` | RandomForest | `calibration_rf_pm25.pkl` | Calibration capteurs |
| `anomaly_if` | IsolationForest | `anomaly_if.pkl` + scaler | Détection d'anomalies (8 features, `decision_function`) |
| `lstm_full` | LSTM | `lstm_full.pt` + `feature_scaler.pkl` | Prédiction PM2.5 (modèle principal) |
| `lstm_light` | LSTM | `lstm_light.pt` + scaler light | Prédiction allégée |
| `prophet_pm25` | Prophet | `prophet_pm25.pkl` | Prédiction par tendance/saisonnalité |
| `threshold_fallback` | (règle) | — | Repli cold-start (< 1 jour de données) |

> **torch** et **prophet** sont volumineux (~+1 Go) ; ils sont compilés dans l'étage
> *builder* du `Dockerfile` (g++ pour cmdstan) et confinés au runtime via build multi-stage.
> `start.sh`/`start.ps1` détectent leur présence et sautent LSTM/Prophet si l'image est gardée légère.

---

## Simulation IoT

Service Docker `dakar-simulator` (démarrage auto) ou lancement manuel :

```bash
cd simulation
python data_generator.py --broker localhost --duration 3600
```

| Module | Description |
|---|---|
| `data_generator.py` | Publie les mesures sur MQTT (`--duration 0` = continu) |
| `sensor_models.py` | PMS5003, BME280, MICS-6814, O₃ virtuel |
| `atmospheric_models.py` | Cycles PM2.5, Harmattan, saison des pluies, 10 zones |
| `anomaly_injector.py` | 8 types d'anomalies (SPIKE, STUCK, DROPOUT, DRIFT…) |
| `firmware_v*_sim.py` | V0 simple · V1 (SPIFFS buffer, OTA, solaire) |
| `lora_*_sim.py` | Okumura-Hata 868 MHz, AES-128-CTR, SF7-SF12 |

---

## Base de données

### PostgreSQL
Extensions : PostGIS, pgvector, ltree, pgcrypto, uuid-ossp, pg_trgm.

| Module | Tables |
|---|---|
| Spatial | `zones`, `ref_stations`, `sensors`, `air_quality` |
| IA & Modèles | `models`, `calibration`, `predictions`, `anomaly_detections`, `alerts` |
| Citoyen & NLP | `citizens`, `reports`, `report_entities`, `report_embeddings`, `anomaly_labels` |
| Features & Kriging | `feature_store`, `kriging_grid`, `kriging_results`, `data_gaps` |
| Qualité & Sécurité | `data_quality_metrics`, `audit_logs` (partitionné), `users`, `pipeline_events` |

### InfluxDB

| Bucket | Rétention | Mesures |
|---|---|---|
| `bucket_raw` | 7 jours | `air_quality_raw` |
| `bucket_cleansed` | 2 ans | `air_quality_cleansed`, `sensor_health` |
| `bucket_downsampled` | ∞ | `air_quality_hourly`, `air_quality_daily`, `iqa_daily` |

> Les historiques du dashboard (`/aqi/history`, toutes résolutions) sont agrégés à la volée
> depuis `bucket_cleansed` (rétention 2 ans) — pas de dépendance au bucket downsampled.

---

## TLS MQTT (mTLS)

```bash
sh infra/mosquitto/certs/generate_certs.sh
docker compose -f docker-compose.infra.yml restart mosquitto
```

---

## Architecture

```
implementation/
├── docker-compose.infra.yml        # Postgres · InfluxDB · Mosquitto · Redis
├── docker-compose.pipeline.yml     # Workers · Flows · Simulateur
├── docker-compose.app.yml          # Backend FastAPI · Frontend React/Nginx
├── start.sh / start.ps1            # Point d'entrée (Linux·macOS·WSL / Windows)
├── backup_models.sh                # Sauvegarde/restauration des modèles
│
├── infra/                          # Init SQL · config InfluxDB+tâches · PKI MQTT
│
├── pipeline/
│   ├── workers/                    # Ingestion · Calibration · Anomaly
│   ├── flows/                      # Features · Prédictions · Kriging · NLP · Monitoring · Retraining
│   ├── training/                   # Génération données · entraînement · registry.py
│   ├── models/                     # Modèles sérialisés (bind mount hôte, persistants)
│   ├── metrics.py                  # Serveur 9090 (collecte + endpoints)
│   ├── dashboard_html.py           # Interface data-warehouse multi-pages (9090)
│   └── run_flows.py                # Scheduler APScheduler + bootstrap
│
├── backend/app/                    # routers · models · security · middleware · db · utils
├── frontend/src/                   # pages · components(charts,map,ui) · hooks · lib · store · types
└── simulation/                     # Simulateur IoT (capteurs · atmosphère · LoRa)
```

---

## Services et ports

| Service | Port | Accès |
|---|---|---|
| **Dashboard citoyen** | 3000 | http://localhost:3000 |
| **Pipeline Control Center** | 3000 | http://localhost:3000/pipeline |
| **Supervision data-warehouse** | 9090 | http://localhost:9090 |
| **API FastAPI** | 8000 | http://localhost:8000/docs |
| PostgreSQL + PostGIS + pgvector | 5432 | `psql -U dakar_admin -d dakar_pollution` |
| InfluxDB | 8086 | http://localhost:8086 |
| Mosquitto MQTT | 1883 / 8883 (TLS) | mqtt://localhost:1883 |
| Redis | 6379 | redis-cli |

---

## Développement

```bash
# Frontend (proxy /api → :8000)
cd frontend && npm install && npm run dev

# Backend
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload
```
