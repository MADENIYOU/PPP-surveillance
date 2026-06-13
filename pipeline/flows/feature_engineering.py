#!/usr/bin/env python3
"""Flow Prefect — Feature Engineering (57 features F01-F57).

Référence : pipeline/PIPELINE_SPEC.md §5 + 02_ia/FEATURE_ENGINEERING_SPEC.md.

Planification : toutes les 15 minutes via Prefect deployment.
Calcule le vecteur de 57 features pour chaque zone active et l'écrit
dans `feature_store` (PostgreSQL) au format JSONB (§5.3).

Sources :
  - InfluxDB `bucket_cleansed` (lags, rolling stats, polluants actuels)
  - InfluxDB `bucket_downsampled` (lags > 1h — agrégats horaires)
  - PostgreSQL `external_weather` (météo, vent)
  - PostgreSQL `traffic_observations` (trafic, congestion)
  - PostgreSQL `sensors`, `calibration`, `zones` (métadonnées capteur)

Gestion des valeurs manquantes : `None` si la source est indisponible —
la table `feature_store.features` (JSONB) tolère les clés
nulles. Le flow aval (predictions.py) impute à la médiane de la ville
les features None avant l'inférence LSTM (§6.2 FEATURE_ENGINEERING_SPEC).
"""
from __future__ import annotations

import json
import math
import os
import structlog
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

try:
    from prefect import flow, task
    from prefect.logging import get_run_logger
    HAS_PREFECT = True
except ImportError:
    HAS_PREFECT = False
    # Stubs pour permettre l'import sans serveur Prefect
    def flow(*a, **kw):
        def _d(fn): return fn
        return _d

    def task(*a, **kw):
        def _d(fn): return fn
        return _d

    def get_run_logger():
        return structlog.get_logger("feature_engineering")


from db.influxdb_client import get_influxdb_client, INFLUX_BUCKET_CLEANSED, INFLUX_ORG  # noqa: E402
from db.postgres_client import PostgresPool  # noqa: E402

LOGGER = structlog.get_logger("feature_engineering")

# ─── Constantes Dakar ─────────────────────────────────────────────────────────
RUSH_HOURS = {7, 8, 9, 17, 18, 19}          # §3.5 FEATURE_ENGINEERING_SPEC
NIGHT_HOURS = {22, 23, 0, 1, 2, 3, 4, 5}    # §3.5


# ============================================================================
# Helpers Flux (InfluxDB query → valeur scalaire)
# ============================================================================
def _influx_scalar(client, flux: str) -> Optional[float]:
    """Exécute une requête Flux et retourne le premier scalaire trouvé, ou None."""
    try:
        tables = client.query_api().query(flux, org=INFLUX_ORG)
        for table in tables:
            for record in table.records:
                v = record.get_value()
                return float(v) if v is not None else None
    except Exception:
        return None
    return None


def _influx_field_mean(client, bucket: str, measurement: str, zone_id: str, field: str, hours: int) -> Optional[float]:
    flux = f"""
from(bucket: "{bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> filter(fn: (r) => r.zone_id == "{zone_id}")
  |> filter(fn: (r) => r._field == "{field}")
  |> mean()
"""
    return _influx_scalar(client, flux)


def _influx_field_std(client, bucket: str, measurement: str, zone_id: str, field: str, hours: int) -> Optional[float]:
    flux = f"""
from(bucket: "{bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> filter(fn: (r) => r.zone_id == "{zone_id}")
  |> filter(fn: (r) => r._field == "{field}")
  |> stddev()
"""
    return _influx_scalar(client, flux)


def _influx_field_stat(client, bucket: str, measurement: str, zone_id: str, field: str, hours: int, agg: str) -> Optional[float]:
    flux = f"""
from(bucket: "{bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> filter(fn: (r) => r.zone_id == "{zone_id}")
  |> filter(fn: (r) => r._field == "{field}")
  |> {agg}()
"""
    return _influx_scalar(client, flux)


