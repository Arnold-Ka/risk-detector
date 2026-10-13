"""Tests du chargeur normalisé (phase 1).

Trois niveaux :
  1. fixtures synthétiques — logique pure, toujours exécutées :
     fenêtre de durée, priorité de tags, restatement, VOTE DE MILLÉSIME ;
  2. invariants sur le trio réel (si `data/cache/companyfacts_*.json`
     présent) : ces contrôles tombent si une règle de sélection régresse
     (mélange de millésimes, tag retiré du YAML…) ;
  3. valeurs dorées (« goldens ») : chiffres SEC vérifiés à la main sur
     les dépôts sources — ils figent LA sélection attendue parmi les
     plusieurs candidats d'une même date.

Historique : des tests « d'accord » loader vs CSV phase 0 ont existé et
ont révélé les bugs de la phase 0 (trimestres fp=FY chez Apple, deux
dates de solde AMC). La phase 0 consomme désormais le chargeur lui-même
(un seul moteur) ; ces tests sont remplacés par les invariants + goldens.

Commande :
    uv run pytest tests/test_normalize.py -v
"""

import json
from datetime import date
from pathlib import Path

import pytest

from app.normalize.loader import ConceptSpec, extract, load_map

CACHE_DIR = Path("data/cache")

# Entreprises du trio + CIK verrouillés (décision 2026-10-12).
TRIO = [
    ("apple_healthy", "0000320193"),
    ("amc_distressed", "0001411579"),
    ("bbby_bankrupt", "0000886158"),
]

# Indicateurs que les signaux MVP exigent (Altman, Piotroski, Beneish,
# divergence, runway) — si l'un disparaît du YAML, un signal croule en
# silence : c'est ce test qui sonne l'alarme.
REQUIRED_FOR_SIGNALS = {
    "total_assets",
    "total_liabilities",
    "current_assets",
    "current_liabilities",
    "cash",
    "receivables",
    "stockholders_equity",
    "long_term_debt",
    "retained_earnings",
    "shares_outstanding",
    "public_float",
    "sales",
    "operating_income",
    "net_income",
    "gross_profit",
    "sga",
    "cfo",
    "shares_weighted_basic",
}

# --- helpers ----------------------------------------------------------------


def _load_trio(cik: str) -> dict:
    cache_file = CACHE_DIR / f"companyfacts_{cik}.json"
    if not cache_file.exists():
        pytest.skip(f"cache SEC absent ({cache_file}) — lancer fetch_phase0")
    return json.loads(cache_file.read_text(encoding="utf-8"))


def _by_concept(rows: list[dict]) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        out.setdefault(r["concept"], {})[r["period_end"]] = r
    return out


def _spec(key: str, kind: str, tags: tuple[str, ...], namespace: str = "us-gaap") -> ConceptSpec:
    return ConceptSpec(key=key, label=key, kind=kind, namespace=namespace, tags=tags)


def _instant(val: int, end: str, accn: str, filed: str) -> dict:
    return {"end": end, "val": val, "accn": accn, "fy": 0, "fp": "FY",
            "form": "10-K", "filed": filed}


# --- 1. fixtures synthétiques (toujours exécutées) --------------------------


def test_map_covers_all_signal_inputs():
    """La table de correspondance contient bien tous les indicateurs requis."""
    missing = REQUIRED_FOR_SIGNALS - set(load_map())
    assert not missing, f"indicateurs manquants dans xbrl_map.yaml: {sorted(missing)}"


def test_duration_window_rejects_quarterly_and_multiyear():
    """Seules les durées ~annuelles passent (trimestre et 5 ans écartés)."""
    spec = _spec("sales", "duration", ("Revenues",))
    node = {"units": {"USD": [
        # trimestre (~92 j) : rejeté
        {"start": "2023-01-01", "end": "2023-04-01", "val": 1, "accn": "a",
         "fp": "FY", "form": "10-K", "filed": "2023-06-01"},
        # annuel (365 j) : retenu
        {"start": "2023-01-01", "end": "2023-12-31", "val": 100, "accn": "b",
         "fp": "FY", "form": "10-K", "filed": "2024-03-01"},
        # synthèse pluriannuelle (~1826 j) : rejetée
        {"start": "2019-01-01", "end": "2023-12-31", "val": 500, "accn": "c",
         "fp": "FY", "form": "10-K", "filed": "2024-03-01"},
    ]}}
    rows = extract({"facts": {"us-gaap": {"Revenues": node}}}, specs={"sales": spec})
    assert [r["value"] for r in rows] == [100]


