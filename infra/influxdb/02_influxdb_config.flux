// ============================================================================
// SCRIPT D'INITIALISATION INFLUXDB — VERSION FINALE CONSOLIDÉE
// Projet : Surveillance Citoyenne de la Pollution à Dakar (DIC2)
// Usage  : voir MODULE 6 — Déploiement CLI
// Outil  : InfluxDB OSS 2.x — Flux language
// ============================================================================
//
// STRUCTURE :
//   MODULE 1 — Buckets : création, rétentions, schéma des measurements
//   MODULE 2 — Tâche 1 : downsample_hourly   (toutes les heures à H+05m)
//   MODULE 3 — Tâche 2 : downsample_daily    (chaque jour à 00h30 UTC)
//   MODULE 4 — Tâche 3 : compute_iqa_daily   (chaque jour à 00h45 UTC)
//   MODULE 5 — Tâche 4 : monitor_sensor_freshness (toutes les 5 min)
//   MODULE 6 — Déploiement CLI (buckets, tâches, tokens)
//   MODULE 7 — Requêtes de référence pipeline (calibration, anomalies, features, kriging)
//   MODULE 8 — Requêtes de vérification post-déploiement
// ============================================================================


// ════════════════════════════════════════════════════════════════════════════
// MODULE 1 : BUCKETS — RÉTENTIONS & SCHÉMA DES MEASUREMENTS
// ════════════════════════════════════════════════════════════════════════════
// Les buckets se créent via CLI (voir MODULE 6).
// Ce bloc documente le schéma complet de chaque bucket.

// ── 1. BUCKET_RAW ────────────────────────────────────────────────────────────
// Rôle      : Réception brute des mesures ESP32 via MQTT (at-least-once, QoS 1)
// Rétention : 7 jours (168h) — données périssables, utiles pour débogage et ré-entraînement
// Écriture  : subscriber MQTT Python (token mqtt_subscriber_write)
// Lecture   : pipeline calibration (token calibration_pipeline)
//
// Measurement : air_quality_raw
//
// Tags (indexés, cardinalité faible) :
//   sensor_id     string   Identifiant matériel (ex: "ESP32_042")
//                          = sensors.serial_number dans PostgreSQL
//   zone_id       string   FK vers PostgreSQL.zones.id (ex: "15")
//   sensor_type   string   "PMS5003" | "SDS011" | "BME280" | "CCS811" | "MQ135"
//   protocol      string   Toujours "mqtt" pour ce bucket
//
// Fields (valeurs numériques) :
//   pm25          float    Particules fines 2.5µm  (µg/m³)   [0.0 – 1000.0]
//   pm10          float    Particules fines 10µm   (µg/m³)   [0.0 – 1000.0]
//   pm1_0         float    Particules ultrafines   (µg/m³)   [0.0 – 1000.0]
//   co            float    Monoxyde de carbone     (ppm)     [0.0 – 50.0]
//   co2           float    Dioxyde de carbone      (ppm)     [0.0 – 5000.0]
//   no2           float    Dioxyde d'azote         (ppb)     [0.0 – 500.0]
//   o3            float    Ozone                   (ppb)     [0.0 – 500.0]
//   voc           float    Composés organiques     (ppb)     [0.0 – 1000.0]
//   temperature   float    Température ambiante    (°C)      [-10.0 – 60.0]
//   humidity      float    Humidité relative       (%)       [0.0 – 100.0]
//   pressure      float    Pression atmosphérique  (hPa)     [800.0 – 1100.0]
//   battery_level float    Niveau batterie         (%)       [0.0 – 100.0]
//   battery_voltage V      Tension batterie         (V)       [0.0 – 5.0]
//   panel_current A        Courant panneau solaire   (A)       [0.0 – 2.0]
//   rssi          int      Puissance signal WiFi   (dBm)     [-120 – 0]
//   uptime        int      Temps depuis reboot     (sec)     [0 – ∞]
//   seq           int      Numéro de séquence      (uint16)  [0 – 65535]
//
// Timestamp : précision nanoseconde. Converti depuis ts_unix (secondes) × 1_000_000_000.
//
// Exemple Line Protocol :
//   air_quality_raw,sensor_id=ESP32_042,sensor_type=PMS5003,zone_id=15,protocol=mqtt \
//     pm25=34.5,pm10=52.1,pm1_0=22.3,co=0.8,co2=412.0,no2=18.4,o3=32.1,voc=55.0,\
//     temperature=28.4,humidity=67.0,pressure=1013.2,battery_level=89.2,rssi=-62i,\
//     uptime=86400i,seq=4521i \
//     1683200000000000000

