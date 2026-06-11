"""Router /admin — backoffice capteurs (API_SPEC.md §6.2, RBAC admin)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from app.db import postgres
from app.models.auth import AdminErasureRequest, ErasureResponse
from app.security.rate_limit import limiter
from app.security.rbac import require_role
from app.utils.audit import log_sensitive_access

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/sensors")
@limiter.limit("60/minute")
def admin_sensors(request: Request, user: dict = Depends(require_role("admin"))):
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT s.serial_number AS sensor_id, s.type, s.status,
                   s.firmware_version, s.install_date, s.last_seen, s.metadata,
                   ST_Y(s.geom) AS lat, ST_X(s.geom) AS lon,
                   z.nom AS zone_name, split_part(z.path::text, '.', -1) AS zone_id,
                   c.coef_a, c.coef_b, c.r2_score, c.valid_from AS calibration_date
            FROM sensors s
            JOIN zones z ON z.id = s.zone_id
            LEFT JOIN calibration c ON c.sensor_id = s.id AND c.valid_until IS NULL
            ORDER BY s.serial_number
        """)
        rows = [dict(r) for r in cur.fetchall()]

    log_sensitive_access("READ_REPORT", "sensors", user["sub"],
                         request.client.host if request.client else None,
                         {"endpoint": "/admin/sensors", "n_rows": len(rows)})

    for r in rows:
        meta = r.get("metadata") or {}
        r["cert_fingerprint"] = meta.get("cert_fingerprint")
        r["install_notes"] = meta.get("install_notes")
        r["drift_rate_estimated"] = meta.get("drift_rate_estimated")

    return {"sensors": rows,
            "meta": {"total": len(rows), "generated_at": datetime.now(timezone.utc)}}


@router.post("/gdpr/erase", response_model=ErasureResponse)
@limiter.limit("2/hour")
def admin_erase_user(request: Request, body: AdminErasureRequest,
                     user: dict = Depends(require_role("super_admin"))):
    """Effacement RGPD initié par un administrateur super_admin."""
    with postgres.cursor() as cur:
        cur.execute("SELECT * FROM gdpr_erase_user(%s::uuid)", (body.user_id,))
        cur.fetchall()

    log_sensitive_access("DELETE", "users", body.user_id,
                         request.client.host if request.client else None,
                         {"gdpr_erasure": True, "admin_initiated": True, "reason": body.reason,
                          "by_admin": user["sub"]})

    return ErasureResponse(
        message=f"Compte utilisateur {body.user_id} effacé. Raison: {body.reason}"
    )
