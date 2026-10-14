"""Cohortes du backtest (feuille de route §6, semaines 7-8) — logique pure.

Deux populations, écrites dans `data/backtest/companies.json` :
  - group="cohort"   : émetteurs ayant déposé un 8-K « Item 1.03 »
                       (mise en Chapter 11) entre 2015 et 2025 → étiquette 1 ;
  - group="control"  : témoins sains (écran S&P 500)                → 0.

Principe du module : AUCUN accès réseau ici (testable sans cache, rejouable
sans EDGAR). Le scan FTS, les catégories Wikipedia, l'écran S&P et les
téléchargements vivent dans scripts/build_cohort.py, qui appelle ces
fonctions. On garde ainsi le même partage « moteur pur / script d'entrée »
que app/normalize/loader.py.

Choix de conception (validés le 2026-10-13 avec l'utilisateur) :
  - source hybride : FTS EDGAR (primaire, date exacte + CIK + SIC) +
    catégories Wikipedia (rattrape les émetteurs absents du FTS) ;
  - ancre de faillite = date du PREMIER 8-K item 1.03 sur l'historique
    submissions (même source que le signal critical_8k du produit : le
    backtest juge l'outil avec ses propres données) ;
  - SIC 6000-6799 exclu (banques/assurances/REIT : « scores non fiables »,
    spec AGENTS) — cohort ET témoins ;
  - couverture ≥ 5 exercices sur les 6 ans précédant la faillite : sans
    ça, pas de série 5 ans pour le DL, et les scores classiques manquent
    de recul.
"""

import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

from app.normalize.loader import extract

# Fenêtre de la feuille de route : « faillite entre 2015 et 2025 ».
WINDOW_START = "2015-01-01"
WINDOW_END = "2025-12-31"

# Codes SIC officiels SEC (4 chiffres, parfois écrits sans padding).
# 6000-6199 établissements dépositaires (banques), 6200-6499 assurances,
# 6500-6799 immobilier + holding financiers (dont REIT 6798). La spec
# interdit de scorer ces secteurs : on les EXCLUT des deux groupes.
FINANCIAL_SIC_RANGE = range(6000, 6800)

# Suffixes retirés avant toute comparaison de noms (Wikipedia titre vs
# entityName SEC) : « Bed Bath & Beyond, Inc. » == « Bed Bath and Beyond ».
_NAME_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company",
    "ltd", "limited", "plc", "llc", "lp", "llp", "group", "holdings",
    "holding", "the", "and", "et", "del", "de", "na", "n.a",
}


def parse_sic(sic: object) -> int | None:
    """SIC SEC (str ou int selon les API) -> int normalisé, ou None."""
    if sic in (None, ""):
        return None
    try:
        return int(str(sic).strip())
    except ValueError:
        return None


def is_financial(sic: object) -> bool:
    """True si le SIC désigne banque/assurance/REIT (scores non fiables)."""
    n = parse_sic(sic)
    return n is not None and n in FINANCIAL_SIC_RANGE


def sector_group_for_sic(sic: object) -> str:
    """SIC -> valeur de companies.sector_group ('bank'|'insurance'|'reit'|'other')."""
    n = parse_sic(sic)
    if n is None:
        return "other"
    if 6000 <= n <= 6199:
        return "bank"
    if 6200 <= n <= 6499:
        return "insurance"
    if 6500 <= n <= 6799:
        return "reit"
    return "other"


# --- Source primaire : recherche plein texte EDGAR (FTS) --------------------

def parse_fts_hits(sources: list[dict], year: int) -> dict[int, dict]:
    """Sources FTS d'une année -> {cik: candidat} avec la 1ʳᵉ date 1.03.

    Chaque `_source` de FTS porte : ciks, file_date, items, display_names,
    sics. On ne garde QUE les hits dont les items confirment « 1.03 »
    (le texte « Item 1.03 » peut apparaître dans un document sans que ce
    soit L'item déclaré — le champ `items` vient de l'en-tête officiel).

    Doublons naturels (une faillite = plusieurs 8-K 1.03 : pétition,
    confirmation de plan…) : le plus tôt gagne, c'est l'ancre.
    """
    out: dict[int, dict] = {}
    for src in sources:
        items = src.get("items") or []
        # items peut être une liste de codes OU une chaîne « 1.03,2.04 ».
        codes = [c.strip() for chunk in items for c in str(chunk).split(",")]
        if "1.03" not in codes:
            continue
        filed = src.get("file_date") or ""
        if not (WINDOW_START <= filed <= WINDOW_END):
            continue
        ciks = src.get("ciks") or []
        if not ciks:
            continue
        cik = int(ciks[0])
        names = src.get("display_names") or [""]
        sics = src.get("sics") or [None]
        cand = out.get(cik)
        if cand is None or filed < cand["bankruptcy_date"]:
            out[cik] = {
                "cik": cik,
                "name": _clean_display_name(names[0]),
                "sic": parse_sic(sics[0]),
                "bankruptcy_date": filed,
                "source": "fts",
            }
    return out