// ── 2. BUCKET_CLEANSED ───────────────────────────────────────────────────────
// Rôle      : Source de vérité — mesures après calibration RF + Filtre de Kalman
// Rétention : 2 ans (17520h)
// Écriture  : pipeline calibration (token calibration_pipeline)
// Lecture   : FastAPI, anomaly detector, feature engineering, kriging
//
// Measurement : air_quality_cleansed
//
// Tags :
//   sensor_id              string   Identique à bucket_raw
//   zone_id                string   Identique à bucket_raw
//   state                  string   "calibrated" | "kalman_filtered"
//
// Fields (héritent de air_quality_raw + champs calibration) :
//   pm25 … pressure        float    Valeurs calibrées (Random Forest + Kalman)
//   battery_level, rssi    float    Inchangés depuis raw
//   kalman_gain            float    Gain du filtre de Kalman [0.0 – 1.0]
//                                   0 = mesure ignorée, 1 = mesure brute retenue
//   confidence             float    Score de confiance global [0.0 – 1.0]
//   calibration_model_id   string   Référence au modèle RF (ex: "rf_v2.1")
//
// Measurement complémentaire : sensor_health
//   Tags   : sensor_id, zone_id
//   Fields : is_fresh (int, 1 = actif dans les 10 dernières minutes)
//   Écrit par : tâche monitor_sensor_freshness (MODULE 5)
//
// Exemple Line Protocol :
//   air_quality_cleansed,sensor_id=ESP32_042,zone_id=15,state=kalman_filtered \
//     pm25=31.2,pm10=48.7,co=0.7,no2=16.1,o3=29.8,temperature=28.1,humidity=66.4,\
//     kalman_gain=0.34,confidence=0.92,calibration_model_id="rf_v2.1" \
//     1683200000000000000

// ── 3. BUCKET_DOWNSAMPLED ────────────────────────────────────────────────────
// Rôle      : Agrégats horaires et journaliers + IQA — historique permanent
// Rétention : Infinie (0 = pas de TTL dans InfluxDB 2.x)
// Écriture  : tâches Flux (downsample_hourly, downsample_daily, compute_iqa_daily)
// Lecture   : FastAPI /aqi/history, /timeseries, études épidémiologiques
//
// Measurement : air_quality_hourly
//   Tags   : zone_id, pollutant ("pm25"|"pm10"|"co"|"no2"|"o3")
//   Fields : mean, min, max, stddev, p50, p95, sensor_count
//
// Measurement : air_quality_daily
//   Tags   : zone_id, pollutant
//   Fields : mean, min, max, stddev, p50, p95, exceedance_hours, sensor_count
//            exceedance_hours = nb d'heures où la moyenne horaire dépasse le seuil OMS
//
// Measurement : iqa_daily
//   Tags   : zone_id
//   Fields : iqa_value (int), pm25_iqa, pm10_iqa, co_iqa, no2_iqa, o3_iqa
//   Attrs  : iqa_category (string tag), dominant_pollutant (string tag)
//
// Volume estimé (50 capteurs, 2 ans) :
//   bucket_raw         → ~14 M points  (éphémère, 7j)
//   bucket_cleansed    → ~50 M points  (2 ans, ~10 Go compressés)
//   bucket_downsampled → ~450 K/an     (infini, négligeable)


// ════════════════════════════════════════════════════════════════════════════
// MODULE 2 : TÂCHE 1 — DOWNSAMPLING HORAIRE
// ════════════════════════════════════════════════════════════════════════════
// Source      : bucket_cleansed → air_quality_cleansed
// Destination : bucket_downsampled → air_quality_hourly
// Fréquence   : toutes les heures
// Offset      : +5 min — laisse le temps au micro-batch calibration (boucle 30s)
//               de terminer avant que la tâche lise bucket_cleansed
// Statistiques: mean, min, max, stddev, p50 (médiane), p95, sensor_count
// Polluants   : pm25, pm10, co, no2, o3

option task = {
    name  : "downsample_hourly",
    every : 1h,
    offset: 5m,
}

// ── Moyenne horaire ──────────────────────────────────────────────────────────
meanHourly = from(bucket: "bucket_cleansed")
    |> range(start: -1h)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> set(key: "_measurement", value: "air_quality_hourly")
    |> rename(columns: {_field: "pollutant", _value: "mean"})

// ── Minimum horaire ──────────────────────────────────────────────────────────
minHourly = from(bucket: "bucket_cleansed")
    |> range(start: -1h)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(every: 1h, fn: min, createEmpty: false)
    |> rename(columns: {_value: "min"})

// ── Maximum horaire (pics de pollution) ──────────────────────────────────────
maxHourly = from(bucket: "bucket_cleansed")
    |> range(start: -1h)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(every: 1h, fn: max, createEmpty: false)
    |> rename(columns: {_value: "max"})

// ── Écart-type horaire (variabilité intra-heure) ──────────────────────────────
stddevHourly = from(bucket: "bucket_cleansed")
    |> range(start: -1h)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(every: 1h, fn: stddev, createEmpty: false)
    |> rename(columns: {_value: "stddev"})

// ── Médiane horaire (p50) ─────────────────────────────────────────────────────
p50Hourly = from(bucket: "bucket_cleansed")
    |> range(start: -1h)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(
        every: 1h,
        fn: (tables=<-, column) => tables |> quantile(q: 0.5, method: "estimate_tdigest"),
        createEmpty: false,
    )
    |> rename(columns: {_value: "p50"})

