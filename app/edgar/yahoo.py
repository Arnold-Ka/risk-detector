"""Cours de bourse Yahoo Finance — source de la colonne D (capitalisation).

API chart v8 (JSON, sans clé, historique long). Sources écartées après
test (cf. scripts/fetch_prices.py) : stooq (challenge JS), Nasdaq (titre
purgé), WSJ (captcha). Yahoo a deux pièges gérés ici :
  - les cours sont AJUSTÉS des splits (Apple 7:1, AMC reverse 1:8) alors
    que les parts XBRL sont brutes → `raw_close` remultiplie par le
    facteur des splits survenus APRÈS la date du cours ;
  - un ticker recyclé (BBBY devenu autre société) renvoie une série
    trèèèès courte récente → traité comme indisponible (repli flottant).

Caché ici pour que le job nocturne (app/jobs/nightly.py) ET le script
batch scripts/fetch_prices.py partagent UNE SEULE implémentation —
règle « un seul moteur » déjà appliquée à l'extraction XBRL.
"""

import json
import time
from pathlib import Path

import httpx

# 1995 : couvre tous les exercices connus (Apple commence en 2007).
PERIOD1 = 788918400  # 1995-01-01T00:00:00Z
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"  # Yahoo exige un UA navigateur


def fetch_history(
    symbol: str,
    cache_dir: Path,
    refresh: bool = False,
    max_age: float | None = None,
) -> dict | None:
    """Historique quotidien complet + splits, avec cache fichier.

    Retourne None si le symbole n'existe plus chez Yahoo (titre delisté
    dont le ticker a été recyclé ou purgé) — pas d'erreur, repli flottant.
    `max_age` : âge max du cache en secondes (None = pérenne) — le job
    nocturne rafraîchit les cours des entreprises suivies sans casser le
    cache long des batchs.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"prices_{symbol}.json"
    if cache_file.exists() and not refresh:
        if max_age is None or (time.time() - cache_file.stat().st_mtime) < max_age:
            return json.loads(cache_file.read_text(encoding="utf-8"))
    try:
        resp = httpx.get(
            CHART_URL.format(symbol=symbol),
            params={
                "period1": PERIOD1,
                "period2": int(time.time()),
                "interval": "1d",
                "events": "split",  # événements de split pour le désajustement
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        print(f"  ! réseau Yahoo, {symbol}: {exc}")
        return None
    if resp.status_code == 404:
        return None  # symbole introuvable / purgé
    if resp.status_code == 429 or resp.status_code >= 500:
        # Rate-limit Yahoo / erreur serveur éphémère sur 800+ symboles :
        # on signale et on passe (« donnée manquante » > faire tomber le lot).
        print(f"  ! Yahoo {resp.status_code} pour {symbol} — prix ignoré")
        return None
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("chart", {}).get("result"):
        return None
    ts = payload["chart"]["result"][0].get("timestamp", [])
    # Symbole recyclé : série très courte commençant récemment = ce n'est
    # plus l'émetteur d'origine (BBBY est devenu une autre société chez
    # Yahoo : 61 points depuis juillet 2026) → traiter comme indisponible.
    if ts and len(ts) < 500 and ts[0] > time.time() - 3 * 365 * 86400:
        return None
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    # Pollicité Yahoo : le SOMMEIL vit ICI (appel réseau réel) et non dans
    # la boucle principale — un cache hit ne doit pas dormir 0,3 s × 875.
    time.sleep(0.3)
    return payload


def daily_closes(payload: dict | None) -> list[tuple[str, float]]:
    """Journalier [(date AAAA-MM-JC, cours ajusté)] — None exclu (jours fermés)."""
    if payload is None:
        return []
    result = payload["chart"]["result"][0]
    ts_list = result.get("timestamp", [])
    closes = result["indicators"]["quote"][0]["close"]
    out = []
    for ts, close in zip(ts_list, closes):
        if close is None:
            continue
        out.append((time.strftime("%Y-%m-%d", time.gmtime(ts)), close))
    return out


def splits_after(payload: dict | None) -> list[tuple[str, float]]:
    """[(date du split, facteur num/dénominateur)] triés croissant.

    Yahoo a déjà divisé les cours antérieurs par ce facteur ; pour
    retrouver le cours BRUT de l'époque, on multiplie le cours ajusté par
    le produit des facteurs des splits survenus APRÈS sa date.
    """
    if payload is None:
        return []
    result = payload["chart"]["result"][0]
    events = result.get("events", {}).get("splits", {}) or {}
    out = []
    for ev in events.values():
        factor = ev["numerator"] / ev["denominator"]
        out.append((time.strftime("%Y-%m-%d", time.gmtime(ev["date"])), factor))
    return sorted(out)


def cached_splits(symbol: str, cache_dir: Path) -> list[tuple[str, float]] | None:
    """Splits depuis le cache fichier des cours — AUCUN réseau.

    Sert au job nocturne pour le signal dilution : comparer les parts
    déclarées à travers un split invente une dilution (mesuré : Apple
    +552 % en 2014 = 7:1, +283 % en 2020 = 4:1). Les facteurs viennent
    du MÊME payload que les cours (cache partagé), donc d'une source
    unique et déjà rafraîchie par fetch_history.

    None = cache absent/inexploitable (entreprise à ticker jamais
    valorisée, purge) : l'appelant traitera « splits non chargés » plutôt
    que « aucun split » — un faux [] affirmerait avoir vérifié.
    """
    cache_file = cache_dir / f"prices_{symbol}.json"
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not payload.get("chart", {}).get("result"):
        return None
    return splits_after(payload)


def raw_close(date: str, adj_close: float, splits: list[tuple[str, float]]) -> float:
    factor = 1.0
    for split_date, ratio in splits:
        if split_date > date:
            factor *= ratio
    return adj_close * factor
