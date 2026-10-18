"""Types partagés par tous les signaux quantitatifs (phase 1, §6 sem. 5-6).

Conventions du paquet `app.signals` :
  - chaque module expose `evaluate(...) -> SignalResult | None` ;
  - `None` = au moins une donnée d'entrée manquante → le signal n'est PAS
    stocké et l'affichage dira « donnée manquante » (règle produit nº1,
    jamais un faux score) ;
  - `severity` en français car c'est du texte affiché à l'utilisateur ;
    les identifiants (signal_type, clés de details) restent en anglais ;
  - `value` porte le chiffre brut (Z, F, M, mois, streak, indice composite)
    et `details` porte les ratios intermédiaires : c'est ce qui rend le
    score explicable et auditable sur la fiche de risque (§4 « tout calcul
    est traçable »).
"""

from dataclasses import dataclass, field

# --- Vocabulaire des sévérités (textes affichés, en français) ---------------
# Les composants utilisent les mêmes bandes que la colonne `zone` du Z
# d'Altman calculée en phase 0 : un seul vocabulaire produit.
SEV_OK = "saine"
SEV_WATCH = "vigilance"
SEV_ALERT = "défaillance"

# Score global (§2 « niveau de risque : faible, modéré, élevé, critique »).
LEVEL_LOW = "faible"
LEVEL_MEDIUM = "modéré"
LEVEL_HIGH = "élevé"
LEVEL_CRITICAL = "critique"

SEVERITIES = (SEV_OK, SEV_WATCH, SEV_ALERT)
LEVELS = (LEVEL_LOW, LEVEL_MEDIUM, LEVEL_HIGH, LEVEL_CRITICAL)

# --- Planschers absolus de plausibilité (qualité des données) ---------------
# Erreurs d'échelle MESURÉES dans la base, même famille que les flottants
# NDSN/ADI (garde-fou relatif dans signals/compute._float_is_plausible) :
#   - PG&E 2009 : shares_outstanding = public_float = 12345 — le
#     télédéclarant a soumis une valeur de test ; cap = 44,65 $ x 12 345
#     = 551 k$ au lieu de ~20 Md$ (ratio « ventes dirigeants » = 11,4) ;
#   - Southwest 2008 : parts déclarées EN MILLIONS (735 au lieu de 735
#     M) -> cap 6 336 $ au lieu de 6,3 Md$ (ratio = 394 !).
# Un plancher ABSOLU est sans faux positif sur une société cotée réelle
# (les standards de cotation exigent ~1 M de parts publiques) — seul le
# déclarant en erreur passe en dessous. Rejeté -> repli de la chaîne de
# capitalisation, sinon strict-None (« donnée manquante > faux score »).
SHARES_FLOOR = 100_000.0  # parts : en dessous = déclaration en millions/kilos
FLOAT_FLOOR = 100_000.0   # $ de flottant : en dessous = coquille ou erreur


@dataclass
class SignalResult:
    """Un score calculé, rattaché à un exercice et à son dépôt source.

    - `period_end` : date de fin de période de l'exercice (celle du bilan)
      — PAS la date de calcul. C'est l'axe de l'historique : backtest et
      graphiques d'évolution se lisent sur cette colonne.
    - `filing_id` : dépôt dont proviennent les chiffres (traçabilité nº1).
      Peut être None pour un signal pur (composite : dérivé d'autres
      signaux eux-mêmes tracés).
    - `value` : None autorisé quand le signal est non numérique
      (runway sans brûlage : pas de mois à afficher, sévérité « saine »).
    """

    signal_type: str
    period_end: str  # date ISO 'YYYY-MM-DD'
    value: float | None
    severity: str
    details: dict = field(default_factory=dict)
    filing_id: str | None = None

    def to_row(self, company_id: str, computed_at: str) -> dict:
        """Ligne prête pour repo.replace_company_signals (SQL)."""
        return {
            "company_id": company_id,
            "signal_type": self.signal_type,
            "period_end": self.period_end,
            "value": self.value,
            "severity": self.severity,
            "details": self.details,
            "computed_at": computed_at,
            "filing_id": self.filing_id,
        }
