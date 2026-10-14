"""Tests de la logique pure des cohortes du backtest.

Cible : app/backtest/cohort.py — parsing FTS, ancre 1.03, écran témoin,
couverture XBRL, échantillonnage SIC. Fixtures SYNTHÉTIQUES toujours +
invariants sur le cache BBBY réel si présent (le vrai companyfacts de la
faillie de référence).

Commande :
    uv run pytest tests/test_backtest.py -v
"""

import json
from pathlib import Path

import pytest

from app.backtest.cohort import (
    control_screen,
    coverage_ok,
    first_item_103,
    is_financial,
    make_slug,
    norm_name,
    parse_fts_hits,
    pre_failure_years,
    sample_controls,
    sector_group_for_sic,
    title_matches_entity,
)
import app.backtest.cohort as cohort_mod

CACHE_BBBY = Path("data/cache/companyfacts_0000886158.json")


# --- FTS ---------------------------------------------------------------------

def test_fts_keeps_only_verified_103_items():
    """Le texte « Item 1.03 » peut apparaître sans être l'item déclaré :
    le champ `items` de l'en-tête fait foi."""
    sources = [
        # Item déclaré 1.03 -> retenu.
        {"ciks": ["0000320193"], "file_date": "2020-06-01", "items": ["1.03", "9.01"],
         "display_names": ["Foo, Inc.  (CIK 0000320193)"], "sics": ["3571"]},
        # Texte « Item 1.03 » mais items déclarés = 5.02 -> écarté.
        {"ciks": ["0000111111"], "file_date": "2020-07-01", "items": ["5.02"],
         "display_names": ["Bar Corp"], "sics": ["2010"]},
    ]
    out = parse_fts_hits(sources, 2020)
    assert set(out) == {320193}
    assert out[320193]["bankruptcy_date"] == "2020-06-01"
    assert out[320193]["sic"] == 3571
    assert out[320193]["name"] == "Foo, Inc."


def test_fts_earliest_103_wins_and_window_enforced():
    """Plusieurs 1.03 (pétition + confirmation de plan) : le plus tôt gagne ;
    hors fenêtre 2015-2025 : ignoré."""
    sources = [
        {"ciks": ["42"], "file_date": "2019-03-01", "items": ["1.03"],
         "display_names": ["X"], "sics": ["5000"]},
        {"ciks": ["42"], "file_date": "2017-08-15", "items": ["1.03"],
         "display_names": ["X"], "sics": ["5000"]},
        {"ciks": ["42"], "file_date": "2014-05-01", "items": ["1.03"],
         "display_names": ["X"], "sics": ["5000"]},
        {"ciks": ["42"], "file_date": "2026-01-10", "items": ["1.03"],
         "display_names": ["X"], "sics": ["5000"]},
    ]
    out = parse_fts_hits(sources, 0)
    assert out[42]["bankruptcy_date"] == "2017-08-15"


def test_fts_items_as_string():
    """items parfois « 1.03,2.04 » en chaîne : le split gère les deux formes."""
    sources = [{"ciks": ["7"], "file_date": "2021-02-02", "items": ["1.03,2.04"],
                "display_names": ["Y"], "sics": None}]
    assert 7 in parse_fts_hits(sources, 2021)


# --- SIC ---------------------------------------------------------------------

def test_financial_sic_exclusion_and_labels():
    assert is_financial("6021")       # banque commerciale
    assert is_financial(6331)         # assurance
    assert is_financial("6798")       # REIT
    assert not is_financial("3571")   # matériel informatique
    assert not is_financial(None)
    assert sector_group_for_sic("6021") == "bank"
    assert sector_group_for_sic("6411") == "insurance"
    assert sector_group_for_sic("6798") == "reit"
    assert sector_group_for_sic("5211") == "other"


# --- Noms (Wikipedia -> EDGAR) ----------------------------------------------

def test_name_normalization_strips_accents_and_suffixes():
    assert norm_name("Bed Bath & Beyond, Inc.") == "bed bath beyond"
    assert norm_name("Québecor Inc.") == "quebecor"
    assert title_matches_entity("IRobot", "iRobot, Inc.")
    assert title_matches_entity("Bed Bath & Beyond", "Bed Bath & Beyond, Inc.")
    # Même radical après retrait des suffixes société.
    assert title_matches_entity("Target", "Target Corp Holdings LLC")
    assert not title_matches_entity("Lufthansa", "Target Corp")


# --- Ancre submissions -------------------------------------------------------

def _filing(form, filed_at, items=""):
    return {"form": form, "filed_at": filed_at, "items": items, "accession": f"A-{filed_at}"}


def test_first_103_picks_earliest_in_window():
    rows = [
        _filing("10-K", "2023-02-20"),
        _filing("8-K", "2023-06-20", "2.02,9.01"),
        _filing("8-K", "2023-07-05", "1.03,3.03"),   # pétition -> ancre
        _filing("8-K", "2024-01-10", "1.03"),        # confirmation de plan
        _filing("8-K/A", "2014-05-01", "1.03"),      # hors fenêtre
    ]
    assert first_item_103(rows) == ("2023-07-05", "A-2023-07-05")


