"""Router /sensors — liste et données par capteur (API_SPEC.md §4.3, §4.4)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request

from app.db import influxdb, postgres
from app.models.sensors import SensorCurrent, SensorDataResponse, SensorsResponse, SensorSummary
from app.security.rate_limit import limiter

router = APIRouter(prefix="/sensors", tags=["sensors"])

SENSOR_ID_RE = r"^ESP32-DK-[A-Z]+-\d{3}$"


def _fetch_sensors(zone_id: Optional[str], status: Optional[str],
                   include_inactive: bool) -> list[dict]:
    clauses, params = [], []
    if zone_id:
        clauses.append("z.path ~ %s")
        params.append(f"*.{zone_id}")
    if status:
        clauses.append("s.status = %s")
        params.append(status)
    elif not include_inactive:
        clauses.append("s.status = 'active'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with postgres.cursor() as cur:
        cur.execute(f"""
            SELECT s.serial_number, s.status, s.firmware_version, s.last_seen,
                   s.metadata, z.nom AS zone_name,
                   split_part(z.path::text, '.', -1) AS zone_slug,
                   ST_Y(s.geom) AS lat, ST_X(s.geom) AS lon
            FROM sensors s JOIN zones z ON z.id = s.zone_id
            {where}
            ORDER BY s.serial_number
        """, params)
        return [dict(r) for r in cur.fetchall()]


@router.get("", response_model=SensorsResponse)
@limiter.limit("100/minute")
def list_sensors(request: Request,
                 zone_id: Optional[str] = Query(None),
                 status: Optional[str] = Query(None, pattern="^(active|maintenance|inactive)$"),
                 include_inactive: bool = Query(False)):
    rows = _fetch_sensors(zone_id, status, include_inactive)
    last = influxdb.sensor_last_values()

    sensors = []
    for r in rows:
        meta = r["metadata"] or {}
        lv = last.get(r["serial_number"], {})
        sensors.append(SensorSummary(
            sensor_id=r["serial_number"], zone_id=r["zone_slug"], zone_name=r["zone_name"],
            lat=r["lat"], lon=r["lon"], status=r["status"],
            last_seen=r["last_seen"], firmware=r["firmware_version"],
            battery_pct=lv.get("battery_level", meta.get("battery_pct")),
            solar_active=meta.get("solar_panel"),
            rssi_dbm=lv.get("rssi", meta.get("rssi_dbm")),
            last_pm25=lv.get("pm25"),
            sim=bool(meta.get("sim", False)),
        ))

    n_active = sum(1 for s in sensors if s.status == "active")
    return SensorsResponse(sensors=sensors, meta={
        "total": len(sensors), "active": n_active,
        "inactive": len(sensors) - n_active,
        "generated_at": datetime.now(timezone.utc),
    })


@router.get("/{sensor_id}/data", response_model=SensorDataResponse)
@limiter.limit("60/minute")
def sensor_data(request: Request,
                sensor_id: str = Path(pattern=SENSOR_ID_RE),
                hours: int = Query(1, ge=1, le=48),
                resolution: str = Query("5min", pattern="^(raw|5min)$")):
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT s.last_seen, split_part(z.path::text, '.', -1) AS zone_slug
            FROM sensors s JOIN zones z ON z.id = s.zone_id
            WHERE s.serial_number = %s
        """, (sensor_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, detail={"code": "SENSOR_NOT_FOUND",
                                         "message": f"Capteur inconnu : {sensor_id}"})
    last_seen = row["last_seen"]
    if last_seen and datetime.now(timezone.utc) - last_seen > timedelta(hours=24):
        raise HTTPException(404, detail={"code": "NO_DATA_AVAILABLE",
                                         "message": "Capteur inactif depuis plus de 24h."})

    rows = influxdb.sensor_timeseries(sensor_id, hours, resolution)
    latest = rows[-1] if rows else {}
    timeseries = [{
        "timestamp": r["_time"].isoformat() if hasattr(r.get("_time"), "isoformat") else r.get("_time"),
        **{k: r.get(k) for k in influxdb.FIELDS if r.get(k) is not None},
    } for r in rows]

    return SensorDataResponse(
        sensor_id=sensor_id, zone_id=row["zone_slug"], last_update=last_seen,
        current=SensorCurrent(
            pm25=latest.get("pm25"), pm10=latest.get("pm10"),
            co_ppm=latest.get("co"), no2_ppb=latest.get("no2"), o3_ppb=latest.get("o3"),
            temperature_c=latest.get("temperature"), humidity_pct=latest.get("humidity"),
            pressure_hpa=latest.get("pressure"),
        ),
        timeseries=timeseries,
    )
