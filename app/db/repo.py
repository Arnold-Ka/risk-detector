"""Couche d'accès à la base de données (fine, SQL brut volontairement).

Pourquoi pas d'ORM (pour l'instant) : le principe produit nº1 de la feuille
de route est la traçabilité — chaque score affiché doit montrer les chiffres
exacts et le dépôt dont il vient. Le SQL explicite garde cette correspondance
évidente. Réévaluer (SQLAlchemy/Alembic) uniquement quand le schéma bougera
régulièrement en production.

Le schéma vit dans `app/db/schema.sql`, appliqué automatiquement par le
montage docker-entrypoint-initdb.d au PREMIER démarrage d'un volume vierge
(`docker compose down -v` pour rejouer en dev).
"""

import psycopg
import uuid

from app.config import settings


def get_conn():
    """Ouvre une connexion psycopg à partir du DSN configuré.

    - Utilise `settings.database_url` (pydantic-settings) et non
      `os.environ["DATABASE_URL"]` : ce dernier ignore les valeurs de
      `.env`, que seul pydantic voit. Lire os.environ est un piège classique
      « ça marche en CI, ça plante en local ».
    - psycopg.connect() est LAZY : il construit l'objet connexion et ne
      compose réellement avec le serveur qu'au premier query/commit.
    - La connexion appartient à l'appelant : `with get_conn() as conn:`
      la ferme à la sortie (ou appeler .close()). Pas de pool de connexions
      pour l'instant — suffisant pour des jobs batchs de nuit ; ajouter
      psycopg_pool quand l'API servira du trafic.
    - ATTENTION psycopg3 : le context manager `with connexion` ne COMMITTE
      pas à la sortie (il ferme, donc annule une transaction non terminée).
      L'appelant doit appeler `conn.commit()` explicitement.
    """
    return psycopg.connect(settings.database_url)


# --- Écritures du pipeline d'ingestion (phase 1) ----------------------------
# Toutes en ON CONFLICT : le job d'ingestion est idempotent, on le relance
# sans crainte de doublon (règle « rejouable » de la feuille de route).


def upsert_company(conn, cik: int, name: str, ticker: str | None = None,
                   sector_group: str | None = None) -> str:
    """Insère ou met à jour une entreprise, renvoie son id (uuid).

    - clé de conflit : `cik` (identifiant permanent SEC — jamais de doublon) ;
    - `name` : toujours écrasé, la source de vérité = la SEC (entityName du
      dernier dépôt) ;
    - `ticker`/`sector_group` : None = « je ne touche pas » (COALESCE) —
      on ne peut pas écraser un secteur corrigé à la main par un
      re-import avec la valeur par défaut 'other'.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO companies (cik, name, ticker, sector_group)
            VALUES (%s, %s, %s, COALESCE(%s, 'other'))
            ON CONFLICT (cik) DO UPDATE SET
                name = EXCLUDED.name,
                ticker = COALESCE(EXCLUDED.ticker, companies.ticker),
                sector_group = COALESCE(EXCLUDED.sector_group, companies.sector_group)
            RETURNING id
            """,
            (cik, name, ticker, sector_group),
        )
        return cur.fetchone()[0]


def upsert_filing(conn, company_id: str, accession: str, form_type: str,
                  filed_at: str, url: str, items: str | None = None,
                  report_date: str | None = None) -> str:
    """Insère ou met à jour un dépôt, renvoie son id (uuid).

    Clé de conflit : `accession` (numéro d'inscription unique SEC).
    `filed_at` = date ISO 'YYYY-MM-DD' (castée par Postgres en date).
    `items` / `report_date` : enrichissement événementiel (8-K, NT) venu
    des submissions — COALESCE côté conflit pour ne pas écraser une valeur
    déjà connue par un ré-ingest qui ne la fournit pas (10-K de facts).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filings
                (company_id, accession, form_type, filed_at, url, items, report_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession) DO UPDATE SET
                form_type = EXCLUDED.form_type,
                filed_at = EXCLUDED.filed_at,
                url = EXCLUDED.url,
                items = COALESCE(EXCLUDED.items, filings.items),
                report_date = COALESCE(EXCLUDED.report_date, filings.report_date)
            RETURNING id
            """,
            (company_id, accession, form_type, filed_at, url, items, report_date),
        )
        return cur.fetchone()[0]


