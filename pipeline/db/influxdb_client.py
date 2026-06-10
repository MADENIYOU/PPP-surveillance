"""Connexion InfluxDB et helpers d'écriture — bucket `bucket_raw` (ingestion).

Référence : pipeline/PIPELINE_SPEC.md §2 + infra/influxdb/02_influxdb_config.flux
(schéma réellement provisionné par `influxdb_setup.sh` : buckets `bucket_raw`,
`bucket_cleansed`, `bucket_downsampled` — noms différents de l'exemple
`INFLUX_BUCKET = 'raw'` du §2.1 de la spec, qui est simplifié/indicatif).

Mapping `SensorPayload` → point `air_quality_raw` (résolution de la divergence
entre PIPELINE_SPEC §2.2, qui définit des champs `pm25`, `co_ppm`, `battery_pct`…
sur une mesure nommée `air_quality`, et 02_influxdb_config.flux, qui documente la
mesure réellement créée `air_quality_raw` avec des champs `pm25`, `co`, `no2`,
`o3`, `battery_level`… §32-65) :

  - On retient le nom de mesure et les noms de champs de `02_influxdb_config.flux`
    (c'est le bucket effectivement provisionné, et les tâches de downsampling
    déployées — `downsample_hourly.flux` — filtrent sur ces noms : pm25, pm10,
    co, no2, o3 — casser cette correspondance romprait le pipeline aval).
  - `co_ppm`→`co`, `no2_ppb`→`no2`, `o3_ppb_est`→`o3`, `pm2_5`→`pm25`,
    `temperature_c`→`temperature`, `humidity_pct`→`humidity`,
    `pressure_hpa`→`pressure`, `battery.level_pct`→`battery_level`,
    `network.rssi_dbm`→`rssi`.
  - Champs documentés dans 02_influxdb_config.flux mais absents du payload simulé
    (`co2`, `voc`, `uptime`) : omis (les capteurs simulés ne modélisent pas ces
    grandeurs — un point InfluxDB n'a pas besoin d'un schéma de champs fixe).
  - Champs présents dans le payload mais absents du schéma documenté
    (`nh3_ppm`, `buffer_pending`) : ajoutés en tant que champs supplémentaires
    (extension documentée — utiles au monitoring sans rien casser en aval).
  - Tags : `sensor_id`, `zone_id` (communs aux deux specs) + `firmware`, `stale`
    (utiles opérationnellement, présents dans l'algorithme §2.2). On omet
    `sensor_type`/`protocol` (02_influxdb_config.flux) : non disponibles dans
    `SensorPayload` et de cardinalité/valeur informative nulle ici (`protocol`
    serait constant `"mqtt"`).
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    import pandas as pd

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from models.pydantic_schemas import SensorPayload

INFLUX_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
INFLUX_TOKEN = os.environ.get("INFLUXDB_TOKEN", os.environ.get("INFLUXDB_ADMIN_TOKEN", ""))
INFLUX_ORG = os.environ.get("INFLUXDB_ORG", "dakar_pollution")
INFLUX_BUCKET_RAW = os.environ.get("INFLUXDB_BUCKET_RAW", "bucket_raw")

RAW_MEASUREMENT = "air_quality_raw"
STALE_THRESHOLD_S = 300  # > 5 min de décalage horloge ↔ réception (§2.2)


def get_influxdb_client() -> InfluxDBClient:
    """Construit un client InfluxDB à partir des variables d'environnement.

    `timeout` généreux (10s) : écriture batch synchrone depuis le worker
    d'ingestion, pas de contrainte de latence stricte côté MQTT callback
    (le buffer en mémoire absorbe les pics — cf. `flush_buffer`)."""
    return InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=10_000)


def is_stale(payload_timestamp: datetime, now: datetime | None = None) -> bool:
    """Vérification de fraîcheur anti-stale-data (§2.2 point 4).

    `> 5 min` d'écart entre l'horloge du capteur et l'heure de réception."""
    now = now or datetime.now(timezone.utc)
    ts = payload_timestamp if payload_timestamp.tzinfo else payload_timestamp.replace(tzinfo=timezone.utc)
    return abs((now - ts).total_seconds()) > STALE_THRESHOLD_S


