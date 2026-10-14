"""Backtest — constitution des cohortes (roadmap §6, semaines 7-8).

Étape FETCH du backtest : ne fait QUE remplir le cache (EdgarClient :
rate limit 10 req/s, User-Agent, écriture atomique) puis écrire le
manifeste d'ingestion `data/backtest/companies.json`. La mise en base
reste `scripts.load_postgres --manifest …`, les signaux restent
`app.jobs.nightly` — le même moteur que pour le trio de phase 0.

Chaîne de construction (choix validés 2026-10-13) :
  1. FTS EDGAR, requête « Item 1.03 », form 8-K, année par année 2015→2025
     → candidats faillite avec date exacte, CIK et SIC (primaire) ;
  2. catégories Wikipedia « Chapter 11 en YYYY » → les titres sans équivalent
     FTS sont résolus par la recherche d'entreprise EDGAR (atom) ; un titre
     sans CIK = société non cotée / sans dépôt → écarté silencieusement
     (compté dans le rapport) ;
  3. pour CHAQUE candidat : submissions comme juge de paix — ancre =
     premier 8-K item 1.03 dans la fenêtre (même définition que le signal
     critical_8k produit), SIC officiel, exclusion 6000-6799 (banques,
     assurances, REIT : scores non fiables, spec) ;
  4. companyfacts → couverture : ≥ 5 exercices sur les 6 ans avant faillite
     (mesurée avec app.normalize.loader.extract, le moteur des signaux) ;
  5. témoins : écran S&P 500 (CIK dans la table Wikipedia) — jamais 1.03,
     10-K continus, toujours coté, non-financier — puis échantillonnage
     proportionnel au SIC 2 chiffres du cohort (« comparables »).

Lancement (depuis la racine, ~10-15 min au premier run, quasi instantané
ensuite grâce au cache) :
    uv run python -m scripts.build_cohort
"""

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote_plus

import httpx

from app.backtest.cohort import (
    control_coverage,
    control_screen,
    coverage_ok,
    first_item_103,
    is_financial,
    make_slug,
    parse_fts_hits,
    pre_failure_years,
    sample_controls,
    save_manifest,
    sector_group_for_sic,
    title_matches_entity,
)
from app.edgar.client import EdgarClient
from app.edgar.submissions import MAIN_URL, load_filing_rows
from scripts.fetch_phase0 import load_facts

OUT = Path("data/backtest/companies.json")

# --- Sources ----------------------------------------------------------------

# Recherche plein texte SEC : https://efts.sec.gov/LATEST/search-index
# (params dans l'URL — le cache d'EdgarClient est indexé sur l'URL complète,
# les params séparés seraient ignorés et les pages se remplaceraient).
FTS_URL = (
    "https://efts.sec.gov/LATEST/search-index"
    "?q=%22Item+1.03%22&forms=8-K&startdt={start}&enddt={end}&from={from_}&size=100"
)

# Catégories Wikipedia par année (API MediaWiki, JSON, une requête par année).
WIKI_CAT_URL = (
    "https://en.wikipedia.org/w/api.php"
    "?action=query&list=categorymembers"
    "&cmtitle=Category:Companies%20that%20filed%20for%20Chapter%2011%20bankruptcy%20in%20{year}"
    "&cmtype=page&cmlimit=500&format=json"
)

# Recherche d'entreprise EDGAR par nom (atom) — résolution des titres
# Wikipedia sans équivalent FTS. type=10-K : seules les entreprises qui
# déposent (ou ont déposé) des rapports annuels ressortent.
EDGAR_NAME_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&company={name}&type=10-K&count=40&output=atom"
)

