"""Orchestration : série d'indicateurs normalisés -> signaux d'une entreprise.

Ce module est le seul à savoir COMMENT les modules `app.signals.*` sont
appelés sur une série d'exercices. Il est pur (aucune BDD, aucun réseau) :
le job nocturne lui passe des lignes de la table `facts`, les tests lui
passent directement la sortie de `app.normalize.loader.extract`.

Entrées :
  rows   : [{concept, value, period_end, fiscal_year?, filing_id?}] —
           les lignes de `facts` (ou du chargeur) ;
  prices : [(date ISO, cours)] — table `prices` (les cours retenus pour D).

Réglages de valorisation : la logique de capitalisation reproduit À L'IDENTIQUE
scripts/fetch_prices.py (source_D) pour que Z(phase 0) et Z(nightly) disent
la même chose :
  a) cours ≤ date de bilan (à 14 j près — c'est la « date_valeur » stockée)
     × parts de couverture (dei) ;
   b) sinon dernier flottant SEC ≤ date de bilan (dans les 12 mois),
      écarté s'il est hors d'échelle face aux autres flottants de
      l'entreprise (erreur de facteur 1000 ou flottant à 0 — cf.
      _float_is_plausible) ;
  c) sinon cours × parts pondérées moyennes ;
  d) sinon capitalisation absente -> Altman non calculable (None).

Convention d'année : année CALENDAIRE de la date de fin de période
(identique à la colonne `year` de la phase 0 et à facts.fiscal_year) ;
plusieurs dates de fin dans une même année (AMC 2018) => la date la plus
tardive gagne (tri croissant + écrasement), exactement comme la phase 0.
"""

import statistics
from datetime import date

from app.signals import (
    altman,
    beneish,
    composite,
    divergence,
    insiders,
    piotroski,
    runway,
)
from app.signals.common import SignalResult
from app.signals.events import (
    assign_to_years,
    evaluate_critical_8k,
    evaluate_late_filing,
)
from app.signals.insiders import is_open_sale

# Cours utilisable s'il est à moins de 14 jours du bilan (week-end/férié
# derrière : la date_valeur de fetch_prices est le dernier cours ≤ bilan).
PRICE_MAX_AGE_DAYS = 14
# Flottant SEC utilisable s'il date de moins de 12 mois (mesuré ~6 mois
# avant le bilan pour un exercice civil ; ~0 mois pour décalé).
FLOAT_MAX_AGE_DAYS = 365
# Un flottant déclaré n'est retenu que s'il reste dans un facteur 100 de
# la médiane des autres déclarations de l'entreprise (voir
# _float_is_plausible) : au-delà, c'est une erreur d'échelle du
# télédéclarant, pas un marché qui s'effondre.
FLOAT_MAGNITUDE_TOL = 100.0


def build_years(rows: list[dict]) -> dict[int, dict[str, dict]]:
    """Lignes de faits -> {année: {concept: node}}, date la plus tardive gagne."""
    years: dict[int, dict[str, dict]] = {}
    for row in sorted(rows, key=lambda r: r["period_end"]):
        year = int(row["period_end"][:4])
        node = {
            "value": row["value"],
            "period_end": row["period_end"],
            # facts.filing_id (uuid) côté BDD ; les tests passent l'accn.
            "filing_id": row.get("filing_id") or row.get("accn"),
        }
        years.setdefault(year, {})[row["concept"]] = node
    return years


def _v(year_node: dict, concept: str):
    """Valeur d'un concept pour l'exercice, ou None si absent."""
    node = year_node.get(concept)
    return node["value"] if node else None


def _meta(year_node: dict) -> tuple[str | None, str | None]:
    """Ancre (period_end, filing_id) de l'exercice.

    Préférence : le bilan (total_assets) ; sinon le résultat, la trésorerie
    ou le CA — un exercice sans aucun de ces postes n'a pas de signal du
    tout (le parcours de compute_company saute l'année).
    """
    for anchor in ("total_assets", "net_income", "cash", "sales"):
        node = year_node.get(anchor)
        if node:
            return node["period_end"], node.get("filing_id")
    return None, None


def _price_on_or_before(prices: list[tuple[str, float]], balance_date: str) -> float | None:
    """Dernier cours ≤ date de bilan et d'au plus PRICE_MAX_AGE_DAYS jours.

    La table `prices` ne contient que les cours retenus par fetch_prices
    (une ligne par exercice valorisé) : pour un exercice passé par le repli
    « flottant_sec », aucun cours n'est stocké — on retombe donc
    naturellement sur l'étape (b), comme le script de phase 0.
    """
    bd = date.fromisoformat(balance_date)
    best: float | None = None
    for d, close in prices:
        dd = date.fromisoformat(d)
        if dd > bd:
            break  # tri croissant : plus rien d'utilisable ensuite
        if (bd - dd).days <= PRICE_MAX_AGE_DAYS:
            best = close
    return best


