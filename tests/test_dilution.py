"""Tests du signal V2 dilution d'actions (feuille de route §2).

Fixtures synthétiques purs : bandes 5 %/10 %, seuil strict « plus de
10 % », extrémités manquantes ou nulles, traçabilité des sources de
parts (dei vs repli pondéré — le garde-fou d'échelle vit dans
compute._dilution_shares, testé côté compute).

Commande :
    uv run pytest tests/test_dilution.py -v
"""

from app.signals import dilution


def test_growth_above_ten_percent_is_alerte():
    """Seuil feuille de route « plus de 10 % sur un an » -> défaillance."""
    res = dilution.evaluate(100.0, 112.0, "2023-12-31", "f1")
    assert res is not None
    assert res.value == 0.12
    assert res.severity == "défaillance"


def test_growth_exactly_ten_percent_is_watch():
    """Seuil strict « plus de 10 % » : pile 10 % -> vigilance (mi-seuil)."""
    res = dilution.evaluate(100.0, 110.0, "2023-12-31", "f1")
    assert res is not None
    assert res.value == 0.10
    assert res.severity == "vigilance"


def test_growth_between_five_and_ten_is_watch():
    """Bande intermédiaire : au-dessus de 5 % -> vigilance."""
    res = dilution.evaluate(100.0, 107.0, "2023-12-31", "f1")
    assert res is not None
    assert res.value == 0.07
    assert res.severity == "vigilance"


def test_moderate_growth_is_saine():
    """En dessous de 5 % (y compris nul ou décroissant) -> saine."""
    for prev, cur in ((100.0, 104.0), (100.0, 100.0), (100.0, 70.0)):
        res = dilution.evaluate(prev, cur, "2023-12-31", "f1")
        assert res is not None, (prev, cur)
        assert res.severity == "saine", (prev, cur)


def test_reverse_split_growth_is_saine():
    """Division des parts (reverse split) : voulue « saine », pas d'alerte."""
    res = dilution.evaluate(100.0, 10.0, "2023-12-31", "f1")
    assert res is not None
    assert res.value == -0.9
    assert res.severity == "saine"


def test_missing_or_invalid_endpoint_returns_none():
    """Strict-None : extrémité absente ou passé non positif -> pas de signal."""
    assert dilution.evaluate(None, 100.0, "2023-12-31", "f1") is None
    assert dilution.evaluate(100.0, None, "2023-12-31", "f1") is None
    assert dilution.evaluate(0.0, 100.0, "2023-12-31", "f1") is None
    assert dilution.evaluate(-5.0, 100.0, "2023-12-31", "f1") is None


def test_mixed_sources_return_none():
    """Bases hétérogènes (dei instantané vs moyenne pondérée) -> None.

    Mesuré en base : 886 paires mixtes sur 8 826 — le saut de base
    passerait pour de la dilution (AMC 2022 : 95 M moyenne -> 517 M
    couverture = +441 % de mélange). Règle « donnée manquante > faux ».
    """
    assert dilution.evaluate(
        100.0, 130.0, "2023-12-31", "f1",
        prev_source="dei_cover", cur_source="shares_weighted_basic",
    ) is None
    assert dilution.evaluate(
        100.0, 130.0, "2023-12-31", "f1",
        prev_source="shares_weighted_basic", cur_source="dei_cover",
    ) is None


def test_same_sources_are_traced_in_details():
    """Même base des deux côtés : ratio calculé, sources tracées (audit fiche)."""
    res = dilution.evaluate(
        100.0, 130.0, "2023-12-31", "f1",
        prev_source="dei_cover", cur_source="dei_cover",
    )
    assert res is not None
    assert res.details["shares_source_prev"] == "dei_cover"
    assert res.details["shares_source_cur"] == "dei_cover"
    assert res.details["shares_prev"] == 100.0
    assert res.details["shares_cur"] == 130.0
    assert res.severity == "défaillance"


