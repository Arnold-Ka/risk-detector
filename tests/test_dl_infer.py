"""Tests de l'inférence de production du signal LSTM (phase 2).

Pur : aucune BDD, aucun réseau, aucun entraînement — uniquement l'artefact
(save/load), les bandes de sévérité, la construction des échantillons
(traçabilité + features événementielles) et les SignalResult finaux.
L'intégration postgres (filing_id NOT NULL, counts déterministes) est
couverte par tests/test_nightly.py qui exécute main(refresh=False).
"""

from datetime import date

import pytest

from app.dl.dataset import EVENT_FEATURES, INPUT_DIM, MAX_YEARS, MIN_YEARS, Sample
from app.dl.infer import (
    META_NAME,
    WEIGHTS_NAME,
    build_signal,
    company_samples,
    load_artifact,
    sample_signals,
    save_artifact,
    severity_for,
)
from app.dl.model import LstmScorer, predict

META = {"model": "lstm", "input_dim": INPUT_DIM, "threshold": 0.611,
        "trained_at": "2026-10-14"}


def _rows(years, filing_ids=None, filed_at=None):
    """Faits synthétiques DL : un total_assets datable par exercice.

    filing_ids : dict {année: filing_id} (défaut f-<année>) ;
    filed_at : dict {année: date de dépôt} (défaut ~2 mois après le bilan).
    """
    rows = []
    for i, year in enumerate(years):
        rows.append(
            {
                "period_end": date(year, 12, 31),
                "concept": "total_assets",
                "value": 1000.0 + i,
                "filed_at": (filed_at or {}).get(year, date(year + 1, 2, 15)),
                "filing_id": (filing_ids or {}).get(year, f"f-{year}"),
            }
        )
    return rows


def test_severity_bands_calibrated_on_threshold():
    """Bandes : >= seuil défaillance, >= seuil/2 vigilance, sinon saine."""
    assert severity_for(0.62, 0.60) == "défaillance"
    assert severity_for(0.60, 0.60) == "défaillance"  # seuil inclus
    assert severity_for(0.31, 0.60) == "vigilance"
    assert severity_for(0.30, 0.60) == "vigilance"  # seuil/2 inclus
    assert severity_for(0.299, 0.60) == "saine"


def test_save_load_roundtrip(tmp_path):
    """L'artefact écrit par train_lstm se recharge à l'identique."""
    model = LstmScorer(input_dim=INPUT_DIM)
    weights = save_artifact(model, META, tmp_path)
    assert weights.name == WEIGHTS_NAME
    assert (tmp_path / META_NAME).is_file()

    loaded = load_artifact(tmp_path)
    assert loaded is not None
    model2, meta2 = loaded
    assert meta2["threshold"] == pytest.approx(0.611)

    # Mêmes poids -> mêmes prédictions (indépendance de l'ordre de chargement).
    samples = company_samples(_rows(range(2019, 2024)), [], cik=320193)
    assert samples and samples[-1].period_end == date(2023, 12, 31)
    assert predict(model, samples) == pytest.approx(predict(model2, samples))


def test_load_missing_and_desynced_returns_none(tmp_path):
    """Dossier vide -> None ; meta.input_dim != code -> None (dérive)."""
    assert load_artifact(tmp_path) is None

    stale = LstmScorer(input_dim=INPUT_DIM + 1)
    save_artifact(
        stale, {"model": "lstm", "input_dim": INPUT_DIM + 1, "threshold": 0.5},
        tmp_path,
    )
    assert load_artifact(tmp_path) is None  # artefact désynchronisé ignoré


def test_company_samples_strict_none():
    """< MIN_YEARS exercices datables, ou zéro point -> pas d'échantillon."""
    assert company_samples([], [], cik=1) == []
    assert company_samples(_rows([2021, 2022]), [], cik=1) == []
    # Points jamais datables : company_year_points les jette -> strict-None.
    undatable = _rows([2019, 2020, 2021])
    for r in undatable:
        r["filed_at"] = None
    assert company_samples(undatable, [], cik=1) == []