// ── Percentile 95 horaire (indicateur réglementaire) ─────────────────────────
p95Hourly = from(bucket: "bucket_cleansed")
    |> range(start: -1h)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(
        every: 1h,
        fn: (tables=<-, column) => tables |> quantile(q: 0.95, method: "estimate_tdigest"),
        createEmpty: false,
    )
    |> rename(columns: {_value: "p95"})

// ── Nombre de capteurs actifs dans la zone (qualité de la fenêtre) ────────────
// Permet de détecter les heures avec peu de capteurs (zone dégradée).
sensorCountHourly = from(bucket: "bucket_cleansed")
    |> range(start: -1h)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) => r._field == "pm25")
    |> group(columns: ["zone_id"])
    |> aggregateWindow(
        every: 1h,
        fn: (tables=<-, column) => tables |> unique(column: "sensor_id") |> count(),
        createEmpty: false,
    )
    |> rename(columns: {_value: "sensor_count"})
    |> set(key: "_measurement", value: "air_quality_hourly")

// ── Écriture dans bucket_downsampled ─────────────────────────────────────────
union(tables: [meanHourly, minHourly, maxHourly, stddevHourly, p50Hourly, p95Hourly])
    |> set(key: "_measurement", value: "air_quality_hourly")
    |> to(bucket: "bucket_downsampled")

sensorCountHourly
    |> to(bucket: "bucket_downsampled")


// ════════════════════════════════════════════════════════════════════════════
// MODULE 3 : TÂCHE 2 — DOWNSAMPLING JOURNALIER
// ════════════════════════════════════════════════════════════════════════════
// Source      : bucket_cleansed → air_quality_cleansed
// Destination : bucket_downsampled → air_quality_daily
// Fréquence   : une fois par jour à 00h30 UTC
//               (heure fixe via cron — plus fiable que every:1d pour les études)
// Statistiques: mean, min, max, stddev, p50, p95, exceedance_hours, sensor_count
//
// exceedance_hours : nb d'heures dans la journée où la moyenne horaire dépasse
//   le seuil OMS 2021 (PM2.5 = 15 µg/m³ sur 24h). Indicateur réglementaire ANSD.

option task = {
    name: "downsample_daily",
    every: 1d,
    cron: "30 0 * * *",
}

// ── Moyenne journalière ───────────────────────────────────────────────────────
meanDaily = from(bucket: "bucket_cleansed")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(every: 1d, fn: mean, createEmpty: false)
    |> set(key: "_measurement", value: "air_quality_daily")
    |> rename(columns: {_field: "pollutant", _value: "mean"})

// ── Minimum journalier ────────────────────────────────────────────────────────
minDaily = from(bucket: "bucket_cleansed")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(every: 1d, fn: min, createEmpty: false)
    |> rename(columns: {_value: "min"})

// ── Maximum journalier ────────────────────────────────────────────────────────
maxDaily = from(bucket: "bucket_cleansed")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
    |> rename(columns: {_value: "max"})

// ── Écart-type journalier ─────────────────────────────────────────────────────
stddevDaily = from(bucket: "bucket_cleansed")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(every: 1d, fn: stddev, createEmpty: false)
    |> rename(columns: {_value: "stddev"})

// ── Médiane journalière (p50) ─────────────────────────────────────────────────
p50Daily = from(bucket: "bucket_cleansed")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(
        every: 1d,
        fn: (tables=<-, column) => tables |> quantile(q: 0.5, method: "estimate_tdigest"),
        createEmpty: false,
    )
    |> rename(columns: {_value: "p50"})

// ── Percentile 95 journalier (indicateur OMS / ANSD) ─────────────────────────
p95Daily = from(bucket: "bucket_cleansed")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) =>
        r._field == "pm25" or r._field == "pm10" or
        r._field == "co"   or r._field == "no2"  or r._field == "o3"
    )
    |> group(columns: ["zone_id", "_field"])
    |> aggregateWindow(
        every: 1d,
        fn: (tables=<-, column) => tables |> quantile(q: 0.95, method: "estimate_tdigest"),
        createEmpty: false,
    )
    |> rename(columns: {_value: "p95"})

// ── Exceedance hours PM2.5 (seuil OMS 2021 : 15 µg/m³ sur 24h) ──────────────
// Compte le nombre d'heures dans la journée où la moyenne horaire dépasse 15 µg/m³.
// Indicateur clé pour les rapports ANSD et les études épidémiologiques.
exceedancePM25 = from(bucket: "bucket_cleansed")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) => r._field == "pm25")
    |> group(columns: ["zone_id"])
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> map(fn: (r) => ({r with _value: if r._value > 15.0 then 1 else 0}))
    |> sum()
    |> rename(columns: {_value: "exceedance_hours"})
    |> set(key: "_measurement", value: "air_quality_daily")
    |> set(key: "pollutant", value: "pm25")

// ── Nombre de capteurs actifs dans la journée ─────────────────────────────────
sensorCountDaily = from(bucket: "bucket_cleansed")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
    |> filter(fn: (r) => r._field == "pm25")
    |> group(columns: ["zone_id"])
    |> aggregateWindow(
        every: 1d,
        fn: (tables=<-, column) => tables |> unique(column: "sensor_id") |> count(),
        createEmpty: false,
    )
    |> rename(columns: {_value: "sensor_count"})
    |> set(key: "_measurement", value: "air_quality_daily")

