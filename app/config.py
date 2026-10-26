"""Configuration centrale de l'application.

`pydantic_settings.BaseSettings` fusionne, par ordre de priorité :
  1. les variables d'environnement réelles (shell, CI, etc.)
  2. les valeurs lues depuis le fichier `.env` nommé dans `model_config`
     — pydantic-settings v2 ne lit PAS `.env` tant que ce n'est pas déclaré
     explicitement ci-dessous
  3. les valeurs par défaut déclarées ci-dessous.

Correspondance des noms (insensible à la casse) :
  `database_url` <- `DATABASE_URL`, `sec_user_agent` <- `SEC_USER_AGENT`.

IMPORTANT : `settings = Settings()` s'exécute au moment de l'IMPORT. Si
`.env` est absent et que les variables ne sont pas exportées, chaque module
faisant `from app.config import settings` PLANTE avec une ValidationError —
ma message personnalisé, grâce au model_validator ci-dessous. C'est
volontaire : échouer vite au démarrage plutôt que de découvrir le problème
à la première requête SEC. `.env` doit exister (copier `.env.example`).

NOTE ANALYSE STATIQUE : les champs ont des défauts vides (`= ""`) pour que
Pylance/PyRight considère `Settings()` comme un appel valide (pydantic
remplit tout depuis `.env` à l'exécution, ce qu'un analyseur statique ne
sait pas modéliser). Le contrôle « la variable est bien là » est délégué au
model_validator — l'échec rapide est conservé.
"""

from pydantic import model_validator
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
    # Défaut vide pour l'analyse statique ; le contrôle réel est dans
    # _check_required_env ci-dessous.
    database_url: str = ""

    # REQUIS par les conditions d'accès à la SEC EDGAR : « nom + e-mail »
    # dans le User-Agent, sinon les requêtes sont bloquées. Renseigner une
    # adresse réelle dans `.env` avant la phase 0.
    # Défaut vide pour l'analyse statique ; le contrôle réel est dans
    # _check_required_env ci-dessous.
    sec_user_agent: str = ""

    # Où les réponses EDGAR brutes sont mises en cache sur disque (gitignoré).
    cache_dir: str = "data/cache"

    # Origines Next.js autorisées à appeler l'API depuis le navigateur.
    frontend_origins: str = "http://localhost:3000"

    # Secret serveur-à-serveur : seul le BFF Next.js peut appeler les routes
    # privées de liste de suivi. Ne jamais préfixer cette variable NEXT_PUBLIC_.
    watchlist_api_secret: str = ""

    # Alertes e-mail du nightly (app/alerts/mailer.py). Envoi désactivé tant
    # que smtp_host OU alert_from_email est vide : le job journalise alors
    # les changements sans rien envoyer (local, CI). Port 465 = TLS
    # implicite, tout autre port = STARTTLS (587 chez la plupart des relais).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    # Expéditeur, ex. "Détecteur de risque <alertes@mondomaine.fr>" : le
    # domaine doit être vérifié chez le fournisseur (SPF/DKIM), sinon les
    # messages finissent en spam.
    alert_from_email: str = ""
    # URL publique du site Next (liens des e-mails) — même valeur que
    # NEXT_PUBLIC_SITE_URL côté frontend.
    site_url: str = "http://localhost:3000"

    @model_validator(mode="after")
    def _check_required_env(self) -> "Settings":
        """Échec explicite au démarrage si une variable manque dans .env.

        Remplace les champs « required » de pydantic : même protection
        (ValidationError à l'import), mais message actionnable en français,
        et des paramètres optionnels pour Pylance/PyRight.
        """
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL manquant — copier .env.example vers .env "
                "et renseigner la chaîne de connexion PostgreSQL"
            )
        if not self.sec_user_agent:
            raise ValueError(
                "SEC_USER_AGENT manquant — la SEC exige nom + e-mail "
                "réels dans le User-Agent (voir .env.example)"
            )
        return self


# Instance unique au niveau module : une seule source de vérité pour toute
# l'application. Ne jamais lire os.environ["DATABASE_URL"] ailleurs — les
# valeurs de `.env` sont visibles par pydantic mais PAS par os.environ.
settings = Settings()
