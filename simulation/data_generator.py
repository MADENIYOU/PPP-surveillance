#!/usr/bin/env python3
"""Générateur principal de données IoT simulées — Surveillance Pollution Dakar.

Référence : simulation/SIMULATION_SPEC.md §5 (payload), §6 (config), §7 (CLI).

Publie en continu, sur le broker MQTT, des mesures de qualité de l'air
simulées pour une flotte de capteurs ESP32 virtuels représentant les zones
de Dakar. Les valeurs "vraies" proviennent d'atmospheric_models.py, le bruit
et les défauts physiques de sensor_models.py. Le marqueur `"sim": true` dans
chaque payload est l'unique différence avec un capteur réel (cf. spec §0).

L'injection d'anomalies (§4) est pilotée par `AnomalyInjector` — mode aléatoire
via `--anomaly-rate` ou mode scénario via `--scenario config/anomaly_scenarios.yaml`.
Les comportements firmware avancés (buffer SPIFFS, OTA, batterie détaillée par
courant consommé en mAh) et la simulation réseau LoRa restent des modules
autonomes (firmware_v{0,1}_sim.py, lora_*_sim.py — §8, §9), démontrables
indépendamment de cette boucle de génération MQTT "nominale".
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import paho.mqtt.client as mqtt
import yaml
from pydantic import BaseModel, Field, field_validator

from anomaly_injector import AnomalyInjector
from atmospheric_models import DakarAtmosphericModel, SeasonalModel
from sensor_models import BME280Model, MICS6814Model, PMS5003Model, o3_estimated

LOGGER = logging.getLogger("data_generator")

SIM_ROOT = Path(__file__).resolve().parent
DEFAULT_SENSORS_CONFIG = SIM_ROOT / "config" / "sensors.yaml"
DEFAULT_ZONES_CONFIG = SIM_ROOT / "config" / "zones.yaml"
GROUND_TRUTH_DIR = SIM_ROOT / "ground_truth"
LOGS_DIR = SIM_ROOT / "logs"

SENSOR_ID_PATTERN = r"^ESP32-DK-[A-Z]+-\d{3}$"


# ============================================================================
# Schéma du payload MQTT — §5.1 (structure) / §5.2 (règles de validation)
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
    timestamp: str
    seq: int
    firmware: str
    measurements: Measurements
    data_quality: DataQuality
    battery: Battery
    network: Network
    position: Position
    sim: bool = True
    sim_metadata: SimMetadata

    @field_validator("seq")
    @classmethod
    def _seq_range(cls, v: int) -> int:
        if not 0 <= v < 2**31:
            raise ValueError("seq doit être un entier 32 bits positif")
        return v


# ============================================================================
# État et modèles d'un capteur simulé
# ============================================================================
class SensorRuntime:
    """Regroupe l'état mutable et les modèles physiques d'un capteur simulé."""

    def __init__(self, sensor_cfg: dict, zones_cfg: dict, seasonal: SeasonalModel,
                 firmware: str, run_start: datetime, seed_seq: np.random.SeedSequence):
        self.sensor_id: str = sensor_cfg["id"]
        self.zone_id: str = sensor_cfg["zone_id"]
        self.lat: float = sensor_cfg["lat"]
        self.lon: float = sensor_cfg["lon"]
        self.pollution_profile: str = sensor_cfg.get("pollution_profile", "urban_medium")
        self.network_type: str = sensor_cfg.get("network_type", "wifi")
        self.firmware = firmware

        battery_cfg = sensor_cfg.get("battery", {})
        self.solar_panel: bool = bool(battery_cfg.get("solar_panel", False))

        self.install_date = _parse_date(sensor_cfg.get("install_date"), default=run_start)
        self.calibration_date = _parse_date(sensor_cfg.get("calibration_date"), default=self.install_date)
        self.last_restart = run_start

        zone_params = zones_cfg["zones"][self.zone_id]
        profile_params = zones_cfg["pollution_profiles"].get(self.pollution_profile, {})
        sub_seeds = seed_seq.spawn(4)
        self.atmospheric = DakarAtmosphericModel(zone_params=zone_params, profile_params=profile_params,
                                                  seasonal=seasonal)
        self.pms = PMS5003Model(seed=sub_seeds[0], install_date=self.calibration_date)
        self.bme = BME280Model(seed=sub_seeds[1])
        self.mics = MICS6814Model(seed=sub_seeds[2], init_time=self.install_date)
        self.rng = np.random.default_rng(sub_seeds[3])

        self.seq = 0
        # Niveau de batterie initial réaliste : élevé, légèrement bruité (§5.1 exemples : 78-100%)
        self.battery_level_pct = float(self.rng.uniform(70, 100))
        self.battery_voltage_v = 3.6 + 0.4 * (self.battery_level_pct / 100.0)
        self.rssi_dbm = int(self.rng.integers(-80, -50))

    def step_battery(self, dt: datetime, dt_seconds: float) -> None:
        """Évolution simplifiée du niveau de batterie (modèle détaillé en mAh : §8.2, tâche #3).

        Décharge lente continue, compensée par une recharge solaire en journée
        si le capteur est équipé d'un panneau (§6.1 `battery.solar_panel`).
        """
        drain_pct_per_hour = 0.15
        delta = -drain_pct_per_hour * (dt_seconds / 3600.0)
        if self.solar_panel:
            sunlight = max(0.0, np.sin(np.pi * (dt.hour + dt.minute / 60.0 - 6) / 12)) if 6 <= dt.hour <= 18 else 0.0
            delta += 0.45 * sunlight * (dt_seconds / 3600.0)
        self.battery_level_pct = float(np.clip(self.battery_level_pct + delta, 0.0, 100.0))
        self.battery_voltage_v = 3.3 + 0.6 * (self.battery_level_pct / 100.0)

    @property
    def is_charging(self) -> bool:
        return self.solar_panel and self.battery_level_pct < 100.0

    def warming_up(self, now: datetime) -> bool:
        return self.mics.is_warming_up(now, self.last_restart)


def _parse_date(value, default: datetime) -> datetime:
    if value is None:
        return default
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


# ============================================================================
# Boucle principale de simulation
# ============================================================================
class SimulationRunner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.run_id = f"sim_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
        self._stop = False

        seed_seq = np.random.SeedSequence(args.seed)
        self.rng = np.random.default_rng(seed_seq)
        self.seasonal = SeasonalModel(season_override=args.season, seed=args.seed)

        sensors_cfg, zones_cfg = self._load_configs()
        run_start = datetime.now(timezone.utc)
        firmware = sensors_cfg.get("global", {}).get("default_firmware", "sim-v1.2.0")
        sub_seeds = seed_seq.spawn(len(sensors_cfg["sensors"]))
        self.sensors: list[SensorRuntime] = [
            SensorRuntime(cfg, zones_cfg, self.seasonal, firmware, run_start, sub_seed)
            for cfg, sub_seed in zip(sensors_cfg["sensors"], sub_seeds)
        ]

        self.interval = args.interval or sensors_cfg.get("global", {}).get("publish_interval_s", 30)
        self.client = self._build_mqtt_client(sensors_cfg.get("global", {}))

        self.injector: AnomalyInjector | None = self._build_injector(args)

        self._gt_path = self._resolve_ground_truth_path()
        self._gt_file = None
        self._gt_writer = None
        # Journal des anomalies au format §4.3 (colonnes distinctes du ground
        # truth principal §10.2 — la spec les décrit comme un même "fichier de
        # vérité terrain" mais documente deux schémas de colonnes différents ;
        # choix : fichier séparé `{run_id}_{date}_anomalies.csv` à côté du CSV principal).
        self._anomaly_log_path = self._gt_path.with_name(self._gt_path.stem + "_anomalies.csv")
        self._log_path = LOGS_DIR / f"generator_{datetime.now(timezone.utc):%Y%m%d}.jsonl"

        self.stats = {
            "run_id": self.run_id,
            "start_time": run_start.isoformat().replace("+00:00", "Z"),
            "end_time": None,
            "n_sensors": len(self.sensors),
            "total_messages_published": 0,
            "total_messages_buffered": 0,
            "total_messages_dropped": 0,
            "anomalies_injected": 0,
            "battery_dead_events": 0,
            "mqtt_reconnects": 0,
        }

    # ── Configuration ────────────────────────────────────────────────────────
    def _load_configs(self) -> tuple[dict, dict]:
        sensors_path = Path(self.args.config) if self.args.config else DEFAULT_SENSORS_CONFIG
        with open(sensors_path, encoding="utf-8") as f:
            sensors_cfg = yaml.safe_load(f)
        with open(DEFAULT_ZONES_CONFIG, encoding="utf-8") as f:
            zones_cfg = yaml.safe_load(f)

        all_sensors = sensors_cfg["sensors"]
        if self.args.sensor_ids:
            wanted = set(self.args.sensor_ids)
            all_sensors = [s for s in all_sensors if s["id"] in wanted]
            missing = wanted - {s["id"] for s in all_sensors}
            if missing:
                raise SystemExit(f"Capteurs introuvables dans la configuration : {sorted(missing)}")
        elif self.args.n_sensors:
            all_sensors = all_sensors[: self.args.n_sensors]
        sensors_cfg["sensors"] = all_sensors
        return sensors_cfg, zones_cfg

    def _build_injector(self, args: argparse.Namespace) -> Optional[AnomalyInjector]:
        """Construit l'injecteur d'anomalies selon les arguments CLI (§4.2).

        `--scenario` prévaut sur `--anomaly-rate` (mode scénario programmé vs
        mode aléatoire) ; aucun des deux → pas d'injection (comportement
        nominal de la tâche #2, conservé par défaut)."""
        if args.scenario:
            LOGGER.info("Injection d'anomalies : mode scénario (%s)", args.scenario)
            return AnomalyInjector(mode="scenario", scenario_path=args.scenario, seed=args.seed)
        if args.anomaly_rate and args.anomaly_rate > 0:
            LOGGER.info("Injection d'anomalies : mode aléatoire (p=%.3f)", args.anomaly_rate)
            return AnomalyInjector(mode="random", p_anomaly=args.anomaly_rate, seed=args.seed)
        return None

    def _resolve_ground_truth_path(self) -> Path:
        if self.args.ground_truth_output:
            path = Path(self.args.ground_truth_output)
        else:
            path = GROUND_TRUTH_DIR / f"{self.run_id}_{datetime.now(timezone.utc):%Y%m%d}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # ── MQTT ─────────────────────────────────────────────────────────────────
    def _build_mqtt_client(self, global_cfg: dict) -> mqtt.Client:
        broker = self.args.broker or global_cfg.get("mqtt_broker", "localhost")
        port = self.args.port or global_cfg.get("mqtt_port", 1883)
        client = mqtt.Client(client_id=f"data_generator_{self.run_id}", clean_session=True)

        if self.args.tls or global_cfg.get("tls_enabled"):
            ca_cert = self.args.ca_cert or global_cfg.get("ca_cert")
            client.tls_set(ca_certs=ca_cert)

        client.on_disconnect = self._on_mqtt_disconnect
        LOGGER.info("Connexion MQTT → %s:%s (tls=%s)", broker, port, bool(self.args.tls))
        client.connect(broker, port, keepalive=60)
        client.loop_start()

        for sensor in self.sensors:
            status_topic = f"dakar/sensors/{sensor.sensor_id}/status"
            client.will_set(status_topic, json.dumps({"status": "offline", "sim": True}), qos=1, retain=True)
            client.publish(status_topic, json.dumps({"status": "online", "sim": True,
                                                      "timestamp": _iso(datetime.now(timezone.utc))}),
                           qos=1, retain=True)
        return client

    def _on_mqtt_disconnect(self, client, userdata, rc):  # noqa: ANN001 (signature paho)
        if rc != 0:
            self.stats["mqtt_reconnects"] += 1
            LOGGER.warning("Déconnexion MQTT inattendue (rc=%s) — reconnexion automatique", rc)

    # ── Génération d'une mesure ──────────────────────────────────────────────
    def _generate_payload(self, sensor: SensorRuntime, now: datetime) -> tuple[SensorPayload, dict, bool]:
        atm = sensor.atmospheric
        true_pm25 = atm.pm25_true(now)
        true_pm10 = atm.pm10_true(true_pm25)
        true_no2 = atm.no2_true(now)
        true_co = atm.co_true(now)
        true_nh3 = atm.nh3_true(now)
        harmattan_active, _ = self.seasonal.harmattan_flag_and_bonus(now)

        true_temp, true_humidity = self.seasonal.temperature_humidity(now)
        bme_out = sensor.bme.measure(true_temp, true_humidity, true_pressure_hpa=1013.0, dt_seconds=self.interval)
        temp_c, humidity_pct = bme_out["temperature_c"], bme_out["humidity_pct"]

        pms_out = sensor.pms.measure(true_pm25, true_pm10, temp_c, humidity_pct, now,
                                     harmattan_active=harmattan_active)
        warming_up = sensor.warming_up(now)
        co_ppm = sensor.mics.measure_co(true_co, temp_c, humidity_pct, true_no2, now, warming_up=warming_up)
        no2_ppb = sensor.mics.measure_no2(true_no2, temp_c, now, warming_up=warming_up)
        nh3_ppm = sensor.mics.measure_nh3(true_nh3, warming_up=warming_up)
        solar_idx = atm.solar_radiation_index(now)
        o3_ppb = o3_estimated(true_no2, temp_c, solar_idx, sensor.rng)

        sensor.step_battery(now, self.interval)
        sensor.seq += 1

        confidence = 0.6 if warming_up else float(np.clip(0.95 - sensor.pms.calibration_age_days(now) / 400.0, 0.5, 0.99))

        # ── Injection d'anomalies (§4) — transforme les valeurs mesurées avant
        # construction du payload. `suppress_publish` n'est vrai que pour DROPOUT
        # (le message est conservé dans le ground truth mais jamais publié sur MQTT).
        measured = {
            "pm1_0": pms_out["pm1_0"], "pm2_5": pms_out["pm2_5"], "pm10": pms_out["pm10"],
            "co_ppm": co_ppm, "no2_ppb": no2_ppb, "o3_ppb_est": o3_ppb, "nh3_ppm": nh3_ppm,
            "temperature_c": temp_c, "humidity_pct": humidity_pct, "pressure_hpa": bme_out["pressure_hpa"],
        }
        anomaly_active = False
        anomaly_type: Optional[str] = None
        suppress_publish = False
        if self.injector is not None:
            active = self.injector.tick(sensor.sensor_id, sensor.zone_id, now, true_pm25)
            if active is not None:
                measured, suppress_publish = self.injector.apply(active, now, measured)
                anomaly_active = True
                anomaly_type = active.type

        measurements = Measurements(
            pm1_0=round(measured["pm1_0"], 1), pm2_5=round(measured["pm2_5"], 1), pm10=round(measured["pm10"], 1),
            co_ppm=round(measured["co_ppm"], 2), no2_ppb=round(measured["no2_ppb"], 2),
            o3_ppb_est=round(measured["o3_ppb_est"], 1), nh3_ppm=round(measured["nh3_ppm"], 2),
            temperature_c=round(measured["temperature_c"], 1), humidity_pct=round(measured["humidity_pct"], 1),
            pressure_hpa=round(measured["pressure_hpa"], 1), warm_up=warming_up,
        )
        data_quality = DataQuality(
            humidity_correction_applied=pms_out["humidity_correction_applied"],
            warming_up=warming_up,
            calibration_age_days=round(sensor.pms.calibration_age_days(now), 1),
            confidence_score=round(confidence, 2),
        )
        battery = Battery(
            voltage_v=round(sensor.battery_voltage_v, 2),
            level_pct=int(round(sensor.battery_level_pct)),
            charging=sensor.is_charging,
            solar_active=sensor.solar_panel and solar_idx > 0,
        )
        network = Network(type=sensor.network_type, rssi_dbm=sensor.rssi_dbm, reconnects=0, buffer_pending=0)
        position = Position(lat=sensor.lat, lon=sensor.lon, source="config")
        sim_metadata = SimMetadata(run_id=self.run_id, true_pm25=round(true_pm25, 1),
                                   anomaly_active=anomaly_active, anomaly_type=anomaly_type)

        payload = SensorPayload(
            sensor_id=sensor.sensor_id, timestamp=_iso(now), seq=sensor.seq, firmware=sensor.firmware,
            measurements=measurements, data_quality=data_quality, battery=battery, network=network,
            position=position, sim=True, sim_metadata=sim_metadata,
        )
        ground_truth_row = {
            "run_id": self.run_id, "timestamp": _iso(now), "sensor_id": sensor.sensor_id,
            "true_pm25": round(true_pm25, 1), "true_pm10": round(true_pm10, 1),
            "true_co": round(true_co, 2), "true_no2": round(true_no2, 1),
            "true_temp": round(temp_c, 1), "true_humidity": round(humidity_pct, 1),
            "anomaly_active": "true" if anomaly_active else "false",
            "anomaly_type": anomaly_type or "",
        }
        return payload, ground_truth_row, suppress_publish

    # ── Boucle d'exécution ───────────────────────────────────────────────────
    def run(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        self._gt_file = open(self._gt_path, "w", newline="", encoding="utf-8")
        self._gt_writer = csv.DictWriter(self._gt_file, fieldnames=[
            "run_id", "timestamp", "sensor_id", "true_pm25", "true_pm10", "true_co",
            "true_no2", "true_temp", "true_humidity", "anomaly_active", "anomaly_type"])
        self._gt_writer.writeheader()
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = open(self._log_path, "a", encoding="utf-8")

        LOGGER.info("Démarrage simulation run_id=%s — %d capteur(s), interval=%ss, durée=%ss",
                    self.run_id, len(self.sensors), self.interval, self.args.duration)

        start = time.monotonic()
        next_tick = start
        try:
            while not self._stop:
                elapsed = time.monotonic() - start
                if self.args.duration and elapsed >= self.args.duration:
                    break

                now = datetime.now(timezone.utc)
                snapshot = []
                for sensor in self.sensors:
                    t0 = time.monotonic()
                    payload, gt_row, suppress_publish = self._generate_payload(sensor, now)
                    topic = f"dakar/sensors/{sensor.sensor_id}/data"
                    body = payload.model_dump_json()

                    published = not suppress_publish
                    if published:
                        self.client.publish(topic, body, qos=1)
                        self.stats["total_messages_published"] += 1
                    else:
                        # DROPOUT (§4.1) : message perdu — non publié, conservé au ground truth
                        self.stats["total_messages_dropped"] += 1
                    latency_ms = round((time.monotonic() - t0) * 1000, 1)

                    self._gt_writer.writerow(gt_row)
                    log_file.write(json.dumps({
                        "timestamp": _iso(now), "sensor_id": sensor.sensor_id, "seq": sensor.seq,
                        "published": published, "latency_ms": latency_ms, "buffer_size": 0}) + "\n")

                    snapshot.append((sensor, payload))

                if self.injector is not None:
                    self.stats["anomalies_injected"] = self.injector.injected_count

                self._gt_file.flush()
                log_file.flush()

                if not self.args.headless:
                    self._print_console(now, snapshot)

                next_tick += self.interval
                sleep_for = max(0.0, next_tick - time.monotonic())
                time.sleep(sleep_for)
        finally:
            self._shutdown(log_file)

    def _handle_signal(self, signum, frame):  # noqa: ANN001
        LOGGER.info("Signal %s reçu — arrêt propre en cours...", signum)
        self._stop = True

    def _shutdown(self, log_file) -> None:
        self.stats["end_time"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        if self.injector is not None:
            self.injector.finalize_run_id(self.run_id)
            self.injector.write_log(self._anomaly_log_path)
            self.stats["anomalies_injected"] = self.injector.injected_count

        stats_path = LOGS_DIR / f"stats_{self.run_id}.json"
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, ensure_ascii=False, indent=2)

        for sensor in self.sensors:
            status_topic = f"dakar/sensors/{sensor.sensor_id}/status"
            self.client.publish(status_topic, json.dumps({"status": "offline", "sim": True}), qos=1, retain=True)

        if self._gt_file:
            self._gt_file.close()
        log_file.close()
        self.client.loop_stop()
        self.client.disconnect()
        LOGGER.info("Simulation terminée — run_id=%s | messages=%d | ground_truth=%s | stats=%s",
                    self.run_id, self.stats["total_messages_published"], self._gt_path, stats_path)

    # ── Affichage console (§7.3) ─────────────────────────────────────────────
    def _print_console(self, now: datetime, snapshot: list[tuple[SensorRuntime, SensorPayload]]) -> None:
        season = self.seasonal.season_for(now)
        header = (f"[{now:%H:%M:%S}] SIM {len(self.sensors)} capteurs | ▶ RUNNING "
                  f"| Saison: {season} | Seed: {self.args.seed}")
        sep = "─" * 64
        lines = [header, sep, f"{'Capteur':<22}{'Zone':<14}{'PM2.5':>6} {'PM10':>6} {'CO':>5}  {'Bat%':>5}  Status"]
        for sensor, payload in snapshot:
            m = payload.measurements
            if payload.sim_metadata.anomaly_active:
                status = f"⚠ {payload.sim_metadata.anomaly_type}"
            elif m.warm_up:
                status = "⏳ warm-up"
            else:
                status = "✓ OK"
            lines.append(f"{sensor.sensor_id:<22}{sensor.zone_id:<14}{m.pm2_5:>6.1f} {m.pm10:>6.1f} "
                         f"{m.co_ppm:>5.1f}  {payload.battery.level_pct:>4d}%  {status}")
        lines.append(sep)
        msgs_per_min = round(len(self.sensors) * 60 / self.interval) if self.interval else 0
        anomalies_active = self.injector.active_count if self.injector is not None else 0
        lines.append(f"Messages/min: {msgs_per_min}/{msgs_per_min} | "
                     f"Anomalies actives: {anomalies_active} | Buffer total: 0")
        sys.stdout.write("\n".join(lines) + "\n\n")
        sys.stdout.flush()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ============================================================================
# CLI
# ============================================================================
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Génère et publie des données IoT de qualité de l'air simulées sur MQTT.")
    parser.add_argument("--config", help="Chemin vers config/sensors.yaml (défaut : config/sensors.yaml)")
    parser.add_argument("--broker", help="Hôte du broker MQTT (défaut : valeur de sensors.yaml)")
    parser.add_argument("--port", type=int, help="Port du broker MQTT (défaut : valeur de sensors.yaml)")
    parser.add_argument("--tls", action="store_true", help="Active la connexion TLS")
    parser.add_argument("--ca-cert", help="Chemin vers le certificat CA (si --tls)")
    parser.add_argument("--n-sensors", type=int, help="Nombre de capteurs à simuler (sous-ensemble de la config)")
    parser.add_argument("--sensor-ids", nargs="+", help="Identifiants explicites des capteurs à simuler")
    parser.add_argument("--interval", type=float, help="Intervalle de publication en secondes")
    parser.add_argument("--duration", type=float, default=3600,
                        help="Durée totale de la simulation en secondes (défaut : 3600)")
    parser.add_argument("--season", choices=("dry", "rain", "harmattan"),
                        help="Force une saison plutôt que de la déduire de la date courante")
    parser.add_argument("--anomaly-rate", type=float, default=0.0,
                        help="Active le mode aléatoire d'injection d'anomalies (§4.2) avec cette "
                             "probabilité par mesure (0 = désactivé ; valeur documentée par défaut "
                             "dans la spec : 0.02). Ignoré si --scenario est fourni.")
    parser.add_argument("--scenario",
                        help="Active le mode scénario d'injection d'anomalies : chemin vers un "
                             "fichier YAML de scénarios programmés (cf. config/anomaly_scenarios.yaml, §4.2)")
    parser.add_argument("--seed", type=int, default=None, help="Graine pour la reproductibilité")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING"), default="INFO")
    parser.add_argument("--ground-truth-output", help="Chemin du CSV de vérité terrain en sortie")
    parser.add_argument("--headless", action="store_true", help="Désactive l'affichage console temps réel")
    parser.add_argument("--stats-interval", type=float, default=60,
                        help="Intervalle (s) entre rafraîchissements de statistiques (mode interactif)")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Console Windows (cp1252) : l'affichage §7.3 utilise des symboles Unicode (▶ ─ ✓ ⏳).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")

    runner = SimulationRunner(args)
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
