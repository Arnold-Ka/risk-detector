"""Phase 0 — collecte des données des 3 entreprises de référence.

Feuille de route §5 (semaine 1) : récupérer les données d'une entreprise
saine, d'une en difficulté et d'une faillie, pour ensuite calculer leur
Z-score À LA MAIN dans un tableur. Ce script fait la partie « récupération »
et prépare les colonnes du tableur (variables A–E, chaque valeur reliée au
dépôt SEC exact d'où elle vient).

Ce qu'il produit, dans data/phase0/ :
  - <slug>_facts.csv   : format long (année fiscale, concept, valeur,
                         accn, date de dépôt, URL) — traçabilité totale,
                         pivotable dans Excel ;
  - <slug>_ratios.csv  : les ratios A, B, C, E pré-calculés (D = valeur
                         boursière MANQUANTE : il faut une source de cours,
                         tâche semaine 1 de la phase 0) pour faciliter le
                         calcul manuel du Z.

Lancement (depuis la racine) :
    uv run python -m scripts.fetch_phase0
    uv run python -m scripts.fetch_phase0 --refresh   # ignorer le cache
    uv run python -m scripts.fetch_phase0 --manifest data/backtest/companies.json
    # ^ mode backtest : mêmes règles d'extraction, mais liste d'entrées
    #   {cik, slug, label, ticker, name...} lue dans le manifeste, CSV
    #   écrits à côté de lui (data/backtest/*.csv) au lieu de data/phase0/.

Cache : les réponses companyfacts sont écrites dans data/cache/ (gitignoré)
— règle SEC « mettre en cache plutôt que re-interroger ».
"""

import csv
import json
import re
import sys
from pathlib import Path

import httpx

from app.edgar.client import FACTS_URL, EdgarClient
# Extraction DÉLÉGUÉE au chargeur produit : la phase 0 ne fait plus que
# du formatage. Une seule implémentation des règles de sélection
# (fenêtre de durée, priorité de tags, vote de millésime) vivant dans
# app/normalize/loader.py — c'est le même code qui remplit PostgreSQL.
from app.normalize.loader import extract, load_map

# --- Les 3 entreprises de la phase 0 (choix validé) -------------------------
# « saine » = actuelle et profitable ; « en difficulté » = cotée, très
# endettée, mais vivante ; « faillie » = 8-K item 1.03 classique.
COMPANIES = [
    # CIK verrouillés par la décision du 2026-10-12 : le CIK étant stable
    # (identifiant permanent SEC), on le fixe ici plutôt que de re-le
    # résoudre à chaque run — le ticker peut être retiré de la fenêtre
    # cotée (BBBY delisté, ticker recyclé depuis 2026), pas le CIK.
    {"slug": "apple_healthy", "label": "Apple (saine)", "ticker": "AAPL", "cik": 320193},
    {"slug": "amc_distressed", "label": "AMC Entertainment (en difficulté)", "ticker": "AMC", "cik": 1411579},
    # Enron écarté par décision du 2026-10-12 : dépôts pré-XBRL (1997-2001),
    # l'API companyfacts renvoie 404 — aucune donnée structurée exploitable.
    # BBBY a le même profil (faillie 2023, dernier exercice désastreux)
    # mais 16 ans de données XBRL. Pas de ticker : delisté depuis 2023.
    # "name" force le libellé : entityName SEC = entité post-redressement
    # (« 20230930-DK-BUTTERFLY-1 ») alors que les dépôts analysés sont ceux
    # de l'entité d'origine.
    {"slug": "bbby_bankrupt", "label": "Bed Bath & Beyond (faillie 2023)", "search": "bed+bath", "cik": 886158, "name": "Bed Bath & Beyond, Inc."},
]

# Les concepts XBRL (tags, priorités, durée/instant) vivent MAINTENANT
# dans app/normalize/xbrl_map.yaml (table de correspondance phase 1),
# lus par app.normalize.loader.load_map — plus de liste parallèle ici.

CACHE_DIR = Path("data/cache")
OUT_DIR = Path("data/phase0")


