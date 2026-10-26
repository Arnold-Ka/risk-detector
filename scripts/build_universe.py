"""Construit un manifeste candidat de sociétés cotées sur des places US.

Le fichier SEC ticker/exchange est un point de départ, pas une preuve de
cotation active. Chaque candidat est vérifié via submissions : il doit avoir
un rapport annuel 10-K, 20-F ou 40-F récent. Les fonds identifiés sont écartés.

Pilote de 100 CIKs (le client SEC met ses réponses en cache) :
    uv run python -m scripts.build_universe --limit 100 \
      --output data/universe/pilot_000.json

Lots suivants : modifier `--offset` et `--output`. Liste entière :
    uv run python -m scripts.build_universe --limit 0

Pour charger un manifeste, utiliser le pipeline partagé avec
`--manifest data/universe/companies.json`. Ne pas remplacer le manifeste du
backtest : celui-ci garde sa cohorte historique fixe.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.backtest.cohort import make_slug
from app.edgar.client import EdgarClient
from app.edgar.submissions import MAIN_URL
from app.normalize.loader import SUPPORTED_ANNUAL_FORMS

TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
ALLOWED_EXCHANGES = {"nyse", "nyse american", "nasdaq", "cboe", "txse"}
FUND_SICS = {"6722", "6726"}
EXCHANGE_PRIORITY = {
    "nyse": 0,
    "nasdaq": 1,
    "nyse american": 2,
    "cboe": 3,
    "txse": 4,
}


def candidate_rows(payload: dict) -> list[dict]:
    """Fichier SEC ticker/exchange -> sociétés uniques des places retenues."""
    fields = payload.get("fields", [])
    positions = {name: index for index, name in enumerate(fields)}
    required = {"cik", "name", "ticker", "exchange"}
    if not required <= positions.keys():
        raise ValueError("Format SEC company_tickers_exchange inattendu")

    by_cik: dict[int, dict] = {}
    for raw in payload.get("data", []):
        try:
            cik = int(raw[positions["cik"]])
            name = str(raw[positions["name"]]).strip()
            ticker = str(raw[positions["ticker"]]).strip()
            exchange = str(raw[positions["exchange"]] or "").strip()
        except (IndexError, TypeError, ValueError):
            continue
        if not cik or not name or not ticker:
            continue
        exchange_key = exchange.casefold()
        if exchange_key not in ALLOWED_EXCHANGES:
            continue

        row = {"cik": cik, "name": name, "ticker": ticker, "exchange": exchange}
        existing = by_cik.get(cik)
        if existing is None or EXCHANGE_PRIORITY[exchange_key] < EXCHANGE_PRIORITY[
            existing["exchange"].casefold()
        ]:
            by_cik[cik] = row
    return [by_cik[cik] for cik in sorted(by_cik)]


def manifest_entry(candidate: dict, submission: dict, as_of: str) -> dict | None:
    """Ajoute le type de rapport annuel, ou écarte fonds et non-déclarants."""
    sic_value = submission.get("sic")
    sic = str(sic_value).strip() if sic_value not in (None, "") else None
    entity_type = str(submission.get("entityType") or "").strip()
    annual_forms = sorted(
        set(submission.get("filings", {}).get("recent", {}).get("form", []))
        & set(SUPPORTED_ANNUAL_FORMS)
    )

    if entity_type.casefold() in {"investment company", "fund"}:
        return None
    if sic in FUND_SICS or not annual_forms:
        return None

    return {
        **candidate,
        "slug": make_slug(candidate["cik"], candidate["ticker"], candidate["name"]),
        "label": candidate["name"],
        "sic": sic,
        "entity_type": entity_type or None,
        "annual_forms": annual_forms,
        "universe_source": "SEC company_tickers_exchange + recent submissions",
        "universe_as_of": as_of,
    }


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="nombre de CIKs à vérifier ; 0 traite tous les candidats",
    )
    parser.add_argument("--offset", type=int, default=0, help="position de départ dans la liste candidate")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/universe/companies.json"),
        help="chemin du manifeste résultat",
    )
    args = parser.parse_args()
    if args.limit < 0 or args.offset < 0:
        parser.error("--limit et --offset doivent être positifs (0 signifie sans limite)")

    client = EdgarClient()
    payload = json.loads(client.get(TICKERS_EXCHANGE_URL))
    candidates = candidate_rows(payload)
    selected = candidates[args.offset :]
    if args.limit:
        selected = selected[: args.limit]

    as_of = date.today().isoformat()
    entries = []
    errors = 0
    excluded = 0
    for index, candidate in enumerate(selected, 1):
        try:
            submission = json.loads(
                client.get(MAIN_URL.format(cik=candidate["cik"]))
            )
            entry = manifest_entry(candidate, submission, as_of)
        except Exception as exc:
            errors += 1
            print(
                f"  !! {candidate['ticker']} CIK {candidate['cik']}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        if entry is None:
            excluded += 1
        else:
            entries.append(entry)
        if index % 25 == 0:
            print(
                f"[{index}/{len(selected)}] candidats retenus : {len(entries)}",
                flush=True,
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Manifeste écrit : {args.output} — {len(entries)} retenus, "
        f"{excluded} écartés, {errors} erreurs."
    )
    print(
        "La liste SEC sert de point de départ et peut contenir des associations "
        "anciennes ; vérifier la cotation avant de présenter l'univers comme complet."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
