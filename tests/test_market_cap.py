"""Chaîne de capitalisation de market_capitalisation() — garde-fous flottant.

Le flottant SEC déclaré est la seule source de valorisation capable de
mentir sans se faire prendre par les maths (D = cap/dettes avalise tout) :
erreurs mesurées NDSN 2018 (7,4 M$ au lieu de 7,4 Md$), ADI 2012 (pareil),
flottants à 0 donnant des Z en fausse faillite. Ces tests verrouillent le
comportement du garde-fou _float_is_plausible au sein de la chaîne :
    (a) cours ≤ 14 j × parts de couverture dei
    (b) flottant SEC ≤ 12 mois, SI plausible face aux autres années
    (c) cours × parts pondérées moyennes
    (d) None -> Altman non calculable (donnée manquante > faux score)

Commande pour ce fichier seul :
    uv run pytest tests/test_market_cap.py -v
"""

from app.signals.compute import (
    _float_is_plausible,
    market_capitalisation,
)


def _node(value, period_end="2018-10-31"):
    """Nœud formaté comme build_years (value, period_end, filing_id)."""
    return {"value": value, "period_end": period_end, "filing_id": "f1"}


def _cur(**extra):
    """Exercice type : bilan au 2018-10-31, + concepts optionnels."""
    return {"total_assets": _node(1e9), **extra}


# --- _float_is_plausible (règle pure) ---------------------------------------

def test_zero_float_rejected():
    """Flottant 0 : D = 0 dans l'Altman -> jamais retenu."""
    assert not _float_is_plausible(0.0, [2e9, 3e9])


def test_wrong_scale_float_rejected():
    """Facteur 1000 (cas NDSN/ADI mesuré) : écarté."""
    assert not _float_is_plausible(7_441_507.0, [7.18e9, 8.35e9])


def test_plausible_float_accepted():
    """Croissance annuelle normale (facteur < 100) : retenu."""
    assert _float_is_plausible(8.35e9, [7.18e9, 9.1e9])


def test_single_positive_float_accepted():
    """Pas d'autre année comparable -> impossible à juger, accepté."""
    assert _float_is_plausible(5e7, [0.0, -1.0])  # positifs vides


# --- market_capitalisation (chaîne complète) --------------------------------

def test_plausible_float_is_source_b():
    """Pas de cours ni de parts : flottant plausible = source (b)."""
    cur = _cur()
    floats = [("2018-04-30", 7.4e9), ("2017-04-30", 7.1e9)]
    cap, src = market_capitalisation(cur, floats, [])
    assert (cap, src) == (7.4e9, "flottant_sec")


def test_zero_float_falls_back_to_wavg():
    """Flottant 0 -> repli (c) cours × parts pondérées."""
    cur = _cur(shares_weighted_basic=_node(10_000_000))
    floats = [("2018-04-30", 0.0), ("2017-04-30", 2e9)]
    prices = [("2018-10-31", 100.0)]
    cap, src = market_capitalisation(cur, floats, prices)
    assert (cap, src) == (100.0 * 10_000_000, "yahoo+parts_ponderees")


def test_wrong_scale_float_without_fallback_is_missing():
    """Flottant hors échelle et aucune autre source -> None, pas un score."""
    cur = _cur()
    floats = [("2018-04-30", 7_441_507.0), ("2017-04-30", 7.18e9)]
    cap, src = market_capitalisation(cur, floats, [("2018-10-31", 150.0)])
    assert (cap, src) == (None, None)  # le cours seul ne suffit pas (pas de parts)


def test_dei_chain_wins_even_if_float_is_bogus():
    """(a) cours × parts dei prime toujours : le flottant n'est même pas lu."""
    cur = _cur(shares_outstanding=_node(57_900_000))
    floats = [("2018-04-30", 7_441_507.0), ("2017-04-30", 7.18e9)]
    prices = [("2018-10-31", 150.0)]
    cap, src = market_capitalisation(cur, floats, prices)
    assert (cap, src) == (150.0 * 57_900_000, "yahoo+dei")


def test_no_balance_sheet_returns_none():
    """Sans total_assets : pas de date de bilan -> None (pas de calcul)."""
    assert market_capitalisation({}, [("2018-04-30", 7e9)], []) == (None, None)
