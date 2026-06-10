"""Injection contrôlée d'anomalies dans le flux de données simulé.

Référence : simulation/SIMULATION_SPEC.md §4.
Classes : AnomalyInjector, AnomalyScenario.

Deux modes (§4.2) :
  - "random"   : à chaque mesure, probabilité `p_anomaly` de déclencher une
                 anomalie d'un type tiré selon une distribution pondérée.
  - "scenario" : anomalies programmées chargées depuis un fichier YAML
                 (config/anomaly_scenarios.yaml), déclenchées à `trigger_time`.

Note d'interprétation (la spec décrit l'effet narratif de chaque type sans
donner le mécanisme exact d'application — les choix ci-dessous sont
documentés en commentaire à chaque transformation) :
  - SPIKE        : enveloppe triangulaire (montée puis décroissance), pic à
                   `factor` × valeur vraie au milieu de la fenêtre.
  - HARMATTAN    : palier soutenu à `intensity` × valeur vraie sur PM10/PM2.5.
  - STUCK        : valeurs mesurées figées à celles du premier tick de l'anomalie.
  - DROPOUT      : aucune publication MQTT pendant la fenêtre (message perdu).
  - DRIFT_RAPID  : terme additif croissant linéairement, pente ×10 de la
                   dérive nominale du capteur PM (§2.1 `drift_rate`).
  - OUTLIER      : un seul point isolé, valeur ×10 sur PM2.5 (canal le plus
                   surveillé), anomalie ponctuelle (durée = 1 tick).
  - PARTIAL_FAULT: un seul canal (`sensor: pm25|co|no2`) renvoie 0.
  - HIGH_NOISE   : bruit gaussien additionnel d'écart-type 4× le bruit nominal
                   (total ≈ ×5 conformément à la spec) sur tous les canaux.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import yaml

ANOMALY_TYPES = (
    "SPIKE", "STUCK", "DROPOUT", "DRIFT_RAPID", "OUTLIER",
    "HARMATTAN", "PARTIAL_FAULT", "HIGH_NOISE",
)

# Distribution pondérée pour le mode aléatoire (§4.2 : "distribution pondérée",
# poids non fournis dans la spec — choix documenté ici, favorise les anomalies
# bénignes/fréquentes par rapport aux pannes lourdes).
_RANDOM_TYPE_WEIGHTS = {
    "OUTLIER": 0.25,
    "HIGH_NOISE": 0.20,
    "SPIKE": 0.15,
    "STUCK": 0.12,
    "DROPOUT": 0.12,
    "DRIFT_RAPID": 0.07,
    "PARTIAL_FAULT": 0.06,
    "HARMATTAN": 0.03,
}

PM_CHANNELS = ("pm1_0", "pm2_5", "pm10")


@dataclass
class AnomalyScenario:
    name: str
    trigger_time: datetime
    type: str
    params: dict
    affected_zones: list[str] = field(default_factory=list)
    affected_sensors: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> "AnomalyScenario":
        trigger = datetime.fromisoformat(str(raw["trigger_time"]).replace("Z", "+00:00"))
        known_keys = {"name", "trigger_time", "type", "affected_zones", "affected_sensors"}
        params = {k: v for k, v in raw.items() if k not in known_keys}
        return cls(
            name=raw["name"], trigger_time=trigger, type=raw["type"], params=params,
            affected_zones=list(raw.get("affected_zones", [])),
            affected_sensors=list(raw.get("affected_sensors", [])),
        )

    def applies_to(self, sensor_id: str, zone_id: str) -> bool:
        if self.affected_sensors:
            return sensor_id in self.affected_sensors
        if self.affected_zones:
            return "all" in self.affected_zones or zone_id in self.affected_zones
        return False


def _duration(params: dict, rng: np.random.Generator) -> timedelta:
    """Calcule la durée d'une anomalie selon ses paramètres ou les bornes §4.1."""
    if "duration_minutes" in params:
        return timedelta(minutes=params["duration_minutes"])
    if "duration_hours" in params:
        return timedelta(hours=params["duration_hours"])
    return timedelta(minutes=0)