def build_raw_point(payload: SensorPayload, zone_id: str, now: datetime | None = None) -> Point:
    """Construit un `Point` `air_quality_raw` à partir d'un payload validé.

    `zone_id` est résolu en amont par l'appelant (cf. `db.postgres_client.
    get_zone_for_sensor`) — l'ingestion ne doit pas dépendre d'un format
    particulier de zone (slug simulation vs ID PostgreSQL)."""
    m = payload.measurements
    point = (
        Point(RAW_MEASUREMENT)
        .tag("sensor_id", payload.sensor_id)
        .tag("zone_id", zone_id)
        .tag("firmware", payload.firmware)
        .tag("stale", str(is_stale(payload.timestamp, now)))
        .field("pm25", m.pm2_5)
        .field("pm10", m.pm10)
        .field("pm1_0", m.pm1_0)
        .field("co", m.co_ppm)
        .field("no2", m.no2_ppb)
        .field("o3", m.o3_ppb_est)
        .field("nh3_ppm", m.nh3_ppm)
        .field("temperature", m.temperature_c)
        .field("humidity", m.humidity_pct)
        .field("pressure", m.pressure_hpa)
        .field("battery_level", float(payload.battery.level_pct))
        .field("rssi", payload.network.rssi_dbm)
        .field("buffer_pending", payload.network.buffer_pending)
        .field("seq", payload.seq)
        .time(payload.timestamp, WritePrecision.S)
    )
    return point


class InfluxBatchWriter:
    """Écriture par lot dans `bucket_raw`, déclenchée par taille ou timeout
    (§2.1 `BATCH_SIZE`/`BATCH_TIMEOUT`). `flush()` est idempotent et sûr à
    appeler depuis le callback MQTT comme depuis le handler `SIGTERM`."""

    def __init__(self, client: InfluxDBClient, bucket: str = INFLUX_BUCKET_RAW):
        self._write_api = client.write_api(write_options=SYNCHRONOUS)
        self._bucket = bucket
        self._buffer: list[Point] = []
        self._lock = threading.Lock()

    def add(self, point: Point) -> int:
        """Ajoute un point au buffer. Retourne la taille courante du buffer
        (sous verrou — évite une race entre le callback MQTT et le flush
        périodique sur le seuil `BATCH_SIZE`, §2.2 points 6-7)."""
        with self._lock:
            self._buffer.append(point)
            return len(self._buffer)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    def flush(self) -> int:
        """Écrit le buffer courant et le vide. Retourne le nombre de points écrits."""
        with self._lock:
            if not self._buffer:
                return 0
            pending, self._buffer = self._buffer, []
        self._write_api.write(bucket=self._bucket, org=INFLUX_ORG, record=pending)
        return len(pending)

    def close(self) -> None:
        self.flush()
        self._write_api.close()


def write_points(client: InfluxDBClient, points: Iterable[Point], bucket: str = INFLUX_BUCKET_RAW) -> None:
    """Écriture directe (hors buffer), utilisée par les tests/démos."""
    write_api = client.write_api(write_options=SYNCHRONOUS)
    write_api.write(bucket=bucket, org=INFLUX_ORG, record=list(points))
    write_api.close()


# ============================================================================
# Helpers de lecture — workers calibration (§3) + anomaly_detector (§4) +
# flows feature_engineering (§5)
# ============================================================================
INFLUX_BUCKET_CLEANSED = os.environ.get("INFLUXDB_BUCKET_CLEANSED", "bucket_cleansed")
CLEANSED_MEASUREMENT = "air_quality_cleansed"

POLL_FIELDS = ["pm25", "pm10", "pm1_0", "co", "no2", "o3", "temperature", "humidity", "pressure"]
ALL_RAW_FIELDS = POLL_FIELDS + ["battery_level", "rssi", "nh3_ppm", "buffer_pending", "seq"]


