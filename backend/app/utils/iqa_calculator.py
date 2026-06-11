"""Calcul IQA — grille EPA hybride adaptée Dakar (API_SPEC.md §4.1).

Seuil PM2.5 "bon" relevé à 25 µg/m³ (contexte harmattan), le reste suit la
grille EPA. Cohérent avec la fonction SQL compute_iqa pour les autres
polluants ; pour PM2.5 c'est CETTE grille (adaptée) qui fait foi côté API."""
from __future__ import annotations

from typing import Optional

# (iqa_low, iqa_high, conc_low, conc_high) — PM2.5 µg/m³, grille Dakar
PM25_BREAKPOINTS = [
    (0, 50, 0.0, 25.0),
    (51, 100, 25.0, 55.0),
    (101, 150, 55.0, 150.0),
    (151, 200, 150.0, 250.0),
    (201, 300, 250.0, 350.0),
    (301, 500, 350.0, 500.0),
]

LEVELS = [
    (50, "good", "Bon", "#00E400"),
    (100, "moderate", "Modéré", "#FFA500"),
    (150, "unhealthy_sensitive", "Mauvais pour personnes sensibles", "#FF7E00"),
    (200, "unhealthy", "Mauvais", "#FF0000"),
    (300, "very_unhealthy", "Très mauvais", "#8F3F97"),
    (10**9, "hazardous", "Dangereux", "#7E0023"),
]


def compute_iqa(pm25: Optional[float]) -> Optional[int]:
    if pm25 is None or pm25 < 0:
        return None
    for iqa_lo, iqa_hi, c_lo, c_hi in PM25_BREAKPOINTS:
        if pm25 <= c_hi:
            return round(iqa_lo + (pm25 - c_lo) / (c_hi - c_lo) * (iqa_hi - iqa_lo))
    return 500


def iqa_level(iqa: int) -> tuple[str, str, str]:
    """→ (level, label_fr, color)."""
    for threshold, level, label, color in LEVELS:
        if iqa <= threshold:
            return level, label, color
    return LEVELS[-1][1:]
