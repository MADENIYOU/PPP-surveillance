"""Tests unitaires — calcul IQA (grille EPA hybride Dakar, API_SPEC §4.1)."""
from app.utils.iqa_calculator import compute_iqa, iqa_level


def test_iqa_good_boundary():
    assert compute_iqa(0) == 0
    assert compute_iqa(25.0) == 50          # seuil "bon" relevé à 25 µg/m³


def test_iqa_moderate():
    iqa = compute_iqa(40.0)
    assert 51 <= iqa <= 100
    assert iqa_level(iqa)[0] == "moderate"


def test_iqa_hazardous_capped():
    assert compute_iqa(1000.0) == 500


def test_iqa_none():
    assert compute_iqa(None) is None
    assert compute_iqa(-1) is None


def test_levels_labels_fr():
    assert iqa_level(30) == ("good", "Bon", "#00E400")
    assert iqa_level(180)[0] == "unhealthy"