def _float_is_plausible(value: float, others: list[float]) -> bool:
    """Le flottant déclaré est-il du bon ordre de grandeur ?

    Erreurs mesurées dans la base avant ce garde-fou :
      - NDSN 2018 : public_float = 7 441 507 $ (7,4 M$ au lieu de 7,4
        Md$ — le télédéclarant a oublié le facteur 1000), ADI 2012
        pareil (9 664 000 au lieu de 9,7 Md$) ;
      - des flottants à 0 (LITE, CEPL…) donnaient D = 0 dans l'Altman :
        76 signaux en fausse « défaillance » mesurés.

    Un vrai flottant ne s'écarte pas d'un facteur 100 de la médiane des
    autres déclarations de la MÊME entreprise — une erreur d'échelle, si
    (facteur 1000 typique, ou 0). Le candidat écarté laisse parler la
    chaîne de repli (cours × parts pondérées) ou l'absence de
    capitalisation : règle produit « donnée manquante > faux score ».

    Pas de comparaison (autres valeurs absentes ou nulles) => on ne peut
    pas juger : un positif unique est accepté tel quel.
    """
    if value <= 0:
        return False
    positives = [v for v in others if v > 0]
    if not positives:
        return True
    median = statistics.median(positives)
    ratio = value / median
    return 1 / FLOAT_MAGNITUDE_TOL <= ratio <= FLOAT_MAGNITUDE_TOL


def _latest_float(floats: list[tuple[str, float]], balance_date: str) -> float | None:
    """Dernier flottant SEC ≤ date de bilan, d'au plus 12 mois.

    Le candidat retenu doit passer _float_is_plausible face aux autres
    flottants de l'entreprise (toutes années, futur compris : c'est un
    contrôle d'échelle de la DÉCLARATION, pas une info financière — seul
    le montant candidat, lui, reste cantonné ≤ date de bilan).
    """
    bd = date.fromisoformat(balance_date)
    best: float | None = None
    best_idx = -1
    for i, (d, value) in enumerate(floats):
        dd = date.fromisoformat(d)
        if dd > bd:
            break
        if (bd - dd).days <= FLOAT_MAX_AGE_DAYS:
            best = value
            best_idx = i
    if best is None:
        return None
    others = [v for i, (_d, v) in enumerate(floats) if i != best_idx]
    if not _float_is_plausible(best, others):
        return None
    return best


def market_capitalisation(
    cur: dict,
    floats: list[tuple[str, float]],
    prices: list[tuple[str, float]],
) -> tuple[float | None, str | None]:
    """(capitalisation, source) pour l'exercice — miroir de fetch_prices.

    Retourne (None, None) quand aucune source ne s'applique : Altman sera
    alors non calculable, jamais valorisé avec un chiffre inventé.
    """
    ta = cur.get("total_assets")
    if not ta:
        return None, None
    balance_date = ta["period_end"]

    price = _price_on_or_before(prices, balance_date)
    dei = _v(cur, "shares_outstanding")
    wavg = _v(cur, "shares_weighted_basic")

    if price and dei:
        return price * dei, "yahoo+dei"
    flottant = _latest_float(floats, balance_date)
    if flottant is not None:
        return flottant, "flottant_sec"
    if price and wavg:
        return price * wavg, "yahoo+parts_ponderees"
    return None, None


