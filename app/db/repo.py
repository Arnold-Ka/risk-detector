"""Database access layer (thin, raw SQL on purpose).

Why no ORM (yet): the roadmap's #1 product principle is traceability —
every displayed score must show the exact numbers and filing it came from.
Explicit SQL keeps that mapping obvious. Revisit (SQLAlchemy/Alembic) only
when the schema starts changing regularly in production.

Schema lives in `app/db/schema.sql`, applied automatically by the
docker-entrypoint-initdb.d mount on the FIRST start of a fresh volume
(`docker compose down -v` to replay it in dev).
"""

import psycopg

from app.config import settings


def get_conn():
    """Open a psycopg connection from the configured DSN.

    - Uses `settings.database_url` (pydantic-settings) instead of
      `os.environ["DATABASE_URL"]`: the latter ignores `.env` values, which
      only pydantic sees. Reading os.environ is a classic "works in CI,
      crashes locally" trap here.
    - psycopg.connect() is LAZY: it builds the connection object and only
      really dials the server on the first query/commit.
    - The caller owns the connection: `with get_conn() as conn:` closes it
      on exit (or call .close()). There is no connection pool yet — fine for
      nightly batch jobs; add one (psycopg_pool) when the API serves traffic.
    """
    return psycopg.connect(settings.database_url)
