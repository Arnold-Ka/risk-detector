"""Santé des DONNÉES (et non du processus) — règles pures, sans base ni réseau.

Constat d'origine (AGENTS.md) : le nightly journalise les échecs par
entreprise et termine toujours en succès, et `/health` n'interroge pas
PostgreSQL. Une Action verte ou un `/health` OK ne prouvaient donc rien sur
la fraîcheur des scores — or les alertes e-mail calculées sur des données
périmées détruiraient la confiance dans l'outil.

Deux contrôles, utilisés par deux appelants :
  - `run_problems` : le nightly échoue (code de sortie 1, Action rouge) si
    trop d'entreprises ont échoué ;
  - `freshness` : `/health/data` répond 503 si les signaux en base datent de
    plus d'un jour.

Seuils choisis pour ne PAS sonner chaque nuit sur le bruit normal :
  - les erreurs de cours Yahoo sont fréquentes et attendues (la cohorte du
    backtest compte 547 faillites, souvent radiées de la cote) : elles
    restent informatives et n'entrent pas dans ces règles ;
  - un échec de la page « recent » de la SEC touche toutes les entreprises
    à la fois quand il est systémique (User-Agent refusé, réseau coupé) :
    plus de la moitié = panne, pas un cas isolé ;
  - une erreur de CALCUL annule l'entreprise entière (rollback) : au-delà
    de 20 %, la base n'est plus représentative.
"""

from datetime import date

MAX_COMPUTE_ERROR_RATIO = 0.2
MAX_SEC_ERROR_RATIO = 0.5
# Le nightly tourne chaque jour à 05:30 UTC : la veille est normale, deux
# jours = au moins une nuit manquée.
MAX_SIGNAL_AGE_DAYS = 1


def run_problems(total: int, compute_errors: int, sec_errors: int) -> list[str]:
    """Problèmes bloquants d'une exécution du nightly ([] = exécution saine)."""
    if total == 0:
        # Base vide ou --limit 0 : rien n'a été recalculé, ce n'est pas un
        # succès silencieux.
        return ["aucune entreprise traitée"]
    problems = []
    if compute_errors / total > MAX_COMPUTE_ERROR_RATIO:
        problems.append(
            f"{compute_errors}/{total} entreprises en erreur de calcul "
            f"(seuil {MAX_COMPUTE_ERROR_RATIO:.0%})"
        )
    if sec_errors / total > MAX_SEC_ERROR_RATIO:
        problems.append(
            f"{sec_errors}/{total} échecs SEC sur les dépôts récents "
            f"(seuil {MAX_SEC_ERROR_RATIO:.0%}) — User-Agent refusé ou réseau ?"
        )
    return problems


def freshness(
    last_computed: date | None,
    today: date,
    max_age_days: int = MAX_SIGNAL_AGE_DAYS,
) -> dict:
    """Statut de fraîcheur des signaux : 'ok', 'stale' (périmés) ou 'empty'."""
    if last_computed is None:
        return {"status": "empty", "last_computed_at": None, "age_days": None}
    age = (today - last_computed).days
    return {
        "status": "ok" if age <= max_age_days else "stale",
        "last_computed_at": last_computed.isoformat(),
        "age_days": age,
    }
