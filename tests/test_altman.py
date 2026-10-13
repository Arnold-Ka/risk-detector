"""Tests du signal Altman Z.

Stratégie (utile pour la suite) :
  - ICI : comportement pur, sans base, sans réseau — les modules de
    app/signals/ sont des calculs déterministes, c'est ce qui les rend
    testables ainsi ;
  - golden (fin du fichier) : le Z calculé par app.signals.altman doit
    REJOINDRE celui du gate de phase 0 (scripts/compute_z.py, colonne Z
    de ratios.csv) sur la même année — c'est le test anti-dérive entre
    les deux implémentations de la même formule (voir altman.py docstring).

Commande pour ce fichier seul :
    uv run pytest tests/test_altman.py -v
"""

import csv
from pathlib import Path

import pytest

from app.signals.altman import Z_DISTRESS, Z_SAFE, altman_severity, evaluate

OUT_DIR = Path("data/phase0")


def test_missing_data_returns_none():
    """total_assets absent (None) -> pas de division par zéro, None."""
    assert evaluate(100, None, 200, 150, 500, 400, 1200, "2023-12-31", "f1") is None


def test_zero_total_assets_returns_none():
    """Actif total nul = bilan impossible -> None (jamais Z infini)."""
    assert evaluate(100, 0, 200, 150, 500, 400, 1200, "2023-12-31", "f1") is None


def test_missing_component_returns_none():
    """Une composante manquante (ex. capitalisation, titre delisté) -> None.

    Règle produit : donnée manquante > faux score. Testée sur les 7 entrées
    une par une : aucune ne peut être silencieusement remplacée par 0.
    """
    base = dict(
        working_capital=100, total_assets=1000, retained_earnings=200,
        ebit=150, market_capitalisation=5000, total_liabilities=400,
        sales=1200, period_end="2023-12-31", filing_id="f1",
    )
    for field in ("working_capital", "retained_earnings", "ebit",
                  "market_capitalisation", "sales"):
        kwargs = {**base, field: None}
        assert evaluate(**kwargs) is None, f"{field} manquant doit annuler Z"


def test_zero_liabilities_returns_none():
    """D = cap/dettes : dettes nulles => ratio indéfini => None."""
    assert evaluate(100, 1000, 200, 150, 5000, 0, 1200, "2023-12-31", "f1") is None


def test_formula_matches_hand_calculation():
    """Calcul à la main : A=.1 B=.2 C=.15 D=12.5 E=2 -> Z=10.395."""
    res = evaluate(
        working_capital=100, total_assets=1000, retained_earnings=200,
        ebit=150, market_capitalisation=5000, total_liabilities=400,
        sales=2000, period_end="2023-12-31", filing_id="f1",
    )
    assert res is not None
    assert res.value == pytest.approx(10.395)
    assert res.details["D"] == pytest.approx(12.5)  # 5000/400, pas /1000
    assert res.signal_type == "altman"
    assert res.filing_id == "f1"


def test_severity_bands_match_phase0():
    """Mêmes bandes que scripts/compute_z.py (1,81 / 2,99)."""
    assert altman_severity(3.5) == "saine"
    assert altman_severity(Z_SAFE) == "saine"          # 2,99 inclus -> saine
    assert altman_severity(2.5) == "vigilance"
    assert altman_severity(Z_DISTRESS) == "vigilance"   # 1,81 inclus -> vigilance
    assert altman_severity(1.5) == "défaillance"
    assert altman_severity(-0.4) == "défaillance"       # AMC sous 0


# --- Golden : accord avec le gate de phase 0 ---------------------------------

def _read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # en-tête
        return [r for r in reader]


def test_golden_reproduces_phase0_z():
    """Z(app.signals) == Z(compute_z) sur chaque année d'Apple où le gate
    a pu calculer (tolérance 0,002 : le gate arrondit A-E à 4 décimales
    puis Z à 3). Si ce test casse, les deux formules ont divergé — corriger
    l'une des deux, pas le test.
    """
    facts = _read_csv(OUT_DIR / "apple_healthy_facts.csv")
    ratios = _read_csv(OUT_DIR / "apple_healthy_ratios.csv")

    # Valeurs d'entrée par année (facts : year, period_end, concept, value…)
    # — period_end est conservé métadonnée pour le SignalResult.
    per_year: dict[int, dict] = {}
    for r in facts:
        node = per_year.setdefault(int(r[0]), {"period_end": r[1], "values": {}})
        node["values"][r[2]] = float(r[3])

    # ratios.csv : [year, A, B, C, E, D, Z, date_valeur, cours, capitalisation,
    #                dettes_totales, source_D, zone]
    checked = 0
    for r in ratios:
        if not r[6]:  # Z vide dans le gate (composante manquante) -> ignoré
            continue
        year = int(r[0])
        node = per_year[year]
        y = node["values"]
        cap, liab = float(r[9]), float(r[10])
        res = evaluate(
            working_capital=y["current_assets"] - y["current_liabilities"],
            total_assets=y["total_assets"],
            retained_earnings=y["retained_earnings"],
            ebit=y["operating_income"],
            market_capitalisation=cap,
            total_liabilities=liab,
            sales=y["sales"],
            period_end=node["period_end"],
            filing_id=None,
        )
        assert res is not None, f"{year} : Z du gate présent mais entrées manquantes"
        assert res.value == pytest.approx(float(r[6]), abs=0.002), (
            f"{year} : Z signal {res.value} != Z gate {r[6]}"
        )
        checked += 1
    assert checked >= 15, f"seulement {checked} années croisées — CSV inattendu"
