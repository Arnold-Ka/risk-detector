"""Phase 1 — contrôle d'extraction sur 20 sociétés connues.

Feuille de route §6 (semaine 3-4), livrable « tests automatisés sur
20 sociétés connues » : xbrl_map.yaml + app.normalize.loader doivent
tenir sur un échantillon varié (tech, santé, énergie, consommation,
télécom, banque), pas seulement sur le trio de référence de la phase 0.

Pour CHAQUE société :
  1. résolution du CIK via le fichier officiel company_tickers.json
     (une seule requête, mise en cache par le client) ;
  2. companyfacts via scripts.fetch_phase0.load_facts (cache data/cache/) ;
  3. app.normalize.loader.extract — LE MÊME chemin que la production,
     aucune logique dupliquée ici ;
  4. contrôles d'invariants :
       ÉCHEC (code retour 1) :
         - extraction vide / 404 ;
         - total_assets absent ou <= 0 à n'importe quelle date ;
         - current_assets > total_assets sur une même date (impossible
           en bilan : détecte un mélange de sources ou de dates) ;
         - sales négatif (tag de repli qui attrape les contre-passations).
       AVERTISSEMENT (ne fait pas échouer) :
         - couverture < 18 des 22 concepts (banques/assurances n'ont pas
           de bilan classique → les signaux seront filtrés par
           companies.sector_group, règle produit) ;
         - identité A ≈ L + SC écartée de plus de 10 % (minoritaires,
           titres hybrides…) — à surveiller, pas bloquant.

Lancement (depuis la racine) :
    uv run python -m scripts/verify_known
Premier lancement : ~20 téléchargements SEC (30-90 s, cache ensuite).
Code retour 0 = tout vert ; 1 = au moins un échec.
"""

import json
import sys

from app.edgar.client import EdgarClient
from app.normalize.loader import extract, load_map
from scripts.fetch_phase0 import TICKERS_URL, load_facts

# 20 émetteurs liquides et documentés, un éventail de secteurs volontairement
# hétérogène. JPM = contrôle « banque » : le filtre sector_group des
# signaux est pensé pour ce cas (cf. feuille de route §3).
TICKERS = [
    "AAPL", "MSFT", "INTC", "CSCO",          # informatique
    "JNJ", "MRK", "PFE", "ABT",              # santé / pharma
    "XOM", "CVX",                            # énergie
    "KO", "PEP", "PG", "MCD", "HD", "DIS",   # consommation
    "VZ", "T",                               # télécom
    "WMT", "JPM",                            # distribution + banque
]

# Couverture minimale des 22 concepts de xbrl_map.yaml avant alerte.
MIN_CONCEPTS = 18
# Tolérance sur l'identité bilancielle A ≈ L + capitaux propres.
IDENTITY_TOLERANCE = 0.10

# Repli de CIK quand company_tickers.json pointe vers une entité VIDE.
# 2026 : le fichier officiel ne contient plus pour XOM que
# « ExxonMobil Holdings Corp » (CIK 2115436, holding créée lors d'une
# reorganisation, AUCUN fait XBRL) — l'entité d'exploitation historique,
# qui porte les 10-K depuis 1920, reste CIK 34088 (438 tags).
# Contrôle : companyfacts du CIK du repli non vide, sinon échec assumé.
CIK_FALLBACK = {"XOM": 34088}


def resolve_ciks(client: EdgarClient, tickers: list[str]) -> dict[str, int]:
    """tickers -> CIK via le fichier officiel (1 requête, puis cache)."""
    data = json.loads(client.get(TICKERS_URL))
    wanted = {t.upper() for t in tickers}
    found: dict[str, int] = {}
    for row in data.values():
        ticker = row["ticker"].upper()
        if ticker in wanted:
            found[ticker] = int(row["cik_str"])
    return found