// ── Écriture dans bucket_downsampled ─────────────────────────────────────────
union(tables: [meanDaily, minDaily, maxDaily, stddevDaily, p50Daily, p95Daily])
    |> set(key: "_measurement", value: "air_quality_daily")
    |> to(bucket: "bucket_downsampled")

exceedancePM25
    |> to(bucket: "bucket_downsampled")

sensorCountDaily
    |> to(bucket: "bucket_downsampled")


// ════════════════════════════════════════════════════════════════════════════
// MODULE 4 : TÂCHE 3 — CALCUL IQA JOURNALIER
// ════════════════════════════════════════════════════════════════════════════
// Source      : bucket_downsampled → air_quality_daily (champ "mean")
// Destination : bucket_downsampled → iqa_daily
// Fréquence   : une fois par jour à 00h45 UTC (après downsample_daily à 00h30)
//
// Grille IQA : formule EPA US (AQI) — interpolation linéaire par tranche
// Polluants  : PM2.5, PM10, CO, NO2, O3
// IQA global : max des sous-indices (règle EPA — le polluant le plus dégradé domine)
//
// Tranches PM2.5 (µg/m³) → IQA :
//   0.0 – 12.0   → Good              (IQA   0 – 50)
//   12.0 – 35.4  → Moderate          (IQA  51 – 100)
//   35.4 – 55.4  → Unhealthy Sensit. (IQA 101 – 150)
//   55.4 – 150.4 → Unhealthy         (IQA 151 – 200)
//   150.4 – 250.4→ Very Unhealthy    (IQA 201 – 300)
//   > 250.4      → Hazardous         (IQA 301 – 500)

option task = {
    name: "compute_iqa_daily",
    every: 1d,
    cron: "45 0 * * *",
}

import "math"

// ── Sous-indice PM2.5 ─────────────────────────────────────────────────────────
pm25IQA = from(bucket: "bucket_downsampled")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_daily")
    |> filter(fn: (r) => r.pollutant == "pm25")
    |> filter(fn: (r) => r._field == "mean")
    |> group(columns: ["zone_id"])
    |> last()
    |> map(fn: (r) => ({
        r with
        _field: "pm25_iqa",
        _value: float(v:
            if r._value <= 12.0 then
                int(v: (r._value / 12.0) * 50.0)
            else if r._value <= 35.4 then
                int(v: ((r._value - 12.0) / (35.4 - 12.0)) * 49.0 + 51.0)
            else if r._value <= 55.4 then
                int(v: ((r._value - 35.4) / (55.4 - 35.4)) * 49.0 + 101.0)
            else if r._value <= 150.4 then
                int(v: ((r._value - 55.4) / (150.4 - 55.4)) * 49.0 + 151.0)
            else if r._value <= 250.4 then
                int(v: ((r._value - 150.4) / (250.4 - 150.4)) * 99.0 + 201.0)
            else
                int(v: math.mMin(x: ((r._value - 250.4) / (500.4 - 250.4)) * 199.0 + 301.0, y: 500.0))
        ),
    }))

// ── Sous-indice PM10 ──────────────────────────────────────────────────────────
pm10IQA = from(bucket: "bucket_downsampled")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_daily")
    |> filter(fn: (r) => r.pollutant == "pm10")
    |> filter(fn: (r) => r._field == "mean")
    |> group(columns: ["zone_id"])
    |> last()
    |> map(fn: (r) => ({
        r with
        _field: "pm10_iqa",
        _value: float(v:
            if r._value <= 54.0 then
                int(v: (r._value / 54.0) * 50.0)
            else if r._value <= 154.0 then
                int(v: ((r._value - 54.0) / 100.0) * 49.0 + 51.0)
            else if r._value <= 254.0 then
                int(v: ((r._value - 154.0) / 100.0) * 49.0 + 101.0)
            else if r._value <= 354.0 then
                int(v: ((r._value - 254.0) / 100.0) * 49.0 + 151.0)
            else if r._value <= 424.0 then
                int(v: ((r._value - 354.0) / 70.0) * 99.0 + 201.0)
            else
                int(v: math.mMin(x: ((r._value - 424.0) / 200.0) * 199.0 + 301.0, y: 500.0))
        ),
    }))

// ── Sous-indice NO2 (ppb) ─────────────────────────────────────────────────────
no2IQA = from(bucket: "bucket_downsampled")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_daily")
    |> filter(fn: (r) => r.pollutant == "no2")
    |> filter(fn: (r) => r._field == "mean")
    |> group(columns: ["zone_id"])
    |> last()
    |> map(fn: (r) => ({
        r with
        _field: "no2_iqa",
        _value: float(v:
            if r._value <= 53.0 then
                int(v: (r._value / 53.0) * 50.0)
            else if r._value <= 100.0 then
                int(v: ((r._value - 53.0) / 47.0) * 49.0 + 51.0)
            else if r._value <= 360.0 then
                int(v: ((r._value - 100.0) / 260.0) * 49.0 + 101.0)
            else
                int(v: math.mMin(x: ((r._value - 360.0) / 640.0) * 349.0 + 151.0, y: 500.0))
        ),
    }))

