"""Tuning des poids du composite sur les métriques du backtest (§6).

Levier explicitement prévu par la feuille de route : « le poids de chaque
signal sera ajusté grâce au backtest ». Le calcul des niveaux composite
est pur (moyenne pondérée des sévérités, cf. app/signals/composite.py) :
on peut donc RECALCULER les niveaux pour tout vecteur de poids EN MÉMOIRE,
sans réécrire PostgreSQL, puis évaluer détection/FPR avec la même logique
que scripts/backtest.py.

Résultat retenu (2026-10-14, validé produit) :
    critical_8k = 0.5  ->  det 6m 68,0% (cible 60-70%) | FPR/an 14,7%
    (contre 74,2% / 27,2% à poids égaux) — voir WEIGHTS dans composite.py.

Lancement (depuis la racine, DB remplie) :
    uv run python -m scripts.tune_weights
"""

import sys
from datetime import date
from pathlib import Path

from app.backtest.metrics import (
    Snapshot,
    add_months,
    exceeds,
    pick_recent,
)
from app.signals.composite import LEVEL_CRITICAL, SEV_INDEX, WEIGHTS, level_for_index
from scripts.backtest import load_manifest, load_signal_rows

MANIFEST = Path("data/backtest/companies.json")

# Types « financiers » : leurs défaillances décrivent l'état du bilan,
# contrairement aux événements (8-K) qui peuvent toucher une société saine.
FINANCIAL = {"altman", "piotroski", "beneish", "divergence", "runway"}

SWEEP_VALUES = (0.25, 0.5, 2.0, 4.0)


def recompute_snapshots(
    rows_by_cik: dict[int, list[dict]], weights: dict[str, float]
) -> dict[int, list[Snapshot]]:
    """Recalcule les snapshots (niveau + def_types) pour un vecteur de poids.

    Identique à composite.evaluate, mais par (entreprise, exercice) et sans
    objet SignalResult : availability reste celle des données en base
    (max filed_at des composantes) pour rester comparable au rapport.
    """
    out: dict[int, list[Snapshot]] = {}
    for cik, rows_c in rows_by_cik.items():
        by_period: dict[date, dict[str, str]] = {}
        filed: dict[date, list[date]] = {}
        for r in rows_c:
            if r["signal_type"] == "composite":
                continue
            by_period.setdefault(r["period_end"], {})[r["signal_type"]] = r["severity"]
            if r["filed_at"] is not None:
                filed.setdefault(r["period_end"], []).append(r["filed_at"])
        snaps = []
        for pe, sevs in by_period.items():
            usable = {t: s for t, s in sevs.items() if t in weights}
            # Même garde-fou que le produit : pas de composante datée ->
            # pas de snapshot (impossible de dire quand il fut calculable).
            if not usable or pe not in filed:
                continue
            total = sum(weights[t] for t in usable)
            index = sum(weights[t] * SEV_INDEX[s] for t, s in usable.items()) / total
            snaps.append(
                Snapshot(
                    period_end=pe,
                    available_at=max(filed[pe]),
                    level=level_for_index(index),
                    has_defaillance=any(s == "défaillance" for s in sevs.values()),
                    def_types=frozenset(t for t, s in sevs.items() if s == "défaillance"),
                )
            )
        out[cik] = sorted(snaps, key=lambda s: s.period_end)
    return out


