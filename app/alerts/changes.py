"""Détection des changements de palier du score global — fonctions pures.

Feuille de route §7 (phase 2) : « alertes par e-mail quand un nouveau
signal apparaît sur une entreprise suivie ». Version 1 retenue : alerter
quand le NIVEAU GLOBAL (composite faible / modéré / élevé / critique) du
dernier exercice change de palier — c'est l'information que l'utilisateur
peut comprendre et vérifier sans lire les 12 signaux.

Principe, SANS table d'état (le schéma n'a pas de migrations) :
  1. le nightly lit le dernier composite EN BASE avant de remplacer les
     signaux d'une entreprise (`before`) ;
  2. il calcule les nouveaux signaux et en extrait le dernier composite
     (`after`) ;
  3. palier différent = une alerte.
Une relance du nightly voit ensuite « avant = après » (le nouveau niveau est
déjà écrit) : pas de doublon. Contrepartie assumée : si l'envoi échoue après
l'écriture, l'alerte est perdue (journalisée), jamais renvoyée en double.

Ce module ne touche ni la base ni le réseau : le nightly lui passe des
dictionnaires, `app.alerts.mailer` envoie le résultat.
"""

from dataclasses import dataclass

from app.signals.common import LEVELS, SignalResult

# Miroir des libellés de frontend/lib/signals.ts (SIGNAL_LABELS) : l'e-mail
# doit parler la même langue que la fiche entreprise. L'ordre du dict est
# l'ordre d'affichage des composantes dans l'e-mail.
SIGNAL_LABELS: dict[str, str] = {
    "altman": "Altman Z",
    "piotroski": "Piotroski F",
    "beneish": "Beneish M",
    "divergence": "Écart bénéfice/cash",
    "runway": "Autonomie de trésorerie",
    "late_filing": "Dépôts en retard",
    "critical_8k": "8-K critiques",
    "insider_sales": "Ventes de dirigeants",
    "net_debt_ebitda": "Dette nette / EBITDA",
    "dilution": "Dilution d'actions",
}

DISCLAIMER = (
    "Outil informatif : ne constitue ni un conseil en investissement, ni une "
    "recommandation d'achat ou de vente. Les niveaux de risque sont des "
    "indicateurs, pas des prévisions de faillite."
)


@dataclass(frozen=True)
class LevelChange:
    """Un changement de palier du composite pour une entreprise."""

    cik: int
    name: str
    ticker: str | None
    before: str
    after: str
    before_period: str
    after_period: str
    # (signal_type, sévérité avant, sévérité après) ; None = non calculé.
    components: tuple[tuple[str, str | None, str | None], ...]

    @property
    def is_increase(self) -> bool:
        return LEVELS.index(self.after) > LEVELS.index(self.before)


def latest_composite_of(results: list[SignalResult]) -> dict | None:
    """Dernier composite (exercice le plus récent) parmi les signaux calculés.

    Même forme que `repo.latest_composite` pour que `detect_level_change`
    compare des objets identiques ; None si aucun composite n'est calculable
    (aucune composante disponible : pas de niveau inventé).
    """
    composites = [r for r in results if r.signal_type == "composite"]
    if not composites:
        return None
    last = max(composites, key=lambda r: str(r.period_end))
    return {
        "period_end": str(last.period_end),
        "severity": last.severity,
        "components": dict((last.details or {}).get("components", {})),
    }