def test_variant_priority_and_year_filling():
    """Tag prioritaire gagne sur une même date ; les variantes comblent
    les autres années (fusion par date, cas du CA multi-tags)."""
    spec = _spec("sales", "duration", ("Revenues", "SalesRevenueGoodsNet"))
    # Durée annuelle : start = 1er janvier de l'année de `end` (le fait 2021
    # doit être 2021-01-01 → 2021-12-31, sinon fenêtre négative = rejeté).
    dur = lambda val, end, accn, filed: (  # noqa: E731 — lambda de confort
        {"start": f"{end[:4]}-01-01", "end": end, "val": val, "accn": accn,
         "fp": "FY", "form": "10-K", "filed": filed}
    )
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [dur(100, "2022-12-31", "a", "2023-03-01")]}},
        "SalesRevenueGoodsNet": {"units": {"USD": [
            dur(999, "2022-12-31", "b", "2023-03-01"),   # même date : perd
            dur(80, "2021-12-31", "c", "2022-03-01"),    # année comblée
        ]}},
    }}}
    rows = extract(facts, specs={"sales": spec})
    by_end = {r["period_end"]: r for r in rows}
    assert by_end["2022-12-31"]["value"] == 100
    assert by_end["2022-12-31"]["tag"] == "Revenues"
    assert by_end["2021-12-31"]["value"] == 80
    assert by_end["2021-12-31"]["tag"] == "SalesRevenueGoodsNet"


def test_restatement_prefers_latest_filing():
    """Sur une même date, le dépôt le plus récent gagne — concept isolé
    (vote à égalité de votes → tie-break sur filed)."""
    spec = _spec("total_assets", "instant", ("Assets",))
    node = {"units": {"USD": [
        _instant(100, "2023-12-31", "old", "2024-02-01"),
        _instant(120, "2023-12-31", "new", "2024-09-01"),
    ]}}
    rows = extract({"facts": {"us-gaap": {"Assets": node}}}, specs={"total_assets": spec})
    assert [r["value"] for r in rows] == [120]
    assert rows[0]["accn"] == "new"


def test_vintage_vote_uses_one_filing_per_balance_date():
    """Bilan « millésime » : tous les postes d'une même date viennent du
    dépôt gagnant au vote (majorité des concepts), jamais mélangés.

    Scénario = le bug Apple 2008 corrigé : le dépôt 2009 couvre actif +
    passif + capitaux propres (3 votes), le dépôt 2010 ne répète que
    actif + capitaux propres (2 votes) → gagne 2009, même si 2010 est
    plus récent et que chaque concept pris isolément préférerait 2010.
    """
    specs = {
        "total_assets": _spec("total_assets", "instant", ("Assets",)),
        "total_liabilities": _spec("total_liabilities", "instant", ("Liabilities",)),
        "stockholders_equity": _spec("stockholders_equity", "instant",
                                     ("StockholdersEquity",)),
    }
    facts = {"facts": {"us-gaap": {
        "Assets": {"units": {"USD": [
            _instant(100, "2023-12-31", "a23", "2024-02-01"),   # millésime 2009 : 3 votes
            _instant(95, "2023-12-31", "a24", "2025-02-01"),    # millésime 2010 : 2 votes
        ]}},
        "Liabilities": {"units": {"USD": [
            _instant(40, "2023-12-31", "a23", "2024-02-01"),
        ]}},
        "StockholdersEquity": {"units": {"USD": [
            _instant(60, "2023-12-31", "a23", "2024-02-01"),
            _instant(55, "2023-12-31", "a24", "2025-02-01"),
        ]}},
    }}}
    rows = extract(facts, specs=specs)
    by = _by_concept(rows)
    # Le millésime 2024 l'emporte (3 votes > 2) : rien ne vient de 2025.
    assert by["total_assets"]["2023-12-31"]["value"] == 100
    assert by["total_liabilities"]["2023-12-31"]["value"] == 40
    assert by["stockholders_equity"]["2023-12-31"]["value"] == 60
    assert {r["filed"] for r in rows} == {"2024-02-01"}
    # Identité bilancielle retrouvée : A = L + SC.
    assert 100 == 40 + 60


def test_vintage_tie_breaks_on_latest_and_drops_uncovered_concepts():
    """Égalité de votes → dépôt le plus récent ; un concept absent du
    millésime gagnant est DROPPÉ (pas de chiffre d'un autre vintage)."""
    specs = {
        "total_assets": _spec("total_assets", "instant", ("Assets",)),
        "total_liabilities": _spec("total_liabilities", "instant", ("Liabilities",)),
        "stockholders_equity": _spec("stockholders_equity", "instant",
                                     ("StockholdersEquity",)),
    }
    facts = {"facts": {"us-gaap": {
        "Assets": {"units": {"USD": [
            _instant(100, "2023-12-31", "a23", "2024-02-01"),  # 1 vote
            _instant(110, "2023-12-31", "a24", "2025-02-01"),  # 2 votes
        ]}},
        "Liabilities": {"units": {"USD": [
            _instant(45, "2023-12-31", "a24", "2025-02-01"),   # 2e vote de 2025
        ]}},
        "StockholdersEquity": {"units": {"USD": [
            _instant(63, "2023-12-31", "a23", "2024-02-01"),   # seul en 2024
        ]}},
    }}}
    rows = extract(facts, specs=specs)
    by = _by_concept(rows)
    # votes : 2024 -> {TA, SE} = 2 ; 2025 -> {TA, TL} = 2 ; tie → 2025.
    assert by["total_assets"]["2023-12-31"]["filed"] == "2025-02-01"
    assert by["total_liabilities"]["2023-12-31"]["value"] == 45
    # SE absent du millésime gagnant → concept manquant, pas de mélange.
    assert "stockholders_equity" not in by


