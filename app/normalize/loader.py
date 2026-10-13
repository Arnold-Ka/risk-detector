"""Extraction des indicateurs standard depuis une réponse `companyfacts`.

Rôle dans le pipeline (phase 1, §6 semaines 3-4) : transformer le JSON
brut de la SEC en une liste de faits normalisés, prêts à être insérés dans
la table `facts` (une ligne = un concept, une valeur, une date de fin de
période, et le dépôt source exact — traçabilité au sens du principe nº1).

Règles de sélection (héritées de la phase 0, validées par les tests) :
  - uniquement les dépôts **10-K / fp=FY** (l'annuel, pas les trimestres) ;
  - pour les durées (`kind: duration`), une fenêtre de 300 à 400 jours —
    écarte les sous-périodes et les synthèses pluriannuelles (Item 6) ;
  - plusieurs tags par concept (table xbrl_map.yaml) : priorité à l'ordre
    de la liste, les années manquantes sont comblées par les variantes
    (le CA d'Apple chevauche 3 tags) ;
  - en cas de correction de dépôt, la version la plus récente (`filed`)
    gagne ;
  - clé = date `end` EXACTE du fait, jamais le champ `fy` (colonne
    comparative piégée : l'exercice BBBY 2022 finit le 2023-02-25) ;
  - **cohérence de millésime (instantanés uniquement)** : tous les postes
    d'un même bilan doivent venir d'un MÊME dépôt. Chaque dépôt « vote »
    pour la date de fin concernée (un vote par concept qu'il couvre) ;
    gagne le plus grand nombre de votes, puis — à égalité — le dépôt le
    plus récent (les 10-K/A sont en dehors du périmètre `form=10-K`).
    Sans cette règle, chaque concept prend son propre dépôt le plus
    récent et l'on mélange deux millésimes : Apple 2008 ressortait avec
    actif du rapport 2010 mais passif du rapport 2009 (A ≠ L + SC).
    Un concept absent du millésime gagnant est DROPPÉ (« donnée
    manquante » vaut mieux qu'un chiffre d'un autre vintage).

Aucune dépendance réseau ni base : `extract` est une fonction pure testable
(unit tests sur fixtures) — les contrôles d'invariants sur le trio de la
phase 0 s'exécutent en plus si `data/cache/` est peuplé.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

# Le fichier vit dans le même package ; chemin absolu déduit de __file__
# pour rester valable quel que soit le répertoire de lancement.
MAP_PATH = Path(__file__).parent / "xbrl_map.yaml"

ANNUAL_FORM = "10-K"
ANNUAL_FP = "FY"

# Fenêtre de durée admissible pour un fait "annuel" (en jours) : couvre les
# exercices de 52-53 semaines et les extrémités bissextiles, écarte les
# trimestres (~90 j) et les synthèses 5 ans (~1825 j).
MIN_DURATION_DAYS = 300
MAX_DURATION_DAYS = 400


@dataclass(frozen=True)
class ConceptSpec:
    """Définition d'un indicateur normalisé (une ligne du YAML)."""

    key: str
    label: str
    kind: str  # "instant" | "duration"
    namespace: str  # "us-gaap" | "dei"
    tags: tuple[str, ...]