# Table S&P 500 sur Wikipedia (colonnes Symbol / GICS Sector / CIK).
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def get_retry(client: EdgarClient, url: str, tries: int = 4) -> bytes:
    """client.get avec reprise sur 5xx/429 — le FTS renvoie parfois un 500
    transitoire (les erreurs ne sont JAMAIS mises en cache par EdgarClient,
    donc rejouer est sûr ; backoff 2 s, 4 s, 8 s)."""
    for attempt in range(tries):
        try:
            return client.get(url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status < 500 and status != 429:
                raise
            if attempt == tries - 1:
                raise
            delay = 2 * (2 ** attempt)
            print(f"  ! HTTP {status} sur {url[:80]}… — nouvelle tentative dans {delay}s")
            time.sleep(delay)


def scan_fts(client: EdgarClient) -> dict[int, dict]:
    """Candidats faillite 2015-2025 depuis la recherche plein texte SEC."""
    merged: dict[int, dict] = {}
    for year in range(2015, 2026):
        start, end = f"{year}-01-01", f"{year}-12-31"
        offset = 0
        while True:
            url = FTS_URL.format(start=start, end=end, from_=offset)
            page = json.loads(get_retry(client, url))
            hits = page["hits"]["hits"]
            sources = [h["_source"] for h in hits]
            year_hits = parse_fts_hits(sources, year)
            for cik, cand in year_hits.items():
                prev = merged.get(cik)
                if prev is None or cand["bankruptcy_date"] < prev["bankruptcy_date"]:
                    merged[cik] = cand
            total = page["hits"]["total"]["value"]
            offset += len(hits)
            if not hits or offset >= min(total, 9900):  # fenêtre FTS = 10 000
                break
        print(f"  FTS {year}: {offset} hits cumulés -> {len(merged)} CIK uniques")
    return merged


def wiki_members(client: EdgarClient) -> list[str]:
    """Titres des catégories Wikipedia « Chapter 11 en YYYY » (2015-2025)."""
    titles: list[str] = []
    for year in range(2015, 2026):
        payload = json.loads(get_retry(client, WIKI_CAT_URL.format(year=year)))
        members = payload.get("query", {}).get("categorymembers", [])
        titles.extend(m["title"] for m in members)
        print(f"  Wikipedia {year}: {len(members)} pages")
    # Un même article peut être dans deux catégories (double faillite) :
    # dédupliqué ici, puis par CIK après résolution EDGAR.
    return sorted(set(titles))


def resolve_edgar_cik(client: EdgarClient, title: str) -> int | None:
    """Recherche atom EDGAR par nom de titre Wikipedia -> premier CIK, ou None.

    Motifs de None (comptés dans le rapport final) : société privée sans
    dépôt SEC (restaurants, églises, hôpitaux des catégories), nom trop
    ambigu sans correspondance, résolution déjà couverte par le FTS.
    """
    xml = get_retry(client, EDGAR_NAME_URL.format(name=quote_plus(title))).decode(
        "utf-8", "replace"
    )
    # Plusieurs formes dans les flux atom/HTML d'EDGAR : balise <cik> pure,
    # ou « CIK=0000320193 » dans un lien, ou « (CIK 0000320199) ».
    for pattern in (r"<cik>(\d+)</cik>", r"CIK=(\d{10})", r"CIK\s*(\d{10})"):
        m = re.search(pattern, xml, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def parse_sp500(html_text: str) -> list[dict]:
    """Table des constituants S&P 500 -> [{cik, ticker, sector}], dédupliqué.

    Certaines lignes sont des actions multiples d'un MÊME émetteur (NWSA/NWS,
    GOOGL/GOOG, FOXA/FOX → un CIK, deux tickers) : dédup par CIK, première
    ligne gagne (le ticker sert seulement à Yahoo, les cours des deux classes
    restent proches — approximation documentée, négligeable pour le backtest).
    """
    table = re.search(r'<table[^>]*id="constituents".*?</table>', html_text, re.S)
    if not table:
        raise SystemExit("Table S&P 500 introuvable dans la page Wikipedia")
    rows: list[dict] = []
    seen_ciks: set[int] = set()
    # Les <tr>/<td> de Wikipedia portent des attributs (id, class) :
    # `<tr[^>]*>` et non `<tr>` — sinon zéro ligne parsée.
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) < 7:
            continue  # en-tête ou ligne vide

        def clean(cell: str) -> str:
            return re.sub(r"<[^>]+>", "", cell).strip()

        ticker, sector, cik = clean(cells[0]), clean(cells[2]), clean(cells[6])
        if not cik.isdigit() or int(cik) in seen_ciks:
            continue
        seen_ciks.add(int(cik))
        rows.append({"cik": int(cik), "ticker": ticker, "sector": sector})
    return rows


def main() -> None:
    # Console Windows (cp1252) : un caractère exotique (≥, ✓…) ne doit
    # JAMAIS planter un run de 15 minutes — remplacer au lieu d'échouer.
    sys.stdout.reconfigure(errors="replace")
    client = EdgarClient()

    # --- 1. FTS primaire ----------------------------------------------------
    print("=== 1. Scan FTS EDGAR (8-K Item 1.03, 2015-2025)")
    fts = scan_fts(client)
    print(f"  -> {len(fts)} CIK avec 1.03 dans la fenêtre")

    # --- 2. Wikipedia secondaire --------------------------------------------
    print("=== 2. Catégories Wikipedia + résolution EDGAR des restes")
    titles = wiki_members(client)
    fts_names = [c["name"] for c in fts.values()]
    leftover = [t for t in titles if not any(title_matches_entity(t, n) for n in fts_names)]
    print(f"  {len(titles)} titres uniques, dont {len(leftover)} sans équivalent FTS")

    wiki_added: dict[int, dict] = {}
    no_sec = ambiguous = 0
    for i, title in enumerate(leftover, 1):
        cik = resolve_edgar_cik(client, title)
        if cik is None:
            no_sec += 1
        elif cik in fts or cik in wiki_added:
            ambiguous += 0  # déjà couvert : pas une anomalie
        else:
            wiki_added[cik] = {"cik": cik, "name": title, "source": "wikipedia"}
        if i % 100 == 0:
            print(f"  résolution: {i}/{len(leftover)} "
                  f"(+{len(wiki_added)} candidats, {no_sec} sans dépôt SEC)")
    print(f"  -> {len(wiki_added)} candidats supplémentaires via Wikipedia "
          f"({no_sec} titres sans émetteur SEC — privé/non déposé)")

    candidates = dict(fts)
    candidates.update(wiki_added)

    # --- 3. Vérification submissions (ancre + SIC) --------------------------
    print(f"=== 3. Submissions: ancre 1.03 + SIC pour {len(candidates)} candidats")
    cohort: list[dict] = []
    stats = Counter()
    for i, cand in enumerate(sorted(candidates.values(), key=lambda c: c["cik"]), 1):
        cik = cand["cik"]
        try:
            main_json = json.loads(get_retry(client, MAIN_URL.format(cik=cik)))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                stats["cik_inexistant"] += 1
                continue
            raise
        rows = load_filing_rows(client, cik)
        hit = first_item_103(rows)
        if hit is None:
            stats["sans_1.03_valide"] += 1
            continue
        bankruptcy_date, accession = hit
        sic = cand.get("sic")
        if sic is None:
            sic = int(main_json["sic"]) if main_json.get("sic") else None
        if is_financial(sic):
            stats["financier_sic"] += 1
            continue
        cohort.append(
            {
                "cik": cik,
                "name": cand.get("name") or main_json.get("name") or f"CIK {cik}",
                "ticker": (main_json.get("tickers") or [None])[0],
                "sic": sic,
                "sector_group": sector_group_for_sic(sic),
                "bankruptcy_date": bankruptcy_date,
                "bankruptcy_accession": accession,
                "source": cand["source"],
            }
        )
        if i % 50 == 0:
            print(f"  candidat {i}/{len(candidates)} -> {len(cohort)} retenus "
                  f"({dict(stats)})")
    print(f"  -> {len(cohort)} faillites candidates après submissions ({dict(stats)})")

    # --- 4. Couverture companyfacts -----------------------------------------
    # ASCII ">=" : la console Windows cp1252 refuse « ≥ ».
    print("=== 4. Couverture XBRL (>= 5 exercices sur les 6 ans avant faillite)")
    covered: list[dict] = []
    for i, cand in enumerate(cohort, 1):
        facts = load_facts(client, cand["cik"], refresh=False)
        if not facts.get("facts", {}).get("us-gaap"):
            stats["sans_xbrl"] += 1
            continue
        years = sorted(pre_failure_years(facts, cand["bankruptcy_date"]))
        if not coverage_ok(facts, cand["bankruptcy_date"]):
            stats["couverture_insuffisante"] += 1
            continue
        cand["years_pre_failure"] = years
        covered.append(cand)
        if i % 50 == 0:
            print(f"  couverture: {i}/{len(cohort)} -> {len(covered)} retenus")
    print(f"  -> {len(covered)} faillites avec >= 5 exercices pré-faillite "
          f"({dict(stats)})")

    # --- 5. Écran témoins S&P 500 --------------------------------------------
    print("=== 5. Écran S&P 500 (témoins sains comparables)")
    sp = parse_sp500(get_retry(client, SP500_URL).decode("utf-8", "replace"))
    print(f"  {len(sp)} constituants S&P 500")
    controls: list[dict] = []
    screen_stats = Counter()
    for i, member in enumerate(sp, 1):
        cik = member["cik"]
        try:
            main_json = json.loads(get_retry(client, MAIN_URL.format(cik=cik)))
        except httpx.HTTPStatusError:
            screen_stats["cik_invalide"] += 1
            continue
        rows = load_filing_rows(client, cik)
        ok, reasons = control_screen(rows)
        if not ok:
            for r in reasons:
                screen_stats[r] += 1
            continue
        sic = int(main_json["sic"]) if main_json.get("sic") else None
        if is_financial(sic):
            screen_stats["financier_sic"] += 1
            continue
        facts = load_facts(client, cik, refresh=False)
        if not control_coverage(facts):
            screen_stats["couverture_insuffisante"] += 1
            continue
        controls.append(
            {
                "cik": cik,
                "name": main_json.get("name") or member["sector"],
                "ticker": member["ticker"],
                "sic": sic,
                "sector_group": sector_group_for_sic(sic),
            }
        )
        if i % 100 == 0:
            print(f"  écran: {i}/{len(sp)} -> {len(controls)} témoins")
    print(f"  -> {len(controls)} témoins éligibles ({dict(screen_stats)})")

    # --- 6. Échantillonnage + manifeste -------------------------------------
    target = min(len(controls), max(len(covered), 100))
    picked = sample_controls(controls, covered, target=target)
    print(f"=== 6. Manifeste: {len(covered)} faillites + {len(picked)} témoins "
          f"(cible {target})")

    entries: list[dict] = []
    for cand in covered:
        year = cand["bankruptcy_date"][:4]
        entries.append(
            {
                "cik": cand["cik"],
                "slug": make_slug(cand["cik"], cand["ticker"], cand["name"]),
                "label": f"{cand['name']} (faillie {year})",
                "name": cand["name"],
                "ticker": cand["ticker"],
                "sic": cand["sic"],
                "sector_group": cand["sector_group"],
                "group": "cohort",
                "bankruptcy_date": cand["bankruptcy_date"],
            }
        )
    for ctrl in picked:
        entries.append(
            {
                "cik": ctrl["cik"],
                "slug": make_slug(ctrl["cik"], ctrl["ticker"], ctrl["name"]),
                "label": f"{ctrl['name']} (témoin)",
                "name": ctrl["name"],
                "ticker": ctrl["ticker"],
                "sic": ctrl["sic"],
                "sector_group": ctrl["sector_group"],
                "group": "control",
                "bankruptcy_date": None,
            }
        )
    save_manifest(OUT, entries)

    sic_top = Counter(e["sic"] // 100 for e in entries if e["sic"])
    src_counts = Counter(c["source"] for c in covered)
    print(f"\nManifeste écrit : {OUT} ({len(entries)} entreprises)")
    print(f"  cohort : {len(covered)} faillites "
          f"(FTS {src_counts.get('fts', 0)}, Wikipedia {src_counts.get('wikipedia', 0)})")
    print(f"  témoins: {len(picked)} sains (S&P 500, proportionnel SIC)")
    print(f"  top SIC-2 : {sic_top.most_common(8)}")
    if len(covered) < 100:
        print("  !! ALERTE : moins de 100 faillites — gate feuille de route non atteint")
    print(
        "\nSuite : uv run python -m scripts.fetch_phase0 --manifest "
        f"{OUT} puis fetch_prices --manifest {OUT}, "
        f"fetch_submissions --manifest {OUT}, load_postgres --manifest {OUT}, "
        "app.jobs.nightly."
    )


if __name__ == "__main__":
    main()
