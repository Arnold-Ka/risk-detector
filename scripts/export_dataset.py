"""Exporte le jeu de données deep learning (§6 sem. 7-8) — séries + étiquette.

Lit les faits de toutes les entreprises du manifeste backtest
(`data/backtest/companies.json`), construit les vecteurs annuels
(app/dl/dataset.py) et écrit :

  data/backtest/dl_dataset.csv
    une ligne par (entreprise, exercice) : disponibilité, étiquette
    faillite-à-12-mois, 18 ratios + 18 flags manquant.

Le fichier est gitignoré (régénérable, ≈12k lignes). Le fenêtrage en
séquences de 5 ans est fait à l'entraînement (train_lstm.py) — l'export
reste une table « série d'indicateurs » lisible telle quelle.

Usage : uv run python -m scripts.export_dataset
"""

import csv
import sys
from pathlib import Path

from app.db.repo import get_conn
from app.dl.dataset import FEATURE_CONCEPTS, build_samples, company_year_points
from scripts.backtest import MANIFEST as MANIFEST_PATH, load_manifest

OUT_PATH = Path("data/backtest/dl_dataset.csv")


def load_fact_rows(ciks: list[int]) -> dict[int, list[dict]]:
    """Faits + date de dépôt de chaque fact, groupés par CIK."""
    by_cik: dict[int, list[dict]] = {cik: [] for cik in ciks}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT co.cik, f.period_end, f.concept, f.value, fi.filed_at
                FROM facts f
                JOIN companies co ON co.id = f.company_id
                LEFT JOIN filings fi ON fi.id = f.filing_id
                WHERE co.cik = ANY(%s)
                ORDER BY co.cik, f.period_end
                """,
                (ciks,),
            )
            for cik, period_end, concept, value, filed_at in cur.fetchall():
                by_cik[cik].append(
                    {
                        "period_end": period_end,
                        "concept": concept,
                        "value": value,
                        "filed_at": filed_at,
                    }
                )
    return by_cik


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    anchors, control_ciks = load_manifest(MANIFEST_PATH)
    all_ciks = sorted(set(anchors) | control_ciks)
    print(
        f"Manifeste : {len(all_ciks)} entreprises "
        f"({len(anchors)} faillites, {len(control_ciks)} temoins)"
    )

    by_cik = load_fact_rows(all_ciks)
    rows_out: list[dict] = []
    n_pos = 0
    for cik in all_ciks:
        points = company_year_points(by_cik.get(cik, []))
        if not points:
            print(f"  !! cik={cik} : aucun point annuel exploitable")
            continue
        # anchor absente -> temoin, etiquette toujours 0.
        samples = build_samples(points, cik, anchors.get(cik))
        for s in samples:
            flat: dict = {
                "cik": cik,
                "period_end": s.period_end.isoformat(),
                "availability": s.availability.isoformat(),
                "label": s.label,
            }
            # La séquence du LSTM se reconstruit à l'entraînement ; le CSV
            # stocke la table annuelle = le dernier vecteur de la fenêtre
            # (les 4 précédents sont les lignes des exercices antérieurs).
            vec = s.sequence[-1]
            for i, concept in enumerate(FEATURE_CONCEPTS):
                flat[f"r_{concept}"] = round(vec[2 * i], 6)
                flat[f"m_{concept}"] = int(vec[2 * i + 1])
            rows_out.append(flat)
            n_pos += s.label

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows_out[0].keys())
    with OUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    size_kb = OUT_PATH.stat().st_size // 1024
    print(
        f"Écrit {OUT_PATH} : {len(rows_out)} lignes "
        f"({n_pos} positives = {100 * n_pos / max(len(rows_out), 1):.1f}%), "
        f"{size_kb} Ko"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