def resolve_run(argv: list[str] | None = None) -> tuple[list[dict], Path]:
    """(--manifest PATH) -> (companies, out_dir) — le standard des scripts.

    Sans manifeste : le trio de phase 0 + data/phase0/ (gate historique).
    Avec `--manifest data/backtest/companies.json` : les cohortes du
    backtest, et les CSV d'ingestion rangés À CÔTÉ du manifeste
    (data/backtest/*.csv, gitignorés — rejouables depuis le cache EDGAR).

    Même moteur, deux populations : fetch_phase0, fetch_prices,
    fetch_submissions et load_postgres appellent TOUS cette fonction.
    """
    argv = sys.argv if argv is None else argv
    if "--manifest" in argv:
        path = Path(argv[argv.index("--manifest") + 1])
        companies = json.loads(path.read_text(encoding="utf-8"))
        return companies, path.parent
    return COMPANIES, OUT_DIR

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEARCH_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&company={name}&type=10-K&count=10&output=atom"
)
# FACTS_URL vit dans app/edgar/client.py (partagé avec le refresh nocturne).


def resolve_cik(client: EdgarClient, company: dict) -> int:
    """Résout le CIK : valeur verrouillée > ticker (fichier officiel) > nom.

    - `cik` figé dans COMPANIES : aucune requête réseau, zéro dépendance à
      la disponibilité de company_tickers.json (BBBY en a disparu) ;
    - sinon ticker (fichier officiel, CIK canonique) ;
    - sinon recherche atom par nom (résolution dynamique).
    """
    if "cik" in company:
        return int(company["cik"])
    if "ticker" in company:
        data = json.loads(client.get(TICKERS_URL))
        for row in data.values():
            if row["ticker"].upper() == company["ticker"].upper():
                # Le fichier utilise "cik_str" (et non "cik") — nom de champ
                # officiel de company_tickers.json.
                return int(row["cik_str"])
        raise SystemExit(f"Ticker {company['ticker']} introuvable dans company_tickers.json")

    # Recherche par nom : l'URL atom renvoie un ou plusieurs <cik>.
    xml = client.get(SEARCH_URL.format(name=company["search"])).decode("utf-8", "replace")
    matches = re.findall(r"<cik>(\d+)</cik>", xml, flags=re.IGNORECASE)
    if not matches:
        raise SystemExit(f"Aucun résultat EDGAR pour « {company['search']} »")
    return int(matches[0])


def load_facts(client: EdgarClient, cik: int, refresh: bool) -> dict:
    """companyfacts avec cache fichier (règle SEC : ne pas re-télécharger)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"companyfacts_{cik:010d}.json"
    if cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    try:
        # cached=False : ce fichier a DÉJÀ son propre cache ci-dessus ;
        # le cache du client (data/cache/edgar/) ferait une COPIE inutile
        # de plusieurs Mo du même companyfacts.
        payload = client.get(FACTS_URL.format(cik=cik), cached=False)
    except httpx.HTTPStatusError as exc:
        # 404 = cet émetteur n'a AUCUN fait XBRL : dépôts d'avant ~2009
        # (Enron) ou API sans couverture. Ce n'est pas une erreur réseau :
        # on le signale et on passe à l'entreprise suivante.
        if exc.response.status_code == 404:
            return {}
        raise
    cache_file.write_bytes(payload)
    return json.loads(payload)


def build_rows(cik: int, companyfacts: dict) -> tuple[list[dict], dict[int, dict], list[str]]:
    """companyfacts -> lignes longues sourcées + valeurs par année + notes.

    L'extraction est intégralement déléguée à `app.normalize.loader.extract`
    (voir ses règles : 10-K/FY, fenêtre de durée, priorité de tags, vote
    de millésime). Ce formatage ajoute :
      - l'URL cliquable du dépôt (traçabilité principe nº1) ;
      - l'année clé = année de la date de fin (convention « exercice »
        reprise par ratios.csv et fetch_prices) ;
      - `per_year[année][concept]` écrasé par les dates successives :
        extract trie par date croissante, donc la date de fin la PLUS
        TARDIVE de l'année gagne (ex. AMC : comparatif au 2018-01-01
        puis vrai solde au 2018-12-31 → le solde l'emporte).
    """
    rows: list[dict] = []
    per_year: dict[int, dict] = {}
    tags_used: dict[str, set[str]] = {}

    for fact in extract(companyfacts):
        accn = fact["accn"]
        year = int(fact["period_end"][:4])
        rows.append(
            {
                "year": year,
                # Date de fin de période EXACTE du fait (bilan au…,
                # exercice se terminant au…) — nécessaire pour
                # aligner ensuite le cours de bourse sur cette date.
                "period_end": fact["period_end"],
                "concept": fact["concept"],
                "value": fact["value"],
                "accession": accn,
                "filed": fact["filed"],
                "url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{accn.replace('-', '')}/{accn}-index.htm"
                ),
            }
        )
        per_year.setdefault(year, {})[fact["concept"]] = fact["value"]
        tags_used.setdefault(fact["concept"], set()).add(fact["tag"])

    # Relevé de variantes (imprimé dans main) + concepts absents de ce
    # dépôt — la table YAML étant la source de vérité, on la référence.
    missing = sorted(set(load_map()) - set(tags_used))
    notes = [f"{k} <- {sorted(v)}" for k, v in sorted(tags_used.items())]
    return rows, per_year, notes + [f"manquant: {m}" for m in missing]


def write_outputs(slug: str, rows: list[dict], per_year: dict[int, dict], out_dir: Path) -> Path:
    """Écrit facts (long, sourcé) + ratios (A B C E, D manquant).

    `out_dir` : data/phase0/ (trio) ou data/backtest/ (manifeste) — le
    chemin est injecté par resolve_run, pas figé ici.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    facts_file = out_dir / f"{slug}_facts.csv"
    with facts_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["year", "period_end", "concept", "value", "accession", "filed", "url"]
        )
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["year"], r["concept"])))

    ratios_file = out_dir / f"{slug}_ratios.csv"
    with ratios_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        # D (valeur boursière / dettes) exige un cours de bourse : aucune
        # source choisie en phase 0 => colonne laissée vide, pas de fausse valeur.
        # « year » = année de la date de fin de période (voir build_rows).
        # EBIT : clé loader `operating_income` (OperatingIncomeLoss — l'EBIT
        # pur n'existe presque jamais en XBRL, approximation standard à
        # documenter dans la doc du signal Altman).
        w.writerow(["year", "A=FR/actif", "B=RE/actif", "C=EBIT/actif", "E=CA/actif", "D=VK/dettes", "Z (à calculer à la main)"])
        for fy in sorted(per_year):
            y = per_year[fy]
            ta = y.get("total_assets")
            if not ta:
                continue
            wc = y.get("current_assets", 0) - y.get("current_liabilities", 0)
            a = wc / ta
            b = y.get("retained_earnings", 0) / ta
            c = y.get("operating_income", 0) / ta
            e = y.get("sales", 0) / ta
            w.writerow([fy, f"{a:.4f}", f"{b:.4f}", f"{c:.4f}", f"{e:.4f}", "", ""])
    return facts_file