// ── Sous-indice O3 (ppb) ──────────────────────────────────────────────────────
o3IQA = from(bucket: "bucket_downsampled")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_daily")
    |> filter(fn: (r) => r.pollutant == "o3")
    |> filter(fn: (r) => r._field == "mean")
    |> group(columns: ["zone_id"])
    |> last()
    |> map(fn: (r) => ({
        r with
        _field: "o3_iqa",
        _value: float(v:
            if r._value <= 54.0 then
                int(v: (r._value / 54.0) * 50.0)
            else if r._value <= 70.0 then
                int(v: ((r._value - 54.0) / 16.0) * 49.0 + 51.0)
            else if r._value <= 85.0 then
                int(v: ((r._value - 70.0) / 15.0) * 49.0 + 101.0)
            else if r._value <= 105.0 then
                int(v: ((r._value - 85.0) / 20.0) * 49.0 + 151.0)
            else
                int(v: math.mMin(x: ((r._value - 105.0) / 95.0) * 99.0 + 201.0, y: 500.0))
        ),
    }))

// ── Sous-indice CO (ppm) ──────────────────────────────────────────────────────
coIQA = from(bucket: "bucket_downsampled")
    |> range(start: -1d)
    |> filter(fn: (r) => r._measurement == "air_quality_daily")
    |> filter(fn: (r) => r.pollutant == "co")
    |> filter(fn: (r) => r._field == "mean")
    |> group(columns: ["zone_id"])
    |> last()
    |> map(fn: (r) => ({
        r with
        _field: "co_iqa",
        _value: float(v:
            if r._value <= 4.4 then
                int(v: (r._value / 4.4) * 50.0)
            else if r._value <= 9.4 then
                int(v: ((r._value - 4.4) / 5.0) * 49.0 + 51.0)
            else if r._value <= 12.4 then
                int(v: ((r._value - 9.4) / 3.0) * 49.0 + 101.0)
            else if r._value <= 15.4 then
                int(v: ((r._value - 12.4) / 3.0) * 49.0 + 151.0)
            else if r._value <= 30.4 then
                int(v: ((r._value - 15.4) / 15.0) * 99.0 + 201.0)
            else
                int(v: math.mMin(x: ((r._value - 30.4) / 19.6) * 199.0 + 301.0, y: 500.0))
        ),
    }))

// ── IQA global = max des 5 sous-indices (règle EPA) ──────────────────────────
// Le polluant le plus dégradé détermine la catégorie globale.
allSubIndices = union(tables: [pm25IQA, pm10IQA, no2IQA, o3IQA, coIQA])
    |> group(columns: ["zone_id"])

iqaGlobal = allSubIndices
    |> max()
    |> map(fn: (r) => ({
        r with
        _field      : "iqa_value",
        _measurement: "iqa_daily",
        iqa_category: if r._value <= 50.0 then "good"
            else if r._value <= 100.0 then "moderate"
            else if r._value <= 150.0 then "unhealthy_sensitive"
            else if r._value <= 200.0 then "unhealthy"
            else if r._value <= 300.0 then "very_unhealthy"
            else "hazardous",
    }))

// ── Écriture IQA dans bucket_downsampled ─────────────────────────────────────
union(tables: [iqaGlobal, pm25IQA, pm10IQA, no2IQA, o3IQA, coIQA])
    |> set(key: "_measurement", value: "iqa_daily")
    |> to(bucket: "bucket_downsampled")


// ════════════════════════════════════════════════════════════════════════════
// MODULE 5 : TÂCHE 4 — MONITORING FRAÎCHEUR DES CAPTEURS
// ════════════════════════════════════════════════════════════════════════════
// Source      : bucket_raw → air_quality_raw
// Destination : bucket_cleansed → sensor_health
// Fréquence   : toutes les 5 minutes
// Objectif    : détecter les capteurs silencieux (aucune donnée depuis > 10 min)
//               et écrire un flag is_fresh dans bucket_cleansed.
//               Le pipeline de calibration Python lit ce flag pour savoir
//               quels capteurs inclure dans la fenêtre de calibration.
//
// Logique :
//   - Les capteurs présents dans la fenêtre -10m → is_fresh = 1 (actif)
//   - Les capteurs absents n'apparaissent pas → le pipeline les considère inactifs
//   - Une alerte PostgreSQL est générée côté Python si is_fresh = 0 pendant > 30 min

option task = {
    name : "monitor_sensor_freshness",
    every: 5m,
}

from(bucket: "bucket_raw")
    |> range(start: -10m)
    |> filter(fn: (r) => r._measurement == "air_quality_raw")
    |> filter(fn: (r) => r._field == "pm25")
    |> group(columns: ["sensor_id", "zone_id"])
    |> last()
    |> map(fn: (r) => ({
        r with
        _measurement: "sensor_health",
        _field      : "is_fresh",
        _value      : 1,
    }))
    |> to(bucket: "bucket_cleansed")