def _influx_lag(client, bucket: str, measurement: str, zone_id: str, field: str, lag_hours: int) -> Optional[float]:
    """Valeur du champ à (now - lag_hours), avec fenêtre ±30min pour tolérer les gaps."""
    flux = f"""
from(bucket: "{bucket}")
  |> range(start: -{lag_hours + 1}h, stop: -{lag_hours - 1}h)
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> filter(fn: (r) => r.zone_id == "{zone_id}")
  |> filter(fn: (r) => r._field == "{field}")
  |> last()
"""
    return _influx_scalar(client, flux)


# ============================================================================
# Calcul des features par groupe (§3 FEATURE_ENGINEERING_SPEC)
# ============================================================================
@task(name="compute-zone-features", retries=1)
def compute_zone_features(zone_id: str, pg_pool: PostgresPool,
                           influx_client, ts: datetime) -> dict[str, Any]:
    """Calcule les 57 features (F01-F57) pour une zone à l'instant `ts`."""
    log = get_run_logger() if HAS_PREFECT else LOGGER
    feats: dict[str, Any] = {}

    # Mesures actuelles pour la zone (moyenne dernières 15 min)
    cleansed = INFLUX_BUCKET_CLEANSED
    meas = "air_quality_cleansed"
    dnsamp = "bucket_downsampled"
    aq_h = "air_quality_hourly"

    pm25_now = _influx_field_mean(influx_client, cleansed, meas, zone_id, "pm25", 1) or 0.0
    pm10_now = _influx_field_mean(influx_client, cleansed, meas, zone_id, "pm10", 1) or 0.0
    co_now   = _influx_field_mean(influx_client, cleansed, meas, zone_id, "co",   1) or 0.0
    no2_now  = _influx_field_mean(influx_client, cleansed, meas, zone_id, "no2",  1) or 0.0
    o3_now   = _influx_field_mean(influx_client, cleansed, meas, zone_id, "o3",   1) or 0.0

    # ── F01-F11 : Lags ──────────────────────────────────────────────────────
    for lag in [1, 2, 3, 4, 6, 12, 24, 48, 168]:
        feats[f"pm25_lag_{lag}h"] = _influx_lag(influx_client, dnsamp, aq_h, zone_id, "pm25", lag) \
            if lag >= 1 else pm25_now
    feats["pm10_lag_1h"]  = _influx_lag(influx_client, dnsamp, aq_h, zone_id, "pm10",  1)
    feats["pm10_lag_24h"] = _influx_lag(influx_client, dnsamp, aq_h, zone_id, "pm10", 24)
    feats["co_lag_1h"]    = _influx_lag(influx_client, dnsamp, aq_h, zone_id, "co",    1)
    feats["no2_lag_1h"]   = _influx_lag(influx_client, dnsamp, aq_h, zone_id, "no2",   1)

    # ── F12-F21 : Rolling statistics ─────────────────────────────────────────
    for w in [3, 6, 24]:
        feats[f"pm25_rolling_mean_{w}h"] = _influx_field_mean(influx_client, cleansed, meas, zone_id, "pm25", w)
        feats[f"pm25_rolling_std_{w}h"]  = _influx_field_std( influx_client, cleansed, meas, zone_id, "pm25", w)
    feats["pm25_rolling_mean_7d"]  = _influx_field_mean(influx_client, dnsamp, aq_h, zone_id, "pm25", 168)
    feats["pm25_rolling_min_6h"]   = _influx_field_stat(influx_client, cleansed, meas, zone_id, "pm25", 6, "min")
    feats["pm25_rolling_max_6h"]   = _influx_field_stat(influx_client, cleansed, meas, zone_id, "pm25", 6, "max")
    feats["pm25_rolling_p95_24h"]  = _influx_field_stat(influx_client, cleansed, meas, zone_id, "pm25", 24, "quantile(q: 0.95)")
    feats["pm10_rolling_mean_6h"]  = _influx_field_mean(influx_client, cleansed, meas, zone_id, "pm10", 6)
    feats["pm25_rolling_mean_1h"]  = _influx_field_mean(influx_client, cleansed, meas, zone_id, "pm25", 1)
    feats["pm25_rolling_median_6h"] = _influx_field_stat(influx_client, cleansed, meas, zone_id, "pm25", 6, "median")
    feats["pm25_rolling_std_1h"]   = _influx_field_std( influx_client, cleansed, meas, zone_id, "pm25", 1)
    feats["pm25_rolling_mean_12h"] = _influx_field_mean(influx_client, cleansed, meas, zone_id, "pm25", 12)
    feats["pm10_rolling_mean_24h"] = _influx_field_mean(influx_client, cleansed, meas, zone_id, "pm10", 24)
    feats["pm10_rolling_mean_1h"]  = _influx_field_mean(influx_client, cleansed, meas, zone_id, "pm10", 1)
    feats["pm25_rolling_min_1h"]   = _influx_field_stat(influx_client, cleansed, meas, zone_id, "pm25", 1, "min")
    feats["pm25_rolling_max_1h"]   = _influx_field_stat(influx_client, cleansed, meas, zone_id, "pm25", 1, "max")

    # ── F22-F25 : Dérivées ───────────────────────────────────────────────────
    lag1  = feats.get("pm25_lag_1h")
    lag6  = feats.get("pm25_lag_6h")
    lag24 = feats.get("pm25_lag_24h")
    feats["pm25_delta_1h"]  = (pm25_now - lag1)  if lag1  is not None else None
    feats["pm25_delta_6h"]  = (pm25_now - lag6)  if lag6  is not None else None
    lag12 = feats.get("pm25_lag_12h")
    feats["pm25_delta_12h"] = (pm25_now - lag12) if lag12 is not None else None
    lag3  = feats.get("pm25_lag_3h")
    feats["pm25_delta_3h"]  = (pm25_now - lag3)  if lag3  is not None else None
    delta_1h = feats["pm25_delta_1h"]
    delta_t1 = (lag1 - lag6) if (lag1 is not None and lag6 is not None) else None
    feats["pm25_accel_1h"]  = (delta_1h - delta_t1) if (delta_1h is not None and delta_t1 is not None) else None
    feats["pm25_daily_change_pct"] = ((pm25_now - lag24) / lag24 * 100) if (lag24 and lag24 > 0) else None

    # ── F26-F33 : Cycliques sin/cos ──────────────────────────────────────────
    h = ts.hour + ts.minute / 60.0
    dow = ts.weekday()
    m   = ts.month
    feats["hour_sin"]         = math.sin(2 * math.pi * h   / 24)
    feats["hour_cos"]         = math.cos(2 * math.pi * h   / 24)
    feats["day_of_week_sin"]  = math.sin(2 * math.pi * dow / 7)
    feats["day_of_week_cos"]  = math.cos(2 * math.pi * dow / 7)
    feats["month_sin"]        = math.sin(2 * math.pi * m   / 12)
    feats["month_cos"]        = math.cos(2 * math.pi * m   / 12)
    # wind_dir_sin/cos ajoutés après récupération météo ci-dessous

    # ── F34-F36 : Calendaires ────────────────────────────────────────────────
    feats["is_weekend"]   = 1 if dow >= 5 else 0
    feats["is_rush_hour"] = 1 if ts.hour in RUSH_HOURS else 0
    feats["is_night"]     = 1 if ts.hour in NIGHT_HOURS else 0
    feats["is_morning"]        = 1 if 6 <= ts.hour <= 10 else 0
    feats["is_evening"]        = 1 if 17 <= ts.hour <= 21 else 0
    feats["is_business_hour"]  = 1 if 8 <= ts.hour <= 17 and dow < 5 else 0

    # ── F37-F44 : Météo (PostgreSQL external_weather) ────────────────────────
    weather = _fetch_weather(pg_pool, zone_id, ts)
    if weather:
        T  = weather.get("temperature")
        RH = weather.get("humidity")
        WD = weather.get("wind_direction")
        feats["temperature"]   = T
        feats["humidity"]      = RH
        feats["pressure"]      = weather.get("pressure")
        feats["wind_speed"]    = weather.get("wind_speed")
        feats["wind_direction"] = WD
        feats["precipitation"] = weather.get("precipitation")
        if WD is not None:
            wd_r = math.radians(WD)
            feats["wind_dir_sin"] = math.sin(wd_r)
            feats["wind_dir_cos"] = math.cos(wd_r)
        if T is not None and RH is not None:
            feats["temp_hum_index"] = 0.8 * T + (RH * T) / 500
            feats["dew_point"]      = T - ((100 - RH) / 5)
    else:
        for k in ["temperature", "humidity", "pressure", "wind_speed", "wind_direction",
                  "precipitation", "wind_dir_sin", "wind_dir_cos", "temp_hum_index", "dew_point"]:
            feats[k] = None

    # ── F45-F47 : Trafic (PostgreSQL traffic_observations) ───────────────────
    traffic = _fetch_traffic(pg_pool, zone_id, ts)
    feats["congestion_level"]         = traffic.get("congestion_level")
    feats["congestion_lag_1h"]        = _fetch_traffic_at(pg_pool, zone_id, ts - _h(1))
    feats["congestion_rolling_mean_3h"] = _fetch_traffic_mean(pg_pool, zone_id, ts, hours=3)

    # ── F48-F50 : Inter-polluants ─────────────────────────────────────────────
    feats["pm25_pm10_ratio"] = (pm25_now / pm10_now) if pm10_now > 0 else None
    feats["pm25_co_ratio"]   = (pm25_now / co_now)   if co_now   > 0 else None
    feats["no2_co_ratio"]    = (no2_now  / co_now)   if co_now   > 0 else None
    feats["pm25_no2_ratio"]  = (pm25_now / no2_now)  if no2_now  > 0 else None
    feats["co_no2_ratio"]    = (co_now   / no2_now)  if no2_now  > 0 else None
    feats["pm10_pm25_ratio"] = (pm10_now / pm25_now) if pm25_now > 0 else None
    feats["pm10_co_ratio"]    = (pm10_now / co_now) if co_now > 0 else None
    feats["no2_o3_ratio"]     = (no2_now / o3_now) if o3_now > 0 else None

    # ── F51-F54 : Spatiales ──────────────────────────────────────────────────
    feats["pm25_neighbor_mean"] = _influx_field_mean(influx_client, cleansed, meas, zone_id, "pm25", 1)
    feats["pm25_upwind_mean"]   = _fetch_upwind_pm25_mean(
        pg_pool, influx_client, zone_id, feats.get("wind_direction"))
    feats["pm25_city_mean"]     = _fetch_city_pm25_mean(influx_client)
    feats["sensor_density"]     = _fetch_sensor_density(pg_pool, zone_id)
    feats["pm25_downwind_mean"]  = _fetch_downwind_pm25_mean(
        pg_pool, influx_client, zone_id, feats.get("wind_direction"))
    upwind = feats.get("pm25_upwind_mean")
    ws     = feats.get("wind_speed")
    if pm25_now > 0 and upwind is not None and upwind > 0:
        feats["wind_independence_index"] = abs(pm25_now - upwind) / max(pm25_now, upwind)
    elif ws is not None and ws < 0.5:
        feats["wind_independence_index"] = 1.0
    else:
        feats["wind_independence_index"] = None
    feats["pm25_spatial_gradient"] = (pm25_now - feats.get("pm25_neighbor_mean", pm25_now)) / max(pm25_now, 1.0) if feats.get("pm25_neighbor_mean") is not None else None

    # ── F55-F57 : Capteur ────────────────────────────────────────────────────
    sensor_meta = _fetch_sensor_meta(pg_pool, zone_id, ts)
    feats["days_since_calibration"] = sensor_meta.get("days_since_calibration")
    feats["battery_level"]          = sensor_meta.get("battery_level")
    feats["sensor_age_days"]        = sensor_meta.get("sensor_age_days")

    log.debug("features computed zone=%s n_non_null=%d",
              zone_id, sum(1 for v in feats.values() if v is not None))
    return {"zone_id": zone_id, "timestamp": _iso(ts), "features": feats}


