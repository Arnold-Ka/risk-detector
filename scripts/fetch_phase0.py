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

Cache : les réponses companyfacts sont écrites dans data/cache/ (gitignoré)
— règle SEC « mettre en cache plutôt que re-interroger ».
"""

import csv
import json
import re
import sys
from pathlib import Path

import httpx

from app.edgar.client import EdgarClient

# --- Les 3 entreprises de la phase 0 (choix validé) -------------------------
# « saine » = actuelle et profitable ; « en difficulté » = cotée, très
# endettée, mais vivante ; « faillie » = 8-K item 1.03 classique.
COMPANIES = [
    {"slug": "apple_healthy", "label": "Apple (saine)", "ticker": "AAPL"},
    {"slug": "amc_distressed", "label": "AMC Entertainment (en difficulté)", "ticker": "AMC"},
    {"slug": "enron_bankrupt", "label": "Enron (faillie)", "search": "enron"},
    # Candidat de remplacement si Enron s'avère sans XBRL (cf. main()).
    {"slug": "bbby_bankrupt", "label": "Bed Bath & Beyond (faillie 2023)", "search": "bed+bath"},
]

# --- Concepts XBRL recherchés, avec leurs variantes ------------------------
# Les entreprises n'utilisent pas toujours le même tag (feuille de route §3,
# « limites connues ») : on essaie les variantes dans l'ordre et on note
# laquelle a marché — ce relevé sert directement à construire la table de
# correspondance XBRL de la phase 1 (app/normalize/xbrl_map.yaml).
CONCEPTS = {
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit", "RetainedEarnings"],
    # EBIT pur n'existe presque jamais en XBRL : OperatingIncomeLoss est
    # l'approximation standard (à documenter dans la doc du signal Altman).
    "ebit_proxy": ["OperatingIncomeLoss"],
    "sales": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
}
# Parts en circulation : namespace "dei" (pas "us-gaap") dans companyfacts.
SHARES_CONCEPTS = ["EntityCommonStockSharesOutstanding"]

CACHE_DIR = Path("data/cache")
OUT_DIR = Path("data/phase0")

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEARCH_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&company={name}&type=10-K&count=10&output=atom"
)
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def resolve_cik(client: EdgarClient, company: dict) -> int:
    """Résout le CIK : par ticker (fichier officiel) ou par nom (recherche)."""
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
        payload = client.get(FACTS_URL.format(cik=cik))
    except httpx.HTTPStatusError as exc:
        # 404 = cet émetteur n'a AUCUN fait XBRL : dépôts d'avant ~2009
        # (Enron) ou API sans couverture. Ce n'est pas une erreur réseau :
        # on le signale et on passe à l'entreprise suivante.
        if exc.response.status_code == 404:
            return {}
        raise
    cache_file.write_bytes(payload)
    return json.loads(payload)


def annual_values(concept_json: dict) -> dict[int, dict]:
    """Extrait les valeurs ANNUELLES (10-K, fp=FY) d'un concept.

    Clé = année de la date `end` du fait (ET non le champ `fy`) :
      - un solde (instant) rapporté en colonne comparative porte le `fy` de
        L'AUTRE exercice (ex. BBBY, exercice 2022 finissant le 2023-02-25) ;
      - en cas de correction de dépôt (« restated »), on garde le dépôt le
        plus récent (filed max) — c'est la valeur que l'outil affichera.
    Attention conséquence (phase 0) : pour un émetteur à exercice décalé
    (BBBY finit en février), l'année affichée = année de la date de fin,
    pas le « fiscal year » du libellé. Incohérents affichés = incohérents
    comparables, et tous les postes d'une même ligne partagent la même
    règle.
    """
    best: dict[int, dict] = {}
    for unit_values in concept_json.get("units", {}).values():
        for v in unit_values:
            if v.get("form") != "10-K" or v.get("fp") != "FY":
                continue
            end = v.get("end")
            if not end:
                continue
            year = int(end[:4])
            if year not in best or v.get("filed", "") > best[year].get("filed", ""):
                best[year] = v
    return best


def build_rows(cik: int, facts: dict) -> tuple[list[dict], dict[int, dict], list[str]]:
    """Construit les lignes longues + les valeurs par année + relevé de variantes.

    Variantes par ANNÉE (et non « un tag gagne pour toujours ») : un même
    concept change de tag au fil du temps (ASC 606 en 2018, dépendances de
    tags hérités…). Chaque variante vient combler les années qu'elle couvre,
    l'ordre de la liste = ordre de priorité. C'est exactement le relevé qui
    alimentera la table de correspondance XBRL de la phase 1.
    """
    rows: list[dict] = []
    per_year: dict[int, dict] = {}
    notes: list[str] = []
    missing: list[str] = []

    def harvest(namespace: str, concepts: dict[str, list[str]], key_map=None):
        for key, variants in concepts.items():
            merged: dict[int, dict] = {}
            used_tags: set[str] = set()
            for tag in variants:
                node = facts.get(namespace, {}).get(tag)
                if not node:
                    continue
                for year, v in annual_values(node).items():
                    if year not in merged:  # variante prioritaire gagne
                        merged[year] = v
                        used_tags.add(tag)
            if not merged:
                missing.append(key)
                continue
            notes.append(f"{key} <- {sorted(used_tags)}")
            for year, v in merged.items():
                accn = v["accn"]
                url = (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{accn.replace('-', '')}/{accn}-index.htm"
                )
                rows.append(
                    {
                        "year": year,
                        "concept": key,
                        "value": v["val"],
                        "accession": accn,
                        "filed": v.get("filed", ""),
                        "url": url,
                    }
                )
                per_year.setdefault(year, {})[key] = v["val"]

    harvest("us-gaap", CONCEPTS)
    harvest("dei", {"shares_outstanding": SHARES_CONCEPTS})
    return rows, per_year, notes + [f"manquant: {m}" for m in missing]


def write_outputs(slug: str, rows: list[dict], per_year: dict[int, dict]) -> Path:
    """Écrit facts (long, sourcé) + ratios (A B C E, D manquant)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    facts_file = OUT_DIR / f"{slug}_facts.csv"
    with facts_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["year", "concept", "value", "accession", "filed", "url"]
        )
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["year"], r["concept"])))

    ratios_file = OUT_DIR / f"{slug}_ratios.csv"
    with ratios_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        # D (valeur boursière / dettes) exige un cours de bourse : aucune
        # source choisie en phase 0 => colonne laissée vide, pas de fausse valeur.
        # « year » = année de la date de fin de période (voir annual_values).
        w.writerow(["year", "A=FR/actif", "B=RE/actif", "C=EBIT/actif", "E=CA/actif", "D=cours", "Z (à calculer à la main)"])
        for fy in sorted(per_year):
            y = per_year[fy]
            ta = y.get("total_assets")
            if not ta:
                continue
            wc = y.get("current_assets", 0) - y.get("current_liabilities", 0)
            a = wc / ta
            b = y.get("retained_earnings", 0) / ta
            c = y.get("ebit_proxy", 0) / ta
            e = y.get("sales", 0) / ta
            w.writerow([fy, f"{a:.4f}", f"{b:.4f}", f"{c:.4f}", f"{e:.4f}", "", ""])
    return facts_file


