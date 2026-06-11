"""Router /aqi — IQA courant et historique (API_SPEC.md §4.1, §4.2)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.db import influxdb, postgres
from app.db.redis_client import cache_get, cache_set
from app.models.aqi import (AqiCurrentMeta, AqiCurrentResponse, AqiHistoryResponse,
                            HistoryPoint, Pagination, ZoneAQI)
from app.security.rate_limit import limiter
from app.utils.iqa_calculator import compute_iqa, iqa_level

router = APIRouter(prefix="/aqi", tags=["aqi"])

RESOLUTION_TO_FLUX = {"5min": "5m", "1h": "1h", "6h": "6h", "24h": "24h"}


def _sensor_counts() -> dict[str, dict[str, int]]:
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT split_part(z.path::text, '.', -1) AS slug,
                   count(*) AS total,
                   count(*) FILTER (WHERE s.status = 'active') AS active
            FROM sensors s JOIN zones z ON z.id = s.zone_id
            GROUP BY slug
        """)
        return {r["slug"]: {"total": r["total"], "active": r["active"]} for r in cur.fetchall()}


def _trend(zone: str) -> Optional[str]:
    """Tendance = comparaison moyenne PM2.5 dernière heure vs heure précédente."""
    try:
        now = influxdb.zone_latest_means(60).get(zone, {}).get("pm25")
        hist = influxdb.zone_history(zone,
                                     datetime.now(timezone.utc) - timedelta(hours=2),
                                     datetime.now(timezone.utc) - timedelta(hours=1), "1h")
        prev = hist[-1].get("pm25") if hist else None
        if now is None or prev is None:
            return None
        if now > prev * 1.1:
            return "increasing"
        if now < prev * 0.9:
            return "decreasing"
        return "stable"
    except Exception:
        return None


@router.get("/current", response_model=AqiCurrentResponse)
@limiter.limit("100/minute")
def aqi_current(request: Request,
                zone_id: Optional[str] = Query(None),
                include_sensors: bool = Query(False)):
    cache_key = f"aqi_current:{zone_id}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    zones = postgres.list_zones()
    if zone_id:
        zones = [z for z in zones if z["slug"] == zone_id]
        if not zones:
            raise HTTPException(404, detail={"code": "NOT_FOUND",
                                             "message": f"Zone inconnue : {zone_id}"})

    means = influxdb.zone_latest_means(15)
    freshness = influxdb.zone_last_timestamp()
    counts = _sensor_counts()
    now = datetime.now(timezone.utc)

    out: list[ZoneAQI] = []
    for z in zones:
        slug = z["slug"]
        m = means.get(slug, {})
        pm25 = m.get("pm25")
        iqa = compute_iqa(pm25)
        level, label, color = iqa_level(iqa) if iqa is not None else (None, None, None)
        last_ts = freshness.get(slug)
        cnt = counts.get(slug, {"total": 0, "active": 0})
        out.append(ZoneAQI(
            zone_id=slug, zone_name=z["nom"],
            lat_center=z["lat_center"], lon_center=z["lon_center"],
            timestamp=last_ts, iqa=iqa, iqa_level=level, iqa_label_fr=label,
            iqa_color=color,
            pm25_ug_m3=pm25, pm10_ug_m3=m.get("pm10"),
            no2_ppb=m.get("no2"), co_ppm=m.get("co"),
            temperature_c=m.get("temperature"), humidity_pct=m.get("humidity"),
            dominant_pollutant="pm25" if pm25 is not None else None,
            sensor_count=cnt["total"], sensors_active=cnt["active"],
            data_freshness_s=int((now - last_ts).total_seconds()) if last_ts else None,
            trend=_trend(slug) if pm25 is not None else None,
        ))

    response = AqiCurrentResponse(
        zones=out,
        meta=AqiCurrentMeta(generated_at=now, n_zones=len(out),
                            n_zones_active=sum(1 for z in out if z.iqa is not None)),
    )
    cache_set(cache_key, response.model_dump(mode="json"), ttl_s=15)
    return response


@router.get("/history", response_model=AqiHistoryResponse)
@limiter.limit("100/minute")
def aqi_history(request: Request,
                zone_id: str = Query(...),
                start: Optional[datetime] = Query(None),
                end: Optional[datetime] = Query(None),
                resolution: str = Query("1h"),
                page: int = Query(1, ge=1),
                page_size: int = Query(100, ge=1, le=1000)):
    if resolution not in RESOLUTION_TO_FLUX:
        raise HTTPException(400, detail={"code": "INVALID_PARAMS",
                                         "message": "resolution ∈ {5min, 1h, 6h, 24h}"})
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(hours=24)
    if start >= end:
        raise HTTPException(400, detail={"code": "INVALID_PARAMS",
                                         "message": "start doit précéder end"})

    rows = influxdb.zone_history(zone_id, start, end, RESOLUTION_TO_FLUX[resolution])
    points = [HistoryPoint(
        timestamp=r["_time"],
        iqa=compute_iqa(r.get("pm25")),
        pm25_mean=r.get("pm25"), pm10_mean=r.get("pm10"),
        no2_ppb_mean=r.get("no2"), co_ppm_mean=r.get("co"),
        temperature_c=r.get("temperature"), humidity_pct=r.get("humidity"),
    ) for r in rows]

    total = len(points)
    total_pages = max(1, math.ceil(total / page_size))
    page_points = points[(page - 1) * page_size: page * page_size]

    return AqiHistoryResponse(
        zone_id=zone_id, resolution=resolution, start=start, end=end,
        data=page_points,
        pagination=Pagination(page=page, page_size=page_size,
                              total_pages=total_pages, total_count=total),
    )
