"""Signal « ventes massives d'actions par les dirigeants » (Form 4, §2).

Pourquoi c'est inquiétant (feuille de route §2) : « ceux qui savent le
plus vendent ». Un dirigeant qui vend massivement ses titres alors que
l'entreprise communique sur des perspectives positives est un signal
d'alerte classique (§16 b).

Définition v1 (perimètre et seuils — tunables au backtest comme
critical_8k) :
  - transactions retenues = ventes sur marché OUVERTES : code EDGAR "S"
    uniquement, tableau non dérivé (le parseur filtre déjà les droits
    dérivés) ; exclus : F (retenue fiscale — pas un choix), M (exercice
    d'options), G (don), P (achat)… ;
  - vendeurs retenus = officier OU directeur (certains dépôts anciens
    remplissent officerTitle sans passer isOfficer — d'où le OU sur les
    trois drapeaux) ;
  - « massif » = valeur des ventes rapportée au capital :
      ratio = somme(prix x quantité) / capitalisation, sinon
              somme(quantité) / actions en circulation (fallback tracé)
    Bandes : >= 0,25 % vigilance ; >= 1,0 % défaillance.

Strict-None maison : sans aucun dénominateur (pas de capitalisation ni
d'actions), pas de score — « donnée manquante » plutôt qu'un chiffre
inventé. 0 vente = signal « saine » (la courbe continue, le zéro est
vrai puisqu'on a bien regardé les Form 4 de l'exercice).
"""

from app.signals.common import SEV_ALERT, SEV_OK, SEV_WATCH, SignalResult

# Code EDGAR de vente sur marché ouverte (choix du vendeur).
SELL_CODE = "S"

# Seuils initiaux (ratios du capital vendus sur un exercice civil).
WATCH_RATIO = 0.0025  # 0,25 %
ALERT_RATIO = 0.01    # 1,0 %


def is_open_sale(tx: dict) -> bool:
    """True si la transaction est une vente ouverte par officier/directeur.

    Partagé par compute.py (filtre par exercice) et les tests.
    """
    if tx.get("code") != SELL_CODE:
        return False
    return bool(
        tx.get("is_officer") or tx.get("is_director") or tx.get("officer_title")
    )


def evaluate(
    sales: list[dict],
    market_capitalisation: float | None,
    shares_outstanding: float | None,
    period_end: str,
    filing_id: str | None,
) -> SignalResult | None:
    """Ventes ouvertes des dirigeants de l'exercice -> SignalResult.

    `sales` = transactions déjà filtrées par is_open_sale(). Chaque
    transaction porte value/shares (value peut être None si prix absent).
    filing_id = dépôt du Form 4 de la plus grosse vente (traçabilité).
    """
    if not sales:
        return SignalResult(
            signal_type="insider_sales",
            period_end=period_end,
            value=0.0,
            severity=SEV_OK,
            details={"n_sales": 0, "n_sellers": 0, "sold_value": 0.0},
            filing_id=filing_id,
        )

    sold_value = sum(t.get("value") or 0.0 for t in sales)
    sold_shares = sum(t.get("shares") or 0.0 for t in sales)
    n_sellers = len({t.get("owner_name") for t in sales if t.get("owner_name")})

    if market_capitalisation:
        ratio = sold_value / market_capitalisation
        denominator = "capitalisation"
        denominator_value = float(market_capitalisation)
    elif shares_outstanding:
        # Fallback : parts vendues / parts en circulation (le prix se
        # simplifie quand il est homogène — approximatif si prix variables,
        # mais honnête : la provenance est tracée dans denominator).
        ratio = sold_shares / float(shares_outstanding)
        denominator = "actions_en_circulation"
        denominator_value = float(shares_outstanding)
    else:
        # Aucun dénominateur : strict-None (donnée manquante).
        return None

    if ratio >= ALERT_RATIO:
        severity = SEV_ALERT
    elif ratio >= WATCH_RATIO:
        severity = SEV_WATCH
    else:
        severity = SEV_OK

    worst = max(sales, key=lambda t: (t.get("value") or 0.0))
    return SignalResult(
        signal_type="insider_sales",
        period_end=period_end,
        value=round(ratio, 6),
        severity=severity,
        details={
            "ratio": round(ratio, 6),
            "denominator": denominator,
            "denominator_value": round(denominator_value, 2),
            "sold_value": round(sold_value, 2),
            "sold_shares": sold_shares,
            "n_sales": len(sales),
            "n_sellers": n_sellers,
            "worst_owner": worst.get("owner_name"),
        },
        # Traçabilité sur le plus gros dépôt de vente (règle produit).
        filing_id=worst.get("filing_id") or filing_id,
    )