def main() -> None:
    refresh = "--refresh" in sys.argv
    client = EdgarClient()  # rate-limit 0.1 s + User-Agent du .env

    for company in COMPANIES:
        print(f"\n=== {company['label']}")
        cik = resolve_cik(client, company)
        print(f"  CIK: {cik}")
        facts = load_facts(client, cik, refresh)

        gaap = facts.get("facts", {}).get("us-gaap", {})
        if not gaap:
            # Découverte typique de phase 0 : dépôts d'avant l'ère XBRL
            # (obligatoire depuis ~2009) n'ont AUCUN fait structuré.
            print("  !! AUCUNE donnée XBRL (dépôts antérieurs à l'ère XBRL ?)")
            print("     -> entreprise à remplacer dans le trio de la phase 0")
            continue

        rows, per_year, notes = build_rows(cik, facts["facts"])
        out = write_outputs(company["slug"], rows, per_year)
        years = sorted(per_year)
        print(f"  années fiscales: {years[0]}–{years[-1]} ({len(years)} ans)" if years else "  aucune année")
        print(f"  variantes retenues: {', '.join(n for n in notes if not n.startswith('manquant')) or '—'}")
        print(f"  manques: {', '.join(n[8:] for n in notes if n.startswith('manquant')) or '—'}")
        print(f"  sorties: {out} + ratios.csv")

    print(
        "\nRappel phase 0 : le Z-score reste À CALCULER À LA MAIN dans le tableur "
        "(colonne vide duu ratios.csv). D = valeur boursière : il faut d'abord "
        "choisir une source de cours (semaine 1)."
    )


if __name__ == "__main__":
    main()
