"""Backtest §6 (semaines 7-8) — détection 6/12 mois + alertes fausses.

Question centrale du gate de la feuille de route : « combien de faillites
sont signalées AU MOINS 6 mois avant l'annonce, avec un taux d'alertes
fausses acceptable sur des entreprises saines ? »

Définitions (décisions de conception, cf. app/backtest/metrics.py) :
  - ancre de faillite = date de dépôt du PREMIER 8-K item 1.03
    (fenêtre 2015-2025, même définition que le signal critical_8k) ;
  - « détecté à l'horizon h » = l'état composite le plus récent qui était
    DÉJÀ DISPONIBLE (dépôt source connu) à (ancre − h mois) déclenche la
    règle testée ; sans aucun état disponible = non détecté (compté au
    dénominateur, honnêteté du gate) ;
  - alertes fausses sur témoins (S&P 500 sains, 2015-2025) : par
    exercice observé ET « jamais » (au moins un dépassement un jour).

Lancement (depuis la racine, après ingestion + nightly) :
    uv run python -m scripts.backtest
"""

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from app.backtest.metrics import (
    add_months,
    build_snapshots,
    exceeds,
    gap_months,
    pick_recent,
)
from app.db.repo import get_conn

MANIFEST = Path("data/backtest/companies.json")

# Règles d'alerte candidates (décision produit = ce tableau). Chaque règle
# voit le snapshot choisi (état à l'horizon) + l'exercice précédent
# disponible (règles de persistance « 2 exercices »). Les définitions
# mixtes naissent de l'analyse des fausses alertes témoins : le niveau
# seul est bruyant (critical_8k 5.02 en vigilance chaque année chez
# ~87% des sains), la composante défaillance seule aussi (Z-score qui
# sanctionne les sociétés de croissance).
RULES: dict[str, object] = {
    "niveau >= modere": lambda s, p: exceeds(s, "modéré"),
    "niveau >= eleve": lambda s, p: exceeds(s, "élevé"),
    "niveau >= critique": lambda s, p: exceeds(s, "critique"),
    "defaillance composante": lambda s, p: exceeds(s, "defaillance"),
    "modere + defaillance": lambda s, p: exceeds(s, "modéré") and s.has_defaillance,
    "eleve ou defaillance": lambda s, p: exceeds(s, "élevé") or s.has_defaillance,
    # Persistance : les DEUX derniers exercices disponibles >= modéré,
    # écart annuel exigé (~16 mois max) — pas de « streak » sans
    # continuité réelle (deux bilans rapprochés ne comptent pas).
    "2 exercices moderes": lambda s, p: (
        p is not None
        and exceeds(s, "modéré")
        and exceeds(p, "modéré")
        and 8 <= gap_months(p, s) <= 16
    ),
}

HORIZONS = [6, 12]


def load_manifest(path: Path) -> tuple[dict[int, date], set[int]]:
    """Manifeste -> ({cik: ancre}, {ciks témoins})."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    anchors: dict[int, date] = {}
    controls: set[int] = set()
    for e in entries:
        cik = int(e["cik"])
        if e["group"] == "cohort":
            anchors[cik] = date.fromisoformat(e["bankruptcy_date"])
        else:
            controls.add(cik)
    return anchors, controls


def load_signal_rows(ciks: set[int]) -> dict[int, list[dict]]:
    """Lignes signaux CLASSIQUES des ciks du manifeste, groupées par cik.

    `<> 'lstm'` : le backtest classique mesure les signaux classiques —
    les lignes DL entreraient dans build_snapshots.def_types (règle
    alternative « défaillance ») et fausseraient la comparaison. Le LSTM
    a sa propre évaluation (scripts/train_lstm, seuil + disponibilité
    dédiés).
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # psycopg3 : ANY(%s) avec une liste Python native (array pg).
            cur.execute(
                """
                SELECT co.cik, s.signal_type, s.period_end, s.severity, f.filed_at
                FROM signals s
                JOIN companies co ON co.id = s.company_id
                LEFT JOIN filings f ON f.id = s.filing_id
                WHERE co.cik = ANY(%s)
                  AND s.signal_type <> 'lstm'
                ORDER BY co.cik, s.period_end
                """,
                [sorted(ciks)],
            )
            rows_by_cik: dict[int, list[dict]] = {}
            for cik, s_type, period_end, severity, filed_at in cur.fetchall():
                rows_by_cik.setdefault(cik, []).append(
                    {
                        "signal_type": s_type,
                        "period_end": period_end,
                        "severity": severity,
                        "filed_at": filed_at,
                    }
                )
            return rows_by_cik
    finally:
        conn.close()


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "—"


