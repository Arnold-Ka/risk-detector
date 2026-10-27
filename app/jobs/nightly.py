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
                    chaque ligne avec period_end + filing_id (traçabilité) ;
                    + signal LSTM (phase 2, app/dl/infer) si l'artefact
                    data/models/lstm.pt existe — ignoré sinon ;
    3. alertes    — app/alerts : dernier composite en base AVANT le
                    remplacement comparé au nouveau ; un changement de
                    palier sur une entreprise suivie = un e-mail
                    récapitulatif par utilisateur en fin de job (envoi
                    désactivé sans SMTP_HOST, cf. app/alerts/mailer).

Mode batch historique (amorçage du manifeste) : les scripts fetch_phase0
→ fetch_prices → fetch_submissions → load_postgres restent la voie du
bootstrap ; ce job ne fait que MAINTENIR à jour ce qui est en base.

Invocation (depuis la racine du projet, pour que `app` soit importable) :
    uv run python -m app.jobs.nightly              # refresh + signaux
    uv run python -m app.jobs.nightly --no-refresh # signaux seuls (offline)
    uv run python -m app.jobs.nightly --limit 3    # pilote sur 3 entreprises
    uv run python -m app.jobs.nightly --no-alerts  # sans détection d'alertes
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
from pathlib import Path

from app.alerts.changes import (
    LevelChange,
    detect_level_change,
    latest_composite_of,
)
from app.alerts.mailer import alerts_enabled, send_digests
from app.config import settings
from app.db.repo import (
    annual_forms_for_company,
    company_watcher_emails,
    fetch_event_rows,
    fetch_fact_rows,
    fetch_insider_rows,
    fetch_price_rows,
    get_conn,
    has_form4_filings,
    latest_composite,
    list_companies,
    replace_company_signals,
)
from app.dl import infer as dl_infer
from app.edgar.client import EdgarClient
from app.edgar.yahoo import cached_splits
from app.health import run_problems
from app.ingest.refresh import refresh_company
from app.signals.compute import compute_company