def test_first_103_none_when_absent():
    assert first_item_103([_filing("8-K", "2023-07-05", "2.02")]) is None


# --- Écran témoin ------------------------------------------------------------

def _control_filings(tenk_years, has_103=False):
    rows = [ _filing("10-K", f"{y}-03-01") for y in tenk_years ]
    if has_103:
        rows.append(_filing("8-K", "2018-06-01", "1.03"))
    return rows


def test_control_screen_healthy_passes():
    ok, reasons = control_screen(
        _control_filings([2014] + list(range(2016, 2026)))
    )
    assert ok and reasons == []


def test_control_screen_rejects_distressed():
    # Jamais de 1.03 admis, même avant la fenêtre.
    ok, reasons = control_screen(_control_filings([2014] + list(range(2016, 2026)), has_103=True))
    assert not ok and "a_déposé_1.03" in reasons
    # Continuité insuffisante.
    ok2, reasons2 = control_screen(_control_filings([2014, 2016, 2018]))
    assert not ok2 and any("continuité" in r for r in reasons2)
    # Pas de 10-K avant 2016 (IPO trop récent pour la fenêtre).
    ok3, reasons3 = control_screen(_control_filings(list(range(2016, 2026))))
    assert not ok3 and "pas_de_10-K_avant_2016" in reasons3


# --- Couverture XBRL ---------------------------------------------------------

def _fake_extract(rows):
    """Remplace loader.extract : rows = [(period_end,)] pour le test."""
    return [{"period_end": pe} for (pe,) in rows]


def test_pre_failure_years_window(monkeypatch):
    facts = {"facts": {"us-gaap": {"x": {}}}}
    rows = [
        ("2015-12-31",),  # 6 ans avant 2021 -> limite basse incluse
        ("2016-12-31",),
        ("2017-12-31",),
        ("2018-12-31",),
        ("2021-03-31",),  # dans l'année de faillite, avant l'ancre -> inclus
        ("2022-12-31",),  # post-pétition -> exclu
        ("2010-12-31",),  # trop ancien -> exclu
    ]
    monkeypatch.setattr(cohort_mod, "extract", lambda cf: _fake_extract(rows))
    years = pre_failure_years(facts, "2021-09-01", span=6)
    assert years == {2015, 2016, 2017, 2018, 2021}
    assert coverage_ok(facts, "2021-09-01") is True
    # 4 exercices seulement -> insuffisant pour une série 5 ans.
    monkeypatch.setattr(cohort_mod, "extract", lambda cf: _fake_extract(rows[:4]))
    assert coverage_ok(facts, "2021-09-01") is False


def test_bbby_real_cache_has_coverage():
    """Invariant réel : le companyfacts de BBBY (faillie de référence)
    passe le gate de couverture sur son ancre réelle (1.03 juillet 2023)."""
    if not CACHE_BBBY.exists():
        pytest.skip("cache BBBY absent : uv run python -m scripts.fetch_phase0")
    facts = json.loads(CACHE_BBBY.read_text(encoding="utf-8"))
    assert coverage_ok(facts, "2023-07-05")
    assert 2019 in pre_failure_years(facts, "2023-07-05")


# --- Échantillonnage ---------------------------------------------------------

def _c(cik, sic):
    return {"cik": cik, "sic": sic}


def test_sample_controls_proportional_and_deterministic():
    cohort = [_c(1, 5211), _c(2, 5211), _c(3, 5211), _c(4, 2911)]  # 3 retail / 1 pétrole
    pool = [_c(10, 2911), _c(11, 2911), _c(12, 5211), _c(13, 5211), _c(14, 5211)]
    picked = sample_controls(pool, cohort, target=4)
    # 3 témoins retail (SIC-2 = 52) + 1 pétrole (29), puis tri par CIK.
    assert [c["cik"] for c in picked] == [10, 12, 13, 14]
    assert sample_controls(pool, cohort, target=4) == picked  # déterministe


def test_sample_controls_fills_shortfall():
    """Bucket pétrole sans témoin : le reliquat comble la cible."""
    cohort = [_c(1, 5211), _c(2, 2911)]
    pool = [_c(10, 5211), _c(11, 5211), _c(12, 5211)]
    picked = sample_controls(pool, cohort, target=3)
    assert [c["cik"] for c in picked] == [10, 11, 12]


# --- Slugs -------------------------------------------------------------------

def test_make_slug_unique_and_safe():
    a = make_slug(320193, "AAPL", "Apple Inc.")
    b = make_slug(886158, None, "Bed Bath & Beyond, Inc.")
    assert a == "aapl_320193"
    assert b == "bedbathbeyond_886158" or b.startswith("bedbathbeyond")
    assert a != b
    for ch in ' <>:"/\\|?*':
        assert ch not in b