def eval_cohort(
    anchors: dict[int, date], snaps_by_cik: dict[int, list]
) -> tuple[dict, dict[int, int], Counter]:
    """Détections par horizon × règle -> ({horizon: {rule: (det, total)}},
    sans_score[horizon], distribution des états à B-6m)."""
    total = len(anchors)
    results: dict[int, dict[str, int]] = {h: dict.fromkeys(RULES, 0) for h in HORIZONS}
    no_score: dict[int, int] = dict.fromkeys(HORIZONS, 0)
    dist: Counter = Counter()

    for cik, anchor in anchors.items():
        snaps = snaps_by_cik.get(cik, [])
        for h in HORIZONS:
            recent = pick_recent(snaps, add_months(anchor, -h), 2)
            if not recent:
                no_score[h] += 1
                if h == 6:
                    dist["sans etat"] += 1
                continue
            snap, prev = recent[0], (recent[1] if len(recent) > 1 else None)
            if h == 6:
                dist[snap.level + ("+def" if snap.has_defaillance else "")] += 1
            for name, rule in RULES.items():
                if rule(snap, prev):
                    results[h][name] += 1
    for h in HORIZONS:
        for name in RULES:
            results[h][name] = (results[h][name], total)
    return results, no_score, dist


def eval_controls(
    control_ciks: set[int], snaps_by_cik: dict[int, list]
) -> tuple[dict[str, tuple[int, int]], int, int]:
    """Alertes fausses par règle -> {rule: (depassements, exercices, ever, ciks)}.

    - par exercice : depassements / tous les snapshots témoins (ce qu'un
      utilisateur verrait année après année) ;
    - jamais : ciks avec >= 1 dépassement / ciks ayant >= 1 snapshot.
    """
    n_snaps_total = 0
    ciks_eval = 0
    ciks_no_snap = 0
    hits: dict[str, int] = dict.fromkeys(RULES, 0)
    ever_ciks: dict[str, int] = dict.fromkeys(RULES, 0)

    for cik in control_ciks:
        snaps = snaps_by_cik.get(cik, [])
        if not snaps:
            ciks_no_snap += 1
            continue
        ciks_eval += 1
        n_snaps_total += len(snaps)
        fired: set[str] = set()
        for i, snap in enumerate(snaps):
            prev = snaps[i - 1] if i else None
            for name, rule in RULES.items():
                if rule(snap, prev):
                    hits[name] += 1
                    fired.add(name)
        for name in fired:
            ever_ciks[name] += 1

    out = {name: (hits[name], n_snaps_total, ever_ciks[name], ciks_eval) for name in RULES}
    return out, n_snaps_total, ciks_no_snap


def main() -> None:
    # Console Windows cp1252 : ne pas planer sur un caractère inconnu.
    sys.stdout.reconfigure(errors="replace")

    anchors, control_ciks = load_manifest(MANIFEST)
    all_ciks = set(anchors) | control_ciks
    rows_by_cik = load_signal_rows(all_ciks)
    snaps_by_cik = {cik: build_snapshots(rows) for cik, rows in rows_by_cik.items()}

    print("=== BACKTEST : detection des faillites (ancre = 1er 8-K item 1.03)")
    print(
        f"cohortes: {len(anchors)} faillites 2015-2025 | "
        f"temoins: {len(control_ciks)} S&P 500 sains | "
        f"sans aucun signaux en base: {len(all_ciks - set(rows_by_cik))}"
    )

    cohort, no_score, dist = eval_cohort(anchors, snaps_by_cik)
    controls, n_ctrl_snaps, ctrl_no_snap = eval_controls(control_ciks, snaps_by_cik)

    print("\n--- Grille de regles (deTECTION: etat connu a l'ancree -h) ---")
    header = f"{'regle':<24} {'det 6m':>9} {'det 12m':>9} {'FPR/annee':>10} {'FPR jamais':>14}  verdict"
    print(header)
    for name in RULES:
        det6, total6 = cohort[6][name]
        det12, _ = cohort[12][name]
        hits, n_snaps, ever, ciks_eval = controls[name]
        fpr_yr = 100.0 * hits / n_snaps if n_snaps else 0.0
        r6 = 100.0 * det6 / total6
        # Cible feuille de route : 60-70% a 6 mois. Seuil FPR « acceptable »
        # discuté au checkpoint : 10% par exercice retenu comme repère.
        verdict = ""
        if 60 <= r6 <= 70 and fpr_yr <= 10.0:
            verdict = "CANDIDAT GATE"
        elif r6 > 70 and fpr_yr <= 10.0:
            verdict = "det haute, FPR OK"
        print(
            f"{name:<24} {pct(det6, total6):>9} {pct(det12, total6):>9} "
            f"{pct(hits, n_snaps):>10} {f'{pct(ever, ciks_eval)} ({ever}/{ciks_eval})':>14}  {verdict}"
        )

    print(f"\nsans etat disponible: {dict(no_score)} (compte non detecte)")
    print("etat B-6m cohort:", dict(dist.most_common()))
    print(f"temoins: {n_ctrl_snaps} exercices observes" + (
        f", {ctrl_no_snap} sans etat" if ctrl_no_snap else ""
    ))


if __name__ == "__main__":
    main()
