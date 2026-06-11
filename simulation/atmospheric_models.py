"""Modèles atmosphériques de Dakar — cycles journaliers et saisonniers.

Référence : simulation/SIMULATION_SPEC.md §3.
Classes : DakarAtmosphericModel, SeasonalModel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

# Largeurs des pics bimodaux PM2.5 (§3.1, constantes globales)
SIGMA_MATIN = 1.5
SIGMA_SOIR = 2.0
SIGMA_NUIT = 1.0
H_NUIT = 22.0

# Facteurs hebdomadaires (§3.2) — index = datetime.weekday() (0=lundi .. 6=dimanche)
WEEKDAY_FACTORS = (1.00, 1.00, 1.00, 1.00, 1.00, 0.85, 0.70)

SEASONS = ("dry", "rain", "harmattan")


def _harmattan_intensity(month: int, rng: np.random.Generator) -> float:
    """Intensité Harmattan (§3.3) : non nulle de novembre (11) à mars (3)."""
    if month not in (11, 12, 1, 2, 3):
        return 0.0
    # mois - 11 modulo 12 ramène nov→0, déc→1, jan→2, fév→3, mar→4 (cycle de 4 mois)
    phase = (month - 11) % 12
    return float(rng.uniform(0.3, 1.0)) * math.sin(math.pi * phase / 4)


@dataclass
class SeasonalModel:
    """Détermine la saison et les paramètres associés à partir d'une date.

    `season_override` force une saison (CLI `--season`) indépendamment du mois.
    """

    season_override: str | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.season_override is not None and self.season_override not in SEASONS:
            raise ValueError(f"Saison inconnue : {self.season_override!r} (attendu : {SEASONS})")
        self._rng = np.random.default_rng(self.seed)
        self._last_rain_time: datetime | None = None

    def season_for(self, dt: datetime) -> str:
        if self.season_override is not None:
            return self.season_override
        month = dt.month
        if month in (11, 12, 1, 2, 3):
            return "harmattan"
        if month in (7, 8, 9, 10):
            return "rain"
        return "dry"

    def temperature_humidity(self, dt: datetime) -> tuple[float, float]:
        """T_vrai(h), H_vrai(h) — §3.6, anti-corrélées, dépendantes de la saison."""
        season = self.season_for(dt)
        h = dt.hour + dt.minute / 60.0
        if season == "rain":
            t_mean, delta_t, h_mean, delta_h = 30.0, 5.0, 78.0, 15.0
        else:  # "dry" et "harmattan" partagent le même profil thermique de base (§3.6)
            t_mean, delta_t, h_mean, delta_h = 28.0, 8.0, 55.0, 20.0

        if 6 <= h <= 18:
            t = t_mean + (delta_t / 2) * math.sin(math.pi * (h - 6) / 12)
        else:
            t = t_mean - (delta_t / 4) * math.sin(math.pi * (h - 18) / 12)
        humidity = h_mean - (delta_h / 2) * math.sin(math.pi * (h - 6) / 12)
        return t, humidity

    def harmattan_flag_and_bonus(self, dt: datetime) -> tuple[bool, float]:
        """Retourne (H_flag, Fond_harmattan) — §3.3."""
        if self.season_for(dt) != "harmattan":
            return False, 0.0
        intensity = _harmattan_intensity(dt.month, self._rng)
        if intensity <= 0.5:
            return False, 0.0
        # Fond_harmattan ∈ [+15, +50] µg/m³ proportionnel à l'intensité ∈ ]0.5, 1.0]
        bonus = 15.0 + (intensity - 0.5) / 0.5 * 35.0
        return True, bonus

    def mark_rain(self, dt: datetime) -> None:
        self._last_rain_time = dt

    def rain_reduction(self, dt: datetime) -> float:
        """Facteur multiplicatif lié à la saison des pluies (§3.3).

        - Lessivage atmosphérique structurel : ×0.70 pendant l'hivernage.
        - Effet pluie immédiat (2h après précipitation) : -30% supplémentaires.
        """
        if self.season_for(dt) != "rain":
            return 1.0
        factor = 0.70
        rained = self._last_rain_time is not None and (dt - self._last_rain_time).total_seconds() < 7200
        if rained:
            factor *= 0.70
        return factor


@dataclass
class DakarAtmosphericModel:
    """Calcule les valeurs "vraies" (sans bruit capteur) des polluants pour une zone.

    `zone_params` : dict issu de config/zones.yaml, clé "zones".
    `profile_params` : dict issu de config/zones.yaml, clé "pollution_profiles"
                       (sélectionné via `pollution_profile` du capteur).
    """

    zone_params: dict
    profile_params: dict | None = None
    seasonal: SeasonalModel | None = None

    def __post_init__(self) -> None:
        if self.seasonal is None:
            self.seasonal = SeasonalModel()
        self._profile = self.profile_params or {}

    # ── PM2.5 (§3.1) — modèle bimodal + harmattan + saisonnalité + hebdo ──────
    def pm25_true(self, dt: datetime) -> float:
        h = dt.hour + dt.minute / 60.0
        zp = self.zone_params

        value = zp["pm_base"]
        value += zp["a_matin"] * math.exp(-((h - zp["h_matin"]) ** 2) / (2 * SIGMA_MATIN ** 2))
        value += zp["a_soir"] * math.exp(-((h - zp["h_soir"]) ** 2) / (2 * SIGMA_SOIR ** 2))
        value += zp["a_nuit"] * math.exp(-((h - H_NUIT) ** 2) / (2 * SIGMA_NUIT ** 2))

        h_flag, fond_harmattan = self.seasonal.harmattan_flag_and_bonus(dt)
        if h_flag:
            value += fond_harmattan

        # Multiplicateur du profil de pollution (§6.2)
        value *= self._profile.get("pm_multiplier", 1.0)

        # Réduction brise marine pour les profils côtiers (§6.2 coastal_low)
        sea_breeze = self._profile.get("sea_breeze_reduction")
        if sea_breeze and 12 <= h <= 18:
            value *= (1.0 - sea_breeze)

        # Saisonnalité hivernage (§3.3)
        value *= self.seasonal.rain_reduction(dt)

        # Variabilité hebdomadaire (§3.2)
        value *= WEEKDAY_FACTORS[dt.weekday()]

        return max(0.0, value)

    def pm10_true(self, pm25_true: float) -> float:
        """PM10 dérivé de PM2.5 — ratio typique zones urbaines saheliennes ~1.7."""
        return pm25_true * 1.7

    def pm1_true(self, pm25_true: float) -> float:
        """PM1.0 dérivé de PM2.5 — ratio typique ~0.65."""
        return pm25_true * 0.65

    # ── NO2 (§3.4) — cycle bimodal trafic matin/soir ─────────────────────────
    def no2_true(self, dt: datetime) -> float:
        h = dt.hour + dt.minute / 60.0
        zp = self.zone_params
        value = zp["no2_base"]
        value += zp["no2_b_matin"] * math.exp(-((h - 8) ** 2) / (2 * 1.5 ** 2))
        value += zp["no2_b_soir"] * math.exp(-((h - 18) ** 2) / (2 * 2.0 ** 2))
        value *= self._profile.get("no2_multiplier", 1.0)
        shipping_factor = self._profile.get("shipping_no2_factor")
        if shipping_factor:
            value *= shipping_factor / 2.0 + 0.5  # atténue l'effet pour rester réaliste (×1.0..×factor)
        return max(0.0, value)

    # ── CO (§3.5) — base + heures de pointe ──────────────────────────────────
    def co_true(self, dt: datetime) -> float:
        h = dt.hour
        rush_morning = 1.0 if 7 <= h <= 9 else 0.0
        rush_evening = 1.0 if 17 <= h <= 19 else 0.0
        value = 0.8 + 0.6 * (rush_morning + rush_evening)
        value *= self._profile.get("co_multiplier", 1.0)
        return max(0.0, value)

    # ── NH3 — non spécifié explicitement dans le document ; modèle simple ────
    def nh3_true(self, dt: datetime) -> float:
        """Pas de cycle dédié dans SIMULATION_SPEC.md — valeur de fond stable
        proportionnelle au profil industriel/périurbain (sources agricoles/déchets)."""
        baseline = self._profile.get("industrial_baseline", 0.0)
        return 2.0 + 0.3 * baseline

    # ── O3 estimé (§2.4) — corrélation empirique, calculée côté capteur ──────
    @staticmethod
    def solar_radiation_index(dt: datetime) -> float:
        h = dt.hour + dt.minute / 60.0
        if 6 <= h <= 18:
            return math.sin(math.pi * (h - 6) / 12)
        return 0.0
