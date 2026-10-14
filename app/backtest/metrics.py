"""Métriques du backtest (§6, semaines 7-8) — logique pure, sans DB.

Principe de disponibilité (bien honnête) : un score n'est « connu »
qu'à la date de dépôt du millésime qui le porte (`filed_at` via
`filing_id`). Le composite n'a pas de dépôt propre : sa date = le MAX
des dates de ses composantes de l'exercice (celle qui arrive en dernier
débloque le score complet). Conséquence assumée : pour les émetteurs
ayant tardé ou restitué (millésime final stocké après coup), la
disponibilité mesurée est CONSERVATEUR — un analyste avait peut-être
une version antérieure plus tôt ; on ne mesure pas mieux que ce que la
base conserve (une seule vintage par exercice, purge des précédentes).

Choix d'évaluation : « état à l'instant T » — le dernier snapshot dont
la disponibilité ≤ T (ex. ancre de faillite − 6 mois). Une faillite est
« détectée à l'horizon h » si ce snapshot franchit le seuil testé.
"""

from dataclasses import dataclass
from datetime import date

# Niveaux du composite (ordinal croissant = gravité). Le seuil testé
# « >= modéré » = l'alerte produit standard ; >= critique = l'alerte la
# plus stricte ; la composante défaillance = « au moins un signal pur
# en défaillance sur l'exercice » (définition sans le composite).
LEVEL_ALERT = {"faible": 0, "modéré": 1, "élevé": 2, "critique": 3}


@dataclass(frozen=True)
class Snapshot:
    """État composite d'une entreprise pour un exercice donné."""

    period_end: date
    available_at: date  # max(filed_at) des composantes de l'exercice
    level: str
    has_defaillance: bool  # au moins une composante en défaillance
    # Types exacts des composantes en défaillance : permet des règles
    # affinées (« défaillance financière seule » vs 8-K événementiel).
    def_types: frozenset[str] = frozenset()


def add_months(anchor: date, months: int) -> date:
    """anchor + months mois, arithmétique calendaire (clamp fin de mois).

    2023-04-23 - 6 mois = 2022-10-23 ; 2023-03-31 - 1 mois = 2023-02-28
    (clamp : février n'a pas le 31).
    """
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    # Jour clampé au dernier jour du mois cible.
    for day in (anchor.day, 30, 29):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return date(year, month, 28)


def build_snapshots(rows: list[dict]) -> list[Snapshot]:
    """Lignes signaux d'UNE entreprise -> snapshots composites triés.

    `rows` : dicts {signal_type, period_end (date), severity, filed_at
    (date|None)} — déjà filtrés à l'entreprise côté script DB.

    Garde-fou : un composite sans AUCUNE composante datée est inexistant
    pour nous (impossible de dire quand il a pu être calculé) → ignoré.
    Un exercice sans composite (ex. aucune composante évaluable) n'est
    pas un snapshot — « donnée manquante ».
    """
    levels: dict[date, str] = {}
    filed_by_period: dict[date, list[date]] = {}
    def_types: dict[date, set[str]] = {}

    for r in rows:
        pe = r["period_end"]
        if r["signal_type"] == "composite":
            levels[pe] = r["severity"]
        else:
            if r["filed_at"] is not None:
                filed_by_period.setdefault(pe, []).append(r["filed_at"])
            if r["severity"] == "défaillance":
                def_types.setdefault(pe, set()).add(r["signal_type"])

    snaps = []
    for pe, level in levels.items():
        known = filed_by_period.get(pe, [])
        if not known:
            continue  # composite non datable → non exploitable
        snaps.append(
            Snapshot(
                period_end=pe,
                available_at=max(known),
                level=level,
                has_defaillance=pe in def_types,
                def_types=frozenset(def_types.get(pe, ())),
            )
        )
    return sorted(snaps, key=lambda s: s.period_end)


def pick_recent(snaps: list[Snapshot], cutoff: date, n: int = 2) -> list[Snapshot]:
    """Les `n` derniers snapshots DISPONIBLES au `cutoff`, plus récent d'abord.

    Disponibilité NON monotone avec period_end possible (un millésime de
    restitution tardif peut dater APRÈS le dépôt de l'exercice suivant) :
    on parcourt tout, on garde les `n` period_end les plus récents parmi
    les available_at <= cutoff, triés décroissants.
    """
    available = [
        s for s in snaps
        if s.available_at <= cutoff
    ]
    available.sort(key=lambda s: s.period_end, reverse=True)
    return available[:n]


def pick_snapshot(snaps: list[Snapshot], cutoff: date) -> Snapshot | None:
    """Dernier snapshot disponible au `cutoff` (voir pick_recent)."""
    recent = pick_recent(snaps, cutoff, 1)
    return recent[0] if recent else None


def gap_months(older: Snapshot, newer: Snapshot) -> int:
    """Écart en mois entre deux exercices consécutifs (ex. 12 ± retards)."""
    return (newer.period_end.year - older.period_end.year) * 12 + (
        newer.period_end.month - older.period_end.month
    )


def exceeds(snap: Snapshot, rule: str) -> bool:
    """True si le snapshot déclenche l'alerte `rule` (voir RÈGLES du script)."""
    if rule == "defaillance":
        return snap.has_defaillance
    return LEVEL_ALERT[snap.level] >= LEVEL_ALERT[rule]
