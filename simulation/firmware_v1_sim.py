"""Simulation du firmware V1 — comportement avancé (buffer, batterie, OTA).

Référence : simulation/SIMULATION_SPEC.md §8.2.
Classes : FirmwareV1Simulator, SPIFFSBuffer, BatteryModel.

Reproduit le cycle de veille documenté : mesure → tentative de connexion WiFi
→ vidage du buffer SPIFFS en priorité puis publication, ou mise en buffer si
hors-ligne → mise à jour batterie (mAh, recharge solaire) → veille. Une
vérification OTA simulée est exécutée toutes les 24 h.

Comme `firmware_v0_sim.py`, ce module est indépendant de `data_generator.py` :
les capteurs et le client MQTT sont injectés via callbacks.
"""
from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

CYCLE_INTERVAL_S = 15 * 60   # 15 minutes (§8.2)
MEASURE_TIME_S = 5           # 5 secondes de mesure
WIFI_TIMEOUT_S = 30          # 30 secondes max pour connexion WiFi
OTA_CHECK_INTERVAL_S = 24 * 3600
OTA_DOWNLOAD_S = 5
OTA_ENDPOINT = "http://ota.dakar-sim.local/firmware/latest"

ACTIVE_CURRENT_MA = 240.0    # ESP32 WiFi actif
SLEEP_CURRENT_MA = 0.01      # Deep sleep
SOLAR_CURRENT_MA = 200.0     # Panneau 5W @ 3.7V typique


# ============================================================================
# SPIFFSBuffer — file persistante de messages non publiés (FIFO)
# ============================================================================
@dataclass
class SPIFFSBuffer:
    """File FIFO bornée simulant la mémoire flash SPIFFS de l'ESP32.

    `max_size` : capacité maximale (messages les plus anciens écrasés au-delà,
    comportement typique d'un buffer circulaire embarqué — non spécifié
    explicitement par la spec, choix documenté ici)."""
    max_size: int = 200
    _queue: deque[str] = field(default_factory=deque, init=False, repr=False)
    dropped: int = field(default=0, init=False)

    def push(self, payload_json: str) -> None:
        if len(self._queue) >= self.max_size:
            self._queue.popleft()
            self.dropped += 1
        self._queue.append(payload_json)

    def flush(self, publish_fn: Callable[[str], bool], topic: str) -> int:
        """Republie les messages en attente, du plus ancien au plus récent
        (priorité aux anciens messages, §8.2). S'arrête au premier échec pour
        préserver l'ordre — les messages restants demeurent bufferisés."""
        flushed = 0
        while self._queue:
            payload_json = self._queue[0]
            if not publish_fn(topic, payload_json):
                break
            self._queue.popleft()
            flushed += 1
        return flushed

    def __len__(self) -> int:
        return len(self._queue)


# ============================================================================
# BatteryModel — suivi mAh avec recharge solaire (§8.2)
# ============================================================================
@dataclass
class BatteryModel:
    """Suivi de la charge restante en mAh, avec décharge selon le mode actif/
    veille et recharge solaire optionnelle (formules verbatim §8.2)."""
    capacity_mah: float = 2000.0
    remaining_mah: float = field(default=2000.0)
    solar_panel: bool = False
    dead_event_fired: bool = field(default=False, init=False)

    @staticmethod
    def sunlight_fraction(hour_decimal: float) -> float:
        """sunlight_fraction = max(0, sin(π×(h-6)/12)) pour h ∈ [6,18] (§8.2)."""
        if not (6 <= hour_decimal <= 18):
            return 0.0
        return max(0.0, math.sin(math.pi * (hour_decimal - 6) / 12))

    def update(self, active_mode: bool, duration_s: float, hour_decimal: float) -> bool:
        """Applique décharge + recharge solaire pour `duration_s` secondes.

        Retourne True la première fois que la batterie atteint 0 (déclenche
        l'événement `battery_dead_events` du §10.3)."""
        current_ma = ACTIVE_CURRENT_MA if active_mode else SLEEP_CURRENT_MA
        self.remaining_mah -= current_ma * duration_s / 3600.0

        if self.solar_panel:
            fraction = self.sunlight_fraction(hour_decimal)
            self.remaining_mah += SOLAR_CURRENT_MA * fraction * duration_s / 3600.0

        self.remaining_mah = max(0.0, min(self.capacity_mah, self.remaining_mah))

        just_died = self.remaining_mah <= 0.0 and not self.dead_event_fired
        if just_died:
            self.dead_event_fired = True
        return just_died

    @property
    def percent(self) -> float:
        return round(100.0 * self.remaining_mah / self.capacity_mah, 1)


