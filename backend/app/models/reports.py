"""Modèles Pydantic — /reports (API_SPEC.md §4.8, §5.1, §7.1)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ReportCreate(BaseModel):
    description: str = Field(min_length=10, max_length=500)
    lat: float = Field(ge=14.50, le=14.90)    # presqu'île de Dakar
    lon: float = Field(ge=-17.60, le=-17.20)
    type: Literal["smoke", "dust", "odor", "chemical", "noise", "other"]
    intensity: Optional[Literal["low", "medium", "high"]] = "medium"
    media_url: Optional[HttpUrl] = None

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("Description trop courte (min 10 chars non-vides)")
        return v.strip()


class ReportCreated(BaseModel):
    report_id: int
    status: str = "received"
    message: str = "Signalement reçu. Il sera traité dans quelques secondes."
    estimated_processing_s: int = 5


class PublicReport(BaseModel):
    id: int
    created_at: datetime
    zone_id: Optional[str] = None
    lat_approx: Optional[float] = None
    lon_approx: Optional[float] = None
    type: Optional[str] = None
    description_excerpt: str
    entities: list[str] = []
    anomaly_correlated: bool = False
    upvotes: int = 0


class ReportsResponse(BaseModel):
    reports: list[PublicReport]
    meta: dict[str, Any]