# ============================================================================
# Helpers PostgreSQL
# ============================================================================
def _h(hours: int):
    from datetime import timedelta
    return timedelta(hours=hours)


def _fetch_weather(pool: PostgresPool, zone_id: str, ts: datetime) -> Optional[dict]:
    zone_int = _zone_int(pool, zone_id)
    if zone_int is None:
        return None
    with pool.cursor() as cur:
        cur.execute("""
            SELECT temperature, humidity, pressure, wind_speed, wind_direction, precipitation
            FROM external_weather
            WHERE zone_id = %s AND timestamp <= %s
            ORDER BY timestamp DESC LIMIT 1
        """, (zone_int, ts))
        row = cur.fetchone()
        return dict(row) if row else None


def _fetch_traffic(pool: PostgresPool, zone_id: str, ts: datetime) -> dict:
    zone_int = _zone_int(pool, zone_id)
    if zone_int is None:
        return {}
    with pool.cursor() as cur:
        cur.execute("""
            SELECT congestion_level FROM traffic_observations
            WHERE zone_id = %s AND timestamp <= %s
            ORDER BY timestamp DESC LIMIT 1
        """, (zone_int, ts))
        row = cur.fetchone()
        return dict(row) if row else {}


def _fetch_traffic_at(pool: PostgresPool, zone_id: str, ts: datetime) -> Optional[float]:
    r = _fetch_traffic(pool, zone_id, ts)
    v = r.get("congestion_level")
    return float(v) if v is not None else None


