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

Choix de conception (v2 — features événementielles) :
  Gate 2 v1 : le LSTM ne voyait QUE les ratios financiers et perdait
  face au classique (det6 55,6 % vs 78,3 %) — or l'arme du classique
  est critical_8k (8-K items 1.03/2.04/4.02 = faillite annoncée). La v2
  ajoute par exercice les MÊMES grandeurs que les signaux d'événements
  (app/signals/events.py, table CRITICAL_ITEMS partagée — pas de double
  logique) :
    - compte d'8-K « défaillance » (items de rang 3) et compte d'8-K
      « vigilance » (items de rang 2 seuls) — décomposition mesurée
      plutôt qu'un rang max saturé (80 % des exercices à cause des 5.02
      routine, cf. EVENT_FEATURES) ;
    - nombre de dépôts NT (retard de rapport) ;
    - disponibilité étendue au max(filed_at) des dépôts de l'exercice :
      un NT déposé 4 mois après le bilan ne rend le point exploitable
      qu'à cette date (même anti-fuite que metrics.build_snapshots) ;
    - flag « événements absents » : une entreprise sans AUCUN 8-K/NT
      ingéré n'a jamais vu passer ses submissions (un déposant coté en
      dépose toujours) -> features à 0 + flag 1, pas un faux « sain ».
  Les events partagent l'ancre report_date/filed_at des signaux
  classiques : le LSTM apprend les mêmes événements, sur les mêmes
  exercices, avec la même discipline de disponibilité.
