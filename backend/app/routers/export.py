"""Router /export — export CSV/JSON pour chercheurs (API_SPEC.md §6.1).

Chaque export est audité dans audit_logs (action EXPORT)."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.db import influxdb
from app.security.rate_limit import limiter
from app.security.rbac import require_role
from app.utils.audit import log_sensitive_access

router = APIRouter(prefix="/export", tags=["export"])

EXPORT_POLLUTANTS = {"pm25", "pm10", "no2", "co", "o3"}
MAX_RANGE_DAYS = 30


@router.get("/data")
@limiter.limit("5/hour")
def export_data(request: Request,
                zone_id: str = Query(...),
                start: datetime = Query(...),
                end: datetime = Query(...),
                pollutants: str = Query("pm25,pm10,no2,co"),
                format: str = Query("csv", pattern="^(csv|json)$"),
                user: dict = Depends(require_role("researcher"))):
    if end <= start:
        raise HTTPException(400, detail={"code": "INVALID_PARAMS",
                                         "message": "start doit précéder end"})
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(400, detail={"code": "INVALID_PARAMS",
                                         "message": f"Période max : {MAX_RANGE_DAYS} jours"})
    selected = [p.strip() for p in pollutants.split(",") if p.strip() in EXPORT_POLLUTANTS]
    if not selected:
        raise HTTPException(400, detail={"code": "INVALID_PARAMS",
                                         "message": f"pollutants ∈ {sorted(EXPORT_POLLUTANTS)}"})

    rows = influxdb.export_rows(zone_id, start, end, selected)
    log_sensitive_access("EXPORT", "air_quality", user["sub"],
                         request.client.host if request.client else None,
                         {"zone_id": zone_id, "start": start, "end": end,
                          "pollutants": selected, "n_rows": len(rows)})

    columns = ["timestamp", "zone_id"] + selected + ["temperature", "humidity"]

    def row_dict(r: dict) -> dict:
        return {
            "timestamp": r["_time"].isoformat() if hasattr(r.get("_time"), "isoformat") else r.get("_time"),
            "zone_id": zone_id,
            **{c: r.get(c) for c in columns[2:]},
        }

    if format == "json":
        payload = json.dumps([row_dict(r) for r in rows], default=str)
        return StreamingResponse(io.BytesIO(payload.encode()), media_type="application/json")

    def csv_stream():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns)
        writer.writeheader()
        yield buf.getvalue()
        for r in rows:
            buf.seek(0); buf.truncate()
            writer.writerow(row_dict(r))
            yield buf.getvalue()

    return StreamingResponse(
        csv_stream(), media_type="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename=export_{zone_id}_{start:%Y%m%d}_{end:%Y%m%d}.csv"},
    )
