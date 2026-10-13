"""Tests des signaux quantitatifs MVP (feuille de route §6, sem. 5-6).

Trois niveaux, même stratégie que tests/test_normalize.py :
  1. fixtures synthétiques — calculs purs, toujours exécutés ;
  2. golden Altman dans tests/test_altman.py (accord avec le gate phase 0) ;
  3. intégration sur le trio réel (si cache SEC présent) : mêmes entrées
     que l'ingestion PostgreSQL, assertions de cohérence globale.

Commande :
    uv run pytest tests/test_signals.py -v
"""

import csv
from pathlib import Path

import pytest

from app.normalize.loader import extract
from app.signals import beneish, composite, divergence, piotroski, runway
from app.signals.common import SEVERITIES, LEVELS
from app.signals.compute import compute_company

CACHE_DIR = Path("data/cache")
PHASE0_DIR = Path("data/phase0")

TRIO = [
    ("apple_healthy", "0000320193"),
    ("amc_distressed", "0001411579"),
    ("bbby_bankrupt", "0000886158"),
]


def _year(ni, cfo, ta, ca, cl, ltd, shares, sales, gp=None, op=None,
          re=0, r=0, dep=0, ppe=0, sga=0) -> dict:
    """Fixture d'exercice compacte pour piotroski/beneish (valeurs brutes)."""
    return {
        "net_income": ni, "cfo": cfo, "total_assets": ta,
        "current_assets": ca, "current_liabilities": cl,
        "long_term_debt": ltd, "shares_outstanding": shares, "sales": sales,
        "gross_profit": gp, "operating_income": op, "retained_earnings": re,
        "receivables": r, "depreciation": dep, "ppe": ppe, "sga": sga,
    }


# --- Piotroski ---------------------------------------------------------------

def test_piotroski_all_criteria_pass():
    """Fixture entièrement améliorée -> F=9, sévérité saine.

    Chaque critère doit strictement s'améliorer (F3/F5/F6/F8/F9 sont des
    comparaisons, pas des niveaux) tout en restant positif (F1/F2/F4).
    """
    prev = _year(ni=70, cfo=80, ta=1000, ca=400, cl=250, ltd=300,
                 shares=100, sales=800, gp=200)
    cur = _year(ni=100, cfo=130, ta=1100, ca=500, cl=250, ltd=300,
                shares=95, sales=950, gp=280)
    res = piotroski.evaluate(prev, cur, "2023-12-31", "f1")
    assert res is not None
    assert res.value == 9.0
    assert res.severity == "saine"
    assert all(res.details["criteria"].values())


def test_piotroski_all_criteria_fail():
    """Fixture entièrement détérorée -> F=0, sévérité défaillance.

    NI et CFO tous deux négatifs sinon F4 (accruals) ou F1 (ROA) pourraient
    encore passer « par accident ».
    """
    prev = _year(ni=70, cfo=80, ta=1000, ca=500, cl=220, ltd=250,
                 shares=95, sales=900, gp=240)
    cur = _year(ni=-100, cfo=-150, ta=1100, ca=400, cl=300, ltd=300,
                shares=120, sales=850, gp=200)
    res = piotroski.evaluate(prev, cur, "2023-12-31", "f1")
    assert res is not None
    assert res.value == 0.0
    assert res.severity == "défaillance"
    assert not any(res.details["criteria"].values())


def test_piotroski_missing_input_returns_none():
    """Aucun résultat brut ni EBIT -> critère de marge inévaluable -> None."""
    prev = _year(ni=70, cfo=80, ta=1000, ca=500, cl=220, ltd=250,
                 shares=95, sales=900)
    cur = _year(ni=70, cfo=80, ta=1000, ca=500, cl=220, ltd=250,
                shares=95, sales=900)
    assert piotroski.evaluate(prev, cur, "2023-12-31", "f1") is None


