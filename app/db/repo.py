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
                  filed_at: str, url: str) -> str:
    """Insère ou met à jour un dépôt, renvoie son id (uuid).

    Clé de conflit : `accession` (numéro d'inscription unique SEC).
    `filed_at` = date ISO 'YYYY-MM-DD' (castée par Postgres en date).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filings (company_id, accession, form_type, filed_at, url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (accession) DO UPDATE SET
                form_type = EXCLUDED.form_type,
                filed_at = EXCLUDED.filed_at,
                url = EXCLUDED.url
            RETURNING id
            """,
            (company_id, accession, form_type, filed_at, url),
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
