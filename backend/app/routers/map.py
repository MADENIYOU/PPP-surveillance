"""Router /map — heatmap kriging GeoJSON (API_SPEC.md §4.6).

Source : table `kriging_results` (flow flows/kriging.py, grille GPR 200×200)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.db import postgres
from app.security.rate_limit import limiter

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/kriging")
@limiter.limit("100/minute")
def kriging_map(request: Request,
                max_age_hours: int = Query(2, ge=1, le=48),
                bbox: Optional[str] = Query(None)):
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT computed_at, geojson, rmse_loo, grid_resolution
            FROM kriging_results
            ORDER BY computed_at DESC LIMIT 1
        """)
        row = cur.fetchone()
    if row is None:
        return {
            "metadata": {
                "generated_at": None,
                "age_minutes": None,
                "pm25_min": None,
                "pm25_max": None,
                "rmse_loo": None,
                "n_sensors_used": None,
                "status": "computing",
            },
            "geojson": {"type": "FeatureCollection", "features": []},
        }

    now = datetime.now(timezone.utc)
    age_minutes = (now - row["computed_at"]).total_seconds() / 60
    if age_minutes > max_age_hours * 60:
        raise HTTPException(503, detail={"code": "SERVICE_UNAVAILABLE",
                                         "message": f"Heatmap trop ancienne ({age_minutes:.0f} min)."})

    geojson = row["geojson"]
    features = geojson.get("features", []) if isinstance(geojson, dict) else []

    if bbox:
        try:
            lat_min, lon_min, lat_max, lon_max = (float(x) for x in bbox.split(","))
        except ValueError:
            raise HTTPException(400, detail={"code": "INVALID_PARAMS",
                                             "message": "bbox = lat_min,lon_min,lat_max,lon_max"})
        features = [f for f in features
                    if f.get("geometry", {}).get("type") == "Point"
                    and lon_min <= f["geometry"]["coordinates"][0] <= lon_max
                    and lat_min <= f["geometry"]["coordinates"][1] <= lat_max]
        geojson = {**geojson, "features": features}

    pm_values = [f["properties"].get("pm25") for f in features
                 if f.get("properties", {}).get("pm25") is not None]
    return {
        "metadata": {
            "generated_at": row["computed_at"],
            "age_minutes": round(age_minutes),
            "pm25_min": min(pm_values) if pm_values else None,
            "pm25_max": max(pm_values) if pm_values else None,
            "rmse_loo": row["rmse_loo"],
            "n_sensors_used": (geojson.get("metadata", {}) or {}).get("n_sensors_used")
            if isinstance(geojson, dict) else None,
        },
        "geojson": geojson,
    }
