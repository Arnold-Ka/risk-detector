"""Tests de l'attribution SHAP des scores LSTM (phase 2 « explication »).

Pur (pas de BDD) : forme et déterminisme des attributions, ordre des
noms de features, tri des top-k, et intégration sample_signals ->
details.attribution (dernier exercice seul).
"""

import math
from datetime import date

import torch

from app.dl.attribution import feature_names, explain, top_contributors
from app.dl.dataset import EVENT_FEATURES, INPUT_DIM, MIN_YEARS, Sample
from app.dl.infer import sample_signals
from app.dl.model import LstmScorer

META = {"model": "lstm", "input_dim": INPUT_DIM, "threshold": 0.611,
        "trained_at": "2026-10-14"}


def _rows(years):
    """Faits synthétiques DL : un total_assets datable par exercice."""
    return [
        {
            "period_end": date(year, 12, 31),
            "concept": "total_assets",
            "value": 1000.0 + i,
            "filed_at": date(year + 1, 2, 15),
            "filing_id": f"f-{year}",
        }
        for i, year in enumerate(years)
    ]


def _sample(n_years=MIN_YEARS):
    vec = tuple(0.5 for _ in range(INPUT_DIM))
    return Sample(
        cik=1,
        period_end=date(2023, 12, 31),
        availability=date(2024, 2, 15),
        sequence=tuple(vec for _ in range(n_years)),
        label=0,
    )


def test_feature_names_match_vector_order():
    """Noms alignés sur dataset.vectorize : interleaving ratio/flag + events."""
    names = feature_names()
    assert len(names) == INPUT_DIM
    assert names[:2] == ["cash_ratio", "cash_missing"]
    assert names[-len(EVENT_FEATURES):] == list(EVENT_FEATURES)
    i = names.index("sales_ratio")
    assert names[i + 1] == "sales_missing"


def test_explain_shape_and_determinism():
    """Attributions = une par feature, finies, reproductibles (seed fixe)."""
    model = LstmScorer(INPUT_DIM)
    first = explain(model, _sample())
    assert [name for name, _ in first] == feature_names()
    assert all(math.isfinite(value) for _, value in first)
    # Même modèle + même seed -> mêmes interpolations SHAP -> mêmes valeurs.
    second = explain(model, _sample())
    assert [round(v, 8) for _, v in first] == [round(v, 8) for _, v in second]


def test_explain_sums_to_logit_gap():
    """Additivité : somme des attributions ≈ logit(x) − logit(zéro).

    Garde-fou contre le piège pack_padded_sequence (longueurs de taille 1
    sur un batch SHAP -> seule la première ligne évaluée, attributions
    divisées par N : mesuré ~50× trop petites avant correction).
    """
    torch.manual_seed(0)  # poids du modèle déterministes
    model = LstmScorer(INPUT_DIM)
    model.eval()
    sample = _sample(n_years=5)

    x = torch.tensor(sample.sequence).unsqueeze(0)  # (1, 5, D)
    bg = torch.zeros_like(x)
    lengths = torch.tensor([5])
    with torch.no_grad():
        logit_x = float(model(x, lengths))
        logit_bg = float(model(bg, lengths))

    total = sum(value for _, value in explain(model, sample))
    # GradientExplainer = Monte-Carlo sur nsamples=200 interpolations :
    # écart mesuré ≤ 0.0014 sur 3 configurations, tolérance large ici.
    assert abs(total - (logit_x - logit_bg)) < 0.05


def test_top_contributors_orders_by_absolute_value():
    attr = [("a", 0.1), ("b", -0.9), ("c", 0.5), ("d", 0.05)]
    top = top_contributors(attr, 2)
    assert [name for name, _ in top] == ["b", "c"]


def test_sample_signals_attribution_on_latest_only():
    """details.attribution sur le DERNIER signal seul (top-k triés)."""
    model = LstmScorer(INPUT_DIM)
    results = sample_signals(_rows(range(2020, 2024)), [], 1, model, META)
    assert len(results) == 2  # fenêtres 2022 et 2023 (MIN_YEARS=3)

    latest = results[-1]
    assert latest.details["attribution_method"] == "shap_gradient"
    attr = latest.details["attribution"]
    assert 0 < len(attr) <= 8
    # Tri par valeur absolue décroissante + noms de features connus.
    abs_vals = [abs(item["value"]) for item in attr]
    assert abs_vals == sorted(abs_vals, reverse=True)
    known = set(feature_names())
    assert all(item["feature"] in known for item in attr)
    # L'historique reste léger : pas d'attribution sur les exercices passés.
    assert "attribution" not in results[0].details
