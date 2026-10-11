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
    """
    return psycopg.connect(settings.database_url)
