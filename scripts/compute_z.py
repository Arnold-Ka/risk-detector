"""Phase 0 — calcul du Z d'Altman sur les ratios (gate du projet).

    Z = 1,2·A + 1,4·B + 3,3·C + 0,6·D + 1,0·E
    avec A = fonds de roulement / actif,  B = bénéfices non répartis / actif,
        C = EBIT / actif,  D = valeur de marché des capitaux propres /
        dettes book totales,  E = chiffre d'affaires / actif.

Bands d'Altman (article 1968, sociétés industrielles cotées) :
  - Z ≥ 2,99          : zone saine (« safe zone ») ;
  - 1,81 ≤ Z < 2,99   : zone grise (vigilance) ;
  - Z < 1,81          : zone de défaillance (le seuil cité par la feuille
                        de route : « Altman Z < 1.81 = détresse »).
(Débats sur d'autres seuils 2,7 / 1,1 : écartés, la feuille de route et
l'article original utilisent 1,81 ; la colonne zone le rappelle.)

Colonne Z de ratios.csv : remplie ici à la demande du 2026-10-12 (calcul
initialement prévu à la main ; l'utilisateur a délégué le calcul —
l'auditabilité reste : chaque composante est visible en colonne, une
re-faite à la main est un simple 12-opérations par ligne).

Z n'est calculé QUE si les 5 composantes sont présentes (D manquant =>
ligne Z vide : « donnée manquante » > valeur fausse).

Lancement (depuis la racine) :
    uv run python -m scripts.compute_z
"""

import csv
from pathlib import Path

OUT_DIR = Path("data/phase0")
COMPANIES = [
    ("apple_healthy", "Apple (saine)"),
    ("amc_distressed", "AMC (en difficulté)"),
    ("bbby_bankrupt", "Bed Bath & Beyond (faillie)"),
]

# Colonnes de base : [year, A, B, C, E, D, Z] — Z = index 6.
IDX = {"year": 0, "A": 1, "B": 2, "C": 3, "E": 4, "D": 5, "Z": 6}


def zone(z: float) -> str:
    if z < 1.81:
        return "défaillance"
    if z < 2.99:
        return "vigilance"
    return "saine"


def process(slug: str) -> list[list[str]]:
    path = OUT_DIR / f"{slug}_ratios.csv"
    with path.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [list(r) for r in reader]

    # Le script est idempotent : colonne zone en fin de ligne si absente.
    if "zone" not in header:
        header = header + ["zone"]
    zi = header.index("zone")

    for r in rows:
        while len(r) < len(header):
            r.append("")
        try:
            a = float(r[IDX["A"]])
            b = float(r[IDX["B"]])
            c = float(r[IDX["C"]])
            e = float(r[IDX["E"]])
            d = float(r[IDX["D"]])
        except ValueError:
            # Composante manquante (souvent D) : Z vide, pas de valeur fausse.
            r[IDX["Z"]] = ""
            r[zi] = "composante manquante"
            continue
        z = 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e
        r[IDX["Z"]] = f"{z:.3f}"
        r[zi] = zone(z)

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return rows


def main() -> None:
    for slug, label in COMPANIES:
        rows = process(slug)
        print(f"\n=== {label} — Z d'Altman")
        print(f"{'année':>6} {'A':>7} {'B':>7} {'C':>7} {'D':>7} {'E':>7} {'Z':>8}  zone")
        for r in rows:
            # Dernières années + premières : le tableau complet ferait du bruit.
            if r[IDX["year"]] >= str(int(rows[-1][IDX["year"]]) - 4) or r is rows[0]:
                z = r[IDX["Z"]] or "—"
                print(
                    f"{r[IDX['year']]:>6} {r[IDX['A']]:>7} {r[IDX['B']]:>7} "
                    f"{r[IDX['C']]:>7} {r[IDX['D']]:>7} {r[IDX['E']]:>7} "
                    f"{z:>8}  {r[-1]}"
                )
    print(
        # ASCII pour '>' : la console Windows cp1252 ne connaît pas '≥'.
        "\nBands : Z >= 2,99 saine | 1,81-2,99 vigilance | < 1,81 défaillance "
        "(seuil de la feuille de route)."
    )


if __name__ == "__main__":
    main()
