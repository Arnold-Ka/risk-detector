"""Tests de la couche d'écriture PostgreSQL (repo) — exige la base levée.

Ces tests vérifient le CONTRAT d'ingestion de la phase 1 :
  - upsert idempotent (relancer le job ne crée pas de doublon) ;
  - mise à jour de la valeur ET du filing en cohérence (traçabilité) ;
  - NULL = « je ne touche pas » pour ticker/sector_group ;
  - la contrainte UNIQUE (company_id, concept, period_end) protège
    vraiment la table (garde-fou si un appelant contourne repo).

Chaque test tourne dans SA transaction, systématiquement rollbackée au
nettoyage : aucun résidu dans la base de dev, les tests sont rejouables.
Si la base est éteinte → skip (pas d'échec), commande :
    docker compose up -d --wait
    uv run pytest tests/test_repo.py -v
"""

import uuid

import psycopg
import pytest

from app.db.repo import get_conn, upsert_company, upsert_facts, upsert_filing

# CIK factice hors des données réelles (régime = 5 chiffres max, 999999
# ne collera jamais avec un vrai émetteur SEC).
FAKE_CIK = 999_999


def _db_available() -> bool:
    """Vrai si Postgres répond — sinon pytest.skip, pas d'échec."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="PostgreSQL indisponible — `docker compose up -d --wait`",
)


@pytest.fixture()
def conn():
    """Connexion dédiée : rollback garanti à la fin du test."""
    c = get_conn()
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def _insert_filing(conn, company_id: str, accn: str) -> str:
    return upsert_filing(
        conn,
        company_id,
        accession=accn,
        form_type="10-K",
        filed_at="2024-03-01",
        url=f"https://www.sec.gov/Archives/edgar/data/{FAKE_CIK}/x/{accn}-index.htm",
    )


def test_upsert_company_is_idempotent_and_preserves_manual_fields(conn):
    """Relancer l'ingestion : 1 seule ligne, ticker corrigé à la main préservé."""
    id1 = upsert_company(conn, FAKE_CIK, "Fake Inc.", ticker="FAKE")
    # Re-import avec ticker/sector absents (None) : on ne doit PAS écraser
    # les valeurs existantes (COALESCE), mais bien le nom (source SEC).
    id2 = upsert_company(conn, FAKE_CIK, "Fake Inc. renommée")
    assert id1 == id2  # même ligne, pas de doublon

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, ticker, sector_group FROM companies WHERE cik = %s",
            (FAKE_CIK,),
        )
        name, ticker, sector = cur.fetchone()
    assert name == "Fake Inc. renommée"  # nom SEC toujours écrasé
    assert ticker == "FAKE"              # ticker None → conservé
    assert sector == "other"             # valeur par défaut à l'insertion


def test_upsert_facts_updates_value_and_filing_together(conn):
    """Restatement : valeur + filing_id changent ensemble (couple verrouillé)."""
    company_id = upsert_company(conn, FAKE_CIK, "Fake Inc.")
    filing_old = _insert_filing(conn, company_id, "0000999999-24-000001")
    row = {
        "company_id": company_id,
        "filing_id": filing_old,
        "concept": "total_assets",
        "value": 100,
        "period_end": "2023-12-31",
        "fiscal_year": 2023,
    }
    assert upsert_facts(conn, company_id, [row]) == 1

    # Même (entreprise, concept, date), nouveau dépôt + nouvelle valeur.
    filing_new = _insert_filing(conn, company_id, "0000999999-24-000002")
    row2 = dict(row, value=150, filing_id=filing_new)
    upsert_facts(conn, company_id, [row2])

    with conn.cursor() as cur:
        cur.execute(
            """SELECT value, filing_id FROM facts
               WHERE company_id = %s AND concept = 'total_assets'
                 AND period_end = '2023-12-31'""",
            (company_id,),
        )
        rows = cur.fetchall()
    assert len(rows) == 1, "la contrainte UNIQUE n'a pas évité le doublon"
    assert rows[0][0] == 150
    assert rows[0][1] == filing_new  # la trace pointe vers le NOUVEAU filing


def test_unique_constraint_blocks_raw_duplicate_insert(conn):
    """Garde-fou : même sans passer par repo, la table refuse le doublon."""
    company_id = upsert_company(conn, FAKE_CIK, "Fake Inc.")
    filing_id = _insert_filing(conn, company_id, "0000999999-24-000003")
    base = {
        "company_id": company_id,
        "filing_id": filing_id,
        "concept": "cash",
        "period_end": "2023-12-31",
        "value": 1,
        "fiscal_year": 2023,
    }
    upsert_facts(conn, company_id, [base])

    # Insertion brute BRISE l'unicité → UniqueViolation SQL (pas de ON CONFLICT).
    # Transaction abîmée par l'erreur : on annule tout dans le finally du
    # fixture conn (rollback), donc le test suivant repart d'une base propre.
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO facts (company_id, filing_id, concept, value,
                                      period_end, fiscal_year)
                   VALUES (%(company_id)s, %(filing_id)s, %(concept)s,
                           %(value)s, %(period_end)s, %(fiscal_year)s)""",
                {**base, "value": 2},
            )
