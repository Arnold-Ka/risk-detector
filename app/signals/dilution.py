"""Dilution — augmentation du nombre d'actions (feuille de route §2, V2).

Ligne V2 du tableau de signaux (§2) :
    « Dilution | Augmentation du nombre d'actions |
       Plus de 10 % sur un an | V2 »

Bandes (comme les lignes MVP, le seuil de la feuille de route est noté
en défaillance ; la bande intermédiaire à mi-seuil est un avertissement
précoce, calibrable au backtest comme tous les poids) :
    > 10 % sur un an -> défaillance   (seuil d'alerte « plus de 10 % »)
    >  5 % sur un an -> vigilance     (mi-seuil, signal d'approche)
    sinon            -> saine

Entrées : parts déjà filtrées par compute._dilution_shares (plancher
SHARES_FLOOR + échelle relative aux autres exercices, source unique
plausible_shares) — SANS ce garde-fou, l'erreur mesurée RMD 2021
(« 149 638 » déclaré en milliers) aurait donné une dilution de
+100 000 %. Les deux extrémités doivent être présentes et le passé
strictement positif : sinon None strict (« donnée manquante > faux
score »).

PIÈGE DE SPLIT (mesuré sur données réelles avant correction) : les parts
déclarées sont post-split d'un côté et pré-split de l'autre — Apple
+552 % en 2014 (7:1) et +283 % en 2020 (4:1) n'étaient QUE des splits,
pas des émissions. `splits` = [(date, facteur)] de l'entreprise (app.
edgar.yahoo) ; tout split entre les deux dates d'observation ramène
l'ancienne extrémité à l'échelle du présent (× facteur) avant la
comparaison — un vrai ×8 type AMC 2021 sans split reste détecté, la
correction ne touche que les sauts de split.

BASES MIXTES REFUSÉES (mesuré : 886 paires sur 8 826) : comparer une
part de couverture (dei, instantanée à la date de couverture) à une part
pondérée moyenne (moyenne sur l'exercice) mesure deux choses
différentes — le saut de base passerait pour de la dilution (AMC 2022 :
95 M de moyenne -> 517 M de couverture = +441 % de mélange, pas
d'émission). Sources différentes -> None strict.

Limite assumée connue (reste en V2.1) : une chaine PONDÉRÉE/PONDÉRÉE
peut comparer des vintages de déclaration différents (le chargeur garde
la déclaration la plus récente ; un 10-K post-reverse-split restate les
comparatifs de l'histoire — mesuré : AMC exercice 2021 à −59 % lu entre
234 M de l'édition 2023 et 95 M de l'édition 2024). Sans schéma
multi-vintage on garde la valeur honnête de la base ; le composite
d'AMC n'en dépend pas (altman/événements le portent).

Un reverse split (division des parts) fait chuter le ratio -> « saine » :
c'est voulu, un reverse split n'est pas une dilution d'actionnaires.
"""

from app.signals.common import SEV_ALERT, SEV_OK, SEV_WATCH, SignalResult

# Bandes : mi-seuil (5 %) et seuil feuille de route (10 %).
WATCH_GROWTH = 0.05
ALERT_GROWTH = 0.10


def evaluate(
    prev_shares: float | None,
    cur_shares: float | None,
    period_end: str,
    filing_id: str | None,
    prev_date: str | None = None,
    cur_date: str | None = None,
    prev_source: str | None = None,
    cur_source: str | None = None,
    splits: list[tuple[str, float]] | None = None,
) -> SignalResult | None:
    """Croissance annuelle des parts en circulation pour l'exercice courant.

    `prev_date` / `cur_date` : dates d'observation des deux extrémités
    (celles des nœuds XBRL) — fenêtre de recherche des splits. Dates
    absentes avec des splits fournis : pas de correction possible, le
    calcul continue non corrigé (les nœuds ont toujours une date en
    pratique ; garde d'urgence, pas un cas normal).

    `prev_source` / `cur_source` : d'où vient chaque extrémité (dei
    couverture vs repli parts pondérées) — tracé dans details : un
    exercice mesuré en dei et l'autre en repli pondéré reste lisible et
    auditable pour l'utilisateur.
    """
    if prev_shares is None or cur_shares is None:
        return None
    if prev_shares <= 0:
        # Division par zéro ou parts négatives : déclaration inutilisable.
        return None
    if (
        prev_source is not None
        and cur_source is not None
        and prev_source != cur_source
    ):
        # Bases hétérogènes (dei instantané vs moyenne pondérée) : le saut
        # mesurerait le changement de base, pas une dilution (cf. docstring).
        return None

    # --- Correction de split (cf. docstring) -------------------------------
    # Comparaison lexicographique des ISO : même astuce que raw_close.
    split_factor = 1.0
    in_window: list[tuple[str, float]] = []
    if splits and prev_date and cur_date:
        for split_date, ratio in splits:
            if prev_date < split_date <= cur_date:
                split_factor *= ratio
                in_window.append((split_date, ratio))
    comparable_prev = prev_shares * split_factor
    if comparable_prev <= 0:
        return None

    # Arrondi AVANT la comparaison : 110/100 en flottant donne
    # 0.10000000000000009 et ferait sauter le seuil strict « > 10 % ».
    # Décision et valeur stockée sont ainsi le MÊME nombre (cohérence
    # badge/valeur sur la fiche), à 4 décimales — bien au-delà de la
    # précision d'une déclaration de parts.
    growth = round(cur_shares / comparable_prev - 1.0, 4)

    if growth > ALERT_GROWTH:
        severity = SEV_ALERT
    elif growth > WATCH_GROWTH:
        severity = SEV_WATCH
    else:
        severity = SEV_OK

    return SignalResult(
        signal_type="dilution",
        period_end=period_end,
        value=growth,
        severity=severity,
        details={
            "shares_prev": float(prev_shares),
            "shares_cur": float(cur_shares),
            "growth": growth,
            "watch_threshold": WATCH_GROWTH,
            "alert_threshold": ALERT_GROWTH,
            "shares_source_prev": prev_source,
            "shares_source_cur": cur_source,
            # Auditabilité de la correction : facteur appliqué + splits
            # retenus (vide = aucun dans la fenêtre des deux dates).
            "split_factor": split_factor if split_factor != 1.0 else None,
            "splits_in_window": in_window,
        },
        filing_id=filing_id,
    )
