"""Simulation du réseau LoRa de secours (capteurs hors couverture WiFi/MQTT).

Référence : simulation/SIMULATION_SPEC.md §9.
Classe : LoRaNetworkSimulator.

Génère des paquets LoRa au format §9.3 à partir des positions des capteurs et
d'une gateway, en utilisant le modèle de propagation Okumura-Hata de
`lora_propagation_sim`. Le payload envoyé sur LoRa est une trame binaire
compacte de 20 octets (struct little-endian, mesures quantifiées) chiffrée
AES-128-CTR à la manière LoRaWAN (bloc compteur A_i dérivé de DevAddr + FCnt,
clé de session par nœud dérivée d'une clé réseau) — et non le JSON MQTT
complet. La taille de 20 octets reproduit le `time_on_air_ms` ≈ 370 ms
documenté dans l'exemple §9.3 pour SF10.
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from lora_propagation_sim import is_decodable, rssi_dbm, snr_db, time_on_air_ms

LORA_PAYLOAD_BYTES = 20  # trame binaire compacte chiffrée (cf. docstring)
# Clé réseau racine — secret via env (jamais hardcodé en prod, cf. PKI_SPEC.md).
# La valeur par défaut n'existe que pour la simulation hors infra.
LORA_NETWORK_KEY = os.environ.get("LORA_NETWORK_KEY", "sim-dev-only-network-key")
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


# ============================================================================
# Trame binaire + chiffrement AES-128-CTR (style LoRaWAN)
# ============================================================================
_FRAME_FMT = "<IHHHhHHHBB"  # 20 octets — voir build_frame
assert struct.calcsize(_FRAME_FMT) == LORA_PAYLOAD_BYTES


def derive_session_key(node_id: str) -> bytes:
    """Clé de session AES-128 par nœud (AppSKey simulée) : dérivée de la clé
    réseau + identifiant du nœud (SHA-256 tronqué à 16 octets). En production
    réelle, la clé viendrait du join LoRaWAN (OTAA) / de Vault."""
    return hashlib.sha256(f"{LORA_NETWORK_KEY}:{node_id}".encode()).digest()[:16]


def _dev_addr(node_id: str) -> int:
    """DevAddr 32 bits stable dérivé de l'identifiant du nœud."""
    return int.from_bytes(hashlib.sha256(node_id.encode()).digest()[:4], "little")


def _ctr_nonce(dev_addr: int, seq: int) -> bytes:
    """Bloc compteur initial (16 octets) façon LoRaWAN A_i :
    0x01 | 4×0x00 | dir=0 (uplink) | DevAddr (4o) | FCnt (4o) | 0x00 | i=1."""
    return struct.pack("<B4sBIIBB", 0x01, b"\x00" * 4, 0x00, dev_addr, seq & 0xFFFFFFFF, 0x00, 0x01)


def build_frame(dev_addr: int, seq: int, measurements: dict | None = None) -> bytes:
    """Trame uplink 20 octets : DevAddr(4) FCnt(2) pm25×10(2) pm10×10(2)
    temp×10(2, signé) hum×10(2) press-900hPa×10(2) no2_ppb(2) batt%(1) flags(1)."""
    m = measurements or {}
    clamp = lambda v, lo, hi: max(lo, min(hi, v))
    return struct.pack(
        _FRAME_FMT,
        dev_addr,
        seq & 0xFFFF,
        clamp(int(round(m.get("pm2_5", 0.0) * 10)), 0, 65535),
        clamp(int(round(m.get("pm10", 0.0) * 10)), 0, 65535),
        clamp(int(round(m.get("temperature_c", 0.0) * 10)), -32768, 32767),
        clamp(int(round(m.get("humidity_pct", 0.0) * 10)), 0, 65535),
        clamp(int(round((m.get("pressure_hpa", 1013.0) - 900.0) * 10)), 0, 65535),
        clamp(int(round(m.get("no2_ppb", 0.0))), 0, 65535),
        clamp(int(round(m.get("battery_pct", 100))), 0, 255),
        0x01,  # flags : bit0 = trame applicative valide
    )


def encrypt_payload(node_id: str, seq: int, frame: bytes) -> bytes:
    """Chiffre la trame en AES-128-CTR avec la clé de session du nœud.
    Le nonce dérive de (DevAddr, FCnt) — jamais réutilisé tant que seq croît,
    condition de sûreté du mode CTR (cf. LoRaWAN §4.3.3)."""
    cipher = Cipher(algorithms.AES(derive_session_key(node_id)),
                    modes.CTR(_ctr_nonce(_dev_addr(node_id), seq)))
    enc = cipher.encryptor()
    return enc.update(frame) + enc.finalize()


def decrypt_payload(node_id: str, seq: int, ciphertext: bytes) -> dict:
    """Déchiffre et décode une trame côté gateway. Retourne les mesures en
    unités physiques. Lève ValueError si le DevAddr décodé ne correspond pas
    au nœud (clé erronée ou trame corrompue)."""
    cipher = Cipher(algorithms.AES(derive_session_key(node_id)),
                    modes.CTR(_ctr_nonce(_dev_addr(node_id), seq)))
    dec = cipher.decryptor()
    frame = dec.update(ciphertext) + dec.finalize()
    (dev_addr, fcnt, pm25, pm10, temp, hum, press, no2, batt, flags) = struct.unpack(_FRAME_FMT, frame)
    if dev_addr != _dev_addr(node_id):
        raise ValueError(f"DevAddr mismatch pour {node_id} — clé ou trame invalide")
    return {
        "dev_addr": dev_addr, "fcnt": fcnt,
        "pm2_5": pm25 / 10.0, "pm10": pm10 / 10.0,
        "temperature_c": temp / 10.0, "humidity_pct": hum / 10.0,
        "pressure_hpa": 900.0 + press / 10.0, "no2_ppb": float(no2),
        "battery_pct": batt, "flags": flags,
    }


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

    def transmit(self, node: LoRaNode, now: datetime | None = None,
                 measurements: dict | None = None) -> dict | None:
        """Simule l'émission d'un paquet par `node`. Retourne le paquet reçu
        au format §9.3, ou None si le signal n'est pas décodable (paquet perdu
        — hors de portée pour le SF configuré). `measurements` (optionnel, mêmes
        clés que le payload MQTT simulé) est encodé en trame binaire puis chiffré
        AES-128-CTR — `payload_hex` est donc déchiffrable via decrypt_payload()."""
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
            "payload_hex": encrypt_payload(
                node.node_id, node.seq,
                build_frame(_dev_addr(node.node_id), node.seq, measurements),
            ).hex(),
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

    # Aller-retour chiffrement : émission avec mesures → déchiffrement gateway
    demo_measures = {"pm2_5": 18.4, "pm10": 31.2, "temperature_c": 28.3,
                     "humidity_pct": 65.1, "pressure_hpa": 1013.4,
                     "no2_ppb": 38.5, "battery_pct": 78}
    packet = sim.transmit(demo_nodes[0], measurements=demo_measures)
    if packet:
        decoded = decrypt_payload(packet["node_id"], packet["seq"],
                                  bytes.fromhex(packet["payload_hex"]))
        print(f"\nAES-128-CTR round-trip OK : pm2_5={decoded['pm2_5']} µg/m³, "
              f"batt={decoded['battery_pct']}%, fcnt={decoded['fcnt']}")
