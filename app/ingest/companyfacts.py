"""Ingestion « companyfacts -> PostgreSQL » — le pont normalize → base.

Extraite de scripts/load_postgres.py pour être partagée entre le batch
d'amorçage (manifeste) et le refresh nocturne autonome : UNE SEULE
implémentation des règles (extract du chargeur, purge + réinsertion,
traçabilité filing_id) — même règle « un seul moteur » que partout ailleurs.

Le caller fournit companyfacts DÉJÀ chargés (JSON de
data/cache/companyfacts_*.json pour le batch, téléchargement frais pour
le nightly) : ce module ne touche jamais au réseau.
"""

from app.db.repo import delete_facts, upsert_facts, upsert_filing
from app.normalize.loader import DEFAULT_ANNUAL_FORMS, extract

# URL du dépôt dans EDGAR, dérivée de l'accession (même nommage partout :
# chaque valeur exportée est cliquable jusqu'au document source).
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{accn}-index.htm"


def ingest_companyfacts(
    conn,
    company_id: str,
    cik: int,
    companyfacts: dict,
    annual_forms: tuple[str, ...] = DEFAULT_ANNUAL_FORMS,
) -> dict:
    """Faits normalisés + dépôts annuels d'UN companyfacts -> base.

    Par défaut, conserve uniquement le 10-K pour le backtest historique.
    Les cohortes étrangères peuvent activer 20-F/40-F explicitement.
    Retourne {"facts": n, "purged": n, "annual_filings": n}.
    Même transaction que l'appelant (pas de commit ici) : purge +
    réinsertion atomiques, comme dans le batch d'origine — upsert seul
    laisserait des faits périmés quand les règles d'extraction changent.
    """
    facts = extract(companyfacts, annual_forms=annual_forms)
    if not facts and any(form in {"20-F", "40-F"} for form in annual_forms):
        # Un émetteur IFRS peut n'avoir encore aucun tag équivalent dans
        # xbrl_map. Ne pas effacer son historique précédemment normalisé.
        return {"facts": 0, "purged": 0, "annual_filings": 0}

    # 1. Dépôts d'abord : les faits pointent vers leurs ids.
    filing_ids: dict[str, str] = {}
    for fact in facts:
        accn = fact["accn"]
        if accn not in filing_ids:
            filing_ids[accn] = upsert_filing(
                conn,
                company_id,
                accession=accn,
                form_type=fact["form"],
                filed_at=fact["filed"],
                url=FILING_URL.format(cik=cik, accn=accn.replace("-", "")),
            )

    # 2. Purge de l'ancien lot PUIS écriture : upsert seul = les faits que
    # l'extraction ne produit plus resteraient en base (règles qui
    # évoluent). Même transaction → atomicité (voir get_conn).
    n_purged = delete_facts(conn, company_id)
    rows = [
        {
            "company_id": company_id,
            "filing_id": filing_ids[fact["accn"]],
            "concept": fact["concept"],
            "value": fact["value"],
            "period_end": fact["period_end"],
            # Convention phase 0 : « exercice » = année de la date de FIN
            # de période (le fiscal_year du libellé SEC est piégé en
            # colonne comparative, cf. loader).
            "fiscal_year": int(fact["period_end"][:4]),
        }
        for fact in facts
    ]
    n_facts = upsert_facts(conn, company_id, rows)
    return {"facts": n_facts, "purged": n_purged, "annual_filings": len(filing_ids)}
