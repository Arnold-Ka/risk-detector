"""Phase 0 — colonne D du Z d'Altman : cours de bourse + valeur de marché.

La feuille de route (§5, semaine 1) impose de CHOISIR une source de cours.
Choix retenu : **API chart de Yahoo Finance** (JSON, sans clé, historique
long). Sources écartées après test : stooq (challenge JavaScript anti-bot),
Nasdaq API (titre purgé après delisting), WSJ (captcha DataDome), Yahoo
pour le symbole BBBY (ticker recyclé par une autre société depuis 2026).

Pour CHAQUE année de `data/phase0/<slug>_ratios.csv` :
  1. date de fin de période du bilan (colonne `period_end` du concept
     total_assets dans facts.csv) ;
  2. résolution de D par ordre de fiabilité (colonne `source_D`) :
       a. `yahoo+dei` : dernier cours ≤ date de bilan × parts
          EntityCommonStockSharesOutstanding — la plus précise ;
       b. `flottant_sec` : dei:EntityPublicFloat (mesuré ~6 mois avant le
          bilan, exclut les titres détenus par des initiés) — repli
          indispensable pour les titres DELISTÉS (BBBY : aucun service de
          cours gratuit ne garde l'historique) ;
       c. `yahoo+parts_ponderees` : cours × WeightedAverageNumber…Basic —
          dernier repli, approximation documentée (écart important si le
          nombre d'actions a bougé dans l'exercice, ex. AMC 2021) ;
       d. sinon : vide (règle produit « donnée manquante » > fausse valeur).

Piège géré : Yahoo renvoie des cours AJUSTÉS pour les splits (Apple 7:1
en 07/2014, 4:1 en 08/2020 ; AMC reverse 1:8 en 08/2023) alors que les
parts de l'XBRL sont brutes, telles déposées à l'époque. On désajuste
chaque cours en le multipliant par le facteur des splits survenus APRÈS
sa date (`raw_close`) — sans cela Apple 2013 serait valorisé ×7 trop bas.

Repères de validation (imprimés à chaque exécution) :
  - Apple fin 2013 : ~0,94 Md d'actions × ~483 $ ≈ 434 Md$ (valeur réelle) ;
  - Apple sept. 2014 (post 7:1) : ~6 Md d'actions × ~101 $ ≈ 590 Md$ ;
  - AMC flottant au 30/06/2021 : 29,1 Md$ ↔ 513 M d'actions ≈ 57 $
    (cours réel de l'époque) — contrôle croisé flottant ↔ cours.

PROTÉGÈRE D'ORDRE : relancer TOUJOURS fetch_phase0 AVANT fetch_prices
(régénère ratios.csv sans colonnes ; fetch_prices les (ré)ajoute,
c'est idempotent).

Lancement (depuis la racine) :
    uv run python -m scripts.fetch_prices
    uv run python -m scripts.fetch_prices --refresh
"""

import csv
import json
import sys
import time
from pathlib import Path

import httpx

# Même trio que scripts/fetch_phase0.py (verrouillé le 2026-10-12).
COMPANIES = [
    {"slug": "apple_healthy", "label": "Apple", "symbol": "AAPL"},
    {"slug": "amc_distressed", "label": "AMC", "symbol": "AMC"},
    {"slug": "bbby_bankrupt", "label": "Bed Bath & Beyond", "symbol": "BBBY"},
]

CACHE_DIR = Path("data/cache")
OUT_DIR = Path("data/phase0")

# Colonnes de base de ratios.csv (fetch_phase0) — fetch_prices est
# idempotent : on re-saute toujours à ces 7 colonnes avant d'ajouter les siennes.
BASE_COLS = 7

# 1995 : couvre tous les exercices du trio (Apple commence en 2007).
PERIOD1 = 788918400  # 1995-01-01T00:00:00Z
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"  # Yahoo exige un UA navigateur

ADDED_COLS = ["date_valeur", "cours", "capitalisation", "dettes_totales", "source_D"]


