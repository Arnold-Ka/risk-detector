"""Écart bénéfice / cash opérationnel — le bénéfice monte, le cash descend.

Principe (feuille de route §2) : un résultat net en hausse pendant que le
flux de trésorerie d'exploitation recule signale que les « profits » ne se
transforment pas en cash (accruals, stocks/créances qui gonflent, ou
comptes agressifs) — qualité des bénéfices.

Seuil d'alerte de la feuille de route : « 2 périodes consécutives ».
Décision du 2026-10-12 (avec l'utilisateur) : base ANNUELLE pour le MVP
(2 exercices consécutifs), l'extension trimestrielle (10-Q) viendra si le
backtest montre que c'est le maillon faible. Le streak ci-dessous compte
donc des exercices, pas des trimestres.

Sévérité :
    0 divergence  -> saine
    1 exercice    -> vigilance
    >= 2          -> défaillance (le seuil de la feuille de route)

Entrées manquantes (NI ou CFO sur l'année courante ou précédente) =>
aucun signal pour cet exercice (skip, pas de valeur inventée).

Seul signal qui a besoin de PLUSIEURS exercices (streak) : il s'appelle
une fois sur l'historique complet, pas par exercice isolé.
"""

from app.signals.common import SEV_ALERT, SEV_OK, SEV_WATCH, SignalResult


def _val(year_node: dict, concept: str):
    """Valeur d'un concept (nœud {value, period_end, filing_id}) ou None."""
    node = year_node.get(concept)
    return node.get("value") if node else None


def _divergent(ni_prev, ni_cur, cfo_prev, cfo_cur) -> bool | None:
    """True si bénéfice en hausse ET cash en baisse ; None si entrée absente."""
    if None in (ni_prev, ni_cur, cfo_prev, cfo_cur):
        return None
    return ni_cur > ni_prev and cfo_cur < cfo_prev


def severity(streak: int) -> str:
    if streak >= 2:
        return SEV_ALERT
    if streak == 1:
        return SEV_WATCH
    return SEV_OK


def evaluate_history(years: dict[int, dict[str, dict]]) -> dict[int, SignalResult]:
    """Calcule le streak de divergence pour tous les exercices évaluables.

    years = {année: {concept: node}} — même forme que compute.build_years
    (node = {value, period_end, filing_id}). Chaque exercice dont t ET t-1
    sont évaluables reçoit un SignalResult ; les autres années sont
    absentes (données manquantes).
    """
    results: dict[int, SignalResult] = {}
    streak = 0
    for year in sorted(years):
        prev = years.get(year - 1)
        if not prev:
            continue
        cur = years[year]
        is_div = _divergent(
            _val(prev, "net_income"), _val(cur, "net_income"),
            _val(prev, "cfo"), _val(cur, "cfo"),
        )
        if is_div is None:
            continue  # entrée manquante : exercice non évaluable
        streak = streak + 1 if is_div else 0

        # Ancre de traçabilité : le dépôt du résultat net de l'exercice
        # (le signal porte sur le couple bénéfice/cash de ce 10-K).
        node = cur.get("net_income") or cur.get("cfo") or {}
        results[year] = SignalResult(
            signal_type="divergence",
            period_end=node.get("period_end") or f"{year}-12-31",
            value=float(streak),
            severity=severity(streak),
            details={
                "streak": streak,
                "net_income": [_val(prev, "net_income"), _val(cur, "net_income")],
                "cfo": [_val(prev, "cfo"), _val(cur, "cfo")],
                "divergent": is_div,
            },
            filing_id=node.get("filing_id"),
        )
    return results