def _fetch_traffic_mean(pool: PostgresPool, zone_id: str, ts: datetime, hours: int) -> Optional[float]:
    zone_int = _zone_int(pool, zone_id)
    if zone_int is None:
        return None
    with pool.cursor() as cur:
        cur.execute("""
            SELECT AVG(congestion_level)
            FROM traffic_observations
            WHERE zone_id = %s AND timestamp BETWEEN %s - (%s * interval '1 hour') AND %s
        """, (zone_int, ts, hours, ts))
        row = cur.fetchone()
        if row:
            vals = list(row.values())
            return float(vals[0]) if vals[0] is not None else None
        return None


def _fetch_city_pm25_mean(influx_client) -> Optional[float]:
    flux = f"""
from(bucket: "{INFLUX_BUCKET_CLEANSED}")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
  |> filter(fn: (r) => r._field == "pm25")
  |> mean()
"""
    return _influx_scalar(influx_client, flux)


UPWIND_SECTOR_HALF_DEG = 45.0  # secteur ±45° autour de la direction d'origine du vent


def _fetch_upwind_pm25_mean(pool: PostgresPool, influx_client, zone_id: str,
                            wind_direction: Optional[float]) -> Optional[float]:
    """F52 — moyenne PM2.5 (1h) des zones situées au vent de `zone_id`.

    `wind_direction` est la direction météorologique (degrés, 0=Nord — d'où
    VIENT le vent). Une zone candidate est "au vent" si l'azimut depuis le
    centroïde de la zone courante vers son centroïde tombe dans le secteur
    wind_direction ± 45°. L'azimut est calculé par PostGIS (ST_Azimuth) ;
    la moyenne PM2.5 vient de bucket_cleansed sur la dernière heure."""
    if wind_direction is None:
        return None
    with pool.cursor() as cur:
        cur.execute("""
            SELECT split_part(z2.path::text, '.', -1) AS zone_slug,
                   degrees(ST_Azimuth(ST_Centroid(z1.geom), ST_Centroid(z2.geom))) AS azimuth
            FROM zones z1
            JOIN zones z2 ON z2.id <> z1.id AND z2.niveau = z1.niveau
            WHERE z1.path ~ %s
        """, (f"*.{zone_id}",))
        rows = cur.fetchall()
    upwind_slugs = []
    for row in rows:
        az = row.get("azimuth")
        if az is None:
            continue
        # écart angulaire circulaire entre azimut et direction d'origine du vent
        diff = abs((az - wind_direction + 180.0) % 360.0 - 180.0)
        if diff <= UPWIND_SECTOR_HALF_DEG:
            upwind_slugs.append(row["zone_slug"])
    if not upwind_slugs:
        return None
    zone_filter = " or ".join(f'r.zone_id == "{s}"' for s in upwind_slugs)
    flux = f"""
from(bucket: "{INFLUX_BUCKET_CLEANSED}")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "air_quality_cleansed")
  |> filter(fn: (r) => {zone_filter})
  |> filter(fn: (r) => r._field == "pm25")
  |> mean()
  |> group()
  |> mean()
"""
    return _influx_scalar(influx_client, flux)