def load_map(path: Path = MAP_PATH) -> dict[str, ConceptSpec]:
    """Charge xbrl_map.yaml en validateur tôt (erreur YAML = échec clair)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs: dict[str, ConceptSpec] = {}
    for key, node in raw["concepts"].items():
        kind = node["kind"]
        if kind not in {"instant", "duration"}:
            raise ValueError(f"xbrl_map.yaml: kind invalide pour {key!r}: {kind!r}")
        specs[key] = ConceptSpec(
            key=key,
            label=node["label"],
            kind=kind,
            namespace=node.get("namespace", "us-gaap"),
            tags=tuple(node["tags"]),
        )
    return specs


def _iter_annual(node: dict, kind: str):
    """Tous les faits annuels VALIDES d'un tag : (fin de période, fait).

    Filtres seulement (form/fp/fenêtre de durée), SANS déduplication —
    la sélection se fait ensuite selon le kind :
      - durée : `_annual_values` garde le filed le plus récent par date ;
      - instant : le vote de millésime dans `extract` a besoin de TOUS
        les candidats (chaque dépôt doit pouvoir voter).
    """
    for unit_values in node.get("units", {}).values():
        for v in unit_values:
            if v.get("form") != ANNUAL_FORM or v.get("fp") != ANNUAL_FP:
                continue
            end = v.get("end")
            if not end:
                continue
            if kind == "duration":
                start = v.get("start")
                if not start:
                    continue
                days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                if not MIN_DURATION_DAYS <= days <= MAX_DURATION_DAYS:
                    continue
            yield end, v


def _annual_values(node: dict, kind: str) -> dict[str, dict]:
    """Valeurs annuelles d'un tag brut : {fin de période ISO: fait source}.

    Plusieurs faits peuvent tomber sur la même date (restatements) : on
    garde celui déposé le plus récent (`filed` max).
    """
    best: dict[str, dict] = {}
    for end, v in _iter_annual(node, kind):
        if end not in best or v.get("filed", "") > best[end].get("filed", ""):
            best[end] = v
    return best


def _select_vintage(
    instant_cand: dict[str, dict[str, list[tuple[int, dict]]]],
) -> dict[str, str]:
    """Vote de millésime : {date de fin: filed gagnant}.

    `instant_cand[concept][end] = [(tag_idx, fait), …]` — chaque dépôt
    présent sur `end` remporte un vote pour CHAQUE concept qu'il couvre à
    cette date. Gagne (votes max, puis filed max en tie-break).
    """
    votes: dict[str, dict[str, set[str]]] = {}
    for concept, by_end in instant_cand.items():
        for end, cands in by_end.items():
            bucket = votes.setdefault(end, {})
            for _, rec in cands:
                bucket.setdefault(rec.get("filed", ""), set()).add(concept)
    return {
        end: max(bucket.items(), key=lambda kv: (len(kv[1]), kv[0]))[0]
        for end, bucket in votes.items()
    }


def extract(companyfacts: dict, specs: dict[str, ConceptSpec] | None = None) -> list[dict]:
    """companyfacts -> liste de faits normalisés (tri concept puis date).

    Chaque entrée :
      {"concept", "label", "kind", "period_end", "value",
       "accn", "filed", "tag"} — `tag` = variante XBRL réellement retenue,
      `accn`/`filed` = dépôt et date de dépôt, pour remonter à la source.

    Durées sélectionnées directement (priorité de tag, puis filed max) ;
    instantanés filtrés par vote de millésime (voir docstring module).
    """
    if specs is None:
        specs = load_map()
    facts_ns: dict = companyfacts.get("facts", {})

    # Durées : {concept: {end: (tag_idx, fait)}} — setdefault => la variante
    # la plus prioritaire (ordre du YAML) gagne pour une même date.
    duration_sel: dict[str, dict[str, tuple[int, dict]]] = {}
    # Instants : {concept: {end: [(tag_idx, fait), …]}} — TOUS les
    # candidats, pour que chaque dépôt puisse voter (et que le millésime
    # gagnant retrouve le bon fait de chaque concept).
    instant_cand: dict[str, dict[str, list[tuple[int, dict]]]] = {}

    for spec in specs.values():
        ns_facts = facts_ns.get(spec.namespace, {})
        dur_slot = duration_sel.setdefault(spec.key, {})
        inst_slot = instant_cand.setdefault(spec.key, {})
        for tag_idx, tag in enumerate(spec.tags):
            node = ns_facts.get(tag)
            if not node:
                continue
            if spec.kind == "duration":
                for end, rec in _annual_values(node, spec.kind).items():
                    dur_slot.setdefault(end, (tag_idx, rec))
            else:
                for end, rec in _iter_annual(node, spec.kind):
                    inst_slot.setdefault(end, []).append((tag_idx, rec))

    winners = _select_vintage(instant_cand)

    out: list[dict] = []
    for spec in specs.values():
        if spec.kind == "duration":
            selected = sorted(duration_sel[spec.key].items())
        else:
            selected = []
            for end, cands in sorted(instant_cand[spec.key].items()):
                winner = winners.get(end)
                kept = [(ti, rec) for ti, rec in cands if rec.get("filed", "") == winner]
                if not kept:
                    # Concept non couvert par le millésime gagnant : on
                    # préfère l'absence à un chiffre d'un autre vintage.
                    continue
                kept.sort(key=lambda p: p[0])  # priorité de tag du YAML
                selected.append((end, kept[0]))
        for end, (tag_idx, rec) in selected:
            out.append(
                {
                    "concept": spec.key,
                    "label": spec.label,
                    "kind": spec.kind,
                    "period_end": end,
                    "value": rec["val"],
                    "accn": rec["accn"],
                    "filed": rec.get("filed", ""),
                    "tag": spec.tags[tag_idx],
                }
            )
    return out
