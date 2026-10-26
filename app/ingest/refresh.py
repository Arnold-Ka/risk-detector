"""Refresh autonome d'UNE entreprise — le « fetch + normalize » du nightly.

Avant : les dépôts arrivaient par des scripts batchs manuels (fetch_phase0,
fetch_submissions, fetch_form4, load_postgres) puis le nightly ne faisait
que recalculer les signaux. Maintenant le nightly est AUTONOME : pour
chaque entreprise de la base il va voir EDGAR/Yahoo et n'ingère QUE le
nouveau (détection incrémentale par accession déjà connue).

Étapes (chacune résiliente — une panne réseau n'annule pas les autres
ni le recalcul des signaux sur les données existantes) ;
  0. recent   — page submissions `recent` (~1000 dépôts, 1 requête, cache
                TTL 20 h) : la base de la détection incrémentale ;
  1. facts    — si un 10-K inédit apparaît → retéléchargement companyfacts
                (max_age=0 = forcé) → extract + purge/réinsertion ;
  2. événements— 8-K/NT pour les signaux ; 6-K des FPI conservés comme
                 dépôts sources, sans les interpréter comme des 8-K ;
  3. Form 4   — idem pour les dépôts form="4" (XML parse → transactions) ;
                SEULEMENT si l'entreprise a déjà des Form 4 en base :
                le bootstrap historique (~720k XML) reste le travail du
                batch scripts/fetch_form4 + load_form4 ;
  4. prix     — historique Yahoo (cache TTL 12 h) → dernier cours ≤ chaque
                date de bilan (désajusté des splits) → upsert `prices`.

Résilience : les erreurs réseau sont collectées dans le retour
(stats["errors"]) au lieu de lever — le job continue et affiche un
résumé ; « donnée manquante » > faire tomber la nuit entière.
"""

import json
from pathlib import Path

from app.config import settings
from app.db.repo import (
    annual_forms_for_company,
    fetch_accessions,
    fetch_balance_dates,
    has_form4_filings,
    latest_annual_filed_at,
    upsert_filing,
    upsert_prices,
)
from app.edgar.client import FACTS_URL, EdgarClient
from app.edgar.form4 import parse_form4, raw_doc_url
from app.edgar.submissions import load_recent_rows
from app.edgar.yahoo import daily_closes, fetch_history, raw_close, splits_after
from app.ingest.companyfacts import ingest_companyfacts
from app.ingest.form4 import ingest_form4_rows
from app.normalize.loader import DEFAULT_ANNUAL_FORMS, SUPPORTED_ANNUAL_FORMS

# Formulaires porteurs d'événements (§2) : 8-K (+ amendements) pour leurs
# items, NT* pour les retards de dépôt. Même liste que le batch
# load_postgres — une seule source de vérité (voir aussi EVENT_FORMS de
# scripts/load_postgres.py, importé depuis ici pour rester aligné).
EVENT_FORMS = ("8-K", "NT")

# TTL des caches du refresh : une passe nocturne doit voir les dépôts de
# la journée, mais deux exécutions dans la même journée ne re-frappent
# pas EDGAR/Yahoo pour rien (20 h < 24 h : une exécution par nuit est
# toujours fraîche).
EDGAR_TTL = 20 * 3600
PRICE_TTL = 12 * 3600


def select_new_filings(recent: list[dict], known: set[str], form_of) -> list[dict]:
    """Dépôts de la page recent INÉDITS en base, filtrés par `form_of`.

    `form_of(row) -> bool` : prédicat de sélection (exact pour 10-K et
    Form 4 — les amendements 4/A re-déposent l'original, piège doublon —,
    préfixe pour 8-K/NT). Pure : testable sans base ni réseau.
    """
    return [r for r in recent if form_of(r) and r["accession"] not in known]


def last_closes_for_balances(
    balance_dates: list[str],
    closes: list[tuple[str, float]],
    splits: list[tuple[str, float]],
) -> list[tuple[str, float]]:
    """[(date du cours retenu, cours brut)] — un cours par date de bilan.

    Même règle que scripts/fetch_prices et app/signals/compute : dernier
    cours ≤ date de bilan, désajusté des splits (parts XBRL brutes).
    Date de COURS (et non de bilan) en clé : c'est elle qui figure dans
    la table `prices` (coïncide avec date_valeur du pipeline CSV).
    Pure : testable sans Yahoo (splits et closes en entrée).
    """
    dates = [d for d, _ in closes]
    out = []
    for balance in balance_dates:
        idx = max((i for i, d in enumerate(dates) if d <= balance), default=None)
        if idx is None:
            continue  # aucune cotation avant ce bilan : donnée manquante
        close_date, adj = closes[idx]
        out.append((close_date, raw_close(close_date, adj, splits)))
    return out