def _clean_display_name(display: str) -> str:
    """« Athenex, Inc.  (CIK 0001300699) » -> « Athenex, Inc. »."""
    return re.sub(r"\s*\((CIK|CIK\s*\d+).*?\)\s*$", "", display).strip()


# --- Source secondaire : catégories Wikipedia par année ---------------------

def norm_name(name: str) -> str:
    """Normalisation grossière pour comparer un titre Wikipedia à un nom SEC.

    Accents ôtés, minuscules, ponctuation/suffixes société retirés :
    « Bed Bath & Beyond, Inc. » -> « bed bath beyond ».
    """
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", text)
    return " ".join(w for w in words if w not in _NAME_SUFFIXES)


def title_matches_entity(title: str, entity_name: str) -> bool:
    """True si le titre Wikipedia désigne déjà une entité couverte par le FTS.

    Comparaison « contient » après normalisation : le FTS renvoie
    l'entityName SEC (souvent plus complet), le titre Wikipedia parfois
    tronqué (« IRobot » vs « iRobot, Inc. »).
    """
    a, b = norm_name(title), norm_name(entity_name)
    if not a or not b:
        return False
    return a == b or a in b or b in a


# --- Vérification ground truth : submissions --------------------------------

def first_item_103(rows: list[dict]) -> tuple[str, str] | None:
    """Premier 8-K item 1.03 de l'historique -> (filed_at, accession).

    `rows` = sortie de app.edgar.submissions.load_filing_rows (champ items
    = « 1.03,2.04 » pour les 8-K, "" ailleurs). Ancre de faillite retenue
    pour le backtest — même définition que le produit (signal critical_8k).
    Fenêtre : 2015-2025 (un 1.03 hors fenêtre n'est pas UNE faillite de
    notre période d'étude).
    """
    best: tuple[str, str] | None = None
    for row in rows:
        if not row["form"].startswith("8-K"):
            continue
        codes = [c.strip() for c in row["items"].split(",")]
        if "1.03" not in codes:
            continue
        filed = row["filed_at"]
        if not (WINDOW_START <= filed <= WINDOW_END):
            continue
        if best is None or filed < best[0]:
            best = (filed, row["accession"])
    return best


# --- Écran témoins (S&P 500) ------------------------------------------------

def control_screen(rows: list[dict]) -> tuple[bool, list[str]]:
    """Écran « entreprise saine » sur son historique de dépôts.

    Critères (tous sur submissions = source de vérité) :
      1. jamais de 8-K item 1.03 sur TOUT l'historique chargé (un 1.03
         même avant 2015 = l'entreprise a connu la faillite : exclue) ;
      2. 10-K déposé au plus tard en 2015 (activité avant la fenêtre) ;
      3. ≥ 9 des 10 années 2016-2025 avec un 10-K (continuité) ;
      4. un 10-K déposé entre 2024 et 2025 (toujours en vie, cotée).
    Retourne (ok, motifs_de_rejet) — les motifs servent au rapport final.
    """
    reasons: list[str] = []
    # Tous les 10-K de l'historique chargé (sans borne basse : c'est
    # justement la présence d'un 10-K AVANT 2016 qui valide le critère 2).
    tenk_years = {int(r["filed_at"][:4]) for r in rows if r["form"] == "10-K"}
    has_103 = any(
        r["form"].startswith("8-K") and "1.03" in {c.strip() for c in r["items"].split(",")}
        for r in rows
    )
    if has_103:
        reasons.append("a_déposé_1.03")
    if not any(y <= 2015 for y in tenk_years):
        reasons.append("pas_de_10-K_avant_2016")
    window_years = {y for y in tenk_years if 2016 <= y <= 2025}
    if len(window_years) < 9:
        reasons.append(f"continuité_{len(window_years)}_ans_sur_10")
    if not (window_years & {2024, 2025}):
        reasons.append("pas_de_10-K_récent")
    return (not reasons), reasons