_RANDOM_DURATION_RANGES = {
    "SPIKE": ("minutes", (15, 120)),
    "STUCK": ("minutes", (30, 240)),
    "DROPOUT": ("minutes", (10, 180)),
    "DRIFT_RAPID": ("hours", (2, 24)),
    "OUTLIER": (None, None),       # ponctuel — un seul tick
    "HARMATTAN": ("hours", (6, 48)),
    "PARTIAL_FAULT": ("minutes", (30, 120)),
    "HIGH_NOISE": ("minutes", (30, 60)),
}


def _random_params_and_duration(anomaly_type: str, rng: np.random.Generator) -> tuple[dict, timedelta]:
    """Tire paramètres et durée pour le mode aléatoire selon les bornes du §4.1."""
    params: dict = {}
    if anomaly_type == "SPIKE":
        params["factor"] = float(rng.uniform(3, 8))
        params["pollutants"] = ["pm25", "pm10"]
    elif anomaly_type == "HARMATTAN":
        params["intensity"] = float(rng.uniform(3, 8))
        params["pollutants"] = ["pm10", "pm25"]
    elif anomaly_type == "PARTIAL_FAULT":
        params["sensor"] = str(rng.choice(["pm25", "co", "no2"]))
    elif anomaly_type == "OUTLIER":
        params["pollutants"] = ["pm25"]

    unit, bounds = _RANDOM_DURATION_RANGES[anomaly_type]
    if unit is None:
        return params, timedelta(seconds=0)
    low, high = bounds
    value = float(rng.uniform(low, high))
    duration = timedelta(minutes=value) if unit == "minutes" else timedelta(hours=value)
    if unit == "minutes":
        params["duration_minutes"] = round(value)
    else:
        params["duration_hours"] = round(value, 1)
    return params, duration


@dataclass
class ActiveAnomaly:
    type: str
    start: datetime
    end: datetime
    params: dict
    true_value_at_start: float
    affected_pollutants: list[str]
    frozen_measurements: dict | None = None
    peak_value: float | None = None  # injected_value_at_peak — renseigné a posteriori