def compute_company(
    rows: list[dict],
    prices: list[tuple[str, float]],
    events: list[dict] | None = None,
    insiders_rows: list[dict] | None = None,
) -> list[SignalResult]:
    """Tous les signaux de tous les exercices d'une entreprise.

    Chaque SignalResult porte period_end + filing_id (traçabilité) ;
    None renvoyé par un module = signal absent pour l'exercice (jamais de
    valeur de substitution). Le composite est dérivé des sévérités de
    l'exercice une fois ses composants calculés.

    events : dépôts 8-K/NT (repo.fetch_event_rows / edgar.submissions).
      - None  = événements non chargés (anciens appels, tests isolés) :
        les signaux d'événements sont OMIS plutôt qu'affichés « 0 » (un
        zéro affirme avoir vérifié — ce serait un faux score) ;
      - []    = chargés, aucun événement : signaux « saine » émis pour la
        continuité des courbes.

    insiders_rows : transactions Form 4 (repo.fetch_insider_rows) — même
      contrat None/[] que events (signal insider_sales).
    """
    years = build_years(rows)
    if not years:
        return []

    # Flottants à plat, triés : reprise du « dernier flottant ≤ bilan ».
    floats = sorted(
        (node["period_end"], node["value"])
        for year_node in years.values()
        for concept, node in year_node.items()
        if concept == "public_float"
    )
    prices = sorted(prices)

    # L'écart bénéfice/cash a besoin de l'historique complet (streak) :
    # il reçoit directement les nœuds (value, period_end, filing_id).
    divergences = divergence.evaluate_history(years)

    # Événements -> exercices : toutes les dates de bilan connues servent
    # d'échelle de rattachement (report_date privilégié, cf. events.py).
    events_by_year: dict[int, list[dict]] = {}
    insiders_by_year: dict[int, list[dict]] = {}
    all_period_ends = sorted(
        {node["period_end"] for y in years.values() for node in y.values()}
    )
    if events is not None:
        events_by_year, _dropped = assign_to_years(events, all_period_ends)
    if insiders_rows is not None:
        # Même échelle de rattachement que les 8-K : ancre = date de la
        # transaction (report_date du dict), sinon date de dépôt.
        tx_like = [
            {**t, "report_date": t["transaction_date"],
             "filed_at": t.get("filed_at") or t["transaction_date"]}
            for t in insiders_rows
        ]
        insiders_by_year, _dropped = assign_to_years(tx_like, all_period_ends)

    results: list[SignalResult] = []
    for year in sorted(years):
        cur = years[year]
        period_end, filing_id = _meta(cur)
        if period_end is None:
            continue
        cur_v = {c: n["value"] for c, n in cur.items()}

        year_results: list[SignalResult] = []

        # --- Altman ---------------------------------------------------------
        cap, cap_source = market_capitalisation(cur, floats, prices)
        ca, cl = _v(cur, "current_assets"), _v(cur, "current_liabilities")
        wc = (ca - cl) if (ca is not None and cl is not None) else None
        res = altman.evaluate(
            working_capital=wc,
            total_assets=_v(cur, "total_assets"),
            retained_earnings=_v(cur, "retained_earnings"),
            ebit=_v(cur, "operating_income"),
            market_capitalisation=cap,
            total_liabilities=_v(cur, "total_liabilities"),
            sales=_v(cur, "sales"),
            period_end=period_end,
            filing_id=filing_id,
        )
        if res:
            # Traçabilité du D : capitalisation + provenance du calcul,
            # pour que l'affichage montre d'où vient la composante boursière
            # (pas un dépôt SEC, mais un cours — cf. source dans details).
            res.details["market_capitalisation"] = cap
            res.details["cap_source"] = cap_source
            year_results.append(res)

        # --- Piotroski + Beneish (nécessitent l'exercice précédent) --------
        prev = years.get(year - 1)
        if prev:
            prev_v = {c: n["value"] for c, n in prev.items()}
            res = piotroski.evaluate(prev_v, cur_v, period_end, filing_id)
            if res:
                year_results.append(res)
            res = beneish.evaluate(prev_v, cur_v, period_end, filing_id)
            if res:
                year_results.append(res)

        # --- Runway ---------------------------------------------------------
        res = runway.evaluate(_v(cur, "cash"), _v(cur, "cfo"), period_end, filing_id)
        if res:
            year_results.append(res)

        # --- Écart bénéfice/cash (streak sur plusieurs exercices) ----------
        if year in divergences:
            year_results.append(divergences[year])

        # --- Événements (dépôts 8-K / NT, §2 signaux d'événements) --------
        if events is not None:
            year_events = events_by_year.get(year, [])
            nt_rows = [e for e in year_events if e["form"].startswith("NT")]
            k8_rows = [e for e in year_events if e["form"].startswith("8-K")]
            year_results.append(
                evaluate_late_filing(nt_rows, period_end, filing_id)
            )
            year_results.append(
                evaluate_critical_8k(k8_rows, period_end, filing_id)
            )

        # --- Ventes de dirigeants (Form 4, §2 « ventes massives ») -------
        # cap (capitalisation) et shares_outstanding sont déjà calculés
        # pour Altman : le signal insiders réutilise les MÊMES valeurs —
        # un seul miroir de la chaîne de repli de valorisation.
        if insiders_rows is not None:
            year_txs = insiders_by_year.get(year, [])
            sales = [t for t in year_txs if is_open_sale(t)]
            res = insiders.evaluate(
                sales,
                market_capitalisation=cap,
                shares_outstanding=_v(cur, "shares_outstanding"),
                period_end=period_end,
                filing_id=filing_id,
            )
            if res:
                year_results.append(res)

        # --- Composite : niveau global de l'exercice ------------------------
        severities = {r.signal_type: r.severity for r in year_results}
        compo = composite.evaluate(severities, period_end)
        if compo:
            year_results.append(compo)

        results.extend(year_results)

    return results