def query_raw_recent(client: InfluxDBClient, lookback_s: int = 60) -> "pd.DataFrame":
    """Retourne un DataFrame des points `air_quality_raw` des `lookback_s` dernières
    secondes, pivoté (une ligne par point, une colonne par champ) — utilisé par le
    worker de calibration (§3.3 `read_influxdb_raw`)."""
    import pandas as pd
    flux = f"""
from(bucket: "{INFLUX_BUCKET_RAW}")
  |> range(start: -{lookback_s}s)
  |> filter(fn: (r) => r._measurement == "{RAW_MEASUREMENT}")
  |> filter(fn: (r) => {' or '.join(f'r._field == "{f}"' for f in ALL_RAW_FIELDS)})
  |> pivot(rowKey: ["_time", "sensor_id", "zone_id"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"], desc: false)
"""
    try:
        df = client.query_api().query_data_frame(flux, org=INFLUX_ORG)
        if isinstance(df, list):
            df = pd.concat(df, ignore_index=True) if df else pd.DataFrame()
        return df
    except Exception:
        return pd.DataFrame()


def query_cleansed_window(client: InfluxDBClient, sensor_id: str, hours: int = 2) -> "pd.DataFrame":
    """Retourne un DataFrame des points `air_quality_cleansed` pour un capteur
    donné sur les `hours` dernières heures — utilisé par le worker de détection
    d'anomalies (§4 Niveaux 2 et 3) et le flow feature engineering (§5)."""
    import pandas as pd
    flux = f"""
from(bucket: "{INFLUX_BUCKET_CLEANSED}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "{CLEANSED_MEASUREMENT}")
  |> filter(fn: (r) => r.sensor_id == "{sensor_id}")
  |> filter(fn: (r) => {' or '.join(f'r._field == "{f}"' for f in POLL_FIELDS)})
  |> pivot(rowKey: ["_time", "sensor_id", "zone_id"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"], desc: false)
"""
    try:
        df = client.query_api().query_data_frame(flux, org=INFLUX_ORG)
        if isinstance(df, list):
            df = pd.concat(df, ignore_index=True) if df else pd.DataFrame()
        return df
    except Exception:
        return pd.DataFrame()


def query_cleansed_zone_mean(client: InfluxDBClient, zone_id: str, hours: int = 1) -> dict[str, float]:
    """Moyenne des polluants PM25/PM10/CO/NO2/O3 par zone sur la dernière heure
    — utilisé par le flow kriging (§7) pour les snapshots par zone."""
    flux = f"""
from(bucket: "{INFLUX_BUCKET_CLEANSED}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "{CLEANSED_MEASUREMENT}")
  |> filter(fn: (r) => r.zone_id == "{zone_id}")
  |> filter(fn: (r) => r._field == "pm25" or r._field == "pm10" or r._field == "co" or r._field == "no2" or r._field == "o3")
  |> mean()
"""
    result: dict[str, float] = {}
    try:
        tables = client.query_api().query(flux, org=INFLUX_ORG)
        for table in tables:
            for record in table.records:
                result[record.get_field()] = record.get_value()
    except Exception:
        pass
    return result


def build_cleansed_point(
    sensor_id: str, zone_id: str, timestamp: "datetime",
    pm25_kalman: float, pm25_std: float, calibration_method: str,
    kalman_gain: float, row: "pd.Series",
) -> Point:
    """Construit un point `air_quality_cleansed` pour le worker de calibration (§3.4)."""
    confidence = max(0.0, min(1.0, 1.0 - pm25_std / max(pm25_kalman, 1.0)))
    return (
        Point(CLEANSED_MEASUREMENT)
        .tag("sensor_id", sensor_id)
        .tag("zone_id", zone_id)
        .tag("state", "kalman_filtered" if "kalman" in calibration_method else "calibrated")
        .field("pm25", pm25_kalman)
        .field("pm10",  float(row.get("pm10",  0.0)))
        .field("pm1_0", float(row.get("pm1_0", 0.0)))
        .field("co",    float(row.get("co",    0.0)))
        .field("no2",   float(row.get("no2",   0.0)))
        .field("o3",    float(row.get("o3",    0.0)))
        .field("temperature", float(row.get("temperature", 0.0)))
        .field("humidity",    float(row.get("humidity",    0.0)))
        .field("pressure",    float(row.get("pressure",    0.0)))
        .field("battery_level", float(row.get("battery_level", 0.0)))
        .field("rssi",          float(row.get("rssi", 0.0)))
        .field("kalman_gain",   round(kalman_gain, 4))
        .field("confidence",    round(confidence, 3))
        .field("calibration_model_id", calibration_method)
        .time(timestamp, WritePrecision.S)
    )