// ════════════════════════════════════════════════════════════════════════════
// MODULE 6 : DÉPLOIEMENT CLI — SÉQUENCE COMPLÈTE
// ════════════════════════════════════════════════════════════════════════════
// Séquence d'initialisation sur un serveur InfluxDB 2.x vierge.
// Adapter ORG_NAME, ADMIN_USER, ADMIN_PASSWORD selon l'environnement.
//
// IMPORTANT : influx task create ne supporte qu'un seul bloc option task par
// fichier. Extraire chaque tâche dans un fichier séparé avant de les déployer.
// Voir l'arborescence recommandée ci-dessous.
//
// Arborescence recommandée :
//   influxdb/
//   ├── 03_influxdb_config_final.flux   ← ce fichier (documentation + référence)
//   ├── tasks/
//   │   ├── downsample_hourly.flux      ← MODULE 2 extrait
//   │   ├── downsample_daily.flux       ← MODULE 3 extrait
//   │   ├── compute_iqa_daily.flux      ← MODULE 4 extrait
//   │   └── monitor_freshness.flux      ← MODULE 5 extrait
//   └── influxdb_setup.sh               ← script bash ci-dessous

// ── Étape 1 : Setup initial (une seule fois) ─────────────────────────────────
//
// influx setup \
//   --username dakar_admin \
//   --password <mot_de_passe_fort> \
//   --org dakar_pollution \
//   --bucket bucket_raw \
//   --retention 168h \
//   --force
//
// export INFLUX_ORG=dakar_pollution
// export INFLUX_HOST=http://localhost:8086
// export INFLUX_TOKEN=$(influx auth list --json | jq -r '.[0].token')

// ── Étape 2 : Créer les buckets manquants ────────────────────────────────────
//
// influx bucket create \
//   --name bucket_cleansed \
//   --org $INFLUX_ORG \
//   --retention 17520h \
//   --description "Données calibrées RF+Kalman — source de vérité — rétention 2 ans"
//
// influx bucket create \
//   --name bucket_downsampled \
//   --org $INFLUX_ORG \
//   --retention 0 \
//   --description "Agrégats horaires/journaliers + IQA — rétention infinie"

// ── Étape 3 : Déployer les 4 tâches Flux ─────────────────────────────────────
//
// influx task create --file tasks/downsample_hourly.flux  --org $INFLUX_ORG
// influx task create --file tasks/downsample_daily.flux   --org $INFLUX_ORG
// influx task create --file tasks/compute_iqa_daily.flux  --org $INFLUX_ORG
// influx task create --file tasks/monitor_freshness.flux  --org $INFLUX_ORG

// ── Étape 4 : Vérifier les tâches ────────────────────────────────────────────
//
// influx task list --org $INFLUX_ORG
// → doit afficher : downsample_hourly, downsample_daily,
//                   compute_iqa_daily, monitor_sensor_freshness

// ── Étape 5 : Créer les tokens d'accès par composant ─────────────────────────
// Principe du moindre privilège : chaque composant n'a accès qu'à ce dont il a besoin.
//
// # Récupérer les IDs des buckets
// RAW_ID=$(influx bucket list --name bucket_raw --json | jq -r '.[0].id')
// CLEANSED_ID=$(influx bucket list --name bucket_cleansed --json | jq -r '.[0].id')
// DOWN_ID=$(influx bucket list --name bucket_downsampled --json | jq -r '.[0].id')
//
// # Token subscriber MQTT → écriture bucket_raw uniquement
// influx auth create \
//   --write-bucket $RAW_ID \
//   --description "mqtt_subscriber_write" \
//   --org $INFLUX_ORG
//
// # Token pipeline calibration → lecture bucket_raw + écriture bucket_cleansed
// influx auth create \
//   --read-bucket  $RAW_ID \
//   --write-bucket $CLEANSED_ID \
//   --description "calibration_pipeline" \
//   --org $INFLUX_ORG
//
// # Token anomaly detector → lecture bucket_cleansed uniquement
// influx auth create \
//   --read-bucket $CLEANSED_ID \
//   --description "anomaly_detector_read" \
//   --org $INFLUX_ORG
//
// # Token feature engineering + kriging → lecture bucket_cleansed
// influx auth create \
//   --read-bucket $CLEANSED_ID \
//   --description "feature_kriging_read" \
//   --org $INFLUX_ORG
//
// # Token FastAPI (dashboard public) → lecture bucket_cleansed + bucket_downsampled
// influx auth create \
//   --read-bucket $CLEANSED_ID \
//   --read-bucket $DOWN_ID \
//   --description "fastapi_readonly" \
//   --org $INFLUX_ORG
//
// # Token tâches Flux (interne InfluxDB) → lecture + écriture tous buckets
// # Ce token est configuré dans InfluxDB UI > Tasks > Settings
// influx auth create \
//   --read-bucket  $RAW_ID \
//   --read-bucket  $CLEANSED_ID \
//   --read-bucket  $DOWN_ID \
//   --write-bucket $CLEANSED_ID \
//   --write-bucket $DOWN_ID \
//   --description "flux_tasks_internal" \
//   --org $INFLUX_ORG


