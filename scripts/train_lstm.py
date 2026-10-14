"""LSTM vs scores classiques (§6 sem. 7-8, gate 2) — comparaison honnête.

Même question que le backtest classique, mais pour le modèle séquentiel :
« combien de faillites le LSTM aurait-il signalées 6 et 12 mois avant,
et combien d'alertes fausses sur les témoins ? » — sur la MÊME fenêtre
de test que les scores classiques, pour que la comparaison soit loyale.

Décisions d'évaluation (reprises de scripts/backtest.py quand applicable) :
  - split TEMPOREL (pas de fuite d'avenir) : train <= 2018, val 2019-2021,
    test >= 2022 — le test ne voit jamais les années d'entraînement ;
  - étiquette = faillite <= 12 mois (horizon de la feuille de route) ;
  - seuil de probabilité calé sur les TÉMOINS de validation au
    décile 90 (~10 % FPR cible, même repère que le gate classique) ;
  - évaluation « état à l'instant T » : dernier échantillon dont la
    disponibilité (max filed_at de la fenêtre) <= ancre − h, identique
    à pick_recent() pour le composite — le LSTM ne triche pas sur les
    dépôts tardifs non plus ;
  - classique de comparaison = règle produit retenue : niveau >= modéré.

Usage : uv run python -m scripts.train_lstm
"""

import math
import sys
from datetime import date

from app.backtest.metrics import add_months, build_snapshots, exceeds, pick_recent
from app.dl.dataset import INPUT_DIM, Sample, build_samples, company_year_points
from app.dl.model import auc_rank, predict, train_model
from scripts.backtest import MANIFEST, load_manifest, load_signal_rows
from scripts.export_dataset import load_fact_rows

TEST_START = 2022  # premier exercice du split de test
VAL_START = 2019  # bornes du split de validation
HORIZONS = [6, 12]
RULE = "modéré"  # règle classique de référence (décision produit backtest)


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "—"