# --- Couverture données (facts XBRL) ----------------------------------------

def pre_failure_years(companyfacts: dict, bankruptcy_date: str, span: int = 6) -> set[int]:
    """Années d'exercice avec faits EXTRAITS dans [faillite-span, faillite].

    Utilise app.normalize.loader.extract (le moteur unique du produit) :
    on mesure la couverture avec EXACTEMENT ce que les signaux liront, pas
    avec un comptage brut de tags. Les faits postérieurs à la pétition
    sont ignorés (l'entreprise ne dépose plus normalement après).
    """
    if not companyfacts.get("facts"):
        return set()
    b = date.fromisoformat(bankruptcy_date)
    start = f"{b.year - span:04d}{bankruptcy_date[4:]}"
    years: set[int] = set()
    for fact in extract(companyfacts):
        pe = fact["period_end"]
        if start <= pe <= bankruptcy_date:
            years.add(int(pe[:4]))
    return years


def coverage_ok(companyfacts: dict, bankruptcy_date: str, min_years: int = 5) -> bool:
    """≥ 5 exercices sur les 6 ans avant faillite (série 5 ans + recul)."""
    return len(pre_failure_years(companyfacts, bankruptcy_date)) >= min_years


def control_coverage(companyfacts: dict, min_years: int = 5) -> bool:
    """≥ 5 exercices distincts entre 2015 et 2025 pour un témoin."""
    if not companyfacts.get("facts"):
        return False
    years: set[int] = set()
    for fact in extract(companyfacts):
        pe = fact["period_end"]
        if WINDOW_START[:4] <= pe[:4] <= WINDOW_END[:4]:
            years.add(int(pe[:4]))
    return len(years) >= min_years


# --- Échantillonnage témoins proportionnel au SIC ---------------------------

def sample_controls(
    controls: list[dict], cohort: list[dict], target: int | None = None
) -> list[dict]:
    """Sous-ensemble de témoins calé sur la distribution SIC (2 chiffres) du cohort.

    « Comparables » au sens de la feuille de route : si le cohort est à
    30 % commerce de détail, le groupe témoin aussi. Déterministe (tri par
    CIK) pour que deux runs donnent le même échantillon — reproductibilité
    du backtest.
    """
    if target is None:
        target = len(cohort)
    cohort_buckets = Counter(c["sic"] // 100 if c["sic"] else -1 for c in cohort)
    total = sum(cohort_buckets.values()) or 1

    by_bucket: dict[int, list[dict]] = {}
    for ctrl in sorted(controls, key=lambda c: c["cik"]):
        bucket = ctrl["sic"] // 100 if ctrl["sic"] else -1
        by_bucket.setdefault(bucket, []).append(ctrl)

    picked: list[dict] = []
    quota: dict[int, int] = {}
    for bucket, n_cohort in cohort_buckets.items():
        want = round(target * n_cohort / total)
        quota[bucket] = max(want, 1 if bucket in by_bucket else 0)

    # Remplissage des quotas, puis second tour avec le reliquat
    # (buckets sous-alimentés : moins de témoins disponibles que visés).
    leftovers: list[dict] = []
    for bucket, want in quota.items():
        pool = by_bucket.get(bucket, [])
        picked.extend(pool[:want])
        leftovers.extend(pool[want:])
    if len(picked) < target:
        extra = [c for c in sorted(leftovers, key=lambda c: c["cik"])]
        picked.extend(extra[: target - len(picked)])
    return sorted(picked, key=lambda c: c["cik"])


# --- Manifeste ---------------------------------------------------------------

def make_slug(cik: int, ticker: str | None, name: str) -> str:
    """Slug de fichier stable et unique : base lisible + CIK (clé réelle)."""
    base = re.sub(r"[^a-z0-9]+", "", (ticker or name).lower())[:20] or "entreprise"
    return f"{base}_{cik}"


def save_manifest(path: Path | str, entries: list[dict]) -> None:
    """Écrit le manifeste d'ingestion (trié : cohort puis témoins, puis CIK)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted(entries, key=lambda e: (e["group"] != "cohort", e["cik"]))
    path.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_manifest(path: Path | str) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