def detect_level_change(
    company: dict, before: dict | None, after: dict | None
) -> LevelChange | None:
    """Compare deux derniers composites ; LevelChange si le palier a changé.

    Pas d'alerte quand :
      - `before` est None : première fois que l'entreprise est calculée
        (rien à comparer — une alerte « nouveau » serait du bruit à
        l'amorçage d'un univers) ;
      - `after` est None : plus aucun composite calculable. Une disparition
        de donnée n'est PAS une baisse de risque (règle « donnée manquante ») ;
      - le secteur n'est pas 'other' : les scores sont peu fiables pour les
        banques/assurances/REIT et sont filtrés à l'affichage (AGENTS.md) —
        un e-mail est un affichage ;
      - un niveau sort du vocabulaire attendu (défense contre une ligne
        corrompue : mieux vaut se taire qu'alerter à tort).
    """
    if before is None or after is None:
        return None
    if company.get("sector_group", "other") != "other":
        return None
    if before["severity"] not in LEVELS or after["severity"] not in LEVELS:
        return None
    if before["severity"] == after["severity"]:
        return None

    old, new = before["components"], after["components"]
    # Ordre stable : celui des libellés, puis les inconnus éventuels.
    names = [n for n in SIGNAL_LABELS if n in old or n in new]
    names += sorted((set(old) | set(new)) - set(SIGNAL_LABELS))
    components = tuple(
        (name, old.get(name), new.get(name))
        for name in names
        if old.get(name) != new.get(name)
    )
    return LevelChange(
        cik=company["cik"],
        name=company["name"],
        ticker=company.get("ticker"),
        before=before["severity"],
        after=after["severity"],
        before_period=str(before["period_end"]),
        after_period=str(after["period_end"]),
        components=components,
    )


def _company_title(change: LevelChange) -> str:
    return f"{change.ticker} — {change.name}" if change.ticker else change.name


def build_digest(changes: list[LevelChange], site_url: str) -> tuple[str, str]:
    """(sujet, corps texte) d'UN e-mail regroupant les changements d'un utilisateur.

    Un seul e-mail par utilisateur et par nuit, même s'il suit 10 entreprises
    qui bougent : un flot d'e-mails ferait désactiver les alertes. Hausses
    d'abord (c'est la promesse du produit), puis baisses.
    """
    if not changes:
        raise ValueError("build_digest exige au moins un changement")
    base = site_url.rstrip("/")
    ordered = sorted(changes, key=lambda c: (not c.is_increase, c.name))

    if len(ordered) == 1:
        only = ordered[0]
        direction = "en hausse" if only.is_increase else "en baisse"
        subject = (
            f"Risque {direction} : {only.ticker or only.name} "
            f"({only.before} → {only.after})"
        )
    else:
        subject = f"Risque : {len(ordered)} changements sur votre liste de suivi"

    lines = [
        "Bonjour,",
        "",
        (
            "Le niveau de risque global a changé pour "
            + (
                "une entreprise"
                if len(ordered) == 1
                else f"{len(ordered)} entreprises"
            )
            + " de votre liste de suivi :"
        ),
    ]
    for change in ordered:
        arrow = "▲" if change.is_increase else "▼"
        lines += ["", f"{arrow} {_company_title(change)}"]
        if change.after_period != change.before_period:
            # Nouveau rapport annuel : le niveau porte sur un autre exercice.
            lines.append(
                f"  {change.before} → {change.after} — nouvel exercice clos le "
                f"{change.after_period} (précédent : {change.before_period})"
            )
        else:
            # Même exercice : un événement (8-K, NT, Form 4) l'a fait bouger.
            lines.append(
                f"  {change.before} → {change.after} — exercice clos le "
                f"{change.after_period}"
            )
        if change.components:
            lines.append("  Ce qui a changé :")
            for name, old, new in change.components:
                label = SIGNAL_LABELS.get(name, name)
                lines.append(
                    f"    - {label} : {old or 'non calculé'} → {new or 'non calculé'}"
                )
        lines.append(f"  Détails et dépôts sources : {base}/company/{change.cik}")

    lines += [
        "",
        f"Gérer votre liste de suivi : {base}/watchlist",
        "Pour ne plus recevoir d'alerte sur une entreprise, retirez-la de votre liste.",
        "",
        DISCLAIMER,
    ]
    return subject, "\n".join(lines) + "\n"
