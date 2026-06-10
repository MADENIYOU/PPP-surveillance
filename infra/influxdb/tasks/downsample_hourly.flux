// Tâche InfluxDB — downsample_hourly
// Extrait de 02_influxdb_config.flux (MODULE 2) pour déploiement via 'influx task create'
// Source : bucket_cleansed/air_quality_cleansed -> Destination : bucket_downsampled/air_quality_hourly

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
