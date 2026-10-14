"""Job batch nocturne — le cœur de la précalculation du produit.

Principe de la feuille de route : « pré-calculer la nuit plutôt que de
calculer à la demande ». L'API ne fait que LIRE les signaux ; ce job est le
seul écrivain.

Pipeline (AUTONOME depuis la réfection de la phase 1) :
    1. fetch+normalize — app/ingest/refresh.refresh_company : pour chaque
                    entreprise, va voir EDGAR (page recent → 10-K inédit →
                    companyfacts frais ; 8-K/NT/Form 4 nouveaux → upsert)
                    et Yahoo (dernier cours ≤ chaque bilan) — détection
                    INCRÉMENTALE, seule la nouveauté est ingérée ;
    2. signals    — app/signals/compute sur les séries de `facts`,
                    purge + réinsertion par entreprise (replace_company_signals),
                    chaque ligne avec period_end + filing_id (traçabilité).

Mode batch historique (amorçage du manifeste) : les scripts fetch_phase0
→ fetch_prices → fetch_submissions → load_postgres restent la voie du
bootstrap ; ce job ne fait que MAINTENIR à jour ce qui est en base.

Invocation (depuis la racine du projet, pour que `app` soit importable) :
    uv run python -m app.jobs.nightly              # refresh + signaux
    uv run python -m app.jobs.nightly --no-refresh # signaux seuls (offline)
    uv run python -m app.jobs.nightly --limit 3    # pilote sur 3 entreprises
Le drapeau `-m` est important : il ajoute le répertoire courant au
sys.path ; lancer `python app/jobs/nightly.py` directement échouerait sur
les imports `app.*`.

Transaction : UNE transaction par entreprise (et non plus une pour tout
le lot) — un plantage réseau au bout de 800 entreprises ne perd pas les
799 précédentes, et la reprise est naturelle (les upserts sont
idempotents). commit/rollback gérés ici, pas dans refresh_company.

Planification : manuel en dev ; `cron` sur le VPS en production (choix de
planificateur selon la feuille de route §4 — cron d'abord, RQ/Celery
seulement en phase 2+).

Note sector_group : les scores d'Altman/Piotroski/Beneish sont peu fiables
pour banques/assurances/REIT (§2). Le filtre sera appliqué à l'AFFICHAGE
(API/frontend) : on stocke quand même l'historique, on décide ensuite de
masquer — ne rien calculer reviendrait à perdre la donnée pour un choix de
présentation.
"""

import sys
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
from app.edgar.client import EdgarClient
from app.ingest.refresh import refresh_company
from app.signals.compute import compute_company


def main(refresh: bool = True, limit: int | None = None) -> None:
    """`refresh=False` = signaux seuls (tests, offline) ; `limit` = pilote.

    Les paramètres sont explicites (pas de lecture sys.argv ici) : un test
    qui appelle main() ne doit pas dépendre de l'argv de pytest — sinon
    `--no-refresh` absent de pytest.jsonlanderait le réseau.
    """
    # cp1252 : les noms d'entreprises et les messages accentués ne doivent
    # pas planter la console Windows (mesuré : UnicodeEncodeError).
    sys.stdout.reconfigure(errors="replace")

    conn = get_conn()
    client = EdgarClient() if refresh else None
    try:
        companies = list_companies(conn)
        if limit is not None:
            companies = companies[:limit]
        computed_at = date.today().isoformat()
        totals: Counter = Counter()
        n_errors = 0

        for company in companies:
            # Une transaction par entreprise : si le refresh ou le
            # calcul échoue, on annule CETTE entreprise et on continue.
            try:
                if refresh:
                    stats = refresh_company(conn, client, company)
                    note = (
                        f"refresh: +{stats['new_10k']} 10-K, "
                        f"+{stats['new_events']} événements, "
                        f"+{stats['new_form4']} Form 4 ({stats['tx']} tx), "
                        f"{stats['prices']} cours"
                    )
                    if stats["errors"]:
                        note += f" | ERREURS: {'; '.join(stats['errors'])}"
                        n_errors += 1
                    print(f"  {company['ticker'] or company['cik']}: {note}")

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
                conn.commit()  # commit PAR entreprise (reprise possible)

                by_sev = Counter(r.severity for r in results)
                by_type = Counter(r.signal_type for r in results)
                totals.update(by_sev)
                print(
                    f"  {company['ticker'] or company['cik']}: {n} signaux "
                    f"({dict(sorted(by_sev.items()))})"
                )
                print(f"    par type: {dict(sorted(by_type.items()))}")
            except Exception as exc:
                conn.rollback()
                n_errors += 1
                print(
                    f"  !! {company['ticker'] or company['cik']}: "
                    f"{type(exc).__name__}: {exc} — ignorée, entreprise suivante"
                )

        print(f"\nSignaux recalculés ({sum(totals.values())} lignes, "
              f"seuils: {dict(sorted(totals.items()))}) — {computed_at}")
        if n_errors:
            print(f"Entreprises en erreur : {n_errors} (voir détails ci-dessus)")
    finally:
        conn.close()


if __name__ == "__main__":
    # Active `python -m app.jobs.nightly` ; argv parsé ICI (et non dans
    # main) pour que les tests appellent main(refresh=False) sans dépendre
    # de l'argv de pytest.
    main(
        refresh="--no-refresh" not in sys.argv,
        limit=(
            int(sys.argv[sys.argv.index("--limit") + 1])
            if "--limit" in sys.argv
            else None
        ),
    )