def _fetch_downwind_pm25_mean(pool: PostgresPool, influx_client, zone_id: str,
                               wind_direction: Optional[float]) -> Optional[float]:
    """Downwind PM2.5 mean — same geometry as upwind but offset by 180°."""
    if wind_direction is None:
        return None
    return _fetch_upwind_pm25_mean(pool, influx_client, zone_id,
                                    (wind_direction + 180.0) % 360.0)


def _fetch_sensor_density(pool: PostgresPool, zone_id: str) -> Optional[int]:
    zone_int = _zone_int(pool, zone_id)
    if zone_int is None:
        return None
    with pool.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM sensors
            WHERE zone_id = %s AND status = 'active'
        """, (zone_int,))
        row = cur.fetchone()
        if row:
            vals = list(row.values())
            return int(vals[0]) if vals[0] is not None else 0
        return 0


def _fetch_sensor_meta(pool: PostgresPool, zone_id: str, ts: datetime) -> dict:
    zone_int = _zone_int(pool, zone_id)
    if zone_int is None:
        return {}
    with pool.cursor() as cur:
        cur.execute("""
            SELECT s.install_date,
                   (s.metadata->>'battery_pct')::float AS battery_level,
                   c.valid_from AS last_calibration
            FROM sensors s
            LEFT JOIN calibration c ON s.id = c.sensor_id AND c.valid_until IS NULL
            WHERE s.zone_id = %s AND s.status = 'active'
            ORDER BY s.id LIMIT 1
        """, (zone_int,))
        row = cur.fetchone()
        if not row:
            return {}
        result = {}
        if row.get("install_date"):
            result["sensor_age_days"] = (ts.date() - row["install_date"]).days
        if row.get("battery_level") is not None:
            result["battery_level"] = float(row["battery_level"])
        if row.get("last_calibration"):
            result["days_since_calibration"] = (ts.date() - row["last_calibration"]).days
        return result


def _zone_int(pool: PostgresPool, zone_slug: str) -> Optional[int]:
    with pool.cursor() as cur:
        cur.execute("SELECT id FROM zones WHERE path ~ %s ORDER BY niveau DESC LIMIT 1", (f"*.{zone_slug}",))
        row = cur.fetchone()
        return int(row["id"]) if row else None


# ============================================================================
# Écriture feature_store (§5.3)
# ============================================================================
@task(name="write-feature-store", retries=2)
def write_feature_store(results: list[dict], pg_pool: PostgresPool) -> int:
    n = 0
    for r in results:
        zone_id_slug = r["zone_id"]
        zone_int = _zone_int(pg_pool, zone_id_slug)
        if zone_int is None:
            LOGGER.warning("write_feature_store zone_not_found zone=%s", zone_id_slug)
            continue
        with pg_pool.cursor() as cur:
            cur.execute("""
                INSERT INTO feature_store (zone_id, timestamp, features, feature_names)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT (zone_id, timestamp)
                DO UPDATE SET features = EXCLUDED.features, feature_names = EXCLUDED.feature_names
            """, (zone_int, r["timestamp"],
                  json.dumps(r["features"], ensure_ascii=False),
                  list(r["features"].keys())))
        n += 1
    return n


@task(name="get-active-zones")
def get_active_zones(pg_pool: PostgresPool) -> list[str]:
    """Retourne les zone slugs (dernier label du path ltree) des zones actives."""
    with pg_pool.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT split_part(z.path::text, '.', -1) AS zone_slug
            FROM sensors s JOIN zones z ON z.id = s.zone_id
            WHERE s.status = 'active'
        """)
        return [row["zone_slug"] for row in cur.fetchall()]


# ============================================================================
# Flow principal (§5.1)
# ============================================================================
@flow(name="feature_engineering", retries=2, retry_delay_seconds=60)
def run_feature_engineering(zone_id: Optional[str] = None, lookback_hours: int = 2):
    pg_pool = PostgresPool()
    influx = get_influxdb_client()
    ts = datetime.now(timezone.utc)

    zones = [zone_id] if zone_id else get_active_zones(pg_pool)
    if not zones:
        (get_run_logger() if HAS_PREFECT else LOGGER).warning("no_active_zones")
        return {"zones_processed": 0, "total_rows": 0}

    results = [compute_zone_features(z, pg_pool, influx, ts) for z in zones]
    n_written = write_feature_store(results, pg_pool)
    return {"zones_processed": len(zones), "total_rows": n_written}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    structlog.configure(
        processors=[
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    result = run_feature_engineering()
    print("feature_engineering result:", result)
