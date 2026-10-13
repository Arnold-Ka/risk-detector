"""Signaux d'événements — dépôts réglementaires (feuille de route §2).

Deux signaux MVP (les données viennent de l'API submissions, ingérées dans
la table `filings` avec `items` + `report_date`) :

1. late_filing — « rapport déposé en retard » (NT 10-K / NT 10-Q).
   Le dépôt du rapport annuel/trimestriel en retard signale souvent des
   problèmes dans les comptes (§2). Valeur = nombre de dépôts NT de
   l'exercice : 0 = saine, 1 = vigilance, >= 2 = défaillance (deux rapports
   retardés dans le même exercice = problème structurel, pas un incident).

2. critical_8k — 8-K critiques (§2 : « Détection des 8-K critiques ») :
     item 1.03  mise sous protection judiciaire / défaut de dette
                -> défaillance (c'est littéralement une faillite annoncée)
     item 2.04  déclenchement de clause de dette / perte matérielle
                -> défaillance
     item 4.02  comptes corrigés, non-fiance de l'auditeur (fraude)
                -> défaillance
     item 4.01  changement d'auditeur -> vigilance
     item 5.02  départ de dirigeant (PDG/CFO) -> vigilance
   Valeur = nombre de 8-K critiques de l'exercice ; sévérité = la plus
   grave des items déclarés ; filing_id = dépôt de l'item le plus grave.

Mapping événement -> exercice (le piège) :
  - ancre = report_date si la SEC l'a renseignée (un NT 10-K déposé en
    mars 2023 porte report_date = fin d'exercice 2022 -> AU BON endroit),
    sinon filed_at ;
  - l'événement est rattaché au premier period_end >= ancre (l'exercice
    en cours à la date de l'événement) ;
  - événement APRÈS le dernier period_end connu : ignoré (aucun exercice
    ne l'accueille ; les faits suivants arriveront et le prochain calcul
    l'inclura). S'arrêter au dernier bilan est cohérent avec le reste :
    on ne score que ce que l'on a observé.

Comme les autres modules : 0 événement = signal « saine » (continuité des
courbes, rien n'est inventé), entrée manquante = None (stricte).
"""

from app.signals.common import (
    SEV_ALERT,
    SEV_OK,
    SEV_WATCH,
    SignalResult,
)

# Item -> rang de gravité (2 = vigilance, 3 = défaillance).
CRITICAL_ITEMS: dict[str, int] = {
    "1.03": 3,
    "2.04": 3,
    "4.02": 3,
    "4.01": 2,
    "5.02": 2,
}
RANK_SEVERITY = {2: SEV_WATCH, 3: SEV_ALERT}


def assign_to_years(
    events: list[dict], period_ends: list[str]
) -> tuple[dict[int, list[dict]], list[dict]]:
    """Rattache chaque événement à un exercice (année de period_end).

    period_ends = toutes les dates de fin de bilan connues (triées).
    Retourne ({année: [événements]}, [événements ignorés]) — les ignorés
    sont ceux postérieurs au dernier bilan (voir docstring).
    """
    if not period_ends:
        return {}, list(events)
    assigned: dict[int, list[dict]] = {}
    dropped: list[dict] = []
    for event in events:
        anchor = event.get("report_date") or event["filed_at"]
        target = next((pe for pe in period_ends if pe >= anchor), None)
        if target is None:
            dropped.append(event)
            continue
        year = int(target[:4])
        assigned.setdefault(year, []).append(event)
    return assigned, dropped


def evaluate_late_filing(
    events: list[dict],
    period_end: str,
    fallback_filing_id: str | None,
) -> SignalResult:
    """Retards de dépôt de l'exercice (events = lignes de form NT)."""
    nt_forms = [e["form"] for e in events]
    if len(events) >= 2:
        severity = SEV_ALERT
    elif len(events) == 1:
        severity = SEV_WATCH
    else:
        severity = SEV_OK
    return SignalResult(
        signal_type="late_filing",
        period_end=period_end,
        value=float(len(events)),
        severity=severity,
        details={
            "nt_forms": nt_forms,
            "accessions": [e["accession"] for e in events],
        },
        # Tracé sur le dépôt NT fautif ; saine -> dépôt d'ancrage de
        # l'exercice (le 10-K lui-même), jamais NULL hors composite.
        filing_id=(events[0]["filing_id"] if events else fallback_filing_id),
    )


def evaluate_critical_8k(
    events: list[dict],
    period_end: str,
    fallback_filing_id: str | None,
) -> SignalResult:
    """8-K critiques de l'exercice (events = tous les 8-K, items inclus)."""
    # Un 8-K peut déclarer plusieurs items : on garde les plus graves.
    flagged = []
    worst_rank = 0
    for event in events:
        items = [
            it.strip()
            for it in (event.get("items") or "").split(",")
            if it.strip()
        ]
        ranks = [CRITICAL_ITEMS[it] for it in items if it in CRITICAL_ITEMS]
        if not ranks:
            continue  # 8-K ordinaire (2.02 résultats, 9.01 annexes…)
        rank = max(ranks)
        worst_rank = max(worst_rank, rank)
        flagged.append(
            {
                "accession": event["accession"],
                "items": items,
                "rank": rank,
                "filed_at": event["filed_at"],
                "filing_id": event["filing_id"],
            }
        )

    severity = RANK_SEVERITY.get(worst_rank, SEV_OK)
    # Filing tracé = premier dépôt portant l'item le plus grave.
    worst = next((f for f in flagged if f["rank"] == worst_rank), None)
    return SignalResult(
        signal_type="critical_8k",
        period_end=period_end,
        value=float(len(flagged)),
        severity=severity,
        details={
            "events": [
                {k: f[k] for k in ("accession", "items", "filed_at")}
                for f in flagged
            ],
            "worst_item": next(
                (it for f in flagged if f["rank"] == worst_rank
                 for it in f["items"] if CRITICAL_ITEMS.get(it) == worst_rank),
                None,
            ),
            "total_8k": len(events),
        },
        filing_id=(
            worst["filing_id"] if worst else fallback_filing_id
        ),
    )