def fetch_history(symbol: str, refresh: bool) -> dict | None:
    """Historique quotidien complet + splits, avec cache fichier.

    Retourne None si le symbole n'existe plus chez Yahoo (titre delisté
    dont le ticker a été recyclé ou purgé) — pas d'erreur, repli flottant.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"prices_{symbol}.json"
    if cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    try:
        resp = httpx.get(
            CHART_URL.format(symbol=symbol),
            params={
                "period1": PERIOD1,
                "period2": int(time.time()),
                "interval": "1d",
                "events": "split",  # événements de split pour le désajustement
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        print(f"  ! réseau Yahoo, {symbol}: {exc}")
        return None
    if resp.status_code == 404:
        return None  # symbole introuvable / purgé
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("chart", {}).get("result"):
        return None
    ts = payload["chart"]["result"][0].get("timestamp", [])
    # Symbole recyclé : série très courte commençant récemment = ce n'est
    # plus l'émetteur d'origine (BBBY est devenu une autre société chez
    # Yahoo : 61 points depuis juillet 2026) → traiter comme indisponible.
    if ts and len(ts) < 500 and ts[0] > time.time() - 3 * 365 * 86400:
        return None
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def daily_closes(payload: dict | None) -> list[tuple[str, float]]:
    """Journalier [(date AAAA-MM-JC, cours ajusté)] — None exclu (jours fermés)."""
    if payload is None:
        return []
    result = payload["chart"]["result"][0]
    ts_list = result.get("timestamp", [])
    closes = result["indicators"]["quote"][0]["close"]
    out = []
    for ts, close in zip(ts_list, closes):
        if close is None:
            continue
        out.append((time.strftime("%Y-%m-%d", time.gmtime(ts)), close))
    return out


def splits_after(payload: dict | None) -> list[tuple[str, float]]:
    """[(date du split, facteur num/dénominateur)] triés croissant.

    Yahoo a déjà divisé les cours antérieurs par ce facteur ; pour
    retrouver le cours BRUT de l'époque, on multiplie le cours ajusté par
    le produit des facteurs des splits survenus APRÈS sa date.
    """
    if payload is None:
        return []
    result = payload["chart"]["result"][0]
    events = result.get("events", {}).get("splits", {}) or {}
    out = []
    for ev in events.values():
        factor = ev["numerator"] / ev["denominator"]
        out.append((time.strftime("%Y-%m-%d", time.gmtime(ev["date"])), factor))
    return sorted(out)


def raw_close(date: str, adj_close: float, splits: list[tuple[str, float]]) -> float:
    factor = 1.0
    for split_date, ratio in splits:
        if split_date > date:
            factor *= ratio
    return adj_close * factor


def read_facts(slug: str) -> tuple[dict[int, dict[str, dict]], list[tuple[str, float]]]:
    """facts.csv -> ({année: {concept: {value, period_end}}}, [(date, valeur) des flottants]).

    Les flottants sont extraits en liste PLATTE car leur date (≈ 6 mois
    avant chaque bilan) ne coïncide pas avec l'année-clé des ratios : on
    fera « dernier flottant ≤ date de bilan ».
    """
    per_year: dict[int, dict[str, dict]] = {}
    with (OUT_DIR / f"{slug}_facts.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            per_year.setdefault(int(row["year"]), {})[row["concept"]] = {
                "value": float(row["value"]),
                "period_end": row["period_end"],
            }
    floats = sorted(
        (node["period_end"], node["value"])
        for year_map in per_year.values()
        for concept, node in year_map.items()
        if concept == "public_float"
    )
    return per_year, floats


def read_ratios(slug: str) -> tuple[list[str], list[list[str]]]:
    """En-tête + lignes, ramenés aux 7 colonnes de base (idempotent)."""
    with (OUT_DIR / f"{slug}_ratios.csv").open(encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)[:BASE_COLS]
        return header, [r[:BASE_COLS] for r in reader]


def process(company: dict, refresh: bool) -> None:
    slug = company["slug"]
    symbol = company["symbol"]
    print(f"\n=== {company['label']} ({symbol})")

    payload = fetch_history(symbol, refresh)
    closes = daily_closes(payload)
    splits = splits_after(payload)
    dates = [d for d, _ in closes]

    facts, floats = read_facts(slug)
    header, rows = read_ratios(slug)
    out_header = header + ADDED_COLS
    out_rows: list[list[str]] = []
    stats: dict[str, int] = {}

    for r in rows:
        year = int(r[0])
        r[5] = ""  # colonne D de base : ré-écrite à chaque passage (idempotent)
        y_facts = facts.get(year, {})
        ta = y_facts.get("total_assets")
        liab = y_facts.get("total_liabilities")
        if not (ta and liab):
            out_rows.append(r + ["", "", "", "", ""])
            stats["sans_bilan"] = stats.get("sans_bilan", 0) + 1
            continue

        balance_date = ta["period_end"]  # date du bilan = repère de valorisation
        liab_value = liab["value"]

        # --- (a) cours Yahoo ≤ date de bilan, désajusté des splits -------
        price = None
        idx = max((i for i, d in enumerate(dates) if d <= balance_date), default=None)
        if idx is not None:
            price_date, adj = closes[idx]
            price = (price_date, raw_close(price_date, adj, splits))

        dei = y_facts.get("shares_outstanding")
        wavg = y_facts.get("shares_weighted_basic")

        cap = date_val = cours = source = ""

        if price and dei:
            # (a) la plus précise : cours au bilan × parts telles déposées.
            date_val, cours = price
            cap = float(cours) * dei["value"]
            source = "yahoo+dei"
        else:
            # (b) dernier flottant SEC mesuré AVANT le bilan (~6 mois avant).
            eligible = [f for f in floats if f[0] <= balance_date]
            if eligible:
                f_date, f_val = eligible[-1]
                # Flottant acceptable seulement s'il appartient bien à
                # l'exercice en cours : mesuré dans les ~12 mois précédant
                # le bilan (cas réels : 6 mois pour émetteurs à exercice
                # décalé, ~6 mois pour calendriers). age_days = approx. jours.
                age_days = (
                    (int(balance_date[:4]) - int(f_date[:4])) * 365
                    + (int(balance_date[5:7]) - int(f_date[5:7])) * 30
                )
                if age_days <= 365:
                    date_val, cap, source = f_date, f_val, "flottant_sec"
            if not source and price and wavg:
                # (c) dernier repli : parts pondérées moyennes (approximation).
                date_val, cours = price
                cap = float(cours) * wavg["value"]
                source = "yahoo+parts_ponderees"

        if not source:
            out_rows.append(r + ["", "", "", "", ""])
            stats["vide"] = stats.get("vide", 0) + 1
            continue

        # D s'écrit dans la colonne de base (index 5), pas en doublon.
        r[5] = f"{float(cap) / liab_value:.4f}"
        out_rows.append(
            r
            + [
                date_val,
                cours,
                f"{float(cap):.0f}",
                f"{liab_value:.0f}",
                source,
            ]
        )
        stats[source] = stats.get(source, 0) + 1

    with (OUT_DIR / f"{slug}_ratios.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(out_header)
        w.writerows(out_rows)

    print(f"  couverture: {dict(stats)}")
    # Contrôles : capitalisation des années repères (validation visuelle).
    for probe in ("2013", "2014", "2021", "2022", "2023"):
        for r in out_rows:
            if r[0] == probe and r[5]:
                # r = [year,A,B,C,E,D,Z] + [date,cours,cap,dettes,source]
                print(
                    f"  contrôle {probe}: date {r[-5]}, "
                    f"cours {format(float(r[-4]), '.2f') if r[-4] else '—'}, "
                    f"cap {r[-3]}, D={r[5]} ({r[-1]})"
                )


def main() -> None:
    refresh = "--refresh" in sys.argv
    for company in COMPANIES:
        process(company, refresh)
    print(
        "\nD = valeur de marché / dettes totales book (voir source_D). "
        "Z reste à CALCULER À LA MAIN (gate phase 0)."
    )


if __name__ == "__main__":
    main()