"""

from dataclasses import dataclass
from datetime import date

from app.signals.events import (
    CRITICAL_ITEMS,
    assign_to_years,
    evaluate_late_filing,
)

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

# Features d'événements ajoutées à chaque vecteur annuel (v2) — les 3
# premières = mêmes grandeurs que les signaux classiques du §2, la 4e =
# flag « pas de données d'événements » (règle produit, cf. docstring).
#
# Décision v2.1 (mesurée sur l'export) : au lieu du RANG MAX (saturé —
# 80 % des exercices à 0.667 car un 5.02 « départ de dirigeant » touche
# presque tout le monde chaque année, le même bruit qui a forcé le poids
# 0.5 de critical_8k côté composite), on décompose le compte d'8-K
# critiques en deux features non saturées : nombre d'8-K « défaillance »
# (items 1.03/2.04/4.02 — rare, ~3.6 % des exercices, la vraie arme) et
# nombre d'8-K « vigilance » (items 4.01/5.02 — fréquent, peu
# discriminant). Leur somme = critical_8k classique : aucune information
# perdue, mais le LSTM peut apprendre à ignorer le bruit 5.02 au lieu
# d'être noyé dedans.
EVENT_FEATURES: tuple[str, ...] = (
    "critical_defaillance",  # nb d'8-K à items de rang 3 (clipé)
    "critical_vigilance",  # nb d'8-K à items de rang 2 seuls (clipé)
    "late_filing",  # nb de dépôts NT (rapports en retard)
    "events_missing",  # flag : zéro 8-K/NT = submissions non chargées
)

# ratio + flag manquant par concept, + features d'événements (v2).
INPUT_DIM = 2 * len(FEATURE_CONCEPTS) + len(EVENT_FEATURES)
HORIZON_DAYS = 365  # étiquette « faillite dans les 12 mois »
MIN_YEARS = 3  # séquence minimale pour alimenter le LSTM
MAX_YEARS = 5  # fenêtre « sur 5 ans » de la feuille de route
RATIO_CLIP = 5.0  # borne les ratios extrêmes (surcroissance, ventes ~0…)
COUNT_CLIP = 5.0  # borne les comptes d'événements (rafales d'8-K en faillite)


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


def event_features(
    year_events: list[dict], period_end: date, missing: bool
) -> tuple[float, float, float, float]:
    """Dépôts rattachés à un exercice -> 4 features d'événements (v2.1).

    Même table d'items que les signaux classiques (events.CRITICAL_ITEMS —
    moteur partagé, pas de copie divergante) mais le compte est DÉCOMPOSÉ
    par rang plutôt que réduit à un rang max saturé (cf. EVENT_FEATURES) :
      - 8-K « défaillance » = au moins un item de rang 3 (1.03/2.04/4.02) ;
      - 8-K « vigilance » = items de rang 2 seulement (4.01/5.02).
    late_filing réutilise l'évaluateur classique (compte de form NT).
    Valeurs bornées par COUNT_CLIP (rafales d'8-K en faillite).
    `missing` = aucune donnée de dépôt pour l'entreprise (règle produit :
    0 neutre + flag explicite, jamais un faux « 0 sain »).
    """
    if missing:
        return (0.0, 0.0, 0.0, 1.0)
    n_def = 0  # 8-K portant au moins un item de rang 3
    n_vig = 0  # 8-K portant uniquement des items de rang 2
    for e in year_events:
        if not e["form"].startswith("8-K"):
            continue
        items = [
            it.strip()
            for it in (e.get("items") or "").split(",")
            if it.strip()
        ]
        ranks = [CRITICAL_ITEMS[it] for it in items if it in CRITICAL_ITEMS]
        if not ranks:
            continue  # 8-K ordinaire (2.02 résultats, 9.01 annexes…)
        if max(ranks) >= 3:
            n_def += 1
        else:
            n_vig += 1
    nt_rows = [e for e in year_events if e["form"].startswith("NT")]
    res_n = evaluate_late_filing(nt_rows, period_end.isoformat(), None)
    return (
        min(float(n_def), COUNT_CLIP),
        min(float(n_vig), COUNT_CLIP),
        min(float(res_n.value or 0.0), COUNT_CLIP),
        0.0,
    )


def company_year_points(rows: list[dict], events: list[dict] | None = None) -> list[YearPoint]:
    """Faits d'UNE entreprise -> points annuels chronologiques.

    `rows` : {period_end (date), concept, value, filed_at (date|None)}.
    Convention identique à compute.build_years : dernier period_end de la
    année civile gagne (ex. comparatif au 01-01 puis vrai solde au
    31-12) ; disponibilité = max(filed_at) des faits retenus.

    `events` : dépôts 8-K/NT de l'entreprise, même forme que
    repo.fetch_event_rows (filed_at / report_date en ISO str) — None ou []
    = données d'événements absentes -> flag events_missing = 1.
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

    # Événements -> exercices : MOTEUR PARTAGÉ des signaux classiques
    # (assign_to_years : ancre report_date sinon filed_at). Échelle =
    # toutes les dates de bilan connues, losers compris — le rattachement
    # par année est identique avec ou sans losers (mêmes années civiles).
    events_by_year: dict[int, list[dict]] = {}
    if events:
        all_period_ends = sorted({r["period_end"].isoformat() for r in rows})
        events_by_year, _dropped = assign_to_years(events, all_period_ends)
    # Flag entreprise : zéro dépôt = submissions jamais chargées (un
    # déposant coté en dépose toujours) -> pas un faux « sain ».
    events_missing = not events

    points = []
    for year in sorted(by_year):
        node = by_year[year]
        if not node["values"] or not node["filed"]:
            continue  # exercice vide ou jamais datable -> inexploitable
        year_events = events_by_year.get(year, [])
        ev_vec = event_features(year_events, node["period_end"], events_missing)
        # Disponibilité étendue aux dépôts rattachés : un NT déposé après
        # le 10-K ne se connaît qu'à sa date de dépôt (anti-fuite, même
        # discipline que metrics.build_snapshots sur les signaux).
        filed = node["filed"] + [
            date.fromisoformat(e["filed_at"]) for e in year_events
        ]
        points.append(
            YearPoint(
                period_end=node["period_end"],
                availability=max(filed),
                vector=vectorize(node["values"]) + ev_vec,
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