def main(
    refresh: bool = True, limit: int | None = None, notify: bool = False
) -> list[str]:
    """`refresh=False` = signaux seuls (tests, offline) ; `limit` = pilote.

    Renvoie les problèmes bloquants de l'exécution (app.health.run_problems) :
    [] = saine. La ligne de commande en fait un code de sortie 1 pour que
    l'Action GitHub passe au rouge au lieu de rester verte sur une base
    à moitié recalculée.

    Les paramètres sont explicites (pas de lecture sys.argv ici) : un test
    qui appelle main() ne doit pas dépendre de l'argv de pytest — sinon
    `--no-refresh` absent de pytest.jsonlanderait le réseau.

    `notify` vaut False par défaut pour la même raison : un test qui appelle
    main() ne doit JAMAIS envoyer d'e-mail, même si le `.env` du poste
    configure un SMTP. Seule la ligne de commande l'active (sauf
    `--no-alerts`).
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
        # Compteurs séparés : seuls les échecs de calcul et les échecs SEC
        # systémiques sont bloquants (cf. app/health.py) ; les autres
        # erreurs de refresh (cours Yahoo d'entreprises radiées…) sont
        # attendues et restent informatives.
        compute_errors = 0
        sec_errors = 0
        refresh_errors = 0
        # Alertes en attente : e-mail -> changements de palier. Envoyées en
        # fin de job pour regrouper toutes les entreprises d'un utilisateur
        # dans UN seul message.
        pending: dict[str, list[LevelChange]] = {}
        n_changes = 0

        # Signal deep learning (phase 2) : l'artefact est chargé UNE fois
        # pour tout le lot (cache interne à app.dl.infer). Absent ou
        # désynchronisé -> le job continue SANS inférence DL : le modèle
        # est un bonus, pas un prérequis de la précalculation.
        dl_bundle = dl_infer.load_artifact()
        if dl_bundle is None:
            print(
                "Modèle LSTM absent ou désynchronisé — inférence DL ignorée "
                "(uv run python -m scripts.train_lstm)"
            )

        for company in companies:
            # Une transaction par entreprise : si le refresh ou le
            # calcul échoue, on annule CETTE entreprise et on continue.
            try:
                if refresh:
                    stats = refresh_company(conn, client, company)
                    note = (
                        f"refresh: +{stats['new_annual']} rapports annuels, "
                        f"+{stats['new_events']} événements, "
                        f"+{stats['new_form4']} Form 4 ({stats['tx']} tx), "
                        f"{stats['prices']} cours"
                    )
                    if stats["errors"]:
                        note += f" | ERREURS: {'; '.join(stats['errors'])}"
                        refresh_errors += 1
                        # « recent: » = la page des dépôts SEC elle-même a
                        # échoué (refresh.py) : symptôme d'une panne globale.
                        if any(e.startswith("recent:") for e in stats["errors"]):
                            sec_errors += 1
                    print(f"  {company['ticker'] or company['cik']}: {note}")

                # Niveau AVANT recalcul : replace_company_signals va le
                # purger, c'est le seul moment où il est encore lisible.
                before = latest_composite(conn, company["id"]) if notify else None

                annual_forms = set(annual_forms_for_company(conn, company["id"]))
                is_foreign_filer = bool({"20-F", "40-F"} & annual_forms)
                rows = fetch_fact_rows(conn, company["id"])
                if is_foreign_filer:
                    # Les ADR peuvent coter une unité différente des actions
                    # ordinaires XBRL ; le flottant est en USD tandis que les
                    # états IFRS peuvent être en devise locale. Sans ratios de
                    # conversion vérifiés, ne pas fabriquer ces signaux.
                    rows = [
                        row
                        for row in rows
                        if row["concept"]
                        not in {
                            "shares_outstanding",
                            "shares_weighted_basic",
                            "public_float",
                        }
                    ]
                prices = fetch_price_rows(conn, company["id"])
                # Dépôts 8-K/NT -> signaux d'événements (toujours une liste :
                # on a vérifié, même vide, le « 0 » est donc vrai).
                # Les FPI déclarent souvent leurs événements en 6-K ; tant
                # que leur taxonomie n'est pas modélisée, omettre ces signaux
                # plutôt que d'interpréter l'absence de 8-K comme un « sain ».
                events = (
                    None
                    if is_foreign_filer
                    else fetch_event_rows(conn, company["id"])
                )
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
                # Splits de marché -> correction du signal dilution. Source
                # = cache de cours partagé, ZÉRO requête (contrat main(
                # refresh=False) hors réseau tenu : lecture fichier seule).
                # Ticker absent = jamais coté côté Yahoo : [] (aucun split
                # de marché observable, documenté) ; ticker présent mais
                # cache absent = None -> dilution omise (contrat events).
                splits = (
                    None
                    if is_foreign_filer
                    else (
                        cached_splits(company["ticker"], Path(settings.cache_dir))
                        if company.get("ticker")
                        else []
                    )
                )
                results = compute_company(
                    rows,
                    [] if is_foreign_filer else prices,
                    events,
                    insiders,
                    splits=splits,
                )
                # Signaux LSTM : probabilité de faillite à 12 mois, un
                # par exercice (fenêtre glissante) — AJOUTÉS aux signaux
                # classiques, jamais pondérés par le composite (cf.
                # app/dl/infer). [] = strict-None (< 3 exercices, non
                # traçable…) : la fiche affichera « donnée manquante ».
                if dl_bundle is not None and not is_foreign_filer:
                    results.extend(
                        dl_infer.infer_company(conn, company, dl_bundle)
                    )
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
                compute_errors += 1
                print(
                    f"  !! {company['ticker'] or company['cik']}: "
                    f"{type(exc).__name__}: {exc} — ignorée, entreprise suivante"
                )
                continue

            # Détection APRÈS le commit : une alerte ne porte que sur un
            # niveau réellement écrit. Détecter avant exposerait à un doublon
            # (commit raté -> la nuit suivante redétecte le même changement).
            if notify:
                try:
                    change = detect_level_change(
                        company, before, latest_composite_of(results)
                    )
                    if change is not None:
                        n_changes += 1
                        watchers = company_watcher_emails(conn, company["id"])
                        conn.commit()  # ferme la transaction de lecture
                        for email in watchers:
                            pending.setdefault(email, []).append(change)
                        # Journal sans adresse e-mail (journaux Actions publics).
                        print(
                            f"    alerte: {change.before} -> {change.after} "
                            f"({len(watchers)} abonné(s))"
                        )
                except Exception as exc:
                    conn.rollback()
                    print(
                        f"  !! {company['ticker'] or company['cik']}: alerte "
                        f"non préparée ({type(exc).__name__}) — signaux conservés"
                    )

        print(f"\nSignaux recalculés ({sum(totals.values())} lignes, "
              f"seuils: {dict(sorted(totals.items()))}) — {computed_at}")
        print(
            f"Bilan : {len(companies)} entreprises, {compute_errors} en erreur "
            f"de calcul, {refresh_errors} avec erreurs de refresh "
            f"(dont {sec_errors} échecs SEC) — détails ci-dessus"
        )
        problems = run_problems(len(companies), compute_errors, sec_errors)
        if notify:
            stats = send_digests(pending)
            mode = "" if alerts_enabled() else " — envoi désactivé (SMTP_HOST vide)"
            print(
                f"Alertes : {n_changes} changement(s) de palier, "
                f"{len(pending)} destinataire(s), {stats['sent']} envoyé(s), "
                f"{stats['failed']} en échec{mode}"
            )
        return problems
    finally:
        conn.close()


if __name__ == "__main__":
    # Active `python -m app.jobs.nightly` ; argv parsé ICI (et non dans
    # main) pour que les tests appellent main(refresh=False) sans dépendre
    # de l'argv de pytest.
    problems = main(
        refresh="--no-refresh" not in sys.argv,
        limit=(
            int(sys.argv[sys.argv.index("--limit") + 1])
            if "--limit" in sys.argv
            else None
        ),
        notify="--no-alerts" not in sys.argv,
    )
    if problems:
        # Code 1 = Action rouge. Les signaux des entreprises réussies sont
        # déjà commités : l'échec signale, il n'annule rien.
        print("ÉCHEC du nightly : " + " ; ".join(problems))
        sys.exit(1)
