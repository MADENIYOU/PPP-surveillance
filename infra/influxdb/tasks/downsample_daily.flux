// Tâche InfluxDB — downsample_daily
// Extrait de 02_influxdb_config.flux (MODULE 3) pour déploiement via 'influx task create'
// Source : bucket_cleansed/air_quality_cleansed -> Destination : bucket_downsampled/air_quality_daily
// NB : 'every' retiré — InfluxDB rejette un task option combinant 'cron' et 'every'
// (le fichier de référence en contenait les deux ; on garde 'cron' pour respecter
// l'horaire documenté dans CHOIX_TECHNIQUES.md / PIPELINE_SPEC.md : "30 0 * * *").

option task = {
    name: "downsample_daily",
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
