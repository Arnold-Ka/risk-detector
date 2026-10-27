"""Tests de la santé des données (règles pures + /health/data sans vraie base)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.health import freshness, run_problems

client = TestClient(api_main.app)
TODAY = date(2026, 10, 26)


def test_healthy_run_has_no_problem():
    # 10 % de calcul raté et 40 % d'échecs SEC : sous les deux seuils.
    assert run_problems(total=100, compute_errors=10, sec_errors=40) == []


def test_run_problems_flags_each_threshold():
    problems = run_problems(total=100, compute_errors=21, sec_errors=51)

    assert len(problems) == 2
    assert problems[0].startswith("21/100 entreprises en erreur de calcul")
    assert "échecs SEC" in problems[1]


def test_empty_run_is_a_problem_not_a_silent_success():
    assert run_problems(total=0, compute_errors=0, sec_errors=0) == [
        "aucune entreprise traitée"
    ]


@pytest.mark.parametrize(
    ("last", "status", "age"),
    [
        (TODAY, "ok", 0),
        (date(2026, 10, 25), "ok", 1),  # nightly de la veille : normal
        (date(2026, 10, 24), "stale", 2),  # au moins une nuit manquée
    ],
)
def test_freshness_tolerates_one_day(last, status, age):
    result = freshness(last, TODAY)

    assert (result["status"], result["age_days"]) == (status, age)
    assert result["last_computed_at"] == last.isoformat()


def test_freshness_of_empty_database():
    assert freshness(None, TODAY) == {
        "status": "empty",
        "last_computed_at": None,
        "age_days": None,
    }


class _FakeConn:
    def close(self):
        pass


def _serve(monkeypatch, snapshot):
    monkeypatch.setattr(api_main, "get_conn", lambda: _FakeConn())
    monkeypatch.setattr(api_main, "data_freshness", lambda conn: snapshot)


def test_health_data_is_200_when_fresh(monkeypatch):
    _serve(monkeypatch, {"last_computed": date.today(), "companies": 3,
                         "companies_with_level": 2})

    resp = client.get("/health/data")

    assert resp.status_code == 200
    assert resp.json() | {"last_computed_at": None} == {
        "status": "ok", "age_days": 0, "last_computed_at": None,
        "companies": 3, "companies_with_level": 2,
    }


@pytest.mark.parametrize(
    ("last", "status"), [(date(2000, 1, 1), "stale"), (None, "empty")]
)
def test_health_data_is_503_when_stale_or_empty(monkeypatch, last, status):
    _serve(monkeypatch, {"last_computed": last, "companies": 3,
                         "companies_with_level": 0})

    resp = client.get("/health/data")

    assert resp.status_code == 503
    assert resp.json()["status"] == status


def test_health_data_is_503_when_database_is_down(monkeypatch):
    def _down():
        raise OSError("connexion refusée")

    monkeypatch.setattr(api_main, "get_conn", _down)

    resp = client.get("/health/data")

    assert resp.status_code == 503
    assert resp.json() == {"status": "db_unavailable", "error": "OSError"}
