"""Ingestion « transactions Form 4 -> PostgreSQL » — partagée batch/nightly.

scripts/load_form4.py (bootstrap : jsonl du batch complet) et le refresh
nocturne (dépôts récents seulement) passent par ici : même upsert des
dépôts (filing_id = source traçable du signal) et des transactions.
"""

from app.db.repo import upsert_filing, upsert_insider_transactions
from app.edgar.submissions import filing_url


def ingest_form4_rows(
    conn, company_id: str, cik: int, transactions: list[dict]
) -> tuple[int, int]:
    """Transactions parsées (sortie de parse_form4) -> filings + table.

    Retourne (nb dépôts Form 4 upsertés, nb transactions insérées).
    Une transaction PostgreSQL : un plantage au milieu ne laisse pas de
    dépôt orphelin sans ses transactions. Idempotent — rejeu sans doublon
    (clé d'unicité du schéma).
    """
    # 1. Dépôts Form 4 (une fois par accession) -> filing_id.
    filing_ids: dict[str, str] = {}
    for row in transactions:
        accn = row["accession"]
        if accn not in filing_ids:
            filing_ids[accn] = upsert_filing(
                conn,
                company_id,
                accession=accn,
                form_type="4",
                filed_at=row["filed_at"],
                url=filing_url(cik, accn),
            )

    # 2. Transactions, prêtes pour repo (filing_id + dates en ISO).
    tx_rows = [
        {
            "filing_id": filing_ids[r["accession"]],
            "transaction_date": r["transaction_date"],
            "code": r.get("code"),
            "acquired_disposed": r.get("acquired_disposed"),
            "shares": r.get("shares"),
            "price": r.get("price"),
            "owner_name": r.get("owner_name"),
            "is_officer": r.get("is_officer"),
            "is_director": r.get("is_director"),
            "officer_title": r.get("officer_title"),
            "plan_10b5_1": r.get("plan_10b5_1"),
        }
        for r in transactions
    ]
    inserted = upsert_insider_transactions(conn, company_id, tx_rows)
    return len(filing_ids), inserted