def test_piotroski_margin_fallback_operating_income():
    """Repli F8 : sans gross_profit, la marge vient de operating_income
    et la source est tracée dans details.margin_source.

    Autres critères améliorés un par un (comparaisons strictes) pour que
    seul le marge puisse décider du total.
    """
    prev = _year(ni=70, cfo=80, ta=1000, ca=400, cl=250, ltd=300,
                 shares=100, sales=800, op=100)
    cur = _year(ni=100, cfo=130, ta=1100, ca=500, cl=250, ltd=300,
                shares=95, sales=950, op=180)
    res = piotroski.evaluate(prev, cur, "2023-12-31", "f1")
    assert res is not None
    assert res.details["margin_source"] == "operating_income_fallback"
    assert res.value == 9.0  # marge en hausse via le repli, tous critères OK


def test_piotroski_without_previous_year_returns_none():
    """Premier exercice de l'histoire : comparaison impossible -> None."""
    cur = _year(ni=70, cfo=80, ta=1000, ca=500, cl=220, ltd=250,
                shares=95, sales=900, gp=240)
    assert piotroski.evaluate({}, cur, "2023-12-31", "f1") is None


# --- Beneish -----------------------------------------------------------------

def _beneish_base(**overrides) -> dict:
    """Exercice dont TOUS les ratios valent 1 (prev == cur) et TATA = 0.

    Clés = noms de concepts du chargeur (receivables/depreciation/ppe…).
    Toutes les entrées à valeur identique d'un exercice sur l'autre =>
    DSRI=GMI=AQI=SGI=SGAI=DEPI=LVGI=1, et NI == CFO => TATA=0.
    M attendu à la main : -4,840 + 0,920 + 0,528 + 0,404 + 0,892 + 0,115
                           - 0,172 = -2,153.
    """
    base = dict(net_income=50, cfo=50, total_assets=1000, current_assets=400,
                current_liabilities=200, long_term_debt=300, sales=800,
                gross_profit=200, receivables=100, depreciation=40,
                ppe=500, sga=80)
    base.update(overrides)
    return base


def test_beneish_hand_computed_value():
    prev = _beneish_base()
    cur = _beneish_base()
    res = beneish.evaluate(prev, cur, "2023-12-31", "f1")
    assert res is not None
    assert res.value == pytest.approx(-2.153, abs=1e-6)
    assert res.severity == "vigilance"  # -2,27 < -2,153 <= -1,78
    assert set(res.details["ratios"]) == {
        "dsri", "gmi", "aqi", "sgi", "sgai", "depi", "lvgi", "tata"
    }


def test_beneish_high_accruals_flagged_suspect():
    """TATA élevé (bénéfice sans cash) fait franchir le seuil -1,78."""
    prev = _beneish_base()
    cur = _beneish_base(net_income=550)  # TATA = (550-50)/1000 = 0.5 -> +2,34
    res = beneish.evaluate(prev, cur, "2023-12-31", "f1")
    assert res is not None
    assert res.value > beneish.M_SUSPECT
    assert res.severity == "défaillance"


def test_beneish_missing_input_returns_none():
    """Somme pondérée : un ratio absent => M absent (pas de somme partielle)."""
    prev = _beneish_base(sga=None)
    cur = _beneish_base(sga=None)
    assert beneish.evaluate(prev, cur, "2023-12-31", "f1") is None


def test_beneish_missing_gross_profit_returns_none():
    """AMC-like : pas de résultat brut -> GMI inexploitable -> None."""
    prev = _beneish_base(gross_profit=None)
    cur = _beneish_base(gross_profit=None)
    assert beneish.evaluate(prev, cur, "2023-12-31", "f1") is None


# --- Runway ------------------------------------------------------------------

def test_runway_vigilance_band():
    res = runway.evaluate(cash=100, cfo=-60, period_end="2023-12-31", filing_id="f1")
    assert res is not None
    assert res.value == pytest.approx(20.0)  # 100 / (60/12)
    assert res.severity == "vigilance"       # 12 <= 20 < 24


