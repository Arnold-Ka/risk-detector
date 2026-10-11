"""Application FastAPI — la couche HTTP du backend.

Périmètre (feuille de route §4) : API JSON uniquement. Les pages sont
rendues par le frontend Next.js (`frontend/`), qui appelle ces endpoints.
Le backend ne rend jamais de HTML lui-même.
"""

from fastapi import FastAPI, HTTPException

# `title` apparaît dans la documentation auto-générée (/docs et /redoc) —
# utile pour tester les endpoints à la main tant que le frontend n'existe pas.
app = FastAPI(title="Risk Detector API")


@app.get("/health")
def health():
    """Sonde de vivacité (liveness).

    Utilisée par les vérifications de type docker --wait, par le frontend et
    par nous-mêmes pour répondre « l'API est-elle levée ? » sans toucher à la
    base de données. Délibérément SANS requête Postgres : santé = le processus
    répond, la disponibilité de la DB se vérifie ailleurs (docker compose ps
    du service db).
    """
    return {"status": "ok"}


@app.get("/companies/{cik}")
def get_company(cik: int):
    """Fiche de risque d'une entreprise, identifiée par son CIK SEC.

    501 = « implémenté plus tard, volontairement ». On renvoie une erreur
    explicite plutôt qu'un objet vide car la règle produit est : afficher les
    données manquantes comme manquantes, jamais une fausse réponse
    (feuille de route §3 « donnée manquante »). À implémenter en phase 1,
    quand `companies` et `signals` seront peuplées.

    Note : un `def` simple (pas `async def`) suffit ici — FastAPI exécute les
    endpoints synchrones dans une threadpool, et les appels BDD en phase 1
    seront du psycopg bloquant : l'async n'apporterait rien.
    """
    raise HTTPException(status_code=501, detail="Not Implemented - Phase 1")