def upsert_facts(conn, company_id: str, rows: list[dict]) -> int:
    """Ingestion batch des faits normalisés d'une entreprise.

    `rows` = sorties de app.normalize.loader.extract enrichies de
    `filing_id` et `fiscal_year` par l'appelant. Clé de conflit :
    (company_id, concept, period_end) — voir schema.sql. La valeur et le
    dépôt source sont mis à jour ensemble : on garde toujours le couple
    « chiffre + filing dont il vient » cohérent (traçabilité nº1).
    Renvoie le nombre de lignes traitées.
    """
    stmt = """
        INSERT INTO facts (company_id, filing_id, concept, value, period_end, fiscal_year)
        VALUES (%(company_id)s, %(filing_id)s, %(concept)s, %(value)s,
                %(period_end)s, %(fiscal_year)s)
        ON CONFLICT (company_id, concept, period_end) DO UPDATE SET
            filing_id = EXCLUDED.filing_id,
            value = EXCLUDED.value,
            fiscal_year = EXCLUDED.fiscal_year
    """
    with conn.cursor() as cur:
        cur.executemany(stmt, rows)
    return len(rows)


def delete_facts(conn, company_id: str) -> int:
    """Supprime TOUS les faits d'une entreprise, renvoie le nombre de lignes.

    À appeler AVANT upsert_facts dans une même transaction : l'upsert seul
    ne touche que les clés présentes dans le nouveau lot — quand une règle
    d'extraction change (vote de millésime, tag retiré du YAML), les faits
    de l'ancien lot resteraient en base à côté des nouveaux (on l'a mesuré :
    2 lignes périmées après le passage au vote de millésimes). Le couple
    purge + réinsertion fait de l'ingestion un vrai REMPLACEMENT reproductible.
    Les dépôts (filings) ne sont pas purgés : ils servent aussi d'historique
    des dépôts vus et n'ont pas de clé d'unicité par lot.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM facts WHERE company_id = %s", (company_id,))
        return cur.rowcount


def upsert_prices(conn, company_id: str, rows: list[tuple[str, float]]) -> int:
    """Ingestion batch (date ISO, cours) — clé primaire (company_id, date)."""
    stmt = """
        INSERT INTO prices (company_id, date, close)
        VALUES (%s, %s, %s)
        ON CONFLICT (company_id, date) DO UPDATE SET close = EXCLUDED.close
    """
    with conn.cursor() as cur:
        cur.executemany(stmt, [(company_id, d, c) for d, c in rows])
    return len(rows)


# --- Lectures (job nocturne + API) ------------------------------------------
# Le job nocturne EST le seul écrivain des signaux ; l'API ne fait que
# lire ces fonctions (règle « pré-calculer la nuit, l'API lit »).


def list_companies(conn) -> list[dict]:
    """Toutes les entreprises suivies (id, cik, nom, ticker, secteur)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, cik, name, ticker, sector_group FROM companies ORDER BY cik"
        )
        cols = ("id", "cik", "name", "ticker", "sector_group")
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_company(conn, cik: int) -> dict | None:
    """Entreprise par CIK SEC, ou None (l'API répondra 404)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, cik, name, ticker, sector_group FROM companies WHERE cik = %s",
            (cik,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = ("id", "cik", "name", "ticker", "sector_group")
        return dict(zip(cols, row))


def search_companies(conn, query: str, limit: int = 10) -> list[dict]:
    """Recherche par nom, symbole ou CIK (feuille de route §9).

    - nom/ticker : ILIKE partiel, jokers % et _ de l'utilisateur échappés
      (sinon une requête « _ » listerait tout) ;
    - si la requête ne contient que des chiffres, c'est un CIK : comparaison
      exacte en plus (un CIK ne fait « parti » de rien) ;
    - `level` = dernier score composite connu (niveau global) pour afficher
      le risque directement dans les résultats de recherche ; NULL si
      l'entreprise n'a pas encore été scorée (jamais de niveau inventé).
    """
    # Jokers ILIKE de l'entrée utilisateur échappés AVANT d'ajouter les
    # nôtres (échappés après, on neutraliserait nos propres % — bug déjà
    # commis : la recherche rendait toujours vide). Backslash = escape par
    # défaut sous PostgreSQL.
    safe = (
        query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    pattern = f"%{safe}%"
    params: list = [pattern, pattern]
    if query.isdigit():
        where = "(c.name ILIKE %s OR c.ticker ILIKE %s OR c.cik = %s)"
        params.append(int(query))
    else:
        where = "(c.name ILIKE %s OR c.ticker ILIKE %s)"
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.cik, c.name, c.ticker, c.sector_group, s.severity
            FROM companies c
            LEFT JOIN LATERAL (
                SELECT sg.severity FROM signals sg
                WHERE sg.company_id = c.id AND sg.signal_type = 'composite'
                ORDER BY sg.period_end DESC LIMIT 1
            ) s ON true
            WHERE {where}
            ORDER BY c.name
            LIMIT %s
            """,
            params,
        )
        cols = ("cik", "name", "ticker", "sector_group", "level")
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def list_coverage_companies(
    conn, query: str = "", limit: int = 50, offset: int = 0
) -> dict:
    """Page d'annuaire sur les entreprises effectivement présentes en base.

    Le statut distingue « score disponible » de « fiche chargée » ; la liste
    ne prétend pas représenter toutes les sociétés cotées américaines.
    """
    where = ""
    filter_params: list = []
    cleaned = query.strip()
    if cleaned:
        safe = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{safe}%"
        if cleaned.isdigit():
            where = "WHERE (c.cik = %s OR c.name ILIKE %s OR c.ticker ILIKE %s)"
            filter_params.extend((int(cleaned), pattern, pattern))
        else:
            where = "WHERE (c.name ILIKE %s OR c.ticker ILIKE %s)"
            filter_params.extend((pattern, pattern))

    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM companies c {where}", filter_params)
        total = cur.fetchone()[0]
        cur.execute(
            f"""
            WITH page_companies AS MATERIALIZED (
                SELECT c.id, c.cik, c.name, c.ticker, c.sector_group
                FROM companies c
                {where}
                ORDER BY c.name, c.cik
                LIMIT %s OFFSET %s
            )
            SELECT c.cik, c.name, c.ticker, c.sector_group,
                   latest.severity, latest.period_end, latest.computed_at,
                   latest.details
            FROM page_companies c
            LEFT JOIN LATERAL (
                SELECT severity, period_end, computed_at, details
                FROM signals
                WHERE company_id = c.id AND signal_type = 'composite'
                ORDER BY period_end DESC, computed_at DESC
                LIMIT 1
            ) latest ON true
            ORDER BY c.name, c.cik
            """,
            [*filter_params, limit, offset],
        )
        rows = cur.fetchall()

    items = []
    for row in rows:
        (
            cik,
            name,
            ticker,
            sector_group,
            level,
            period_end,
            computed_at,
            details,
        ) = row
        missing = details.get("absent", []) if isinstance(details, dict) else []
        if sector_group in {"bank", "insurance", "reit"}:
            status = "not_comparable"
        elif level is None:
            status = "not_scored"
        elif missing:
            status = "partial"
        else:
            status = "scored"
        items.append(
            {
                "cik": cik,
                "name": name,
                "ticker": ticker,
                "sector_group": sector_group,
                "status": status,
                "level": level if status not in {"not_comparable", "not_scored"} else None,
                "period_end": (
                    period_end.isoformat()
                    if period_end and status != "not_comparable"
                    else None
                ),
                "computed_at": (
                    computed_at.isoformat()
                    if computed_at and status != "not_comparable"
                    else None
                ),
                "available_components": (
                    len(details.get("components", {}))
                    if isinstance(details, dict)
                    and isinstance(details.get("components"), dict)
                    else 0
                ),
                "missing_components": len(missing) if isinstance(missing, list) else 0,
            }
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def fetch_fact_rows(conn, company_id: str) -> list[dict]:
    """Tous les faits normalisés d'une entreprise, triés par date de fin.

    Forme d'entrée de app.signals.compute.compute_company. Le tri
    period_end croissant est ce qui fait gagner la date la plus tardive
    par année civile dans build_years (règle AMC 2018-01-01 vs 12-31).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT concept, value, period_end, fiscal_year, filing_id
            FROM facts WHERE company_id = %s ORDER BY period_end
            """,
            (company_id,),
        )
        return [
            {
                "concept": r[0],
                "value": float(r[1]),
                "period_end": r[2].isoformat(),
                "fiscal_year": r[3],
                "filing_id": str(r[4]) if r[4] else None,
            }
            for r in cur.fetchall()
        ]


