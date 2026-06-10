"""Simulation du réseau LoRa de secours (capteurs hors couverture WiFi/MQTT).

Référence : simulation/SIMULATION_SPEC.md §9.
Classe : LoRaNetworkSimulator.

Génère des paquets LoRa au format §9.3 à partir des positions des capteurs et
d'une gateway, en utilisant le modèle de propagation Okumura-Hata de
`lora_propagation_sim`. Le payload réel envoyé sur LoRa est une trame binaire
compacte (chiffrée AES-128 dans la réalité — ici un placeholder hex), et non
le JSON MQTT complet : on retient une taille de ~20 octets, qui reproduit le
`time_on_air_ms` ≈ 370 ms documenté dans l'exemple §9.3 pour SF10.
"""
from __future__ import annotations

import math
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from lora_propagation_sim import is_decodable, rssi_dbm, snr_db, time_on_air_ms

LORA_PAYLOAD_BYTES = 20  # trame binaire compacte chiffrée (cf. docstring)
DEFAULT_GATEWAY_ID = "GW-ESP-DAKAR-001"
DEFAULT_GATEWAY_LAT = 14.6934
DEFAULT_GATEWAY_LON = -17.4678
DEFAULT_GATEWAY_HEIGHT_M = 40  # toit ESP Dakar (§9.2)
EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass
class LoRaNode:
    node_id: str
    lat: float
    lon: float
    sf: int = 10  # SF10 recommandé (§9.2) — bon compromis portée/temps d'antenne
    seq: int = 0


@dataclass
class LoRaNetworkSimulator:
    """Simule un ensemble de nœuds LoRa transmettant à une gateway fixe.

    `nodes` : liste de LoRaNode (id, position, spreading factor).
    `gateway_*` : position et identité de la gateway (défauts §9.3 — toit ESP Dakar).
    """
    nodes: list[LoRaNode]
    gateway_id: str = DEFAULT_GATEWAY_ID
    gateway_lat: float = DEFAULT_GATEWAY_LAT
    gateway_lon: float = DEFAULT_GATEWAY_LON
    gateway_height_m: float = DEFAULT_GATEWAY_HEIGHT_M
    seed: int | None = None
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)

    def distance_to_gateway_km(self, node: LoRaNode) -> float:
        return _haversine_km(node.lat, node.lon, self.gateway_lat, self.gateway_lon)

    def transmit(self, node: LoRaNode, now: datetime | None = None) -> dict | None:
        """Simule l'émission d'un paquet par `node`. Retourne le paquet reçu
        au format §9.3, ou None si le signal n'est pas décodable (paquet perdu
        — hors de portée pour le SF configuré)."""
        now = now or datetime.now(timezone.utc)
        node.seq += 1

        distance_km = self.distance_to_gateway_km(node)
        rssi = rssi_dbm(distance_km, h_bs=self.gateway_height_m) + float(self._rng.normal(0.0, 2.0))
        decodable = is_decodable(rssi, node.sf)
        if not decodable:
            return None

        return {
            "node_id": node.node_id,
            "seq": node.seq,
            "sf": node.sf,
            "rssi_dbm": round(rssi, 0),
            "snr_db": snr_db(rssi, node.sf, rng=self._rng),
            "time_on_air_ms": time_on_air_ms(LORA_PAYLOAD_BYTES, node.sf),
            "payload_hex": secrets.token_hex(LORA_PAYLOAD_BYTES),
            "gateway_id": self.gateway_id,
            "gateway_lat": self.gateway_lat,
            "gateway_lon": self.gateway_lon,
            "received_at": _iso(now),
        }

    def transmit_all(self, now: datetime | None = None) -> list[dict]:
        """Émet un paquet pour chaque nœud, ne retourne que les paquets reçus
        avec succès (ceux hors de portée sont silencieusement perdus, comme
        en LoRa réel — pas d'accusé de réception au niveau radio)."""
        received = []
        for node in self.nodes:
            packet = self.transmit(node, now=now)
            if packet is not None:
                received.append(packet)
        return received

    def coverage_summary(self) -> dict:
        """Résumé de couverture courant (distance, RSSI, décodabilité par nœud)."""
        summary = {}
        for node in self.nodes:
            distance = self.distance_to_gateway_km(node)
            rssi = rssi_dbm(distance, h_bs=self.gateway_height_m)
            summary[node.node_id] = {
                "distance_km": round(distance, 2),
                "sf": node.sf,
                "rssi_dbm": round(rssi, 1),
                "decodable": is_decodable(rssi, node.sf),
            }
        return summary


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


if __name__ == "__main__":
    # Démo : 4 nœuds LoRa à différentes distances de la gateway ESP Dakar,
    # un cycle de transmission montrant paquets reçus / perdus selon le SF.
    demo_nodes = [
        LoRaNode("ESP32-DK-LORA-001", 14.6700, -17.4400, sf=10),   # ~3 km
        LoRaNode("ESP32-DK-LORA-002", 14.7644, -17.3900, sf=10),   # ~10 km
        LoRaNode("ESP32-DK-LORA-003", 14.7167, -17.4677, sf=12),   # ~3 km, SF12
        LoRaNode("ESP32-DK-LORA-004", 14.9000, -17.1000, sf=12),   # ~30 km, hors portée
    ]
    sim = LoRaNetworkSimulator(nodes=demo_nodes, seed=42)

    print("Couverture :")
    for node_id, info in sim.coverage_summary().items():
        print(f"  {node_id}: {info['distance_km']} km, SF{info['sf']}, "
              f"RSSI={info['rssi_dbm']} dBm, décodable={info['decodable']}")

    print("\nCycle de transmission :")
    for packet in sim.transmit_all():
        print(f"  reçu de {packet['node_id']} (seq={packet['seq']}, SF{packet['sf']}, "
              f"RSSI={packet['rssi_dbm']} dBm, SNR={packet['snr_db']} dB, "
              f"ToA={packet['time_on_air_ms']} ms)")
    n_lost = len(demo_nodes) - len(sim.transmit_all())
    print(f"\n{n_lost} paquet(s) perdu(s) (hors de portée pour le SF configuré)")
