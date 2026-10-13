"""Tests des signaux d'événements (8-K critiques, dépôts NT tardifs).

Cible : app/signals/events.py — mapping exercice + deux évaluateurs, en
fixtures synthétiques (toujours) puis intégration sur le trio réel via le
cache submissions (si présent).

Commande :
    uv run pytest tests/test_events.py -v
"""

from pathlib import Path

import pytest

from app.edgar.client import EdgarClient
from app.edgar.submissions import load_filing_rows
from app.signals.events import (
    assign_to_years,
    evaluate_critical_8k,
    evaluate_late_filing,
)

CACHE_DIR = Path("data/cache")


def _event(form="8-K", items="", filed_at="2023-06-15",
            report_date=None, filing_id="f1", accession="0001-23-456"):
    return {
        "form": form,
        "items": items,
        "filed_at": filed_at,
        "report_date": report_date,
        "filing_id": filing_id,
        "accession": accession,
    }


# --- Mapping événement -> exercice ------------------------------------------

def test_assign_uses_report_date_when_present():
    """NT déposé en mars 2023 pour l'exercice clos fin 2022 : report_date
    le rattache au BON exercice (filed_at seule le pousserait à 2023)."""
    pes = ["2021-12-31", "2022-12-31", "2023-12-31"]
    nt = _event(form="NT 10-K", filed_at="2023-03-05",
                report_date="2022-12-31")
    assigned, dropped = assign_to_years([nt], pes)
    assert assigned == {2022: [nt]}
    assert dropped == []


def test_assign_falls_back_to_filing_date():
    pes = ["2022-12-31", "2023-12-31"]
    k8 = _event(filed_at="2023-06-15")  # pas de report_date
    assigned, dropped = assign_to_years([k8], pes)
    assert assigned == {2023: [k8]}
    assert dropped == []


def test_assign_drops_events_after_last_balance():
    """Événement postérieur au dernier bilan : ignoré (pas d'exercice),
    jamais rattaché à un exercice fictif."""
    pes = ["2022-12-31"]
    k8 = _event(filed_at="2023-07-01")
    assigned, dropped = assign_to_years([k8], pes)
    assert assigned == {}
    assert dropped == [k8]


# --- late_filing ------------------------------------------------------------

def test_late_filing_ok_when_no_nt():
    res = evaluate_late_filing([], "2023-12-31", fallback_filing_id="anchor")
    assert res.value == 0.0
    assert res.severity == "saine"
    assert res.filing_id == "anchor"  # ancre de l'exercice, jamais NULL


def test_late_filing_one_nt_is_vigilance():
    nt = _event(form="NT 10-Q", filing_id="nt-1")
    res = evaluate_late_filing([nt], "2023-12-31", "anchor")
    assert res.value == 1.0
    assert res.severity == "vigilance"
    assert res.filing_id == "nt-1"  # tracé sur le dépôt fautive
    assert res.details["nt_forms"] == ["NT 10-Q"]


def test_late_filing_two_or_more_is_alert():
    nts = [_event(form="NT 10-Q", filing_id="a"), _event(form="NT 10-K", filing_id="b")]
    res = evaluate_late_filing(nts, "2023-12-31", "anchor")
    assert res.value == 2.0
    assert res.severity == "défaillance"


# --- critical_8k ------------------------------------------------------------

def test_critical_8k_no_flagged_items():
    """8-K ordinaires (résultats 2.02, annexes 9.01) : saine, valeur 0."""
    events = [_event(items="2.02,9.01", filing_id="k1"),
              _event(items="5.07,9.01", filing_id="k2")]
    res = evaluate_critical_8k(events, "2023-12-31", "anchor")
    assert res.value == 0.0
    assert res.severity == "saine"
    assert res.filing_id == "anchor"
    assert res.details["total_8k"] == 2


def test_critical_8k_bankruptcy_item_is_alert():
    """Item 1.03 (mise sous protection judiciaire) = défaillance, tracé
    sur le 8-K porteur."""
    events = [_event(items="2.02,9.01", filing_id="k1"),
              _event(items="1.03", filing_id="k-bankrupt", accession="0001-23-999")]
    res = evaluate_critical_8k(events, "2023-12-31", "anchor")
    assert res.value == 1.0
    assert res.severity == "défaillance"
    assert res.filing_id == "k-bankrupt"
    assert res.details["worst_item"] == "1.03"


def test_critical_8k_auditor_change_is_vigilance():
    """Item 4.01 (changement d'auditeur) seul : vigilance."""
    events = [_event(items="4.01", filing_id="k-audit")]
    res = evaluate_critical_8k(events, "2023-12-31", "anchor")
    assert res.severity == "vigilance"
    assert res.value == 1.0


def test_critical_8k_worst_item_drives_severity_and_trace():
    """Mélange 4.01 (vigilance) + 4.02 (défaillance) : le plus grave décide
    de la sévérité ET du dépôt tracé."""
    events = [
        _event(items="4.01", filing_id="k-mild", accession="0001-23-1"),
        _event(items="4.02,9.01", filing_id="k-severe", accession="0001-23-2"),
    ]
    res = evaluate_critical_8k(events, "2023-12-31", "anchor")
    assert res.severity == "défaillance"
    assert res.filing_id == "k-severe"
    assert res.value == 2.0
    assert res.details["worst_item"] == "4.02"


# --- Intégration trio réel (cache submissions) ------------------------------

def _load_events(cik: int) -> list[dict]:
    """Événements depuis le cache submissions (aucun réseau)."""
    try:
        rows = load_filing_rows(EdgarClient(), cik)
    except Exception as exc:  # cache absent
        pytest.skip(f"cache submissions absent : uv run python -m scripts.fetch_submissions ({exc})")
    return [r for r in rows if r["form"].startswith(("8-K", "NT"))]


def test_trio_event_profiles():
    """Profils attendus :
      - BBBY : dépôts NT tardifs + 8-K de faillie (1.03, juillet 2023) ;
      - AMC : plusieurs 8-K critiques autour de la crise 2020-2021 ;
      - tout signal émis reste dans le vocabulaire produit.
    """
    bbby = _load_events(886158)
    nt = [e for e in bbby if e["form"].startswith("NT")]
    k8_bankruptcy = [
        e for e in bbby
        if "1.03" in (e["items"] or "") and e["filed_at"] >= "2023-01-01"
    ]
    # BBBY a effectivement déposé NT et fait faillite en juillet 2023.
    assert nt, "BBBY devrait avoir des dépôts NT (retards) dans son historique"
    assert k8_bankruptcy, "BBBY devrait avoir un 8-K item 1.03 (Chapter 11)"

    amc = _load_events(1411579)
    critical = [
        e for e in amc
        if any(it in (e["items"] or "")
               for it in ("1.03", "2.04", "4.02", "4.01", "5.02"))
    ]
    assert critical, "AMC devrait avoir au moins un 8-K critique (crise 2020+)"
    for e in nt + critical:
        assert e["filed_at"] and e["accession"]
