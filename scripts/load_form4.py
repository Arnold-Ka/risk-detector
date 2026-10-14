"""Ingestion des Form 4 parsed (data/cache/form4/*.jsonl) -> PostgreSQL.

Chaîne complète des transactions des dirigeants :
    scripts.fetch_form4 (cache EDGAR -> jsonl)  ->  ce script (-> BDD)
    -> app.jobs.nightly (-> signal insider_sales)  ->  API / frontend.

Pour chaque CIK avec un jsonl :
  1. l'entreprise doit déjà exister (`companies`, via load_postgres
     --manifest) — sinon skip + rappel de la commande (pas de création
     à moitié : nom/ticker viennent du pipeline facts, pas d'ici) ;
  2. upsert des dépôts Form 4 dans `filings` (form_type "4", une fois
     par accession, pour la traçabilité signal -> dépôt) ;
  3. upsert des transactions (idempotent, ON CONFLICT DO NOTHING).

Usage (nécessite la base via `docker compose up -d --wait`) :
    uv run python -m scripts.load_form4
"""

import json
import sys
from pathlib import Path

from app.db.repo import get_conn, get_company
from app.ingest.form4 import ingest_form4_rows

FORM4_DIR = Path("data/cache/form4")


def ingest_company(conn, company_id: str, cik: int) -> tuple[int, int]:
    """Transactions d'un CIK -> filings + insider_transactions.

    Retourne (nb depots upsertés, nb transactions insérées).
    Une transaction PostgreSQL : un plantage au milieu ne laisse pas de
    dépôt orphelin sans ses transactions.
    """
    path = FORM4_DIR / f"{cik}.jsonl"
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # Moteur partagé avec le refresh nocturne (app/ingest/form4.py) :
    # upsert des dépôts (filing_id = source traçable) + transactions.
    return ingest_form4_rows(conn, company_id, cik, rows)


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    if not FORM4_DIR.exists():
        sys.exit("data/cache/form4 absent — lancer d'abord scripts.fetch_form4")

    conn = get_conn()
    n_ciks = n_accn = n_tx = n_skip = 0
    try:
        for path in sorted(FORM4_DIR.glob("*.jsonl")):
            cik = int(path.stem)
            company = get_company(conn, cik)
            if company is None:
                print(
                    f"  !! cik={cik} absent de companies — ignorer "
                    "(re-lancer load_postgres --manifest si c'est un oubli)"
                )
                n_skip += 1
                conn.rollback()  # rien écrit pour ce CIK
                continue
            try:
                n_a, n_i = ingest_company(conn, company["id"], cik)
                conn.commit()  # commit PAR entreprise (reprise possible)
            except Exception as exc:
                conn.rollback()
                print(f"  !! cik={cik}: {type(exc).__name__}: {exc}")
                n_skip += 1
                continue
            n_ciks += 1
            n_accn += n_a
            n_tx += n_i
            if n_ciks % 50 == 0:
                print(f"... {n_ciks} CIKs, {n_accn} dépôts, {n_tx} transactions")
    finally:
        conn.close()

    print(
        f"Termine : {n_ciks} entreprises ({n_skip} sautées), "
        f"{n_accn} dépôts Form 4, {n_tx} transactions insérées"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
