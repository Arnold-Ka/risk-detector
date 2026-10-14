"""Télécharge les archives `submissions` du trio de phase 0 (étape fetch).

Deuxième archive SEC prévue par la feuille de route §3 (la première étant
companyfacts, scripts/fetch_phase0.py) : l'historique complet des dépôts
sert les signaux d'événements (8-K critiques, NT tardifs) et, plus tard,
Form 4.

Étape FETCH au sens phase 0 : ne fait QUE remplir le cache
(data/cache/edgar/ via EdgarClient : rate limit 10 req/s, User-Agent,
écriture atomique). L'ingestion en PostgreSQL reste
`scripts/load_postgres.py`, l'analyse reste `app.jobs.nightly`.

Usage (depuis la racine, après fetch_phase0) :
    uv run python -m scripts.fetch_submissions
    uv run python -m scripts.fetch_submissions --manifest data/backtest/companies.json
Idempotent : le cache répond sans re-télécharger ; relancer après une
nouvelle nuit de dépôts SEC pour rafraîchir (EDGAR met à jour `recent`).
"""

import json

from app.edgar.client import EdgarClient
from app.edgar.submissions import MAIN_URL, OLDER_URL, load_filing_rows
from scripts.fetch_phase0 import resolve_run


def main() -> None:
    client = EdgarClient()
    companies, _ = resolve_run()
    for company in companies:
        cik = company["cik"]
        main_page = json.loads(client.get(MAIN_URL.format(cik=cik)))
        pages = 1
        for extra in main_page["filings"].get("files", []):
            client.get(OLDER_URL.format(name=extra["name"]))
            pages += 1

        # load_filing_rows relit tout depuis le cache (aucun réseau ici) et
        # compte ce qui sera ingéré — c'est la vérification de cohérence du
        # téléchargement.
        rows = load_filing_rows(client, cik)
        forms = [r["form"] for r in rows]
        n_8k = sum(1 for f in forms if f.startswith("8-K"))
        n_nt = sum(1 for f in forms if f.startswith("NT"))
        first = rows[0]["filed_at"] if rows else "-"
        last = rows[-1]["filed_at"] if rows else "-"
        # Flèche ASCII : la console Windows (cp1252) refuse « → ».
        # BBBY (delistée) n'a pas de ticker verrouillé : repli sur le slug.
        label = company.get("ticker") or company["slug"]
        print(
            f"  {label}: {len(rows)} dépôts ({pages} pages, "
            f"{first} -> {last}) — {n_8k} 8-K, {n_nt} NT"
        )
    print("Submissions en cache (fetch_submissions terminé).")


if __name__ == "__main__":
    main()
