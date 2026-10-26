"""Tests PostgreSQL de la limite et de l'idempotence des listes utilisateur."""

from urllib.parse import urlparse
from uuid import uuid4

import pytest

from app.config import settings
from app.db.repo import (
    MAX_WATCHLIST_SIZE,
    add_watchlist_company,
    fetch_watchlist,
    get_conn,
    remove_watchlist_company,
    upsert_company,
    upsert_watchlist_user,
)


def test_watchlist_limit_is_atomic_and_add_remove_are_idempotent():
    host = urlparse(settings.database_url).hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.skip("Le test de liste de suivi s'exécute seulement sur PostgreSQL local")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        conn.close()
        pytest.skip("PostgreSQL local indisponible")

    try:
        cik_start = 2_000_000_000 + uuid4().int % 100_000_000
        companies = [
            upsert_company(conn, cik_start + index, f"Test watchlist {uuid4()}")
            for index in range(MAX_WATCHLIST_SIZE + 1)
        ]
        user_id = upsert_watchlist_user(
            conn, f"user_test_{uuid4()}", f"{uuid4()}@example.test"
        )

        for company_id in companies[:MAX_WATCHLIST_SIZE]:
            assert add_watchlist_company(conn, user_id, company_id) == "added"

        assert add_watchlist_company(conn, user_id, companies[0]) == "already_present"
        assert add_watchlist_company(conn, user_id, companies[-1]) == "limit_reached"
        assert len(fetch_watchlist(conn, user_id)) == MAX_WATCHLIST_SIZE

        assert remove_watchlist_company(conn, user_id, companies[0]) is True
        assert remove_watchlist_company(conn, user_id, companies[0]) is False
        assert add_watchlist_company(conn, user_id, companies[-1]) == "added"
        assert len(fetch_watchlist(conn, user_id)) == MAX_WATCHLIST_SIZE
    finally:
        conn.rollback()
        conn.close()
