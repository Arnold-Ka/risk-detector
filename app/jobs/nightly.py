"""Job batch nocturne — le cœur de la précalculation du produit.

Principe de la feuille de route : « pré-calculer la nuit plutôt que de
calculer à la demande ». L'API ne fait que LIRE les signaux ; ce job est le
seul écrivain.

Pipeline prévu (phase 1) :
    1. fetch      — télécharger les nouvelles données EDGAR (archives
                    companyfacts/submissions massives + 8-K et Form 4
                    incrémentaux) via app.edgar.client
    2. normalize  — mapper les tags XBRL hétérogènes vers des indicateurs
                    standard (app/normalize/, piloté par xbrl_map.yaml)
    3. signals    — exécuter les calculateurs et détecteurs d'événements
                    app/signals/*, stocker chaque résultat avec sa date et
                    son dépôt source (traçabilité)

Invocation (depuis la racine du projet, pour que `app` soit importable) :
    uv run python -m app.jobs.nightly
Le drapeau `-m` est important : il ajoute le répertoire courant au
sys.path ; lancer `python app/jobs/nightly.py` directement échouerait sur
les imports `app.*`.

Planification : manuel en dev ; `cron` sur le VPS en production (choix de
planificateur selon la feuille de route §4 — cron d'abord, RQ/Celery
seulement en phase 2+).
"""


def main():
    # TODO(phase 1) : remplacer par le pipeline fetch -> normalize -> signals.
    print("nightly: fetch -> normalize -> signals (TODO phase 1)")


if __name__ == "__main__":
    # Active `python -m app.jobs.nightly` ; évite que main() s'exécute quand
    # ce fichier est simplement importé par un autre module ou un test.
    main()
