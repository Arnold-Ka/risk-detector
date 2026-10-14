"""Telechargement + parsing des Form 4 (transactions des dirigeants).

Chaque Form 4 = 1 GET du XML brut (cache EdgarClient, 10 req/s) parse en
transactions (app/edgar/form4.py) ecrites en JSONL :
    data/cache/form4/{cik}.jsonl   (une ligne par transaction x owner)

Reprise-native : le cache EDGAR saute les URLs deja vues ; un CIK deja
ecrit (fichier jsonl present) est saute sauf --force. Un plantage au
milieu d'un CIK ne perd que ce CIK (ecriture atomique tmp -> rename).

Le lot complet (~720k XML, ≈3.7 j en processus unique — la latence
EDGAR ~440 ms/req est le goulot, pas le rate-limit — donc ~1.2 j en
3 shards ≈6.75 req/s agregees) se lance depuis la racine :
    uv run python -m scripts.fetch_form4 --shard 0 --shards 3
    (x3 fenetres / proces, index 0, 1, 2)
Pilote rapide (validation) :
    uv run python -m scripts.fetch_form4 --limit 3 --force
"""

import argparse
import json
import sys
import time
from pathlib import Path

from app.edgar.client import EdgarClient
from app.edgar.form4 import parse_form4, raw_doc_url
from app.edgar.submissions import load_filing_rows
from scripts.backtest import MANIFEST, load_manifest

OUT_DIR = Path("data/cache/form4")
# Trio phase 0 : AMC n'est pas dans le manifeste (ni temoin S&P ni
# faillite FTS) mais le signal insiders se developpe dessus.
TRIO = (320193, 1411579, 886158)


def fetch_company(client: EdgarClient, cik: int, limit: int | None) -> tuple[int, int]:
    """Telecharge+parse tous les Form 4 (form == "4" exact) d'un CIK.

    Retourne (nb transactions ecrites, nb d'echecs de parsing/HTTP).
    `form == "4"` exact exclut deja les amendements 4/A (doublons).
    """
    rows = load_filing_rows(client, cik)
    form4s = [r for r in rows if r["form"] == "4"]
    if limit is not None:
        form4s = form4s[:limit]

    transactions: list[dict] = []
    errors = 0
    for row in form4s:
        url = raw_doc_url(cik, row["accession"], row.get("primary_doc", ""))
        if url is None:
            continue  # depots pre-2003 en .htm : hors perimetre v1
        try:
            transactions.extend(parse_form4(client.get(url), row))
        except Exception:
            # XML casse / 404 inattendu : on compte et on passe — un
            # fichier illisible ne doit pas arreter 20 h de lot.
            errors += 1

    if transactions or not form4s:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"{cik}.jsonl"
        tmp = out.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for tx in transactions:
                fh.write(json.dumps(tx, ensure_ascii=False, default=str) + "\n")
        tmp.replace(out)
    return len(transactions), errors


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="max Form 4 par CIK (pilote)")
    parser.add_argument("--force", action="store_true",
                        help="refaire les CIK memes si leur jsonl existe")
    parser.add_argument("--shard", type=int, default=0,
                        help="index de la tranche (0..shards-1) pour le parallelisme")
    parser.add_argument("--shards", type=int, default=1,
                        help="nb de tranches simultanees (3 ≈ 6.75 req/s agregees, "
                             "sous la limite 10/s de la SEC — la latence EDGAR, "
                             "pas le rate-limit, est le vrai goulot)")
    args = parser.parse_args()
    if not 0 <= args.shard < args.shards:
        parser.error("--shard doit être dans [0, --shards)")

    anchors, controls = load_manifest(MANIFEST)
    ciks = sorted(set(anchors) | controls | set(TRIO))
    # Tranches disjointes : ciks[i], ciks[i+n], ciks[i+2n]… Chaque shard
    # a son propre EdgarClient (son propre cadran 10 req/s) ; 3 shards
    # restent ≈6.75 req/s en aggregate, sous la limite SEC.
    ciks = ciks[args.shard :: args.shards]

    client = EdgarClient()
    started = time.monotonic()
    done_tx = done_err = done_ciks = skipped = 0
    for i, cik in enumerate(ciks, 1):
        out = OUT_DIR / f"{cik}.jsonl"
        if out.exists() and not args.force:
            skipped += 1
            continue
        try:
            n_tx, n_err = fetch_company(client, cik, args.limit)
        except Exception as exc:
            print(f"  !! cik={cik}: {type(exc).__name__}: {exc}")
            continue
        done_tx += n_tx
        done_err += n_err
        done_ciks += 1
        if i % 25 == 0:
            elapsed = time.monotonic() - started
            print(
                f"[shard {args.shard}] [{i}/{len(ciks)}] ciks faits: {done_ciks} | "
                f"transactions: {done_tx} | echecs: {done_err} | {elapsed/60:.1f} min",
                flush=True,  # buffer python pipe sinon retient l'affichage
            )

    elapsed = time.monotonic() - started
    print(
        f"Termine: {done_ciks} CIKs telecharges ({skipped} deja presents), "
        f"{done_tx} transactions, {done_err} echecs, {elapsed/60:.1f} min"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
