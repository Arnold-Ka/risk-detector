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
  - poids initiaux égaux (1.0) — sauf `critical_8k` à 0.5, seul levier
    dont le backtest (§6 sem. 7-8, 2026-10-14) a mesuré un gain net
    (détect 6 m toujours en cible 60-70 %, FPR divisé par deux) ;
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

# Poids initiaux égaux, sauf recalibration backtest (voir ci-dessous).
# TODO(backtest) : les autres poids restent à 1.0 faute de gain mesuré
# (balayage monovariable, scripts/tune_weights.py).
WEIGHTS: dict[str, float] = {
    "altman": 1.0,
    "piotroski": 1.0,
    "beneish": 1.0,
    "divergence": 1.0,
    "runway": 1.0,
    "late_filing": 1.0,
    # Ventes massives de dirigeants (Form 4, §2) : poids 1.0 par défaut,
    # re-calibrable au backtest comme critical_8k (aucun gain mesuré
    # encore — le signal vient d'atterrir, batch Form 4 en cours).
    "insider_sales": 1.0,
    # Recalibré le 2026-10-14 par le backtest (547 faillites / 328
    # témoins S&P 500, scripts/tune_weights.py) : à 1.0, la vigilance
    # annuelle de l'item 8-K 5.02 (officier qui quitte) touche 87 % des
    # témoins CHAQUE année et faisait monter le taux d'alertes fausses
    # du seuil « >= modéré » à 27,2 % par exercice. À 0.5 :
    #   détection 6 mois  74,2 % -> 67,8 %   (cible feuille de route 60-70 %)
    #   détection 12 mois 68,4 % -> 61,8 %
    #   FPR par exercice  27,2 % -> 14,6 %   (jamais en 10 ans 97 % -> 78 %)
    # Le signal reste présent (un 1.03/2.04/4.02 compte toujours), il ne
    # sur-vote plus les exercices simples où tout le monde a un 5.02.
    "critical_8k": 0.5,
    # --- V2 (feuille de route §2, ajoutés le 2026-10-19) ------------------
    # Poids 1.0 par défaut, comme tous les signaux à leur arrivée : le
    # balayage tune_weights.py les couvre automatiquement (liste = keys()),
    # le retune (insider_sales + ces deux-là) attend le batch Form 4
    # complet à 875/875 pour ne pas calibrer sur une couverture partielle.
    "net_debt_ebitda": 1.0,
    "dilution": 1.0,
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
