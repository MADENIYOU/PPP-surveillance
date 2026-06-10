"""Simulation du firmware V0 — comportement embarqué minimal.

Référence : simulation/SIMULATION_SPEC.md §8.1.
Classe : FirmwareV0Simulator.

Reproduit la boucle la plus simple possible (pas de buffer, pas de TLS, pas
de gestion batterie, pas d'OTA) : lire les capteurs, construire le payload,
publier en QoS 1, dormir jusqu'au prochain cycle. Si la publication échoue
(MQTT déconnecté), le message est définitivement perdu — c'est la limite
documentée de cette version de firmware.

Ce module est indépendant de `data_generator.py` : `read_fn` et `publish_fn`
sont injectés par l'appelant (callbacks), ce qui permet de le brancher sur de
vrais modèles de capteurs/MQTT ou sur des doublures de test.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

INTERVAL_SECONDS = 30  # cycle de mesure/publication (§8.1)


@dataclass
class FirmwareV0Simulator:
    """Boucle firmware V0 : `mesures → payload → publish`, sans résilience.

    `sensor_id`     : identifiant du capteur simulé.
    `read_fn`       : () -> dict — retourne les mesures courantes.
    `publish_fn`    : (topic, payload_json) -> bool — publie et indique le succès.
    `topic`         : topic MQTT cible (par défaut `dakar/sensors/{sensor_id}/data`).
    `interval_s`    : période du cycle (30 s par défaut, §8.1).
    `clock_fn`      : horloge injectable (tests) — par défaut `datetime.now`.
    `sleep_fn`      : fonction de sommeil injectable (tests) — par défaut `time.sleep`.
    """
    sensor_id: str
    read_fn: Callable[[], dict]
    publish_fn: Callable[[str, str], bool]
    topic: str | None = None
    interval_s: float = INTERVAL_SECONDS
    clock_fn: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    sleep_fn: Callable[[float], None] = field(default=time.sleep)

    seq: int = field(default=0, init=False)
    messages_published: int = field(default=0, init=False)
    messages_lost: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.topic is None:
            self.topic = f"dakar/sensors/{self.sensor_id}/data"

    def build_payload(self, measurements: dict, now: datetime) -> dict:
        self.seq += 1
        return {
            "sensor_id": self.sensor_id,
            "timestamp": _iso(now),
            "seq": self.seq,
            "measurements": measurements,
            "firmware_version": "v0",
        }

    def run_once(self) -> dict:
        """Exécute un cycle complet : lecture, construction, publication.

        Retourne un enregistrement de log au format §10.1 (`published`,
        `latency_ms`, `buffer_size` — toujours 0 ici, V0 n'a pas de buffer)."""
        cycle_start = self.clock_fn()
        measurements = self.read_fn()
        payload = self.build_payload(measurements, cycle_start)

        t0 = time.perf_counter()
        published = self.publish_fn(self.topic, json.dumps(payload))
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        if published:
            self.messages_published += 1
        else:
            # Pas de buffer en V0 : message perdu définitivement (§8.1)
            self.messages_lost += 1

        return {
            "timestamp": _iso(cycle_start),
            "sensor_id": self.sensor_id,
            "seq": self.seq,
            "published": published,
            "latency_ms": latency_ms,
            "buffer_size": 0,
        }

    def run(self, n_cycles: int | None = None, on_log: Callable[[dict], None] | None = None) -> None:
        """Boucle principale (§8.1). `n_cycles=None` → boucle infinie."""
        cycles_done = 0
        while n_cycles is None or cycles_done < n_cycles:
            cycle_start = time.perf_counter()
            log_record = self.run_once()
            if on_log is not None:
                on_log(log_record)

            elapsed = time.perf_counter() - cycle_start
            self.sleep_fn(max(0.0, self.interval_s - elapsed))
            cycles_done += 1


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


if __name__ == "__main__":
    # Démo : 5 cycles accélérés (interval réduit), MQTT factice qui échoue 1 fois sur 3.
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import itertools

    counter = itertools.count()

    def fake_read() -> dict:
        return {"pm2_5": 12.3, "pm10": 21.0, "temperature_c": 28.4, "humidity_pct": 65.0}

    def flaky_publish(topic: str, payload_json: str) -> bool:
        return next(counter) % 3 != 0  # échoue 1 fois sur 3 (MQTT KO)

    sim = FirmwareV0Simulator(
        sensor_id="ESP32-DK-DEMO-000",
        read_fn=fake_read,
        publish_fn=flaky_publish,
        interval_s=0.2,
        sleep_fn=lambda s: time.sleep(min(s, 0.2)),
    )
    sim.run(n_cycles=6, on_log=lambda rec: print(rec))
    print(f"\npubliés={sim.messages_published}  perdus={sim.messages_lost} "
          f"(V0 : aucun buffer → perte définitive en cas d'échec MQTT)")
