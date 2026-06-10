"""Schémas Pydantic partagés du pipeline — contrat de validation des données.

Référence : pipeline/PIPELINE_SPEC.md §2.2 (`SensorPayload`), §4 (`AnomalyRecord`),
§4.2 (`Alert`).

`SensorPayload` (et les modèles imbriqués `Measurements`, `Battery`, `Network`,
`Position`, `DataQuality`, `SimMetadata`) reproduisent EXACTEMENT le schéma
publié par `simulation/data_generator.py` (§5.1 SIMULATION_SPEC) : c'est le
contrat MQTT que l'étape d'ingestion valide. Les deux fichiers doivent rester
synchronisés — un vrai capteur produit la même structure (sans `sim`/`sim_metadata`,
champs optionnels ici pour accepter aussi bien le matériel réel que la simulation).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

SENSOR_ID_PATTERN = r"^ESP32-DK-[A-Z]+-\d{3}$"


# ============================================================================
# Payload capteur — MQTT dakar/sensors/{sensor_id}/data (§5.1 SIMULATION_SPEC)
# ============================================================================
class Measurements(BaseModel):
    pm1_0: float
    pm2_5: float
    pm10: float
    co_ppm: float
    no2_ppb: float
    o3_ppb_est: float
    nh3_ppm: float
    temperature_c: float
    humidity_pct: float
    pressure_hpa: float
    warm_up: bool

    @field_validator("humidity_pct")
    @classmethod
    def _humidity_range(cls, v: float) -> float:
        if not 0 <= v <= 100:
            raise ValueError("humidity_pct doit être dans [0, 100]")
        return v

    @field_validator("temperature_c")
    @classmethod
    def _temperature_range(cls, v: float) -> float:
        if not -10 <= v <= 60:
            raise ValueError("temperature_c doit être dans [-10, 60]")
        return v


class DataQuality(BaseModel):
    humidity_correction_applied: bool
    warming_up: bool
    calibration_age_days: float
    confidence_score: float


class Battery(BaseModel):
    voltage_v: float
    level_pct: int
    charging: bool
    solar_active: bool


class Network(BaseModel):
    type: str
    rssi_dbm: int
    reconnects: int
    buffer_pending: int


class Position(BaseModel):
    lat: float
    lon: float
    source: str = "config"


class SimMetadata(BaseModel):
    run_id: str
    true_pm25: float
    anomaly_active: bool = False
    anomaly_type: Optional[str] = None


class SensorPayload(BaseModel):
    sensor_id: str = Field(pattern=SENSOR_ID_PATTERN)
    timestamp: datetime
    seq: int
    firmware: str
    measurements: Measurements
    data_quality: DataQuality
    battery: Battery
    network: Network
    position: Position
    sim: bool = False
    sim_metadata: Optional[SimMetadata] = None

    @field_validator("seq")
    @classmethod
    def _seq_range(cls, v: int) -> int:
        if not 0 <= v < 2**31:
            raise ValueError("seq doit être un entier 32 bits positif")
        return v


# ============================================================================
# Détection d'anomalies — §4 (worker anomaly_detector)
# ============================================================================
class AnomalyRecord(BaseModel):
    """Reflète la table PostgreSQL `anomaly_detections` (01_schema.sql).

    `sensor_id`/`zone_id` portent ici les identifiants internes (INT) de la
    base — la résolution `sensor_id` capteur (ESP32-...) → ID interne se fait
    en amont, dans le worker, via `db.postgres_client`."""
    sensor_id: Optional[int] = None
    zone_id: int
    model_id: Optional[int] = None
    pollutant: str
    detected_value: float
    threshold: float
    anomaly_score: Optional[float] = None
    detected_at: datetime
    duration_minutes: Optional[int] = None
    handled: bool = False

    # Champs informatifs côté worker, non persistés tels quels (servent à
    # construire `description`/`message` de l'alerte associée — §4.1, §4.2).
    type: Optional[str] = None
    severity: Optional[str] = None
    affected_pollutants: List[str] = Field(default_factory=list)
    description: Optional[str] = None


# ============================================================================
# Alertes — §4.2 (table PostgreSQL `alerts`)
# ============================================================================
class Alert(BaseModel):
    prediction_id: Optional[str] = None
    anomaly_id: Optional[int] = None
    zone_id: int
    type: str
    pollutant: Optional[str] = None
    gravite: str
    message: str
    canal_envoi: List[str] = Field(default_factory=lambda: ["push"])
    statut_envoi: str = "pending"
    sent_at: Optional[datetime] = None
