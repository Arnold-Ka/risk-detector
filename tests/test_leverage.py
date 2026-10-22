"""Tests du signal V2 dette nette / EBITDA (feuille de route §2).

Fixtures synthétiques purs (stratégie niveau 1 de tests/test_signals.py) :
bandes de sévérité, cas EBITDA ≤ 0, repli amortissements, entrées
manquantes et tendance « en hausse » du critère d'alerte.

Commande :
    uv run pytest tests/test_leverage.py -v
"""

from app.signals import leverage


def _year(ltd: float, cash: float, ebit: float, dep: float | None = None) -> dict:
    """Exercice compact {concept: valeur} pour leverage.evaluate."""
    year = {
        "long_term_debt": ltd,
        "cash": cash,
        "operating_income": ebit,
    }
    if dep is not None:
        year["depreciation"] = dep
    return year


# --- Zone saine (ratio ≤ 4) ---------------------------------------------------

def test_healthy_net_cash_position_is_saine():
    """Trésorerie > dette : ratio négatif, largement sous le seuil 4."""
    res = leverage.evaluate(None, _year(ltd=50, cash=60, ebit=40, dep=10),
                             "2023-12-31", "f1")
    assert res is not None
    # dette nette = 50 - 60 = -10 ; EBITDA = 40 + 10 = 50 ; ratio = -0.2
    assert res.value == -0.2
    assert res.severity == "saine"
    assert res.details["ebitda_source"] == "operating_income_plus_depreciation"
    assert res.details["rising"] is None  # pas d'exercice précédent


def test_ratio_exactly_threshold_is_saine():
    """Seuil strict « supérieur à 4 » : ratio = 4,0 pile reste saine."""
    res = leverage.evaluate(None, _year(ltd=100, cash=60, ebit=7, dep=3),
                             "2023-12-31", "f1")
    assert res is not None
    # net = 40, EBITDA = 10, ratio = 4.0 (pas > 4)
    assert res.value == 4.0
    assert res.severity == "saine"


# --- Zone d'alerte (« supérieur à 4 et en hausse ») --------------------------

def _prev_balanced() -> dict:
    """Exercice précédent : net 80 / EBITDA 40 = ratio 2,0."""
    return _year(ltd=100, cash=20, ebit=30, dep=10)


def test_above_threshold_and_rising_is_alerte():
    """Critère complet de la feuille de route -> défaillance."""
    cur = _year(ltd=300, cash=20, ebit=35, dep=10)  # net 280 / 45 = 6.22
    res = leverage.evaluate(_prev_balanced(), cur, "2023-12-31", "f1")
    assert res is not None
    assert res.value == round(280 / 45, 3)
    assert res.severity == "défaillance"
    assert res.details["rising"] is True
    assert res.details["ratio_prev"] == 2.0


def test_above_threshold_but_falling_is_watch():
    """Au-dessus de 4 mais en baisse : vigilance (pas le critère complet)."""
    prev = _year(ltd=300, cash=20, ebit=30, dep=10)  # net 280 / 40 = 7.0
    cur = _year(ltd=300, cash=20, ebit=35, dep=10)   # net 280 / 45 = 6.22
    res = leverage.evaluate(prev, cur, "2023-12-31", "f1")
    assert res is not None
    assert res.severity == "vigilance"
    assert res.details["rising"] is False


def test_above_threshold_without_previous_year_is_watch():
    """Pas de passé : « en hausse » non confirmable -> vigilance, pas plus."""
    cur = _year(ltd=300, cash=20, ebit=35, dep=10)
    res = leverage.evaluate(None, cur, "2023-12-31", "f1")
    assert res is not None
    assert res.severity == "vigilance"
    assert res.details["rising"] is None


def test_rising_but_still_below_threshold_is_saine():
    """La hausse seule ne suffit pas : 1 -> 3 reste sous le seuil 4."""
    prev = _year(ltd=40, cash=10, ebit=30)   # net 30 / 30 = 1.0
    cur = _year(ltd=130, cash=10, ebit=40)   # net 120 / 40 = 3.0
    res = leverage.evaluate(prev, cur, "2023-12-31", "f1")
    assert res is not None
    assert res.severity == "saine"
    assert res.details["rising"] is True


def test_previous_ebitda_non_positive_keeps_ratio_prev_none():
    """Passé avec EBITDA ≤ 0 : ratio_prev indéfini -> rising None -> watch."""
    prev = _year(ltd=200, cash=20, ebit=-5, dep=2)   # EBITDA = -3
    cur = _year(ltd=300, cash=20, ebit=35, dep=10)   # ratio 6.22
    res = leverage.evaluate(prev, cur, "2023-12-31", "f1")
    assert res is not None
    assert res.details["ratio_prev"] is None
    assert res.details["rising"] is None
    assert res.severity == "vigilance"


# --- EBITDA ≤ 0 : sévérité sans nombre ---------------------------------------

def test_negative_ebitda_with_debt_is_alerte_without_value():
    """Dette à servir, aucun cash-flow : défaillance, value None assumée."""
    res = leverage.evaluate(None, _year(ltd=100, cash=10, ebit=-5, dep=2),
                             "2023-12-31", "f1")
    assert res is not None
    assert res.value is None
    assert res.severity == "défaillance"
    assert res.details["reason"] == "ebitda_non_positive_avec_dette"


def test_negative_ebitda_with_net_cash_is_saine():
    """Perte mais trésorerie nette : rien à servir -> saine, value None."""
    res = leverage.evaluate(None, _year(ltd=10, cash=100, ebit=-5),
                             "2023-12-31", "f1")
    assert res is not None
    assert res.value is None
    assert res.severity == "saine"
    assert res.details["reason"] == "ebitda_non_positive_avec_trésorerie_nette"


# --- Replis et entrées manquantes --------------------------------------------

def test_missing_depreciation_falls_back_to_ebit_only():
    """Pas d'amortissements publiés : EBIT seul, source tracée."""
    res = leverage.evaluate(None, _year(ltd=100, cash=20, ebit=50),
                             "2023-12-31", "f1")
    assert res is not None
    # net 80 / EBIT 50 = 1.6 (l'EBITDA avec dep=0 aurait donné 1.6 aussi
    # ici, on vérie surtout la SOURCE tracée et le calcul sans dep).
    assert res.details["ebitda_source"] == "operating_income_only"
    assert res.details["depreciation"] is None
    assert res.value == 1.6


def test_missing_input_returns_none():
    """Strict-None : un pilier absent (dette, trésorerie ou EBIT) tue tout."""
    base = _year(ltd=100, cash=20, ebit=50, dep=10)
    for missing in ("long_term_debt", "cash", "operating_income"):
        year = {k: v for k, v in base.items() if k != missing}
        assert leverage.evaluate(None, year, "2023-12-31", "f1") is None, missing
