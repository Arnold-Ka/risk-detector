"""FastAPI application — the HTTP layer of the backend.

Scope (roadmap §4): JSON API only. Pages are rendered by the Next.js
frontend (`frontend/`), which calls these endpoints. The backend never
renders HTML itself.
"""

from fastapi import FastAPI, HTTPException

# `title` shows up in the auto-generated docs at /docs and /redoc —
# useful to test endpoints by hand while the frontend is not ready yet.
app = FastAPI(title="Risk Detector API")


@app.get("/health")
def health():
    """Liveness probe.

    Used by docker --wait style checks, the frontend, and us humans to answer
    "is the API up?" without touching the database. Deliberately does NOT
    query Postgres: health == process answers, DB readiness is checked
    separately (see docker compose ps for the db service).
    """
    return {"status": "ok"}


@app.get("/companies/{cik}")
def get_company(cik: int):
    """Risk sheet for one company, addressed by its SEC CIK identifier.

    501 = "implemented later, on purpose". We return an explicit error rather
    than an empty object because the product rule is: show missing data as
    missing data, never a fake/wrong answer (roadmap §3 "donnée manquante").
    To be implemented in phase 1 once `companies`/`signals` are populated.

    Note: plain `def` (not `async def`) is fine here — FastAPI runs sync
    endpoints in a threadpool, and DB calls in phase 1 are blocking psycopg
    anyway, so async would buy nothing.
    """
    raise HTTPException(status_code=501, detail="Not Implemented - Phase 1")
