"""Modèles physiques des capteurs bas coût — bruit, dérive, corrections.

Référence : simulation/SIMULATION_SPEC.md §2.
Classes : PMS5003Model, BME280Model, MICS6814Model.

Chaque modèle convertit une valeur "vraie" (issue d'atmospheric_models) en
valeur "brute" telle que mesurée par le capteur, en appliquant les corrections
environnementales, le bruit gaussien et la dérive long-terme documentés.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


def _clip_resolution(value: float, resolution: float) -> float:
    """Arrondit à la résolution du capteur et empêche les valeurs négatives."""
    return max(0.0, round(value / resolution) * resolution)


# ============================================================================
# PMS5003 — particules PM1.0 / PM2.5 / PM10 (§2.1)
# ============================================================================
@dataclass
class PMS5003Model:
    seed: int | None = None
    install_date: datetime | None = None

    # Paramètres tirés à l'initialisation (dérive individuelle, §2.1)
    drift_rate: float = field(init=False)   # µg/m³/jour, U(0.05, 0.30)
    bias: float = field(init=False)         # N(0, 2) µg/m³
    last_calibration: datetime | None = field(init=False, default=None)

    _SIGMA = {
        "pm1_0": {"normal": 1.5, "harmattan": 3.0, "resolution": 1.0},
        "pm2_5": {"normal": 2.0, "harmattan": 4.0, "resolution": 1.0},
        "pm10": {"normal": 3.5, "harmattan": 7.0, "resolution": 1.0},
    }

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)
        self.drift_rate = float(self._rng.uniform(0.05, 0.30))
        self.bias = float(self._rng.normal(0.0, 2.0))
        self.last_calibration = self.install_date

    def recalibrate(self, when: datetime) -> None:
        """Événement CALIBRATION : réinitialise la dérive accumulée (§2.1)."""
        self.last_calibration = when

    def calibration_age_days(self, now: datetime) -> float:
        if self.last_calibration is None:
            return 0.0
        return max(0.0, (now - self.last_calibration).total_seconds() / 86400)

    @staticmethod
    def humidity_correction(rh_pct: float, channel: str) -> float:
        """C_humidite(RH) = 1 + α×(RH/100)² — Badura et al. 2018 (§2.1)."""
        alpha = 0.25 if channel == "pm2_5" else 0.15
        return 1.0 + alpha * (rh_pct / 100.0) ** 2

    @staticmethod
    def temperature_correction(temp_c: float) -> float:
        """C_temperature(T) = 1 + β×(T - T_ref)/T_ref, β=0.02, T_ref=25°C."""
        return 1.0 + 0.02 * (temp_c - 25.0) / 25.0

    def _drift(self, now: datetime) -> float:
        days = self.calibration_age_days(now)
        return self.drift_rate * days

    def measure(
        self,
        true_pm25: float,
        true_pm10: float,
        temp_c: float,
        humidity_pct: float,
        now: datetime,
        harmattan_active: bool = False,
    ) -> dict:
        """Retourne {"pm1_0", "pm2_5", "pm10", "humidity_correction_applied"}.

        Applique corrections environnementales, bruit, dérive puis impose la
        contrainte physique PM1.0 ≤ PM2.5 ≤ PM10 (§2.1).
        """
        true_pm1 = true_pm25 * 0.65
        regime = "harmattan" if harmattan_active else "normal"
        drift = self._drift(now)
        humidity_applied = humidity_pct <= 85.0

        results: dict[str, float] = {}
        for channel, true_value in (("pm1_0", true_pm1), ("pm2_5", true_pm25), ("pm10", true_pm10)):
            params = self._SIGMA[channel]
            c_hum = self.humidity_correction(min(humidity_pct, 85.0), channel)
            c_temp = self.temperature_correction(temp_c)
            sigma = params[regime]
            noise = float(self._rng.normal(0.0, sigma))
            raw = true_value * c_hum * c_temp + noise + drift + self.bias
            results[channel] = _clip_resolution(raw, params["resolution"])

        # Contrainte physique : PM1.0 ≤ PM2.5 ≤ PM10 (tolérance — on force si violée)
        if results["pm10"] < results["pm2_5"] * 1.1:
            results["pm10"] = results["pm2_5"] * 1.1
        if results["pm1_0"] > results["pm2_5"]:
            results["pm1_0"] = results["pm2_5"]

        return {
            "pm1_0": results["pm1_0"],
            "pm2_5": results["pm2_5"],
            "pm10": results["pm10"],
            "humidity_correction_applied": humidity_applied,
        }


# ============================================================================
# BME280 — environnemental T / H / P (§2.2)
# ============================================================================
@dataclass
class BME280Model:
    seed: int | None = None
    _tau_s: float = 8.0  # constante de temps thermique (réponse humidité)

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)
        self._prev_humidity: float | None = None

    def measure(self, true_temp_c: float, true_humidity_pct: float, true_pressure_hpa: float,
                dt_seconds: float = 30.0) -> dict:
        """ε_T~N(0,0.3), ε_H~N(0,1.5), ε_P~N(0,0.2) + délai de réponse humidité (§2.2)."""
        temp = true_temp_c + float(self._rng.normal(0.0, 0.3))
        pressure = true_pressure_hpa + float(self._rng.normal(0.0, 0.2))

        humidity_target = true_humidity_pct + float(self._rng.normal(0.0, 1.5))
        if self._prev_humidity is None:
            humidity = humidity_target
        else:
            decay = math.exp(-dt_seconds / self._tau_s)
            humidity = humidity_target * (1 - decay) + self._prev_humidity * decay
        self._prev_humidity = humidity

        return {
            "temperature_c": max(-40.0, min(85.0, temp)),
            "humidity_pct": max(0.0, min(100.0, humidity)),
            "pressure_hpa": max(300.0, min(1100.0, pressure)),
        }


# ============================================================================
# MICS-6814 — électrochimique CO / NO2 / NH3 (§2.3)
# ============================================================================
@dataclass
class MICS6814Model:
    seed: int | None = None
    init_time: datetime | None = None

    WARMUP_SECONDS = 3 * 60  # 3 minutes de préchauffage (§2.3)

    co_offset: float = field(init=False)       # N(0, 8) ppm, tiré à l'init
    _drift_co_rate = 0.5    # ppm/jour
    _drift_no2_rate = 0.8   # ppb/jour

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)
        self.co_offset = float(self._rng.normal(0.0, 8.0))

    def is_warming_up(self, now: datetime, last_restart: datetime | None) -> bool:
        if last_restart is None:
            return False
        return (now - last_restart).total_seconds() < self.WARMUP_SECONDS

    def _days_since_init(self, now: datetime) -> float:
        if self.init_time is None:
            return 0.0
        return max(0.0, (now - self.init_time).total_seconds() / 86400)

    def measure_co(self, true_co_ppm: float, temp_c: float, humidity_pct: float,
                   true_no2_ppb: float, now: datetime, warming_up: bool = False) -> float:
        """f_cross(T,H,NO2) + ε_CO + drift_CO + offset_individuel (§2.3)."""
        no2_normalized = true_no2_ppb / 40.0  # normalisation arbitraire (échelle ppb typique Dakar)
        f_cross = 1 + 0.015 * (temp_c - 20) + 0.008 * (humidity_pct - 50) + 0.02 * no2_normalized
        sigma_co = 5.0 + 0.03 * true_co_ppm
        if warming_up:
            sigma_co *= 5
        noise = float(self._rng.normal(0.0, sigma_co))
        drift = self._drift_co_rate * self._days_since_init(now)
        raw = true_co_ppm * f_cross + noise + drift + self.co_offset
        return max(0.0, raw)

    def measure_no2(self, true_no2_ppb: float, temp_c: float, now: datetime,
                    warming_up: bool = False) -> float:
        """NO2_brut = NO2_vrai×(1+0.02×(T-25)) + ε_NO2 + drift_NO2 (§2.3)."""
        sigma_no2 = 3.0 + 0.05 * true_no2_ppb
        if warming_up:
            sigma_no2 *= 5
        noise = float(self._rng.normal(0.0, sigma_no2))
        drift = self._drift_no2_rate * self._days_since_init(now)
        raw = true_no2_ppb * (1 + 0.02 * (temp_c - 25)) + noise + drift
        return max(0.0, raw)

    def measure_nh3(self, true_nh3_ppm: float, warming_up: bool = False) -> float:
        """Pas de modèle dédié dans la spec — bruit proportionnel analogue au CO."""
        sigma = 0.5 + 0.05 * true_nh3_ppm
        if warming_up:
            sigma *= 5
        noise = float(self._rng.normal(0.0, sigma))
        return max(0.0, true_nh3_ppm + noise)


def o3_estimated(no2_true_ppb: float, temp_c: float, solar_radiation_index: float,
                 rng: np.random.Generator) -> float:
    """O3_estimé = max(0, 30 + 0.8×solar - 0.3×NO2 + 0.5×T + ε), ε~N(0,5) (§2.4)."""
    noise = float(rng.normal(0.0, 5.0))
    return max(0.0, 30 + 0.8 * solar_radiation_index - 0.3 * no2_true_ppb + 0.5 * temp_c + noise)
