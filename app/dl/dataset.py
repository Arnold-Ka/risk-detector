"""Dataset deep learning (§6 sem. 7-8, gate 2) — séries + étiquette.

Feuille de route : « exporter le jeu de données d'entraînement : séries
d'indicateurs sur 5 ans + étiquette faillite / sain » puis « entraîner
un premier modèle séquentiel (LSTM) ».

Choix de conception (v1) :
  - features = grandeurs financières du loader rapportées à l'actif
    total de l'exercice (ratios sans dimension : comparables entre
    sociétés de tailles différentes), clipés à ±5, plus un flag
    « manquant » par concept (règle produit « donnée manquante » ->
    0 neutre + indicateur explicite plutôt qu'un blanc piégé) ;
    parts/flottant exclus (quantités de marché, pas des ratios de bilan) ;
  - séquence = jusqu'à 5 exercices consécutifs (fenêtre glissante),
    MIN_YEARS = 3 pour que le LSTM ait un minimum de temporalité ;
  - étiquette = faillite (ancre = 1er 8-K item 1.03) dans les 12 mois
    APRÈS la date de fin de l'exercice — le même ancrage que le
    backtest classique, pour comparer les deux mondes ;
  - disponibilité = max(filed_at) des faits de la fenêtre : un échantillon
    ne peut servir à l'évaluation qu'une fois ses dépôts publiés
    (anti-leakage, même discipline que app/backtest/metrics.py).
"""

from dataclasses import dataclass
from datetime import date

# 18 concepts financiers (les 23 du loader moins public_float et les 3
# parts — voir docstring). Ordre = ordre des features d'entrée du modèle.
FEATURE_CONCEPTS: tuple[str, ...] = (
    "cash",
    "cfo",
    "current_assets",
    "current_liabilities",
    "depreciation",
    "gross_profit",
    "interest_expense",
    "inventory",
    "long_term_debt",
    "net_income",
    "operating_income",
    "ppe",
    "receivables",
    "retained_earnings",
    "sales",
    "sga",
    "stockholders_equity",
    "total_liabilities",
)

INPUT_DIM = 2 * len(FEATURE_CONCEPTS)  # ratio + flag manquant par concept
HORIZON_DAYS = 365  # étiquette « faillite dans les 12 mois »
MIN_YEARS = 3  # séquence minimale pour alimenter le LSTM
MAX_YEARS = 5  # fenêtre « sur 5 ans » de la feuille de route
RATIO_CLIP = 5.0  # borne les ratios extrêmes (surcroissance, ventes ~0…)


@dataclass(frozen=True)
class YearPoint:
    """Vecteur annuel d'une entreprise (un exercice = un point)."""

    period_end: date
    availability: date  # max(filed_at) des faits de cet exercice
    vector: tuple[float, ...]


@dataclass(frozen=True)
class Sample:
    """Échantillon d'entraînement/évaluation : séquence + étiquette."""

    cik: int
    period_end: date
    availability: date  # max sur la fenêtre (conservateur)
    sequence: tuple[tuple[float, ...], ...]
    label: int


def vectorize(values: dict[str, float]) -> tuple[float, ...]:
    """Concepts de l'exercice -> vecteur (ratios clipés + flags manquant).

    Ratio = valeur / total_assets ; sans actif total (jamais) -> vecteur
    tout manquant. total_assets vaut toujours dans les faits retenus par
    le loader (c'est un concept prioritaire), le garde-fou reste.
    """
    ta = values.get("total_assets")
    vector: list[float] = []
    for concept in FEATURE_CONCEPTS:
        v = values.get(concept)
        if v is None or not ta:
            vector.extend((0.0, 1.0))
        else:
            # float() : les valeurs sortent de psycopg en Decimal.
            ratio = float(v) / float(ta)
            vector.append(max(-RATIO_CLIP, min(RATIO_CLIP, ratio)))
            vector.append(0.0)
    return tuple(vector)


def company_year_points(rows: list[dict]) -> list[YearPoint]:
    """Faits d'UNE entreprise -> points annuels chronologiques.

    `rows` : {period_end (date), concept, value, filed_at (date|None)}.
    Convention identique à compute.build_years : dernier period_end de la
    année civile gagne (ex. comparatif au 01-01 puis vrai solde au
    31-12) ; disponibilité = max(filed_at) des faits retenus.
    """
    by_year: dict[int, dict] = {}
    for r in rows:
        year = r["period_end"].year
        node = by_year.setdefault(
            year, {"period_end": r["period_end"], "values": {}, "filed": []}
        )
        if r["period_end"] > node["period_end"]:
            # Nouveau period_end gagnant pour l'année : les valeurs du
            # perdant sont abandonnées (indépendant de l'ordre des rows).
            node["period_end"] = r["period_end"]
            node["values"] = {}
        if r["period_end"] == node["period_end"]:
            node["values"][r["concept"]] = r["value"]
        if r["filed_at"] is not None:
            node["filed"].append(r["filed_at"])

    points = []
    for year in sorted(by_year):
        node = by_year[year]
        if not node["values"] or not node["filed"]:
            continue  # exercice vide ou jamais datable -> inexploitable
        points.append(
            YearPoint(
                period_end=node["period_end"],
                availability=max(node["filed"]),
                vector=vectorize(node["values"]),
            )
        )
    return points


def build_samples(points: list[YearPoint], cik: int, anchor: date | None) -> list[Sample]:
    """Fenêtres glissantes -> échantillons (étiquette 12 mois si ancre).

    `anchor` = date de faillite (cohort) ou None (témoin, toujours 0).
    Échantillon refusé si la fenêtre contient un exercice daté APRÈS
    l'ancre (impossible à connaître avant l'événement).
    """
    samples: list[Sample] = []
    for i in range(MIN_YEARS - 1, len(points)):
        window = points[max(0, i - MAX_YEARS + 1) : i + 1]
        last = window[-1]
        if anchor is not None and last.period_end > anchor:
            break  # exercices post-faillite : fin de l'entreprise de toute façon
        label = 0
        if anchor is not None:
            delta = (anchor - last.period_end).days
            label = int(0 <= delta <= HORIZON_DAYS)
        samples.append(
            Sample(
                cik=cik,
                period_end=last.period_end,
                availability=max(p.availability for p in window),
                sequence=tuple(p.vector for p in window),
                label=label,
            )
        )
    return samples