def fetch_price_rows(conn, company_id: str) -> list[tuple[str, float]]:
    """[(date ISO, cours)] pour la composante D (capitalisation)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, close FROM prices WHERE company_id = %s ORDER BY date",
            (company_id,),
        )
        return [(r[0].isoformat(), float(r[1])) for r in cur.fetchall()]


def fetch_event_rows(conn, company_id: str) -> list[dict]:
    """Dépôts porteurs d'événements (8-K items + NT de retard), triés.

    Alimente app.signals.events : un 8-K critique (items 1.03/2.04/4.01/
    4.02/5.02) ou un NT 10-K/10-Q = signaux d'événements du §2. Chaque
    ligne garde filing_id : tout score d'événement doit rester tracé jusqu'au
    dépôt source.
    """
    with conn.cursor() as cur:
        cur.execute(
            # %% = % littéral : psycopg3 parse les % de la requête quand des
            # paramètres sont passés (LIKE '8-K%' devrait fuir sinon).
            """
            SELECT id, accession, form_type, filed_at, items, report_date
            FROM filings
            WHERE company_id = %s
              AND (form_type LIKE '8-K%%' OR form_type LIKE 'NT%%')
            ORDER BY filed_at
            """,
            (company_id,),
        )
        return [
            {
                "filing_id": str(r[0]),
                "accession": r[1],
                "form": r[2],
                "filed_at": r[3].isoformat(),
                "items": r[4],
                # report_date peut être NULL (SEC facultatif) : le mapping
                # vers l'exercice retombe sur filed_at.
                "report_date": r[5].isoformat() if r[5] else None,
            }
            for r in cur.fetchall()
        ]


def upsert_insider_transactions(conn, company_id: str, rows: list[dict]) -> int:
    """Ingestion batch des transactions Form 4 d'une entreprise.

    `rows` : lignes prêtes (déjà rattachées à leur filing_id) —
    {filing_id, transaction_date, code, acquired_disposed, shares, price,
     owner_name, is_officer, is_director, officer_title, plan_10b5_1}.
    ON CONFLICT DO NOTHING sur la clé d'idempotence du schéma : un
    re-jeu de scripts/load_form4 est sans effet. Retourne le nombre de
    lignes réellement insérées.
    """
    if not rows:
        return 0
    cols = (
        "company_id", "filing_id", "transaction_date", "code",
        "acquired_disposed", "shares", "price", "owner_name",
        "is_officer", "is_director", "officer_title", "plan_10b5_1",
    )
    with conn.cursor() as cur:
        # Un seul INSERT multi-lignes par paquet : cur.rowcount est alors
        # exact (executemany ne garantit pas le compte total en psycopg3).
        inserted = 0
        for start in range(0, len(rows), 1000):
            chunk = rows[start : start + 1000]
            values = ", ".join(
                "(" + ", ".join("%s" for _ in cols) + ")" for _ in chunk
            )
            all_params: list = []
            for r in chunk:
                all_params.append(company_id)
                all_params.extend(
                    [r["filing_id"], r["transaction_date"], r.get("code"),
                     r.get("acquired_disposed"), r.get("shares"), r.get("price"),
                     r.get("owner_name"), bool(r.get("is_officer")),
                     bool(r.get("is_director")), r.get("officer_title"),
                     bool(r.get("plan_10b5_1"))]
                )
            cur.execute(
                f"""
                INSERT INTO insider_transactions ({', '.join(cols)})
                VALUES {values}
                ON CONFLICT DO NOTHING
                """,
                all_params,
            )
            inserted += cur.rowcount
        return inserted


def has_form4_filings(conn, company_id: str) -> bool:
    """True si des dépôts Form 4 sont en base pour cette entreprise.

    Sert au contrat None/[] du signal insiders : la table
    `insider_transactions` ne contient QUE les entreprises passées par
    scripts/load_form4 — sans dépôt Form 4, un [] serait un mensonge
    (« on a vérifié, aucune vente ») alors que les Form 4 n'ont jamais
    été téléchargés.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM filings "
            "WHERE company_id = %s AND form_type = '4')",
            (company_id,),
        )
        return bool(cur.fetchone()[0])