// ════════════════════════════════════════════════════════════════════════════
// MODULE 7 : REQUÊTES DE RÉFÉRENCE PIPELINE
// ════════════════════════════════════════════════════════════════════════════
// Ces requêtes documentent les patterns de lecture utilisés par chaque
// composant Python du pipeline. Elles ne sont pas des tâches planifiées.
// Copier-coller dans le code Python via influxdb_client.query_api().query_data_frame()

// ── R1 : Calibration — lecture bucket_raw (fenêtre 90s) ──────────────────────
// Utilisé par : Étape 2 — Calibration (systemd, boucle sleep 30s)
// Fenêtre 90s : couvre les messages en retard réseau (QoS 1 at-least-once)
//
// from(bucket: "bucket_raw")
//     |> range(start: -90s)
//     |> filter(fn: (r) => r._measurement == "air_quality_raw")
//     |> filter(fn: (r) =>
//         r._field == "pm25"        or r._field == "pm10"     or
//         r._field == "co"          or r._field == "no2"      or
//         r._field == "o3"          or r._field == "temperature" or
//         r._field == "humidity"    or r._field == "pressure"
//     )
//     |> pivot(
//         rowKey    : ["_time", "sensor_id", "zone_id"],
//         columnKey : ["_field"],
//         valueColumn: "_value"
//     )

// ── R2 : Détection d'anomalies — lecture bucket_cleansed (5 min glissantes) ──
// Utilisé par : Étape 3 — Anomaly Detector (systemd, cron 1 min)
// Fenêtre 5 min : contexte temporel suffisant pour Isolation Forest / AutoEncoder
//
// from(bucket: "bucket_cleansed")
//     |> range(start: -5m)
//     |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
//     |> filter(fn: (r) =>
//         r._field == "pm25" or r._field == "pm10" or
//         r._field == "co"   or r._field == "no2"  or r._field == "o3"
//     )
//     |> pivot(
//         rowKey    : ["_time", "sensor_id", "zone_id"],
//         columnKey : ["_field"],
//         valueColumn: "_value"
//     )

// ── R3 : Feature Engineering — lecture bucket_cleansed (7 jours, agrégé 1h) ──
// Utilisé par : Étape 4 — Feature Engineering (Prefect, H+00)
// Agrégation 1h : réduit le volume avant jointure avec traffic + météo PostgreSQL
//
// from(bucket: "bucket_cleansed")
//     |> range(start: -7d)
//     |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
//     |> filter(fn: (r) =>
//         r._field == "pm25"     or r._field == "pm10"    or
//         r._field == "co"       or r._field == "no2"     or
//         r._field == "o3"       or r._field == "temperature" or
//         r._field == "humidity"
//     )
//     |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
//     |> group(columns: ["zone_id", "_field"])
//     |> pivot(
//         rowKey    : ["_time", "zone_id"],
//         columnKey : ["_field"],
//         valueColumn: "_value"
//     )

// ── R4 : Kriging — lecture bucket_cleansed (dernière heure, moyenne par capteur)
// Utilisé par : Étape 6 — Kriging (Prefect, H+10)
// Retourne une valeur moyenne par capteur pour alimenter GaussianProcessRegressor
//
// from(bucket: "bucket_cleansed")
//     |> range(start: -1h)
//     |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
//     |> filter(fn: (r) => r._field == "pm25" or r._field == "pm10")
//     |> group(columns: ["sensor_id", "zone_id", "_field"])
//     |> mean()
//     |> pivot(
//         rowKey    : ["sensor_id", "zone_id"],
//         columnKey : ["_field"],
//         valueColumn: "_value"
//     )

// ── R5 : Dashboard temps réel — IQA actuel par zone ──────────────────────────
// Utilisé par : GET /api/v1/aqi/current (FastAPI)
// Lit la dernière valeur IQA calculée par compute_iqa_daily
//
// from(bucket: "bucket_downsampled")
//     |> range(start: today())
//     |> filter(fn: (r) => r._measurement == "iqa_daily")
//     |> filter(fn: (r) => r._field == "iqa_value")
//     |> group(columns: ["zone_id"])
//     |> last()

// ── R6 : Dashboard historique — PM2.5 moyen sur 30 jours par zone ────────────
// Utilisé par : GET /api/v1/aqi/history (FastAPI, granularity=day)
//
// from(bucket: "bucket_downsampled")
//     |> range(start: -30d)
//     |> filter(fn: (r) => r._measurement == "air_quality_daily")
//     |> filter(fn: (r) => r.pollutant == "pm25")
//     |> filter(fn: (r) => r._field == "mean")
//     |> filter(fn: (r) => r.zone_id == "15")
//     |> keep(columns: ["_time", "_value", "zone_id"])

