"""Lectures InfluxDB pour l'API — mesures `air_quality_cleansed` (temps réel)
et `air_quality_hourly` (bucket_downsampled, historique).

Schéma : voir pipeline/db/influxdb_client.py (champs pm25, pm10, co, no2, o3,
temperature, humidity, pressure ; tags sensor_id, zone_id)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from influxdb_client import InfluxDBClient

from app.config import get_settings

CLEANSED_MEAS = "air_quality_cleansed"
RAW_MEAS = "air_quality_raw"
HOURLY_MEAS = "air_quality_hourly"
FIELDS = ["pm25", "pm10", "co", "no2", "o3", "temperature", "humidity", "pressure"]

_SAFE = re.compile(r"^[A-Za-z0-9_\-]+$")
_client: Optional[InfluxDBClient] = None


def _safe(tag: str) -> str:
    """Les tags sont interpolés dans Flux (pas de requêtes paramétrées en OSS) —
    on n'accepte que [A-Za-z0-9_-] pour interdire toute injection Flux."""
    if not _SAFE.match(tag):
        raise ValueError(f"identifiant invalide: {tag!r}")
    return tag


def client() -> InfluxDBClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = InfluxDBClient(url=s.influxdb_url, token=s.influxdb_token,
                                 org=s.influxdb_org, timeout=15_000)
    return _client


def _query(flux: str) -> list[dict[str, Any]]:
    s = get_settings()
    rows: list[dict[str, Any]] = []
    tables = client().query_api().query(flux, org=s.influxdb_org)
    for table in tables:
        for record in table.records:
            rows.append(dict(record.values))
    return rows


def zone_latest_means(window_minutes: int = 15) -> dict[str, dict[str, float]]:
    """Moyenne par zone et par champ sur la fenêtre récente → {zone: {field: val}}."""
    s = get_settings()
    flux = f"""
from(bucket: "{s.influxdb_bucket_cleansed}")
  |> range(start: -{int(window_minutes)}m)
  |> filter(fn: (r) => r._measurement == "{CLEANSED_MEAS}")
  |> filter(fn: (r) => {' or '.join(f'r._field == "{f}"' for f in FIELDS)})
  |> group(columns: ["zone_id", "_field"])
  |> mean()
"""
    out: dict[str, dict[str, float]] = {}
    for r in _query(flux):
        zone = r.get("zone_id")
        if zone and r.get("_value") is not None:
            out.setdefault(zone, {})[r["_field"]] = float(r["_value"])
    return out


def zone_last_timestamp() -> dict[str, datetime]:
    """Dernier point pm25 par zone (fraîcheur des données)."""
    s = get_settings()
    flux = f"""
from(bucket: "{s.influxdb_bucket_cleansed}")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "{CLEANSED_MEAS}" and r._field == "pm25")
  |> group(columns: ["zone_id"])
  |> last()
"""
    return {r["zone_id"]: r["_time"] for r in _query(flux) if r.get("zone_id")}


def zone_history(zone_id: str, start: datetime, end: datetime,
                 every: str) -> list[dict[str, Any]]:
    """Agrégats fenêtrés multi-champs pour /aqi/history.
    `every` ∈ {5m, 1h, 6h, 24h} (validé côté router)."""
    s = get_settings()
    zone = _safe(zone_id)
    # On agrège toujours depuis le bucket cleansed (rétention 2 ans, schéma _field=pm25…)
    # plutôt que le bucket downsampled : ce dernier stocke un schéma différent
    # (tag `pollutant`, champs mean/min/max) incompatible avec le pivot ci-dessous,
    # et n'est alimenté qu'après le 1er passage de la tâche horaire. aggregateWindow
    # produit directement les fenêtres 1h/6h/24h demandées.
    bucket = s.influxdb_bucket_cleansed
    meas = CLEANSED_MEAS
    flux = f"""
from(bucket: "{bucket}")
  |> range(start: {start.isoformat()}, stop: {end.isoformat()})
  |> filter(fn: (r) => r._measurement == "{meas}")
  |> filter(fn: (r) => r.zone_id == "{zone}")
  |> filter(fn: (r) => {' or '.join(f'r._field == "{f}"' for f in FIELDS)})
  |> aggregateWindow(every: {every}, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> sort(columns: ["_time"])
"""
    return _query(flux)


def sensor_timeseries(sensor_id: str, hours: int, resolution: str) -> list[dict[str, Any]]:
    """Série temporelle d'un capteur — `resolution` ∈ {raw, 5min}."""
    s = get_settings()
    sensor = _safe(sensor_id)
    agg = "" if resolution == "raw" else \
        "|> aggregateWindow(every: 5m, fn: mean, createEmpty: false)\n"
    flux = f"""
from(bucket: "{s.influxdb_bucket_cleansed}")
  |> range(start: -{int(hours)}h)
  |> filter(fn: (r) => r._measurement == "{CLEANSED_MEAS}")
  |> filter(fn: (r) => r.sensor_id == "{sensor}")
  |> filter(fn: (r) => {' or '.join(f'r._field == "{f}"' for f in FIELDS)})
  {agg}|> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> sort(columns: ["_time"])
"""
    return _query(flux)


def sensor_last_values() -> dict[str, dict[str, Any]]:
    """Dernières valeurs par capteur (pm25 + télémétrie batterie/rssi du raw)."""
    s = get_settings()
    flux = f"""
from(bucket: "{s.influxdb_bucket_raw}")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "{RAW_MEAS}")
  |> filter(fn: (r) => r._field == "pm25" or r._field == "battery_level" or r._field == "rssi")
  |> group(columns: ["sensor_id", "_field"])
  |> last()
"""
    out: dict[str, dict[str, Any]] = {}
    for r in _query(flux):
        sid = r.get("sensor_id")
        if sid:
            entry = out.setdefault(sid, {})
            entry[r["_field"]] = r.get("_value")
            entry["_time"] = r.get("_time")
    return out


def messages_count_today() -> dict[str, int]:
    """Nombre de messages (points pm25) reçus aujourd'hui, par capteur."""
    s = get_settings()
    flux = f"""
from(bucket: "{s.influxdb_bucket_raw}")
  |> range(start: today())
  |> filter(fn: (r) => r._measurement == "{RAW_MEAS}")
  |> filter(fn: (r) => r._field == "pm25")
  |> group(columns: ["sensor_id"])
  |> count()
"""
    out: dict[str, int] = {}
    for r in _query(flux):
        sid = r.get("sensor_id")
        if sid:
            out[sid] = int(r.get("_value") or 0)
    return out


def export_rows(zone_id: str, start: datetime, end: datetime,
                pollutants: list[str]) -> list[dict[str, Any]]:
    """Lignes horaires pour /export/data (bucket_downsampled)."""
    s = get_settings()
    zone = _safe(zone_id)
    fields = [f for f in pollutants if f in FIELDS] + ["temperature", "humidity"]
    flux = f"""
from(bucket: "{s.influxdb_bucket_downsampled}")
  |> range(start: {start.isoformat()}, stop: {end.isoformat()})
  |> filter(fn: (r) => r._measurement == "{HOURLY_MEAS}")
  |> filter(fn: (r) => r.zone_id == "{zone}")
  |> filter(fn: (r) => {' or '.join(f'r._field == "{f}"' for f in dict.fromkeys(fields))})
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> sort(columns: ["_time"])
"""
    return _query(flux)
