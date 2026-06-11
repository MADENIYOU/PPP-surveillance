"""Router /alerts — alertes actives (API_SPEC.md §4.7)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, Request

from app.db import postgres
from app.models.predictions import Alert, AlertsResponse
from app.security.rate_limit import limiter

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=AlertsResponse)
@limiter.limit("100/minute")
def list_alerts(request: Request,
                zone_id: Optional[str] = Query(None),
                gravite: Optional[str] = Query(None, pattern="^(info|warning|danger|critical)$"),
                active_only: bool = Query(True),
                limit: int = Query(20, ge=1, le=100)):
    clauses, params = [], []
    if zone_id:
        clauses.append("z.path ~ %s")
        params.append(f"*.{zone_id}")
    if gravite:
        clauses.append("a.gravite = %s::alert_gravite")
        params.append(gravite)
    if active_only:
        # actif = non annulée et créée il y a < 24h (schéma sans resolved_at —
        # convention identique à la vue v_active_alerts de 01_schema.sql)
        clauses.append("a.statut_envoi IN ('pending', 'sent')")
        clauses.append("a.created_at > now() - interval '24 hours'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    with postgres.cursor() as cur:
        cur.execute(f"""
            SELECT a.id, a.type, a.gravite, a.message, a.created_at,
                   z.nom AS zone_name, split_part(z.path::text, '.', -1) AS zone_slug,
                   s.serial_number AS sensor_id
            FROM alerts a
            JOIN zones z ON z.id = a.zone_id
            LEFT JOIN anomaly_detections ad ON ad.id = a.anomaly_id
            LEFT JOIN sensors s ON s.id = ad.sensor_id
            {where}
            ORDER BY a.created_at DESC
            LIMIT %s
        """, params)
        rows = cur.fetchall()

    alerts = [Alert(
        id=r["id"], zone_id=r["zone_slug"], zone_name=r["zone_name"],
        type=str(r["type"]), gravite=str(r["gravite"]), message=r["message"],
        created_at=r["created_at"], active=True, sensor_id=r["sensor_id"],
    ) for r in rows]

    return AlertsResponse(alerts=alerts, meta={
        "total_active": len(alerts),
        "generated_at": datetime.now(timezone.utc),
    })
