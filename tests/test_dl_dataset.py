# Tests purs du dataset DL : fenetres, etiquettes, normalisation.
from datetime import date

from app.dl.dataset import (
    FEATURE_CONCEPTS,
    HORIZON_DAYS,
    INPUT_DIM,
    MAX_YEARS,
    MIN_YEARS,
    YearPoint,
    build_samples,
    company_year_points,
    vectorize,
)


def _fact(year, concept="total_assets", value=100.0, filed=2020):
    return {
        "period_end": date(year, 12, 31),
        "concept": concept,
        "value": value,
        "filed": date(filed, 3, 1),
        "filed_at": date(filed, 3, 1),
    }


def test_vectorize_ratio_and_missing_flags():
    vec = vectorize({"total_assets": 100.0, "cash": 25.0, "sales": 50.0})
    assert len(vec) == INPUT_DIM == 2 * len(FEATURE_CONCEPTS)
    cash_i = FEATURE_CONCEPTS.index("cash") * 2
    sales_i = FEATURE_CONCEPTS.index("sales") * 2
    missing_i = FEATURE_CONCEPTS.index("inventory") * 2
    assert vec[cash_i] == 0.25 and vec[cash_i + 1] == 0.0
    assert vec[sales_i] == 0.5
    assert vec[missing_i] == 0.0 and vec[missing_i + 1] == 1.0  # flag manquant


def test_vectorize_clips_extremes():
    vec = vectorize({"total_assets": 1.0, "net_income": 100.0, "long_term_debt": -50.0})
    ni = FEATURE_CONCEPTS.index("net_income") * 2
    ltd = FEATURE_CONCEPTS.index("long_term_debt") * 2
    assert vec[ni] == 5.0 and vec[ltd] == -5.0


def test_year_points_last_period_end_wins():
    # Même année : comparatif au 01-01 PUIS solde au 31-12 -> le 31-12 gagne.
    # total_assets sert de dénominateur (pas un feature) : on valide sur cash.
    rows = [
        _fact(2018, "cash", 25.0, filed=2019),
        {**_fact(2018), "period_end": date(2018, 1, 1), "concept": "cash",
         "value": 8.0, "filed_at": date(2019, 3, 1)},
        _fact(2018, "total_assets", 100.0, filed=2019),
    ]
    points = company_year_points(rows)
    assert len(points) == 1
    cash_i = FEATURE_CONCEPTS.index("cash") * 2
    assert points[0].vector[cash_i] == 0.25  # ratio du gagnant (25/100)
    assert points[0].availability == date(2019, 3, 1)


def test_build_samples_windows_and_label():
    points = [
        YearPoint(date(y, 12, 31), date(y + 1, 3, 1), (0.1, 0.0) * 18)
        for y in range(2016, 2022)
    ]
    anchor = date(2021, 6, 15)  # faillite ~6 mois apres l'exercice 2020
    samples = build_samples(points, cik=1, anchor=anchor)
    # Le bilan 2021-12-31 est post-faillite : exclu par conception.
    assert [s.period_end.year for s in samples] == [2018, 2019, 2020]
    # Etiquette = 1 uniquement si 0 <= delta <= 12 mois (ex. 2020: 166 j).
    assert [s.label for s in samples] == [0, 0, 1]
    # Fenetre bornee a MAX_YEARS.
    assert all(len(s.sequence) <= MAX_YEARS for s in samples)
    assert len(samples[-1].sequence) == MAX_YEARS
    # Disponibilite = max de la fenetre.
    assert samples[-1].availability == date(2021, 3, 1)


def test_build_samples_controls_never_labelled_and_horizon_edge():
    points = [
        YearPoint(date(y, 12, 31), date(y + 1, 3, 1), (0.0, 1.0) * 18)
        for y in range(2016, 2020)
    ]
    assert all(s.label == 0 for s in build_samples(points, 2, None))
    # Borne exacte : delta == HORIZON_DAYS -> 1 ; delta == HORIZON_DAYS+1 -> 0.
    p = points + [YearPoint(date(2020, 12, 31), date(2021, 3, 1), (0.0, 1.0) * 18)]
    a_in = date(2020, 12, 31)  # delta 0
    a_edge = date(2020, 12, 31).fromordinal(date(2020, 12, 31).toordinal() + HORIZON_DAYS)
    a_out = date(2020, 12, 31).fromordinal(date(2020, 12, 31).toordinal() + HORIZON_DAYS + 1)
    assert build_samples(p, 3, a_in)[-1].label == 1
    assert build_samples(p, 3, a_edge)[-1].label == 1
    assert build_samples(p, 3, a_out)[-1].label == 0
