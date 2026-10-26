"""Tests des contrôles d'accès et du CORS sans écriture en base."""

from fastapi.testclient import TestClient
import pytest

from app.api.main import app
from app.config import settings
from app.db.repo import get_conn
from app.db.repo import watchlist_user_id

client = TestClient(app)


def test_watchlist_is_disabled_without_a_strong_internal_secret(monkeypatch):
    monkeypatch.setattr(settings, "watchlist_api_secret", "too-short")

    response = client.get("/me/watchlist")

    assert response.status_code == 503


def test_watchlist_rejects_requests_without_the_internal_secret(monkeypatch):
    secret = "s" * 40
    monkeypatch.setattr(settings, "watchlist_api_secret", secret)

    response = client.get(
        "/me/watchlist",
        headers={
            "X-Watchlist-Api-Key": "wrong-secret",
            "X-Clerk-User-Id": "user_test",
            "X-Clerk-User-Email": "test@example.com",
        },
    )

    assert response.status_code == 401


def test_watchlist_requires_a_server_verified_user_identity(monkeypatch):
    secret = "s" * 40
    monkeypatch.setattr(settings, "watchlist_api_secret", secret)

    response = client.get(
        "/me/watchlist",
        headers={"X-Watchlist-Api-Key": secret},
    )

    assert response.status_code == 401


def test_client_supplied_user_id_cannot_replace_clerk_identity(monkeypatch):
    secret = "s" * 40
    monkeypatch.setattr(settings, "watchlist_api_secret", secret)

    response = client.post(
        "/me/watchlist",
        headers={"X-Watchlist-Api-Key": secret},
        json={"cik": 320193, "user_id": "another-user"},
    )

    assert response.status_code == 401


def test_public_api_allows_the_local_frontend_origin():
    # Le middleware CORS lit FRONTEND_ORIGINS à l'import de l'API (.env ou
    # variable d'environnement) : on teste la première origine configurée
    # plutôt qu'un port codé en dur, sinon le test dépend du poste.
    origin = settings.frontend_origins.split(",")[0].strip()
    response = client.options(
        "/search?q=apple",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_clerk_subject_maps_to_a_stable_local_user_id():
    first = watchlist_user_id("user_clerk_123")
    second = watchlist_user_id("user_clerk_123")

    assert first == second
    assert first != watchlist_user_id("user_clerk_456")


def test_coverage_endpoint_pages_loaded_companies():
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
    except Exception:
        pytest.skip("PostgreSQL indisponible")

    response = client.get("/coverage", params={"limit": 5, "offset": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= len(body["items"])
    assert len(body["items"]) <= 5
    if body["items"]:
        assert {
            "cik",
            "name",
            "ticker",
            "status",
            "level",
            "available_components",
            "missing_components",
        } <= body["items"][0].keys()