def main() -> None:
    refresh = "--refresh" in sys.argv
    companies, out_dir = resolve_run()
    manifest_mode = out_dir != OUT_DIR
    client = EdgarClient()  # rate-limit 0.1 s + User-Agent du .env

    for i, company in enumerate(companies, 1):
        print(f"\n=== {company['label']} ({i}/{len(companies)})")
        cik = resolve_cik(client, company)
        print(f"  CIK: {cik}")
        facts = load_facts(client, cik, refresh)

        gaap = facts.get("facts", {}).get("us-gaap", {})
        if not gaap:
            # Découverte typique de phase 0 : dépôts d'avant l'ère XBRL
            # (obligatoire depuis ~2009) n'ont AUCUN fait structuré.
            # Normal dans le backtest (cotée avant 2009 + pas de XBRL).
            print("  !! AUCUNE donnée XBRL (dépôts antérieurs à l'ère XBRL ?)")
            if not manifest_mode:
                print("     -> entreprise à remplacer dans le trio de la phase 0")
            continue

        rows, per_year, notes = build_rows(cik, facts)
        out = write_outputs(company["slug"], rows, per_year, out_dir)
        years = sorted(per_year)
        print(f"  années fiscales: {years[0]}–{years[-1]} ({len(years)} ans)" if years else "  aucune année")
        if not manifest_mode:
            # Le relevé de variantes (10 lignes/entreprise) serait illisible
            # sur 875 entreprises du backtest — gardé pour le trio.
            print(f"  variantes retenues: {', '.join(n for n in notes if not n.startswith('manquant')) or '—'}")
            print(f"  manques: {', '.join(n.removeprefix('manquant: ') for n in notes if n.startswith('manquant')) or '—'}")
        print(f"  sorties: {out} + ratios.csv")

    if not manifest_mode:
        print(
            "\nRappel phase 0 : la colonne Z reste À CALCULER À LA MAIN dans le "
            "tableur (gate du projet). Les colonnes de valorisation (D) sont "
            "renseignées par scripts.fetch_prices — à relancer APRÈS ce script "
            "(fetch_phase0 régénère ratios.csv à zéro)."
        )


if __name__ == "__main__":
    main()
