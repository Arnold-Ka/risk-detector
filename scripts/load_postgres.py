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
    uv run python -m scripts.load_postgres --manifest data/backtest/companies.json
    # ^ ingère les cohortes du backtest (CSV lus à côté du manifeste).

Le chargeur fait tout le travail de sélection (règles dans
app/normalize/loader.py, validées par tests/test_normalize.py) : ce
script ne fait que persister. Idempotent — relancer ne crée ni doublon
(ni ligne orpheline : les faits sans dépôt source échoueraient au
contrôle de vérification final).
"""

import csv
import json
import sys

from app.backtest.cohort import sector_group_for_sic
from app.db.repo import (
    get_conn,
    upsert_company,
    upsert_filing,
    upsert_prices,
)
from app.edgar.client import EdgarClient
from app.edgar.submissions import load_filing_rows
from app.ingest.companyfacts import ingest_companyfacts
from scripts.fetch_phase0 import CACHE_DIR, OUT_DIR, resolve_run

# Formulaires porteurs d'événements (§2) — une seule source de vérité :
# la constante vit dans app/ingest/refresh.py (le nightly l'utilise aussi).
from app.ingest.refresh import EVENT_FORMS


def load_prices(conn, company_id: str, slug: str, out_dir) -> int:
    """Insère les cours retenus par fetch_prices (date_valeur, cours).

    Seules les lignes AVEC cours sont prises : quand fetch_prices est
    tombé sur le repli « flottant SEC » (titre delisté : BBBY), la colonne
    cours est vide — « donnée manquante » plutôt qu'un prix inventé, donc
    rien à inserer dans `prices`.
    """
    path = out_dir / f"{slug}_ratios.csv"
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
    companies, out_dir = resolve_run()
    # Contrôle d'entrée : sans cache SEC, on ne peut rien charger — message
    # clair plutôt qu'un échec noyé dans un traceback json.JSONDecodeError.
    missing = [
        CACHE_DIR / f"companyfacts_{c['cik']:010d}.json"
        for c in companies
        if not (CACHE_DIR / f"companyfacts_{c['cik']:010d}.json").exists()
    ]
    if missing:
        cmd = "uv run python -m scripts.fetch_phase0"
        if out_dir != OUT_DIR:  # mode backtest : le manifeste précise la population
            cmd += " --manifest data/backtest/companies.json"
        sys.exit(
            "Cache SEC manquant : "
            + ", ".join(str(p) for p in missing[:5])
            + (f"\n(+ {len(missing) - 5} autres)" if len(missing) > 5 else "")
            + f"\nLancer d'abord : {cmd}"
        )

    conn = get_conn()
    try:
        totals = 0
        for i, company in enumerate(companies, 1):
            slug = company["slug"]
            cik = company["cik"]
            cache_file = CACHE_DIR / f"companyfacts_{cik:010d}.json"
            companyfacts = json.loads(cache_file.read_text(encoding="utf-8"))

            # Priorité : libellé verrouillé en COMPANIES (entityName SEC de
            # BBBY = entité post-redressement, cf. commentaire de la liste),
            # sinon nom officiel du déposant (source de vérité SEC),
            # sinon libellé de la phase 0.
            name = company.get("name") or companyfacts.get("entityName") or company["label"]
            # sector_group depuis le SIC du manifeste (banques/assurances/REIT
            # = scores non fiables, cf. spec) ; None = ne pas toucher (COALESCE).
            sector_group = sector_group_for_sic(company.get("sic")) if company.get("sic") else None
            company_id = upsert_company(conn, cik, name, company.get("ticker"), sector_group)

            # 1. Faits XBRL : extract + purge/réinsertion via le moteur
            # partagé (app/ingest/companyfacts.py) — le refresh nocturne
            # utilise EXACTEMENT le même code, une seule implémentation
            # des règles de sélection (vote de millésime, fenêtre 300-400j…).
            stats = ingest_companyfacts(conn, company_id, cik, companyfacts)

            # 1 bis. Dépôts événementiels (8-K items, NT retard) : mêmes
            # lignes submissions que scripts.fetch_submissions met en cache.
            # Sans réseau si fetch_submissions a tourné ; sinon EdgarClient
            # retélécharge poliment (10 req/s, cache) — et si le réseau est
            # aussi coupé, on abandonne avec le rappel de la commande.
            try:
                event_filings = [
                    fr for fr in load_filing_rows(EdgarClient(), cik)
                    if fr["form"].startswith(EVENT_FORMS)
                ]
            except Exception as exc:
                sys.exit(
                    "Submissions indisponibles (cache absent + réseau en échec) : "
                    "lancer d'abord uv run python -m scripts.fetch_submissions\n"
                    + str(exc)
                )
            for fr in event_filings:
                upsert_filing(
                    conn,
                    company_id,
                    accession=fr["accession"],
                    form_type=fr["form"],
                    filed_at=fr["filed_at"],
                    url=fr["url"],
                    items=fr["items"],
                    report_date=fr["report_date"],
                )

            n_prices = load_prices(conn, company_id, slug, out_dir)
            totals += stats["facts"]
            purge_note = f", {stats['purged']} périmés purgés" if stats["purged"] else ""
            print(
                f"  [{i}/{len(companies)}] {slug}: {stats['facts']} faits{purge_note}, "
                f"{stats['filings_10k']} dépôts 10-K + {len(event_filings)} événements, "
                f"{n_prices} cours"
            )

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