def quantile(values: list[float], q: float) -> float:
    """Quantile par interpolation simple (numpy-like, sans dépendance)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = q * (len(ordered) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def eval_lstm_detection(
    samples_by_cik: dict[int, list[Sample]],
    anchors: dict[int, date],
    threshold: float,
    model,
    test_start_year: int,
) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    """Detection LSTM (test) -> ({h: (det, total)} cohort, {h: (hits, obs)} temoins).

    Cohort : pour chaque ancre de TEST (meme sous-ensemble que le
    classique), dernier echantillon DISPONIBLE a l'ancree -h (meme
    discipline que pick_recent) -> proba >= seuil.
    Temoins : tous les echantillons de test (probabilite >= seuil).
    Pas d'echantillon disponible = non detecte (compte au denominateur).
    """
    det = {h: 0 for h in HORIZONS}
    total = sum(1 for a in anchors.values() if a.year >= test_start_year)
    no_state = {h: 0 for h in HORIZONS}
    hits = {h: 0 for h in HORIZONS}
    obs = {h: 0 for h in HORIZONS}

    # Pre-calcul des probas par entreprise (une passe, mini-batches inclus).
    probs_by_cik: dict[int, list[float]] = {}
    for cik, samples in samples_by_cik.items():
        if samples:
            probs_by_cik[cik] = predict(model, samples)

    for cik, anchor in anchors.items():
        if anchor.year < test_start_year:
            continue  # meme sous-ensemble de test que le classique
        samples = samples_by_cik.get(cik, [])
        probs = probs_by_cik.get(cik, [])
        for h in HORIZONS:
            cutoff = add_months(anchor, -h)
            # Dernier echantillon (period_end max) deja disponible au cutoff.
            candidates = [
                (s.period_end, p)
                for s, p in zip(samples, probs)
                if s.availability <= cutoff and s.period_end <= anchor
            ]
            if not candidates:
                no_state[h] += 1
                continue
            _, best_prob = max(candidates, key=lambda t: t[0])
            if best_prob >= threshold:
                det[h] += 1

    for cik, samples in samples_by_cik.items():
        if cik not in probs_by_cik:
            continue
        for s, p in zip(samples, probs_by_cik[cik]):
            if s.period_end.year < test_start_year:
                continue
            for h in HORIZONS:
                obs[h] += 1
                if p >= threshold:
                    hits[h] += 1

    return (
        ({h: (det[h], total) for h in HORIZONS}, {h: (hits[h], obs[h]) for h in HORIZONS}),
        no_state,
    )


def eval_classic_test(
    snaps_by_cik: dict[int, list],
    anchors: dict[int, date],
    control_ciks: set[int],
    test_start_year: int,
) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    """Classique >= modere sur le MEME sous-ensemble de test."""
    test_anchors = {c: a for c, a in anchors.items() if a.year >= test_start_year}
    det = {h: 0 for h in HORIZONS}
    total = len(test_anchors)
    hits = {h: 0 for h in HORIZONS}
    obs = {h: 0 for h in HORIZONS}

    for _cik, anchor in test_anchors.items():
        snaps = snaps_by_cik.get(_cik, [])
        for h in HORIZONS:
            recent = pick_recent(snaps, add_months(anchor, -h), 1)
            if recent and exceeds(recent[0], RULE):
                det[h] += 1

    for cik in control_ciks:
        for snap in snaps_by_cik.get(cik, []):
            if snap.period_end.year < test_start_year:
                continue
            for h in HORIZONS:
                obs[h] += 1
                if exceeds(snap, RULE):
                    hits[h] += 1

    return {h: (det[h], total) for h in HORIZONS}, {h: (hits[h], obs[h]) for h in HORIZONS}


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    anchors, control_ciks = load_manifest(MANIFEST)
    all_ciks = sorted(set(anchors) | control_ciks)

    # 1) Echantillons depuis les faits (meme builder que l'export CSV).
    by_cik = load_fact_rows(all_ciks)
    samples_by_cik: dict[int, list[Sample]] = {}
    for cik in all_ciks:
        points = company_year_points(by_cik.get(cik, []))
        samples_by_cik[cik] = build_samples(points, cik, anchors.get(cik))

    all_samples = [s for samples in samples_by_cik.values() for s in samples]
    train = [s for s in all_samples if s.period_end.year <= VAL_START - 1]
    val = [s for s in all_samples if VAL_START <= s.period_end.year < TEST_START]
    test = [s for s in all_samples if s.period_end.year >= TEST_START]
    print(
        f"Dataset : {len(all_samples)} echantillons "
        f"(train {len(train)} <= 2018 | val {len(val)} 2019-21 | test {len(test)} >= 2022)"
    )
    print(
        f"Positifs : train {sum(s.label for s in train)} | "
        f"val {sum(s.label for s in val)} | test {sum(s.label for s in test)}"
    )

    # 2) Entrainage (early stopping sur AUC de validation).
    model, val_auc = train_model(train, val, INPUT_DIM)
    test_scores = predict(model, test)
    test_auc = auc_rank([s.label for s in test], test_scores)

    # 3) Seuil sur les temoins de validation (decile 90 ~ 10% FPR cible).
    val_ctrl_probs = [
        p
        for s, p in zip(val, predict(model, val))
        if s.label == 0
    ]
    threshold = quantile(val_ctrl_probs, 0.90)

    # 4) Metriques echantillon (discrimination brute sur le test).
    tp = sum(1 for s, p in zip(test, test_scores) if s.label == 1 and p >= threshold)
    n_pos_test = sum(s.label for s in test)
    fp = sum(1 for s, p in zip(test, test_scores) if s.label == 0 and p >= threshold)
    n_neg_test = len(test) - n_pos_test
    print(f"\nLSTM : AUC val {val_auc:.3f} | AUC test {test_auc:.3f} | seuil {threshold:.3f}")
    print(
        f"Sur le test (par exercice) : rappel positifs {pct(tp, n_pos_test)} | "
        f"FPR {pct(fp, n_neg_test)}"
    )

    # 5) Comparaison honnete : detection 6/12m (etat a l'instant T).
    (lstm_det, lstm_ctrl), no_state = eval_lstm_detection(
        samples_by_cik, anchors, threshold, model, TEST_START
    )
    snaps_by_cik = {
        cik: build_snapshots(rows)
        for cik, rows in load_signal_rows(set(all_ciks)).items()
    }
    classic_det, classic_ctrl = eval_classic_test(
        snaps_by_cik, anchors, control_ciks, TEST_START
    )

    print(f"\n--- Detection a l'ancree -h | test >= {TEST_START} (hors echantillon) ---")
    print(
        f"{'modele':<10} {'det 6m':>9} {'det 12m':>9} {'FPR/annee':>10}  (temoins test)"
    )
    for name, det, ctrl in (
        (f"classique", classic_det, classic_ctrl),
        ("LSTM", lstm_det, lstm_ctrl),
    ):
        d6, t6 = det[6]
        d12, t12 = det[12]
        h6, o6 = ctrl[6]
        print(
            f"{name:<10} {pct(d6, t6):>9} {pct(d12, t12):>9} "
            f"{pct(h6, o6):>10}  ({t6} faillites, {o6} ex. temoins)"
        )
    print(f"sans etat LSTM (non detecte) : {dict(no_state)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
