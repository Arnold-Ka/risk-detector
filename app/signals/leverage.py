"""Dette nette / EBITDA — poids de la dette (feuille de route §2, V2).

Ligne V2 du tableau de signaux (§2) :
    « Dette nette / EBITDA | Poids de la dette |
       Supérieur à 4 et en hausse | V2 »

Définitions, uniquement avec les concepts déjà dans xbrl_map.yaml
(aucune ré-ingestion de la cohorte nécessaire) :
  dette nette = dette long terme (long_term_debt) − trésorerie (cash) ;
  EBITDA      = résultat d'exploitation (operating_income)
                + amortissements (depreciation) — proxy classique E + D&A ;
                sans amortissements publiés pour l'exercice, repli sur
                l'EBIT seul, source tracée dans details.ebitda_source
                (même esprit que le repli marge de Piotroski F8).

Lecture (cohérente avec les 4 lignes MVP de la feuille de route, dont le
seuil est toujours noté en défaillance) :
  - ratio > 4 ET en hausse vs l'exercice précédent  -> défaillance
    (c'est littéralement le critère d'alerte « et en hausse ») ;
  - ratio > 4 sans tendance confirmée               -> vigilance
    (hors pic, tendance absente ou en baisse) ;
  - ratio ≤ 4                                       -> saine ;
  - EBITDA ≤ 0 avec dette nette positive            -> défaillance
    (aucun résultat à sommet pour porter la dette : le ratio EST
    infini, on n'affiche pas de nombre — value None, règle produit
    « donnée manquante > faux score » s'applique à la valeur, pas à la
    sévérité qui, elle, est un fait : pas de cash-flow à rembourser) ;
  - EBITDA ≤ 0 avec trésorerie supérieure à la dette -> saine
    (position de trésorerie nette : rien à servir malgré la perte).

Entrées manquantes (dette long terme, trésorerie ou résultat
d'exploitation absents) -> None strict, comme tous les signaux : 154
entreprises de la cohorte ne taguent pas de dette long terme standard
(couverture mesurée 721/875), elles auront simplement « donnée
manquante ».

Limite assumée : seules les dettes LONG TERMES entrent dans la dette
nette (les dettes courantes / revolver ne sont pas taguées en standard).
Le ratio est donc un plancher du levier réel pour les émetteurs à
découvert courant — inoffensif pour la règle « en hausse » (biais
constant d'un exercice à l'autre), documenté ici plutôt que masqué.
"""

from app.signals.common import SEV_ALERT, SEV_OK, SEV_WATCH, SignalResult

# Seuil d'alerte de la feuille de route (« supérieur à 4 »).
ALERT_RATIO = 4.0


def _components(year: dict) -> tuple[float | None, float | None, str | None]:
    """(dette nette, EBITDA, source EBITDA) pour l'exercice.

    (None, None, None) si une entrée obligatoire manque : dettes long
    terme, trésorerie et résultat d'exploitation sont les trois piliers
    du calcul — un pilier absent tue tout le signal.
    """
    ltd = year.get("long_term_debt")
    cash = year.get("cash")
    ebit = year.get("operating_income")
    if ltd is None or cash is None or ebit is None:
        return None, None, None
    dep = year.get("depreciation")
    if dep is not None:
        return float(ltd) - float(cash), float(ebit) + float(dep), "operating_income_plus_depreciation"
    # Repli documenté : EBIT seul (déjà utilisé par Altman en entrée E).
    return float(ltd) - float(cash), float(ebit), "operating_income_only"


def _ratio(year: dict | None) -> float | None:
    """Ratio dette nette / EBITDA de l'exercice, ou None (indéfini).

    Indéfini si entrées manquantes ou EBITDA ≤ 0 — dans ces cas-là la
    comparaison d'année à l'autre n'a pas de sens numérique (cf. docstring).
    """
    if not year:
        return None
    net_debt, ebitda, _source = _components(year)
    if net_debt is None or ebitda is None or ebitda <= 0:
        return None
    return net_debt / ebitda


def evaluate(
    prev: dict | None,
    cur: dict,
    period_end: str,
    filing_id: str | None,
) -> SignalResult | None:
    """Signal dette nette / EBITDA pour l'exercice `cur` ({concept: valeur}).

    `prev` = exercice précédent ({concept: valeur}) ou None : sans lui on
    ne peut pas confirmer « en hausse » -> un ratio > 4 plafonne à la
    vigilance (details['rising'] = None le trace). `cur` sans dettes,
    trésorerie ou EBIT -> None strict.
    """
    net_debt, ebitda, ebitda_source = _components(cur)
    if net_debt is None or ebitda is None:
        return None

    ltd = float(cur["long_term_debt"])
    cash = float(cur["cash"])
    ebit = float(cur["operating_income"])
    dep = cur.get("depreciation")
    ratio_prev = _ratio(prev)

    if ebitda <= 0:
        # Pas de ratio affichable : la sévérité reste un fait calculable.
        if net_debt > 0:
            # Dette à servir, aucun cash-flow pour le faire : le ratio
            # tend vers +∞ — on émet la sévérité sans nombre.
            severity = SEV_ALERT
            reason = "ebitda_non_positive_avec_dette"
        else:
            severity = SEV_OK
            reason = "ebitda_non_positive_avec_trésorerie_nette"
        return SignalResult(
            signal_type="net_debt_ebitda",
            period_end=period_end,
            value=None,
            severity=severity,
            details={
                "reason": reason,
                "long_term_debt": ltd,
                "cash": cash,
                "net_debt": net_debt,
                "operating_income": ebit,
                "depreciation": float(dep) if dep is not None else None,
                "ebitda": ebitda,
                "ebitda_source": ebitda_source,
                "alert_threshold": ALERT_RATIO,
            },
            filing_id=filing_id,
        )

    ratio = round(net_debt / ebitda, 3)
    rising: bool | None = None
    if ratio_prev is not None:
        # Comparaison sur les valeurs arrondies AFFICHÉES : le bruit de
        # flottant (4,00000000001) ne doit pas basculer une sévérité ni
        # contredire le chiffre montré à l'utilisateur.
        rising = ratio > round(ratio_prev, 3)

    if ratio > ALERT_RATIO:
        severity = SEV_ALERT if rising else SEV_WATCH
    else:
        severity = SEV_OK

    return SignalResult(
        signal_type="net_debt_ebitda",
        period_end=period_end,
        value=ratio,
        severity=severity,
        details={
            "long_term_debt": ltd,
            "cash": cash,
            "net_debt": net_debt,
            "operating_income": ebit,
            "depreciation": float(dep) if dep is not None else None,
            "ebitda": ebitda,
            "ebitda_source": ebitda_source,
            "ratio_prev": round(ratio_prev, 3) if ratio_prev is not None else None,
            "rising": rising,
            "alert_threshold": ALERT_RATIO,
        },
        filing_id=filing_id,
    )