def refresh_company(conn, client: EdgarClient, company: dict) -> dict:
    """Rafraîchit facts + événements + Form 4 + prix d'UNE entreprise.

    `company` = ligne de repo.list_companies (id, cik, name, ticker, ...).
    Ne lève jamais sur erreur réseau (collectée dans stats["errors"]) ;
    n'écrit pas (commit) — la transaction appartient au caller (nightly :
    un commit par entreprise, reprise possible après plantage).
    """
    cik = company["cik"]
    company_id = company["id"]
    stats: dict = {
        "errors": [], "new_annual": 0, "new_events": 0,
        "new_form4": 0, "tx": 0, "prices": 0,
    }

    # --- 0. Page recent : la base de la détection incrémentale -------------
    # Sans elle, pas de steps 1-3 (mais le step 4 prix reste faisable :
    # il ne dépend que de la base et de Yahoo).
    recent: list[dict] = []
    try:
        recent = load_recent_rows(client, cik, max_age=EDGAR_TTL)
    except Exception as exc:
        stats["errors"].append(f"recent: {type(exc).__name__}: {exc}")

    # --- 1. Faits XBRL : un dépôt annuel inédit est-il arrivé ? ------------
    # Le formulaire est propre à l'émetteur : domestique 10-K, FPI 20-F,
    # canadien 40-F. Le backtest garde son filtre 10-K par défaut ; le
    # manifeste d'univers active explicitement les autres formes.
    if recent:
        try:
            annual_forms = set(annual_forms_for_company(conn, company_id))
            recent_annual = [
                r for r in recent if r["form"] in SUPPORTED_ANNUAL_FORMS
            ]
            annual_forms.update(r["form"] for r in recent_annual)
            if not annual_forms:
                annual_forms.update(DEFAULT_ANNUAL_FORMS)
            db_latest = latest_annual_filed_at(conn, company_id)
            new_annual_rows = [
                r for r in recent_annual if r["filed_at"] > (db_latest or "")
            ]
            stats["new_annual"] = 1 if new_annual_rows else 0
            if stats["new_annual"]:
                # max_age=0 : le cache est périmé PAR DÉFINITION (un
                # nouveau rapport annuel est tombé) → force le re-téléchargement ;
                # le cache fichier est réécrit pour les prochains lancements.
                facts_json = json.loads(
                    client.get(FACTS_URL.format(cik=cik), max_age=0)
                )
                stats["facts"] = ingest_companyfacts(
                    conn,
                    company_id,
                    cik,
                    facts_json,
                    annual_forms=tuple(sorted(annual_forms)),
                )
                # Marquer les rapports observés même si aucun tag normalisé
                # n'est disponible : évite de retélécharger companyfacts
                # chaque nuit pour un formulaire étranger non mappé.
                for row in new_annual_rows:
                    upsert_filing(
                        conn,
                        company_id,
                        accession=row["accession"],
                        form_type=row["form"],
                        filed_at=row["filed_at"],
                        url=row["url"],
                    )
        except Exception as exc:
            stats["errors"].append(f"facts: {type(exc).__name__}: {exc}")

        # --- 2. Événements 8-K/NT ; archives 6-K des FPI -------------------
        try:
            # Relecture des accessions : le step 1 a pu en ajouter (les
            # 10-K récents) — ne pas les re-proposer comme « nouveaux ».
            known = fetch_accessions(conn, company_id)
            is_foreign_filer = bool(
                {"20-F", "40-F"} & set(annual_forms_for_company(conn, company_id))
            )
            new_events = select_new_filings(
                recent,
                known,
                lambda r: r["form"].startswith(EVENT_FORMS)
                or (is_foreign_filer and r["form"].startswith("6-K")),
            )
            for r in new_events:
                upsert_filing(
                    conn,
                    company_id,
                    accession=r["accession"],
                    form_type=r["form"],
                    filed_at=r["filed_at"],
                    url=r["url"],
                    items=r["items"],
                    report_date=r["report_date"],
                )
            stats["new_events"] = len(new_events)
        except Exception as exc:
            stats["errors"].append(f"events: {type(exc).__name__}: {exc}")

        # --- 3. Form 4 inédits -> transactions des dirigeants --------------
        # Bootstrap historique = batch (fetch_form4 + load_form4) : sans au
        # moins UN Form 4 en base, la page recent peut en contenir des
        # CENTAINES (Apple en file des dizaines par semaine) — le nightly
        # ne doit pas re-télécharger l'historique complet par accident.
        try:
            if has_form4_filings(conn, company_id):
                known = fetch_accessions(conn, company_id)
                new_form4 = select_new_filings(
                    recent, known, lambda r: r["form"] == "4"
                )
                for r in new_form4:
                    url = raw_doc_url(cik, r["accession"], r.get("primary_doc", ""))
                    if url is None:
                        continue  # dépôts pré-2003 en .htm : hors périmètre v1
                    transactions = parse_form4(client.get(url), r)
                    n_f, n_t = ingest_form4_rows(conn, company_id, cik, transactions)
                    stats["new_form4"] += n_f
                    stats["tx"] += n_t
        except Exception as exc:
            stats["errors"].append(f"form4: {type(exc).__name__}: {exc}")

    # --- 4. Cours de bourse : dernier cours ≤ chaque bilan -----------------
    # Ticker absent (faillie delistée, ex. BBBY) → flottant SEC seul, pas
    # de requête Yahoo (le repli vit dans signals/compute via public_float).
    try:
        ticker = company.get("ticker") or ""
        if ticker:
            symbol = ticker.replace(".", "-")  # BRK.B -> BRK-B (Yahoo)
            payload = fetch_history(
                symbol, Path(settings.cache_dir), max_age=PRICE_TTL
            )
            closes = daily_closes(payload)
            if closes:
                splits = splits_after(payload)
                # Les dates de bilan viennent des faits (déjà rafraîchis
                # au step 1 si un 10-K est tombé) : le nouveau bilan est
                # valorisé dans la même passe.
                balance_dates = fetch_balance_dates(conn, company_id)
                rows = last_closes_for_balances(balance_dates, closes, splits)
                stats["prices"] = upsert_prices(conn, company_id, rows)
    except Exception as exc:
        stats["errors"].append(f"prices: {type(exc).__name__}: {exc}")

    return stats
