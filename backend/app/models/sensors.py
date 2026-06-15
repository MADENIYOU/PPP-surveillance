"""Modèles Pydantic — /sensors/* (API_SPEC.md §4.3, §4.4, §6.2)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class SensorSummary(BaseModel):
    sensor_id: str
    zone_id: str
    zone_name: str
    lat: float
    lon: float
    status: str
    last_seen: Optional[datetime] = None
    firmware: Optional[str] = None
    battery_pct: Optional[float] = None
    solar_active: Optional[bool] = None
    rssi_dbm: Optional[float] = None
    last_pm25: Optional[float] = None
    sim: bool = False


class SensorsResponse(BaseModel):
    sensors: list[SensorSummary]
    meta: dict[str, Any]


class SensorHistoryPoint(BaseModel):
    timestamp: str
    value: float


class SensorDetail(SensorSummary):
    pm25_history: list[SensorHistoryPoint] = []
    calibration_coefficients: Optional[dict[str, float]] = None
    messages_today: int = 0


class SensorsDetailResponse(BaseModel):
    sensors: list[SensorDetail]
    meta: dict[str, Any]


class SensorCurrent(BaseModel):
    pm25: Optional[float] = None
    pm10: Optional[float] = None
    co_ppm: Optional[float] = None
    no2_ppb: Optional[float] = None
    o3_ppb: Optional[float] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    pressure_hpa: Optional[float] = None


class SensorDataResponse(BaseModel):
    sensor_id: str
    zone_id: str
    last_update: Optional[datetime] = None
    current: SensorCurrent
    timeseries: list[dict[str, Any]]


class AdminSensor(SensorSummary):
    install_notes: Optional[str] = None
    calibration_date: Optional[str] = None
    cert_fingerprint: Optional[str] = None
    drift_rate_estimated: Optional[float] = None
    metadata: dict[str, Any] = {}
