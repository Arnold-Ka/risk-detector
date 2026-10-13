"""Z-score d'Altman — probabilité de défaut à 2 ans.

Formule (article d'Altman 1968, sociétés industrielles cotées — c'est la
variante qu'impose la feuille de route §2) :

    A = fonds de roulement  / actif total       (liquidité)
    B = bénéfices non distribués / actif total  (rentabilité cumulée)
    C = EBIT               / actif total        (rentabilité opérationnelle)
    D = capitalisation boursière / dettes totales book   <- D est DÉJÀ un
        ratio (valeur de marché des titres / passif book) : on ne le
        normalise PAS par l'actif, contrairement à A/B/C/E. C'est la
        définition de la feuille de route et celle du script de phase 0
        scripts/compute_z.py — les deux implémentations doivent rester
        alignées (couvert par le test golden de tests/test_altman.py).
    E = chiffre d'affaires  / actif total       (rotation des actifs)

    Z = 1,2·A + 1,4·B + 3,3·C + 0,6·D + 1,0·E

Seuils (les bandes de la feuille de route, mêmes que scripts/compute_z.py) :
    Z > 2,99   zone saine
    1,81–2,99  zone grise (vigilance)
    Z < 1,81   zone de détresse  <-- déclencheur d'alerte

Avertissement de secteur (§2) : score PAS fiable pour banques, assurances
et REIT — l'appelant (job nocturne, API) filtre sur companies.sector_group.

Règle produit : renvoyer None dès qu'une composante manque (la phase 0 a
montré que Z sans D — titre delisté — n'avait aucun sens) : jamais de
composante silencieusement remplacée par 0. Exception assumée : EBIT ou
bénéfices valant 0 sont des valeurs LÉGITIMES et ne déclenchent pas None.
"""

from app.signals.common import SEV_ALERT, SEV_OK, SEV_WATCH, SignalResult

# Bandes d'interprétation (valeurs de la feuille de route §2).
Z_SAFE = 2.99
Z_DISTRESS = 1.81


def altman_severity(z: float) -> str:
    """Bande Altman -> sévérité produit (mêmes seuils que phase 0)."""
    if z < Z_DISTRESS:
        return SEV_ALERT
    if z < Z_SAFE:
        return SEV_WATCH
    return SEV_OK


def evaluate(
    working_capital,
    total_assets,
    retained_earnings,
    ebit,
    market_capitalisation,
    total_liabilities,
    sales,
    period_end: str,
    filing_id: str | None,
) -> SignalResult | None:
    """Calcule Z pour un exercice, ou None si une composante manque.

    Entrées = valeurs BRUTES (pas des ratios) ; les divisions sont
    interne. `working_capital` peut être négatif (legit) ; 0 pour EBIT ou
    bénéfices est legit aussi.
    """
    # Dénominateurs : sans actif total ni dettes totales, A/B/C/E/D sont
    # tous indéfinis. `<= 0` couvre le 0 (division par zéro) et un bilan
    # impossible ; None couvre l'absence.
    if total_assets is None or total_assets <= 0:
        return None
    if total_liabilities is None or total_liabilities <= 0:
        return None
    # Composantes de numérateur : None = donnée absente de l'extraction.
    numerators = (working_capital, retained_earnings, ebit, market_capitalisation, sales)
    if any(v is None for v in numerators):
        return None

    a = working_capital / total_assets
    b = retained_earnings / total_assets
    c = ebit / total_assets
    d = market_capitalisation / total_liabilities  # ratio déjà normalisé
    e = sales / total_assets
    z = 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e

    return SignalResult(
        signal_type="altman",
        period_end=period_end,
        value=round(z, 4),
        severity=altman_severity(z),
        details={"A": a, "B": b, "C": c, "D": d, "E": e},
        filing_id=filing_id,
    )