# --- 2. invariants sur le trio réel (si cache présent) ----------------------


@pytest.mark.parametrize("slug,cik", TRIO)
def test_invariants_on_real_trio(slug: str, cik: str):
    """Invariants durs sur les données SEC réelles du trio."""
    rows = extract(_load_trio(cik))
    assert rows, f"{slug}: extraction vide"
    by = _by_concept(rows)

    # Traçabilité : chaque ligne remonte à un dépôt daté.
    for r in rows:
        assert r["accn"] and r["filed"], f"{slug}: ligne sans dépôt {r}"
        date.fromisoformat(r["period_end"])

    # Solde toujours positif, CA toujours positif.
    ta = by.get("total_assets", {})
    assert ta, f"{slug}: total_assets absent"
    bad_ta = {d: v["value"] for d, v in ta.items() if v["value"] <= 0}
    assert not bad_ta, f"{slug}: total_assets <= 0: {bad_ta}"
    sales = by.get("sales", {})
    neg_sales = {d: v["value"] for d, v in sales.items() if v["value"] < 0}
    assert not neg_sales, f"{slug}: sales < 0: {neg_sales}"

    # Actif courant ≤ actif total (même date de bilan).
    ca = by.get("current_assets", {})
    breaches = {
        d: (ca[d]["value"], ta[d]["value"])
        for d in set(ca) & set(ta)
        if ca[d]["value"] > ta[d]["value"]
    }
    assert not breaches, f"{slug}: current_assets > total_assets: {breaches}"

    # Cohérence de millésime : A ≈ L + SC sur la grande majorité des
    # bilans (tolérance 5 % par écart ; minoritaires et titres
    # hybrides — mezzanine chez AMC — expliquent les quelques % restants,
    # d'où le seuil de 80 % et non 100 %).
    liab = by.get("total_liabilities", {})
    se = by.get("stockholders_equity", {})
    common = sorted(set(ta) & set(liab) & set(se))
    if common:  # BBBY/AMC anciens peuvent manquer SE sur certains exercices
        gaps = [
            (d, abs(ta[d]["value"] - (liab[d]["value"] + se[d]["value"])) / abs(ta[d]["value"]))
            for d in common
        ]
        ok_share = sum(1 for _, g in gaps if g <= 0.05) / len(gaps)
        worst = sorted(gaps, key=lambda t: -t[1])[:3]
        assert ok_share >= 0.80, (
            f"{slug}: identité A ≈ L + SC trop souvent rompue "
            f"({ok_share:.0%} ≤ 5 %, pires écarts: {worst}) — mélange de millésimes ?"
        )


# --- 3. valeurs dorées (sélection figée, vérifiée à la main) -----------------

# (slug, cik, concept, period_end, valeur SEC de référence).
# Sources : dépôts cités dans data/phase0/*_facts.csv + raw companyfacts.
GOLDEN_VALUES = [
    # CA Apple FY2018 : 265 595 M$ (10-K 0000320193-18-000145) — la valeur
    # doit survivre aux restatements postérieurs à valeur égale.
    ("apple_healthy", "0000320193", "sales", "2018-09-29", 265_595_000_000),
    # Actif Apple au 27/09/2008 : le millésime du 10-K de 2009 (39 572 M$)
    # gagne au vote contre le millésime 2010 (36 171 M$, sans passif) —
    # c'est EXACTEMENT ce que le vote de millésime doit produire.
    ("apple_healthy", "0000320193", "total_assets", "2008-09-27", 39_572_000_000),
    # Réserves AMC au 31/12/2018 : le vrai solde (-550,9 M$) et non le
    # comparatif de début d'exercice au 01/01/2018 (-239,7 M$) qui
    # porte la même année civile clé.
    ("amc_distressed", "0001411579", "retained_earnings", "2018-12-31", -550_900_000),
]


@pytest.mark.parametrize("slug,cik,concept,period_end,expected", GOLDEN_VALUES,
                         ids=[f"{s}-{c}" for s, _, c, _, _ in GOLDEN_VALUES])
def test_golden_values(slug: str, cik: str, concept: str, period_end: str, expected: int):
    """Le chargeur doit reproduire ces valeurs SEC exactes."""
    rows = extract(_load_trio(cik))
    by = _by_concept(rows)
    fact = by.get(concept, {}).get(period_end)
    assert fact is not None, f"{slug}: {concept}@{period_end} absent"
    assert fact["value"] == expected, (
        f"{slug}: {concept}@{period_end} = {fact['value']}, attendu {expected} "
        f"(accn {fact['accn']}, filed {fact['filed']})"
    )