// ── R7 : Séries temporelles — PM2.5 sur 24h, intervalle 15 min ───────────────
// Utilisé par : GET /api/v1/timeseries (FastAPI, window=24h, interval=15m)
//
// from(bucket: "bucket_cleansed")
//     |> range(start: -24h)
//     |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
//     |> filter(fn: (r) => r._field == "pm25")
//     |> filter(fn: (r) => r.zone_id == "15")
//     |> aggregateWindow(every: 15m, fn: mean, createEmpty: false)
//     |> keep(columns: ["_time", "_value"])

// ── R8 : Analyse long terme — évolution mensuelle PM2.5 sur 1 an ─────────────
// Utilisé par : études épidémiologiques ANSD, rapports annuels
//
// from(bucket: "bucket_downsampled")
//     |> range(start: -1y)
//     |> filter(fn: (r) => r._measurement == "air_quality_daily")
//     |> filter(fn: (r) => r.pollutant == "pm25")
//     |> filter(fn: (r) => r._field == "mean")
//     |> aggregateWindow(every: 1mo, fn: mean, createEmpty: false)

// ── V0 : Vérifier les champs battery_voltage et panel_current ────────────────
// (added per SIMULATION_SPEC §5.1)
//
// from(bucket: "bucket_raw")
//   |> range(start: -1h)
//   |> filter(fn: (r) => r._field == "battery_voltage" or r._field == "panel_current")
//   |> limit(n: 1)

// ════════════════════════════════════════════════════════════════════════════
// MODULE 8 : REQUÊTES DE VÉRIFICATION POST-DÉPLOIEMENT
// ════════════════════════════════════════════════════════════════════════════
// À exécuter manuellement dans l'UI InfluxDB (Data Explorer) ou via CLI
// pour valider que la configuration est opérationnelle.

// ── V1 : bucket_raw reçoit des données (capteurs actifs) ─────────────────────
//
// from(bucket: "bucket_raw")
//     |> range(start: -15m)
//     |> filter(fn: (r) => r._measurement == "air_quality_raw")
//     |> filter(fn: (r) => r._field == "pm25")
//     |> group(columns: ["sensor_id"])
//     |> count()
// → Doit retourner une ligne par capteur actif avec _value > 0

// ── V2 : bucket_cleansed reçoit les données calibrées ────────────────────────
//
// from(bucket: "bucket_cleansed")
//     |> range(start: -5m)
//     |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
//     |> filter(fn: (r) => r._field == "pm25")
//     |> group(columns: ["sensor_id", "zone_id"])
//     |> count()
// → Doit retourner des lignes avec state=kalman_filtered

// ── V3 : Tâche downsample_hourly a bien tourné ───────────────────────────────
//
// from(bucket: "bucket_downsampled")
//     |> range(start: -2h)
//     |> filter(fn: (r) => r._measurement == "air_quality_hourly")
//     |> filter(fn: (r) => r._field == "mean")
//     |> group(columns: ["zone_id", "pollutant"])
//     |> count()
// → Doit retourner des lignes pour chaque zone × polluant

// ── V4 : IQA journalier calculé ──────────────────────────────────────────────
//
// from(bucket: "bucket_downsampled")
//     |> range(start: today())
//     |> filter(fn: (r) => r._measurement == "iqa_daily")
//     |> filter(fn: (r) => r._field == "iqa_value")
//     |> group(columns: ["zone_id"])
//     |> last()
// → Doit retourner une valeur IQA par zone avec iqa_category renseigné

// ── V5 : Alerte — zones où PM2.5 > 35 µg/m³ dans la dernière heure ───────────
//
// from(bucket: "bucket_cleansed")
//     |> range(start: -1h)
//     |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
//     |> filter(fn: (r) => r._field == "pm25")
//     |> filter(fn: (r) => r._value > 35.0)
//     |> group(columns: ["zone_id"])
//     |> last()
// → Résultat vide = aucune alerte. Sinon, zones à notifier.

// ── V6 : Capteurs silencieux (is_fresh absent depuis > 10 min) ────────────────
//
// from(bucket: "bucket_cleansed")
//     |> range(start: -15m)
//     |> filter(fn: (r) => r._measurement == "sensor_health")
//     |> filter(fn: (r) => r._field == "is_fresh")
//     |> group(columns: ["sensor_id"])
//     |> last()
// → Comparer avec la liste complète des capteurs dans PostgreSQL.sensors
//   pour identifier les capteurs absents (silencieux)

// ── V7 : Vérifier les 4 tâches enregistrées (CLI) ────────────────────────────
//
// influx task list --org $INFLUX_ORG
// → Doit afficher :
//   downsample_hourly       Active   every 1h   offset 5m
//   downsample_daily        Active   cron 30 0 * * *
//   compute_iqa_daily       Active   cron 45 0 * * *
//   monitor_sensor_freshness Active  every 5m

// ── V8 : Vérifier les rétentions des 3 buckets ───────────────────────────────
//
// influx bucket list --org $INFLUX_ORG
// → Doit afficher :
//   bucket_raw          168h0m0s    (7 jours)
//   bucket_cleansed     17520h0m0s  (2 ans)
//   bucket_downsampled  infinite    (0)

// ============================================================================
// FIN DU FICHIER
// ============================================================================