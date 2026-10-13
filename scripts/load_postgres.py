"""Phase 1 — ingestion des indicateurs normalisés dans PostgreSQL.

Entrées (locales — aucun appel réseau si le cache existe) :
  - data/cache/companyfacts_<cik>.json  (récupéré par scripts.fetch_phase0)
  - data/phase0/<slug>_ratios.csv       (colonnes date_valeur/cours
    écrites par scripts.fetch_prices → table `prices`)

Sorties (tables de app/db/schema.sql) :
  - companies : une ligne par émetteur (cik, entityName SEC, ticker)
  - filings   : un dépôt par numéro d'inscription (accession) cité
  - facts     : chaque fait normalisé + son filing_id (traçabilité nº1 :
    tout chiffre stocké doit pouvoir remonter à son dépôt source)
  - prices    : les cours retenus pour le ratio D

Lancement (depuis la racine) :
    uv run python -m scripts.load_postgres

Le chargeur fait tout le travail de sélection (règles dans
app/normalize/loader.py, validées par tests/test_normalize.py) : ce
script ne fait que persister. Idempotent — relancer ne crée ni doublon
(ni ligne orpheline : les faits sans dépôt source échoueraient au
contrôle de vérification final).
"""

import csv
import json
import sys

from app.db.repo import (
    get_conn,
    delete_facts,
    upsert_company,
    upsert_facts,
    upsert_filing,
    upsert_prices,
)
from app.normalize.loader import extract
from scripts.fetch_phase0 import CACHE_DIR, COMPANIES, OUT_DIR

# URL du dépôt dans EDGAR, dérivée de l'accession (mêmes nommage que la
# phase 0 : chaque valeur exportée est cliquable jusqu'au document source).
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{accn}-index.htm"


def load_prices(conn, company_id: str, slug: str) -> int:
    """Insère les cours retenus par fetch_prices (date_valeur, cours).

    Seules les lignes AVEC cours sont prises : quand fetch_prices est
    tombé sur le repli « flottant SEC » (titre delisté : BBBY), la colonne
    cours est vide — « donnée manquante » plutôt qu'un prix inventé, donc
    rien à inserer dans `prices`.
    """
    path = OUT_DIR / f"{slug}_ratios.csv"
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            (r["date_valeur"], float(r["cours"]))
            for r in reader
            if r.get("date_valeur") and r.get("cours")
        ]
    if not rows:
        return 0
    return upsert_prices(conn, company_id, rows)


def verify(conn) -> None:
    """Contrôle post-chargement : compteurs + traçabilité complète.

    Échoue (assert) si un fait n'a pas de dépôt source — la règle
    produit « chaque score montre le dépôt d'où il vient » serait violée.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.cik, c.name,
                   (SELECT count(*) FROM facts f WHERE f.company_id = c.id),
                   (SELECT count(DISTINCT f2.concept) FROM facts f2 WHERE f2.company_id = c.id),
                   (SELECT count(DISTINCT f3.period_end) FROM facts f3 WHERE f3.company_id = c.id),
                   (SELECT count(*) FROM filings fi WHERE fi.company_id = c.id),
                   (SELECT count(*) FROM prices p WHERE p.company_id = c.id)
            FROM companies c
            ORDER BY c.cik
            """
        )
        print("=== État de la base ===")
        print(f"{'cik':>7}  {'nom':<28} {'faits':>6} {'conc.':>6} {'exerc.':>7} {'dépôts':>7} {'cours':>6}")
        for cik, name, n_facts, n_concepts, n_periods, n_filings, n_prices in cur.fetchall():
            print(f"{cik:>7}  {name[:28]:<28} {n_facts:>6} {n_concepts:>6} "
                  f"{n_periods:>7} {n_filings:>7} {n_prices:>6}")
        cur.execute("SELECT count(*) FROM facts WHERE filing_id IS NULL")
        orphan = cur.fetchone()[0]
        assert orphan == 0, f"{orphan} fait(s) sans filing_id — traçabilité cassée"
        print(f"traçabilité : 0 fait sans dépôt source")


def main() -> None:
    # Contrôle d'entrée : sans cache SEC, on ne peut rien charger — message
    # clair plutôt qu'un échec noyé dans un traceback json.JSONDecodeError.
    missing = [
        CACHE_DIR / f"companyfacts_{c['cik']:010d}.json"
        for c in COMPANIES
        if not (CACHE_DIR / f"companyfacts_{c['cik']:010d}.json").exists()
    ]
    if missing:
        sys.exit(
            "Cache SEC manquant : "
            + ", ".join(str(p) for p in missing)
            + "\nLancer d'abord : uv run python -m scripts.fetch_phase0"
        )

    conn = get_conn()
    try:
        totals = 0
        for company in COMPANIES:
            slug = company["slug"]
            cik = company["cik"]
            cache_file = CACHE_DIR / f"companyfacts_{cik:010d}.json"
            companyfacts = json.loads(cache_file.read_text(encoding="utf-8"))

            # Priorité : libellé verrouillé en COMPANIES (entityName SEC de
            # BBBY = entité post-redressement, cf. commentaire de la liste),
            # sinon nom officiel du déposant (source de vérité SEC),
            # sinon libellé de la phase 0.
            name = company.get("name") or companyfacts.get("entityName") or company["label"]
            company_id = upsert_company(conn, cik, name, company.get("ticker"))

            # 1. Dépots d'abord : les faits pointent vers leurs ids.
            facts = extract(companyfacts)
            filing_ids: dict[str, str] = {}
            for fact in facts:
                accn = fact["accn"]
                if accn not in filing_ids:
                    filing_ids[accn] = upsert_filing(
                        conn,
                        company_id,
                        accession=accn,
                        form_type="10-K",  # extract ne garde que l'annuel
                        filed_at=fact["filed"],
                        url=FILING_URL.format(cik=cik, accn=accn.replace("-", "")),
                    )

            # 2. Puis les faits eux-mêmes.
            rows = [
                {
                    "company_id": company_id,
                    "filing_id": filing_ids[fact["accn"]],
                    "concept": fact["concept"],
                    "value": fact["value"],
                    "period_end": fact["period_end"],
                    # Convention phase 0 : « exercice » = année de la date
                    # de FIN de période (le fiscal_year du libellé SEC est
                    # piégé en colonne comparative, cf. loader).
                    "fiscal_year": int(fact["period_end"][:4]),
                }
                for fact in facts
            ]
            # 2. Purge de l'ancien lot PUIS écriture : upsert seul = les
            # faits que l'extraction ne produit plus resteraient en base
            # (règles qui évoluent). Même transaction → atomicité.
            n_purged = delete_facts(conn, company_id)
            n_facts = upsert_facts(conn, company_id, rows)
            n_prices = load_prices(conn, company_id, slug)
            totals += n_facts
            purge_note = f", {n_purged} périmés purgés" if n_purged else ""
            print(f"  {slug}: {n_facts} faits{purge_note}, {len(filing_ids)} dépôts, {n_prices} cours")

        conn.commit()  # transaction unique : tout ou rien (voir repo.get_conn)
        print(f"\nIngestion validée ({totals} faits).")
        verify(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