def metrics(
    snaps_by_cik: dict[int, list[Snapshot]],
    anchors: dict[int, date],
    controls: set[int],
    rule,
) -> tuple[float, float, float, float]:
    """(det 6m %, det 12m %, FPR/an %, FPR jamais %) pour rule(snap, prev)."""
    det = {6: 0, 12: 0}
    for cik, anchor in anchors.items():
        for h in (6, 12):
            recent = pick_recent(snaps_by_cik.get(cik, []), add_months(anchor, -h), 2)
            if recent:
                snap = recent[0]
                prev = recent[1] if len(recent) > 1 else None
                if rule(snap, prev):
                    det[h] += 1
    hits = total = 0
    ever = n_ever = 0
    for cik in controls:
        snaps = snaps_by_cik.get(cik, [])
        if not snaps:
            continue
        n_ever += 1
        fired = False
        for i, snap in enumerate(snaps):
            prev = snaps[i - 1] if i else None
            total += 1
            if rule(snap, prev):
                hits += 1
                fired = True
        if fired:
            ever += 1
    n = len(anchors)
    fpr = 100 * hits / total if total else 0.0
    return 100 * det[6] / n, 100 * det[12] / n, fpr, 100 * ever / n_ever if n_ever else 0.0


def main() -> None:
    sys.stdout.reconfigure(errors="replace")
    anchors, controls = load_manifest(MANIFEST)
    rows = load_signal_rows(set(anchors) | controls)

    # --- 0. Validation : recompute à poids 1.0 == niveaux stockés en DB ----
    db_levels = {
        (cik, r["period_end"]): r["severity"]
        for cik, rows_c in rows.items()
        for r in rows_c
        if r["signal_type"] == "composite"
    }
    base = recompute_snapshots(rows, dict(WEIGHTS))
    mismatch = sum(
        1
        for cik, snaps in base.items()
        for s in snaps
        if db_levels.get((cik, s.period_end)) != s.level
    )
    print(f"validation recompute vs DB: {mismatch} ecart(s) sur {len(db_levels)} composites")
    print("(ecarts attendus ~0.5% : composantes ajoutees/supprimees depuis le dernier nightly)")

    R_MOD = lambda s, p: exceeds(s, "modéré")
    R_HIGH = lambda s, p: exceeds(s, "élevé")

    # --- 1. Balayage monovariable -------------------------------------------
    for rule, label in ((R_MOD, ">= modere"), (R_HIGH, ">= eleve")):
        print(f"\n--- Balayage poids (autres a 1.0), regle: {label} ---")
        print(f"{'signal':<14} " + " ".join(f"{w:>12}" for w in SWEEP_VALUES))
        for sig in WEIGHTS:
            cells = []
            for w in SWEEP_VALUES:
                vw = dict(WEIGHTS)
                vw[sig] = w
                d6, _, fpr, _ = metrics(recompute_snapshots(rows, vw), anchors, controls, rule)
                cells.append(f"{d6:.0f}/{fpr:.0f}")
            print(f"{sig:<14} " + " ".join(f"{c:>12}" for c in cells))
    print("(cellule = det6%/FPR% ; ligne WEIGHTS actuels = reference)")

    # --- 2. Règles d'alerte alternatives -------------------------------------
    print("\n--- Regles d'alerte (poids actuels) ---")
    for name, rule in (
        ("defaillance (tous types)", lambda s, p: s.has_defaillance),
        ("defaillance (financier seul)", lambda s, p: bool(s.def_types & FINANCIAL)),
        ("modere + defaillance", lambda s, p: exceeds(s, "modéré") and s.has_defaillance),
    ):
        d6, d12, fpr, ev = metrics(base, anchors, controls, rule)
        print(f"  {name:<30} det6 {d6:5.1f} | det12 {d12:5.1f} | FPR {fpr:4.1f} | jamais {ev:4.0f}%")

    # --- 3. Candidat retenu (le seul validé produit a ce jour) ---------------
    print("\n--- Candidat retenu: critical_8k = 0.5, regle >= modere ---")
    vw = dict(WEIGHTS)
    vw["critical_8k"] = 0.5
    d6, d12, fpr, ev = metrics(recompute_snapshots(rows, vw), anchors, controls, R_MOD)
    print(f"  det6 {d6:.1f}% | det12 {d12:.1f}% | FPR/an {fpr:.1f}% | jamais {ev:.0f}%")
    print("  (cf. WEIGHTS commente dans app/signals/composite.py)")


if __name__ == "__main__":
    main()