def test_runway_alert_below_12_months():
    res = runway.evaluate(cash=30, cfo=-60, period_end="2023-12-31", filing_id="f1")
    assert res is not None
    assert res.value == pytest.approx(6.0)
    assert res.severity == "défaillance"


def test_runway_without_burn_is_ok_without_value():
    """CFO positif : pas de mois à afficher (None), sévérité saine."""
    res = runway.evaluate(cash=100, cfo=40, period_end="2023-12-31", filing_id="f1")
    assert res is not None
    assert res.value is None
    assert res.severity == "saine"


def test_runway_negative_cash_clamped_to_zero():
    res = runway.evaluate(cash=-10, cfo=-60, period_end="2023-12-31", filing_id="f1")
    assert res is not None
    assert res.value == 0.0
    assert res.severity == "défaillance"
    assert res.details["months_raw"] == pytest.approx(-2.0)  # brut tracé


def test_runway_missing_returns_none():
    assert runway.evaluate(None, -60, "2023-12-31", "f1") is None
    assert runway.evaluate(100, None, "2023-12-31", "f1") is None


# --- Écart bénéfice/cash -----------------------------------------------------

def _div_series(ys: dict[int, tuple]) -> dict[int, dict]:
    """{année: (ni, cfo)} -> série au format evaluate_history (nœuds)."""
    def node(year, value):
        return {"value": value, "period_end": f"{year}-12-31",
                "filing_id": f"f{year}"}

    return {
        year: {"net_income": node(year, ni), "cfo": node(year, cfo)}
        for year, (ni, cfo) in ys.items()
    }


def test_divergence_streak_three_years():
    """Bénéfice en hausse + cash en baisse 3 années de suite -> streak 3."""
    series = _div_series({
        2020: (10, 10),
        2021: (20, 5),   # divergent -> streak 1 (vigilance)
        2022: (30, 4),   # divergent -> streak 2 (défaillance)
        2023: (40, 3),   # divergent -> streak 3 (défaillance)
    })
    results = divergence.evaluate_history(series)
    assert results[2021].value == 1.0
    assert results[2021].severity == "vigilance"
    assert results[2022].severity == "défaillance"
    assert results[2023].value == 3.0
    assert 2020 not in results  # pas d'exercice précédent


def test_divergence_resets_when_cash_recovers():
    series = _div_series({
        2020: (10, 10),
        2021: (20, 5),   # streak 1
        2022: (30, 20),  # cash repart en hausse -> reset
        2023: (40, 15),  # re-divergent -> streak 1
    })
    results = divergence.evaluate_history(series)
    assert results[2022].value == 0.0
    assert results[2022].severity == "saine"
    assert results[2023].value == 1.0


def test_divergence_skips_missing_years():
    """Entrée manquante : exercice absent du résultat, pas de faux 0."""
    series = _div_series({2020: (10, 10), 2021: (20, None), 2022: (30, 2)})
    results = divergence.evaluate_history(series)
    assert 2021 not in results
    # 2022 a son pair complet (2021 manquant cfo) => 2022 dépend de 2021 :
    # non évaluable non plus (prev.get('cfo') est None).
    assert 2022 not in results


# --- Score global ------------------------------------------------------------

def test_composite_all_alerts_is_critical():
    sev = {name: "défaillance" for name in composite.WEIGHTS}
    res = composite.evaluate(sev, "2023-12-31")
    assert res is not None
    assert res.value == pytest.approx(2.0)
    assert res.severity == "critique"


def test_composite_all_ok_is_low():
    sev = {name: "saine" for name in composite.WEIGHTS}
    res = composite.evaluate(sev, "2023-12-31")
    assert res is not None
    assert res.value == 0.0
    assert res.severity == "faible"


def test_composite_half_alerts_is_high():
    """Une alerte + un sain : moyenne 1,0 -> niveau élevé (bande [1, 1,5[)."""
    sev = {"altman": "défaillance", "piotroski": "saine"}
    res = composite.evaluate(sev, "2023-12-31")
    assert res is not None
    assert res.value == pytest.approx(1.0)
    assert res.severity == "élevé"
    # Absents = poids connus mais sévérité non fournie ce-là (composite
    # pondère 7 signaux depuis l'ajout des événements).
    assert set(res.details["absent"]) == {
        "beneish", "divergence", "runway", "late_filing", "critical_8k",
    }


