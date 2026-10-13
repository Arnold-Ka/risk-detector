"""F-score de Piotroski — solidité financière de 0 à 9 (Piotroski, 2000).

Neuf critères binaires évalués sur DEUX exercices consécutifs (t vs t-1) ;
un point par critère satisfait. Lecture (feuille de route §2) :
    7 à 9 : solide
    3 à 6 : intermédiaire
    0 à 2 : entreprise fragile  <-- seuil d'alerte de la feuille de route

Critères (F1-F9, définitions classiques) :
    F1  ROA  = résultat net / actif total                      > 0
    F2  Flux de trésorerie d'exploitation                      > 0
    F3  ROA en hausse vs t-1
    F4  Accruals : CFO > résultat net  (bénéfice de plus haute qualité)
    F5  Levier en baisse : dette long terme / actif total diminue
    F6  Liquidité en hausse : actifs circulants / passifs circulants augmente
    F7  Pas d'émission d'actions : parts en circulation non augmentées
    F8  Marge en hausse (voir repli ci-dessous)
    F9  Rotation des actifs en hausse : CA / actif total

Repli F8 (documenté, trace dans details.margin_source) : la marge est
calculée sur le résultat brut (gross_profit/sales) quand il existe, sinon
sur le résultat d'exploitation (operating_income/sales) — l'AMC ne publie
AUCUN résultat brut ni coût des ventes agrégé sur ses 10-K (vérifié le
2026-10-12 sur companyfacts) et Strict-None laisserait l'entreprise la plus
intéressante du trio sans F-score. Les deux définitions mesurent la même
chose (tendance de rentabilité opérationnelle) ; le critère concerné note
la direction du changement, pas son ampleur.

Règle produit : si un UNE SEULE des entrées manque, tout le score vaut
None (un F sur 7 surévalué mentirait autant qu'un F sur 9). Les entrées
absentes sont listées dans le résultat pour expliquer le « donnée
manquante » affiché.
"""

from app.signals.common import SEV_ALERT, SEV_OK, SEV_WATCH, SignalResult

# Seuils de lecture (feuille de route : 0-2 = fragile).
F_STRONG = 7
F_WEAK = 3  # en dessous = zone d'alerte (score 0-2)


def severity(score: int) -> str:
    if score < F_WEAK:
        return SEV_ALERT
    if score < F_STRONG:
        return SEV_WATCH
    return SEV_OK


def _margin(year: dict) -> tuple[float | None, str | None]:
    """Marge de l'exercice + source : 'gross_profit' ou 'operating_income'.

    year = {concept: valeur} pour UN exercice (les valeurs None sont
    traitées comme absentes).
    """
    sales = year.get("sales")
    if not sales:
        return None, None
    gp = year.get("gross_profit")
    if gp is not None:
        return gp / sales, "gross_profit"
    op = year.get("operating_income")
    if op is not None:
        return op / sales, "operating_income"
    return None, None


def evaluate(
    prev: dict,
    cur: dict,
    period_end: str,
    filing_id: str | None,
) -> SignalResult | None:
    """F-score sur l'exercice `cur` comparé à `prev` ({concept: valeur}).

    None si le premier exercice manque ou si un critère n'est pas
    évaluable — dans ce cas details['missing'] liste les coupables.
    """
    if not prev:
        return None

    def ratio(y: dict, num: str, den: str) -> float | None:
        n, d = y.get(num), y.get(den)
        if n is None or d is None or d <= 0:
            return None
        return n / d

    roa_cur = ratio(cur, "net_income", "total_assets")
    roa_prev = ratio(prev, "net_income", "total_assets")
    ni_cur, cfo_cur = cur.get("net_income"), cur.get("cfo")
    ltd_ratio_cur = ratio(cur, "long_term_debt", "total_assets")
    ltd_ratio_prev = ratio(prev, "long_term_debt", "total_assets")
    cr_cur = ratio(cur, "current_assets", "current_liabilities")
    cr_prev = ratio(prev, "current_assets", "current_liabilities")
    sh_cur, sh_prev = cur.get("shares_outstanding"), prev.get("shares_outstanding")
    margin_cur, margin_src_cur = _margin(cur)
    margin_prev, margin_src_prev = _margin(prev)
    turn_cur = ratio(cur, "sales", "total_assets")
    turn_prev = ratio(prev, "sales", "total_assets")

    criteria = {
        # Noms en clair dans details : l'utilisateur lit le pourquoi, pas F5.
        "profitability_positive": (roa_cur is not None and roa_cur > 0)
        if roa_cur is not None else None,
        "cash_flow_positive": (cfo_cur > 0) if cfo_cur is not None else None,
        "roa_improving": (roa_cur > roa_prev)
        if (roa_cur is not None and roa_prev is not None) else None,
        "accruals_quality": (cfo_cur > ni_cur)
        if (cfo_cur is not None and ni_cur is not None) else None,
        "leverage_decreasing": (ltd_ratio_cur < ltd_ratio_prev)
        if (ltd_ratio_cur is not None and ltd_ratio_prev is not None) else None,
        "liquidity_improving": (cr_cur > cr_prev)
        if (cr_cur is not None and cr_prev is not None) else None,
        "no_new_equity": (sh_cur <= sh_prev)
        if (sh_cur is not None and sh_prev is not None) else None,
        "margin_improving": (margin_cur > margin_prev)
        if (margin_cur is not None and margin_prev is not None) else None,
        "asset_turnover_improving": (turn_cur > turn_prev)
        if (turn_cur is not None and turn_prev is not None) else None,
    }

    missing = [name for name, flag in criteria.items() if flag is None]
    if missing:
        # Strict-None : un F partiel serait un faux score (règle produit).
        # Le job nocturne ne stocke rien et l'affichage dira « donnée
        # manquante » ; aucun détail partiel n'est conservé pour éviter
        # qu'un demi-score ne soit jamais lu comme un vrai F.
        return None

    score = sum(1 for flag in criteria.values() if flag)
    # Tracer la source de F8 quand le repli operating_income a servi.
    margin_source = None
    if margin_src_cur == "operating_income" or margin_src_prev == "operating_income":
        margin_source = "operating_income_fallback"

    return SignalResult(
        signal_type="piotroski",
        period_end=period_end,
        value=float(score),
        severity=severity(score),
        details={
            "criteria": criteria,
            "roa": roa_cur,
            "current_ratio": cr_cur,
            "leverage": ltd_ratio_cur,
            "margin": margin_cur,
            "margin_source": margin_source,
            "asset_turnover": turn_cur,
        },
        filing_id=filing_id,
    )
