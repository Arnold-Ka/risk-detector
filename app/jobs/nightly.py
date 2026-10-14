"""Job batch nocturne — le cœur de la précalculation du produit.

Principe de la feuille de route : « pré-calculer la nuit plutôt que de
calculer à la demande ». L'API ne fait que LIRE les signaux ; ce job est le
seul écrivain.

Pipeline (état phase 1, semaines 5-6) :
    1. fetch      — TODO : nouveaux dépôts EDGAR (les données de départ
                    arrivent par scripts/load_postgres, ingestion manuelle
                    du MVP) ;
    2. normalize  — fait : c'est le chargeur (app/normalize/) qui remplit
                    `facts` lors de l'ingestion ;
    3. signals    — FAIT : app/signals/compute sur les séries de `facts`,
                    purge + réinsertion par entreprise (replace_company_signals),
                    chaque ligne avec period_end + filing_id (traçabilité).

Invocation (depuis la racine du projet, pour que `app` soit importable) :
    uv run python -m app.jobs.nightly
Le drapeau `-m` est important : il ajoute le répertoire courant au
sys.path ; lancer `python app/jobs/nightly.py` directement échouerait sur
les imports `app.*`.

Planification : manuel en dev ; `cron` sur le VPS en production (choix de
planificateur selon la feuille de route §4 — cron d'abord, RQ/Celery
seulement en phase 2+).

Note sector_group : les scores d'Altman/Piotroski/Beneish sont peu fiables
pour banques/assurances/REIT (§2). Le filtre sera appliqué à l'AFFICHAGE
(API/frontend) : on stocke quand même l'historique, on décide ensuite de
masquer — ne rien calculer reviendrait à perdre la donnée pour un choix de
présentation.
"""

from collections import Counter
from datetime import date

from app.db.repo import (
    fetch_event_rows,
    fetch_fact_rows,
    fetch_insider_rows,
    fetch_price_rows,
    get_conn,
    has_form4_filings,
    list_companies,
    replace_company_signals,
)
from app.signals.compute import compute_company


def main() -> None:
    conn = get_conn()
    try:
        companies = list_companies(conn)
        computed_at = date.today().isoformat()
        totals: Counter = Counter()

        for company in companies:
            rows = fetch_fact_rows(conn, company["id"])
            prices = fetch_price_rows(conn, company["id"])
            # Dépôts 8-K/NT -> signaux d'événements (toujours une liste :
            # on a vérifié, même vide, le « 0 » est donc vrai).
            events = fetch_event_rows(conn, company["id"])
            # Transactions Form 4 -> signal ventes de dirigeants. Contrat
            # None/[] strict : [] seulement si des dépôts Form 4 existent
            # en base (on a RÉELLEMENT vérifié) ; sinon None — un []
            # fantôme diluerait le composite de tout le monde (mesuré :
            # det6 68 % -> 57 % avant ce garde-fou).
            insiders = (
                fetch_insider_rows(conn, company["id"])
                if has_form4_filings(conn, company["id"])
                else None
            )
            results = compute_company(rows, prices, events, insiders)
            payload = [r.to_row(company["id"], computed_at) for r in results]
            n = replace_company_signals(conn, company["id"], payload, computed_at)

            by_sev = Counter(r.severity for r in results)
            by_type = Counter(r.signal_type for r in results)
            totals.update(by_sev)
            print(
                f"  {company['ticker'] or company['cik']}: {n} signaux "
                f"({dict(sorted(by_sev.items()))})"
            )
            print(f"    par type: {dict(sorted(by_type.items()))}")

        conn.commit()  # transaction unique : tout ou rien (voir repo.get_conn)
        print(f"\nSignaux recalculés ({sum(totals.values())} lignes, "
              f"seuils: {dict(sorted(totals.items()))}) — {computed_at}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    # Active `python -m app.jobs.nightly` ; évite que main() s'exécute quand
    # ce fichier est simplement importé par un autre module ou un test.
    main()