def test_composite_ignores_unknown_and_empty():
    """Signal inconnu ignoré ; aucun composant -> None (pas de niveau inventé)."""
    assert composite.evaluate({}, "2023-12-31") is None
    res = composite.evaluate({"inconnu": "défaillance"}, "2023-12-31")
    assert res is None


# --- Intégration sur le trio réel --------------------------------------------

def _load_trio(cik: str) -> tuple[list[dict], list[tuple[str, float]]]:
    """(lignes chargeur, cours de ratios.csv) pour une entreprise du trio."""
    cache_file = CACHE_DIR / f"companyfacts_{cik}.json"
    if not cache_file.exists():
        pytest.skip(f"cache SEC absent ({cache_file}) — lancer fetch_phase0")
    import json

    rows = extract(json.loads(cache_file.read_text(encoding="utf-8")))
    # Même forme que facts : filing_id = accn pour la traçabilité.
    for row in rows:
        row["filing_id"] = row["accn"]

    slug = next(s for s, c in TRIO if c == cik)
    prices: list[tuple[str, float]] = []
    ratios_file = PHASE0_DIR / f"{slug}_ratios.csv"
    if ratios_file.exists():
        with ratios_file.open(encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)
            # colonnes [year, A, B, C, E, D, Z, date_valeur, cours, …]
            prices = [(r[7], float(r[8])) for r in reader if r[7] and r[8]]
    return rows, prices


@pytest.mark.parametrize("slug,cik", TRIO)
def test_trio_produces_traced_signals(slug: str, cik: str):
    """Chaque signal du trio est tracé (period_end + filing_id) et sévère
    dans le vocabulaire produit."""
    rows, prices = _load_trio(cik)
    results = compute_company(rows, prices)
    assert results, f"{slug}: aucun signal calculé"
    types = {r.signal_type for r in results}
    assert "altman" in types and "composite" in types and "runway" in types
    for r in results:
        assert r.period_end and len(r.period_end) == 10
        assert r.severity in (SEVERITIES + LEVELS), r
        if r.signal_type == "composite":
            assert r.filing_id is None  # dérive d'autres signaux tracés
        else:
            assert r.filing_id, f"{r.signal_type}@{r.period_end} sans dépôt"


def test_trio_expected_profiles():
    """Profils attendus (phase 0) :
      - Apple : Altman saine sur les derniers exercices ;
      - AMC : pas de Beneish (pas de résultat brut publié) mais bien un F ;
      - BBBY : Altman défaillance sur l'exercice final (2023).
    """
    rows_a, prices_a = _load_trio("0000320193")
    apple = {(r.signal_type, r.period_end): r for r in compute_company(rows_a, prices_a)}
    last_apple = max(k[1] for k in apple if k[0] == "altman")
    assert apple[("altman", last_apple)].severity == "saine"

    rows_m, prices_m = _load_trio("0001411579")
    amc = compute_company(rows_m, prices_m)
    assert not [r for r in amc if r.signal_type == "beneish"], (
        "AMC ne devrait pas avoir de Beneish (GMI/SGAI inexploitables)"
    )
    assert [r for r in amc if r.signal_type == "piotroski"], (
        "AMC doit avoir un F-score (repli de marge sur operating_income)"
    )
    amc_altman = [r for r in amc if r.signal_type == "altman"]
    assert amc_altman and amc_altman[-1].severity == "défaillance"

    rows_b, prices_b = _load_trio("0000886158")
    bbby = {(r.signal_type, r.period_end): r for r in compute_company(rows_b, prices_b)}
    final = max(k[1] for k in bbby if k[0] == "altman")
    assert final.startswith("2023"), f"dernier exercice BBBY inattendu: {final}"
    assert bbby[("altman", final)].severity == "défaillance"
