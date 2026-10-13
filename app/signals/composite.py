"""Score global de risque — niveau composite faible / modéré / élevé / critique.

Feuille de route §2 : « Chaque entreprise reçoit un niveau de risque
(faible, modéré, élevé, critique) calculé à partir des signaux actifs,
pondérés selon leur gravité. Le poids de chaque signal sera ajusté grâce
au backtest. »

Implémentation initiale (à recalibrer sur le backtest des semaines 7-8) :
  - index de gravité par signal : saine = 0, vigilance = 1, défaillance = 2 ;
  - moyenne PONDÉRÉE des signaux disponibles de l'exercice ; un signal non
    calculable (donnée manquante) est exclu du numérateur ET du
    dénominateur — sain de comparer 4 signaux plutôt que de noter 0 un
    signal absent ;
  - poids initiaux égaux (1.0) : aucun résultat de backtest ne justifie
    encore d'hierarchiser Altman contre Piotroski ;
  - bandes : [0, 0,5[ faible · [0,5, 1[ modéré · [1, 1,5[ élevé ·
    [1,5, 2] critique.

Le composite porte sur la même date de fin d'exercice que ses composants
et n'a PAS de filing_id propre (il dérive d'eux) : la traçabilité remonte
par chaque signal listé dans details.components.
"""

from app.signals.common import (
    LEVEL_CRITICAL,
    LEVEL_HIGH,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    SEVERITIES,
    SignalResult,
)

# Poids initiaux — TODO(backtest sem. 7-8) : recalibrer et documenter.
WEIGHTS: dict[str, float] = {
    "altman": 1.0,
    "piotroski": 1.0,
    "beneish": 1.0,
    "divergence": 1.0,
    "runway": 1.0,
}

# index de gravité par sévérité (texte affiché -> nombre).
SEV_INDEX = {"saine": 0.0, "vigilance": 1.0, "défaillance": 2.0}

# Bandes de niveaux sur l'indice pondéré (voir docstring).
LEVEL_BREAKS = ((0.5, LEVEL_LOW), (1.0, LEVEL_MEDIUM), (1.5, LEVEL_HIGH))


def level_for_index(index: float) -> str:
    for break_value, label in LEVEL_BREAKS:
        if index < break_value:
            return label
    return LEVEL_CRITICAL


def evaluate(
    severities: dict[str, str],
    period_end: str,
    weights: dict[str, float] | None = None,
) -> SignalResult | None:
    """Composite de l'exercice à partir des sévérités {signal_type: sévérité}.

    `weights` : surcharge des poids initiaux (le backtest des semaines 7-8
    fera varier ces valeurs ; par défaut, WEIGHTS ci-dessus).
    None si aucun composant n'est disponible (ni niveau, ni valeur : la
    règle produit interdit d'afficher un niveau inventé).
    """
    weights = weights or WEIGHTS
    usable = {
        name: sev
        for name, sev in severities.items()
        if name in weights and sev in SEVERITIES
    }
    if not usable:
        return None

    total_weight = sum(weights[name] for name in usable)
    index = sum(weights[name] * SEV_INDEX[sev] for name, sev in usable.items()) / total_weight

    return SignalResult(
        signal_type="composite",
        period_end=period_end,
        value=round(index, 3),
        severity=level_for_index(index),
        details={
            "index": round(index, 3),
            "components": usable,
            "weights": {name: weights[name] for name in usable},
            # Signaux non calculables cet exercice : l'affichage pourra dire
            # « niveau fondé sur 3 signaux sur 5 ».
            "absent": sorted(set(weights) - set(usable)),
        },
        filing_id=None,  # dérive des composants, eux-mêmes tracés
    )
