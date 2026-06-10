// Tâche InfluxDB — compute_iqa_daily
// Extrait de 02_influxdb_config.flux (MODULE 4) pour déploiement via 'influx task create'
// Source : bucket_downsampled/air_quality_daily -> Destination : bucket_downsampled/iqa_daily
// NB : import déplacé avant 'option task' (convention Flux : imports en tête de fichier)
// NB : 'every' retiré — InfluxDB rejette un task option combinant 'cron' et 'every'
// (le fichier de référence en contenait les deux ; on garde 'cron' pour respecter
// l'horaire documenté dans CHOIX_TECHNIQUES.md / PIPELINE_SPEC.md : "45 0 * * *").

import "math"

option task = {
    name: "compute_iqa_daily",
    cron: "45 0 * * *",
}


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
