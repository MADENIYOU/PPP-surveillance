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

---

## Architecture

```
implementation/
├── docker-compose.infra.yml      # Postgres · InfluxDB · Mosquitto · Redis
├── docker-compose.pipeline.yml   # Workers (supervisord) + Flows (APScheduler)
├── start.sh                      # ← point d'entrée Linux/macOS/WSL
├── start.ps1                     # ← point d'entrée Windows PowerShell
│
├── infra/
│   └── postgres/init/            # Schémas SQL (01_schema.sql, 02_missing_tables.sql)
│
├── pipeline/
│   ├── workers/                  # Ingestion MQTT · Calibration RF · Anomaly IF
│   ├── flows/                    # Features · Prédictions · Kriging · NLP · Monitoring · Retraining
│   ├── training/                 # Génération données · Téléchargement datasets · Entraînement
│   ├── models/                   # Modèles sérialisés (.pkl, .pt)
│   ├── db/                       # Clients Postgres + InfluxDB
│   └── run_flows.py              # Scheduler APScheduler (démarre tous les flows)
│
└── simulation/                   # Simulateur de capteurs IoT (MQTT)
```

## Services et ports

| Service | Port | UI |
|---|---|---|
| PostgreSQL + PostGIS + pgvector | 5432 | — |
| InfluxDB | 8086 | http://localhost:8086 |
| Mosquitto MQTT | 1883 | — |
| Redis | 6379 | — |
