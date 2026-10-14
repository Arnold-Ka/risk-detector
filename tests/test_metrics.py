# Tests de la logique de métriques (arithmétique calendaire + snapshots).
from datetime import date

from app.backtest.metrics import (
    Snapshot,
    add_months,
    build_snapshots,
    exceeds,
    pick_snapshot,
)


def _comp(sev, pe, filed):
    return {"signal_type": "altman", "period_end": pe, "severity": sev, "filed_at": filed}


def _comp_no_filing(sev, pe):
    # Composante sans dépôt relier (jamais vu en prod, cas limite testé).
    return {"signal_type": "piotroski", "period_end": pe, "severity": sev, "filed_at": None}


def _compo(sev, pe):
    return {"signal_type": "composite", "period_end": pe, "severity": sev, "filed_at": None}


def test_add_months_clamp_and_wrap():
    assert add_months(date(2023, 4, 23), -6) == date(2022, 10, 23)
    assert add_months(date(2023, 3, 31), -1) == date(2023, 2, 28)  # clamp février
    assert add_months(date(2023, 1, 15), -1) == date(2022, 12, 15)  # wrap année
    assert add_months(date(2023, 6, 10), 0) == date(2023, 6, 10)


def test_build_snapshots_takes_max_filed_at():
    # L'exercice n'est connu qu'au dépôt de sa dernière composante.
    rows = [
        _compo("modéré", date(2022, 12, 31)),
        _comp("saine", date(2022, 12, 31), date(2023, 3, 1)),
        _comp("défaillance", date(2022, 12, 31), date(2023, 6, 14)),
        _compo("faible", date(2021, 12, 31)),
        _comp("saine", date(2021, 12, 31), date(2022, 3, 5)),
    ]
    snaps = build_snapshots(rows)
    assert [s.period_end for s in snaps] == [date(2021, 12, 31), date(2022, 12, 31)]
    assert snaps[1].available_at == date(2023, 6, 14)
    assert snaps[1].has_defaillance and not snaps[0].has_defaillance


def test_build_snapshots_skips_undatable_composite():
    # Composantes toutes non datées -> snapshot inexploitable, ignoré.
    rows = [_compo("critique", date(2022, 12, 31)), _comp_no_filing("défaillance", date(2022, 12, 31))]
    assert build_snapshots(rows) == []


def test_pick_snapshot_latest_available_even_if_not_monotonic():
    # available_at NON monotone : l'exercice 2022 est daté 2024
    # (restitution tardive) alors que l'exercice 2023 est daté 2024 aussi ;
    # au cutoff 2024-01, seul 2021 est disponible, PAS de 2022/2023.
    snaps = [
        Snapshot(date(2021, 12, 31), date(2022, 3, 1), "faible", False),
        Snapshot(date(2022, 12, 31), date(2024, 6, 1), "critique", True),
        Snapshot(date(2023, 12, 31), date(2024, 3, 1), "modéré", False),
    ]
    assert pick_snapshot(snaps, date(2024, 1, 1)).period_end == date(2021, 12, 31)
    # cutoff post-2024-03 : le 2023 (bien daté) est pris de préférence
    # au 2022 même plus récent en période car daté plus tard (2024-06).
    assert pick_snapshot(snaps, date(2024, 4, 1)).period_end == date(2023, 12, 31)
    assert pick_snapshot(snaps, date(2024, 7, 1)).period_end == date(2023, 12, 31)
    assert pick_snapshot(snaps, date(2021, 1, 1)) is None


def test_exceeds_rules():
    s = Snapshot(date(2022, 12, 31), date(2023, 3, 1), "élevé", False)
    assert exceeds(s, "modéré") and exceeds(s, "élevé")
    assert not exceeds(s, "critique") and not exceeds(s, "defaillance")
    d = Snapshot(date(2022, 12, 31), date(2023, 3, 1), "faible", True)
    assert not exceeds(d, "modéré") and exceeds(d, "defaillance")
