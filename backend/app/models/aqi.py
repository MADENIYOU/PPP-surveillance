"""Modèles Pydantic — /aqi/* (API_SPEC.md §4.1, §4.2, §7.1)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ZoneAQI(BaseModel):
    zone_id: str
    zone_name: str
    lat_center: float
    lon_center: float
    timestamp: Optional[datetime] = None
    iqa: Optional[int] = Field(None, ge=0, le=500)
    iqa_level: Optional[str] = None
    iqa_label_fr: Optional[str] = None
    iqa_color: Optional[str] = None
    pm25_ug_m3: Optional[float] = Field(None, ge=0, le=1000)
    pm10_ug_m3: Optional[float] = Field(None, ge=0, le=2000)
    no2_ppb: Optional[float] = None
    co_ppm: Optional[float] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    dominant_pollutant: Optional[str] = None
    sensor_count: int = 0
    sensors_active: int = 0
    data_freshness_s: Optional[int] = None
    trend: Optional[Literal["increasing", "decreasing", "stable"]] = None


class AqiCurrentMeta(BaseModel):
    generated_at: datetime
    n_zones: int
    n_zones_active: int


class AqiCurrentResponse(BaseModel):
    zones: list[ZoneAQI]
    meta: AqiCurrentMeta


class HistoryPoint(BaseModel):
    timestamp: datetime
    iqa: Optional[int] = None
    pm25_mean: Optional[float] = None
    pm10_mean: Optional[float] = None
    no2_ppb_mean: Optional[float] = None
    co_ppm_mean: Optional[float] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None


class Pagination(BaseModel):
    page: int
    page_size: int
    total_pages: int
    total_count: int


class AqiHistoryResponse(BaseModel):
    zone_id: str
    resolution: str
    start: datetime
    end: datetime
    data: list[HistoryPoint]
    pagination: Pagination
