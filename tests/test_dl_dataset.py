# Tests purs du dataset DL : fenetres, etiquettes, normalisation.
from datetime import date

from app.dl.dataset import (
    EVENT_FEATURES,
    FEATURE_CONCEPTS,
    HORIZON_DAYS,
    INPUT_DIM,
    MAX_YEARS,
    MIN_YEARS,
    YearPoint,
    build_samples,
    company_year_points,
    event_features,
    vectorize,
)

# Index de depart des features d'evenements dans un vecteur annuel.
EV0 = 2 * len(FEATURE_CONCEPTS)


def _fact(year, concept="total_assets", value=100.0, filed=2020):
    return {
        "period_end": date(year, 12, 31),
        "concept": concept,
        "value": value,
        "filed": date(filed, 3, 1),
        "filed_at": date(filed, 3, 1),
    }


def _event(
    form="8-K",
    items="",
    filed_at="2020-06-15",
    report_date=None,
    filing_id="f-1",
):
    """Depot 8-K/NT, meme forme que repo.fetch_event_rows (ISO str).

    filing_id est requis : les evaluateurs classiques y accedent
    (events.py:105/135) — le vecteur DL les appelle tels quels.
    """
    return {
        "accession": f"0001-{filed_at[:4]}-001",
        "form": form,
        "filed_at": filed_at,
        "items": items,
        "report_date": report_date,
        "filing_id": filing_id,
    }


def test_vectorize_ratio_and_missing_flags():
    vec = vectorize({"total_assets": 100.0, "cash": 25.0, "sales": 50.0})
    # vectorize ne produit que la partie financiere (36 dims) ;
    # les 4 features d'evenements sont ajoutees par company_year_points.
    assert len(vec) == 2 * len(FEATURE_CONCEPTS)
    assert INPUT_DIM == len(vec) + len(EVENT_FEATURES)
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


def test_event_features_missing_flag_when_no_submissions():
    # Zero depot = submissions jamais chargees -> (0,0,0) + flag 1, jamais
    # un faux « 0 sain » (un depositeur coté en depose toujours).
    assert event_features([], date(2020, 12, 31), missing=True) == (
        0.0, 0.0, 0.0, 1.0,
    )
    # Données présentes mais aucun événement sur l'exercice -> flag 0.
    assert event_features([], date(2020, 12, 31), missing=False) == (
        0.0, 0.0, 0.0, 0.0,
    )


def test_event_features_counts_and_worst_rank():
    # Moteur classique partagé : 1.03 = rang 3 (défaillance) -> worst 3/3,
    # 2.04 = rang 3 aussi, 5.02 = rang 2 ; un 2.02 ordinaire n'est PAS critique.
    events = [
        _event(items="1.03", filed_at="2020-03-01", filing_id="a"),
        _event(items="2.04", filed_at="2020-06-01", filing_id="b"),
        _event(items="5.02", filed_at="2020-09-01", filing_id="c"),
        _event(items="2.02", filed_at="2020-10-01", filing_id="d"),  # ignoré
    ]
    n_def, n_vig, nt, missing = event_features(
        events, date(2020, 12, 31), missing=False
    )
    assert n_def == 2.0  # 1.03 + 2.04 (rang 3)
    assert n_vig == 1.0  # 5.02 seul (rang 2)
    assert nt == 0.0
    assert missing == 0.0


def test_event_features_rank2_only_counts_as_vigilance():
    # Une seule 5.02 (départ dirigeant) -> vigilance, PAS défaillance :
    # la décomposition évite la saturation du « rang max » v1 (80 % des
    # exercices à 0.667 aplatissaient la feature).
    n_def, n_vig, _, _ = event_features(
        [_event(items="5.02")], date(2020, 12, 31), missing=False
    )
    assert n_def == 0.0
    assert n_vig == 1.0
    # Un 8-K mixte 5.02+1.03 compte en défaillance (rang max = 3), pas en vigilance.
    n_def, n_vig, _, _ = event_features(
        [_event(items="5.02,1.03")], date(2020, 12, 31), missing=False
    )
    assert n_def == 1.0 and n_vig == 0.0
    # Clip : 8 dépôts de rang 3 -> plafonné à COUNT_CLIP (5.0).
    rafale = [_event(items="1.03", filing_id=f"f{i}") for i in range(8)]
    crit_clip, _, _, _ = event_features(rafale, date(2020, 12, 31), False)
    assert crit_clip == 5.0


def test_event_features_splits_nt_from_8k():
    # late_filing compte les form NT*, pas les 8-K (même découpage que compute.py).
    events = [
        _event(form="NT 10-K", filed_at="2021-03-15"),
        _event(form="NT 10-Q", filed_at="2021-05-15"),
        _event(form="8-K", items="1.03"),
    ]
    n_def, _, nt, _ = event_features(events, date(2020, 12, 31), missing=False)
    assert n_def == 1.0  # seul l'8-K 1.03 est critique
    assert nt == 2.0  # deux NT -> défaillance côté signal, comptés pour le LSTM


def test_company_year_points_extends_availability_with_event():
    # Un NT déposé 3 mois après le bilan repousse la disponibilité de
    # l'exercice (anti-fuite : on ne connaît le retard qu'à son dépôt).
    rows = [_fact(2020, "total_assets", 100.0, filed=2021)]
    events = [
        _event(form="NT 10-K", filed_at="2021-03-20", report_date="2020-12-31")
    ]
    points = company_year_points(rows, events)
    assert len(points) == 1
    assert points[0].availability == date(2021, 3, 20)  # > filed des faits
    # L'événement est bien rattaché à l'exercice 2020 (report_date).
    ev0 = 2 * len(FEATURE_CONCEPTS)
    assert points[0].vector[ev0 + 2] == 1.0  # late_filing = 1
    assert points[0].vector[ev0 + 3] == 0.0  # événements présents


def test_company_year_points_assigns_events_by_anchor_not_filed_year():
    # Un 8-K déposé en 2021 avec report_date 2020 se rattache à l'exercice
    # 2020 (ancre = report_date), comme les signaux classiques.
    rows = [
        _fact(2020, "total_assets", 100.0, filed=2021),
        _fact(2021, "total_assets", 110.0, filed=2022),
    ]
    events = [
        _event(items="1.03", filed_at="2021-02-10", report_date="2020-12-31")
    ]
    points = company_year_points(rows, events)
    assert len(points) == 2
    ev0 = 2 * len(FEATURE_CONCEPTS)
    assert points[0].vector[ev0] == 1.0  # 2020 porte l'8-K
    assert points[1].vector[ev0] == 0.0  # 2021 non


def test_company_year_points_missing_events_flag_propagates():
    # Aucun dépôt -> flag events_missing = 1 sur CHAQUE vecteur.
    rows = [
        _fact(2019, "total_assets", 90.0, filed=2020),
        _fact(2020, "total_assets", 100.0, filed=2021),
    ]
    points = company_year_points(rows, events=[])
    ev0 = 2 * len(FEATURE_CONCEPTS)
    assert all(p.vector[ev0 + 3] == 1.0 for p in points)
    assert all(p.vector[ev0:ev0 + 3] == (0.0, 0.0, 0.0) for p in points)
    # None se comporte comme [] (paramètre optionnel non fourni).
    points_none = company_year_points(rows)
    assert all(p.vector[ev0 + 3] == 1.0 for p in points_none)
