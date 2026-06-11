"""Router /predictions — dernières prédictions t+1h/6h/24h (API_SPEC.md §4.5).

Source : table PostgreSQL `predictions` (écrite par flows/predictions.py),
horizons 60/360/1440 minutes, dernier run par zone."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, Request

from app.db import postgres
from app.models.predictions import PredictionHorizon, PredictionsResponse, ZonePredictions
from app.security.rate_limit import limiter
from app.utils.iqa_calculator import compute_iqa

router = APIRouter(prefix="/predictions", tags=["predictions"])

HORIZON_KEYS = {60: "h1", 360: "h6", 1440: "h24"}


def _trend(pred: float, current: Optional[float]) -> Optional[str]:
    if current is None:
        return None
    if pred > current * 1.1:
        return "increasing"
    if pred < current * 0.9:
        return "decreasing"
    return "stable"


@router.get("", response_model=PredictionsResponse)
@limiter.limit("100/minute")
def get_predictions(request: Request,
                    zone_id: Optional[str] = Query(None),
                    include_ci: bool = Query(True)):
    params: list = []
    zone_clause = ""
    if zone_id:
        zone_clause = "AND z.path ~ %s"
        params.append(f"*.{zone_id}")

    # Dernière prédiction par (zone, horizon) — DISTINCT ON après tri par création
    with postgres.cursor() as cur:
        cur.execute(f"""
            SELECT DISTINCT ON (p.zone_id, p.horizon_minutes)
                   split_part(z.path::text, '.', -1) AS zone_slug,
                   p.horizon_minutes, p.predicted_value, p.ci_lower, p.ci_upper,
                   p.target_timestamp, p.created_at,
                   m.name AS model_name, m.version AS model_version
            FROM predictions p
            JOIN zones z ON z.id = p.zone_id
            JOIN models m ON m.id = p.model_id
            WHERE p.pollutant = 'pm25'
              AND p.horizon_minutes IN (60, 360, 1440)
              AND p.created_at > now() - interval '6 hours'
              {zone_clause}
            ORDER BY p.zone_id, p.horizon_minutes, p.created_at DESC
        """, params)
        rows = [dict(r) for r in cur.fetchall()]

    by_zone: dict[str, dict] = {}
    for r in rows:
        z = by_zone.setdefault(r["zone_slug"], {
            "predicted_at": r["created_at"], "model": r["model_name"], "horizons": {},
        })
        key = HORIZON_KEYS[r["horizon_minutes"]]
        z["horizons"][key] = PredictionHorizon(
            target_at=r["target_timestamp"],
            pm25_pred=max(0.0, float(r["predicted_value"])),
            iqa_pred=compute_iqa(r["predicted_value"]),
            ci_lower_95=float(r["ci_lower"]) if include_ci and r["ci_lower"] is not None else None,
            ci_upper_95=float(r["ci_upper"]) if include_ci and r["ci_upper"] is not None else None,
        )

    predictions = [ZonePredictions(zone_id=slug, predicted_at=d["predicted_at"],
                                   model_used=d["model"], horizons=d["horizons"])
                   for slug, d in sorted(by_zone.items())]
    model_version = rows[0]["model_version"] if rows else None
    return PredictionsResponse(predictions=predictions, meta={
        "generated_at": datetime.now(timezone.utc), "model_version": model_version,
    })