def fetch_accessions(conn, company_id: str) -> set[str]:
    """Numéros d'inscription déjà en base pour cette entreprise.

    Le job nocturne incrémental compare cette collection aux dépôts
    récents EDGAR (page submissions `recent`) pour ne re-ingérer QUE ce
    qui est nouveau — une passe complète à chaque nuit serait du gâchis
    réseau pour 99,9 % de doublons.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT accession FROM filings WHERE company_id = %s", (company_id,))
        return {row[0] for row in cur.fetchall()}


def fetch_balance_dates(conn, company_id: str) -> list[str]:
    """Dates de fin de période distinctes des faits (repères de valorisation).

    Le refresh nocturne des cours cherche « dernier cours ≤ chaque date de
    bilan » — ces dates viennent des faits eux-mêmes (pas du cache CSV),
    donc la table `prices` se remplit toujours à la bonne hauteur.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT period_end FROM facts "
            "WHERE company_id = %s ORDER BY period_end",
            (company_id,),
        )
        return [row[0].isoformat() for row in cur.fetchall()]


def latest_form_filed_at(conn, company_id: str, form_type: str) -> str | None:
    """Date de dépôt la plus récente d'un type de formulaire, ou None.

    Le refresh nocturne compare cette date à celle du dernier 10-K vu sur
    la page recent EDGAR : plus récent = un nouveau 10-K est tombé →
    re-télécharger companyfacts. Comparer les DATES (et non les
    accessions) évite le faux positif des 10-K dont extract() ne produit
    AUCUN fait (vintage perdant au vote, fenêtre de durée hors 300-400j) —
    ils n'apparaissent jamais dans `filings`, et une comparaison par
    accession les re-détecterait à chaque nuit.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(filed_at) FROM filings "
            "WHERE company_id = %s AND form_type = %s",
            (company_id, form_type),
        )
        row = cur.fetchone()[0]
        return row.isoformat() if row else None


def annual_forms_for_company(conn, company_id: str) -> tuple[str, ...]:
    """Formulaires annuels déjà observés pour choisir l'extracteur du nightly."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT form_type
            FROM filings
            WHERE company_id = %s AND form_type = ANY(%s)
            ORDER BY form_type
            """,
            (company_id, ["10-K", "20-F", "40-F"]),
        )
        return tuple(row[0] for row in cur.fetchall())


def latest_annual_filed_at(conn, company_id: str) -> str | None:
    """Date du dernier 10-K/20-F/40-F connu, ou None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT max(filed_at)
            FROM filings
            WHERE company_id = %s AND form_type = ANY(%s)
            """,
            (company_id, ["10-K", "20-F", "40-F"]),
        )
        row = cur.fetchone()[0]
        return row.isoformat() if row else None


def fetch_insider_rows(conn, company_id: str) -> list[dict]:
    """Transactions Form 4 d'une entreprise (alimente app.signals.insiders).

    Chaque ligne porte filing_id + filed_at (dépôt source, traçabilité)
    et `value` (colonne générée prix x quantité — NULL si prix absent).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.filing_id, t.transaction_date, t.code,
                   t.acquired_disposed, t.shares, t.price, t.value,
                   t.owner_name, t.is_officer, t.is_director, t.officer_title,
                   t.plan_10b5_1, f.filed_at
            FROM insider_transactions t
            LEFT JOIN filings f ON f.id = t.filing_id
            WHERE t.company_id = %s
            ORDER BY t.transaction_date
            """,
            (company_id,),
        )
        return [
            {
                "filing_id": str(r[0]) if r[0] else None,
                "transaction_date": r[1].isoformat(),
                "code": r[2],
                "acquired_disposed": r[3],
                "shares": float(r[4]) if r[4] is not None else None,
                "price": float(r[5]) if r[5] is not None else None,
                "value": float(r[6]) if r[6] is not None else None,
                "owner_name": r[7],
                "is_officer": r[8],
                "is_director": r[9],
                "officer_title": r[10],
                "plan_10b5_1": r[11],
                "filed_at": r[12].isoformat() if r[12] else None,
            }
            for r in cur.fetchall()
        ]


def latest_signals(conn, company_id: str) -> list[dict]:
    """Dernier signal de chaque type (la fiche de risque « aujourd'hui »).

    DISTINCT ON = idiom Postgres : une ligne par signal_type, celle du
    period_end le plus récent. LEFT JOIN filings : chaque score doit
    pouvoir pointer vers son dépôt source (feuille de route §9 — lien
    vers chaque dépôt source ; composite sans filing_id -> url NULL).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (s.signal_type)
                   s.signal_type, s.period_end, s.value, s.severity,
                   s.details, s.computed_at, s.filing_id, f.url
            FROM signals s
            LEFT JOIN filings f ON f.id = s.filing_id
            WHERE s.company_id = %s
            ORDER BY s.signal_type, s.period_end DESC
            """,
            (company_id,),
        )
        return [_signal_dict(r) for r in cur.fetchall()]


def signal_history(conn, company_id: str) -> list[dict]:
    """Historique complet, trié par exercice (graphiques + backtest)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.signal_type, s.period_end, s.value, s.severity,
                   s.details, s.computed_at, s.filing_id, f.url
            FROM signals s
            LEFT JOIN filings f ON f.id = s.filing_id
            WHERE s.company_id = %s
            ORDER BY s.period_end, s.signal_type
            """,
            (company_id,),
        )
        return [_signal_dict(r) for r in cur.fetchall()]


def _signal_dict(row) -> dict:
    """Ligne signals + url du dépôt -> dict JSON (details jsonb décodé).

    Les deux requêtes (latest/history) retournent les mêmes 8 colonnes ;
    filing_url est NULL pour le composite (qui dérive d'autres signaux).
    """
    (
        signal_type, period_end, value, severity,
        details, computed_at, filing_id, filing_url,
    ) = row
    return {
        "signal_type": signal_type,
        "period_end": period_end.isoformat(),
        "value": float(value) if value is not None else None,
        "severity": severity,
        "details": details,
        "computed_at": computed_at.isoformat(),
        "filing_id": str(filing_id) if filing_id else None,
        "filing_url": filing_url,
    }


# --- Écriture (job nocturne uniquement) --------------------------------------


def replace_company_signals(
    conn, company_id: str, rows: list[dict], computed_at: str
) -> int:
    """Remplace TOUS les signaux d'une entreprise (purge + insert, 1 transaction).

    Même logique que delete_facts : le job nocturne recalcule toute
    l'historique à chaque exécution ; upsert seul laisserait des lignes
    d'exercices disparus (règle d'extraction qui évolue). L'unicité
    (company_id, signal_type, period_end) empêche les doublons, la purge
    garantit l'absence de résidus. `rows` = SignalResult.to_row(...).
    Renvoie le nombre de lignes insérées.
    """
    stmt = """
        INSERT INTO signals (company_id, signal_type, period_end, value,
                             severity, details, computed_at, filing_id)
        VALUES (%(company_id)s, %(signal_type)s, %(period_end)s, %(value)s,
                %(severity)s, %(details)s, %(computed_at)s, %(filing_id)s)
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM signals WHERE company_id = %s", (company_id,))
        payload = [{**row, "computed_at": computed_at} for row in rows]
        if payload:
            # details (dict) -> jsonb : passage par le wrapper psycopg.
            from psycopg.types.json import Json

            for row in payload:
                row["details"] = Json(row["details"])
            cur.executemany(stmt, payload)
    return len(payload)


# --- Listes de suivi personnelles -------------------------------------------

MAX_WATCHLIST_SIZE = 10


def watchlist_user_id(clerk_subject: str) -> str:
    """UUID local déterministe associé au sujet vérifié par Clerk."""
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"urn:risk-detector:clerk:{clerk_subject}")
    )


