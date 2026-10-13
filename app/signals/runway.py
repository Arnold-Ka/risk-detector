"""Autonomie de trésorerie — mois de survie au rythme de brûlage actuel.

    runway_months = trésorerie / (brûlage mensuel),  brûlage = max(0, -CFO)

Le flux de trésorerie d'exploitation annuel est ramené à un mois
(brûlage = -CFO / 12) ; on suppose le rythme de l'exercice maintenu —
hypothèse volontairement simple pour le MVP, affichée comme telle.

Lecture (feuille de route §2) : moins de 12 mois = alerte.

Cas particuliers (règle produit « donnée manquante > faux chiffre ») :
  - CFO >= 0 : l'entreprise ne brûle pas, il n'y a pas de mois de survie à
    calculer => value None (jamais un « ∞ » ou 999 qui polluerait les
    graphiques), sévérité « saine » — le signal est stocké car « pas de
    brûlage » est une information positive voulue par l'affichage ;
  - trésorerie négatif (découvert) avec brûlage => valeur planchée à 0
    mois (détresse déjà là ; la valeur brute négative reste dans details).
"""

from app.signals.common import SEV_ALERT, SEV_OK, SEV_WATCH, SignalResult

RUNWAY_ALERT = 12.0  # mois : seuil d'alerte de la feuille de route
RUNWAY_WATCH = 24.0  # mois : zone de vigilance intermédiaire


def severity(months: float | None) -> str:
    if months is None:
        return SEV_OK  # aucun brûlage (voir docstring)
    if months < RUNWAY_ALERT:
        return SEV_ALERT
    if months < RUNWAY_WATCH:
        return SEV_WATCH
    return SEV_OK


def evaluate(
    cash,
    cfo,
    period_end: str,
    filing_id: str | None,
) -> SignalResult | None:
    """Mois de survie pour un exercice, ou None si cash/CFO manquent."""
    if cash is None or cfo is None:
        return None

    if cfo >= 0:
        # Pas de brûlage : signal « saine » sans valeur numérique.
        return SignalResult(
            signal_type="runway",
            period_end=period_end,
            value=None,
            severity=SEV_OK,
            details={"cash": cash, "cfo": cfo, "burn_annual": 0.0},
            filing_id=filing_id,
        )

    burn_annual = -cfo  # brûlage annuel (positif par construction)
    months_raw = cash / (burn_annual / 12.0)
    months = max(0.0, months_raw)  # trésorerie négative => 0 mois (voir doc)

    return SignalResult(
        signal_type="runway",
        period_end=period_end,
        value=round(months, 1),
        severity=severity(months),
        details={"cash": cash, "cfo": cfo, "burn_annual": burn_annual,
                 "months_raw": round(months_raw, 2)},
        filing_id=filing_id,
    )
