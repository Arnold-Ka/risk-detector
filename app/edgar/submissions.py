"""API submissions de la SEC — l'historique COMPLET des dépôts d'un émetteur.

Pourquoi ce module : `companyfacts` ne donne que les faits XBRL des 10-K ;
les signaux d'événements (feuille de route §2) ont besoin des DÉPÔTS eux-
mêmes — 8-K avec leurs items ("1.03,2.04"), NT 10-K/NT 10-Q (retards),
Form 4 (transactions des dirigeants, plus tard).

Structure de l'API (`https://data.sec.gov/submissions/CIK##########.json`) :
  - `filings.recent` : les ~1000 derniers dépôts (le plus récent en premier) ;
  - `filings.files`   : liste de pages JSON supplémentaires pour l'historique
    plus ancien (ex. Apple : 1001 récents + 1264 dans CIK…-submissions-001.json).
Les deux doivent être fusionnés pour couvrir toute la vie de l'entreprise.

Champs utiles par dépôt : form, accessionNumber, filingDate, reportDate
(date de la période — facultative mais CRITIQUE pour rattacher un NT à
l'exercice en retard), items (8-K uniquement), primaryDocument.

Le téléchargement passe par EdgarClient (cache + rate limit 10 req/s +
User-Agent) : app/edgar/submissions.py ne fait que FORMATER, le réseau
reste dans scripts/fetch_submissions.py.
"""

import json

from app.edgar.client import EdgarClient

MAIN_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# Pages historiques : data.sec.gov/submissions/<nom de fichier de la page>
OLDER_URL = "https://data.sec.gov/submissions/{name}"

# URL d'un dépôt dans EDGAR — MÊME format que scripts/load_postgres.py
# (accession sans tirets) : un même accession ne doit pas avoir deux URL.
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{accn}-index.htm"


def filing_url(cik: int, accession: str) -> str:
    return FILING_URL.format(cik=cik, accn=accession.replace("-", ""))


def load_filing_rows(client: EdgarClient, cik: int) -> list[dict]:
    """Tous les dépôts d'un CIK (recent + pages historiques), fusionnés.

    Chaque ligne : {accession, form, filed_at, report_date, items, url} —
    la forme d'entrée de repo.upsert_filing. Dédupliqué par accession
    (SEC ne fait pas se chevaucher recent/files, mais coûte rien).
    Requiert les pages en cache : lancer d'abord
    `uv run python -m scripts.fetch_submissions` (sinon EdgarClient
    ira les télécharger au passage, avec les mêmes règles de politesse).
    """
    main = json.loads(client.get(MAIN_URL.format(cik=cik)))
    pages = [main["filings"]["recent"]]
    for extra in main["filings"].get("files", []):
        pages.append(json.loads(client.get(OLDER_URL.format(name=extra["name"]))))

    rows: dict[str, dict] = {}
    for page in pages:
        rows.update(_page_rows(page, cik))
    return sorted(rows.values(), key=lambda r: r["filed_at"])


def load_recent_rows(
    client: EdgarClient, cik: int, max_age: float | None = None
) -> list[dict]:
    """Seulement la page `recent` (~1000 derniers dépôts) — une seule requête.

    Suffisant au job nocturne pour DÉTECTER les dépôts nouveau.x depuis la
    dernière exécution (10-K de l'année, 8-K/NT/Form 4 des derniers
    mois) sans retélécharger les pages historiques complètes.
    `max_age` = TTL du cache (secondes) : le nightly veut les dépôts
    d'aujourd'hui, les batchs gardent le cache pérennne.
    """
    main = json.loads(client.get(MAIN_URL.format(cik=cik), max_age=max_age))
    return sorted(
        _page_rows(main["filings"]["recent"], cik).values(),
        key=lambda r: r["filed_at"],
    )


def _page_rows(page: dict, cik: int) -> dict[str, dict]:
    """Une page submissions -> {accession: ligne} (mêmes champs que load_filing_rows)."""
    rows: dict[str, dict] = {}
    forms = page.get("form", [])
    primaries = page.get("primaryDocument", [])
    for i in range(len(forms)):
        accession = page["accessionNumber"][i]
        if accession in rows:
            continue
        rows[accession] = {
            "accession": accession,
            "form": forms[i],
            "filed_at": page["filingDate"][i],
            # reportDate/"" = absent : None plutôt que chaîne vide pour
            # que le mapping d'exercice sache qu'il faut retomber sur
            # filed_at.
            "report_date": page["reportDate"][i] or None,
            # items = "" pour les non-8-K ; garder "" (et non None) laisse
            # SQL à distinguer « 8-K sans item listé » de « colonne
            # vierge » (NULL = dépôt non enrichi).
            "items": page["items"][i] or "",
            # primaryDocument : chemin du document principal (utile pour
            # les Form 4 — le XML brut se dérive de ce chemin, cf.
            # app/edgar/form4.py). "" quand absent.
            "primary_doc": primaries[i] if i < len(primaries) else "",
            "url": filing_url(cik, accession),
        }
    return rows
