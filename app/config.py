"""Central application configuration.

`pydantic_settings.BaseSettings` merges, in this order of precedence:
  1. real environment variables (e.g. set in the shell / CI)
  2. values read from the file named in `model_config["env_file"]`
     — pydantic-settings v2 does NOT load `.env` unless you declare it
     explicitly below (a ValidationError "Field required" at import time
     means this config line or the `.env` file is missing)
  3. the field defaults declared below.

Field name mapping is case-insensitive: `database_url` <- `DATABASE_URL`,
`sec_user_agent` <- `SEC_USER_AGENT`.

IMPORTANT: `settings = Settings()` runs at IMPORT time. If `.env` is missing
and the variables are not exported, every module that does
`from app.config import settings` will CRASH with a pydantic ValidationError.
That is deliberate: fail fast at startup instead of discovering the problem
on the first SEC request. `.env` must exist (copy `.env.example`).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Point at the repo-root `.env`. Relative to the process working
    # directory: always run commands from the repo root (uv run, uvicorn).
    # utf-8 because SEC_USER_AGENT contains accented characters (Prénom).
    # extra="ignore": the .env file is SHARED with the frontend
    # (NEXT_PUBLIC_API_URL) and pydantic-settings v2 rejects unknown keys
    # by default — without this, Settings() crashes on any non-backend var.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DSN used by app/db/repo.py, e.g. postgresql://risk:risk@localhost:5435/risks
    # Port 5435: docker-compose publishes 5435 (5432 is taken by another local container).
    database_url: str

    # REQUIRED by SEC EDGAR's terms of access: "name + email" in the User-Agent,
    # or requests get blocked. Set a real address in `.env` before phase 0.
    sec_user_agent: str

    # Where raw EDGAR responses are cached on disk (gitignored).
    cache_dir: str = "data/cache"


# Single module-level instance: one source of truth for the whole app.
# Never read os.environ["DATABASE_URL"] directly elsewhere — `.env` values are
# visible to pydantic but NOT to os.environ.
settings = Settings()