def check(facts_rows: list[dict], n_concepts_map: int) -> tuple[list[str], list[str]]:
    """Contrôles d'invariants → (échecs, avertissements)."""
    failures: list[str] = []
    warnings: list[str] = []
    if not facts_rows:
        return ["extraction vide (404 ou aucun fait 10-K exploitable)"], []

    by_concept: dict[str, dict[str, float]] = {}
    for r in facts_rows:
        by_concept.setdefault(r["concept"], {})[r["period_end"]] = r["value"]

    # Échecs durs -----------------------------------------------------------
    if "total_assets" not in by_concept:
        failures.append("total_assets absent")
    else:
        bad = [d for d, v in by_concept["total_assets"].items() if v <= 0]
        if bad:
            failures.append(f"total_assets <= 0 le {sorted(bad)}")

    # Les deux doivent exister À LA MÊME date de bilan pour être comparables.
    ca = by_concept.get("current_assets", {})
    ta = by_concept.get("total_assets", {})
    for d in sorted(set(ca) & set(ta)):
        if ca[d] > ta[d]:
            failures.append(f"current_assets > total_assets le {d} ({ca[d]:.3g} > {ta[d]:.3g})")

    sales = by_concept.get("sales", {})
    neg = [d for d, v in sales.items() if v < 0]
    if neg:
        failures.append(f"sales < 0 le {sorted(neg)}")

    # Avertissements --------------------------------------------------------
    coverage = len(by_concept)
    if coverage < MIN_CONCEPTS:
        warnings.append(
            f"couverture faible : {coverage}/{n_concepts_map} concepts "
            "(secteur sans bilan classique ? voir sector_group)"
        )

    # A = L + SC (sans minoritaires significatifs) : contrôle de cohérence
    # interne des données, pas une égalité comptable stricte.
    liab = by_concept.get("total_liabilities", {})
    se = by_concept.get("stockholders_equity", {})
    gaps = []
    for d in sorted(set(ta) & set(liab) & set(se)):
        if ta[d] == 0:
            continue
        gap = abs(ta[d] - (liab[d] + se[d])) / abs(ta[d])
        if gap > IDENTITY_TOLERANCE:
            gaps.append(f"{d} ({gap:.0%})")
    if gaps:
        # "~=" et non "≈" : console Windows cp1252 (voir note d'encodage
        # dans main).
        warnings.append("identite A ~= L + SC ecartee : " + ", ".join(gaps[:3]))

    return failures, warnings


def main() -> None:
    # Console Windows cp1252 : é/à passent, ≈ et ─ plantent avec
    # UnicodeEncodeError. On remplace le caractère par '?' plutôt que de
    # faire tomber le contrôle en plein milieu (les messages sont de toute
    # façon conçus pour rester ASCII).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    client = EdgarClient()
    specs = load_map()
    ciks = resolve_ciks(client, TICKERS)

    missing_tickers = sorted(set(t.upper() for t in TICKERS) - set(ciks))
    if missing_tickers:
        # Un ticker retiré de company_tickers.json (delisting) : signalé
        # comme échec — la résolution dynamique fait partie du contrat.
        print(f"! introuvable(s) dans company_tickers.json : {missing_tickers}")

    print(f"=== Contrôle extraction — {len(TICKERS)} sociétés connues ===")
    print(f"{'ticker':<7} {'cik':>7} {'nom':<26} {'faits':>5} {'conc':>5} {'exercices':<13} verdict")

    n_failed = 0
    n_warned = 0
    for ticker in TICKERS:
        t = ticker.upper()
        if t not in ciks:
            n_failed += 1
            print(f"{t:<7} {'-':>7} {'(CIK introuvable)':<26} {'-':>5} {'-':>5} {'-':<13} ÉCHEC")
            continue
        cik = ciks[t]
        companyfacts = load_facts(client, cik, refresh=False)
        rows = extract(companyfacts) if companyfacts else []
        # Piège company_tickers.json : la holding « ExxonMobil Holdings »
        # (CIK 2115436) répond 200 avec ses propres 94 tags us-gaap mais
        # AUCUN fait 10-K exploitable (reorganisation 2026) → extraction
        # vide. Le critère de repli est donc le résultat de l'extraction,
        # pas l'absence de namespace. L'entité d'exploitation historique
        # (CIK 34088, 438 tags) reste la bonne.
        if not rows and t in CIK_FALLBACK:
            cik = CIK_FALLBACK[t]
            companyfacts = load_facts(client, cik, refresh=False)
            rows = extract(companyfacts) if companyfacts else []
            print(f"  ({t}: repli CIK {cik} — holding sans fait 10-K exploitable)")
        name = (companyfacts.get("entityName") if companyfacts else None) or "(inconnu)"
        failures, warnings = check(rows, len(specs))

        years = sorted({r["period_end"][:4] for r in rows})
        span = f"{years[0]}-{years[-1]}" if years else "—"
        coverage = len({r["concept"] for r in rows})

        if failures:
            verdict = "ÉCHEC"
            n_failed += 1
        elif warnings:
            verdict = f"OK ({len(warnings)} avert.)"
            n_warned += 1
        else:
            verdict = "OK"
        print(f"{t:<7} {cik:>7} {name[:26]:<26} {len(rows):>5} {coverage:>5} {span:<13} {verdict}")
        # Marqueurs ASCII purs : la console Windows (cp1252) refuse les
        # tirets box-drawing (└─) → UnicodeEncodeError au print.
        for msg in failures:
            print(f"         - ECHEC {ticker} : {msg}")
        for msg in warnings:
            print(f"         - avert. {ticker} : {msg}")

    print(f"\n{len(TICKERS)} contrôles : {n_failed} échec(s), {n_warned} société(s) avec avertissement(s).")
    sys.exit(1 if (n_failed or missing_tickers) else 0)


if __name__ == "__main__":
    main()
