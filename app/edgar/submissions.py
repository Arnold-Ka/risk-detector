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
        # Les tableaux sont indexés par dépôt i (colonne par champ).
        forms = page.get("form", [])
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
                "url": filing_url(cik, accession),
            }
    return sorted(rows.values(), key=lambda r: r["filed_at"])