def test_sample_signals_full_history_and_freshest_filing():
    """Un signal par fenêtre (historique) + filing_id du vintage récent."""
    rows = _rows(range(2019, 2024))  # 5 exercices -> fenêtres 2021-2023
    # Restauration du dernier bilan : second fait, dépôt plus récent.
    rows.append(
        {
            "period_end": date(2023, 12, 31),
            "concept": "cash",
            "value": 55.0,
            "filed_at": date(2024, 5, 1),  # après le 10-K initial
            "filing_id": "f-2023-restated",
        }
    )
    model = LstmScorer(input_dim=INPUT_DIM)
    results = sample_signals(rows, [], cik=320193, model=model, meta=META)

    # 3 échantillons (points 2021, 2022, 2023 — MIN_YEARS=3 requis) :
    # l'historique est complet, pas seulement le dernier exercice.
    assert [r.period_end for r in results] == [
        "2021-12-31", "2022-12-31", "2023-12-31",
    ]
    assert results[-1].filing_id == "f-2023-restated"  # dépôt le + récent
    assert results[-2].filing_id == "f-2022"
    # Fenêtre pleine sur le dernier exercice (MAX_YEARS) + disponibilité.
    assert results[-1].details["window_years"] == MAX_YEARS
    assert results[-1].details["availability"] == "2024-05-01"
    # Chaque signal est traçable et typé (contrat test_nightly).
    assert all(r.signal_type == "lstm" and r.filing_id for r in results)


def test_sample_signals_desynced_vector_returns_none():
    """meta.input_dim != taille des vecteurs -> [] (dérive, pas de crash)."""
    model = LstmScorer(input_dim=INPUT_DIM)
    bad = {**META, "input_dim": INPUT_DIM + 1}
    assert sample_signals(_rows(range(2019, 2024)), [], 1, model, bad) == []


def test_sample_signals_event_features_v21():
    """Les 4 features événementielles alimentent le vecteur (v2.1)."""
    rows = _rows(range(2020, 2024))
    events = [
        {
            "filing_id": "e1",
            "form": "8-K",
            "filed_at": "2023-11-25",
            "items": "1.03",  # rang 3 -> critical_defaillance
            "report_date": "2023-11-20",
            "accession": "a1",
        }
    ]
    samples = company_samples(rows, events, cik=886158)
    assert samples, "fenêtre attendue"
    assert len(EVENT_FEATURES) == 4
    # Vecteur du dernier exercice : les 4 dernières entrées = features
    # d'événements (critical_defaillance=1, vigilance=0, NT=0, missing=0).
    assert samples[-1].sequence[-1][-4:] == (1.0, 0.0, 0.0, 0.0)


def test_build_signal_result_fields():
    """SignalResult `lstm` : type, période, bandes, details auditables."""
    sample = Sample(
        cik=320193,
        period_end=date(2023, 12, 31),
        availability=date(2024, 2, 15),
        sequence=tuple((0.0,) * INPUT_DIM for _ in range(MIN_YEARS)),
        label=0,
    )
    res = build_signal(0.75, sample, "f-filing-1", META)
    assert res.signal_type == "lstm"
    assert res.period_end == "2023-12-31"
    assert res.value == pytest.approx(0.75)
    assert res.severity == "défaillance"  # 0.75 >= 0.611
    assert res.filing_id == "f-filing-1"
    assert res.details["probability"] == pytest.approx(0.75)
    assert res.details["threshold"] == pytest.approx(0.611)
    assert res.details["window_years"] == MIN_YEARS
    assert res.details["availability"] == "2024-02-15"
    # Bande intermédiaire sur le même échantillon.
    res2 = build_signal(0.35, sample, "f-filing-1", META)
    assert res2.severity == "vigilance"  # 0.611/2 <= 0.35 < 0.611
