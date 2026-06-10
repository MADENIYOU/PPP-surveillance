// Tâche InfluxDB — monitor_sensor_freshness
// Extrait de 02_influxdb_config.flux (MODULE 5) pour déploiement via 'influx task create'
// Source : bucket_raw/air_quality_raw -> Destination : bucket_cleansed/sensor_health

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