# --- Correction de split (piège mesuré Apple 7:1 / 4:1) ----------------------

def test_split_between_dates_is_neutralized():
    """+552 % déclarés autour d'un 7:1 -> taux de rachat réel, saine.

    C'est le cas Apple 2014 vu en base : les parts passent de ~0,94 Md
    (pré-split) à ~6,5 Md (post-split) sans aucune dilution économique.
    """
    res = dilution.evaluate(
        100.0, 650.0, "2014-09-30", "f1",
        prev_date="2013-11-01", cur_date="2014-11-01",
        splits=[("2014-06-09", 7.0)],
    )
    assert res is not None
    # comparable_prev = 100 × 7 = 700 ; 650 / 700 − 1 = −0.0714
    assert res.value == round(650 / 700 - 1.0, 4)
    assert res.severity == "saine"
    assert res.details["split_factor"] == 7.0
    assert res.details["splits_in_window"] == [("2014-06-09", 7.0)]


def test_split_outside_window_is_ignored():
    """Split APRÈS la seconde observation : comptes du même régime, non corrigé."""
    res = dilution.evaluate(
        100.0, 650.0, "2014-05-01", "f1",
        prev_date="2013-11-01", cur_date="2014-05-01",
        splits=[("2014-06-09", 7.0)],
    )
    assert res is not None
    assert res.value == 5.5
    assert res.severity == "défaillance"
    assert res.details["split_factor"] is None
    assert res.details["splits_in_window"] == []


def test_reverse_split_is_neutralized():
    """Reverse 1:8 entre les dates : comptes ramenés au même régime."""
    res = dilution.evaluate(
        800.0, 100.0, "2023-12-31", "f1",
        prev_date="2022-01-31", cur_date="2023-02-01",
        splits=[("2022-08-25", 0.125)],
    )
    assert res is not None
    # comparable_prev = 800 × 0.125 = 100 ; 100/100 − 1 = 0
    assert res.value == 0.0
    assert res.severity == "saine"


def test_real_x8_issuance_without_split_still_alerts():
    """Le garde-fou ne masque pas la vraie dilution : ×8 sans split -> alerte."""
    res = dilution.evaluate(
        100.0, 800.0, "2021-12-31", "f1",
        prev_date="2020-12-31", cur_date="2021-12-31", splits=[],
    )
    assert res is not None
    assert res.value == 7.0
    assert res.severity == "défaillance"


def test_missing_dates_skip_correction():
    """Dates absentes avec splits fournis : calcul non corrigé (garde d'urgence)."""
    res = dilution.evaluate(
        100.0, 650.0, "2014-09-30", "f1",
        splits=[("2014-06-09", 7.0)],
    )
    assert res is not None
    assert res.value == 5.5
    assert res.details["split_factor"] is None


def test_apple_real_split_cache_neutralizes():
    """Golden léger : cache Yahoo réel d'AAPL -> splits 2014 (7:1) corrigés.

    Saute si le cache n'est pas présent (pipeline Yahoo jamais lancé) :
    les tests pur-synthétiques ci-dessus couvrent la logique.
    """
    from pathlib import Path

    import pytest

    from app.edgar.yahoo import cached_splits

    splits = cached_splits("AAPL", Path("data/cache"))
    if not splits:
        pytest.skip("cache Yahoo AAPL absent")
    dates = dict(splits)
    assert any(d.startswith("2014-06") and r == 7.0 for d, r in splits), dates
    assert any(d.startswith("2020-08") and r == 4.0 for d, r in splits), dates

    # Exercices Apple réels ~0,94 Md -> ~6,5 Md de parts déclarées.
    res = dilution.evaluate(
        940_000_000.0, 6_540_000_000.0, "2014-09-30", "f1",
        prev_date="2013-11-01", cur_date="2014-11-01",
        splits=splits,
    )
    assert res is not None
    assert res.severity == "saine"  # corrige en rachat net, pas en dilution
