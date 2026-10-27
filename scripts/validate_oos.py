"""Validation HORS ÉCHANTILLON des poids du composite (lecture seule).

Problème : les poids de production (app/signals/composite.WEIGHTS) ont été
ajustés sur toute la cohorte, puis les taux publiés (README, page
/methodology) ont été mesurés sur cette même cohorte. Ces taux sont donc
« dans l'échantillon » : probablement un peu optimistes.

Test temporel, comme si l'on avait réglé l'outil fin 2020 :
  1. APPRENTISSAGE — faillites dont l'ancre (8-K 1.03) est <= 2020 et
     exercices témoins clos <= 2020 : on cherche les poids qui maximisent
     « détection 6 mois − fausses alertes par an » (descente coordonnée sur
     une grille, même recalcul en mémoire que scripts/tune_weights) ;
  2. TEST — faillites 2021-2025 et exercices témoins clos >= 2021, jamais
     vus pendant l'apprentissage : on mesure les poids figés de l'étape 1 ;
  3. RÉFÉRENCES sur la même période de test : poids égaux (1.0) et poids
     de production. Si les poids appris jusqu'en 2020 font aussi bien que
     ceux de production, le réglage n'a pas surappris.

Rien n'est écrit en base ; WEIGHTS n'est pas modifié. Changer les poids de
production reste une décision séparée (balayage complet, cf. AGENTS.md).

Lancement (depuis la racine, DB remplie) :
    uv run python -m scripts.validate_oos
"""

import sys
from datetime import date
from pathlib import Path

from app.backtest.metrics import Snapshot, exceeds
from app.signals.composite import WEIGHTS
from scripts.backtest import load_manifest, load_signal_rows
from scripts.tune_weights import metrics, recompute_snapshots

MANIFEST = Path("data/backtest/companies.json")
SPLIT_YEAR = 2020  # dernière année vue par l'apprentissage
GRID = (0.25, 0.5, 1.0, 1.5, 2.0)
PASSES = 2  # passes de descente coordonnée (la 2e corrige les interactions)


def split_anchors(
    anchors: dict[int, date], split_year: int
) -> tuple[dict[int, date], dict[int, date]]:
    """Faillites -> (apprentissage : ancre <= split_year, test : après)."""
    train = {cik: a for cik, a in anchors.items() if a.year <= split_year}
    test = {cik: a for cik, a in anchors.items() if a.year > split_year}
    return train, test


def window_controls(
    snaps_by_cik: dict[int, list[Snapshot]],
    controls: set[int],
    keep,
) -> dict[int, list[Snapshot]]:
    """Copie des snapshots où ceux des TÉMOINS sont filtrés par `keep(period_end)`.

    Les snapshots des faillites restent complets : pick_recent ne regarde de
    toute façon que ceux disponibles avant l'ancre.
    """
    return {
        cik: (
            [s for s in snaps if keep(s.period_end)] if cik in controls else snaps
        )
        for cik, snaps in snaps_by_cik.items()
    }


def objective(det6: float, fpr: float) -> float:
    """Critère de sélection : détection à 6 mois moins fausses alertes/an."""
    return det6 - fpr


def main() -> None:
    sys.stdout.reconfigure(errors="replace")
    anchors, controls = load_manifest(MANIFEST)
    rows = load_signal_rows(set(anchors) | controls)
    train_anchors, test_anchors = split_anchors(anchors, SPLIT_YEAR)

    def is_train(pe: date) -> bool:
        return pe.year <= SPLIT_YEAR

    def is_test(pe: date) -> bool:
        return pe.year > SPLIT_YEAR

    rule = lambda s, p: exceeds(s, "modéré")

    def evaluate(weights: dict[str, float], period: str):
        snaps = recompute_snapshots(rows, weights)
        if period == "train":
            return metrics(window_controls(snaps, controls, is_train),
                           train_anchors, controls, rule)
        return metrics(window_controls(snaps, controls, is_test),
                       test_anchors, controls, rule)

    print(
        f"Apprentissage : {len(train_anchors)} faillites <= {SPLIT_YEAR} | "
        f"Test : {len(test_anchors)} faillites > {SPLIT_YEAR} | "
        f"témoins : {len(controls)} (exercices découpés à la même date)"
    )

    # --- 1. Descente coordonnée sur la période d'apprentissage --------------
    learned = dict.fromkeys(WEIGHTS, 1.0)
    d6, _, fpr, _ = evaluate(learned, "train")
    best = objective(d6, fpr)
    for n_pass in range(1, PASSES + 1):
        for signal in WEIGHTS:
            for value in GRID:
                if value == learned[signal]:
                    continue
                candidate = {**learned, signal: value}
                d6, _, fpr, _ = evaluate(candidate, "train")
                if objective(d6, fpr) > best:
                    best, learned = objective(d6, fpr), candidate
        print(f"  passe {n_pass} : objectif apprentissage {best:.1f}")

    print("\nPoids appris sur <= 2020 (production entre parenthèses) :")
    for signal in WEIGHTS:
        print(f"  {signal:<16} {learned[signal]:>5}  ({WEIGHTS[signal]})")

    # --- 2. Mesures ----------------------------------------------------------
    print(f"\n{'poids':<34} {'période':<10} {'det 6m':>7} {'det 12m':>8} "
          f"{'FPR/an':>7} {'jamais':>7}")
    for label, weights in (
        ("égaux (1.0)", dict.fromkeys(WEIGHTS, 1.0)),
        ("appris sur <= 2020", learned),
        ("production (vus sur tout)", dict(WEIGHTS)),
    ):
        for period in ("train", "test"):
            d6, d12, fpr, ever = evaluate(weights, period)
            name = "<= 2020" if period == "train" else "2021+"
            print(f"{label:<34} {name:<10} {d6:6.1f}% {d12:7.1f}% "
                  f"{fpr:6.1f}% {ever:6.1f}%")
    print(
        "\nLecture : la ligne « appris sur <= 2020 / 2021+ » est la mesure "
        "honnête (poids réglés sans voir la période de test). « jamais » = "
        "part des témoins alertés au moins une fois DANS la période."
    )


if __name__ == "__main__":
    main()