def upsert_watchlist_user(conn, clerk_subject: str, email: str) -> str:
    """Crée ou retrouve l'utilisateur Clerk avec un UUID local stable.

    Le sujet Clerk est transmis uniquement par le serveur Next après
    validation de la session. L'UUID déterministe permet de réutiliser la
    FK existante de `watchlists` sans exposer l'identité du fournisseur.
    """
    user_id = uuid.UUID(watchlist_user_id(clerk_subject))
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (id, email)
            VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
            RETURNING id
            """,
            (user_id, email.strip()),
        )
        return str(cur.fetchone()[0])


def fetch_watchlist(conn, user_id: str) -> list[dict]:
    """Liste les entreprises suivies et leur dernier niveau composite."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.cik, c.name, c.ticker, w.added_at,
                   (SELECT s.severity
                    FROM signals s
                    WHERE s.company_id = c.id AND s.signal_type = 'composite'
                    ORDER BY s.period_end DESC, s.computed_at DESC
                    LIMIT 1) AS level
            FROM watchlists w
            JOIN companies c ON c.id = w.company_id
            WHERE w.user_id = %s
            ORDER BY w.added_at DESC, c.name
            """,
            (user_id,),
        )
        return [
            {
                "cik": cik,
                "name": name,
                "ticker": ticker,
                "added_at": added_at.isoformat(),
                "level": level,
            }
            for cik, name, ticker, added_at, level in cur.fetchall()
        ]


def add_watchlist_company(
    conn, user_id: str, company_id: str, limit: int = MAX_WATCHLIST_SIZE
) -> str:
    """Ajoute une entreprise, de façon idempotente et limitée par utilisateur.

    Le verrou sur la ligne utilisateur sérialise les ajouts concurrents et
    empêche de dépasser la limite de 10 éléments.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
        if cur.fetchone() is None:
            raise ValueError("Utilisateur de liste de suivi inexistant")

        cur.execute(
            "SELECT 1 FROM watchlists WHERE user_id = %s AND company_id = %s",
            (user_id, company_id),
        )
        if cur.fetchone() is not None:
            return "already_present"

        cur.execute("SELECT count(*) FROM watchlists WHERE user_id = %s", (user_id,))
        if cur.fetchone()[0] >= limit:
            return "limit_reached"

        cur.execute(
            "INSERT INTO watchlists (user_id, company_id) VALUES (%s, %s)",
            (user_id, company_id),
        )
        return "added"


def remove_watchlist_company(conn, user_id: str, company_id: str) -> bool:
    """Retire une entreprise de la liste de l'utilisateur courant."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM watchlists WHERE user_id = %s AND company_id = %s",
            (user_id, company_id),
        )
        return cur.rowcount > 0