class AnomalyInjector:
    """Décide, déclenche et applique les anomalies sur le flux simulé.

    `mode` : "random" (probabilité par mesure) ou "scenario" (programmé).
    `scenario_path` : requis si mode == "scenario".
    """

    def __init__(self, mode: str, p_anomaly: float = 0.02, scenario_path: str | Path | None = None,
                 seed: int | None = None):
        if mode not in ("random", "scenario"):
            raise ValueError(f"Mode d'injection inconnu : {mode!r}")
        self.mode = mode
        self.p_anomaly = p_anomaly
        self._rng = np.random.default_rng(seed)
        self._active: dict[str, ActiveAnomaly] = {}
        self._records: list[dict] = []
        # Par scénario : ensemble des capteurs déjà touchés (évite les
        # déclenchements répétés sur un même capteur sans bloquer les autres
        # capteurs concernés — important pour affected_zones=["all"], où le
        # scénario doit démarrer sur CHAQUE capteur correspondant, pas une seule fois).
        self._scenario_started_for: dict[str, set[str]] = {}

        self.scenarios: list[AnomalyScenario] = []
        if mode == "scenario":
            if scenario_path is None:
                raise ValueError("scenario_path requis en mode 'scenario'")
            with open(scenario_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            self.scenarios = [AnomalyScenario.from_dict(s) for s in raw.get("scenarios", [])]

    # ── Cycle de vie ─────────────────────────────────────────────────────────
    def tick(self, sensor_id: str, zone_id: str, now: datetime, true_pm25: float) -> ActiveAnomaly | None:
        """À appeler une fois par capteur et par mesure. Démarre/termine les
        anomalies et retourne celle actuellement active (ou None)."""
        active = self._active.get(sensor_id)
        if active is not None:
            if now >= active.end:
                self._close(sensor_id, active, now)
                active = None
            else:
                return active

        started = self._maybe_start(sensor_id, zone_id, now, true_pm25)
        return started

    def _maybe_start(self, sensor_id: str, zone_id: str, now: datetime, true_pm25: float) -> ActiveAnomaly | None:
        if self.mode == "random":
            if self._rng.random() >= self.p_anomaly:
                return None
            anomaly_type = str(self._rng.choice(
                list(_RANDOM_TYPE_WEIGHTS.keys()), p=list(_RANDOM_TYPE_WEIGHTS.values())))
            params, duration = _random_params_and_duration(anomaly_type, self._rng)
            return self._start(sensor_id, anomaly_type, now, duration, params, true_pm25)

        # Mode scénario : déclenche au plus tôt à `trigger_time`, une seule fois
        # par capteur concerné (un scénario "all" démarre sur chaque capteur).
        for scenario in self.scenarios:
            started_for = self._scenario_started_for.setdefault(scenario.name, set())
            if sensor_id in started_for:
                continue
            if now < scenario.trigger_time:
                continue
            if not scenario.applies_to(sensor_id, zone_id):
                continue
            duration = _duration(scenario.params, self._rng)
            started_for.add(sensor_id)
            return self._start(sensor_id, scenario.type, now, duration, dict(scenario.params), true_pm25)
        return None

    def _start(self, sensor_id: str, anomaly_type: str, now: datetime, duration: timedelta,
               params: dict, true_pm25: float) -> ActiveAnomaly:
        end = now + duration if duration.total_seconds() > 0 else now + timedelta(seconds=1)
        pollutants = params.get("pollutants") or ([params["sensor"]] if "sensor" in params else ["pm25"])
        anomaly = ActiveAnomaly(type=anomaly_type, start=now, end=end, params=params,
                                true_value_at_start=true_pm25, affected_pollutants=list(pollutants))
        self._active[sensor_id] = anomaly
        return anomaly

    def _close(self, sensor_id: str, anomaly: ActiveAnomaly, now: datetime) -> None:
        del self._active[sensor_id]
        self._records.append({
            "run_id": None,  # renseigné par le générateur via finalize_run_id
            "sensor_id": sensor_id,
            "anomaly_start": anomaly.start, "anomaly_end": anomaly.end,
            "anomaly_type": anomaly.type,
            "affected_pollutants": ",".join(anomaly.affected_pollutants),
            "true_value_at_start": round(anomaly.true_value_at_start, 1),
            "injected_value_at_peak": round(anomaly.peak_value, 1) if anomaly.peak_value is not None else "",
        })

    def finalize_run_id(self, run_id: str) -> None:
        for record in self._records:
            record["run_id"] = run_id

    # ── Application aux mesures ──────────────────────────────────────────────
    def apply(self, anomaly: ActiveAnomaly, now: datetime, measurements: dict) -> tuple[dict, bool]:
        """Transforme `measurements` (dict de canaux mesurés) selon l'anomalie active.

        Retourne (measurements_modifiés, suppress_publish). `suppress_publish`
        est vrai uniquement pour DROPOUT (message perdu — non publié sur MQTT,
        mais conservé dans le ground truth)."""
        progress = self._progress(anomaly, now)
        m = dict(measurements)

        if anomaly.type == "SPIKE":
            envelope = self._triangular_envelope(progress, anomaly.params["factor"])
            for ch in self._target_channels(anomaly, default=("pm2_5", "pm10")):
                m[ch] = m[ch] * envelope
            self._record_peak(anomaly, m["pm2_5"])

        elif anomaly.type == "HARMATTAN":
            intensity = anomaly.params["intensity"]
            for ch in self._target_channels(anomaly, default=("pm10", "pm2_5")):
                m[ch] = m[ch] * intensity
            self._record_peak(anomaly, m["pm2_5"])

        elif anomaly.type == "STUCK":
            if anomaly.frozen_measurements is None:
                anomaly.frozen_measurements = dict(m)
            m = dict(anomaly.frozen_measurements)
            self._record_peak(anomaly, m["pm2_5"])

        elif anomaly.type == "DRIFT_RAPID":
            hours_elapsed = (now - anomaly.start).total_seconds() / 3600.0
            extra = 10 * 0.15 * hours_elapsed / 24.0  # ≈ ×10 du taux nominal PM (§2.1 : U(0.05, 0.30)/jour)
            for ch in PM_CHANNELS:
                m[ch] = max(0.0, m[ch] + extra)
            self._record_peak(anomaly, m["pm2_5"])

        elif anomaly.type == "OUTLIER":
            for ch in self._target_channels(anomaly, default=("pm2_5",)):
                m[ch] = m[ch] * 10
            self._record_peak(anomaly, m["pm2_5"])

        elif anomaly.type == "PARTIAL_FAULT":
            channel = _channel_alias(anomaly.params.get("sensor", "pm25"))
            m[channel] = 0.0
            self._record_peak(anomaly, m.get("pm2_5", 0.0))

        elif anomaly.type == "HIGH_NOISE":
            for ch in m:
                if isinstance(m[ch], (int, float)):
                    extra_sigma = 4 * max(0.5, abs(m[ch]) * 0.1)  # ≈ +4σ → bruit total ×5 (§4.1)
                    m[ch] = max(0.0, m[ch] + float(self._rng.normal(0.0, extra_sigma)))
            self._record_peak(anomaly, m.get("pm2_5", 0.0))

        elif anomaly.type == "DROPOUT":
            self._record_peak(anomaly, m.get("pm2_5", 0.0))
            return m, True

        return m, False

    @staticmethod
    def _target_channels(anomaly: ActiveAnomaly, default: tuple[str, ...]) -> tuple[str, ...]:
        pollutants = anomaly.params.get("pollutants")
        if not pollutants:
            return default
        return tuple(_channel_alias(p) for p in pollutants)

    @staticmethod
    def _progress(anomaly: ActiveAnomaly, now: datetime) -> float:
        total = (anomaly.end - anomaly.start).total_seconds()
        if total <= 0:
            return 1.0
        return float(np.clip((now - anomaly.start).total_seconds() / total, 0.0, 1.0))

    @staticmethod
    def _triangular_envelope(progress: float, factor: float) -> float:
        """Monte de ×1 à ×factor sur la 1ʳᵉ moitié, redescend sur la 2nde (§4.1 'pic')."""
        if progress <= 0.5:
            return 1.0 + (factor - 1.0) * (progress / 0.5)
        return factor - (factor - 1.0) * ((progress - 0.5) / 0.5)

    @staticmethod
    def _record_peak(anomaly: ActiveAnomaly, current_value: float) -> None:
        if anomaly.peak_value is None or current_value > anomaly.peak_value:
            anomaly.peak_value = current_value

    # ── Persistance (§4.3) ───────────────────────────────────────────────────
    def write_log(self, path: str | Path) -> None:
        """Écrit le journal des anomalies injectées au format CSV (§4.3)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["run_id", "sensor_id", "anomaly_start", "anomaly_end", "anomaly_type",
                      "affected_pollutants", "true_value_at_start", "injected_value_at_peak"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for record in self._records:
                row = dict(record)
                row["anomaly_start"] = _iso(record["anomaly_start"])
                row["anomaly_end"] = _iso(record["anomaly_end"])
                writer.writerow(row)

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def injected_count(self) -> int:
        """Nombre total d'anomalies déclenchées (closes + en cours) — alimente
        la statistique `anomalies_injected` du résumé de run (§10.3)."""
        return len(self._records) + len(self._active)


def _channel_alias(pollutant: str) -> str:
    """Convertit les alias de polluants utilisés dans les scénarios/§4 vers les
    clés de `measurements` du payload (§5.1) — ex. 'pm25' → 'pm2_5'."""
    aliases = {"pm25": "pm2_5", "pm1": "pm1_0", "co": "co_ppm", "no2": "no2_ppb"}
    return aliases.get(pollutant, pollutant)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
