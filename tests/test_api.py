"""Tests de l'API (sans serveur).

FastAPI fournit TestClient (basé sur httpx) : il appelle l'application
directement en mémoire — pas de port, pas d'uvicorn. Les endpoints
`/companies/*` touchent PostgreSQL : ces tests sont skippés si la base est
éteinte (docker compose up -d --wait) et attendent un recalcul du job
nocturne si la table `signals` est vide.

Commande :
    uv run pytest tests/test_api.py -v
"""

from fastapi.testclient import TestClient

from app.api.main import app
from app.db.repo import get_conn

client = TestClient(app)  # client unique réutilisé par les tests du fichier


def _db_available() -> bool:
    """Vrai si Postgres répond vraiment — sinon pytest.skip, pas d'échec.

    Attention psycopg : connect() est paresseux (la socket n'est ouverte
    qu'à la première requête) — il faut EXÉCUTER quelque chose pour que
    « base éteinte » soit détecté ici et non au milieu d'un endpoint.
    """
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
        return True
    except Exception:
        return False


def test_health_returns_ok():
    """/health est la sonde utilisée par docker --wait et le frontend."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_company_unknown_cik_returns_404():
    """CIK inconnu -> 404 (pas un objet vide qui ressemblerait à « sain »)."""
    if not _db_available():
        import pytest

        pytest.skip("PostgreSQL indisponible")
    resp = client.get("/companies/9999999")
    assert resp.status_code == 404


def test_company_card_returns_latest_signals():
    """Fiche Apple : identité + un signal par type (dernier exercice).

    Prérequis : données ingérées + job nocturne exécuté — sinon skip avec
    la commande à lancer (le test ne PEUT pas être vert sans ces étapes,
    c'est le but : il valide le câblage bout en bout).
    """
    import pytest

    if not _db_available():
        pytest.skip("PostgreSQL indisponible")
    resp = client.get("/companies/320193")
    if resp.status_code == 404:
        pytest.skip("données non ingérées — uv run python -m scripts.load_postgres")
    if not resp.json().get("signals"):
        pytest.skip("signaux non calculés — uv run python -m app.jobs.nightly")

    body = resp.json()
    assert body["cik"] == 320193
    assert body["name"]
    types = [s["signal_type"] for s in body["signals"]]
    assert len(types) == len(set(types)), "un seul signal par type attendu"
    for signal in body["signals"]:
        assert signal["signal_type"]
        assert signal["severity"]
        assert len(signal["period_end"]) == 10
        assert "details" in signal


def test_signals_history_is_ordered():
    """Historique complet : trié par exercice, lignes avec sévérité."""
    import pytest

    if not _db_available():
        pytest.skip("PostgreSQL indisponible")
    resp = client.get("/companies/320193/signals")
    if resp.status_code == 404:
        pytest.skip("données non ingérées")
    signals = resp.json()["signals"]
    if not signals:
        pytest.skip("signaux non calculés — uv run python -m app.jobs.nightly")
    ends = [s["period_end"] for s in signals]
    assert ends == sorted(ends)
    assert len(ends) >= 10  # au moins une décennie d'historique
