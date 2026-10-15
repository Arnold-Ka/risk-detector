"""Backfill Yahoo des cours de bourse (table `prices`) — sans EDGAR.

Pourquoi : le refresh complet (réseau) n'a jamais parcouru la cohorte de
backtest au complet — 121 entreprises ont un ticker mais AUCUN cours en
base (les 505 autres sans ticker = cohorte faillite sans symbole
disponible chez EDGAR : repli flottant voulu). Sans cours, la chaîne de
capitalisation (a) cours × parts dei et (c) cours × parts pondérées ne
peut jamais s'appliquer : le flottant SEC reste la seule source, ce qui
rend le score sensible à ses erreurs d'échelle (cf. garde-fou
_float_is_plausible dans signals/compute).

Ne consomme AUCUN budget SEC (Yahoo uniquement) : utilisable pendant que
des shards Form 4 tiennent EDGAR. Réutilise les moteurs du refresh
(moteur unique) : fetch_history (cache fichier partagé), daily_closes,
splits_after, last_closes_for_balances, fetch_balance_dates,
upsert_prices — idempotent, relançable à volonté.

Usage (nécessite la base via `docker compose up -d --wait`) :
    uv run python -m scripts.backfill_prices
"""

import sys
from pathlib import Path

from app.config import settings
from app.db.repo import fetch_balance_dates, get_conn, upsert_prices
from app.edgar.yahoo import daily_closes, fetch_history, splits_after
from app.ingest.refresh import PRICE_TTL, last_closes_for_balances


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    conn = get_conn()
    n_comp = n_rows = n_nodata = 0
    try:
        # Cibles : ticker présent ET zéro cours en base (les autres sont
        # déjà valorisés — le refresh nocturne les tiendra à jour ensuite).
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.id, c.ticker FROM companies c "
                "WHERE c.ticker IS NOT NULL AND c.ticker <> '' "
                "AND NOT EXISTS (SELECT 1 FROM prices p WHERE p.company_id = c.id) "
                "ORDER BY c.ticker"
            )
            targets = cur.fetchall()
        print(f"{len(targets)} entreprises a valoriser")
        for company_id, ticker in targets:
            symbol = ticker.replace(".", "-")  # BRK.B -> BRK-B (Yahoo)
            try:
                payload = fetch_history(
                    symbol, Path(settings.cache_dir), max_age=PRICE_TTL
                )
                closes = daily_closes(payload)
                if not closes:
                    # Delisté / purgé chez Yahoo (ticker recyclé ou mort) :
                    # rien à écrire, le repli flottant du calcul s'en charge.
                    n_nodata += 1
                    conn.rollback()
                    continue
                splits = splits_after(payload)
                # Dates de bilan = dates de fin de période des faits (la
                # table prices se remplit à la bonne hauteur, comme le
                # refresh nocturne le ferait).
                balance_dates = fetch_balance_dates(conn, company_id)
                rows = last_closes_for_balances(balance_dates, closes, splits)
                n_rows += upsert_prices(conn, company_id, rows)
                conn.commit()  # commit PAR entreprise (reprise possible)
                n_comp += 1
            except Exception as exc:
                conn.rollback()
                print(f"  !! {ticker}: {type(exc).__name__}: {exc}")
    finally:
        conn.close()
    print(
        f"Termine : {n_comp} entreprises valorisees, {n_rows} cours "
        f"inseres ({n_nodata} sans donnees Yahoo — attendu pour les "
        f"titres delistes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
