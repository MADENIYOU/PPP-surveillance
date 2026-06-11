"""Modèles Pydantic — /predictions et /alerts (API_SPEC.md §4.5, §4.7, §7.1)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class PredictionHorizon(BaseModel):
    target_at: datetime
    pm25_pred: float = Field(ge=0, le=1000)
    iqa_pred: Optional[int] = Field(None, ge=0, le=500)
    ci_lower_95: Optional[float] = Field(None, ge=0)
    ci_upper_95: Optional[float] = Field(None, le=2000)
    trend: Optional[Literal["increasing", "decreasing", "stable"]] = None


class ZonePredictions(BaseModel):
    zone_id: str
    predicted_at: datetime
    model_used: Optional[str] = None
    horizons: dict[str, PredictionHorizon]


class PredictionsResponse(BaseModel):
    predictions: list[ZonePredictions]
    meta: dict[str, Any]


class Alert(BaseModel):
    id: int
    zone_id: str
    zone_name: str
    type: str
    gravite: str
    message: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
    active: bool = True
    sensor_id: Optional[str] = None


class AlertsResponse(BaseModel):
    alerts: list[Alert]
    meta: dict[str, Any]
