"""Tests de l'API (sans serveur).

FastAPI fournit TestClient (basé sur httpx) : il appelle l'application
directement en mémoire — pas de port, pas d'uvicorn, pas de base de
données. Parfait pour vérifier le câblage des routes.

Commande :
    uv run pytest tests/test_api.py -v
"""

from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)  # client unique réutilisé par les tests du fichier


def test_health_returns_ok():
    """/health est la sonde utilisée par docker --wait et le frontend."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_company_endpoint_is_not_implemented():
    """L'endpoint entreprise n'existe pas encore : 501 explicite.

    On asserte le 501 (et non un 200 avec un corps vide) car la règle
    produit interdit de faire semblant de répondre : erreur claire tant que
    la phase 1 n'a pas rempli la table companies.
    """
    resp = client.get("/companies/320193")  # CIK d'Apple, valeur arbitraire
    assert resp.status_code == 501
