"""Configuration centrale de l'application.

`pydantic_settings.BaseSettings` fusionne, par ordre de priorité :
  1. les variables d'environnement réelles (shell, CI, etc.)
  2. les valeurs lues depuis le fichier `.env` nommé dans `model_config`
     — pydantic-settings v2 ne lit PAS `.env` tant que ce n'est pas déclaré
     explicitement ci-dessous (un ValidationError « Field required » à
     l'import signale que cette config ou le fichier `.env` manque)
  3. les valeurs par défaut déclarées ci-dessous.

Correspondance des noms (insensible à la casse) :
  `database_url` <- `DATABASE_URL`, `sec_user_agent` <- `SEC_USER_AGENT`.

IMPORTANT : `settings = Settings()` s'exécute au moment de l'IMPORT. Si
`.env` est absent et que les variables ne sont pas exportées, chaque module
faisant `from app.config import settings` PLANTE avec une ValidationError
pydantic. C'est volontaire : échouer vite au démarrage plutôt que de
découvrir le problème à la première requête SEC. `.env` doit exister
(copier `.env.example`).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Indique le fichier `.env` à la racine du projet. Chemin RELATIF au
    # répertoire de travail : toujours lancer les commandes depuis la racine
    # (uv run, uvicorn). utf-8 parce que SEC_USER_AGENT contient des accents
    # (Prénom).
    # extra="ignore" : le `.env` est PARTAGÉ avec le frontend
    # (NEXT_PUBLIC_API_URL) et pydantic-settings v2 rejette les clés
    # inconnues par défaut — sans cette option, Settings() plante dès qu'une
    # variable non backend apparaît.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DSN utilisé par app/db/repo.py, ex. postgresql://risk:risk@localhost:5435/risks
    # Port 5435 : docker-compose publie 5435 (5432 est pris par un autre
    # conteneur local fa_pg_sql).
    database_url: str

    # REQUIS par les conditions d'accès à la SEC EDGAR : « nom + e-mail »
    # dans le User-Agent, sinon les requêtes sont bloquées. Renseigner une
    # adresse réelle dans `.env` avant la phase 0.
    sec_user_agent: str

    # Où les réponses EDGAR brutes sont mises en cache sur disque (gitignoré).
    cache_dir: str = "data/cache"


# Instance unique au niveau module : une seule source de vérité pour toute
# l'application. Ne jamais lire os.environ["DATABASE_URL"] ailleurs — les
# valeurs de `.env` sont visibles par pydantic mais PAS par os.environ.
settings = Settings()
