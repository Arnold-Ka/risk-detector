"""M-score de Beneish — probabilité de manipulation des comptes (1999).

Somme pondérée de huit ratios qui comparent l'exercice t à t-1 :

    M = -4,840 + 0,920·DSRI + 0,528·GMI + 0,404·AQI + 0,892·SGI
             + 0,115·DEPI - 0,172·LVGI + 4,679·TATA

    DSRI = (receivables/CA)_{t} / (receivables/CA)_{t-1}      (allongement clients)
    GMI  = marge brute_{t-1} / marge brute_{t}                (marge qui se dégrade)
    AQI  = (1 - (actifs circulants + FP) / actif)_{t} / ...   (accumulation d'actifs)
    SGI  = CA_{t} / CA_{t-1}                                  (croissance des ventes)
    SGAI = (SGA/CA)_{t} / (SGA/CA)_{t-1}                      (dépenses admin. hors norme)
    DEPI = (amortissements/FP)_{t-1} / (amortissements/FP)_{t} (amortissement ralenti)
    LVGI = ((dette LT + passifs circulants)/actif)_{t} / ...   (levier qui monte)
    TATA = (résultat net - CFO) / actif                        (accruals totaux)

Lecture (feuille de route §2) : M > -1,78 = suspect (alerte). Seuils
complémentaires de la littérature : M <= -2,27 = « strong non-manipulator ».

Règle produit stricte ici (plus que pour les autres signaux) : M est une
SOMME pondérée — on ne peut pas sommer 7 ratios sur 8 sans fausser
l'interception du modèle. Une entrée manquante => None.

Entrées non disponibles constatées (vérifié sur companyfacts 2026-10-12) :
  - AMC : ni résultat brut ni coût des ventes annuels ni SGA agrégé =>
    GMI et SGAI impossibles => pas de M-score pour AMC (affiché
    « donnée manquante ») ;
  - BBBY : receivables via la variante cartes (tag ajoutée au YAML, cf.
    receivables) — sinon DSRI impossible.
"""

from app.signals.common import SEV_ALERT, SEV_OK, SEV_WATCH, SignalResult

# Coefficients du modèle Beneish (article 1999, Table 5). On garde les
# valeurs exactes de la publication — un coefficient modifié invalide les
# seuils -1,78 / -2,27.
INTERCEPT = -4.840
COEFFS = {
    "dsri": 0.920,
    "gmi": 0.528,
    "aqi": 0.404,
    "sgi": 0.892,
    "depi": 0.115,
    "lvgi": -0.172,
    "tata": 4.679,
}

M_SUSPECT = -1.78  # feuille de route : M > -1,78 = suspect
M_STRONG = -2.27   # littérature : en dessous = « non-manipulator »


def severity(m: float) -> str:
    if m > M_SUSPECT:
        return SEV_ALERT
    if m > M_STRONG:
        return SEV_WATCH
    return SEV_OK


def _div(num, den) -> float | None:
    """Division défensive : dénominateur absent ou nul => ratio inexploitable."""
    if num is None or den is None or den == 0:
        return None
    return num / den


def evaluate(
    prev: dict,
    cur: dict,
    period_end: str,
    filing_id: str | None,
) -> SignalResult | None:
    """M-score de l'exercice `cur` vs `prev`, ou None si un ratio manque.

    prev/cur = {concept: valeur} (valeurs None = absentes).
    """
    if not prev:
        return None

    # Marge brute : gross_profit/sales ; sinon 1 - (sales-costs)/sales n'est
    # pas reconstructible sans tag de coût => None (pas de déduction hasardeuse).
    def gross_margin(y: dict) -> float | None:
        gp, s = y.get("gross_profit"), y.get("sales")
        if gp is None or s is None or s == 0:
            return None
        return gp / s

    # --- Les huit ratios -----------------------------------------------------
    # Chacun : None si une entrée manque ; la somme finale annule tout.
    dsri = _ratio_quotient(
        _div(cur.get("receivables"), cur.get("sales")),
        _div(prev.get("receivables"), prev.get("sales")),
    )
    gm_cur, gm_prev = gross_margin(cur), gross_margin(prev)
    gmi = _ratio_quotient(gm_prev, gm_cur)  # > 1 si la marge DÉGRADE

    def liquidity_assets(y: dict) -> float | None:
        ca, ppe, ta = y.get("current_assets"), y.get("ppe"), y.get("total_assets")
        if ta is None or ta <= 0:
            return None
        if ca is None or ppe is None:
            return None
        return 1 - (ca + ppe) / ta

    aqi = _ratio_quotient(liquidity_assets(cur), liquidity_assets(prev))
    sgi = _ratio_quotient(cur.get("sales"), prev.get("sales"))
    sgai = _ratio_quotient(
        _div(cur.get("sga"), cur.get("sales")),
        _div(prev.get("sga"), prev.get("sales")),
    )

    def dep_ppe(y: dict) -> float | None:
        return _div(y.get("depreciation"), y.get("ppe"))

    depi = _ratio_quotient(dep_ppe(prev), dep_ppe(cur))  # > 1 si amort. ralentit

    def leverage(y: dict) -> float | None:
        ltd, cl, ta = y.get("long_term_debt"), y.get("current_liabilities"), y.get("total_assets")
        if ta is None or ta <= 0 or ltd is None or cl is None:
            return None
        return (ltd + cl) / ta

    lvgi = _ratio_quotient(leverage(cur), leverage(prev))
    tata = _div(
        None
        if (cur.get("net_income") is None or cur.get("cfo") is None)
        else cur["net_income"] - cur["cfo"],
        cur.get("total_assets"),
    )

    ratios = {"dsri": dsri, "gmi": gmi, "aqi": aqi, "sgi": sgi,
              "sgai": sgai, "depi": depi, "lvgi": lvgi, "tata": tata}
    missing = [name for name, value in ratios.items() if value is None]
    if missing:
        return None  # somme pondérée : un ratio absent invalide tout le M

    m = INTERCEPT + sum(COEFFS[name] * ratios[name] for name in COEFFS)
    return SignalResult(
        signal_type="beneish",
        period_end=period_end,
        value=round(m, 4),
        severity=severity(m),
        details={"ratios": ratios},
        filing_id=filing_id,
    )


def _ratio_quotient(num, den) -> float | None:
    """Quotient de deux ratios : None si l'un des deux est inexploitable."""
    if num is None or den is None or den == 0:
        return None
    return num / den
