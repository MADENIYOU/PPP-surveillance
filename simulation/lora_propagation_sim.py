"""Modèle de propagation radio LoRa 868 MHz (Okumura-Hata, quasi-urbain).

Référence : simulation/SIMULATION_SPEC.md §9.1, §9.2.
Fonctions : path_loss_db, rssi_dbm, is_decodable, coverage_map.

Les formules `path_loss_db`, `rssi_dbm` et `is_decodable` sont reprises
verbatim de la spec (modèle Okumura-Hata pour gateway en zone quasi-urbaine,
868 MHz, hauteur antenne gateway 15 m / capteur 3 m par défaut).
"""
from __future__ import annotations

import math

# Sensibilités de réception par spreading factor (dBm) — §9.1
SF_SENSITIVITIES_DBM = {7: -123, 8: -126, 9: -129, 10: -132, 11: -134, 12: -137}

# Portées indicatives publiées en §9.2 pour la gateway toit ESP Dakar (40 m)
SF_INDICATIVE_RANGE_KM = {7: 2, 8: 3, 9: 5, 10: 8, 11: 11, 12: 15}


def path_loss_db(distance_km: float, h_bs: float = 15, h_ms: float = 3,
                 frequency_mhz: float = 868) -> float:
    """Perte de trajet en dB (modèle Okumura-Hata quasi-urbain 868 MHz)."""
    log_f = math.log10(frequency_mhz)
    log_d = math.log10(distance_km)
    a_hms = (1.1 * math.log10(frequency_mhz) - 0.7) * h_ms \
        - (1.56 * math.log10(frequency_mhz) - 0.8)
    L = 69.55 + 26.16 * log_f - 13.82 * math.log10(h_bs) \
        - a_hms + (44.9 - 6.55 * math.log10(h_bs)) * log_d
    return L


def rssi_dbm(distance_km: float, tx_power_dbm: float = 14, **kwargs) -> float:
    """RSSI reçu en dBm."""
    return tx_power_dbm - path_loss_db(distance_km, **kwargs)


def is_decodable(rssi_dbm: float, sf: int) -> bool:
    """True si le signal est décodable pour ce spreading factor."""
    return rssi_dbm >= SF_SENSITIVITIES_DBM[sf]


def snr_db(rssi: float, sf: int, rng=None) -> float:
    """SNR estimé (dB) — non spécifié formellement par la spec : on dérive une
    valeur plausible à partir de la marge au-dessus du seuil de sensibilité du
    SF (signaux proches du seuil → SNR proche du plancher du démodulateur
    LoRa, ~ -20 dB pour les hauts SF ; signaux confortables → SNR positif).
    Un bruit gaussien optionnel (rng fourni) modélise la variabilité mesurée."""
    margin = rssi - SF_SENSITIVITIES_DBM[sf]
    floor = {7: -7.5, 8: -10, 9: -12.5, 10: -15, 11: -17.5, 12: -20}[sf]
    estimate = floor + min(margin, 25.0)
    if rng is not None:
        estimate += float(rng.normal(0.0, 1.0))
    return round(estimate, 1)


def time_on_air_ms(payload_bytes: int, sf: int, bandwidth_khz: int = 125,
                   coding_rate: int = 5, preamble_symbols: int = 8,
                   header_enabled: bool = True, low_data_rate_optimize: bool | None = None) -> float:
    """Temps d'antenne (Time-on-Air) en ms — formule standard LoRaWAN (Semtech AN1200.13).

    Non fournie dans la spec ; calcul "réel" (et non une approximation
    arbitraire) à partir des paramètres radio documentés en §9 (BW=125 kHz,
    CR=4/5 par défaut)."""
    if low_data_rate_optimize is None:
        low_data_rate_optimize = sf >= 11 and bandwidth_khz == 125

    t_symbol_ms = (2 ** sf) / bandwidth_khz  # ms

    de = 1 if low_data_rate_optimize else 0
    ih = 0 if header_enabled else 1
    crc = 1  # CRC activé (capteurs → gateway)

    numerator = 8 * payload_bytes - 4 * sf + 28 + 16 * crc - 20 * ih
    denominator = 4 * (sf - 2 * de)
    n_payload = 8 + max(math.ceil(numerator / denominator) * coding_rate, 0)

    t_preamble_ms = (preamble_symbols + 4.25) * t_symbol_ms
    t_payload_ms = n_payload * t_symbol_ms
    return round(t_preamble_ms + t_payload_ms, 1)


def coverage_map(sensor_distances_km: dict[str, float], sf: int, tx_power_dbm: float = 14,
                 h_bs: float = 40, h_ms: float = 3) -> dict[str, dict]:
    """Calcule, pour chaque capteur (id → distance à la gateway en km), le RSSI
    et la décodabilité au SF donné. Retourne aussi un résumé global, dans
    l'esprit du tableau de couverture du §9.2 (gateway toit ESP Dakar, 40 m)."""
    per_sensor: dict[str, dict] = {}
    n_covered = 0
    for sensor_id, distance in sensor_distances_km.items():
        rssi = rssi_dbm(max(distance, 0.01), tx_power_dbm=tx_power_dbm, h_bs=h_bs, h_ms=h_ms)
        decodable = is_decodable(rssi, sf)
        per_sensor[sensor_id] = {
            "distance_km": round(distance, 2),
            "rssi_dbm": round(rssi, 1),
            "decodable": decodable,
        }
        if decodable:
            n_covered += 1

    total = len(sensor_distances_km)
    return {
        "sf": sf,
        "gateway_height_m": h_bs,
        "indicative_range_km": SF_INDICATIVE_RANGE_KM.get(sf),
        "sensors": per_sensor,
        "n_covered": n_covered,
        "n_total": total,
        "coverage_ratio": round(n_covered / total, 2) if total else 0.0,
    }


if __name__ == "__main__":
    # Démo : reproduit l'esprit du tableau §9.2 avec des distances synthétiques
    # (gateway au centre de Dakar, capteurs à 0.5–14 km — cf. config/sensors.yaml).
    demo_distances = {
        "ESP32-DK-PLATEAU-001": 0.8, "ESP32-DK-MEDINA-001": 1.6,
        "ESP32-DK-GRANDDK-001": 3.2, "ESP32-DK-PIKINE-001": 6.5,
        "ESP32-DK-GUEDIAWAYE-001": 8.1, "ESP32-DK-PARCELLES-001": 5.4,
        "ESP32-DK-OUAKAM-001": 4.0, "ESP32-DK-NGOR-001": 9.5,
        "ESP32-DK-RUFISQUE-001": 13.5, "ESP32-DK-YOFF-001": 7.2,
    }
    print(f"{'SF':<4}{'Couverture':<12}{'Capteurs':<10}{'Portée indicative'}")
    for sf in (7, 9, 10, 12):
        result = coverage_map(demo_distances, sf)
        print(f"SF{sf:<2} {result['coverage_ratio']*100:>5.0f} %     "
              f"{result['n_covered']}/{result['n_total']}      "
              f"~{result['indicative_range_km']} km")