# ============================================================================
# FirmwareV1Simulator — boucle de veille avancée
# ============================================================================
@dataclass
class FirmwareV1Simulator:
    """Boucle firmware V1 (§8.2) : mesure, connexion WiFi probabiliste, vidage
    du buffer SPIFFS puis publication (ou mise en buffer si hors-ligne), suivi
    batterie mAh et vérification OTA périodique.

    `sensor_id`        : identifiant du capteur simulé.
    `read_fn`          : () -> dict — retourne les mesures courantes.
    `publish_fn`       : (topic, payload_json) -> bool — publie, indique le succès.
    `wifi_connect_fn`  : (timeout_s) -> bool — tente la connexion WiFi (par défaut
                         tirage aléatoire selon `outage_prob`).
    `ota_check_fn`     : () -> str | None — interroge l'endpoint OTA, retourne la
                         version disponible si > version courante, sinon None.
    `clock_fn`         : horloge injectable — par défaut `datetime.now`.
    `sleep_fn`         : sommeil injectable — par défaut `time.sleep`.
    """
    sensor_id: str
    read_fn: Callable[[], dict]
    publish_fn: Callable[[str, str], bool]
    topic: str | None = None
    outage_prob: float = 0.05
    solar_panel: bool = False
    firmware_version: str = "v1.0.0"
    wifi_connect_fn: Callable[[float], bool] | None = None
    ota_check_fn: Callable[[], str | None] | None = None
    clock_fn: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    sleep_fn: Callable[[float], None] = field(default=time.sleep)
    rng_seed: int | None = None
    cycle_interval_s: float = CYCLE_INTERVAL_S
    sleep_cap_s: float = CYCLE_INTERVAL_S  # plafond du sommeil réel (accélération en démo/tests)

    seq: int = field(default=0, init=False)
    messages_published: int = field(default=0, init=False)
    messages_buffered: int = field(default=0, init=False)
    mqtt_reconnects: int = field(default=0, init=False)
    battery_dead_events: int = field(default=0, init=False)
    _was_connected: bool = field(default=True, init=False)
    _last_ota_check: datetime | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.topic is None:
            self.topic = f"dakar/sensors/{self.sensor_id}/data"
        import numpy as np
        self._rng = np.random.default_rng(self.rng_seed)
        if self.wifi_connect_fn is None:
            self.wifi_connect_fn = self._default_wifi_connect
        if self.ota_check_fn is None:
            self.ota_check_fn = lambda: None
        self.buffer = SPIFFSBuffer()
        self.battery = BatteryModel(solar_panel=self.solar_panel)

    def _default_wifi_connect(self, timeout_s: float) -> bool:
        return bool(self._rng.random() >= self.outage_prob)

    def build_payload(self, measurements: dict, now: datetime, buffer_size: int) -> dict:
        self.seq += 1
        return {
            "sensor_id": self.sensor_id,
            "timestamp": _iso(now),
            "seq": self.seq,
            "measurements": measurements,
            "firmware_version": self.firmware_version,
            "data_quality": {"buffer_size": buffer_size},
        }

    def _maybe_check_ota(self, now: datetime) -> dict | None:
        """Vérifie l'OTA toutes les 24h (§8.2). Retourne un enregistrement de
        log si une mise à jour a été appliquée, sinon None."""
        if self._last_ota_check is not None and (now - self._last_ota_check).total_seconds() < OTA_CHECK_INTERVAL_S:
            return None
        self._last_ota_check = now

        available = self.ota_check_fn()
        if available is None or available <= self.firmware_version:
            return None

        self.sleep_fn(OTA_DOWNLOAD_S)
        old_version = self.firmware_version
        self.firmware_version = available
        self.mqtt_reconnects += 1  # reconnect() après reboot OTA (§8.2)
        return {
            "timestamp": _iso(now), "sensor_id": self.sensor_id,
            "event": "OTA", "from_version": old_version, "to_version": available,
        }

    def run_once(self) -> dict:
        """Exécute un cycle complet de veille (§8.2). Retourne un enregistrement
        de log au format §10.1 enrichi de l'état batterie/buffer."""
        cycle_start_t = time.perf_counter()
        now = self.clock_fn()
        hour_decimal = now.hour + now.minute / 60.0

        ota_log = self._maybe_check_ota(now)

        measurements = self.read_fn()
        wifi_ok = self.wifi_connect_fn(WIFI_TIMEOUT_S)

        if wifi_ok:
            if not self._was_connected:
                self.mqtt_reconnects += 1
            self._was_connected = True

            flushed = self.buffer.flush(self.publish_fn, self.topic)
            payload = self.build_payload(measurements, now, buffer_size=len(self.buffer))
            published = self.publish_fn(self.topic, json.dumps(payload))
            if published:
                self.messages_published += 1
            else:
                self.buffer.push(json.dumps(payload))
                self.messages_buffered += 1

            self.battery.update(active_mode=True, duration_s=MEASURE_TIME_S, hour_decimal=hour_decimal)
            latency_ms = round((time.perf_counter() - cycle_start_t) * 1000, 1)
        else:
            self._was_connected = False
            payload = self.build_payload(measurements, now, buffer_size=len(self.buffer) + 1)
            self.buffer.push(json.dumps(payload))
            self.messages_buffered += 1
            flushed = 0
            published = False

            self.battery.update(active_mode=True, duration_s=MEASURE_TIME_S + WIFI_TIMEOUT_S,
                                hour_decimal=hour_decimal)
            latency_ms = round((time.perf_counter() - cycle_start_t) * 1000, 1)

        record = {
            "timestamp": _iso(now), "sensor_id": self.sensor_id, "seq": self.seq,
            "published": published, "latency_ms": latency_ms, "buffer_size": len(self.buffer),
            "flushed": flushed, "battery_pct": self.battery.percent,
        }
        if ota_log is not None:
            record["ota"] = ota_log
        return record

    def run(self, n_cycles: int | None = None, on_log: Callable[[dict], None] | None = None) -> None:
        """Boucle principale (§8.2) : mesure/connexion/publication déjà gérées
        par `run_once`, puis phase de veille avec mise à jour batterie en mode
        passif et `sleep`. `n_cycles=None` → boucle infinie."""
        cycles_done = 0
        while n_cycles is None or cycles_done < n_cycles:
            now = self.clock_fn()
            hour_decimal = now.hour + now.minute / 60.0

            log_record = self.run_once()
            if on_log is not None:
                on_log(log_record)
            if self.battery.dead_event_fired:
                self.battery_dead_events = 1

            active_duration_s = MEASURE_TIME_S if log_record["published"] else MEASURE_TIME_S + WIFI_TIMEOUT_S
            sleep_duration = max(0.0, self.cycle_interval_s - active_duration_s)
            self.battery.update(active_mode=False, duration_s=sleep_duration, hour_decimal=hour_decimal)
            self.sleep_fn(min(sleep_duration, self.sleep_cap_s))

            cycles_done += 1


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Démo : horloge accélérée (1 cycle = 15 min simulées en quelques ms réelles),
    # WiFi en panne 1 cycle sur 3, panneau solaire actif.
    state = {"now": datetime(2026, 6, 5, 7, 0, tzinfo=timezone.utc), "tick": 0}

    def fast_clock() -> datetime:
        return state["now"]

    def fast_sleep(_seconds: float) -> None:
        state["tick"] += 1
        state["now"] = state["now"] + timedelta(seconds=CYCLE_INTERVAL_S)
        time.sleep(0.05)

    def fake_read() -> dict:
        return {"pm2_5": 14.2, "pm10": 24.5, "temperature_c": 29.1, "humidity_pct": 58.0}

    published_log: list[str] = []

    def fake_publish(topic: str, payload_json: str) -> bool:
        # En panne au tick 1 sur 3 (simule une coupure réseau)
        if state["tick"] % 3 == 1:
            return False
        published_log.append(payload_json)
        return True

    sim = FirmwareV1Simulator(
        sensor_id="ESP32-DK-DEMO-001",
        read_fn=fake_read,
        publish_fn=fake_publish,
        outage_prob=0.0,  # on contrôle la panne via fake_publish pour la démo
        solar_panel=True,
        clock_fn=fast_clock,
        sleep_fn=fast_sleep,
        rng_seed=7,
        sleep_cap_s=0.05,  # n'attend pas réellement 15 min en démo
    )

    def on_log(rec: dict) -> None:
        print(f"  seq={rec['seq']:>2} t={rec['timestamp']} publish={rec['published']!s:<5} "
              f"buffer={rec['buffer_size']:>2} flushed={rec['flushed']} batt={rec['battery_pct']}%")

    print("Cycles firmware V1 (horloge accélérée) :")
    sim.run(n_cycles=9, on_log=on_log)
    print(f"\npubliés={sim.messages_published}  bufferisés={sim.messages_buffered}  "
          f"reconnects={sim.mqtt_reconnects}  perdus_définitivement={sim.buffer.dropped}  "
          f"batterie_morte={sim.battery_dead_events}")
