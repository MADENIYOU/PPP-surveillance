"""Router /reports — signalements citoyens (API_SPEC.md §4.8, §5.1).

GET : lecture publique anonymisée (la position stockée est DÉJÀ anonymisée
par anonymize_geom à l'insertion — on re-floute en plus à la lecture via
ST_SnapToGrid 0.005° ≈ 500m, défense en profondeur).
POST : authentifié citizen+, insertion + statut nlp 'pending' (le flow NLP
les ramasse par batch — voir flows/nlp_pipeline.py)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.db import postgres
from app.models.reports import PublicReport, ReportCreate, ReportCreated, ReportsResponse
from app.security.jwt import get_current_user
from app.security.rate_limit import limiter

router = APIRouter(prefix="/reports", tags=["reports"])

TYPE_LABELS = {"smoke", "dust", "odor", "chemical", "noise", "other"}


@router.get("", response_model=ReportsResponse)
@limiter.limit("100/minute")
def list_reports(request: Request,
                 zone_id: Optional[str] = Query(None),
                 hours: int = Query(24, ge=1, le=168),
                 type: Optional[str] = Query(None),
                 limit: int = Query(50, ge=1, le=200)):
    if type and type not in TYPE_LABELS:
        raise HTTPException(400, detail={"code": "INVALID_PARAMS",
                                         "message": f"type ∈ {sorted(TYPE_LABELS)}"})
    clauses = ["r.created_at > now() - (%s * interval '1 hour')"]
    params: list = [hours]
    if zone_id:
        clauses.append("""r.geom IS NOT NULL AND EXISTS (
            SELECT 1 FROM zones z WHERE z.path ~ %s AND ST_Contains(z.geom, r.geom))""")
        params.append(f"*.{zone_id}")
    if type:
        clauses.append("r.metadata->>'type' = %s")
        params.append(type)
    params.append(limit)

    with postgres.cursor() as cur:
        cur.execute(f"""
            SELECT r.id, r.created_at, r.metadata,
                   left(r.texte, 100) AS excerpt,
                   ST_Y(ST_SnapToGrid(r.geom, 0.005)) AS lat_approx,
                   ST_X(ST_SnapToGrid(r.geom, 0.005)) AS lon_approx,
                   (SELECT split_part(z.path::text, '.', -1) FROM zones z
                    WHERE z.niveau = 3 AND ST_Contains(z.geom, r.geom)
                    ORDER BY ST_Area(z.geom) LIMIT 1) AS zone_slug,
                   COALESCE(array_agg(DISTINCT e.entity_value)
                            FILTER (WHERE e.entity_value IS NOT NULL), '{{}}') AS entities,
                   EXISTS (SELECT 1 FROM anomaly_labels al WHERE al.report_id = r.id)
                       AS anomaly_correlated
            FROM reports r
            LEFT JOIN report_entities e ON e.report_id = r.id
            WHERE {' AND '.join(clauses)}
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT %s
        """, params)
        rows = cur.fetchall()

    reports = [PublicReport(
        id=r["id"], created_at=r["created_at"], zone_id=r["zone_slug"],
        lat_approx=r["lat_approx"], lon_approx=r["lon_approx"],
        type=(r["metadata"] or {}).get("type"),
        description_excerpt=(r["excerpt"] or "") + ("..." if len(r["excerpt"] or "") == 100 else ""),
        entities=list(r["entities"] or []),
        anomaly_correlated=r["anomaly_correlated"],
        upvotes=int((r["metadata"] or {}).get("upvotes", 0)),
    ) for r in rows]

    return ReportsResponse(reports=reports, meta={
        "total": len(reports), "zone_id": zone_id,
        "generated_at": datetime.now(timezone.utc),
    })


@router.post("", response_model=ReportCreated, status_code=201)
@limiter.limit("10/minute")
def create_report(request: Request, body: ReportCreate,
                  user: dict = Depends(get_current_user)):
    with postgres.cursor() as cur:
        # Profil citoyen lié au compte (créé à la volée au premier signalement)
        cur.execute("SELECT citizen_id FROM users WHERE id = %s", (user["sub"],))
        row = cur.fetchone()
        citizen_id = row["citizen_id"] if row else None
        if citizen_id is None:
            cur.execute("""
                INSERT INTO citizens (pseudonyme)
                VALUES ('user_' || left(%s, 8))
                ON CONFLICT (pseudonyme) DO UPDATE SET last_active = now()
                RETURNING id
            """, (user["sub"],))
            citizen_id = cur.fetchone()["id"]
            cur.execute("UPDATE users SET citizen_id = %s WHERE id = %s",
                        (citizen_id, user["sub"]))

        # Position anonymisée dès l'insertion (SnapToGrid + jitter borné zone)
        cur.execute("""
            INSERT INTO reports (citizen_id, texte, geom, source_app, metadata)
            VALUES (%s, %s,
                    anonymize_geom(ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                                   resolve_zone_id(ST_SetSRID(ST_MakePoint(%s, %s), 4326))),
                    'web',
                    jsonb_build_object('type', %s, 'intensity', %s, 'media_url', %s))
            RETURNING id
        """, (citizen_id, body.description, body.lon, body.lat, body.lon, body.lat,
              body.type, body.intensity, str(body.media_url) if body.media_url else None))
        report_id = cur.fetchone()["id"]
        cur.execute("UPDATE citizens SET nb_reports = nb_reports + 1, last_active = now() WHERE id = %s",
                    (citizen_id,))

    return ReportCreated(report_id=report_id)
