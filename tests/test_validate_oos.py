"""Découpage temporel de la validation hors échantillon (fonctions pures)."""

from datetime import date

from app.backtest.metrics import Snapshot
from scripts.validate_oos import split_anchors, window_controls


def _snap(year: int) -> Snapshot:
    return Snapshot(date(year, 12, 31), date(year + 1, 3, 1), "faible", False)


def test_split_anchors_keeps_split_year_in_training():
    anchors = {1: date(2020, 12, 31), 2: date(2021, 1, 1), 3: date(2016, 5, 1)}

    train, test = split_anchors(anchors, 2020)

    assert set(train) == {1, 3}
    assert set(test) == {2}


def test_window_controls_filters_only_controls():
    snaps = {10: [_snap(2019), _snap(2022)], 20: [_snap(2019), _snap(2022)]}

    windowed = window_controls(snaps, controls={10}, keep=lambda pe: pe.year > 2020)

    # Témoin : seuls les exercices de la fenêtre restent.
    assert [s.period_end.year for s in windowed[10]] == [2022]
    # Faillite : snapshots intacts (pick_recent filtre déjà par l'ancre).
    assert [s.period_end.year for s in windowed[20]] == [2019, 2022]
    # L'entrée n'est pas modifiée.
    assert len(snaps[10]) == 2
